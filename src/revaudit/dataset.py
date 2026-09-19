"""Reads and writes an audit dataset directory.

    contracts.json      structured contract terms (PDF extraction comes later)
    usage_events.csv    raw product usage events
    invoices.csv        one row per invoice line
    ground_truth.json   answer key; only the evaluator reads it
"""
from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import ContractTerms, Finding, Invoice, InvoiceLine, UsageEvent

CONTRACTS = "contracts.json"
USAGE = "usage_events.csv"
INVOICES = "invoices.csv"
TRUTH = "ground_truth.json"

USAGE_FIELDS = ["event_id", "customer_id", "timestamp", "units", "status"]
INVOICE_FIELDS = ["invoice_id", "customer_id", "period", "kind", "description", "amount"]


def load_contracts(directory: Path) -> list[ContractTerms]:
    return [ContractTerms.model_validate(c) for c in json.loads((directory / CONTRACTS).read_text())]


def load_usage_events(directory: Path) -> Iterator[UsageEvent]:
    with open(directory / USAGE, newline="") as f:
        for row in csv.DictReader(f):
            yield UsageEvent.model_validate(row)


def load_invoices(directory: Path) -> dict[tuple[str, str], Invoice]:
    invoices: dict[str, Invoice] = {}
    with open(directory / INVOICES, newline="") as f:
        for row in csv.DictReader(f):
            invoice = invoices.setdefault(row["invoice_id"], Invoice(
                invoice_id=row["invoice_id"], customer_id=row["customer_id"], period=row["period"], lines=[]))
            invoice.lines.append(InvoiceLine(kind=row["kind"], description=row["description"],
                                             amount=row["amount"]))
    by_period: dict[tuple[str, str], Invoice] = {}
    for invoice in invoices.values():
        key = (invoice.customer_id, invoice.period)
        if key in by_period:
            raise ValueError(f"more than one invoice for {key}: "
                             f"{by_period[key].invoice_id}, {invoice.invoice_id}")
        by_period[key] = invoice
    return by_period


def load_truth(directory: Path) -> list[dict]:
    return json.loads((directory / TRUTH).read_text())


def write_dataset(directory: Path, contracts: list[ContractTerms], events: Iterable[UsageEvent],
                  invoices: list[Invoice], truth: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CONTRACTS).write_text(
        json.dumps([c.model_dump(mode="json") for c in contracts], indent=2))
    with open(directory / USAGE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=USAGE_FIELDS)
        writer.writeheader()
        for e in events:
            writer.writerow(e.model_dump(mode="json"))
    with open(directory / INVOICES, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INVOICE_FIELDS)
        writer.writeheader()
        for inv in invoices:
            for line in inv.lines:
                writer.writerow({"invoice_id": inv.invoice_id, "customer_id": inv.customer_id,
                                 "period": inv.period, "kind": line.kind.value,
                                 "description": line.description, "amount": str(line.amount)})
    (directory / TRUTH).write_text(json.dumps(truth, indent=2))


def write_findings(path: Path, findings: list[Finding]) -> None:
    path.write_text(json.dumps([f.model_dump(mode="json") for f in findings], indent=2))


def load_findings(path: Path) -> list[Finding]:
    return [Finding.model_validate(f) for f in json.loads(path.read_text())]
