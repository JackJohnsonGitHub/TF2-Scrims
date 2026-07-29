"""Credits: the balance, the ledger, and starting a payment.

`POST /credits/trade/start` enforces its preconditions in a fixed order — trade link on
file, then no predicted escrow hold, then no payment already in flight — because each
one has a different fix and a user deserves to be told which applies.
"""
from flask import (Blueprint, abort, current_app, redirect, render_template, request,
                   url_for)

from .. import credits, payments
from ..payments import PaymentError
from ..security import current_user, login_required, safe_next

bp = Blueprint("credits", __name__)


@bp.get("/credits")
@login_required
def index():
    steam_id = current_user()["steam_id"]
    return render_template(
        "credits.html",
        balance=credits.available_credits(steam_id),
        ledger=credits.ledger(steam_id),
        payments=payments.recent_payments(steam_id),
        open_payment=payments.open_payment(steam_id),
        can_pay=payments.check_can_pay(steam_id),
        price=payments.price_summary(),
        trade_link=payments.get_trade_link(steam_id),
    )


@bp.post("/credits/trade/start")
@login_required
def start_trade():
    """Record the intent to pay, then hand the browser to Steam.

    The operator's trade URL carries a token, so it is only ever used as a redirect
    destination — it is never rendered into a page.
    """
    steam_id = current_user()["steam_id"]
    scrim_id = request.form.get("scrim_id") or None
    try:
        payments.start_payment(steam_id, target_scrim_id=scrim_id)
    except PaymentError as exc:
        return render_template(
            "credits.html",
            balance=credits.available_credits(steam_id),
            ledger=credits.ledger(steam_id),
            payments=payments.recent_payments(steam_id),
            open_payment=payments.open_payment(steam_id),
            can_pay={"ok": False, "reason": str(exc), "fix": None},
            price=payments.price_summary(),
            trade_link=payments.get_trade_link(steam_id),
        ), exc.status

    destination = current_app.config.get("OPERATOR_TRADE_URL") or ""
    if not destination:
        # Configured-off deployments must not pretend the trade started.
        abort(503)
    return redirect(destination)


@bp.post("/credits/cancel/<int:payment_id>")
@login_required
def cancel(payment_id):
    """Abandon a payment the user never actually sent, so they are not stuck behind the
    one-at-a-time rule. Only ever applies to a payment with no Steam offer attached."""
    steam_id = current_user()["steam_id"]
    payments.abandon(steam_id, payment_id)
    return redirect(safe_next(request.form.get("next")) or url_for("credits.index"))
