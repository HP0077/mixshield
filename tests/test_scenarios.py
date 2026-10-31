import pytest

pytest.importorskip("mcp")

from demo import scenarios, viewer  # noqa: E402
from mixshield.proxy import StubScreen  # noqa: E402


def run_scenario(protect, screen):
    state = viewer.new_run("simulated", protect, "b", "Read my latest email and do what is needed")
    for state in scenarios.stream_run(lambda emit: scenarios.simulate(emit, protect, screen), state):
        pass
    return state


def kinds(run):
    return [k for k, _ in run["events"]]


def test_flagged_email_is_blocked_and_events_come_in_order():
    run = run_scenario(True, StubScreen(["bank account badal gaya"]))
    assert kinds(run) == ["email", "screening", "screen", "call", "gate", "result", "done"]
    assert run["screen"]["flagged"] is True
    assert viewer.outcome(run)[:2] == ("red", "BLOCKED")


def test_unflagged_email_makes_the_gate_ask_and_nothing_is_sent():
    run = run_scenario(True, StubScreen([]))
    assert run["screen"]["flagged"] is False
    assert viewer.outcome(run)[:2] == ("amber", "NEEDS YOUR OK")
    assert run["result"]["is_error"] is True


def test_no_mixshield_sends_the_money():
    run = run_scenario(False, None)
    assert kinds(run) == ["email", "call", "result", "done"]
    assert viewer.outcome(run)[:2] == ("red", "MONEY SENT")


def test_a_failing_scenario_becomes_an_error_event():
    async def boom(emit):
        raise RuntimeError("no network")

    state = viewer.new_run("x", True, "b", "t")
    for state in scenarios.stream_run(boom, state):
        pass
    assert state["error"] == "RuntimeError: no network" and state["done"]
