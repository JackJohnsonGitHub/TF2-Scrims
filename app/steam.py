"""Steam OpenID 2.0 login + Steam Web API persona/avatar lookup.

Security-critical: `verify_return` completes the server-side `check_authentication`
round-trip with Steam and only returns a SteamID when Steam answers `is_valid:true`.
A forged/replayed return therefore cannot produce a signed-in session (SC-007).

That round-trip alone is not enough, though: `check_authentication` is stateless
signature verification. It proves Steam *signed* an assertion, not that Steam signed
it for us — Steam has no idea which site is asking, so an assertion minted for a
different relying party validates just as happily. Anyone running any Steam-login
site could otherwise capture a visitor's assertion and replay it here to be signed in
as them, with no phishing and no stolen password. `verify_return` therefore also
enforces OpenID 2.0 §11.1: the assertion must carry *our* `return_to`, and the fields
we read off it must be covered by the signature.
"""
import re

import requests

OPENID_LOGIN_URL = "https://steamcommunity.com/openid/login"
OPENID_NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
_CLAIMED_ID_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(\d+)$")
_HTTP_TIMEOUT = 10


def return_to_url(base_url: str) -> str:
    """This deployment's one canonical `openid.return_to`. Built in a single place so
    the value we send and the value we later require an assertion to carry cannot
    drift apart — a mismatch between them would lock every user out."""
    return f"{base_url}/login/return"


def build_login_url(base_url: str) -> str:
    """The URL to redirect the browser to for Steam login."""
    params = {
        "openid.ns": OPENID_NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to_url(base_url),
        "openid.realm": base_url,
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    }
    req = requests.Request("GET", OPENID_LOGIN_URL, params=params).prepare()
    return req.url


# Fields we read off the assertion, so each must appear in `openid.signed`. A field
# left out of that list is attacker-controlled even when the signature checks out.
_REQUIRED_SIGNED = ("claimed_id", "return_to")


def verify_return(params: dict, expected_return_to: str) -> str | None:
    """Verify Steam's OpenID return server-side. Returns the SteamID on success,
    else None. `params` is the query string Steam redirected back with;
    `expected_return_to` is this deployment's own `return_to_url`."""
    if params.get("openid.mode") != "id_res":
        return None

    claimed_id = params.get("openid.claimed_id", "")
    match = _CLAIMED_ID_RE.match(claimed_id)
    if not match:
        return None

    # Was this assertion addressed to us? Checked before the round-trip, because
    # Steam would happily validate another site's assertion and report nothing wrong.
    if params.get("openid.return_to") != expected_return_to:
        return None

    signed = params.get("openid.signed", "").split(",")
    if any(field not in signed for field in _REQUIRED_SIGNED):
        return None

    # Echo every openid.* param back with mode=check_authentication (required).
    data = {k: v for k, v in params.items() if k.startswith("openid.")}
    data["openid.mode"] = "check_authentication"
    try:
        resp = requests.post(OPENID_LOGIN_URL, data=data, timeout=_HTTP_TIMEOUT)
    except requests.RequestException:
        return None
    if "is_valid:true" not in resp.text:
        return None
    return match.group(1)


def fetch_summary(steam_id: str, api_key: str) -> tuple[str, str | None]:
    """Return (persona_name, avatar_url) from the Steam Web API. Falls back to the
    SteamID and no avatar if the key is absent or the call fails (FR-005)."""
    if not api_key:
        return steam_id, None
    try:
        resp = requests.get(
            "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
            params={"key": api_key, "steamids": steam_id},
            timeout=_HTTP_TIMEOUT,
        )
        players = resp.json().get("response", {}).get("players", [])
        if players:
            p = players[0]
            return p.get("personaname") or steam_id, p.get("avatarfull")
    except (requests.RequestException, ValueError):
        pass
    return steam_id, None
