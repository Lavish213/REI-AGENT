import asyncio
import hashlib
import json
from datetime import datetime, timezone

from backend.karpathys import client
from backend.karpathys.outbox import enqueue_event
from backend.lib import db
from loguru import logger
from backend.voice.call_brief_loader import _valid_brief, validated_valuation


def amount(value):
    return value if type(value) is int and 0 <= value <= 10**14 else None


def label(value, maximum=500):
    return value if isinstance(value, str) and 0 < len(value) <= maximum and all(ord(c) >= 32 for c in value) else None


def build_snapshot(lead_id, source):
    lead = source['lead']
    prop = lead.get('properties') or {}
    if isinstance(prop, list):
        prop = prop[0] if len(prop) == 1 else {}
    if lead.get('id') != lead_id or not lead.get('property_id') or prop.get('id') != lead['property_id']:
        raise ValueError('Canonical lead/property binding required')
    brief = lead.get('call_brief') or {}
    raw = (brief.get('evidence') or {}).get('valuation') or {}
    valid = validated_valuation(raw, lead_id) if _valid_brief(brief, lead_id) and raw.get('subject_id') == prop['id'] else {}
    comps = []
    if valid:
        for row in raw.get('accepted_comparables', [])[:50]:
            if not isinstance(row, dict):
                continue
            price = amount(row.get('sale_price_cents'))
            ref = label(row.get('source_ref'))
            if price and ref:
                comps.append({'sale_id': label(row.get('sale_id')), 'source_ref': ref, 'closed_on': label(row.get('closed_on'), 10), 'sale_price_cents': price, 'adjusted_value_cents': amount(row.get('adjusted_value_cents'))})
    offers = []
    for row in source.get('offers', [])[:20]:
        if isinstance(row, dict) and row.get('lead_id') == lead_id and row.get('offer_status') in {'draft', 'sent', 'countered', 'accepted', 'rejected', 'expired'}:
            offers.append({'id': label(row.get('id')), 'status': row['offer_status'], 'amount_cents': amount(row.get('offer_amount')), 'repairs_cents': amount(row.get('repair_estimate')), 'updated_at': label(row.get('updated_at') or row.get('created_at'), 40)})
    return {'schema_version': 1, 'observation_hour': datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat(), 'property_id': prop['id'], 'address': label(prop.get('address')), 'city': label(prop.get('city'), 100), 'state': label(prop.get('state'), 2), 'apn': label(prop.get('apn'), 30), 'valuation': valid or None, 'comparables': comps, 'offers': offers, 'appointment': {'at': label(lead.get('appointment_at'), 40), 'status': label(lead.get('appointment_status'), 40)}, 'quote_authorized': False, 'offer_authorized': False}


async def publish_business(call_sid, lead_id):
    if client.delivery_target() is None or not call_sid or not lead_id:
        return False
    source = await asyncio.to_thread(db.dashboard_business_source, lead_id)
    snapshot = build_snapshot(lead_id, source)
    revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return await enqueue_event('business', {'call_sid': call_sid, 'lead_id': lead_id, 'revision': revision, 'snapshot': snapshot, 'lead_name': label(source['lead'].get('owner_name'), 200) or 'Unverified seller', 'phone': label(source['lead'].get('owner_phone'), 40), 'email': label(source['lead'].get('owner_email'), 320), 'address': snapshot['address'], 'occurred_at': datetime.now(timezone.utc).isoformat()})


async def refresh_business(call_sid, lead_id):
    try:
        return await publish_business(call_sid, lead_id)
    except Exception as error:
        logger.warning('business_snapshot_queue_failed type={}', type(error).__name__)
        return False
