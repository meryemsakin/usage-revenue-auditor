from decimal import Decimal

from revaudit.audit import run_audit
from revaudit.evaluate import evaluate
from revaudit.synth import generate
from revaudit.usage import summarize_usage


def test_generated_world_round_trip():
    world = generate(customers=40, seed=3)
    invoices = {(i.customer_id, i.period): i for i in world.invoices}
    findings = run_audit(world.contracts, summarize_usage(world.events), invoices)
    m = evaluate(findings, world.truth)

    assert m["hidden_leak_dollars"] > 0
    assert m["false_alarms"] == 0
    assert m["wrong_amounts"] == 0
    assert m["dollars_missed"] == Decimal("0")
    assert all(expected == predicted for expected, predicted in
               (key.split(" -> ") for key in m["confusion"]))


def test_generation_is_reproducible():
    a, b = generate(customers=10, seed=1), generate(customers=10, seed=1)
    assert a.truth == b.truth
