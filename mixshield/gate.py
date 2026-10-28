"""Action gate. Read before accepting.

Every proposed tool call goes through `Gate.check_call`, which returns allow, ask or block:
  allow  every checked value is trusted (or the tool is not high-risk);
  block  an untrusted value appears in untrusted text that the screen flagged;
  ask    an untrusted value that is not from flagged text. A human confirms it, like a bank's new-payee check.

Trusted data = the user's own account data and saved contacts (given when the gate is built) plus values written
in the user's own request (the task prompt). Text found in tool outputs is never trusted.

The policy says, per high-risk tool, which arguments are checked and how:
  DESTINATION  where money, a message or data goes (IBAN, email address, user, channel, URL).
  VALUE        a value written into a record (a password, an address field).
  TEXT         free text (subject, body, content). Every URL / domain, email address and IBAN inside it is checked.
Arguments not in the policy are not checked: amounts, dates, and IDs of the user's own records. On their own they
cannot send anything to a new place. Known gap: a delete or a change aimed at the wrong record of the user's own
data is not caught, because the gate cannot tell which record the user meant.

Matching is on whole values, never on parts of words:
  - normalise: lowercase, drop "http://", "https://", "www." and a trailing "/", strip spaces and punctuation at the ends;
  - trusted set: the normalised value must equal a trusted value exactly;
  - user request / flagged text: the normalised value must appear there as a whole value (not inside a longer word,
    email address or domain). For the user request this is only allowed for values of 4 characters or more.

Known limitation (domains in free text): a link is found if it starts with "http://", "https://" or "www.", or if it
is a bare domain ending in one of the top-level domains in TLDS. A bare domain with any other ending (for example
"secure-systems-252.shop") or a written-out link ("secure-systems-252 dot com") is not found, so it is not checked.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

DESTINATION = "destination"
VALUE = "value"
TEXT = "text"
MIN_PROMPT_MATCH = 4  # shorter values are never trusted because they appear in the user's request

# High-risk tool -> {argument name: DESTINATION | VALUE | TEXT}
Policy = dict[str, dict[str, str]]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# Links with a scheme or "www.", and bare domains ending in a common top-level domain (secure-systems-252.com).
TLDS = "com|net|org|io|in|co|info|biz|me|ai|app|dev|xyz|site|online|link|ly|us|uk|de|ch"
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'()\[\]{}]+"
    rf"|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:{TLDS})\b(?:/[^\s<>\"'()\[\]{{}}]*)?",
    re.IGNORECASE)
END_PUNCTUATION = " \t\r\n.,;:!?*_`'\"()[]{}<>"


@dataclass(frozen=True)
class Decision:
    action: str  # "allow", "ask" or "block"
    reason: str
    untrusted: list[str] = field(default_factory=list)


def normalize(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"^(?:https?://)?(?:www\.)?", "", text)
    return text.strip(END_PUNCTUATION).rstrip("/").strip(END_PUNCTUATION)


def identifiers_in(text: str) -> list[str]:
    """URLs and domains, email addresses and IBANs written inside free text."""
    found = EMAIL_RE.findall(text)
    rest = EMAIL_RE.sub(" ", text)
    found += [m.rstrip(END_PUNCTUATION) for m in URL_RE.findall(rest)]
    found += IBAN_RE.findall(URL_RE.sub(" ", rest))
    return found


def appears_in(value: str, text: str) -> bool:
    """True if the normalised value is written in the text as a whole value, not as part of a longer one."""
    if not value:
        return False
    # Not preceded by a word character, "@", "-", "." or "/"; not followed by a word character, "@", "-", "/",
    # or a "." that continues the value (as in "emma" inside "emma.johnson@...").
    pattern = rf"(?<![\w@./-]){re.escape(value)}(?![\w@/-]|\.[\w-])"
    return re.search(pattern, normalize_text(text)) is not None


def normalize_text(text: str) -> str:
    """Lowercase and drop link prefixes, so text compares with normalised values."""
    text = re.sub(r"https?://", "", text.lower())
    return re.sub(r"(?<![\w.-])www\.", "", text)


class Gate:
    def __init__(self, policy: Policy, trusted: Iterable[Any]) -> None:
        self.policy = policy
        self.trusted = {normalize(v) for v in trusted if v is not None and normalize(v)}

    def is_trusted(self, value: Any, user_task: str) -> bool:
        v = normalize(value)
        if v == "" or v in self.trusted:
            return True
        return len(v) >= MIN_PROMPT_MATCH and appears_in(v, user_task)

    def check_call(self, tool: str, args: dict[str, Any], user_task: str,
                   flagged_texts: Iterable[str] = ()) -> Decision:
        """flagged_texts: the untrusted texts (tool outputs) that the screen flagged."""
        if tool not in self.policy:
            return Decision("allow", f"{tool} is not a high-risk tool")
        untrusted = []
        for name, kind in self.policy[tool].items():
            value = args.get(name)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                candidates = identifiers_in(str(item)) if kind == TEXT else [item]
                untrusted += [(name, c) for c in candidates if not self.is_trusted(c, user_task)]
        if not untrusted:
            return Decision("allow", f"{tool}: all checked values are trusted")
        flagged_texts = list(flagged_texts)
        from_flagged = [(n, c) for n, c in untrusted if any(appears_in(normalize(c), t) for t in flagged_texts)]
        listed = ", ".join(f"{n}={c!r}" for n, c in (from_flagged or untrusted))
        values = [str(c) for _, c in untrusted]
        if from_flagged:
            return Decision("block", f"{tool}: {listed} comes from text the screen flagged", values)
        return Decision("ask", f"{tool}: {listed} is new (not the user's own data, a saved contact, or in the "
                               f"user's request); confirm before running", values)
