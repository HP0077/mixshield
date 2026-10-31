"""Rate limit for the public playground, so visitors cannot drain the Baseten credits.

Two limits, both checked before a run starts:
  - per visitor: at most `per_minute` runs in any 60 seconds (default 3);
  - global: a daily budget in US dollars. Every run has an ESTIMATED cost (COST below, rounded up on purpose); a run
    is refused once the estimates of the day's runs would pass the budget (default $3.00 a day, UTC days).
A refused run is not run and costs nothing. A run is counted when it is allowed, even if it later fails.

The visitor is the first address in the X-Forwarded-For header (HF Spaces sits behind a proxy), else the socket
address. A visitor can fake that header, so the daily budget is the limit that really protects the credits.
The day's total is kept in a small JSON file (so a restart does not reset it).

Settings (environment variables, read once at start):
  DEMO_RATE_LIMIT=off            no limits at all (for recording on your own machine)
  DEMO_MAX_RUNS_PER_MIN=3        per-visitor runs per minute
  DEMO_DAILY_BUDGET_USD=3.0      global estimated spend per day
  DEMO_LIMIT_FILE=<path>         where the day's total is kept
"""

import json
import os
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

# Estimated Baseten cost of one run, in dollars. Estimates, rounded up: a screened tool output is one Muse Spark Open
# call (about $0.004 in E3a); a real agent run is about 17,000 tokens (about $0.03) plus its screened outputs.
COST = {"check": 0.01, "simulated": 0.02, "agent": 0.08, "direct": 0.0, "replay": 0.0}


class RateLimiter:
    def __init__(self, per_minute: int = 3, daily_budget: float = 3.0, state_file: str | Path | None = None,
                 clock=time.time, enabled: bool = True) -> None:
        self.per_minute, self.daily_budget, self.enabled = per_minute, daily_budget, enabled
        self.clock = clock
        self.state_file = Path(state_file) if state_file else None
        self.lock = threading.Lock()
        self.recent: dict[str, deque] = defaultdict(deque)  # visitor -> times of allowed runs in the last minute
        self.day, self.spent = self._today(), 0.0
        self._load()

    @classmethod
    def from_env(cls) -> "RateLimiter":
        env = os.environ
        return cls(per_minute=int(env.get("DEMO_MAX_RUNS_PER_MIN", 3)),
                   daily_budget=float(env.get("DEMO_DAILY_BUDGET_USD", 3.0)),
                   state_file=env.get("DEMO_LIMIT_FILE") or Path(tempfile.gettempdir()) / "mixshield_demo_budget.json",
                   enabled=env.get("DEMO_RATE_LIMIT", "on").lower() != "off")

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file else {}
            if data.get("day") == self.day:
                self.spent = float(data.get("spent", 0.0))
        except (OSError, ValueError):
            pass  # no file or a broken one: start the day at zero

    def _save(self) -> None:
        try:
            if self.state_file:
                self.state_file.write_text(json.dumps({"day": self.day, "spent": round(self.spent, 4)}), encoding="utf-8")
        except OSError:
            pass  # the limit still works in memory

    def check(self, visitor: str, kind: str) -> tuple[bool, str]:
        """Ask to start one run of `kind` (a key of COST). Returns (allowed, message). Records the run if allowed."""
        if not self.enabled:
            return True, ""
        cost = COST[kind]
        with self.lock:
            now = self.clock()
            if self._today() != self.day:
                self.day, self.spent = self._today(), 0.0
            if len(self.recent) > 1000:  # do not keep an entry for every visitor forever
                for key in [k for k, w in self.recent.items() if not w or now - w[-1] >= 60]:
                    del self.recent[key]
            window = self.recent[visitor]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= self.per_minute:
                wait = int(60 - (now - window[0])) + 1
                return False, f"Too many runs: at most {self.per_minute} per minute. Try again in {wait} s."
            if self.spent + cost > self.daily_budget:
                return False, ("The daily budget for this public demo is used up. It resets at 00:00 UTC. "
                               "You can run it yourself from the GitHub repository.")
            window.append(now)
            self.spent += cost
            self._save()
        return True, ""


def visitor_id(request) -> str:
    """Who is asking: the first X-Forwarded-For address, else the socket address, else 'unknown'."""
    if request is None:
        return "unknown"
    forwarded = (request.headers or {}).get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(getattr(request, "client", None), "host", None) or "unknown"
