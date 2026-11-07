from backend.qa.grader import _grading_model
from backend.qa.transcript_intel import _analysis_model


def test_obsolete_generic_model_cannot_break_voice_qa(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-20250514")
    monkeypatch.setenv("VOICE_LLM_MODEL", "claude-haiku-4-5-20251001")
    assert _grading_model() == "claude-haiku-4-5-20251001"
    assert _analysis_model() == "claude-haiku-4-5-20251001"


def test_dedicated_qa_model_has_priority(monkeypatch):
    monkeypatch.setenv("QA_LLM_MODEL", "qa-model")
    monkeypatch.setenv("VOICE_LLM_MODEL", "voice-model")
    assert _grading_model() == "qa-model"
    assert _analysis_model() == "qa-model"
