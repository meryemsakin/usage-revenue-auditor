"""revaudit generate | audit | eval"""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from . import dataset
from .audit import run_audit
from .evaluate import evaluate, format_report
from .models import Verdict
from .synth import generate
from .usage import summarize_usage


def cmd_generate(args: argparse.Namespace) -> None:
    world = generate(customers=args.customers, seed=args.seed)
    dataset.write_dataset(args.out, world.contracts, world.events, world.invoices, world.truth)
    leaks = [t for t in world.truth if Decimal(t["leak_amount"]) > 0]
    print(f"Wrote {len(world.contracts)} contracts, {len(world.events):,} usage events, "
          f"{len(world.invoices):,} invoices to {args.out}")
    print(f"Hidden: {len(leaks)} leaking account-months, "
          f"${sum(Decimal(t['leak_amount']) for t in leaks):,.2f} (answer key: {dataset.TRUTH})")


def cmd_audit(args: argparse.Namespace) -> None:
    findings = run_audit(dataset.load_contracts(args.data),
                         summarize_usage(dataset.load_usage_events(args.data)),
                         dataset.load_invoices(args.data))
    out = args.out or args.data / "findings.json"
    dataset.write_findings(out, findings)

    leaks = sorted((f for f in findings if f.verdict is Verdict.LEAK), key=lambda f: -f.difference)
    reviews = [f for f in findings if f.verdict is Verdict.NEEDS_REVIEW]
    print(f"Audited {len(findings):,} account-months")
    print(f"Leaks: {len(leaks)}  (${sum((f.difference for f in leaks), Decimal('0')):,.2f})")
    print(f"Needs review: {len(reviews)}")
    for f in leaks[:5]:
        kinds = ", ".join(t.value for t in f.leak_types)
        print(f"  {f.customer_id}  {f.period}  ${f.difference:>10,.2f}  {kinds}")
    print(f"Findings written to {out}")


def cmd_eval(args: argparse.Namespace) -> None:
    findings = dataset.load_findings(args.findings or args.data / "findings.json")
    print(format_report(evaluate(findings, dataset.load_truth(args.data))))


def main() -> None:
    parser = argparse.ArgumentParser(prog="revaudit")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("generate", help="create a synthetic dataset with hidden leaks")
    p.add_argument("out", type=Path)
    p.add_argument("--customers", type=int, default=50)
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("audit", help="reconcile contracts, usage and invoices")
    p.add_argument("data", type=Path)
    p.add_argument("--out", type=Path)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("eval", help="score findings against ground_truth.json")
    p.add_argument("data", type=Path)
    p.add_argument("--findings", type=Path)
    p.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
