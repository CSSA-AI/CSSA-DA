import pytest
from fastapi import Request

from app.api.deps import Principal
from app.core.config import settings
from app.core.rate_limit import chat_rate_limit_key, validate_rate_limit_config


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


def _request(client_host: str = "1.2.3.4") -> Request:
    """A Request with an empty state, as slowapi would see one."""
    return Request(
        {
            "type": "http",
            "headers": [],
            "client": (client_host, 12345),
        }
    )


def test_chat_key_uses_the_principal_when_one_is_present():
    request = _request()
    request.state.principal = Principal(
        kind="internal",
        user_id=None,
        rate_limit_key="ip:9.9.9.9",
    )

    assert chat_rate_limit_key(request) == "ip:9.9.9.9"


def test_chat_key_falls_back_to_the_address_without_a_principal():
    # Happens if a route is ever given a rate limit but no auth dependency.
    # Reading request.state.principal directly would raise AttributeError
    # inside slowapi's wrapper and surface as an unexplained 500.
    assert chat_rate_limit_key(_request("5.6.7.8")) == "ip:5.6.7.8"
