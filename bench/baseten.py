"""Baseten spend: one running total across all scripts, a hard stop at STOP_USD, and one request at a time.

The total lives in results/baseten_spend.json: a fixed baseline (spend before this file existed) plus one entry per
script run, updated after every Baseten call, so a crash keeps the record. Every Baseten call in a script must go
through `Ledger.add` (agent runs: `BasetenBudget`; the screen classifier: `LockedClassifier`).

BASELINE_USD is a conservative estimate of all Baseten spend up to 30 Oct, from the recorded result files
(docs/pilot_results.md, "Baseten spend ledger"). It over-counts on purpose (some merged files repeat rows, and the
e0 candidate runs are priced at the output-token price), because it is only used for the stop rule.

BASETEN_LOCK: at most one Baseten request in flight in this process. Other work (Muse Spark agent workers, local
models) may run in parallel. Only one process may use Baseten at a time; that is the caller's job.
"""

import json
import threading
import time
from pathlib import Path

from bench.budget import DEFAULT_USD_PER_M_IN, DEFAULT_USD_PER_M_OUT, Budget, BudgetExceeded

LEDGER = Path("results/baseten_spend.json")
STOP_USD = 65.0  # keep the rest for the demo
BASELINE_USD = 36.39
BASELINE_NOTE = "conservative estimate of Baseten spend up to 30 Oct, from recorded result files (over-counts)"
BASETEN_LOCK = threading.Lock()


class BasetenCapReached(BudgetExceeded):
    pass


class Ledger:
    def __init__(self, script: str) -> None:
        self._lock = threading.Lock()
        if LEDGER.exists():
            self.data = json.loads(LEDGER.read_text(encoding="utf-8"))
        else:
            self.data = {"baseline_usd": BASELINE_USD, "baseline_note": BASELINE_NOTE, "stop_usd": STOP_USD,
                         "runs": []}
        self.entry = {"script": script, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "usd": 0.0}
        self.data["runs"].append(self.entry)
        self.stopped = False
        self.check()

    @property
    def session_usd(self) -> float:
        return self.entry["usd"]

    @property
    def total_usd(self) -> float:
        return self.data["baseline_usd"] + sum(r["usd"] for r in self.data["runs"])

    def line(self) -> str:
        return f"Baseten: this script ${self.session_usd:.3f}, total ${self.total_usd:.2f} (stop at ${STOP_USD:.0f})"

    def check(self) -> None:
        if self.stopped or self.total_usd > STOP_USD:
            self.stopped = True
            raise BasetenCapReached(f"Baseten total ${self.total_usd:.2f} is above ${STOP_USD:.0f}")

    def add(self, input_tokens: int, output_tokens: int) -> None:
        usd = (input_tokens * DEFAULT_USD_PER_M_IN + output_tokens * DEFAULT_USD_PER_M_OUT) / 1e6
        with self._lock:
            self.entry["usd"] = round(self.entry["usd"] + usd, 6)
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            LEDGER.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        self.check()


class BasetenBudget(Budget):
    """A script's dollar cap for a Muse Spark Open agent, that also feeds the Baseten ledger and its stop."""

    def __init__(self, max_usd: float, ledger: Ledger) -> None:
        super().__init__(max_usd)
        self.ledger = ledger

    def check(self) -> None:
        super().check()
        try:
            self.ledger.check()
        except BasetenCapReached:
            self.exhausted = True
            raise

    def add(self, input_tokens: int, output_tokens: int) -> None:
        try:
            self.ledger.add(input_tokens, output_tokens)
        except BasetenCapReached:
            self.exhausted = True
            raise
        finally:
            super().add(input_tokens, output_tokens)


class LockedClassifier:
    """Wraps mixshield.screen.MuseSparkOpenClassifier: one request at a time (BASETEN_LOCK), spend into the ledger.
    `seconds` lists the time of each call inside the lock (waiting for the lock is not counted)."""

    def __init__(self, inner, ledger: Ledger) -> None:
        self.inner = inner
        self.ledger = ledger
        self.seconds: list[float] = []

    def __call__(self, text: str):
        self.ledger.check()  # raises: the screen fails closed, and the script stops on the ledger flag
        with BASETEN_LOCK:
            in0, out0 = self.inner.input_tokens, self.inner.output_tokens
            start = time.perf_counter()
            try:
                return self.inner(text)
            finally:
                self.seconds.append(time.perf_counter() - start)
                self.ledger.add(self.inner.input_tokens - in0, self.inner.output_tokens - out0)
