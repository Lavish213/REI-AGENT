import asyncio
import hashlib
import json
import re
import sqlite3

from loguru import logger
from postgrest.exceptions import APIError

from backend.lib import db

SMS_STATES = {'accepted', 'queued', 'sending', 'sent', 'delivered', 'undelivered', 'failed', 'read', 'canceled'}
EMAIL_STATES = {'processed', 'delivered', 'deferred', 'dropped', 'bounce', 'open', 'click', 'spamreport', 'unsubscribe', 'group_unsubscribe', 'group_resubscribe'}


def normalize_event(channel, event):
    if not isinstance(event, dict):
        raise TypeError('Event object required')
    if channel == 'sms':
        message = event.get('MessageSid', '')
        status = event.get('MessageStatus', '')
        recipient = event.get('To', '')
        if status not in SMS_STATES or not re.fullmatch(r'\+[1-9][0-9]{7,14}', recipient):
            raise ValueError('Invalid SMS callback')
        payload = {'channel': channel, 'message_id': message, 'status': status, 'recipient': recipient, 'error_code': str(event.get('ErrorCode') or '')[:40]}
    elif channel == 'email':
        status = event.get('event', '')
        recipient = event.get('email', '')
        timestamp = event.get('timestamp')
        args = event.get('custom_args', {})
        if not isinstance(args, dict) or status not in EMAIL_STATES or not isinstance(recipient, str) or '@' not in recipient or len(recipient) > 320 or type(timestamp) is not int or not 0 < timestamp < 32503680000:
            raise ValueError('Invalid email callback')
        payload = {'channel': channel, 'message_id': event.get('sg_message_id', ''), 'status': status, 'recipient': recipient.strip().lower(), 'occurred_at': timestamp, 'intent_id': event.get('communication_intent') or args.get('communication_intent', ''), 'provider_event_id': event.get('sg_event_id', ''), 'bounce_type': str(event.get('type', ''))[:40]}
    else:
        raise ValueError('Unsupported channel')
    if channel == 'email' and not payload['message_id'] and status in {'unsubscribe', 'group_unsubscribe', 'spamreport'}:
        payload['message_id'] = 'unattributed-suppression'
    if not isinstance(payload['message_id'], str) or not 0 < len(payload['message_id']) <= 512:
        raise ValueError('Provider message ID required')
    for field in ('intent_id', 'provider_event_id'):
        if field in payload and (not isinstance(payload[field], str) or len(payload[field]) > 512):
            raise ValueError('Invalid provider identity')
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    key = payload.get('provider_event_id') or hashlib.sha256(raw.encode()).hexdigest()
    return hashlib.sha256((channel + ':' + key).encode()).hexdigest(), payload


def accept_events(channel, events):
    if not isinstance(events, list) or not 0 < len(events) <= 1000:
        raise ValueError('Bounded event batch required')
    normalized = [normalize_event(channel, event) for event in events]
    db.stage_delivery_events(normalized)
    return len(normalized)


async def recover_loop():
    while True:
        for recover in (db.stage_message_acceptances, db.recover_delivery_events):
            try:
                await asyncio.to_thread(recover)
            except (RuntimeError, ValueError, TypeError, KeyError, OSError, sqlite3.Error, APIError) as error:
                logger.warning('delivery_recovery_failed operation={} type={}', recover.__name__, type(error).__name__)
        await asyncio.sleep(5)
