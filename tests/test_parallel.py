import threading
import time

import pytest

from bench.budget import Budget, BudgetExceeded
from bench.parallel import run_parallel


def test_budget_total_is_exact_across_threads():
    budget = Budget(max_usd=1000)

    def work():
        for _ in range(1000):
            budget.add(10, 5)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert budget.input_tokens == 80_000
    assert budget.output_tokens == 40_000
    assert not budget.exhausted


def test_budget_sets_exhausted_and_check_raises():
    budget = Budget(max_usd=0.001)
    budget.check()  # not exhausted yet
    with pytest.raises(BudgetExceeded):
        budget.add(1_000_000, 0)
    assert budget.exhausted
    with pytest.raises(BudgetExceeded):
        budget.check()


def test_run_parallel_keeps_order_and_limits_workers():
    running, peak, lock = 0, 0, threading.Lock()

    def run_one(job):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return {"job": job}

    results = run_parallel(list(range(12)), run_one, 4, Budget(1))
    assert [job for job, _, _ in results] == list(range(12))
    assert all(status == "ok" for _, _, status in results)
    assert peak <= 4


def test_run_parallel_rejects_more_than_4_workers():
    with pytest.raises(ValueError):
        run_parallel([1], lambda j: {}, 5, Budget(1))


def test_run_parallel_stops_cleanly_when_budget_is_used_up():
    budget = Budget(max_usd=1.25)  # $1.25 = 1,000,000 input tokens

    def run_one(job):
        budget.check()
        time.sleep(0.01)
        budget.add(400_000, 0)  # the third call passes the cap
        return {"job": job}

    results = run_parallel(list(range(20)), run_one, 4, budget)
    statuses = [status for _, _, status in results]
    assert "ok" in statuses
    assert "stopped by budget" in statuses or "not started" in statuses
    assert statuses.count("ok") < 20
    assert budget.exhausted
    # No job started after the cap was passed: calls in flight at that moment (at most 4) were still counted.
    assert budget.input_tokens <= 400_000 * (3 + 4)
