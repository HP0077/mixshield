"""Text normalisation before screening. Read before accepting.

`normalize(text)` makes English, Hinglish and Hindi text easier to screen. Steps, in order:
  1. Unicode NFC (composed characters, so "e" + accent and "é" are the same).
  2. Remove invisible characters: every Unicode "format" character (zero-width space / joiner / non-joiner,
     word joiner, byte-order mark, soft hyphen, left-to-right and right-to-left marks and embeddings).
     Unusual spaces (no-break space, thin space and so on) become a normal space.
  3. Collapse repeated spaces and tabs into one space, and trim each line. Line breaks are kept.
  4. Find protected spans: URLs and domains, email addresses, IBANs, and numbers (with $, ₹, commas, dots).
     Nothing inside a protected span is changed by steps 5 and 6.
  5. Lowercase Roman (Latin) letters only. Devanagari has no case; other scripts (for example Cyrillic look-alikes)
     are left as they are.
  6. Map common Hinglish spelling variants to one form (HINGLISH_VARIANTS below). Only whole words or whole
     phrases are mapped, never parts of a longer word.

The output is used only for detection (the screen). The agent always gets the original text. Because of step 5,
text values that are not protected (for example an email subject) come out in lowercase.
"""

import re
import unicodedata

from mixshield.gate import EMAIL_RE, IBAN_RE, URL_RE

# One canonical form -> spellings that mean the same thing in romanised Hindi chat.
# Written on 28 Oct from general Hinglish usage (SMS-style vowel dropping, joined or split "do" endings), not from
# our attack texts or detector results. Keep it small. Do not add entries after looking at test-split results.
# Only spellings that cannot be confused with a common English word or another Hindi word are listed: so no "h",
# "he", "mt", "sb" (English), no "bhej" (stem of "bhej diya", "sent"), "kia" (also "kiya", "did"), "nai" ("new").
HINGLISH_VARIANTS: dict[str, list[str]] = {
    "karo": ["kro", "krdo", "kardo", "kar do", "kr do"],            # "do it"
    "karna": ["krna", "karnaa"],                                    # "to do"
    "bhejo": ["bhej do", "bhejdo", "bhjdo", "bhjo"],                # "send"
    "jaldi": ["jldi", "jaldee", "jaldii", "jldii"],                 # "quickly"
    "abhi": ["abhii", "abhee", "abi"],                              # "right now"
    "turant": ["turnt", "turantt"],                                 # "immediately"
    "nahi": ["nhi", "nahin", "nahee", "nahii"],                     # "no / not"
    "kya": ["kyaa"],                                                # "what"
    "please": ["plz", "pls", "plzz", "plis"],                       # used as-is in Hinglish chat
    "message": ["msg", "msj"],
}

NUMBER_RE = re.compile(r"[$₹€£]?\d(?:[\d,.]*\d)?")
UNUSUAL_SPACE_RE = re.compile(r"[^\S\n\t ]")  # any whitespace that is not a newline, tab or plain space
SPACES_RE = re.compile(r"[ \t]+")

# Longest variants first, so "kar do" wins over a shorter match. Whole words only.
_VARIANT_TO_FORM = {v: form for form, variants in HINGLISH_VARIANTS.items() for v in variants}
_VARIANT_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(v).replace(r"\ ", r"\s+")
                            for v in sorted(_VARIANT_TO_FORM, key=len, reverse=True)) + r")(?!\w)")


def _remove_invisible(text: str) -> str:
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return UNUSUAL_SPACE_RE.sub(" ", text)


def _collapse_spaces(text: str) -> str:
    return "\n".join(SPACES_RE.sub(" ", line).strip() for line in text.split("\n"))


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for pattern in (EMAIL_RE, URL_RE, IBAN_RE, NUMBER_RE):
        for m in pattern.finditer(text):
            if not any(m.start() < end and start < m.end() for start, end in spans):
                spans.append((m.start(), m.end()))
    return sorted(spans)


def _lower_latin(c: str) -> str:
    # Length-preserving, so protected span positions stay valid (a few letters lowercase to two characters).
    lower = c.lower()
    return lower if len(lower) == 1 and "LATIN" in unicodedata.name(c, "") else c


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _collapse_spaces(_remove_invisible(text))
    spans = _protected_spans(text)
    protected = set().union(*(range(s, e) for s, e in spans)) if spans else set()
    text = "".join(c if i in protected else _lower_latin(c) for i, c in enumerate(text))

    def replace(m: re.Match) -> str:
        if any(i in protected for i in range(m.start(), m.end())):
            return m.group(0)
        return _VARIANT_TO_FORM[re.sub(r"\s+", " ", m.group(1))]

    return _VARIANT_RE.sub(replace, text)
