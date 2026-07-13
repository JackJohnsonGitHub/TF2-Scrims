"""Unit tests for the Steam OpenID + Web API helper (network mocked)."""
import app.steam as steam

STEAM_ID = "76561198000000123"
VALID_CLAIMED = {"openid.claimed_id": f"https://steamcommunity.com/openid/id/{STEAM_ID}"}


class _Resp:
    def __init__(self, text="", payload=None, exc=None):
        self.text = text
        self._payload = payload
        self._exc = exc

    def json(self):
        if self._exc:
            raise self._exc
        return self._payload


def test_build_login_url():
    url = steam.build_login_url("http://localhost:5000")
    assert url.startswith("https://steamcommunity.com/openid/login")
    assert "openid.mode=checkid_setup" in url
    assert "openid.return_to=http%3A%2F%2Flocalhost%3A5000%2Flogin%2Freturn" in url


def test_verify_return_valid(monkeypatch):
    monkeypatch.setattr(steam.requests, "post", lambda *a, **k: _Resp(text="ns:...\nis_valid:true\n"))
    assert steam.verify_return(dict(VALID_CLAIMED)) == STEAM_ID


def test_verify_return_bad_claimed_id_no_network():
    # Malformed claimed_id must fail before any network call.
    assert steam.verify_return({"openid.claimed_id": "https://evil.example/id/1"}) is None


def test_verify_return_not_valid(monkeypatch):
    monkeypatch.setattr(steam.requests, "post", lambda *a, **k: _Resp(text="is_valid:false"))
    assert steam.verify_return(dict(VALID_CLAIMED)) is None


def test_verify_return_network_error(monkeypatch):
    def boom(*a, **k):
        raise steam.requests.RequestException("down")
    monkeypatch.setattr(steam.requests, "post", boom)
    assert steam.verify_return(dict(VALID_CLAIMED)) is None


def test_fetch_summary_no_key_returns_fallback():
    assert steam.fetch_summary(STEAM_ID, "") == (STEAM_ID, None)


def test_fetch_summary_success(monkeypatch):
    payload = {"response": {"players": [{"personaname": "Ace", "avatarfull": "http://a/f.jpg"}]}}
    monkeypatch.setattr(steam.requests, "get", lambda *a, **k: _Resp(payload=payload))
    assert steam.fetch_summary(STEAM_ID, "KEY") == ("Ace", "http://a/f.jpg")


def test_fetch_summary_failure_returns_fallback(monkeypatch):
    def boom(*a, **k):
        raise steam.requests.RequestException("down")
    monkeypatch.setattr(steam.requests, "get", boom)
    assert steam.fetch_summary(STEAM_ID, "KEY") == (STEAM_ID, None)
