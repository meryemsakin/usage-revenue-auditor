"""Runs reconciliation for every contract and month in a dataset."""
from __future__ import annotations

from .models import ContractTerms, Finding, Invoice, UsageSummary
from .pricing import contract_month_index
from .reconcile import reconcile


def run_audit(contracts: list[ContractTerms],
              usage: dict[tuple[str, str], UsageSummary],
              invoices: dict[tuple[str, str], Invoice]) -> list[Finding]:
    periods = sorted({p for _, p in usage} | {p for _, p in invoices})
    findings = []
    for terms in contracts:
        for period in periods:
            key = (terms.customer_id, period)
            before_start = contract_month_index(terms, period) < 0
            if before_start and key not in usage and key not in invoices:
                continue
            findings.append(reconcile(terms, period, usage.get(key), invoices.get(key)))
    return findings
