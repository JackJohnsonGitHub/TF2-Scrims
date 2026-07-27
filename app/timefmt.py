"""Template time formatting (feature 004 FR-002/FR-007/FR-009).

Scrim timestamps are stored as ISO-8601 UTC strings (003 convention). These
helpers are the single place that turns one into something a person reads.

Rendering is a two-step: the server emits the instant in UTC (`Jul 29 1:52 AM
UTC`) wrapped in a `<time>` element carrying the machine-readable stamp, and a
small script in the page shell rewrites the text into the *viewer's* timezone
(`Jul 28 9:52 PM EDT`). Without JavaScript the UTC text stands on its own, so a
time is never wrong — only less convenient. Registered as Jinja filters in
`create_app`.
"""
from datetime import datetime, timezone

from markupsafe import Markup, escape


def _parse(value) -> datetime | None:
    """Best-effort parse; naive stamps are UTC (003 convention). None on junk."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _human(moment: datetime) -> str:
    """`Jul 29 1:52 AM UTC` — month, day, 12-hour clock, zone label."""
    return moment.strftime("%b %d %-I:%M %p UTC")


def pretty_utc(value) -> str:
    """Readable UTC text. Unparseable input passes through so a template never
    renders an exception."""
    parsed = _parse(value)
    if parsed is None:
        return "" if value is None else str(value)
    return _human(parsed.astimezone(timezone.utc))


def local_dt(value) -> Markup:
    """A `<time class="ts">` element: UTC text server-side, rewritten to the
    viewer's timezone by the shell script (FR-002). Falls back to plain text when
    the value can't be parsed."""
    parsed = _parse(value)
    if parsed is None:
        return Markup(str(escape("" if value is None else str(value))))
    moment = parsed.astimezone(timezone.utc)
    return Markup(
        f'<time class="ts" datetime="{escape(moment.isoformat(timespec="seconds"))}">'
        f"{escape(_human(moment))}</time>"
    )


def age_since(value, now: datetime | None = None) -> str:
    """How long ago a timestamp was: "just now", "5 hours ago", "2 days ago"
    (FR-009's posting age). Future stamps read as "just now"."""
    parsed = _parse(value)
    if parsed is None:
        return ""
    seconds = int(((now or datetime.now(timezone.utc)) - parsed).total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        count = seconds // size
        if count >= 1:
            return f"{count} {unit}{'s' if count > 1 else ''} ago"
    return "just now"
