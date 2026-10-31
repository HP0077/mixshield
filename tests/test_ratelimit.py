from types import SimpleNamespace

from demo.ratelimit import COST, RateLimiter, visitor_id


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_three_runs_a_minute_per_visitor_then_refused_then_allowed_again():
    clock = Clock()
    limiter = RateLimiter(per_minute=3, daily_budget=100, clock=clock)
    assert all(limiter.check("a", "direct")[0] for _ in range(3))
    ok, message = limiter.check("a", "direct")
    assert not ok and "at most 3 per minute" in message
    assert limiter.check("b", "direct")[0]  # another visitor is not affected
    clock.now += 61
    assert limiter.check("a", "direct")[0]


def test_daily_budget_stops_runs_that_cost_money_and_resets_next_day(tmp_path):
    clock = Clock()
    limiter = RateLimiter(per_minute=100, daily_budget=0.05, state_file=tmp_path / "b.json", clock=clock)
    assert limiter.check("a", "simulated")[0] and limiter.check("b", "simulated")[0]  # 0.04
    ok, message = limiter.check("c", "simulated")  # 0.06 > 0.05
    assert not ok and "daily budget" in message
    assert limiter.check("d", "direct")[0]  # free runs still work
    clock.now += 86400
    assert limiter.check("c", "simulated")[0]


def test_the_days_total_survives_a_restart(tmp_path):
    clock = Clock()
    first = RateLimiter(per_minute=100, daily_budget=0.05, state_file=tmp_path / "b.json", clock=clock)
    first.check("a", "simulated")
    first.check("a", "simulated")
    second = RateLimiter(per_minute=100, daily_budget=0.05, state_file=tmp_path / "b.json", clock=clock)
    assert not second.check("a", "simulated")[0]


def test_refused_runs_cost_nothing_and_off_switch_allows_everything():
    limiter = RateLimiter(per_minute=1, daily_budget=100, clock=Clock())
    limiter.check("a", "agent")
    spent = limiter.spent
    assert not limiter.check("a", "agent")[0] and limiter.spent == spent
    off = RateLimiter(per_minute=1, daily_budget=0, enabled=False)
    assert all(off.check("a", "agent")[0] for _ in range(5))


def test_broken_state_file_starts_the_day_at_zero(tmp_path):
    (tmp_path / "b.json").write_text("not json", encoding="utf-8")
    assert RateLimiter(state_file=tmp_path / "b.json").spent == 0.0


def test_every_run_kind_has_a_cost_and_the_model_runs_cost_money():
    assert COST["direct"] == 0 and COST["replay"] == 0
    assert COST["simulated"] > 0 and COST["agent"] > COST["simulated"] and COST["check"] > 0


def test_visitor_id_uses_the_first_forwarded_address():
    request = SimpleNamespace(headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"}, client=SimpleNamespace(host="10.0.0.1"))
    assert visitor_id(request) == "1.2.3.4"
    assert visitor_id(SimpleNamespace(headers={}, client=SimpleNamespace(host="9.9.9.9"))) == "9.9.9.9"
    assert visitor_id(None) == "unknown"
