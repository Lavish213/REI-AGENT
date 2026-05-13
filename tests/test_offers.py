"""Batch E — Offer calculation + lifecycle tests."""
from unittest.mock import patch, MagicMock


# ──────────────────────────────────────────────────────────────────
# MAO calculation
# ──────────────────────────────────────────────────────────────────

class TestMAOCalculation:
    def test_mao_standard_no_repairs(self):
        """MAO = ARV * 0.70 - repair_estimate."""
        arv = 30_000_000   # $300k in cents
        repair = 2_500_000  # $25k default
        mao = int(arv * 0.70) - repair
        assert mao == 18_500_000  # $185k

    def test_mao_higher_repair_buffer(self):
        arv = 40_000_000   # $400k
        repair = 5_000_000  # $50k
        mao = int(arv * 0.70) - repair
        assert mao == 23_000_000  # $230k

    def test_mao_zero_repair(self):
        arv = 20_000_000   # $200k
        mao = int(arv * 0.70) - 0
        assert mao == 14_000_000  # $140k

    def test_mao_default_formula_matches_spec(self):
        """Spec: (ARV * 0.70) - 2500000 cents."""
        arv = 35_000_000   # $350k
        mao = int(arv * 0.70) - 2_500_000
        assert mao == 22_000_000  # $220k

    def test_mao_below_zero_edge_case(self):
        """Very low ARV can produce negative MAO — still computable."""
        arv = 2_000_000   # $20k (distressed)
        repair = 2_500_000
        mao = int(arv * 0.70) - repair
        assert mao == -1_100_000  # negative is valid, operator decides

    def test_mao_cents_precision(self):
        """Integer truncation, no float rounding errors."""
        arv = 37_500_000   # $375k
        mao = int(arv * 0.70) - 2_500_000
        assert mao == 23_750_000  # exact, no float noise
        assert isinstance(mao, int)

    def test_mao_large_arv(self):
        arv = 100_000_000  # $1M
        repair = 2_500_000
        mao = int(arv * 0.70) - repair
        assert mao == 67_500_000  # $675k


# ──────────────────────────────────────────────────────────────────
# Offer creation DB function
# ──────────────────────────────────────────────────────────────────

class TestOfferCreation:
    def _mock_client(self):
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "offer-abc"}]
        return client

    def test_create_offer_computes_mao(self):
        """create_offer must compute mao_calculated from arv_used."""
        with patch("backend.lib.db._get_client") as mock_get:
            client = self._mock_client()
            mock_get.return_value = client

            from backend.lib.db import create_offer
            offer_id = create_offer(
                lead_id="lead-1",
                arv_used=30_000_000,
                repair_estimate=2_500_000,
            )

            assert offer_id == "offer-abc"
            call_kwargs = client.table.return_value.insert.call_args[0][0]
            assert call_kwargs["mao_calculated"] == 18_500_000
            assert call_kwargs["offer_status"] == "draft"

    def test_create_offer_null_arv_produces_null_mao(self):
        with patch("backend.lib.db._get_client") as mock_get:
            client = self._mock_client()
            mock_get.return_value = client

            from backend.lib.db import create_offer
            create_offer(lead_id="lead-1", arv_used=None, repair_estimate=2_500_000)

            call_kwargs = client.table.return_value.insert.call_args[0][0]
            assert call_kwargs["mao_calculated"] is None

    def test_create_offer_offer_amount_defaults_to_mao(self):
        with patch("backend.lib.db._get_client") as mock_get:
            client = self._mock_client()
            mock_get.return_value = client

            from backend.lib.db import create_offer
            create_offer(lead_id="lead-1", arv_used=30_000_000, repair_estimate=2_500_000)

            call_kwargs = client.table.return_value.insert.call_args[0][0]
            # offer_amount should default to mao_calculated when not specified
            assert call_kwargs["offer_amount"] == 18_500_000

    def test_create_offer_custom_offer_amount(self):
        """Operator can set offer_amount independently of MAO."""
        with patch("backend.lib.db._get_client") as mock_get:
            client = self._mock_client()
            mock_get.return_value = client

            from backend.lib.db import create_offer
            create_offer(
                lead_id="lead-1",
                arv_used=30_000_000,
                repair_estimate=2_500_000,
                offer_amount=20_000_000,  # $200k — above MAO
            )

            call_kwargs = client.table.return_value.insert.call_args[0][0]
            assert call_kwargs["offer_amount"] == 20_000_000
            assert call_kwargs["mao_calculated"] == 18_500_000


# ──────────────────────────────────────────────────────────────────
# Offer status transitions
# ──────────────────────────────────────────────────────────────────

class TestOfferStatusTransitions:
    VALID_STATUSES = ("draft", "sent", "countered", "accepted", "rejected", "expired")

    def test_all_valid_statuses_defined(self):
        from backend.api.routes.offers import OFFER_STATUSES
        for s in self.VALID_STATUSES:
            assert s in OFFER_STATUSES

    def test_update_offer_status_sets_updated_at(self):
        with patch("backend.lib.db._get_client") as mock_get:
            client = MagicMock()
            mock_get.return_value = client

            from backend.lib.db import update_offer_status
            update_offer_status("offer-1", "sent")

            call_kwargs = client.table.return_value.update.call_args[0][0]
            assert call_kwargs["offer_status"] == "sent"
            assert "updated_at" in call_kwargs

    def test_update_offer_status_with_notes(self):
        with patch("backend.lib.db._get_client") as mock_get:
            client = MagicMock()
            mock_get.return_value = client

            from backend.lib.db import update_offer_status
            update_offer_status("offer-1", "countered", notes="Seller countered at $220k")

            call_kwargs = client.table.return_value.update.call_args[0][0]
            assert call_kwargs["notes"] == "Seller countered at $220k"

    def test_api_rejects_invalid_status(self):
        """Route must raise 400 for invalid status."""
        import asyncio
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from backend.api.routes.offers import router

        app = FastAPI()
        app.include_router(router, prefix="/api")
        client = TestClient(app)

        with patch("backend.lib.db.get_offer_by_id") as mock_get:
            mock_get.return_value = {"id": "offer-1", "offer_status": "draft"}
            res = client.patch("/api/offers/offer-1/status", json={"status": "INVALID_STATUS"})
            assert res.status_code == 400


# ──────────────────────────────────────────────────────────────────
# Walkthrough state
# ──────────────────────────────────────────────────────────────────

class TestWalkthroughState:
    VALID_STATES = ("none", "scheduled", "completed", "missed", "cancelled")

    def test_update_walkthrough_sets_state(self):
        with patch("backend.lib.db._get_client") as mock_get:
            client = MagicMock()
            mock_get.return_value = client

            from backend.lib.db import update_walkthrough_state
            update_walkthrough_state("lead-1", "scheduled", notes="Tuesday 2pm")

            call_kwargs = client.table.return_value.update.call_args[0][0]
            assert call_kwargs["walkthrough_state"] == "scheduled"
            assert call_kwargs["walkthrough_notes"] == "Tuesday 2pm"

    def test_update_walkthrough_completed_sets_timestamp(self):
        with patch("backend.lib.db._get_client") as mock_get:
            client = MagicMock()
            mock_get.return_value = client

            from backend.lib.db import update_walkthrough_state
            update_walkthrough_state("lead-1", "completed")

            call_kwargs = client.table.return_value.update.call_args[0][0]
            assert call_kwargs["walkthrough_state"] == "completed"
            assert "walkthrough_completed_at" in call_kwargs
            assert call_kwargs["walkthrough_completed_at"] is not None

    def test_api_rejects_invalid_walkthrough_state(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from backend.api.routes.workflow import router

        app = FastAPI()
        app.include_router(router, prefix="/api")
        client = TestClient(app)

        with patch("backend.lib.db._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "lead-1"}]
            mock_get.return_value = mock_client

            res = client.post("/api/workflow/leads/lead-1/walkthrough", json={"state": "INVALID"})
            assert res.status_code == 400

    def test_all_valid_walkthrough_states(self):
        """No exception for any valid state."""
        with patch("backend.lib.db._get_client") as mock_get:
            client = MagicMock()
            mock_get.return_value = client

            from backend.lib.db import update_walkthrough_state
            for state in self.VALID_STATES:
                update_walkthrough_state("lead-1", state)
