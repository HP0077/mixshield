"""Part 4: latency of the screen, the baseline detectors and the gate, from the E3a/E4/E3b runs (no API calls).

    python -X utf8 -m bench.latency

Per text (one tool output), from the verdict caches (results/e3/cache, results/e3b/cache). Only real detector calls
are in a cache (a cache hit costs nothing and is not counted), and each was timed inside the cache lock, so time spent
waiting for another thread is not included.
  MixShield screen  whole call: normalise + Prompt Guard 2 (CPU) + Muse Spark Open classifier (Baseten).
  classifier only   the Baseten call (bench.baseten.LockedClassifier, timed inside the Baseten lock).
  Prompt Guard 2 / Llama Guard 3  local CPU (this machine), as baselines.
Per gate decision, from the event logs (results/e3/events, results/e3b/events): Gate.check_call only, not the
approver. Per E3b run: number of tool outputs screened, and the agent's own run time (with 4 workers in parallel and
a shared Baseten lock, so it includes waiting; read it as an upper bound).
"""

import csv
import json
import statistics
from pathlib import Path


def p95(values: list[float]) -> float:
    values = sorted(values)
    return values[max(0, int(round(0.95 * len(values))) - 1)]


def line(name: str, values: list[float], unit: str = "s") -> str:
    if not values:
        return f"| {name} | 0 | - | - | - |"
    scale = 1000 if unit == "ms" else 1
    return (f"| {name} | {len(values)} | {statistics.median(values) * scale:.3g} | {p95(values) * scale:.3g} | "
            f"{max(values) * scale:.3g} |")


def cache(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def main() -> None:
    print("Per tool output (cache misses only, no waiting)")
    print("| Detector | Texts | Median (s) | p95 (s) | Max (s) |")
    print("| --- | --- | --- | --- | --- |")
    for experiment in ("e3", "e3b"):
        root = Path("results") / experiment / "cache"
        ms = cache(root / "mixshield.jsonl")
        print(line(f"MixShield screen, whole call ({experiment})", [e["seconds"] for e in ms]))
        print(line(f"  classifier only, Baseten ({experiment})", [e["classifier_seconds"] for e in ms]))
        print(line(f"  rest: normalise + Prompt Guard 2 ({experiment})",
                   [e["seconds"] - e["classifier_seconds"] for e in ms]))
        print(line(f"Prompt Guard 2, CPU ({experiment})", [e["seconds"] for e in cache(root / "pg2.jsonl")]))
        print(line(f"Llama Guard 3 1B, CPU ({experiment})", [e["seconds"] for e in cache(root / "lg3.jsonl")]))

    print("\nGate.check_call per decision (ms)")
    print("| Source | Decisions | Median (ms) | p95 (ms) | Max (ms) |")
    print("| --- | --- | --- | --- | --- |")
    for experiment in ("e3", "e3b"):
        seconds = []
        for path in sorted((Path("results") / experiment / "events").glob("*.jsonl")):
            for x in path.read_text(encoding="utf-8").splitlines():
                seconds += [e["seconds"] for e in json.loads(x)["events"] if e["kind"] == "gate" and "seconds" in e]
        print(line(f"{experiment} (all configs with a gate)", seconds, "ms"))

    print("\nE3b runs (Muse Spark, 4 workers; run time includes waiting for other runs' screen calls)")
    print("| Config | Runs | Outputs screened per run, median (max) | Run time median (s) | Run time p95 (s) |")
    print("| --- | --- | --- | --- | --- |")
    for path in sorted(Path("results/e3b").glob("e3b_*.csv")):
        rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["status"] == "ok"]
        screened = [int(r["screened"] or 0) for r in rows]
        seconds = [float(r["seconds"]) for r in rows]
        print(f"| {path.stem[4:]} | {len(rows)} | {statistics.median(screened):g} ({max(screened)}) | "
              f"{statistics.median(seconds):.1f} | {p95(seconds):.1f} |")


if __name__ == "__main__":
    main()
