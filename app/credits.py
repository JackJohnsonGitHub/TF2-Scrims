"""The credit ledger: the entitlement that lets a server run.

A credit is one hour of server runtime (constitution v3.1.0, Principle VIII). Credits
are granted when a payment completes, reserved when a server is attached to a scrim,
returned if that server never ran, and spent to extend a running one.

**The ledger is append-only and is the only source of truth for a balance.** Available
credits are `SUM(delta)` — there is deliberately no cached total, because a cached total
can drift from these rows and then the ledger stops being trustworthy for exactly the
dispute it exists to settle (FR-068, SC-011).

Four kinds move a balance:

    grant    +n   a payment completed
    reserve  -1   earmarked for a scrim's server
    release  +1   that server never ran, so the credit comes back
    extend   -1   bought more time on a running server

There is no separate `spend` delta. A credit leaves the available balance the moment it
is reserved; subtracting again when the window opens would charge twice for one hour.
The reserved-versus-consumed distinction lives in the server's state (`scheduled` vs
`running`), which is what decides whether a release is still possible.
"""
from .db import get_db, transaction
from .rgl_store import utc_now

GRANT = "grant"
RESERVE = "reserve"
RELEASE = "release"
EXTEND = "extend"

KIND_LABELS = {
    GRANT: "Purchased",
    RESERVE: "Reserved for a scrim",
    RELEASE: "Returned",
    EXTEND: "Extension",
}


class InsufficientCredits(ValueError):
    """Not enough available credits for the action. Routes turn this into a refusal
    that names the balance and offers the way to buy more."""

    def __init__(self, needed: int, available: int):
        super().__init__(
            f"Needs {needed} credit{'s' if needed != 1 else ''}; "
            f"you have {available}."
        )
        self.needed = needed
        self.available = available


def available_credits(steam_id: str) -> int:
    """Credits this account can spend right now. Derived, never stored."""
    row = get_db().execute(
        "SELECT COALESCE(SUM(delta), 0) AS total FROM credit_ledger WHERE steam_id = %s",
        (steam_id,),
    ).fetchone()
    return int(row["total"])


def _entry(steam_id: str, delta: int, kind: str, cause: str, *,
           payment_id=None, scrim_id=None, server_id=None) -> int:
    db = get_db()
    cur = db.execute(
        """INSERT INTO credit_ledger (steam_id, delta, kind, cause, payment_id,
                                      scrim_id, server_id, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (steam_id, delta, kind, cause, payment_id, scrim_id, server_id, utc_now()),
    )
    return cur.fetchone()["id"]


def _spend(steam_id: str, amount: int, kind: str, cause: str, *,
           payment_id=None, scrim_id=None, server_id=None) -> int:
    """Take `amount` credits, refusing if the balance cannot cover it.

    The balance check lives *inside* the INSERT rather than as a separate SELECT, and the
    account's row is locked first. **Both are required, and the second one is new.**

    The conditional insert alone was correct under SQLite only because SQLite has a single
    global writer, so one statement genuinely could not interleave with itself. Postgres
    runs at READ COMMITTED: two concurrent spends of the same account's last credit each
    evaluate the WHERE against a snapshot taken before either insert, both see a
    sufficient balance, and both insert. The balance goes to −1 — silently, on the paid
    compute path, looking from the outside exactly like a page that worked (research R9).

    `SELECT … FOR UPDATE` on the account's own row serializes exactly the transactions
    that could race on this balance, and nothing else:

    - **Per-account.** Two different users spending at the same moment take different
      locks and never wait on each other, which is what FR-008 requires.
    - **The `users` row always exists** — every `credit_ledger.steam_id` is a foreign key
      to it — so the lock always has a target.
    - **No network I/O inside the lock.** `spend_extension` is the mid-match path that
      must complete in seconds; it stays a pure local write.
    - Released by commit or rollback. No leak path.

    A cached balance column with a CHECK constraint would also prevent the negative, and
    is forbidden: FR-013 and constitution VIII require the balance be derivable from the
    ledger, never a stored total that can disagree with the rows explaining it.
    """
    with transaction() as db:
        db.execute("SELECT 1 FROM users WHERE steam_id = %s FOR UPDATE", (steam_id,))
        cur = db.execute(
            """INSERT INTO credit_ledger (steam_id, delta, kind, cause, payment_id,
                                          scrim_id, server_id, created_at)
               SELECT %s, %s, %s, %s, %s, %s, %s, %s
               WHERE (SELECT COALESCE(SUM(delta), 0) FROM credit_ledger
                      WHERE steam_id = %s) >= %s
               RETURNING id""",
            (steam_id, -amount, kind, cause, payment_id, scrim_id, server_id, utc_now(),
             steam_id, amount),
        )
        if cur.rowcount != 1:
            # Read the balance before the rollback releases the lock, so the number in
            # the message is the one the refusal was actually made against.
            available = available_credits(steam_id)
            raise InsufficientCredits(amount, available)
        return cur.fetchone()["id"]


def grant(steam_id: str, amount: int, cause: str, *, payment_id=None) -> int:
    """Credit a completed payment.

    Does not commit: the caller marks the payment complete in the same transaction, so
    that a crash cannot leave a grant with no completed payment (which the next poll
    would grant again) or a completed payment with no grant (money for nothing).
    """
    if amount <= 0:
        raise ValueError("A grant must be positive.")
    return _entry(steam_id, amount, GRANT, cause, payment_id=payment_id)


def reserve(steam_id: str, cause: str, *, scrim_id=None, server_id=None) -> int:
    """Earmark one credit for a scrim's server."""
    return _spend(steam_id, 1, RESERVE, cause, scrim_id=scrim_id, server_id=server_id)


def release(steam_id: str, cause: str, *, scrim_id=None, server_id=None) -> int:
    """Give a reserved credit back — the server never ran, so it was never used.

    FR-067 and Principle VII: a team must never be charged for a server it did not
    get, whether the scrim was cancelled or the server could not be placed.
    """
    entry_id = _entry(steam_id, 1, RELEASE, cause,
                      scrim_id=scrim_id, server_id=server_id)
    get_db().commit()
    return entry_id


def spend_extension(steam_id: str, cause: str, *, server_id=None) -> int:
    """Buy more time on a running server. Deliberately does no network I/O: this is
    the mid-match path, and it has to complete in seconds."""
    return _spend(steam_id, 1, EXTEND, cause, server_id=server_id)


def ledger(steam_id: str, limit: int = 200) -> list[dict]:
    """Every movement, newest first, with its cause — so a disputed balance can be
    explained without the operator's help."""
    rows = get_db().execute(
        """SELECT * FROM credit_ledger WHERE steam_id = %s
           ORDER BY id DESC LIMIT %s""",
        (steam_id, limit),
    ).fetchall()
    return [{**dict(r), "kind_label": KIND_LABELS.get(r["kind"], r["kind"])}
            for r in rows]


def can_afford(steam_id: str, amount: int = 1) -> bool:
    """Whether to offer a credit-spending action at all. An action the balance cannot
    cover MUST NOT be rendered (FR-065) — but the server side still re-checks, because
    an un-rendered action is not a security control."""
    return available_credits(steam_id) >= amount
