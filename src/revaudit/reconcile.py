"""Compares the expected invoice with the one actually issued.

Three outcomes, on purpose: a leak, a clean invoice, or a case the system
refuses to decide. Guessing an amount is worse than asking a human.
"""
from __future__ import annotations

from decimal import Decimal

from .models import (ContractTerms, Finding, Invoice, LeakType, LineComparison, LineKind,
                     SourceRef, UsageSummary, Verdict)
from .pricing import contract_month_index, expected_lines

TOLERANCE = Decimal("0.01")

LEAK_BY_KIND = {
    LineKind.BASE_FEE: LeakType.UNDERBILLED_BASE_FEE,
    LineKind.DISCOUNT: LeakType.EXPIRED_DISCOUNT,
    LineKind.OVERAGE: LeakType.UNBILLED_OVERAGE,
}

TERMS_BY_LEAK = {
    LeakType.UNBILLED_OVERAGE: ("included_units", "overage_block_size", "overage_block_price"),
    LeakType.EXPIRED_DISCOUNT: ("discount", "start_date"),
    LeakType.UNDERBILLED_BASE_FEE: ("base_fee",),
}


def reconcile(terms: ContractTerms, period: str,
              usage: UsageSummary | None, invoice: Invoice | None) -> Finding:
    finding = Finding(customer_id=terms.customer_id, contract_id=terms.contract_id,
                      period=period, verdict=Verdict.NEEDS_REVIEW)

    if missing := terms.missing_terms(usage.billable_units if usage else None):
        finding.reasons.append(f"Contract terms not found: {', '.join(missing)}")
    if contract_month_index(terms, period) < 0:
        finding.reasons.append("Period precedes contract start")
    if usage is None:
        finding.reasons.append("No usage records for period")
    if invoice is None:
        finding.reasons.append("No invoice for period")
    if finding.reasons:
        return finding

    expected = expected_lines(terms, usage)
    finding.comparisons = [
        LineComparison(
            kind=kind,
            expected=sum((l.amount for l in expected if l.kind is kind), Decimal("0")),
            billed=sum((l.amount for l in invoice.lines if l.kind is kind), Decimal("0")),
            basis=next((l.basis for l in expected if l.kind is kind), None),
        )
        for kind in (LineKind.BASE_FEE, LineKind.DISCOUNT, LineKind.OVERAGE)
    ]
    finding.evidence = [
        SourceRef(document="usage_events.csv",
                  quote=f"{usage.billable_units:,} billable units in {period} "
                        f"({usage.failed_events} failed, {usage.duplicate_events} duplicate events excluded)"),
        SourceRef(document=f"invoice {invoice.invoice_id}",
                  quote="; ".join(f"{l.description}: {l.amount}" for l in invoice.lines)),
    ]

    if unknown := [l for l in invoice.lines if l.kind is LineKind.OTHER]:
        finding.reasons.append("Invoice has line items the contract does not explain: "
                               + ", ".join(l.description for l in unknown))
    for c in finding.comparisons:
        if c.difference < -TOLERANCE:
            finding.reasons.append(f"{c.kind.value} billed above contract by {-c.difference}; "
                                   "possible overbilling or an amendment not on file")
    if finding.reasons:
        return finding

    finding.leak_types = [LEAK_BY_KIND[c.kind] for c in finding.comparisons if c.difference > TOLERANCE]
    if not finding.leak_types:
        finding.verdict = Verdict.OK
        return finding

    finding.verdict = Verdict.LEAK
    for leak in finding.leak_types:
        for term in TERMS_BY_LEAK[leak]:
            if term in terms.sources:
                finding.evidence.insert(0, terms.sources[term])
    return finding
