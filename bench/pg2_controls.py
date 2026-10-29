"""Prompt Guard 2 positive and negative controls on a public injection dataset. No API calls.

    python -X utf8 -m bench.pg2_controls

Checks that our Prompt Guard 2 code path (mixshield/prompt_guard.py: same chunking) and the same fixed threshold as
E2 work on texts from outside our benchmark: 20 injections should mostly be flagged, 20 normal texts mostly not.
Dataset: deepset/prompt-injections (Apache-2.0), test split, pinned to one revision. Sample: 20 per label, fixed seed.
The dataset mixes English and German; nothing is filtered, so the numbers are a code-path check, not a benchmark.
"""

import csv
import os
import random
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

from bench.e2_detect import THRESHOLD
from mixshield.prompt_guard import MODEL_ID, PromptGuard2

DATASET = "deepset/prompt-injections"
LICENSE = "apache-2.0"
REVISION = "4f61ecb038e9c3fb77e21034b22511b523772cdd"  # dataset commit, checked 30 Oct
TEST_FILE = "data/test-00000-of-00001-701d16158af87368.parquet"
SEED = 0
PER_LABEL = 20
OUT = Path("results/e2/pg2_controls.csv")


def load_sample() -> list[dict]:
    """20 injections (label 1) and 20 normal texts (label 0) from the test split, chosen with a fixed seed."""
    path = hf_hub_download(DATASET, TEST_FILE, repo_type="dataset", revision=REVISION,
                           token=os.environ.get("HF_TOKEN"))
    rows = pd.read_parquet(path).to_dict("records")
    rng = random.Random(SEED)
    sample = []
    for label in (1, 0):
        indices = [i for i, r in enumerate(rows) if r["label"] == label]
        for i in sorted(rng.sample(indices, PER_LABEL)):
            sample.append({"row": i, "label": label, "text": rows[i]["text"]})
    return sample


def main() -> None:
    sample = load_sample()
    guard = PromptGuard2()
    for item in sample:
        item["score"] = round(guard.score(item["text"]), 4)
        item["flagged"] = item["score"] >= THRESHOLD

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        f.write(f"# dataset: {DATASET} (license {LICENSE}), revision {REVISION}, file {TEST_FILE}\n")
        f.write(f"# sample: {PER_LABEL} per label, random.Random({SEED}); detector {MODEL_ID}, "
                f"threshold {THRESHOLD}; row = index in the test split; label 1 = injection\n")
        writer = csv.DictWriter(f, fieldnames=["row", "label", "score", "flagged", "text"])
        writer.writeheader()
        writer.writerows(sample)

    injections = [s for s in sample if s["label"] == 1]
    normal = [s for s in sample if s["label"] == 0]
    hit, alarms = sum(s["flagged"] for s in injections), sum(s["flagged"] for s in normal)
    print(f"Prompt Guard 2 @{THRESHOLD} on {DATASET} (test, seed {SEED})")
    print(f"  recall on injections : {hit}/{len(injections)} = {hit / len(injections):.0%}")
    print(f"  false alarms, normal : {alarms}/{len(normal)} = {alarms / len(normal):.0%}")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
