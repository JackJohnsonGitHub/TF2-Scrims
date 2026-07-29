"""The credit ledger (T020).

The invariant that matters: available credits can never go negative, and every movement
is explainable from the ledger rows alone.
"""
import threading

import pytest

from app import credits
from app.credits import InsufficientCredits

PAYER = "76561198000000001"


@pytest.fixture
def payer(app):
    with app.test_request_context():
        from app.accounts import upsert_on_login
        upsert_on_login(PAYER, "Payer", None)
    return PAYER


def test_a_new_account_has_no_credits(app, payer):
    with app.test_request_context():
        assert credits.available_credits(payer) == 0
        assert credits.can_afford(payer) is False


def test_balance_is_the_sum_of_the_ledger(app, payer):
    with app.test_request_context():
        credits.grant(payer, 5, "2 keys")
        from app.db import get_db
        get_db().commit()
        credits.reserve(payer, "scrim 1")
        credits.spend_extension(payer, "extend")

        rows = credits.ledger(payer)
        assert credits.available_credits(payer) == sum(r["delta"] for r in rows)
        assert credits.available_credits(payer) == 3


def test_release_returns_a_reserved_credit(app, payer):
    """FR-067: a server that never ran must not cost anything."""
    with app.test_request_context():
        from app.db import get_db
        credits.grant(payer, 5, "2 keys")
        get_db().commit()
        credits.reserve(payer, "scrim 1", scrim_id=None)
        assert credits.available_credits(payer) == 4
        credits.release(payer, "scrim cancelled")
        assert credits.available_credits(payer) == 5


def test_spending_more_than_you_have_is_refused(app, payer):
    with app.test_request_context():
        from app.db import get_db
        credits.grant(payer, 1, "1 key")
        get_db().commit()
        credits.reserve(payer, "scrim 1")
        with pytest.raises(InsufficientCredits) as err:
            credits.reserve(payer, "scrim 2")
        assert err.value.available == 0
        assert credits.available_credits(payer) == 0  # never negative


def test_extension_at_zero_balance_is_refused(app, payer):
    with app.test_request_context():
        with pytest.raises(InsufficientCredits):
            credits.spend_extension(payer, "extend")
        assert credits.available_credits(payer) == 0


def test_a_grant_must_be_positive(app, payer):
    with app.test_request_context():
        with pytest.raises(ValueError):
            credits.grant(payer, 0, "nothing")
        with pytest.raises(ValueError):
            credits.grant(payer, -3, "negative")


def test_every_ledger_row_carries_a_cause(app, payer):
    """SC-011: a disputed balance has to be explainable without the operator."""
    with app.test_request_context():
        from app.db import get_db
        credits.grant(payer, 5, "2 × Mann Co. Supply Crate Key")
        get_db().commit()
        credits.reserve(payer, "Alpha vs Bravo")
        credits.spend_extension(payer, "+30 min on Alpha vs Bravo")

        rows = credits.ledger(payer)
        assert len(rows) == 3
        assert all(r["cause"] for r in rows)
        assert all(r["kind_label"] for r in rows)
        assert [r["kind"] for r in rows] == ["extend", "reserve", "grant"]  # newest first


def test_concurrent_spends_cannot_drive_the_balance_negative(app, payer):
    """The race the in-statement balance check exists to close: the poller writes from
    a different process than the web workers, so a read-then-write would let two spends
    both see the same balance and both succeed."""
    with app.test_request_context():
        from app.db import get_db
        credits.grant(payer, 3, "grant")
        get_db().commit()

    results = []

    def spend():
        with app.test_request_context():
            try:
                credits.spend_extension(payer, "race")
                results.append("ok")
            except InsufficientCredits:
                results.append("refused")

    threads = [threading.Thread(target=spend) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with app.test_request_context():
        assert credits.available_credits(payer) >= 0
        assert results.count("ok") == 3          # exactly the three credits held
        assert credits.available_credits(payer) == 0


def test_can_afford_gates_on_the_requested_amount(app, payer):
    with app.test_request_context():
        from app.db import get_db
        credits.grant(payer, 2, "grant")
        get_db().commit()
        assert credits.can_afford(payer, 1) is True
        assert credits.can_afford(payer, 2) is True
        assert credits.can_afford(payer, 3) is False
