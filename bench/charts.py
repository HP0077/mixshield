"""Result charts for the README and the video. Every number is read from the committed result CSVs (no API calls).

    python -X utf8 -m bench.charts

Writes PNG (300 dpi) and SVG to results/charts/, prints a table of every plotted number, and saves the same table to
results/charts/numbers.md.

Sources (same logic as the stats scripts, test split wherever docs/pilot_results.md says test is the headline):
  e2_language_gap          bench.stats_e2 (verdicts, rate, SCREEN_FILES, SINGLE); test split
  e3_security_vs_utility   E3a ASR from bench.e3_stats.load (test, all languages); E3b utility from results/e3b (test)
  e4_ablation              bench.e3_stats.load("e4") and E3a full MixShield rows; test, all languages
  latency                  bench.latency (cache, p95), results/e3 caches and event logs
  e5_attacks               results/e5/e5a_*.csv and e5b_*.csv (same rule as bench.e5_run --stats)
"""

import csv
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from bench import e3_stats, stats_e2  # noqa: E402
from bench.latency import cache, p95  # noqa: E402

OUT = Path("results/charts")
LANGS = [("en", "English"), ("hi", "Hinglish"), ("hd", "Hindi")]

# Okabe-Ito colour-blind-safe palette. MixShield is always blue; hatched = strict approver, solid = trusting/none.
BLUE, ORANGE, VERMILION, GREEN, GREY, PINK = "#0072B2", "#E69F00", "#D55E00", "#009E73", "#7F7F7F", "#CC79A7"
COLOUR = {"MixShield": BLUE, "Llama Guard 3": ORANGE, "Prompt Guard 2 (0.5)": PINK,
          "Prompt Guard 2 (0.0006)": VERMILION, "No defence": GREY}
CONFIG_NAME = {"none": "No defence", "pg2_0.5": "Prompt Guard 2 (0.5)", "pg2_0.0006": "Prompt Guard 2 (0.0006)",
               "lg3": "Llama Guard 3", "mixshield_trusting": "MixShield (trusting)",
               "mixshield_strict": "MixShield (strict)"}
TICK = {"none": "No\ndefence", "pg2_0.5": "Prompt\nGuard 2\n(0.5)", "lg3": "Llama\nGuard 3",
        "mixshield_trusting": "MixShield\n(trusting)", "mixshield_strict": "MixShield\n(strict)"}
OBEDIENT = "worst case = scripted obedient agent (simulation)"

plt.rcParams.update({"font.size": 15, "axes.titlesize": 17, "axes.labelsize": 16, "legend.fontsize": 14,
                     "xtick.labelsize": 14, "ytick.labelsize": 14, "axes.spines.top": False,
                     "axes.spines.right": False, "hatch.linewidth": 1.5, "figure.dpi": 100})

NUMBERS: list[tuple[str, str, str, str]] = []  # chart, series, category, value text


def note(chart: str, series: str, category: str, value: str) -> None:
    NUMBERS.append((chart, series, category, value))


def colour_of(config: str) -> str:
    return BLUE if config.startswith(("mixshield", "minus")) else COLOUR[CONFIG_NAME[config]]


def hatch_of(config: str) -> str:
    return "//" if config.endswith("strict") or config.endswith("_names_strict") else ""


def save(fig, name: str, caption: str | None = None) -> None:
    if caption:
        fig.text(0.5, -0.01, caption, ha="center", va="top", fontsize=13, style="italic")
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def label_bars(ax, bars, texts, size=12) -> None:
    for bar, text in zip(bars, texts):
        ax.annotate(text, (bar.get_x() + bar.get_width() / 2, bar.get_height()), xytext=(0, 3),
                    textcoords="offset points", ha="center", va="bottom", fontsize=size)


# ---------------------------------------------------------------------------------------------------- 1. E2
def e2_numbers() -> dict:
    """detector -> language key -> {'recall': (mean, std, text), 'fa': ...} on the test split."""
    sheet = {f"{r['goal_id']}_{r['style_id']}": r for r in stats_e2.read(stats_e2.SHEET)}
    stats_e2.check_ids(sheet)
    result = {}
    names = {"MixShield screen": None, "Llama Guard 3": "Llama Guard 3 1B", "Prompt Guard 2 (0.5)": "Prompt Guard 2 at 0.5"}
    for label, single in names.items():
        result[label] = {}
        for lang, _ in LANGS:
            cell = {}
            for kind, key in (("recall", f"{lang}_att"), ("fa", f"{lang}_ben")):
                if single is None:
                    values = [stats_e2.rate(*stats_e2.verdicts(f), "test") for f in stats_e2.SCREEN_FILES[key]]
                    shares = [100 * hit / n for hit, n in values]
                    cell[kind] = (statistics.mean(shares), statistics.stdev(shares),
                                  f"3 runs, test n={values[0][1]}")
                else:
                    suffix, threshold = stats_e2.SINGLE[single]
                    hit, n = stats_e2.rate(*stats_e2.verdicts(stats_e2.single_files(suffix)[key], threshold), "test")
                    cell[kind] = (100 * hit / n, None, f"{hit}/{n}")
            result[label][lang] = cell
    return result


def chart_e2() -> None:
    data = e2_numbers()
    series = [("MixShield screen", BLUE), ("Llama Guard 3", ORANGE), ("Prompt Guard 2 (0.5)", PINK)]
    fig, axes = plt.subplots(1, 2, figsize=(17, 7.5), gridspec_kw={"width_ratios": [1.25, 1]})
    panels = [("recall", "Detection recall: attacks flagged (%)", (0, 112)),
              ("fa", "False alarms: benign texts flagged (%)", (0, 10))]
    width = 0.26
    for ax, (kind, ylabel, ylim) in zip(axes, panels):
        for s, (label, colour) in enumerate(series):
            xs = [i + (s - 1) * width for i in range(3)]
            means = [data[label][lang][kind][0] for lang, _ in LANGS]
            errs = [data[label][lang][kind][1] or 0 for lang, _ in LANGS]
            bars = ax.bar(xs, means, width, color=colour, label=label, yerr=errs if label == "MixShield screen" else None,
                          capsize=5, error_kw={"elinewidth": 2, "ecolor": "black"})
            label_bars(ax, bars, [f"{m:.1f}" for m in means], 12)
            for lang, m, text in ((lang, m, data[label][lang][kind]) for (lang, _), m in zip(LANGS, means)):
                std = text[1]
                note("e2_language_gap", f"{label} {kind}", dict(LANGS)[lang],
                     f"{text[0]:.1f}" + (f" ± {std:.1f} ({text[2]})" if std is not None else f" ({text[2]})"))
        ax.set_xticks(range(3), [name for _, name in LANGS])
        ax.set_ylim(*ylim)
        ax.set_ylabel(ylabel)
    axes[0].set_title("Attacks caught, by language")
    axes[1].set_title("Benign texts wrongly flagged (note scale)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 0.97), frameon=False)
    fig.suptitle("Detection by language, test split (70 attacks, 105 benign texts per language)", fontsize=19, y=1.04)
    save(fig, "e2_language_gap", "MixShield: mean over 3 runs, error bars = std. Other detectors are deterministic (1 run).")


# ---------------------------------------------------------------------------------------------------- 2. E3
def e3a_asr_test(rows: list[dict]) -> tuple[float, int, int]:
    sel = [r for r in rows if r["split"] == "test" and r["attack_success"] != "not_measurable"]
    hit = sum(r["attack_success"] == "True" for r in sel)
    return 100 * hit / len(sel), hit, len(sel)


def e3b_utility_test(config: str) -> tuple[float, int, int]:
    rows = [r for r in csv.DictReader(open(Path("results/e3b") / f"e3b_{config}.csv", encoding="utf-8"))]
    assert all(r["status"] == "ok" for r in rows) and len(rows) == 77, f"e3b {config} incomplete"
    sel = [r for r in rows if r["split"] == "test"]
    hit = sum(r["utility"] == "True" for r in sel)
    return 100 * hit / len(sel), hit, len(sel)


def chart_e3() -> None:
    e3a = e3_stats.load("e3a")
    configs = list(CONFIG_NAME)
    # label offsets (points) so the crowded top-right points do not overlap
    offsets = {"none": (0, 16, "center"), "pg2_0.5": (-16, -6, "right"), "pg2_0.0006": (12, 12, "left"),
               "lg3": (12, 12, "left"), "mixshield_trusting": (0, 22, "center"), "mixshield_strict": (-18, -5, "right")}
    fig, ax = plt.subplots(figsize=(13, 8))
    for config in configs:
        asr, ahit, an = e3a_asr_test(e3a[config])
        util, uhit, un = e3b_utility_test(config)
        ax.scatter(util, asr, s=330, color=colour_of(config), marker="s" if config.endswith("strict") else "o",
                   edgecolor="black", linewidth=1.5, zorder=3)
        dx, dy, ha = offsets[config]
        ax.annotate(CONFIG_NAME[config], (util, asr), xytext=(dx, dy), textcoords="offset points", ha=ha, fontsize=15,
                    fontweight="bold" if config.startswith("mixshield") else "normal",
                    bbox={"fc": "white", "ec": "none", "pad": 1.5, "alpha": 0.85}, zorder=5)
        note("e3_security_vs_utility", CONFIG_NAME[config], "utility, E3b test (x)", f"{util:.1f} ({uhit}/{un})")
        note("e3_security_vs_utility", CONFIG_NAME[config], "attack success, E3a test (y)", f"{asr:.1f} ({ahit}/{an})")
    undefended = e3b_utility_test("none")[0]
    ax.axvline(undefended, color=GREY, ls="--", lw=1, zorder=1)
    ax.text(undefended - 0.6, 52, "undefended utility", rotation=90, ha="right", va="center", fontsize=13, color=GREY)
    note("e3_security_vs_utility", "undefended utility line", "x", f"{undefended:.1f}")
    ax.scatter([100], [0], s=700, marker="*", color=GREEN, edgecolor="black", zorder=4)
    ax.annotate("ideal (not a result)", (100, 0), xytext=(34, 90), textcoords="offset points",
                ha="center", fontsize=14, color=GREEN, fontweight="bold",
                arrowprops={"arrowstyle": "->", "color": GREEN, "lw": 2}, zorder=4)
    ax.set_xlim(0, 105)
    ax.set_ylim(-5, 105)
    ax.set_xlabel("Utility on real Muse Spark tasks, no attack (%)  [E3b, test split, 52 tasks]")
    ax.set_ylabel("Attack success, worst case (%)  [E3a, test split, 189 attacks]")
    ax.set_title("Security vs utility: lower right is better", pad=24)
    ax.grid(alpha=0.25, zorder=0)
    ax.legend(handles=[plt.Line2D([], [], marker="o", ls="", ms=11, mfc="white", mec="black", label="circle = no or trusting approver"),
                       plt.Line2D([], [], marker="s", ls="", ms=11, mfc="white", mec="black", label="square = strict approver")],
              loc="center left", frameon=False)
    save(fig, "e3_security_vs_utility", f"Attack success: {OBEDIENT}. Utility: real agent (Muse Spark).")


# ---------------------------------------------------------------------------------------------------- 3. E4
def chart_e4() -> None:
    e3a, e4 = e3_stats.load("e3a"), e3_stats.load("e4")
    bars = [("Full MixShield\n(trusting)", e3a["mixshield_trusting"], ""),
            ("Full MixShield\n(strict)", e3a["mixshield_strict"], "//"),
            ("Minus screen\n(strict)", e4["minus_screen_strict"], "//"),
            ("Minus screen\n(trusting)", e4["minus_screen_trusting"], ""),
            ("Minus gate", e4["minus_gate"], ""),
            ("Minus approval", e4["minus_approval"], "")]
    fig, ax = plt.subplots(figsize=(14, 7.5))
    values = [e3a_asr_test(rows) for _, rows, _ in bars]
    b = ax.bar(range(len(bars)), [v[0] for v in values], 0.62, color=BLUE, edgecolor="white")
    for rect, (_, _, hatch) in zip(b, bars):
        rect.set_hatch(hatch)
    label_bars(ax, b, [f"{v[0]:.1f}\n({v[1]}/{v[2]})" for v in values], 14)
    for (label, _, _), v in zip(bars, values):
        note("e4_ablation", label.replace("\n", " "), "attack success, test", f"{v[0]:.1f} ({v[1]}/{v[2]})")
    ax.set_xticks(range(len(bars)), [x[0] for x in bars])
    ax.set_ylim(0, 118)
    ax.set_ylabel("Attack success, worst case (%)")
    ax.set_title("Ablation: remove one MixShield part at a time (test split)", pad=14)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(handles=[Patch(facecolor=BLUE, label="solid = trusting approver / no approver"),
                       Patch(facecolor=BLUE, hatch="//", edgecolor="white", label="hatched = strict approver")],
              loc="upper left", frameon=False)
    save(fig, "e4_ablation", f"Attack success: {OBEDIENT}. 189 scorable attacks (3 languages). "
                             "Minus screen: gate and approver act as if nothing was flagged.")


# ---------------------------------------------------------------------------------------------------- 4. latency
def chart_latency() -> None:
    root = Path("results/e3")
    screen = [e["seconds"] for e in cache(root / "cache" / "mixshield.jsonl")]
    lg3 = [e["seconds"] for e in cache(root / "cache" / "lg3.jsonl")]
    gate = []
    for path in sorted((root / "events").glob("*.jsonl")):
        for x in path.read_text(encoding="utf-8").splitlines():
            gate += [e["seconds"] for e in json.loads(x)["events"] if e["kind"] == "gate" and "seconds" in e]
    rows = [("MixShield screen\n(per tool output)", screen, BLUE), ("Gate\n(per tool call)", gate, BLUE),
            ("Llama Guard 3\n(per tool output, CPU)", lg3, ORANGE)]
    fig, ax = plt.subplots(figsize=(13, 7.5))
    width = 0.36
    for i, (label, values, colour) in enumerate(rows):
        med, high = statistics.median(values), p95(values)
        for j, (v, name) in enumerate(((med, "median"), (high, "p95"))):
            rect = ax.bar(i + (j - 0.5) * width, v, width, color=colour, alpha=1.0 if j == 0 else 0.55,
                          edgecolor="black", linewidth=1.2, bottom=1e-6)
            text = f"{v * 1000:.3g} ms" if v < 1 else f"{v:.2f} s"
            ax.annotate(text, (i + (j - 0.5) * width, v), xytext=(0, 4), textcoords="offset points", ha="center",
                        fontsize=13)
            note("latency", label.replace("\n", " "), name, f"{v:.6g} s (n={len(values)})")
    ax.set_yscale("log")
    ax.set_ylim(1e-6, 100)
    ax.set_xticks(range(len(rows)), [r[0] for r in rows])
    ax.set_ylabel("Seconds (log scale)")
    ax.set_title("Latency: the screen costs seconds, the gate costs microseconds", pad=14)
    ax.grid(axis="y", alpha=0.25, which="major")
    ax.set_axisbelow(True)
    ax.legend(handles=[Patch(facecolor="grey", edgecolor="black", label="median"),
                       Patch(facecolor="grey", alpha=0.55, edgecolor="black", label="p95")], loc="upper center", ncol=2, frameon=False)
    save(fig, "latency", "Source: results/e3 caches (E3a, E4, E5 runs), real detector calls only. Screen = normalise + Prompt Guard 2 (CPU) + "
                         "Muse Spark Open classifier (Baseten API); Llama Guard 3 on this machine's CPU.")


# ---------------------------------------------------------------------------------------------------- 5. E5
def e5_asr(part: str, config: str) -> tuple[float, int, int]:
    rows = list(csv.DictReader(open(Path("results/e5") / f"e5{part}_{config}.csv", encoding="utf-8")))
    assert len(rows) == (110 if part == "a" else 30) and all(r["status"] == "ok" for r in rows), f"e5{part} {config}"
    sel = [r for r in rows if r["attack_success"] != "not_measurable"]
    hit = sum(r["attack_success"] == "True" for r in sel)
    return 100 * hit / len(sel), hit, len(sel)


def chart_e5() -> None:
    configs = ["none", "pg2_0.5", "lg3", "mixshield_trusting", "mixshield_strict"]
    titles = {"a": "(a) AgentDojo built-in attacks\nEnglish, written independently of MixShield",
              "b": "(b) Author-written adaptive attempts\nHinglish, written after seeing MixShield"}
    fig, axes = plt.subplots(1, 2, figsize=(17, 8), sharey=True)
    for ax, part in zip(axes, ("a", "b")):
        vals = [e5_asr(part, c) for c in configs]
        bars = ax.bar(range(len(configs)), [v[0] for v in vals], 0.66, color=[colour_of(c) for c in configs],
                      edgecolor="white")
        for rect, c in zip(bars, configs):
            rect.set_hatch(hatch_of(c))
        label_bars(ax, bars, [f"{v[0]:.1f}\n({v[1]}/{v[2]})" for v in vals], 13)
        for c, v in zip(configs, vals):
            note("e5_attacks", CONFIG_NAME[c], f"part {part}", f"{v[0]:.1f} ({v[1]}/{v[2]})")
        ax.set_xticks(range(len(configs)), [TICK[c] for c in configs], fontsize=13)
        ax.set_title(titles[part], pad=12)
        ax.set_ylim(0, 122)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Attack success, worst case (%)")
    fig.suptitle("Adaptive and built-in attacks: attack success per defence", fontsize=19, y=1.02)
    save(fig, "e5_attacks", f"Attack success: {OBEDIENT}. Hatched = strict approver. In (a) the "
                            "important_instructions family counts 6 times (near-duplicate texts). Goal 4 not scorable.")


# ---------------------------------------------------------------------------------------------------- main
def main() -> None:
    for step in (chart_e2, chart_e3, chart_e4, chart_latency, chart_e5):
        step()
    lines = ["| Chart | Series | Category | Value |", "| --- | --- | --- | --- |"]
    lines += [f"| {c} | {s} | {k} | {v} |" for c, s, k, v in NUMBERS]
    table = "\n".join(lines)
    (OUT / "numbers.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"\nWrote {len(list(OUT.glob('*.png')))} PNG and {len(list(OUT.glob('*.svg')))} SVG to {OUT}/")


if __name__ == "__main__":
    main()
