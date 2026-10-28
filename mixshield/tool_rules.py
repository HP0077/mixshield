"""Name rules: which tools are high-risk and which of their arguments the gate checks (used by the proxy and by
Shield(policy="default")). The rules are described in mixshield/proxy.py. Moved here from proxy.py unchanged, so
they work without the mcp package.
"""

import re
from dataclasses import dataclass
from typing import Any, Iterable

from mixshield.gate import DESTINATION, TEXT, VALUE, Policy

# A tool is high-risk if its name has one of these words ...
HIGH_RISK_NAME_RE = re.compile(
    r"send|transfer|pay|schedule|delete|remove|share|post|invite|update|create|cancel|reschedule|add_|publish|"
    r"reserve|book|set_|change|move|write|submit|execute|run_|grant|revoke|approve", re.IGNORECASE)
# ... and low-risk only if it starts with a read-only verb (and has no high-risk word).
LOW_RISK_NAME_RE = re.compile(
    r"^(?:get|list|read|search|find|fetch|view|show|describe|count|check|lookup|query)(?:[_A-Z0-9]|$)")
# Argument names: what an argument is, by name.
DESTINATION_ARG_RE = re.compile(
    r"recipient|^to$|_to$|email|iban|address|url|channel|user|participant|^cc$|^bcc$|account|target|destination",
    re.IGNORECASE)
TEXT_ARG_RE = re.compile(r"body|subject|content|message|text|title|description|note|reference|memo|comment",
                         re.IGNORECASE)
VALUE_ARG_RE = re.compile(r"password|passwd|secret", re.IGNORECASE)
SAFE_TYPES = {"integer", "number", "boolean", "null"}  # arguments of only these types are never checked


@dataclass(frozen=True)
class ToolClass:
    risk: str  # "high" or "low"
    why: str
    checked: dict[str, str]  # argument -> kind (high-risk tools only)


def _types(schema: dict) -> set[str]:
    found: set[str] = set()
    declared = schema.get("type")
    found.update([declared] if isinstance(declared, str) else declared or [])
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []):
            found |= _types(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        found |= {f"[{t}]" for t in _types(items)}
    return found


def _arg_kind(name: str, schema: dict, by_name_only: bool) -> str | None:
    """Kind of one argument, or None if it is not checked. Fail-closed mode checks every non-numeric argument."""
    if VALUE_ARG_RE.search(name):
        return VALUE
    if DESTINATION_ARG_RE.search(name):
        return DESTINATION
    if TEXT_ARG_RE.search(name):
        return TEXT
    if by_name_only:
        return None
    types_ = _types(schema)
    if types_ and types_ <= SAFE_TYPES:
        return None
    return DESTINATION if types_ & {"string", "[string]"} else TEXT  # no clear type: scan it as text


def classify_tools(tools: Iterable[Any], overrides: Policy | None = None,
                   low_risk: Iterable[str] = ()) -> dict[str, ToolClass]:
    """`tools`: objects with .name and .inputSchema (MCP tools)."""
    overrides, low_risk = overrides or {}, set(low_risk)
    classes = {}
    for tool in tools:
        properties = (tool.inputSchema or {}).get("properties", {})
        if tool.name in low_risk:
            classes[tool.name] = ToolClass("low", "config low_risk list", {})
        elif tool.name in overrides:
            classes[tool.name] = ToolClass("high", "config policy", dict(overrides[tool.name]))
        elif LOW_RISK_NAME_RE.search(tool.name) and not HIGH_RISK_NAME_RE.search(tool.name):
            classes[tool.name] = ToolClass("low", "read-only name", {})
        else:
            named = HIGH_RISK_NAME_RE.search(tool.name) is not None
            checked = {a: k for a, s in properties.items() if (k := _arg_kind(a, s, by_name_only=named))}
            why = "high-risk name"
            if not named or not checked:
                checked = {a: k for a, s in properties.items() if (k := _arg_kind(a, s, by_name_only=False))}
                why = ("unclassified: treated as high-risk" if not named
                       else "high-risk name, no argument recognised: all arguments checked")
            classes[tool.name] = ToolClass("high", why, checked)
    return classes


def policy_of(classes: dict[str, ToolClass]) -> Policy:
    return {name: dict(c.checked) for name, c in classes.items() if c.risk == "high"}
