"""Deterministic expected-invoice calculation. No model output is trusted for money."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import ContractTerms, InvoiceLine, LineKind, OverageRounding, UsageSummary

CENT = Decimal("0.01")


def money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def contract_month_index(terms: ContractTerms, period: str) -> int:
    """0 for the month the contract starts in, negative before it."""
    year, month = map(int, period.split("-"))
    return (year - terms.start_date.year) * 12 + (month - terms.start_date.month)


def discount_active(terms: ContractTerms, period: str) -> bool:
    if terms.discount is None:
        return False
    return 0 <= contract_month_index(terms, period) < terms.discount.duration_months


def expected_lines(terms: ContractTerms, usage: UsageSummary) -> list[InvoiceLine]:
    """Lines the invoice for `usage.period` should contain. Terms must be complete."""
    if missing := terms.missing_terms(usage.billable_units):
        raise ValueError(f"cannot price with incomplete terms: {missing}")

    lines = [InvoiceLine(kind=LineKind.BASE_FEE, description="Platform fee",
                         amount=money(terms.base_fee), basis="Contract base fee")]

    if discount_active(terms, usage.period):
        month = contract_month_index(terms, usage.period) + 1
        lines.append(InvoiceLine(
            kind=LineKind.DISCOUNT,
            description="Introductory discount",
            amount=-money(terms.base_fee * terms.discount.rate),
            basis=f"{terms.discount.rate:.0%} off base fee, month {month} of {terms.discount.duration_months}",
        ))

    excess = max(0, usage.billable_units - terms.included_units)
    if excess:
        size, price = terms.overage_block_size, terms.overage_block_price
        if terms.overage_rounding is OverageRounding.CEIL_BLOCK:
            blocks = -(-excess // size)
            amount = blocks * price
            how = f"{blocks} started blocks × ${price}"
        else:
            amount = Decimal(excess) / Decimal(size) * price
            how = f"${price} per {size:,} units, pro rata"
        lines.append(InvoiceLine(
            kind=LineKind.OVERAGE,
            description="Usage overage",
            amount=money(amount),
            basis=f"{usage.billable_units:,} billable − {terms.included_units:,} included "
                  f"= {excess:,} units; {how}",
        ))
    return lines
