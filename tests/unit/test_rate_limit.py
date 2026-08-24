import pytest
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limit import (
    MAX_USER_KEY_LENGTH,
    client_rate_limit_key,
    validate_rate_limit_config,
)


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


def make_request(headers=None, client_host="10.0.0.1") -> Request:
    """Build the minimal ASGI scope client_rate_limit_key reads from."""
    return Request(
        {
            "type": "http",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in (headers or {}).items()
            ],
            "client": (client_host, 50000),
        }
    )


def test_key_uses_the_user_header_when_present():
    request = make_request({"X-User-Id": "alice"})

    assert client_rate_limit_key(request) == "user:alice"


def test_key_falls_back_to_ip_when_the_header_is_absent():
    # Nothing sends X-User-Id until the BFF (CSS-9) ships; until then the
    # limiter must keep counting per address exactly as it did before.
    assert client_rate_limit_key(make_request()) == "ip:10.0.0.1"


@pytest.mark.parametrize("blank", ["", "   ", "	"])
def test_key_falls_back_to_ip_when_the_header_is_blank(blank):
    # A blank header must not become the key "user:" — that single bucket
    # would be shared by every caller that sends one.
    request = make_request({"X-User-Id": blank})

    assert client_rate_limit_key(request) == "ip:10.0.0.1"


def test_key_namespaces_users_apart_from_ips():
    # Without the "user:"/"ip:" prefixes a caller claiming to be user
    # "10.0.0.2" would share a counter with real traffic from 10.0.0.2.
    claimed = client_rate_limit_key(make_request({"X-User-Id": "10.0.0.2"}))
    real = client_rate_limit_key(make_request(client_host="10.0.0.2"))

    assert claimed != real


def test_key_truncates_an_overlong_user_id():
    # Every distinct key is a new entry in the in-memory storage dict, so an
    # unbounded header value would let one caller grow it without limit.
    key = client_rate_limit_key(make_request({"X-User-Id": "x" * 500}))

    assert key == "user:" + "x" * MAX_USER_KEY_LENGTH
