"""Synthetic usage-based SaaS with known, hidden billing errors.

Invoices here are computed independently of revaudit.pricing on purpose: if
both shared code, a pricing bug would be baked into the answer key too.

Besides real leaks the world contains traps that must NOT be flagged (failed
requests, replayed events) and cases the auditor should hand to a human
(a contract term that could not be found, an unexplained credit, a missing invoice).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from .models import (ContractTerms, Discount, Invoice, InvoiceLine, LineKind, OverageRounding,
                     SourceRef, UsageEvent)

FIRST_PERIOD = date(2025, 10, 1)
MONTHS = 12
EVENTS_PER_MONTH = 10


@dataclass(frozen=True)
class Rates:
    stuck_discount: float = 0.25  # contract: billing system never ends the discount
    unbilled_overage: float = 0.10  # account-month with overage: line dropped
    missing_term: float = 0.06  # contract: overage price could not be found in the documents
    service_credit: float = 0.03  # account-month: legitimate credit the contract doesn't explain
    missing_invoice: float = 0.02  # account-month: no invoice issued
    failed_burst: float = 0.08  # trap: failed requests that are not billable
    replayed_events: float = 0.08  # trap: duplicate event ids


@dataclass
class World:
    contracts: list[ContractTerms]
    events: list[UsageEvent]
    invoices: list[Invoice]
    truth: list[dict]


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _cents(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _bill(c: ContractTerms, month: int, units: int, stuck_discount: bool) -> list[InvoiceLine]:
    """What the (possibly buggy) billing system charges."""
    lines = [InvoiceLine(kind=LineKind.BASE_FEE, description="Platform fee", amount=_cents(c.base_fee))]
    if c.discount and (month < c.discount.duration_months or stuck_discount):
        lines.append(InvoiceLine(kind=LineKind.DISCOUNT, description="Introductory discount",
                                 amount=-_cents(c.base_fee * c.discount.rate)))
    extra = units - c.included_units
    if extra > 0:
        if c.overage_rounding is OverageRounding.CEIL_BLOCK:
            blocks = (extra + c.overage_block_size - 1) // c.overage_block_size
            charge = c.overage_block_price * blocks
        else:
            charge = c.overage_block_price * extra / c.overage_block_size
        lines.append(InvoiceLine(kind=LineKind.OVERAGE, description="API usage overage",
                                 amount=_cents(charge)))
    return lines


def _total(lines: list[InvoiceLine]) -> Decimal:
    return sum((l.amount for l in lines), Decimal("0"))


def _contract(rng: random.Random, customer_id: str) -> ContractTerms:
    base_fee = Decimal(rng.choice([500, 1000, 2000, 4000, 8000]))
    block = rng.choice([10_000, 100_000, 1_000_000])
    per_100k = Decimal(rng.choice(["2.00", "2.50", "3.00"]))
    msa, order_form = f"{customer_id}_msa.pdf", f"{customer_id}_order_form.pdf"
    discount = None
    if rng.random() < 0.4:
        discount = Discount(rate=Decimal(rng.choice(["0.10", "0.15", "0.20", "0.25"])),
                            duration_months=rng.choice([3, 6, 12]))
    return ContractTerms(
        contract_id=f"C-{customer_id}",
        customer_id=customer_id,
        start_date=_add_months(FIRST_PERIOD, rng.randint(-8, 5)),
        base_fee=base_fee,
        included_units=int(base_fee) * 250,
        overage_block_size=block,
        overage_block_price=per_100k * block / 100_000,
        overage_rounding=rng.choice(list(OverageRounding)),
        discount=discount,
        sources={
            "start_date": SourceRef(document=msa, page=1, section="1.1"),
            "base_fee": SourceRef(document=msa, page=3, section="3.1"),
            "included_units": SourceRef(document=msa, page=5, section="4.1"),
            "overage_block_size": SourceRef(document=msa, page=5, section="4.2"),
            "overage_block_price": SourceRef(document=msa, page=5, section="4.2"),
            **({"discount": SourceRef(document=order_form, page=1, section="2")} if discount else {}),
        },
    )


def generate(customers: int = 50, seed: int = 7, rates: Rates = Rates()) -> World:
    rng = random.Random(seed)
    world = World([], [], [], [])

    for i in range(customers):
        c = _contract(rng, f"cust-{i:03d}")
        stuck = c.discount is not None and rng.random() < rates.stuck_discount
        term_missing = rng.random() < rates.missing_term
        demand = c.included_units * rng.uniform(0.5, 1.6)
        growth = rng.uniform(-0.02, 0.06)

        for k in range(MONTHS):
            first_day = _add_months(FIRST_PERIOD, k)
            period = first_day.strftime("%Y-%m")
            month = (first_day.year - c.start_date.year) * 12 + first_day.month - c.start_date.month
            if month < 0:
                continue

            units = int(demand * (1 + growth) ** k * rng.uniform(0.85, 1.15))
            traps = _usage_events(rng, world.events, c, first_day, units, rates)

            correct = _bill(c, month, units, stuck_discount=False)
            billed = _bill(c, month, units, stuck_discount=stuck)
            leak_types = ["expired_discount"] if _total(billed) != _total(correct) else []
            if any(l.kind is LineKind.OVERAGE for l in billed) and rng.random() < rates.unbilled_overage:
                billed = [l for l in billed if l.kind is not LineKind.OVERAGE]
                leak_types.append("unbilled_overage")
            leak = _total(correct) - _total(billed)

            reasons = ["missing_term"] if term_missing and units > c.included_units else []
            if not leak_types and rng.random() < rates.service_credit:
                billed.append(InvoiceLine(kind=LineKind.OTHER, description="SLA service credit",
                                          amount=-_cents(c.base_fee * Decimal("0.10"))))
                reasons.append("service_credit")
            if rng.random() < rates.missing_invoice:
                leak, leak_types, billed = _total(correct), ["missing_invoice"], None
                reasons.append("missing_invoice")
            else:
                world.invoices.append(Invoice(invoice_id=f"INV-{period.replace('-', '')}-{i:03d}",
                                              customer_id=c.customer_id, period=period, lines=billed))

            world.truth.append({
                "customer_id": c.customer_id,
                "period": period,
                "expected_verdict": "needs_review" if reasons else ("leak" if leak > 0 else "ok"),
                "leak_types": leak_types,
                "leak_amount": str(leak),
                "review_reasons": reasons,
                "traps": traps,
            })

        if term_missing:
            c = c.model_copy(update={"overage_block_price": None,
                                     "sources": {k: v for k, v in c.sources.items()
                                                 if k != "overage_block_price"}})
        world.contracts.append(c)
    return world


def _usage_events(rng: random.Random, out: list[UsageEvent], c: ContractTerms,
                  first_day: date, units: int, rates: Rates) -> list[str]:
    """Append one month of events for `c`; return the traps planted in it."""
    def at(day: int) -> datetime:
        return datetime(first_day.year, first_day.month, day, rng.randint(0, 23), tzinfo=timezone.utc)

    prefix = f"{c.customer_id}-{first_day:%Y%m}"
    share, rest = divmod(units, EVENTS_PER_MONTH)
    month_events = [UsageEvent(event_id=f"{prefix}-{j}", customer_id=c.customer_id, timestamp=at(1 + 2 * j),
                               units=share + (rest if j == 0 else 0))
                    for j in range(EVENTS_PER_MONTH)]
    traps = []
    if rng.random() < rates.failed_burst:
        month_events.append(UsageEvent(event_id=f"{prefix}-failed", customer_id=c.customer_id,
                                       timestamp=at(15), units=c.included_units, status="failed"))
        traps.append("failed_burst")
    if rng.random() < rates.replayed_events:
        month_events.extend(e.model_copy() for e in rng.sample(month_events[:EVENTS_PER_MONTH], 3))
        traps.append("replayed_events")
    out.extend(month_events)
    return traps
