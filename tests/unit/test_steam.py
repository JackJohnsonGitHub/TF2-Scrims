"""Unit tests for the Steam OpenID + Web API helper (network mocked)."""
import app.steam as steam

STEAM_ID = "76561198000000123"
BASE_URL = "http://localhost:5000"
RETURN_TO = steam.return_to_url(BASE_URL)


def assertion(**overrides):
    """A positive assertion shaped like Steam's, addressed to this deployment.
    Override any field to model a tampered or foreign one."""
    params = {
        "openid.ns": steam.OPENID_NS,
        "openid.mode": "id_res",
        "openid.op_endpoint": steam.OPENID_LOGIN_URL,
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{STEAM_ID}",
        "openid.identity": f"https://steamcommunity.com/openid/id/{STEAM_ID}",
        "openid.return_to": RETURN_TO,
        "openid.response_nonce": "2026-07-27T12:00:00Zabcdef",
        "openid.assoc_handle": "assoc-handle",
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,"
                         "response_nonce,assoc_handle",
        "openid.sig": "c2lnbmF0dXJl",
    }
    params.update(overrides)
    return params


def no_network(monkeypatch):
    """Make any Steam round-trip a test failure — for the rejections that must be
    decided locally, before we ever ask Steam."""
    def _fail(*a, **k):
        raise AssertionError("rejected assertion must not reach Steam")
    monkeypatch.setattr(steam.requests, "post", _fail)


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
    url = steam.build_login_url(BASE_URL)
    assert url.startswith("https://steamcommunity.com/openid/login")
    assert "openid.mode=checkid_setup" in url
    assert "openid.return_to=http%3A%2F%2Flocalhost%3A5000%2Flogin%2Freturn" in url


def test_login_url_return_to_matches_what_verification_requires():
    # Guards the drift that would lock everyone out: the return_to we ask Steam to
    # send users back to must be exactly the one verify_return insists on.
    from urllib.parse import parse_qs, urlparse

    sent = parse_qs(urlparse(steam.build_login_url(BASE_URL)).query)["openid.return_to"][0]
    assert sent == RETURN_TO


def test_verify_return_valid(monkeypatch):
    monkeypatch.setattr(steam.requests, "post", lambda *a, **k: _Resp(text="ns:...\nis_valid:true\n"))
    assert steam.verify_return(assertion(), RETURN_TO) == STEAM_ID


def test_verify_return_bad_claimed_id_no_network(monkeypatch):
    # Malformed claimed_id must fail before any network call.
    no_network(monkeypatch)
    bad = assertion(**{"openid.claimed_id": "https://evil.example/id/1"})
    assert steam.verify_return(bad, RETURN_TO) is None


def test_verify_return_rejects_assertion_minted_for_another_site(monkeypatch):
    """The core §11.1 check. This assertion is genuinely Steam-signed and names a
    real user — it was just issued to someone else's site. An attacker running any
    Steam-login site could otherwise replay a visitor's assertion here and be
    signed in as them, so this must fail without ever asking Steam (which would
    answer is_valid:true and tell us nothing)."""
    no_network(monkeypatch)
    foreign = assertion(**{"openid.return_to": "https://evil.example.com/login/return"})
    assert steam.verify_return(foreign, RETURN_TO) is None


def test_verify_return_rejects_missing_return_to(monkeypatch):
    no_network(monkeypatch)
    stripped = assertion()
    del stripped["openid.return_to"]
    assert steam.verify_return(stripped, RETURN_TO) is None


def test_verify_return_rejects_same_host_different_path(monkeypatch):
    # A near-miss on our own origin is still not the endpoint we published.
    no_network(monkeypatch)
    near = assertion(**{"openid.return_to": f"{BASE_URL}/login/return/../elsewhere"})
    assert steam.verify_return(near, RETURN_TO) is None


def test_verify_return_rejects_unsigned_claimed_id(monkeypatch):
    # A valid signature over *other* fields leaves claimed_id attacker-controlled.
    no_network(monkeypatch)
    unsigned = assertion(**{"openid.signed": "return_to,response_nonce,assoc_handle"})
    assert steam.verify_return(unsigned, RETURN_TO) is None


def test_verify_return_rejects_unsigned_return_to(monkeypatch):
    # Likewise: an unsigned return_to could simply be rewritten to match ours.
    no_network(monkeypatch)
    unsigned = assertion(**{"openid.signed": "claimed_id,response_nonce,assoc_handle"})
    assert steam.verify_return(unsigned, RETURN_TO) is None


def test_verify_return_rejects_non_id_res_mode(monkeypatch):
    no_network(monkeypatch)
    cancelled = assertion(**{"openid.mode": "cancel"})
    assert steam.verify_return(cancelled, RETURN_TO) is None


def test_verify_return_echoes_check_authentication_to_steam(monkeypatch):
    # The round-trip must resend the signed fields verbatim, with only the mode
    # swapped — Steam recomputes the signature over exactly what it sent.
    sent = {}

    def _post(url, data=None, timeout=None):
        sent.update(data=data, url=url)
        return _Resp(text="is_valid:true")

    monkeypatch.setattr(steam.requests, "post", _post)
    steam.verify_return(assertion(), RETURN_TO)

    assert sent["url"] == steam.OPENID_LOGIN_URL
    assert sent["data"]["openid.mode"] == "check_authentication"
    assert sent["data"]["openid.sig"] == "c2lnbmF0dXJl"
    assert sent["data"]["openid.return_to"] == RETURN_TO


def test_verify_return_not_valid(monkeypatch):
    monkeypatch.setattr(steam.requests, "post", lambda *a, **k: _Resp(text="is_valid:false"))
    assert steam.verify_return(assertion(), RETURN_TO) is None


def test_verify_return_network_error(monkeypatch):
    def boom(*a, **k):
        raise steam.requests.RequestException("down")
    monkeypatch.setattr(steam.requests, "post", boom)
    assert steam.verify_return(assertion(), RETURN_TO) is None


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
