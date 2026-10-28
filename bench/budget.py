"""Dollar cap for a script run. Checked after every model call, so a retry loop is stopped mid-run.

Thread-safe: parallel runs share one Budget (one running total). Once the cap is passed, `exhausted` is set, the
call that passed it raises BudgetExceeded, and every later `check()` or `add()` raises too, so all threads stop.
Calls already in flight when the cap is passed still finish and are counted, so the final spend can be a little
above the cap (at most one call per running thread).
"""

import threading

# Prices in USD per million tokens, same for both models (given by Huzaifa on Day 2).
DEFAULT_USD_PER_M_IN = 1.25
DEFAULT_USD_PER_M_OUT = 4.25


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, max_usd: float, usd_per_m_in: float = DEFAULT_USD_PER_M_IN,
                 usd_per_m_out: float = DEFAULT_USD_PER_M_OUT) -> None:
        self.max_usd = max_usd
        self.usd_per_m_in = usd_per_m_in
        self.usd_per_m_out = usd_per_m_out
        self.input_tokens = 0
        self.output_tokens = 0
        self.exhausted = False
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        return (self.input_tokens * self.usd_per_m_in + self.output_tokens * self.usd_per_m_out) / 1e6

    def check(self) -> None:
        """Call before a model call: raises if the cap was already passed."""
        if self.exhausted:
            raise BudgetExceeded(f"budget of ${self.max_usd:.2f} already used up")

    def add(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            if self.spent_usd > self.max_usd:
                self.exhausted = True
                raise BudgetExceeded(f"spent ${self.spent_usd:.2f} of ${self.max_usd:.2f}")
