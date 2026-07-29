"""CLI commands driven by Kubernetes CronJobs.

Deliberately *not* an in-process scheduler. Gunicorn serves this app with two sync
workers, so anything scheduled inside the app would run once per worker — two pollers
racing to credit the same trade, which is the last place to want a race. A separate
invocation has exactly one instance by construction.

Both commands are idempotent and safe to re-run, including after a missed interval.
"""
from datetime import datetime, timedelta, timezone

import click
from flask import current_app
from flask.cli import with_appcontext

from . import payments
from . import servers_store as store
from .steam_trade import SteamUnavailable


def register(app) -> None:
    app.cli.add_command(poll_payments)
    app.cli.add_command(reconcile_servers)


@click.command("poll-payments")
@with_appcontext
def poll_payments():
    """Reconcile the operator's received trade offers into payments and credits."""
    try:
        result = payments.poll_once()
    except SteamUnavailable as exc:
        # Non-zero exit so a CronJob failure is visible, but no payment state moved:
        # Steam having a bad minute must never mark somebody's payment failed.
        click.echo(f"Steam unavailable: {exc}. No payment state changed.", err=True)
        raise SystemExit(1)

    click.echo(f"Saw {result['offers_seen']} offer(s).")
    for change in result["changes"]:
        click.echo(f"  {change}")
    if not result["changes"]:
        click.echo("  nothing to do")


def _parse(stamp):
    if not stamp:
        return None
    when = datetime.fromisoformat(stamp)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


@click.command("reconcile-servers")
@with_appcontext
def reconcile_servers():
    """Advance server states against the clock.

    scheduled → running at the window start, running → in_grace at the window end, and
    in_grace → stopped once the unpaid grace elapses. The grace is granted once per
    server: giving it per window would quietly make every credit buy 45 minutes.
    """
    now = datetime.now(timezone.utc)
    grace = timedelta(minutes=current_app.config["GRACE_MINUTES"])
    moved = []

    for server in store.servers_needing_reconcile():
        starts, ends = _parse(server["window_starts_at"]), _parse(server["window_ends_at"])
        state = server["state"]

        if state in (store.SCHEDULED, store.STARTING) and starts and now >= starts:
            store.set_state(server["id"], store.RUNNING)
            moved.append(f"server {server['id']} → running")
            continue

        if state == store.RUNNING and ends and now >= ends:
            if server["grace_used"]:
                store.set_state(server["id"], store.STOPPED,
                                stopped_reason=store.REASON_TIME_EXPIRED)
                moved.append(f"server {server['id']} → stopped (grace already used)")
            else:
                store.mark_grace_used(server["id"])
                store.set_state(server["id"], store.IN_GRACE)
                moved.append(f"server {server['id']} → in_grace")
            continue

        if state == store.IN_GRACE and ends:
            if now >= ends + grace:
                store.set_state(server["id"], store.STOPPED,
                                stopped_reason=store.REASON_TIME_EXPIRED)
                moved.append(f"server {server['id']} → stopped (grace expired)")
            elif now < ends:
                # An extension pushed the boundary out past now — back to running, with
                # no interruption to anyone playing.
                store.set_state(server["id"], store.RUNNING)
                moved.append(f"server {server['id']} → running (extended)")

    click.echo(f"Reconciled {len(moved)} server(s).")
    for line in moved:
        click.echo(f"  {line}")
