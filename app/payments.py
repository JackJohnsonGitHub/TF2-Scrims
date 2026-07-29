"""Payments: trade links, the escrow gate, and turning accepted trades into credits.

The money path. Three properties matter more than anything else here:

1. **Exactly once.** Crediting relies on `UNIQUE (method, provider_ref)` in the schema,
   not on the poller behaving well — it re-reads the same offers every run and can be
   run twice by hand.
2. **Fail closed.** If Steam cannot tell us whether a trade would be held, we refuse to
   start the payment. Guessing wrong means taking someone's keys for a server that
   cannot be delivered in time.
3. **Never fail a payment because Steam had a bad minute.** A transport error or a 429
   leaves every payment exactly as it was.
"""
import re
from urllib.parse import parse_qs, urlparse

from flask import current_app

from . import credits, steam_trade
from .db import get_db
from .rgl_store import utc_now
from .steam_trade import SteamUnavailable  # re-exported for callers

METHOD_STEAM_TRADE = "steam_trade"

STARTED = "started"
HELD = "held"
COMPLETE = "complete"
INSUFFICIENT = "insufficient"
FAILED = "failed"

OPEN_STATES = (STARTED, HELD)

STATE_LABELS = {
    STARTED: "Waiting for the operator to accept",
    HELD: "Held by Steam",
    COMPLETE: "Complete",
    INSUFFICIENT: "Not enough sent",
    FAILED: "Did not complete",
}

_TRADE_URL_HOSTS = ("steamcommunity.com", "www.steamcommunity.com")


class PaymentError(ValueError):
    """A refused payment action; `status` is the HTTP status a route should use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --- trade links ---------------------------------------------------------------------

def parse_trade_url(url: str) -> tuple[str, str]:
    """Pull (partner_id, token) out of a Steam trade URL.

    Raises PaymentError naming the specific problem, so a form can reject precisely and
    store nothing (FR-046).
    """
    url = (url or "").strip()
    if not url:
        raise PaymentError("Paste your Steam trade URL.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc not in _TRADE_URL_HOSTS:
        raise PaymentError("That is not a steamcommunity.com trade URL.")
    if "/tradeoffer/new" not in parsed.path:
        raise PaymentError("That link is not a trade offer URL — find it under "
                           "Inventory → Trade Offers → Who can send me Trade Offers.")
    query = parse_qs(parsed.query)
    partner = (query.get("partner") or [""])[0]
    token = (query.get("token") or [""])[0]
    if not re.fullmatch(r"\d+", partner or ""):
        raise PaymentError("That trade URL has no valid partner id.")
    if not token:
        raise PaymentError("That trade URL is missing its token.")
    return partner, token


def save_trade_link(steam_id: str, url: str) -> None:
    """Record a user's trade URL after checking it is actually theirs.

    A link belonging to somebody else would make the escrow pre-check answer about the
    wrong person — reporting *their* hold status while charging this account.
    """
    partner, token = parse_trade_url(url)
    if steam_trade.steamid64_from_accountid(partner) != str(steam_id):
        raise PaymentError(
            "That trade URL belongs to a different Steam account. Use your own — "
            "we check it against the account you signed in with."
        )
    db = get_db()
    db.execute(
        """INSERT INTO steam_trade_links (steam_id, trade_url, partner_id,
                                          access_token, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(steam_id) DO UPDATE SET
               trade_url = excluded.trade_url,
               partner_id = excluded.partner_id,
               access_token = excluded.access_token,
               updated_at = excluded.updated_at""",
        (steam_id, url.strip(), partner, token, utc_now()),
    )
    db.commit()


def get_trade_link(steam_id: str) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM steam_trade_links WHERE steam_id = ?", (steam_id,)).fetchone()
    return dict(row) if row else None


def delete_trade_link(steam_id: str) -> None:
    db = get_db()
    db.execute("DELETE FROM steam_trade_links WHERE steam_id = ?", (steam_id,))
    db.commit()


# --- payments ------------------------------------------------------------------------

def open_payment(steam_id: str) -> dict | None:
    row = get_db().execute(
        f"""{_SELECT_WITH_TARGET} WHERE p.steam_id = ? AND p.state IN (?, ?)
            ORDER BY p.id DESC LIMIT 1""",
        (steam_id, STARTED, HELD),
    ).fetchone()
    return _annotate(row) if row else None


"""SQL for a payment plus the state of the scrim it was started for, if any. The join is
what lets FR-020 report a stale target without a second query per row."""
_SELECT_WITH_TARGET = """
    SELECT p.*, s.status AS target_status, s.scheduled_at AS target_scheduled_at
    FROM payments p LEFT JOIN scrims s ON s.id = p.target_scrim_id
"""

# Scrim statuses that mean the match this payment was for will not happen.
_DEAD_SCRIM_STATUSES = ("cancelled", "declined")


def _annotate(row) -> dict:
    """Decorate a payment row with its label and, per FR-020, whether the scrim it was
    started for still applies.

    A stale target does **not** invalidate the payment. Credits are fungible and not
    bound to a scrim, so the trade still completes and the credits still land — telling
    the payer their payment died with the scrim would be both wrong and alarming.
    """
    payment = dict(row)
    payment["state_label"] = STATE_LABELS.get(payment["state"], payment["state"])
    payment["target_note"] = None

    if payment.get("target_scrim_id"):
        status = payment.get("target_status")
        scheduled = payment.get("target_scheduled_at")
        if status is None:
            payment["target_note"] = "The scrim this was for no longer exists."
        elif status in _DEAD_SCRIM_STATUSES:
            payment["target_note"] = "The scrim this was for has been called off."
        elif scheduled and scheduled <= utc_now():
            payment["target_note"] = "The scrim this was for has already started."

    return payment


def recent_payments(steam_id: str, limit: int = 20) -> list[dict]:
    rows = get_db().execute(
        f"{_SELECT_WITH_TARGET} WHERE p.steam_id = ? ORDER BY p.id DESC LIMIT ?",
        (steam_id, limit),
    ).fetchall()
    return [_annotate(r) for r in rows]


def price_summary() -> dict:
    """What a user is told before they pay (FR-033, FR-071)."""
    cfg = current_app.config
    keys = cfg["PAYMENT_MIN_KEYS"]
    return {
        "item": cfg["PAYMENT_ITEM_NAME"],
        "min_keys": keys,
        "credits_for_min": credits_for_keys(keys),
        "credit_minutes": cfg["CREDIT_MINUTES"],
        "extension_minutes": cfg["EXTENSION_MINUTES"],
        "grace_minutes": cfg["GRACE_MINUTES"],
    }


def credits_for_keys(keys: int) -> int:
    """`floor(keys × rate)`. Flooring avoids carrying a fractional remainder around:
    at 2.5 credits per key, 2 keys grant 5 and 3 grant 7."""
    return int(keys * current_app.config["CREDITS_PER_KEY"])


def check_can_pay(steam_id: str) -> dict:
    """Everything that must be true before the Trade action is offered, in order.

    Returns {"ok": True} or {"ok": False, "reason": ..., "fix": ...} so the page can
    explain the refusal instead of just hiding the button.
    """
    link = get_trade_link(steam_id)
    if link is None:
        return {
            "ok": False,
            "reason": "We need your Steam trade URL first.",
            "fix": "account",
        }
    if open_payment(steam_id) is not None:
        return {
            "ok": False,
            "reason": "You already have a payment in progress.",
            "fix": "credits",
        }

    api_key = current_app.config.get("STEAM_API_KEY") or ""
    if not api_key:
        return {
            "ok": False,
            "reason": "Payment is not configured on this deployment.",
            "fix": None,
        }

    try:
        hold = steam_trade.get_trade_hold_duration(
            api_key, steam_id, link["access_token"])
    except SteamUnavailable:
        # Fail closed. Assuming "probably no hold" risks taking keys for a server that
        # cannot arrive in time, which is worse than a temporary refusal.
        return {
            "ok": False,
            "reason": "Steam is not answering right now, so we can't check whether "
                      "your trade would be held. Try again shortly.",
            "fix": None,
        }

    if hold.would_be_held:
        return {
            "ok": False,
            "reason": (
                f"Steam would hold this trade for up to {hold.days} days, which is "
                "longer than the scrim you'd be paying for. Enable the Steam Guard "
                "Mobile Authenticator, wait the qualifying period, and come back."
            ),
            "fix": None,
        }
    return {"ok": True}


def start_payment(steam_id: str, target_scrim_id=None) -> dict:
    """Record the intent to pay and return the row. Raises PaymentError if refused."""
    verdict = check_can_pay(steam_id)
    if not verdict["ok"]:
        raise PaymentError(verdict["reason"])

    now = utc_now()
    db = get_db()
    cur = db.execute(
        """INSERT INTO payments (steam_id, method, state, items_expected,
                                 target_scrim_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (steam_id, METHOD_STEAM_TRADE, STARTED,
         current_app.config["PAYMENT_MIN_KEYS"], target_scrim_id, now, now),
    )
    db.commit()
    return dict(get_db().execute(
        "SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone())


def abandon(steam_id: str, payment_id) -> None:
    """Give up on a payment that was started but never sent.

    Only valid while no Steam offer has been attached — once an offer exists, Steam's
    state is what decides the outcome, and letting a user overwrite that would be a way
    to disown a trade the operator already accepted.
    """
    db = get_db()
    db.execute(
        """UPDATE payments SET state = ?, state_reason = ?, updated_at = ?
           WHERE id = ? AND steam_id = ? AND provider_ref IS NULL
             AND state IN (?, ?)""",
        (FAILED, "Abandoned before a trade was sent.", utc_now(), payment_id,
         steam_id, STARTED, HELD),
    )
    db.commit()


def _set_state(payment_id, state: str, *, reason: str | None = None,
               items_received: int | None = None, hold_until: str | None = None) -> None:
    db = get_db()
    db.execute(
        """UPDATE payments SET state = ?, state_reason = ?, items_received = ?,
                               hold_until = ?, updated_at = ? WHERE id = ?""",
        (state, reason, items_received, hold_until, utc_now(), payment_id),
    )
    db.commit()


def _claim_offer(payment_id, offer_id: str) -> bool:
    """Bind an unclaimed payment row to a Steam offer id.

    The UNIQUE (method, provider_ref) constraint means only one row can ever hold a
    given offer id, so this is what makes crediting exactly-once even if two pollers
    race or one is run twice.
    """
    db = get_db()
    try:
        cur = db.execute(
            """UPDATE payments SET provider_ref = ?, updated_at = ?
               WHERE id = ? AND provider_ref IS NULL""",
            (offer_id, utc_now(), payment_id),
        )
        db.commit()
        return cur.rowcount == 1
    except Exception:
        db.rollback()
        return False


def _payment_for_offer(offer_id: str):
    row = get_db().execute(
        "SELECT * FROM payments WHERE method = ? AND provider_ref = ?",
        (METHOD_STEAM_TRADE, offer_id),
    ).fetchone()
    return dict(row) if row else None


def _oldest_unclaimed(steam_id: str):
    row = get_db().execute(
        """SELECT * FROM payments WHERE steam_id = ? AND method = ?
           AND provider_ref IS NULL AND state IN (?, ?)
           ORDER BY id ASC LIMIT 1""",
        (steam_id, METHOD_STEAM_TRADE, STARTED, HELD),
    ).fetchone()
    return dict(row) if row else None


def _complete(payment: dict, keys: int) -> int:
    """Grant credits and mark the payment complete in one transaction.

    Both halves together or neither: a grant without a completed payment could be
    re-granted on the next poll, and a completed payment without a grant is money taken
    for nothing.
    """
    amount = credits_for_keys(keys)
    db = get_db()
    try:
        # One implicit transaction, one commit: the grant and the state change land
        # together or not at all.
        credits.grant(
            payment["steam_id"], amount,
            f"{keys} × {current_app.config['PAYMENT_ITEM_NAME']}",
            payment_id=payment["id"],
        )
        db.execute(
            """UPDATE payments SET state = ?, state_reason = NULL, items_received = ?,
                                   credits_granted = ?, hold_until = NULL,
                                   updated_at = ? WHERE id = ?""",
            (COMPLETE, keys, amount, utc_now(), payment["id"]),
        )
        db.commit()
        return amount
    except Exception:
        db.rollback()
        raise


def reconcile_offer(offer) -> str | None:
    """Fold one Steam trade offer into our payment records.

    Returns a short description of what changed, or None when nothing did — which is
    the common case, since the poller re-reads every offer on every run.
    """
    existing = _payment_for_offer(offer.offer_id)
    payment = existing or _oldest_unclaimed(offer.partner_steamid64)
    if payment is None:
        # A trade from someone with no payment started — perhaps no account here at
        # all. Not ours to credit; the operator handles it out of band.
        return None
    if payment["state"] == COMPLETE:
        return None  # already credited; the UNIQUE constraint also guarantees this
    if existing is None and not _claim_offer(payment["id"], offer.offer_id):
        return None
    payment = _payment_for_offer(offer.offer_id) or payment

    cfg = current_app.config
    keys = steam_trade.count_payment_items(
        offer, cfg["PAYMENT_ITEM_NAME"], cfg["PAYMENT_ITEM_APPID"])

    if offer.state == steam_trade.STATE_IN_ESCROW:
        # Held: real, signed, and going nowhere for up to 15 days. No credits.
        hold_until = None
        if offer.escrow_end_date:
            from datetime import datetime, timezone
            hold_until = datetime.fromtimestamp(
                offer.escrow_end_date, tz=timezone.utc).isoformat(timespec="seconds")
        _set_state(payment["id"], HELD, items_received=keys, hold_until=hold_until,
                   reason="Steam is holding this trade in escrow.")
        return f"payment {payment['id']} held"

    if offer.state in steam_trade.PENDING_STATES:
        return None  # nothing to do until the operator accepts

    if offer.state in steam_trade.DEAD_STATES:
        _set_state(payment["id"], FAILED, items_received=keys,
                   reason=steam_trade.DEAD_STATE_REASONS.get(
                       offer.state, "The trade did not complete."))
        return f"payment {payment['id']} failed"

    if offer.state == steam_trade.STATE_ACCEPTED:
        if keys < payment["items_expected"]:
            _set_state(
                payment["id"], INSUFFICIENT, items_received=keys,
                reason=(f"Received {keys} × {cfg['PAYMENT_ITEM_NAME']}; "
                        f"{payment['items_expected']} needed."),
            )
            return f"payment {payment['id']} insufficient ({keys} keys)"
        amount = _complete(payment, keys)
        return f"payment {payment['id']} complete (+{amount} credits)"

    return None


def poll_once() -> dict:
    """One reconciliation sweep. Returns a summary for the CLI to print.

    Makes **two** passes on purpose. `active_only=1` excludes terminal states, and
    `Accepted` is terminal — so an active-only poller would watch offers go Active and
    vanish, crediting nobody, silently, forever. The historical pass is what actually
    sees the acceptance.
    """
    api_key = current_app.config.get("STEAM_API_KEY") or ""
    if not api_key:
        raise SteamUnavailable("STEAM_API_KEY is not configured")

    seen, changes = {}, []
    for historical in (False, True):
        for offer in steam_trade.get_received_offers(
                api_key, active_only=True, historical_only=historical):
            if offer.offer_id in seen:
                continue
            seen[offer.offer_id] = True
            change = reconcile_offer(offer)
            if change:
                changes.append(change)
    return {"offers_seen": len(seen), "changes": changes}
