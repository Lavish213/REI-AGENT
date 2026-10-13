from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.karpathys import client
from backend.lib import db
from backend.voice import agent
from pipecat.frames.frames import StartFrame, TranscriptionFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv('KARPATHYS_OUTBOX_PATH', str(tmp_path / 'voice.sqlite3'))
    monkeypatch.setattr(client, '_KARPATHYS_URL', 'https://dashboard.example.invalid')
    monkeypatch.setattr(client, '_KARPATHYS_SECRET', 'synthetic-only')


@pytest.mark.asyncio
async def test_final_transcript_is_checkpointed_before_local_database_failure(journal, monkeypatch):
    sid = 'local-database-failure'
    db.stage_dashboard_event('call', {'call_sid': sid}, client.delivery_target())
    context = SimpleNamespace(transcript_events=[{'role': 'user', 'content': 'Please call tomorrow'}, {'role': 'assistant', 'content': "I can request that callback"}], disposition='WARM', turn_count=1)
    monkeypatch.setattr(agent, '_persist_call_result', AsyncMock(side_effect=TimeoutError('local datastore unavailable')))
    await agent._handle_call_end(sid, {'lead': {'id': 'external-lead'}}, SimpleNamespace(messages=[]), context)
    root = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(root['event_id'], root['lease'], {'persisted': True, 'schema_version': 1, 'receipt_id': 'r', 'call_sid': sid})
    transcript = db.claim_dashboard_event(client.delivery_target())
    assert transcript['endpoint'] == 'transcript'
    assert [chunk['text'] for chunk in transcript['payload']['chunks']] == ['Please call tomorrow', 'I can request that callback']
    db.finish_dashboard_event(transcript['event_id'], transcript['lease'], {'persisted': True, 'schema_version': 1, 'receipt_id': 'r2', 'call_sid': sid})
    assert db.claim_dashboard_event(client.delivery_target())['endpoint'] == 'complete'


@pytest.mark.asyncio
async def test_assistant_and_seller_frames_both_reach_persistent_journal(journal):
    context = agent.CallContext()
    context._call_sid = 'two-sided-call'
    user = agent.TranscriptJournal(context, 'user')
    assistant = agent.TranscriptJournal(context, 'assistant')
    user.push_frame = AsyncMock()
    assistant.push_frame = AsyncMock()
    await user.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
    await assistant.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
    await user.process_frame(TranscriptionFrame('Hello', '', ''), FrameDirection.DOWNSTREAM)
    await assistant.process_frame(TTSTextFrame('Hi, I am an AI assistant', 'sentence'), FrameDirection.DOWNSTREAM)
    await assistant.process_frame(TTSTextFrame('How can I help?', 'sentence'), FrameDirection.DOWNSTREAM)
    assert db.dashboard_event_journal_health()['pending'] == 3
    db.stage_dashboard_event('call', {'call_sid': 'two-sided-call'}, client.delivery_target())
    root = db.claim_dashboard_event(client.delivery_target())
    db.finish_dashboard_event(root['event_id'], root['lease'], {'persisted': True, 'schema_version': 1, 'receipt_id': 'r', 'call_sid': 'two-sided-call'})
    turns = []
    for index in range(3):
        event = db.claim_dashboard_event(client.delivery_target())
        turns.append(event['payload'])
        db.finish_dashboard_event(event['event_id'], event['lease'], {'persisted': True, 'schema_version': 1, 'receipt_id': f'r{index}', 'call_sid': 'two-sided-call'})
    assert [turn['speaker'] for turn in turns] == ['user', 'assistant', 'assistant']
    assert [turn['turn_index'] for turn in turns] == [0, 1, 2]
    await user.cleanup()
    await assistant.cleanup()
