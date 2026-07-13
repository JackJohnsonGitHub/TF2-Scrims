"""Steam OpenID 2.0 login + Steam Web API persona/avatar lookup.

Security-critical: `verify_return` completes the server-side `check_authentication`
round-trip with Steam and only returns a SteamID when Steam answers `is_valid:true`.
A forged/replayed return therefore cannot produce a signed-in session (SC-007).
"""
import re

import requests

OPENID_LOGIN_URL = "https://steamcommunity.com/openid/login"
OPENID_NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
_CLAIMED_ID_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(\d+)$")
_HTTP_TIMEOUT = 10


def build_login_url(base_url: str) -> str:
    """The URL to redirect the browser to for Steam login."""
    return_to = f"{base_url}/login/return"
    params = {
        "openid.ns": OPENID_NS,
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": base_url,
        "openid.identity": IDENTIFIER_SELECT,
        "openid.claimed_id": IDENTIFIER_SELECT,
    }
    req = requests.Request("GET", OPENID_LOGIN_URL, params=params).prepare()
    return req.url


def verify_return(params: dict) -> str | None:
    """Verify Steam's OpenID return server-side. Returns the SteamID on success,
    else None. `params` is the query string Steam redirected back with."""
    claimed_id = params.get("openid.claimed_id", "")
    match = _CLAIMED_ID_RE.match(claimed_id)
    if not match:
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
