"""Unit tests for the shared template time helpers: readable UTC text server-side
wrapped in a `<time>` element the shell script localizes (004 FR-002/FR-007), and
a relative posting age (FR-009)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.timefmt import age_since, local_dt, pretty_utc

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def ago(**delta):
    return (NOW - timedelta(**delta)).isoformat(timespec="seconds")


@pytest.mark.parametrize("value,expected", [
    ("2026-07-29T01:52:00+00:00", "Jul 29 1:52 AM UTC"),
    ("2026-07-29T01:52:00", "Jul 29 1:52 AM UTC"),  # naive == UTC (003 convention)
    ("2026-01-01T19:30:00+00:00", "Jan 01 7:30 PM UTC"),
    ("2026-07-28T21:52:00-04:00", "Jul 29 1:52 AM UTC"),  # offsets normalize to UTC
    (datetime(2026, 7, 29, 13, 5, tzinfo=timezone.utc), "Jul 29 1:05 PM UTC"),
])
def test_pretty_utc_reads_as_month_day_clock(value, expected):
    assert pretty_utc(value) == expected


def test_pretty_utc_passes_unparseable_values_through():
    assert pretty_utc("not a time") == "not a time"
    assert pretty_utc(None) == ""


def test_local_dt_carries_the_instant_for_the_browser():
    markup = str(local_dt("2026-07-29T01:52:00+00:00"))
    # machine-readable stamp drives the client-side timezone rewrite...
    assert 'datetime="2026-07-29T01:52:00+00:00"' in markup
    assert 'class="ts"' in markup
    # ...while the rendered text is the no-JS fallback, never a wrong time.
    assert ">Jul 29 1:52 AM UTC</time>" in markup


def test_local_dt_escapes_and_degrades_on_junk():
    assert str(local_dt("<script>x</script>")) == "&lt;script&gt;x&lt;/script&gt;"
    assert str(local_dt(None)) == ""


@pytest.mark.parametrize("delta,expected", [
    ({"seconds": 5}, "just now"),
    ({"minutes": 1}, "1 minute ago"),
    ({"minutes": 40}, "40 minutes ago"),
    ({"hours": 1}, "1 hour ago"),
    ({"hours": 5}, "5 hours ago"),
    ({"days": 1}, "1 day ago"),
    ({"days": 9}, "9 days ago"),
])
def test_age_since_reads_as_an_age(delta, expected):
    assert age_since(ago(**delta), now=NOW) == expected


def test_age_since_tolerates_future_stamps_and_garbage():
    assert age_since((NOW + timedelta(hours=2)).isoformat(), now=NOW) == "just now"
    assert age_since("nonsense") == ""
    assert age_since(None) == ""
