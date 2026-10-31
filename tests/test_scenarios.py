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
    return [event[0] for event in run["events"]]


def test_flagged_email_is_blocked_and_events_come_in_order():
    run = run_scenario(True, StubScreen(["bank account badal gaya"]))
    order = [k for k in kinds(run) if k in ("email", "call", "gate", "result", "done")]
    assert order == ["email", "call", "gate", "result", "done"]
    assert run["screen"]["flagged"] is True and run["screen"]["email"] is True
    assert viewer.outcome(run)[:2] == ("red", "Blocked")


def test_every_tool_output_is_reported_to_the_screen_step():
    run = run_scenario(True, StubScreen(["bank account badal gaya"]))
    tools = {s["tool"] for s in run["screens"]}
    assert {"read_email"} <= tools and len(run["screens"]) > 1  # the inbox list and the email, not only the email
    assert run["screening"] is False  # every "screening" start was followed by its "done"
    assert [s["email"] for s in run["screens"]].count(True) == 1
    assert "outputs checked, 1 flagged" in viewer.render(run) or "output checked, 1 flagged" in viewer.render(run)


def test_unflagged_email_makes_the_gate_ask_and_nothing_is_sent():
    run = run_scenario(True, StubScreen([]))
    assert run["screen"]["flagged"] is False
    assert viewer.outcome(run)[:2] == ("amber", "Needs your OK")
    assert run["result"]["is_error"] is True


def test_no_mixshield_sends_the_money():
    run = run_scenario(False, None)
    assert kinds(run) == ["email", "call", "result", "done"]
    assert viewer.outcome(run)[:2] == ("red", "Money sent")


def test_a_failing_scenario_becomes_an_error_event():
    async def boom(emit):
        raise RuntimeError("no network")

    state = viewer.new_run("x", True, "b", "t")
    for state in scenarios.stream_run(boom, state):
        pass
    assert state["error"] == "RuntimeError: no network" and state["done"]


def test_events_are_saved_with_their_times_and_replay_waits_the_recorded_gaps():
    state = run_scenario(True, StubScreen(["bank account badal gaya"]))
    times = [event[2] for event in state["events"]]
    assert len(times) == len(state["events"]) and times == sorted(times)
    saved = {k: state[k] for k in ("mode", "protected", "banner", "caption", "task", "events")}
    assert viewer.event_times(saved) == times
    waits = []
    frames = [viewer.render(r) for r in scenarios.play(saved, times, 2.0, sleep=waits.append)]
    assert waits == [(b - a) / 2 for a, b in zip([0.0] + times, times)]
    assert len(frames) == len(times) + 1
    assert "Replaying a recorded run at 2x speed" in frames[0] and "Replaying" not in frames[-1]
    assert "Recorded run" in frames[-1] and viewer.outcome(next(scenarios.play(saved, times, 1.0))) is None
