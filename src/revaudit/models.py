"""Domain models shared by extraction, pricing and reconciliation.

All money is Decimal. An LLM may only ever fill ContractTerms; every monetary
amount in this package is computed by deterministic code.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, computed_field

Period = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]  # "2026-08"

OVERAGE_TERMS = ("overage_block_size", "overage_block_price")


class SourceRef(BaseModel):
    """Where a fact came from, so a human can check every finding."""

    document: str
    page: int | None = None
    section: str | None = None
    quote: str | None = None


class OverageRounding(str, Enum):
    PRORATA = "prorata"  # $2.50 per 100K: 150K extra costs $3.75
    CEIL_BLOCK = "ceil_block"  # $2.50 per started 100K block: 150K extra costs $5.00


class Discount(BaseModel):
    """Percentage off the base fee for the first `duration_months` of the contract."""

    rate: Decimal = Field(gt=0, le=1)
    duration_months: int = Field(gt=0)


class ContractTerms(BaseModel):
    contract_id: str
    customer_id: str
    start_date: date
    base_fee: Decimal | None = None
    included_units: int | None = Field(default=None, ge=0)
    overage_block_size: int | None = Field(default=None, gt=0)
    overage_block_price: Decimal | None = Field(default=None, ge=0)
    overage_rounding: OverageRounding = OverageRounding.PRORATA
    discount: Discount | None = None
    sources: dict[str, SourceRef] = Field(default_factory=dict)

    def missing_terms(self, billable_units: int | None = None) -> list[str]:
        """Terms needed to price a month that were not found.

        Overage terms only matter when usage exceeds the allowance, so a contract
        with an unreadable overage clause can still be audited in quiet months.
        """
        needed = ["base_fee", "included_units"]
        if billable_units is None or self.included_units is None or billable_units > self.included_units:
            needed += OVERAGE_TERMS
        return [name for name in needed if getattr(self, name) is None]


class UsageEvent(BaseModel):
    event_id: str
    customer_id: str
    timestamp: datetime  # UTC
    units: int = Field(ge=0)
    status: str = "success"


class UsageSummary(BaseModel):
    customer_id: str
    period: Period
    billable_units: int = 0
    raw_events: int = 0
    failed_events: int = 0
    duplicate_events: int = 0


class LineKind(str, Enum):
    BASE_FEE = "base_fee"
    DISCOUNT = "discount"
    OVERAGE = "overage"
    OTHER = "other"


class InvoiceLine(BaseModel):
    kind: LineKind
    description: str
    amount: Decimal  # discounts and credits are negative
    basis: str | None = None  # how an expected amount was derived


class Invoice(BaseModel):
    invoice_id: str
    customer_id: str
    period: Period
    lines: list[InvoiceLine]

    @property
    def total(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0"))


class Verdict(str, Enum):
    LEAK = "leak"
    OK = "ok"
    NEEDS_REVIEW = "needs_review"


class LeakType(str, Enum):
    UNBILLED_OVERAGE = "unbilled_overage"
    EXPIRED_DISCOUNT = "expired_discount"
    UNDERBILLED_BASE_FEE = "underbilled_base_fee"


class LineComparison(BaseModel):
    kind: LineKind
    expected: Decimal
    billed: Decimal
    basis: str | None = None

    @computed_field
    @property
    def difference(self) -> Decimal:
        """Positive means the customer was billed less than the contract requires."""
        return self.expected - self.billed


class Finding(BaseModel):
    customer_id: str
    contract_id: str
    period: Period
    verdict: Verdict
    leak_types: list[LeakType] = Field(default_factory=list)
    comparisons: list[LineComparison] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    evidence: list[SourceRef] = Field(default_factory=list)

    @computed_field
    @property
    def difference(self) -> Decimal:
        return sum((c.difference for c in self.comparisons), Decimal("0"))
