from __future__ import annotations
from datetime import datetime, timezone
import math
from loguru import logger

_PHASE_TO_STAGE = {'VERIFY': 'STAGE_1_QUALIFY', 'LIGHT_DISCOVERY': 'STAGE_2_DISCOVER', 'QUALIFY': 'STAGE_3_PRECLOSE', 'NEXT_STEP': 'STAGE_4_CLOSE', 'WRAP': 'STAGE_5_WRAP'}
_BOXES = {'right_person', 'property_confirmed', 'identity', 'occupancy', 'condition', 'timeline', 'motivation', 'next_step', 'none'}
_MOODS = {'unknown', 'guarded', 'open', 'skeptical', 'distressed', 'motivated'}


def _text(value, maximum):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(ord(char) < 32 for char in value)


def _strings(value):
    return isinstance(value, list) and len(value) <= 32 and all(_text(item, 240) for item in value)


def _valid_brief(brief, lead_id):
    if not isinstance(brief, dict) or brief.get('schema_version') != '2.0':
        return False
    if not lead_id or brief.get('lead_id') != lead_id:
        return False
    if any(not isinstance(brief.get(key), str) for key in ('phase', 'missing_box', 'mood')):
        return False
    if brief.get('phase') not in _PHASE_TO_STAGE or brief.get('missing_box') not in _BOXES or brief.get('mood') not in _MOODS:
        return False
    if not _text(brief.get('objective'), 320) or not _strings(brief.get('avoid')) or not _strings(brief.get('escalation_rules')):
        return False
    if brief.get('opener_hint') is not None and not _text(brief['opener_hint'], 320):
        return False
    confidence = brief.get('confidence')
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        return False
    if brief.get('ready_for_call') is not False:
        return False
    try:
        created = datetime.fromisoformat(brief['created_at'].replace('Z', '+00:00'))
        expires = datetime.fromisoformat(brief['expires_at'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return created.tzinfo is not None and expires.tzinfo is not None and created <= now < expires and 0 < (expires - created).total_seconds() <= 168 * 3600
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def load_brief_into_ctx(call_ctx, brief):
    call_ctx.call_brief = {}
    call_ctx.bob_phase = None
    call_ctx.bob_missing_box = None
    call_ctx.bob_mood_hint = None
    call_ctx.bob_avoid = []
    call_ctx.bob_escalation_rules = []
    call_ctx.bob_opener_hint = None
    if not _valid_brief(brief, getattr(call_ctx, 'lead_id', '')):
        if brief:
            logger.warning('call_brief_rejected lead_id={}', getattr(call_ctx, 'lead_id', ''))
        return False
    call_ctx.call_brief = dict(brief)
    call_ctx.bob_phase = brief['phase']
    call_ctx.bob_missing_box = brief['missing_box']
    call_ctx.bob_mood_hint = brief['mood']
    call_ctx.bob_avoid = list(brief['avoid'])
    call_ctx.bob_escalation_rules = list(brief['escalation_rules'])
    call_ctx.bob_opener_hint = brief.get('opener_hint')
    logger.info('call_brief_loaded lead_id={} phase={} box={}', call_ctx.lead_id, brief['phase'], brief['missing_box'])
    return True
