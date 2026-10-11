from backend.voice.agent import _load_system_prompt


def test_live_prompt_preserves_identity_and_verified_context():
    prompt = _load_system_prompt({"property_context_str": "Property: 123 Main Street. Seller: Maria."})
    assert "123 Main Street" in prompt
    assert "Maria" in prompt
    assert "automated" in prompt.lower()
    assert "Lincoln High" not in prompt
    assert "25. Stockton" not in prompt
