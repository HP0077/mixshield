"""Approval of "ask" decisions. Read before accepting.

The gate returns "ask" when a high-risk call uses a value that is new (not the user's own data, not a saved contact,
not in the user's request) and does not come from flagged text. Something must then say yes or no:
  - a human (the demo: demo/agent.py shows `format_request(...)` through a LangGraph interrupt and waits), or
  - `RuleApprover`, for experiments, so a run needs no person.

Both get the same `ApprovalRequest`, and it holds ONLY what a human would see: the user's request, the proposed call,
the gate's decision with its reason and the untrusted values, and the texts the screen flagged with the screen's
reason. It has no field for attack labels, injection-task ids or ground truth, and nothing in the proxy or an
experiment may add one (tests/test_approval.py checks the field names). The rule must never be improved by looking
at which calls were really attacks.

RuleApprover (CLAUDE.md section 5): approve only what the user themselves asked for.
  deny  if an untrusted value comes from a text the screen flagged;
  deny  if an untrusted value is not written in the user's request (whole value, case ignored, no minimum length:
        this is how a short name such as "Bob" in the request is approved even though the gate would not trust it);
  deny  if there is no untrusted value to judge (fail closed);
  else approve.
A human prompt answer is parsed by `parse_answer`: only "yes" / "y" approve, anything else denies.
"""

import json
from dataclasses import dataclass
from typing import Any

from mixshield.gate import Decision, appears_in, normalize


@dataclass(frozen=True)
class FlaggedText:
    text: str
    reason: str  # the screen's reason


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    args: dict[str, Any]
    decision: Decision  # the gate's decision: action, reason, untrusted values
    user_task: str  # the user's own request
    flagged: tuple[FlaggedText, ...] = ()  # texts the screen flagged so far, with the screen's reason


@dataclass(frozen=True)
class Verdict:
    approve: bool
    reason: str


class RuleApprover:
    """Rule-based approver for experiments. Callable: approver(request) -> bool; `decide` gives the reason too."""

    def decide(self, request: ApprovalRequest) -> Verdict:
        values = request.decision.untrusted
        if not values:
            return Verdict(False, "no untrusted value to judge")
        for value in values:
            normalized = normalize(value)
            for flagged in request.flagged:
                if appears_in(normalized, flagged.text):
                    return Verdict(False, f"{value!r} comes from a text the screen flagged ({flagged.reason})")
            if not appears_in(normalized, request.user_task):
                return Verdict(False, f"{value!r} is not in the user's request")
        return Verdict(True, "every new value is written in the user's request and none comes from flagged text")

    def __call__(self, request: ApprovalRequest) -> bool:
        return self.decide(request).approve


def format_request(request: ApprovalRequest) -> str:
    """The text a person reads before answering yes or no."""
    lines = [
        "MixShield needs your approval.",
        f"  Your request : {request.user_task or '(not given)'}",
        f"  Proposed call: {request.tool}({json.dumps(request.args, ensure_ascii=False)})",
        f"  Decision     : {request.decision.action}",
        f"  Reason       : {request.decision.reason}",
        f"  New values   : {', '.join(request.decision.untrusted) or '(none)'}",
    ]
    if request.flagged:
        lines.append(f"  Flagged texts: {len(request.flagged)} so far ({'; '.join(f.reason for f in request.flagged)})")
    else:
        lines.append("  Flagged texts: none so far")
    return "\n".join(lines)


def approval_payload(request: ApprovalRequest) -> dict[str, Any]:
    """The same information as plain JSON, for a UI (the LangGraph interrupt value)."""
    return {
        "question": format_request(request),
        "tool": request.tool,
        "args": request.args,
        "decision": request.decision.action,
        "reason": request.decision.reason,
        "untrusted": list(request.decision.untrusted),
        "flagged_reasons": [f.reason for f in request.flagged],
    }


def parse_answer(answer: Any) -> bool:
    """yes / y / true approve. Anything else, including an empty answer, denies."""
    if isinstance(answer, bool):
        return answer
    return str(answer).strip().lower() in ("yes", "y", "true")
