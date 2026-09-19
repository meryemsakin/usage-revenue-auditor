# Usage-to-Revenue Auditor

Reconciles **what was promised** (contracts), **what happened** (product usage) and
**what was charged** (invoices) to find unbilled revenue in usage-based SaaS.

Status: early. Deterministic engine and synthetic benchmark work end to end on
structured contract terms. LLM extraction from contract PDFs is next.

## Design rules
- Language models only extract contract terms, with a source for every field.
  Every amount is computed in code with `Decimal`.
- Each account-month gets one of three verdicts: `leak`, `ok` or `needs_review`.
  Missing or contradictory inputs go to a human instead of producing a guessed amount.
- Raw usage is not billable usage: failed and replayed events are excluded first.

## Run
```bash
uv sync
uv run revaudit generate data/demo   # synthetic world + hidden answer key
uv run revaudit audit data/demo      # writes data/demo/findings.json
uv run revaudit eval data/demo       # scores findings against ground_truth.json
uv run pytest
```

The synthetic world plants real leaks (unbilled overage, discounts that never
expired), traps that must not be flagged (failed requests, replayed events) and
cases a human should decide (unreadable contract terms, unexplained credits,
missing invoices). Its invoices are computed independently of the engine, so a
pricing bug in the engine cannot leak into the answer key.

With structured terms the engine is expected to score perfectly; that run checks
the plumbing, not the AI. The benchmark becomes meaningful once terms are read
from PDFs.
