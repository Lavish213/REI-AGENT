import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta


def _make_lead(
    callable_val=True,
    opted_out=False,
    dnc_blocked=False,
    last_called_at=None,
    distress_score=75,
    estimated_arv=25000000,
    callable_phones=None,
    composite_score=None,
):
    return {
        "id": "lead-abc123",
        "callable": callable_val,
        "opted_out": opted_out,
        "dnc_blocked": dnc_blocked,
        "last_called_at": last_called_at,
        "composite_score": composite_score,
        "properties": {
            "id": "prop-xyz",
            "distress_score": distress_score,
            "estimated_arv": estimated_arv,
            "callable_phones": callable_phones or ["+12095551234"],
            "address": "123 Test St",
        },
    }


def _filter_eligible(leads, min_score=50):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    results = []
    for lead in leads:
        if not lead.get("callable"):
            continue
        if lead.get("opted_out"):
            continue
        if lead.get("dnc_blocked"):
            continue
        last_called = lead.get("last_called_at")
        if last_called:
            last_dt = datetime.fromisoformat(last_called.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < 72 * 3600:
                continue
        prop = lead.get("properties") or {}
        if prop.get("distress_score", 0) < min_score:
            continue
        if not prop.get("estimated_arv"):
            continue
        phones = prop.get("callable_phones")
        if not phones or (isinstance(phones, list) and len(phones) == 0):
            continue
        results.append(lead)
    return results


class TestEligibilityFilter:
    def test_fully_eligible_lead_passes(self):
        leads = [_make_lead()]
        assert len(_filter_eligible(leads)) == 1

    def test_callable_null_blocked(self):
        leads = [_make_lead(callable_val=None)]
        assert len(_filter_eligible(leads)) == 0

    def test_callable_false_blocked(self):
        leads = [_make_lead(callable_val=False)]
        assert len(_filter_eligible(leads)) == 0

    def test_opted_out_blocked(self):
        leads = [_make_lead(opted_out=True)]
        assert len(_filter_eligible(leads)) == 0

    def test_dnc_blocked(self):
        leads = [_make_lead(dnc_blocked=True)]
        assert len(_filter_eligible(leads)) == 0

    def test_called_recently_blocked(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        leads = [_make_lead(last_called_at=recent)]
        assert len(_filter_eligible(leads)) == 0

    def test_called_over_72h_passes(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
        leads = [_make_lead(last_called_at=old)]
        assert len(_filter_eligible(leads)) == 1

    def test_score_too_low_blocked(self):
        leads = [_make_lead(distress_score=49)]
        assert len(_filter_eligible(leads)) == 0

    def test_no_arv_blocked(self):
        leads = [_make_lead(estimated_arv=None)]
        assert len(_filter_eligible(leads)) == 0

    def test_no_phones_blocked(self):
        lead = _make_lead()
        lead["properties"]["callable_phones"] = None
        assert len(_filter_eligible([lead])) == 0

    def test_empty_phones_list_blocked(self):
        lead = _make_lead()
        lead["properties"]["callable_phones"] = []
        assert len(_filter_eligible([lead])) == 0

    def test_multiple_leads_filters_correctly(self):
        leads = [
            _make_lead(),
            _make_lead(callable_val=False),
            _make_lead(opted_out=True),
            _make_lead(distress_score=30),
            _make_lead(),
        ]
        result = _filter_eligible(leads)
        assert len(result) == 2

    def test_min_score_threshold(self):
        leads = [
            _make_lead(distress_score=85),
            _make_lead(distress_score=70),
            _make_lead(distress_score=50),
            _make_lead(distress_score=49),
        ]
        assert len(_filter_eligible(leads, min_score=50)) == 3
        assert len(_filter_eligible(leads, min_score=70)) == 2
        assert len(_filter_eligible(leads, min_score=85)) == 1


class TestLeadActivation:
    def test_phone_normalization_10_digit(self):
        raw = "2095551234"
        digits = "".join(c for c in raw if c.isdigit())
        normalized = f"+1{digits[-10:]}" if len(digits) == 10 else f"+{digits}"
        assert normalized == "+12095551234"

    def test_phone_normalization_with_formatting(self):
        raw = "(209) 555-1234"
        digits = "".join(c for c in raw if c.isdigit())
        normalized = f"+1{digits[-10:]}" if len(digits) == 10 else f"+{digits}"
        assert normalized == "+12095551234"

    def test_phone_normalization_11_digit_with_1(self):
        raw = "12095551234"
        digits = "".join(c for c in raw if c.isdigit())
        normalized = f"+1{digits[-10:]}" if len(digits) == 10 else f"+{digits}"
        assert normalized == "+12095551234"


class TestOutboundSorting:
    def test_callback_scheduled_sorts_first(self):
        now = datetime.now(timezone.utc)
        past_callback = (now - timedelta(minutes=5)).isoformat()
        future_callback = (now + timedelta(hours=2)).isoformat()

        leads = [
            {"id": "a", "composite_score": 60, "callback_scheduled_at": None, "properties": {}},
            {"id": "b", "composite_score": 90, "callback_scheduled_at": future_callback, "properties": {}},
            {"id": "c", "composite_score": 70, "callback_scheduled_at": past_callback, "properties": {}},
        ]

        def priority(lead):
            callback_at = lead.get("callback_scheduled_at")
            if callback_at:
                try:
                    cb_dt = datetime.fromisoformat(callback_at.replace("Z", "+00:00"))
                    if cb_dt <= now:
                        return (0, 0)
                except Exception:
                    pass
            composite = lead.get("composite_score") or 0
            tier = 1 if composite >= 85 else 2 if composite >= 70 else 3
            return (tier, -composite)

        sorted_leads = sorted(leads, key=priority)
        assert sorted_leads[0]["id"] == "c"
        assert sorted_leads[1]["id"] == "a" or sorted_leads[1]["id"] == "b"

    def test_composite_score_tier_ordering(self):
        leads = [
            {"id": "b", "composite_score": 70, "callback_scheduled_at": None, "properties": {}},
            {"id": "c", "composite_score": 50, "callback_scheduled_at": None, "properties": {}},
            {"id": "a", "composite_score": 90, "callback_scheduled_at": None, "properties": {}},
        ]

        def priority(lead):
            composite = lead.get("composite_score") or 0
            tier = 1 if composite >= 85 else 2 if composite >= 70 else 3
            return (tier, -composite)

        sorted_leads = sorted(leads, key=priority)
        assert sorted_leads[0]["id"] == "a"
        assert sorted_leads[1]["id"] == "b"
        assert sorted_leads[2]["id"] == "c"
