"""Turns raw usage events into billable units per customer and month."""
from __future__ import annotations

from collections.abc import Iterable

from .models import UsageEvent, UsageSummary


def summarize_usage(events: Iterable[UsageEvent]) -> dict[tuple[str, str], UsageSummary]:
    """Aggregate events by (customer_id, period).

    Failed requests are not billable, and a replayed event_id is counted once:
    raw usage that looks like overage is often neither.
    """
    summaries: dict[tuple[str, str], UsageSummary] = {}
    seen: set[str] = set()
    for event in events:
        period = event.timestamp.strftime("%Y-%m")
        key = (event.customer_id, period)
        summary = summaries.setdefault(key, UsageSummary(customer_id=event.customer_id, period=period))
        summary.raw_events += 1
        if event.event_id in seen:
            summary.duplicate_events += 1
            continue
        seen.add(event.event_id)
        if event.status != "success":
            summary.failed_events += 1
            continue
        summary.billable_units += event.units
    return summaries
