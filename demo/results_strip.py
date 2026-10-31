"""The thin results strip under the page subtitle. Every number is computed here from the result CSVs, by the same
calls as `e2_numbers()` in bench/charts.py (bench.stats_e2: verdicts, rate, SCREEN_FILES, SINGLE), on the test split.
tests/test_results_strip.py checks that the two give the same numbers. If the CSVs are missing, the strip is left out
rather than filled with anything else.
"""

import contextlib
import html
import statistics
from pathlib import Path

from bench import stats_e2

REPO = Path(__file__).resolve().parent.parent


def hinglish_numbers() -> dict:
    """Test split, Hinglish: Llama Guard 3 recall, MixShield screen recall (mean of 3 runs), and false alarms."""
    with contextlib.chdir(REPO):  # stats_e2 reads its files by relative path
        out = {}
        suffix, threshold = stats_e2.SINGLE["Llama Guard 3 1B"]
        out["lg3_recall"] = stats_e2.rate(*stats_e2.verdicts(stats_e2.single_files(suffix)["hi_att"], threshold), "test")
        out["lg3_fa"] = stats_e2.rate(*stats_e2.verdicts(stats_e2.single_files(suffix)["hi_ben"], threshold), "test")
        for key, kind in (("hi_att", "ms_recall"), ("hi_ben", "ms_fa")):
            runs = [stats_e2.rate(*stats_e2.verdicts(f), "test") for f in stats_e2.SCREEN_FILES[key]]
            out[kind] = (statistics.mean(100 * hit / n for hit, n in runs), runs[0][1], len(runs))
    return out


def strip_html() -> str:
    """The strip as HTML, or an empty string if the numbers cannot be read."""
    try:
        n = hinglish_numbers()
    except (OSError, KeyError, ValueError, AssertionError):
        return ""
    lg_hit, lg_n = n["lg3_recall"]
    ms_mean, ms_n, runs = n["ms_recall"]
    fa_mean, fa_n, _ = n["ms_fa"]
    lg_fa_hit, lg_fa_n = n["lg3_fa"]
    items = [
        ("Llama Guard 3 recall", f"{100 * lg_hit / lg_n:.1f}% ({lg_hit}/{lg_n})"),
        ("MixShield screen recall", f"{ms_mean:.1f}%"),
        ("MixShield screen false alarms", f"{fa_mean:.1f}%"),
    ]
    note = f"Hinglish. {ms_n} attacks, {fa_n} benign texts. MixShield: mean of {runs} runs."
    cells = "".join(f'<div class="item"><span class="k">{html.escape(k)}</span> <span class="v">{html.escape(v)}</span></div>'
                    for k, v in items)
    return f'<div class="ms-strip"><span class="lead">Test split</span>{cells}<span class="note">{html.escape(note)}</span></div>'
