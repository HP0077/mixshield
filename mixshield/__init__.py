"""MixShield: a guardrail for tool-using AI agents against indirect prompt injection in English, Hinglish and Hindi.

    from mixshield import Shield
    shield = Shield(policy="default", trusted=["<the user's own IBAN>", "<a saved contact>"])
    verdict = shield.screen(text)  # flagged, score, language, reason
    decision = shield.check_call(tool, args, user_task, untrusted_texts)  # decision.action: allow | ask | block

policy   "default": the proxy's name rules (mixshield/tool_rules.py) decide, for every tool, whether it is high-risk
         and which arguments are checked; argument types come from the values in the call (numbers and booleans are
         never checked). Or a dict {tool: {argument: "destination" | "value" | "text"}}: only the listed tools are
         checked, as in mixshield/gate.py.
trusted  the user's own data and saved contacts.
untrusted_texts  texts the agent has read from tools (emails, documents, messages). Each text is screened once.
The Shield keeps every text the screen flagged, from screen() and from check_call(), for its whole life, so a later
call that uses an untrusted value from one of them is blocked. Use one Shield per user session.
"""

from types import SimpleNamespace
from typing import Any, Callable, Iterable

from mixshield.approval import FlaggedText
from mixshield.gate import Decision, Gate, Policy
from mixshield.screen import Screen, ScreenVerdict
from mixshield.tool_rules import classify_tools

__all__ = ["Decision", "Gate", "Screen", "ScreenVerdict", "Shield"]


def _schema_of(value: Any) -> dict:
    """A JSON-schema type for one argument value, so the name rules can skip numbers and booleans."""
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return {"type": "array", "items": {"type": "string"}}
    return {}  # no clear type: scanned as text


class Shield:
    def __init__(self, policy: Policy | str = "default", trusted: Iterable[Any] = (),
                 screen: Callable[[str], ScreenVerdict] | None = None) -> None:
        if isinstance(policy, str) and policy != "default":
            raise ValueError(f'policy must be "default" or a dict, not {policy!r}')
        self.by_name = policy == "default"
        self.gate = Gate({} if self.by_name else dict(policy), trusted)
        self._screen = screen or Screen()
        self.verdicts: dict[str, ScreenVerdict] = {}
        self.flagged: list[FlaggedText] = []

    @property
    def flagged_texts(self) -> list[str]:
        return [f.text for f in self.flagged]

    def screen(self, text: str) -> ScreenVerdict:
        if text not in self.verdicts:
            verdict = self._screen(text)
            self.verdicts[text] = verdict
            if verdict.flagged:
                self.flagged.append(FlaggedText(text, verdict.reason))
        return self.verdicts[text]

    def check_call(self, tool: str, args: dict[str, Any], user_task: str,
                   untrusted_texts: Iterable[str] = ()) -> Decision:
        for text in untrusted_texts:
            self.screen(text)
        if self.by_name:
            schema = {"properties": {name: _schema_of(value) for name, value in args.items()}}
            tool_class = classify_tools([SimpleNamespace(name=tool, inputSchema=schema)])[tool]
            if tool_class.risk == "high":
                self.gate.policy[tool] = tool_class.checked
            else:
                self.gate.policy.pop(tool, None)
        return self.gate.check_call(tool, args, user_task, self.flagged_texts)
