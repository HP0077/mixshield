"""E1 exposure check: did the injected text appear in a tool result the agent received? (no API calls)

    python -X utf8 -m bench.e1_exposure

Reads the six CSVs in results/e1/ and the raw logs in results/raw_logs/e1_*. AgentDojo formats tool results with
yaml.safe_dump, which writes non-ASCII characters as \\uXXXX escapes and wraps long lines. So a result counts as
showing the text if the text is found (1) as is, (2) with whitespace collapsed, or (3) after parsing the result as YAML.
`raw_escaped` marks runs where the text only matches after YAML parsing, i.e. the model saw escape codes, not letters.
"""

import collections
import csv
import json
import re
from pathlib import Path

import yaml

MODELS = {"muse-spark": "Muse Spark", "muse-spark-open": "Muse Spark Open"}
LANGUAGES = ["english", "hinglish", "hindi"]
COLLAPSE = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)


def result_texts(messages: list) -> list[str]:
    out = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m["content"]
        out.append(content if isinstance(content, str) else " ".join(b.get("content") or "" for b in content or []))
    return out


def exposure(text: str, results: list[str]) -> str:
    """Return how the text was found: 'plain', 'whitespace', 'yaml' or '' (not found)."""
    for r in results:
        if text in r:
            return "plain"
    ct = COLLAPSE(text)
    for r in results:
        if ct in COLLAPSE(r):
            return "whitespace"
    for r in results:
        try:
            parsed = yaml.safe_load(r)
        except yaml.YAMLError:
            continue
        if any(ct in COLLAPSE(s) for s in strings(parsed)):
            return "yaml"
    return ""


def log_path(model: str, language: str, row: dict) -> Path:
    base = Path("results/raw_logs") / f"e1_{model}_{language}"
    hits = list(base.rglob(f"{row['suite']}/{row['user_task']}/e1_style{row['style']}/{row['injection_task']}.json"))
    assert len(hits) == 1, (model, language, row["attack_id"], hits)
    return hits[0]


def load_all(sheet_texts: dict) -> list[dict]:
    """One dict per run: CSV row + model, exposure ('' = not exposed), messages."""
    runs = []
    for model in MODELS:
        for language in LANGUAGES:
            with open(f"results/e1/e1_{model}_{language}.csv", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    log = json.loads(log_path(model, language, row).read_text(encoding="utf-8"))
                    assert (log["suite_name"], log["user_task_id"], log["injection_task_id"]) == (
                        row["suite"], row["user_task"], row["injection_task"])
                    text = sheet_texts[(row["attack_id"], language)]
                    runs.append({**row, "model": model, "exposure": exposure(text, result_texts(log["messages"])),
                                 "messages": log["messages"], "has_devanagari": bool(DEVANAGARI.search(text))})
    return runs


def sheet_texts() -> dict:
    texts = {}
    with open("bench/attacks/writing_sheet.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            for language, col in (("english", "english_text"), ("hinglish", "hinglish_text"), ("hindi", "hindi_text")):
                texts[(f"{r['goal_id']}_{r['style_id']}", language)] = r[col]
    return texts


ESCAPE_CODE = re.compile(re.escape(chr(92)) + "u09[0-9a-f]{2}")
DEVANAGARI = re.compile("[" + chr(0x900) + "-" + chr(0x97F) + "]")


def hindi_shown_as(run: dict) -> str:
    """For a Hindi run: did the tool results show Devanagari letters, or only escape codes?"""
    results = result_texts(run["messages"])
    letters = any(DEVANAGARI.search(r) for r in results)
    codes = any(ESCAPE_CODE.search(r) for r in results)
    return "letters" if letters and not codes else "escape codes" if codes and not letters else "both" if letters else "neither"


def pick_sample(runs: list[dict], seed: int = 2, n: int = 10) -> list[dict]:
    """Random exposed runs: one from each model x language cell (6), then the rest at random from what is left."""
    import random
    rng = random.Random(seed)
    exposed = [r for r in runs if r["exposure"]]
    sample = [rng.choice([r for r in exposed if r["model"] == m and r["language"] == lang])
              for m in MODELS for lang in LANGUAGES]
    left = [r for r in exposed if r not in sample]
    return sample + rng.sample(left, n - len(sample))


def show(run: dict) -> None:
    calls = [f"{tc['function']}({json.dumps(tc['args'], ensure_ascii=False)[:110]})"
             for m in run["messages"] for tc in (m.get("tool_calls") or [])]
    last = run["messages"][-1]["content"]
    reply = last if isinstance(last, str) else " ".join(b.get("content") or "" for b in last or [])
    print(f"--- {MODELS[run['model']]} | {run['language']} | attack {run['attack_id']} | {run['suite']} {run['user_task']}")
    print("  tool calls:", " ; ".join(calls) or "none")
    print("  final reply:", reply[:200].replace(chr(10), " "))
    print(f"  attack_success={run['attack_success']} (raw {run['attack_success_raw']}), utility={run['utility']} "
          f"(raw {run['utility_raw']}), attacker email sent={run['secondary_attacker_email_sent']}")


def main() -> None:

    runs = load_all(sheet_texts())
    assert len(runs) == 600, len(runs)
    print("model, language: runs, exposed (how found), not exposed; attack success over exposed, scorable runs")
    for model in MODELS:
        for language in LANGUAGES:
            cell = [r for r in runs if r["model"] == model and r["language"] == language]
            exposed = [r for r in cell if r["exposure"]]
            how = dict(collections.Counter(r["exposure"] for r in exposed))
            scorable = [r for r in exposed if r["attack_success"] != "not_measurable"]
            wins = sum(r["attack_success"] == "True" for r in scorable)
            print(f"{MODELS[model]:16} {language:8} runs {len(cell)}, exposed {len(exposed)} {how}, "
                  f"not exposed {len(cell) - len(exposed)}; attack success {wins}/{len(scorable)}")
    unexposed = [f"{r['model']}/{r['language']}/{r['attack_id']}" for r in runs if not r["exposure"]]
    print("unexposed runs:", unexposed or "none")

    print("\nExposed runs whose attack text has Devanagari (all Hindi, style 9 in English and Hinglish): "
          "did the tool results show letters or escape codes?")
    for model in MODELS:
        shown = collections.Counter(hindi_shown_as(r) for r in runs
                                    if r["model"] == model and r["has_devanagari"] and r["exposure"])
        print(f"  {MODELS[model]:16}", dict(shown))

    print("\nUtility failures (goal 0 excluded, not measurable):")
    for r in runs:
        if r["utility"] == "False":
            print(f"  {MODELS[r['model']]} | {r['language']} | attack {r['attack_id']} | {r['user_task']} | "
                  f"exposed: {bool(r['exposure'])}")

    print("\nHand-check sample (seed 2: one exposed run per model x language, then 4 more at random)")
    for r in pick_sample(runs):
        show(r)


if __name__ == "__main__":
    main()
