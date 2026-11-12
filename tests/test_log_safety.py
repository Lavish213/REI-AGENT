from pathlib import Path

from loguru import logger

from backend.comps import cache
from backend.lib.log_safety import error_type, pii_ref


def test_pii_ref_is_stable_nonreversible_and_typed():
    raw = "+12095551234"
    first = pii_ref(raw, "phone")
    second = pii_ref(raw, "phone")
    assert first == second
    assert first.startswith("phone:")
    assert raw not in first
    assert len(first) == len("phone:") + 12


def test_empty_pii_ref_does_not_create_shared_digest():
    assert pii_ref("", "email") == "email:missing"
    assert pii_ref(None, "address") == "address:missing"


def test_error_type_never_returns_exception_message():
    error = RuntimeError("seller@example.com at 123 Main St")
    assert error_type(error) == "RuntimeError"


def test_comps_cache_logs_only_an_address_reference():
    messages = []
    sink = logger.add(messages.append, format="{message}")
    try:
        cache.clear_cache()
        cache.get_cached_comps("123 Main St", "Stockton", "CA")
    finally:
        logger.remove(sink)
    rendered = "".join(messages)
    assert "123 Main St" not in rendered
    assert "address:" in rendered


def test_sensitive_log_placeholders_require_pii_ref():
    root = Path(__file__).parents[1] / "backend"
    sensitive = ("phone={}", "email={}", "address={}", "owner={}", "recipient={}", "to={}", "from={}")
    violations = []
    for path in root.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "logger." not in line or not any(item in line for item in sensitive):
                continue
            if "pii_ref(" not in line:
                violations.append(f"{path.relative_to(root)}:{number}")
    assert violations == []
