from __future__ import annotations
from datetime import datetime, timezone
import math
from decimal import Decimal
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
    call_ctx.bob_valuation = {}
    call_ctx.bob_county_context = {}
    call_ctx.bob_california_context = {}
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
    evidence = brief.get('evidence')
    report = evidence.get('valuation') if isinstance(evidence, dict) else None
    call_ctx.bob_valuation = validated_valuation(report, call_ctx.lead_id)
    local = evidence.get('county_context') if isinstance(evidence, dict) else None
    call_ctx.bob_county_context = validated_county_context(local, call_ctx.lead_id)
    statewide = evidence.get('california_context') if isinstance(evidence, dict) else None
    call_ctx.bob_california_context = validated_california_context(statewide, call_ctx.lead_id)
    logger.info('call_brief_loaded lead_id={} phase={} box={}', call_ctx.lead_id, brief['phase'], brief['missing_box'])
    return True


def validated_county_context(report, lead_id):
    if not isinstance(report, dict) or report.get('schema_version') != '1.0' or report.get('lead_id') != lead_id:
        return {}
    if report.get('county_fips') != '06077' or report.get('profile_version') != '2026-10-14' or report.get('status') != 'county_context_only':
        return {}
    if report.get('parcel_verified') is not False or report.get('quote_authorized') is not False or report.get('offer_authorized') is not False:
        return {}
    return {key: report[key] for key in ('schema_version', 'lead_id', 'county_fips', 'profile_version', 'status', 'parcel_verified', 'quote_authorized', 'offer_authorized')}


def county_guidance(report, lead_id):
    if not validated_county_context(report, lead_id):
        return ''
    return 'SAN JOAQUIN PROPERTY REVIEW: This is general county context, not verification of this parcel. Confirm the property and its competitive submarket. Recheck actual city or county permit authority, permitted living area and ADU scope, condition, flood/levee and insurance evidence, parcel-specific taxes and supplemental costs, and rural utilities/access or land contracts when relevant. A postal city label does not prove jurisdiction. Parcel assessments, transfer tax and county-wide price indexes do not establish this house\'s sale price or ARV. Use reviewed closed-sale evidence and existing authorized offer tools; this guidance grants no price or contact authority.'


def validated_valuation(report, lead_id):
    if not isinstance(report, dict) or report.get('schema_version') != '1.0' or report.get('lead_id') != lead_id:
        return {}
    if report.get('quote_authorized') is not False or report.get('offer_authorized') is not False:
        return {}
    if report.get('status') != 'ready_advisory' or report.get('method') != 'evidence_adjusted_sales_comparison' or report.get('purpose') not in {'as_is', 'after_repair'}:
        return {}
    count = report.get('comparable_count')
    values = [report.get(key) for key in ('supported_low_cents', 'point_cents', 'supported_high_cents')]
    if type(count) is not int or not 3 <= count <= 50 or any(type(value) is not int or not 0 < value <= 10**14 for value in values):
        return {}
    if not values[0] <= values[1] <= values[2]:
        return {}
    try:
        effective = datetime.strptime(report['as_of'], '%Y-%m-%d').date()
        age = (datetime.now(timezone.utc).date() - effective).days
        if not 0 <= age <= 30 or effective.isoformat() != report['as_of']:
            return {}
    except (KeyError, TypeError, ValueError):
        return {}
    return {key: report[key] for key in ('schema_version', 'lead_id', 'status', 'method', 'purpose', 'as_of', 'comparable_count', 'supported_low_cents', 'point_cents', 'supported_high_cents', 'quote_authorized', 'offer_authorized')}


def valuation_guidance(report, lead_id, identity_confirmed=False, property_confirmed=False):
    safe = validated_valuation(report, lead_id)
    if not safe:
        return ''
    if identity_confirmed is not True or property_confirmed is not True:
        return 'BOB INTERNAL VALUATION: Research evidence is available. Verify this caller and property before discussing it. This does not authorize any price quote or offer.'
    point = Decimal(safe['point_cents']) / 100
    low = Decimal(safe['supported_low_cents']) / 100
    high = Decimal(safe['supported_high_cents']) / 100
    purpose = 'current-market after-repair indication, conditional on the reviewed renovation scope' if safe['purpose'] == 'after_repair' else 'as-is market indication'
    return f"BOB INTERNAL VALUATION: {purpose}: ${point:,.2f}; adjusted comparable-sale span ${low:,.2f}-${high:,.2f}, {safe['comparable_count']} closed sales, effective {safe['as_of']}. This span is not a statistical confidence interval or an appraisal. These numbers are not an approved offer. Do not quote them to the caller; use the existing authorized offer tool. Recheck changed property facts with the operator."


def validated_california_context(report, lead_id):
    if not isinstance(report, dict) or report.get('schema_version') != '1.0' or report.get('lead_id') != lead_id or report.get('state') != 'CA' or report.get('status') != 'california_review_only' or report.get('profile_version') != '2026-10-14':
        return {}
    if report.get('quote_authorized') is not False or report.get('offer_authorized') is not False:
        return {}
    return {key: report[key] for key in ('schema_version', 'lead_id', 'state', 'status', 'profile_version', 'quote_authorized', 'offer_authorized')}


def california_guidance(report, lead_id):
    if not validated_california_context(report, lead_id):
        return ''
    return 'CALIFORNIA PROPERTY REVIEW: Confirm title, liens and current payoffs; tenancy and applicable state/local rules; legal units and permit authority; property-specific insurance; parcel tax rates, direct assessments and supplemental costs. Itemize repairs, financing, holding and selling costs. An asking price, assessment, tax record or county index is not ARV or an approved offer. Public records do not grant contact permission. Do not promise vacant possession, ADU approval, insurance availability, clear title or an unconditional closing. Use existing authorized tools for reviewed offers and scheduling.'
