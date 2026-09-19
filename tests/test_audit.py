from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from revaudit.models import (ContractTerms, Discount, Invoice, InvoiceLine, LeakType, LineKind,
                             OverageRounding, SourceRef, UsageEvent, UsageSummary, Verdict)
from revaudit.pricing import expected_lines
from revaudit.reconcile import reconcile
from revaudit.usage import summarize_usage

D = Decimal


def terms(**overrides) -> ContractTerms:
    base = dict(
        contract_id="C-001", customer_id="apollo", start_date=date(2026, 1, 1),
        base_fee=D("4000"), included_units=1_000_000,
        overage_block_size=100_000, overage_block_price=D("2.50"),
        sources={"overage_block_price": SourceRef(document="apollo_msa.pdf", page=7, section="4.2")},
    )
    return ContractTerms(**(base | overrides))


def usage(units: int, period: str = "2026-08") -> UsageSummary:
    return UsageSummary(customer_id="apollo", period=period, billable_units=units)


def invoice(*lines: tuple[LineKind, str], period: str = "2026-08") -> Invoice:
    return Invoice(invoice_id="INV-2026-0812", customer_id="apollo", period=period,
                   lines=[InvoiceLine(kind=k, description=k.value, amount=D(a)) for k, a in lines])


def amounts(lines):
    return {l.kind: l.amount for l in lines}


# --- pricing -----------------------------------------------------------------

def test_prorata_overage():
    assert amounts(expected_lines(terms(), usage(2_700_000)))[LineKind.OVERAGE] == D("42.50")


def test_ceil_block_overage_charges_started_blocks():
    t = terms(overage_rounding=OverageRounding.CEIL_BLOCK)
    assert amounts(expected_lines(t, usage(1_150_000)))[LineKind.OVERAGE] == D("5.00")


def test_no_overage_line_within_allowance():
    assert LineKind.OVERAGE not in amounts(expected_lines(terms(), usage(1_000_000)))


@pytest.mark.parametrize("period, active", [("2026-01", True), ("2026-06", True), ("2026-07", False)])
def test_discount_applies_only_during_its_window(period, active):
    t = terms(discount=Discount(rate=D("0.20"), duration_months=6))
    lines = amounts(expected_lines(t, usage(0, period)))
    assert (lines.get(LineKind.DISCOUNT) == D("-800.00")) is active


# --- reconciliation ------------------------------------------------------------

def test_unbilled_overage_is_a_leak_with_evidence():
    f = reconcile(terms(), "2026-08", usage(2_700_000), invoice((LineKind.BASE_FEE, "4000")))
    assert f.verdict is Verdict.LEAK
    assert f.leak_types == [LeakType.UNBILLED_OVERAGE]
    assert f.difference == D("42.50")
    assert f.evidence[0].section == "4.2"


def test_discount_still_applied_after_expiry_is_a_leak():
    t = terms(discount=Discount(rate=D("0.20"), duration_months=6))
    f = reconcile(t, "2026-08", usage(0), invoice((LineKind.BASE_FEE, "4000"), (LineKind.DISCOUNT, "-800")))
    assert f.verdict is Verdict.LEAK
    assert f.leak_types == [LeakType.EXPIRED_DISCOUNT]
    assert f.difference == D("800")


def test_correct_invoice_is_ok():
    f = reconcile(terms(), "2026-08", usage(2_700_000),
                  invoice((LineKind.BASE_FEE, "4000"), (LineKind.OVERAGE, "42.50")))
    assert f.verdict is Verdict.OK
    assert f.difference == 0


def test_failed_and_duplicate_events_are_not_billable():
    ts = datetime(2026, 8, 3, tzinfo=timezone.utc)
    events = [
        UsageEvent(event_id="e1", customer_id="apollo", timestamp=ts, units=900_000),
        UsageEvent(event_id="e1", customer_id="apollo", timestamp=ts, units=900_000),  # replay
        UsageEvent(event_id="e2", customer_id="apollo", timestamp=ts, units=500_000, status="failed"),
    ]
    summary = summarize_usage(events)[("apollo", "2026-08")]
    assert (summary.billable_units, summary.duplicate_events, summary.failed_events) == (900_000, 1, 1)
    # Raw volume is 2.3M, but nothing is billable above the allowance: not a leak.
    f = reconcile(terms(), "2026-08", summary, invoice((LineKind.BASE_FEE, "4000")))
    assert f.verdict is Verdict.OK


def test_missing_terms_needs_review_instead_of_guessing():
    f = reconcile(terms(overage_block_price=None), "2026-08", usage(2_700_000),
                  invoice((LineKind.BASE_FEE, "4000")))
    assert f.verdict is Verdict.NEEDS_REVIEW
    assert "overage_block_price" in f.reasons[0]
    assert f.comparisons == []


def test_missing_overage_price_does_not_block_months_within_allowance():
    f = reconcile(terms(overage_block_price=None), "2026-08", usage(900_000),
                  invoice((LineKind.BASE_FEE, "4000")))
    assert f.verdict is Verdict.OK


def test_unexplained_credit_needs_review():
    f = reconcile(terms(), "2026-08", usage(2_700_000),
                  invoice((LineKind.BASE_FEE, "4000"), (LineKind.OTHER, "-42.50")))
    assert f.verdict is Verdict.NEEDS_REVIEW


def test_billing_above_contract_needs_review():
    f = reconcile(terms(), "2026-08", usage(0), invoice((LineKind.BASE_FEE, "4280")))
    assert f.verdict is Verdict.NEEDS_REVIEW
    assert "amendment" in f.reasons[0]


def test_missing_invoice_needs_review():
    assert reconcile(terms(), "2026-08", usage(0), None).verdict is Verdict.NEEDS_REVIEW
