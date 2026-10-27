"""Dollar cap for a script run. Checked after every model call, so a retry loop is stopped mid-run."""

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

    @property
    def spent_usd(self) -> float:
        return (self.input_tokens * self.usd_per_m_in + self.output_tokens * self.usd_per_m_out) / 1e6

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if self.spent_usd > self.max_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.2f} of ${self.max_usd:.2f}")
