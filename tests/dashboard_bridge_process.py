import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from backend.karpathys import client, emitter, outbox
from backend.lib import db


async def main():
    if urlsplit(client._KARPATHYS_URL).hostname not in {'127.0.0.1', 'localhost'}:
        raise RuntimeError('Contract helper only permits loopback receivers')
    phase, result_path = sys.argv[1:3]
    sid, lead_id = os.environ['CONTRACT_CALL_SID'], os.environ['CONTRACT_LEAD_ID']
    if phase == 'stage':
        assert await emitter.emit_turn_completed(sid, 'user', 'Please call tomorrow', turn_index=0)
        assert await emitter.emit_call_created(sid, {'lead': {'id': lead_id, 'owner_first_name': 'Synthetic seller'}})
        assert await emitter.emit_transcript_completed(sid, None, lead_id, 2, [{'speaker': 'SELLER', 'text': 'Please call tomorrow'}, {'speaker': 'SOPHIA', 'text': 'I can request a callback'}])
        assert await emitter.emit_call_completed(sid, 'WARM', 2, 60)
        assert await emitter.emit_call_ended(sid)
    result = await outbox.recover_events(20)
    health = db.dashboard_event_journal_health()
    Path(result_path).write_text(json.dumps({'recovery': result, 'health': health}))


if __name__ == '__main__':
    asyncio.run(main())
