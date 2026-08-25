import pytest

from app.core.config import settings
from app.core.rate_limit import validate_rate_limit_config


def test_validate_accepts_the_shipped_defaults():
    validate_rate_limit_config()


@pytest.mark.parametrize("bad", ["500/dya", "not a limit", "", "0/day"])
def test_validate_rejects_bad_global_limit(monkeypatch, bad):
    # slowapi parses callable limits per request and silently skips the
    # layer on a parse failure (fail-open), so bad strings must be caught
    # at startup instead. "0/day" parses fine but would 429 everything.
    monkeypatch.setattr(settings, "CHAT_GLOBAL_RATE_LIMIT", bad)

    with pytest.raises(RuntimeError, match="CHAT_GLOBAL_RATE_LIMIT"):
        validate_rate_limit_config()


def test_validate_rejects_bad_per_ip_limit(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT", "10/minuet")

    with pytest.raises(RuntimeError, match="CHAT_RATE_LIMIT"):
        validate_rate_limit_config()
