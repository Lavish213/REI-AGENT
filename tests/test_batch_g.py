"""
Batch G — Tests for:
- Geo phrase generation
- SellerMemory V2 context
- AISoftenerProcessor text transforms
- SilenceDetectorProcessor lifecycle
- ProviderRegistry fallback logic
- schedule_followup tool registration
"""
import asyncio
import os
import pytest


# ─────────────────────────────────────────────
# G1/G2 — Geo Phrase Intelligence
# ─────────────────────────────────────────────

class TestGeoPhrases:
    def test_returns_list(self):
        from backend.voice.geo_phrases import get_geo_phrases
        result = get_geo_phrases({"neighborhood": "South Stockton"}, "stockton")
        assert isinstance(result, list)

    def test_known_neighborhood_phrase(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({"neighborhood": "South Stockton"}, "stockton")
        assert any("south" in p.lower() or "South" in p for p in phrases)

    def test_cross_street_phrase(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({
            "neighborhood": "",
            "cross_streets": ["Hammer Lane", "West Lane"],
        }, "stockton")
        assert any("Hammer Lane" in p or "West Lane" in p for p in phrases)

    def test_school_district_phrase(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({
            "school_district": "Lincoln Unified",
        }, "stockton")
        assert any("Lincoln" in p for p in phrases)

    def test_ace_accessible_phrase(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({
            "ace_accessible": True,
        }, "stockton")
        assert any("ACE" in p for p in phrases)

    def test_high_flood_phrase(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({
            "flood_risk": "high — flood insurance required",
        }, "stockton")
        assert any("flood" in p.lower() for p in phrases)

    def test_max_three_phrases(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({
            "neighborhood": "South Stockton",
            "cross_streets": ["Hammer Lane"],
            "school_district": "Stockton Unified",
            "ace_accessible": True,
            "flood_risk": "high — flood insurance required",
        }, "stockton")
        assert len(phrases) <= 3

    def test_format_for_prompt(self):
        from backend.voice.geo_phrases import format_geo_phrases_for_prompt
        result = format_geo_phrases_for_prompt(["That's South Stockton.", "Near Hammer Lane."])
        assert "SOPHIA LOCAL" in result
        assert "South Stockton" in result

    def test_empty_osm_returns_empty(self):
        from backend.voice.geo_phrases import get_geo_phrases
        phrases = get_geo_phrases({}, "unknown")
        assert isinstance(phrases, list)


# ─────────────────────────────────────────────
# G5 — SellerMemory V2
# ─────────────────────────────────────────────

class TestSellerMemoryV2:
    def _make_memory(self, **kwargs):
        from backend.voice.memory import SellerMemory
        m = SellerMemory(lead_id="test-lead-123")
        for k, v in kwargs.items():
            setattr(m, k, v)
        return m

    def test_empty_memory_returns_empty_string(self):
        m = self._make_memory()
        assert m.to_prompt_context() == ""

    def test_single_call_summary(self):
        m = self._make_memory(call_summaries=["Seller seemed interested but needs time."])
        ctx = m.to_prompt_context()
        assert "prior call" in ctx.lower() or "1 prior" in ctx
        assert "interested" in ctx

    def test_multi_call_history_surfaced(self):
        m = self._make_memory(call_summaries=[
            "Call 1: mentioned repairs",
            "Call 2: seemed motivated",
            "Call 3: asked about timeline",
        ])
        ctx = m.to_prompt_context()
        assert "Call 3" in ctx
        assert "Most recent" in ctx or "most recent" in ctx

    def test_objections_surfaced(self):
        m = self._make_memory(objections_raised=["price too low", "need to talk to spouse"])
        ctx = m.to_prompt_context()
        assert "price too low" in ctx or "Objections" in ctx

    def test_price_floor_surfaced(self):
        m = self._make_memory(price_floor=25000_00)  # 2,500,000 cents = $25,000
        ctx = m.to_prompt_context()
        assert "$25,000" in ctx

    def test_competitor_mentions_surfaced(self):
        m = self._make_memory(competitor_mentions=["OpenDoor", "Zillow Offers"])
        ctx = m.to_prompt_context()
        assert "OpenDoor" in ctx

    def test_natural_reference_instruction(self):
        m = self._make_memory(call_summaries=["test"])
        ctx = m.to_prompt_context()
        assert "naturally" in ctx.lower()
        # Instruction tells Sophia NOT to say it — that's the expected content
        assert "never say" in ctx.lower() or "don't say" in ctx.lower()

    def test_update_from_intel_merges_objections(self):
        m = self._make_memory(objections_raised=["low price"])
        m.update_from_intel({"objections": ["not ready", "need to think"]})
        assert "not ready" in m.objections_raised
        assert "low price" in m.objections_raised

    def test_update_from_intel_no_duplicate_objections(self):
        m = self._make_memory(objections_raised=["low price"])
        m.update_from_intel({"objections": ["low price", "new issue"]})
        assert m.objections_raised.count("low price") == 1

    def test_update_from_intel_takes_lower_price_floor(self):
        m = self._make_memory(price_floor=30000_00)
        m.update_from_intel({"price_floor": 25000_00})
        assert m.price_floor == 25000_00

    def test_update_from_intel_keeps_higher_price_floor(self):
        m = self._make_memory(price_floor=20000_00)
        m.update_from_intel({"price_floor": 25000_00})
        assert m.price_floor == 20000_00

    def test_spouse_name_surfaced(self):
        m = self._make_memory(call_summaries=["test"], spouse_name="Maria")
        ctx = m.to_prompt_context()
        assert "Maria" in ctx


# ─────────────────────────────────────────────
# G12 — AISoftenerProcessor
# ─────────────────────────────────────────────

class TestAISoftenerProcessor:
    def _proc(self):
        from backend.voice.processors.ai_softener import AISoftenerProcessor
        return AISoftenerProcessor()

    def test_removes_certainly(self):
        proc = self._proc()
        result = proc._soften("Certainly! Here's what we can do.")
        assert "Certainly" not in result
        assert "Here's what we can do" in result

    def test_removes_absolutely(self):
        proc = self._proc()
        result = proc._soften("Absolutely! That makes a lot of sense.")
        assert "Absolutely" not in result

    def test_removes_of_course(self):
        proc = self._proc()
        result = proc._soften("Of course! I understand completely.")
        assert "Of course" not in result

    def test_contractions_applied(self):
        proc = self._proc()
        result = proc._soften("I am going to help you with this. It is a good option.")
        assert "I'm" in result
        assert "it's" in result.lower()

    def test_preserves_meaning(self):
        proc = self._proc()
        original = "Certainly! The repairs are going to cost around twenty thousand dollars."
        result = proc._soften(original)
        assert "twenty thousand dollars" in result

    def test_repeated_starter_removed(self):
        proc = self._proc()
        proc._soften("Yeah, that makes sense.")
        proc._soften("Yeah, I get that.")
        proc._soften("Yeah, okay.")
        # 4th "yeah" should be suppressed
        result = proc._soften("Yeah, let me check that.")
        assert not result.lower().startswith("yeah")

    def test_empty_string_passes_through(self):
        proc = self._proc()
        assert proc._soften("") == ""

    def test_no_ai_reference_strip(self):
        proc = self._proc()
        result = proc._soften("As an AI, I can help you with that.")
        assert "As an AI" not in result


# ─────────────────────────────────────────────
# G6 — SilenceDetectorProcessor
# ─────────────────────────────────────────────

class TestSilenceDetectorProcessor:
    def test_callback_registration(self):
        from backend.voice.processors.silence_detector import SilenceDetectorProcessor
        proc = SilenceDetectorProcessor()
        calls = []
        async def cb(text): calls.append(text)
        proc.set_recovery_callback(cb)
        assert proc._recovery_cb is not None

    def test_disable_prevents_timer(self):
        from backend.voice.processors.silence_detector import SilenceDetectorProcessor
        proc = SilenceDetectorProcessor()
        proc.disable()
        assert not proc._enabled

    def test_recovery_phrases_non_empty(self):
        from backend.voice.processors.silence_detector import _RECOVERY_PHRASES
        assert len(_RECOVERY_PHRASES) >= 4
        assert all(isinstance(p, str) and p for p in _RECOVERY_PHRASES)

    def test_phrase_rotation(self):
        from backend.voice.processors.silence_detector import SilenceDetectorProcessor, _RECOVERY_PHRASES
        proc = SilenceDetectorProcessor()
        seen = set()
        for i in range(len(_RECOVERY_PHRASES) * 2):
            phrase = _RECOVERY_PHRASES[proc._phrase_idx % len(_RECOVERY_PHRASES)]
            seen.add(phrase)
            proc._phrase_idx += 1
        assert len(seen) == len(_RECOVERY_PHRASES)

    def test_silence_timeout_fires_callback(self):
        from backend.voice.processors.silence_detector import SilenceDetectorProcessor

        received = []
        async def cb(text): received.append(text)

        async def run():
            proc = SilenceDetectorProcessor(silence_timeout=0.05)
            proc.set_recovery_callback(cb)
            proc._start_timer()
            await asyncio.sleep(0.15)

        asyncio.run(run())
        assert len(received) == 1

    def test_cancelled_timer_does_not_fire(self):
        from backend.voice.processors.silence_detector import SilenceDetectorProcessor

        received = []
        async def cb(text): received.append(text)

        async def run():
            proc = SilenceDetectorProcessor(silence_timeout=0.1)
            proc.set_recovery_callback(cb)
            proc._start_timer()
            await asyncio.sleep(0.02)
            proc._cancel_timer()
            await asyncio.sleep(0.15)

        asyncio.run(run())
        assert len(received) == 0


# ─────────────────────────────────────────────
# G9 — ProviderRegistry
# ─────────────────────────────────────────────

class TestProviderRegistry:
    def test_registry_initializes(self):
        from backend.voice.providers import ProviderRegistry
        reg = ProviderRegistry()
        assert reg.health("anthropic") is not None
        assert reg.health("groq") is not None
        assert reg.health("elevenlabs") is not None

    def test_select_llm_anthropic_when_key_set(self, monkeypatch):
        from backend.voice.providers import ProviderRegistry
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        reg = ProviderRegistry()
        provider, tools = reg.select_llm()
        assert provider == "anthropic"
        assert tools is True

    def test_select_llm_groq_fallback(self, monkeypatch):
        from backend.voice.providers import ProviderRegistry
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        reg = ProviderRegistry()
        provider, tools = reg.select_llm()
        assert provider == "groq"
        assert tools is False

    def test_groq_tools_not_supported(self, monkeypatch):
        from backend.voice.providers import ProviderRegistry
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "gk")
        reg = ProviderRegistry()
        _, tools = reg.select_llm()
        assert tools is False

    def test_circuit_opens_after_3_failures(self):
        from backend.voice.providers import ProviderRegistry
        reg = ProviderRegistry()
        h = reg.health("elevenlabs")
        h.record_failure()
        h.record_failure()
        h.record_failure()
        assert h.available is False
        assert h.is_circuit_open()

    def test_health_record_success_reduces_failures(self):
        from backend.voice.providers import ProviderRegistry
        reg = ProviderRegistry()
        h = reg.health("elevenlabs")
        h.record_failure()
        h.record_failure()
        h.record_success(150.0)
        assert h.failure_count == 1

    def test_select_tts_orpheus_when_key_set(self, monkeypatch):
        from backend.voice.providers import ProviderRegistry
        monkeypatch.setenv("TOGETHER_AI_API_KEY", "together-key")
        reg = ProviderRegistry()
        provider = reg.select_tts()
        assert provider == "orpheus"

    def test_select_tts_elevenlabs_fallback(self, monkeypatch):
        from backend.voice.providers import ProviderRegistry
        monkeypatch.delenv("TOGETHER_AI_API_KEY", raising=False)
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        reg = ProviderRegistry()
        provider = reg.select_tts()
        assert provider == "elevenlabs"

    def test_summary_returns_all_providers(self):
        from backend.voice.providers import ProviderRegistry
        reg = ProviderRegistry()
        summary = reg.summary()
        for name in ("anthropic", "groq", "elevenlabs", "orpheus", "deepgram"):
            assert name in summary


# ─────────────────────────────────────────────
# G13 — schedule_followup tool
# ─────────────────────────────────────────────

class TestScheduleFollowupTool:
    def test_tool_in_sophia_tools(self):
        from backend.voice.tools import SOPHIA_TOOLS
        names = [t["name"] for t in SOPHIA_TOOLS]
        assert "schedule_followup" in names

    def test_tool_has_required_fields(self):
        from backend.voice.tools import SOPHIA_TOOLS
        tool = next(t for t in SOPHIA_TOOLS if t["name"] == "schedule_followup")
        props = tool["input_schema"]["properties"]
        assert "lead_id" in props
        assert "priority" in props
        assert "notes" in props

    def test_priority_enum_values(self):
        from backend.voice.tools import SOPHIA_TOOLS
        tool = next(t for t in SOPHIA_TOOLS if t["name"] == "schedule_followup")
        enum_vals = tool["input_schema"]["properties"]["priority"]["enum"]
        assert "high" in enum_vals
        assert "medium" in enum_vals
        assert "low" in enum_vals

    def test_tool_registered_in_execute(self):
        """schedule_followup branch exists in execute_tool router."""
        import inspect
        from backend.voice import tools
        src = inspect.getsource(tools.execute_tool)
        assert "schedule_followup" in src
