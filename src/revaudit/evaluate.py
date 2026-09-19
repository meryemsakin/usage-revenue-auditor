"""Scores findings against the answer key.

Dollar recall alone flatters a system that flags everything, so false alarms,
wrong amounts and review load are reported next to it.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from .models import Finding, Verdict

VERDICTS = [v.value for v in Verdict]


def evaluate(findings: list[Finding], truth: list[dict]) -> dict:
    by_key = {(f.customer_id, f.period): f for f in findings}
    truth_keys = {(t["customer_id"], t["period"]) for t in truth}
    confusion: Counter[tuple[str, str]] = Counter()
    hidden = detected = routed_to_review = false_alarm_dollars = Decimal("0")
    tp = fp = fn = wrong_amount = 0
    trap_false_alarms = 0
    missed: list[dict] = []

    for t in truth:
        f = by_key.get((t["customer_id"], t["period"]))
        predicted = f.verdict.value if f else "missing"
        confusion[(t["expected_verdict"], predicted)] += 1
        amount = Decimal(t["leak_amount"])
        if amount > 0:
            hidden += amount
        if predicted == Verdict.LEAK.value:
            if amount > 0:
                tp += 1
                detected += amount
                wrong_amount += abs(f.difference - amount) > Decimal("0.01")
            else:
                fp += 1
                false_alarm_dollars += f.difference
                trap_false_alarms += bool(t["traps"])
        elif amount > 0:
            fn += 1
            if predicted == Verdict.NEEDS_REVIEW.value:
                routed_to_review += amount
            else:
                missed.append(t)

    extra = [f for k, f in by_key.items() if k not in truth_keys and f.verdict is Verdict.LEAK]
    fp += len(extra)
    false_alarm_dollars += sum((f.difference for f in extra), Decimal("0"))

    reviews = sum(1 for f in findings if f.verdict is Verdict.NEEDS_REVIEW)
    return {
        "account_months": len(truth),
        "hidden_leak_dollars": hidden,
        "detected_dollars": detected,
        "dollar_recall": detected / hidden if hidden else None,
        "dollars_routed_to_review": routed_to_review,
        "dollars_missed": hidden - detected - routed_to_review,
        "case_precision": tp / (tp + fp) if tp + fp else None,
        "case_recall": tp / (tp + fn) if tp + fn else None,
        "false_alarms": fp,
        "false_alarm_dollars": false_alarm_dollars,
        "false_alarms_on_traps": trap_false_alarms,
        "wrong_amounts": wrong_amount,
        "review_cases": reviews,
        "review_rate": reviews / len(findings) if findings else None,
        "confusion": {f"{e} -> {p}": n for (e, p), n in sorted(confusion.items())},
        "missed_examples": missed[:5],
    }


def format_report(m: dict) -> str:
    def pct(x):
        return "n/a" if x is None else f"{x:.1%}"

    rows = [
        ("Account-months audited", f"{m['account_months']:,}"),
        ("Hidden leakage", f"${m['hidden_leak_dollars']:,.2f}"),
        ("Detected automatically", f"${m['detected_dollars']:,.2f}  ({pct(m['dollar_recall'])} dollar recall)"),
        ("Routed to human review", f"${m['dollars_routed_to_review']:,.2f}"),
        ("Missed", f"${m['dollars_missed']:,.2f}"),
        ("Case precision / recall", f"{pct(m['case_precision'])} / {pct(m['case_recall'])}"),
        ("False alarms", f"{m['false_alarms']} (${m['false_alarm_dollars']:,.2f}), "
                         f"{m['false_alarms_on_traps']} on trap months"),
        ("Leaks with wrong amount", str(m["wrong_amounts"])),
        ("Review cases", f"{m['review_cases']} ({pct(m['review_rate'])} of account-months)"),
    ]
    width = max(len(k) for k, _ in rows)
    lines = [f"{k:<{width}}  {v}" for k, v in rows]
    lines += ["", "Expected -> predicted verdicts:"]
    lines += [f"  {k:<32} {n:>5}" for k, n in m["confusion"].items()]
    return "\n".join(lines)
