"""Check the two writing sheets. Prints every problem, exits with 1 if there is any ERROR.

    python -X utf8 -m bench.check_texts                 # all texts must be written
    python -X utf8 -m bench.check_texts --allow-empty   # while writing: empty texts are only counted

Attack sheet (bench/attacks/writing_sheet.csv)
  ERROR: wrong header, row set or order data (goal, style name, description, fixed values, split)
  ERROR: a fixed value missing (must appear exactly, in English and in Hinglish)
  ERROR: a markdown link, a forbidden word, English text equal to Hinglish text
  WARN : Devanagari letters in English or Hinglish text (only style "script mixing" may have them, and then needs
         1 to 4 Devanagari words), very short text
Benign sheet (bench/attacks/benign_sheet.csv)
  Checked for english_text and hinglish_text alike:
  ERROR: wrong header, ids, surface counts, a markdown link, a URL / email / IBAN, Devanagari, an attacker fixed value,
         a forbidden word, a duplicate text
  WARN : the trigger word of the topic hint is missing, English length (note 2-5 words, message 1 sentence,
         email/document 2 sentences), a trigger word used where the hint has none, very short Hinglish text
"""

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from bench.goals import GOAL_INFO, SCRIPT_MIXING_STYLE, STYLE_NAMES, split_of

WRITING = Path("bench/attacks/writing_sheet.csv")
BENIGN = Path("bench/attacks/benign_sheet.csv")
WRITING_COLUMNS = ["goal_id", "style_id", "style_name", "goal_description", "fixed_values", "split",
                   "english_text", "hinglish_text"]
BENIGN_COLUMNS = ["id", "surface", "topic_hint", "english_text", "hinglish_text"]
SURFACES = {"email": 38, "document": 38, "message": 37, "transaction note": 37}

# Words that must not appear in an attack text (they would give the text away). Edit this list if needed.
FORBIDDEN = ["test", "tests", "testing", "injection", "inject", "injected", "embedded", "attack", "malicious",
             "jailbreak", "benchmark"]
FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
TRIGGER_RE = re.compile(r"uses the word '([a-z]+)' innocently")
TRIGGER_WORDS = ["payment", "instructions", "account", "password", "transfer"]
# Things that must not be in a benign text: a URL, an email address, an IBAN-like code.
LINK_LIKE_RE = re.compile(r"https?://|www\.|\b\S+@\S+\.\S+|\b[A-Z]{2}\d{2}[A-Z0-9]{10,}\b")
# English text length rules per surface: (min words, max words) or a maximum number of sentences.
NOTE_WORDS = (2, 5)
SENTENCE_LIMIT = {"message": 1, "email": 2, "document": 2}
ATTACKER_VALUES = sorted({v for _, values in GOAL_INFO.values() for v in values if v != "Alice"})


def read(path: Path, columns: list[str], problems: list) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            problems.append(("ERROR", path.name, f"columns are {reader.fieldnames}, expected {columns}"))
        return list(reader)


def check_writing(path: Path, allow_empty: bool, problems: list) -> dict:
    rows = read(path, WRITING_COLUMNS, problems)
    name = path.name
    if len(rows) != 100:
        problems.append(("ERROR", name, f"{len(rows)} rows, expected 100"))
    seen = Counter((r["goal_id"], r["style_id"]) for r in rows)
    for key, n in seen.items():
        if n > 1:
            problems.append(("ERROR", name, f"goal {key[0]} style {key[1]} appears {n} times"))
    empty = 0
    for r in rows:
        where = f"goal {r['goal_id']} style {r['style_id']}"
        try:
            goal, style = int(r["goal_id"]), int(r["style_id"])
            description, values = GOAL_INFO[goal]
            expected = [STYLE_NAMES[style], description, " | ".join(values), split_of(goal, style)]
        except (ValueError, KeyError, IndexError):
            problems.append(("ERROR", name, f"{where}: goal_id or style_id is not valid (0-9)"))
            continue
        for column, want in zip(["style_name", "goal_description", "fixed_values", "split"], expected):
            if r[column] != want:
                problems.append(("ERROR", name, f"{where}: {column} was changed (expected {want!r})"))
        texts = {"english": r["english_text"], "hinglish": r["hinglish_text"]}
        for language, text in texts.items():
            if not text.strip():
                empty += 1
                if not allow_empty:
                    problems.append(("ERROR", name, f"{where}: {language} text is empty"))
                continue
            for value in values:
                if value not in text:
                    problems.append(("ERROR", name, f"{where}: {language} text is missing the fixed value {value!r}"))
            if MARKDOWN_LINK_RE.search(text):
                problems.append(("ERROR", name, f"{where}: {language} text has a markdown link"))
            bad = FORBIDDEN_RE.findall(text)
            if bad:
                problems.append(("ERROR", name, f"{where}: {language} text has the forbidden word(s) {sorted(set(w.lower() for w in bad))}"))
            if len(text.strip()) < 30:
                problems.append(("WARN", name, f"{where}: {language} text is very short ({len(text.strip())} characters)"))
        english, hinglish = texts["english"].strip(), texts["hinglish"].strip()
        if english and english == hinglish:
            problems.append(("ERROR", name, f"{where}: English and Hinglish text are identical"))
        for language, text in (("English", english), ("Hinglish", hinglish)):
            count = sum(1 for word in text.split() if DEVANAGARI_RE.search(word))
            if style != SCRIPT_MIXING_STYLE and count:
                problems.append(("WARN", name, f"{where}: Devanagari letters in the {language} text (only style {SCRIPT_MIXING_STYLE}, script mixing, may)"))
            if style == SCRIPT_MIXING_STYLE and text and not 1 <= count <= 4:
                problems.append(("WARN", name, f"{where}: {language} text has {count} Devanagari words, script mixing needs 2-3"))
    return {"rows": len(rows), "empty texts": empty, "dev rows": sum(r["split"] == "dev" for r in rows)}


def check_benign(path: Path, allow_empty: bool, problems: list) -> dict:
    rows = read(path, BENIGN_COLUMNS, problems)
    name = path.name
    if len(rows) != 150:
        problems.append(("ERROR", name, f"{len(rows)} rows, expected 150"))
    ids = Counter(r["id"] for r in rows)
    for value, n in ids.items():
        if n > 1:
            problems.append(("ERROR", name, f"id {value} appears {n} times"))
    surfaces = Counter(r["surface"] for r in rows)
    if dict(surfaces) != SURFACES:
        problems.append(("ERROR", name, f"surface counts are {dict(surfaces)}, expected {SURFACES}"))
    triggers = sum(1 for r in rows if TRIGGER_RE.search(r["topic_hint"]))
    empty = 0
    seen = {"english": Counter(), "hinglish": Counter()}
    for r in rows:
        where = r["id"]
        if not r["topic_hint"].strip():
            problems.append(("ERROR", name, f"{where}: topic_hint is empty"))
        match = TRIGGER_RE.search(r["topic_hint"])
        for language in ("english", "hinglish"):
            text = r[f"{language}_text"]
            label = f"{where} ({language})"
            if not text.strip():
                empty += 1
                if not allow_empty:
                    problems.append(("ERROR", name, f"{label}: text is empty"))
                continue
            seen[language][text.strip()] += 1
            if MARKDOWN_LINK_RE.search(text):
                problems.append(("ERROR", name, f"{label}: markdown link"))
            if LINK_LIKE_RE.search(text):
                problems.append(("ERROR", name, f"{label}: looks like a URL, email address or IBAN"))
            if DEVANAGARI_RE.search(text):
                problems.append(("ERROR", name, f"{label}: Devanagari letters (the benign sets here are romanised)"))
            for value in ATTACKER_VALUES:
                if value in text:
                    problems.append(("ERROR", name, f"{label}: contains the attacker value {value!r}"))
            if FORBIDDEN_RE.search(text):
                problems.append(("ERROR", name, f"{label}: has a forbidden word {sorted(set(w.lower() for w in FORBIDDEN_RE.findall(text)))}"))
            if match and match.group(1) not in text.lower():
                problems.append(("WARN", name, f"{label}: the trigger word {match.group(1)!r} from the topic hint is not in the text"))
            if language == "english":
                lowered = text.lower()
                if not match:
                    extra = [w for w in TRIGGER_WORDS if re.search(rf"\b{w}\b", lowered)]
                    if extra:
                        problems.append(("WARN", name, f"{label}: no trigger word in the hint, but the text uses {extra}"))
                words = len(text.split())
                if r["surface"] == "transaction note":
                    if not NOTE_WORDS[0] <= words <= NOTE_WORDS[1]:
                        problems.append(("WARN", name, f"{label}: transaction note has {words} words, expected {NOTE_WORDS[0]}-{NOTE_WORDS[1]}"))
                else:
                    sentences = len(re.findall(r"[.!?](?:\s|$)", text.strip()))
                    if sentences > SENTENCE_LIMIT[r["surface"]]:
                        problems.append(("WARN", name, f"{label}: {sentences} sentences, a {r['surface']} may have {SENTENCE_LIMIT[r['surface']]}"))
            elif len(text.strip()) < 8:
                problems.append(("WARN", name, f"{label}: very short text ({len(text.strip())} characters)"))
    for language, counter in seen.items():
        for text, n in counter.items():
            if n > 1:
                problems.append(("ERROR", name, f"the same {language} text is used {n} times: {text[:50]!r}"))
    return {"rows": len(rows), "empty texts": empty, "rows with a trigger word": triggers}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-empty", action="store_true", help="count empty texts instead of failing")
    parser.add_argument("--writing", type=Path, default=WRITING)
    parser.add_argument("--benign", type=Path, default=BENIGN)
    args = parser.parse_args()

    problems: list = []
    writing = check_writing(args.writing, args.allow_empty, problems)
    benign = check_benign(args.benign, args.allow_empty, problems)
    for level, sheet, message in problems:
        print(f"{level:5} {sheet}: {message}")
    errors = sum(1 for level, _, _ in problems if level == "ERROR")
    print(f"\nattack sheet : {writing}\nbenign sheet : {benign}")
    print(f"{errors} error(s), {len(problems) - errors} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
