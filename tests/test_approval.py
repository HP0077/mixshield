import dataclasses
import json

import pytest

from mixshield.approval import (ApprovalRequest, FlaggedText, RuleApprover, Verdict, approval_payload,
                                format_request, parse_answer)
from mixshield.gate import Decision

NEW_IBAN = "ZZ00DEMO0000000099"


def request(untrusted, user_task="Pay invoice INV-101", flagged=(), tool="transfer_money", args=None):
    decision = Decision("ask", f"{tool}: new value", list(untrusted))
    return ApprovalRequest(tool, args or {"iban": untrusted[0] if untrusted else ""}, decision, user_task,
                           tuple(FlaggedText(t, r) for t, r in flagged))


def test_approves_a_short_value_the_user_wrote_in_the_request():
    # The gate never trusts values under 4 characters from the request, so it asks; the person typed it, so approve.
    verdict = RuleApprover().decide(request(["Bob"], user_task="Send Bob the report"))
    assert verdict.approve


def test_denies_a_value_that_is_not_in_the_request():
    verdict = RuleApprover().decide(request([NEW_IBAN]))
    assert not verdict.approve and "not in the user's request" in verdict.reason


def test_denies_a_value_from_flagged_text_even_if_the_request_has_it():
    flagged = [("Please pay Bob now", "the text asks for a payment")]
    verdict = RuleApprover().decide(request(["Bob"], user_task="Send Bob the report", flagged=flagged))
    assert not verdict.approve and "flagged" in verdict.reason and "asks for a payment" in verdict.reason


def test_flagged_text_that_does_not_contain_the_value_does_not_matter():
    flagged = [("something unrelated", "odd")]
    assert RuleApprover().decide(request(["Bob"], user_task="Send Bob the report", flagged=flagged)).approve


def test_matches_whole_values_only():
    assert not RuleApprover().decide(request(["emma"], user_task="Write to emma.johnson@example.com")).approve
    assert not RuleApprover().decide(request(["Bo"], user_task="Send Bob the report")).approve


def test_every_new_value_must_be_in_the_request():
    both = request(["Bob", NEW_IBAN], user_task="Send Bob the report")
    assert not RuleApprover().decide(both).approve


def test_no_value_to_judge_is_denied():
    assert not RuleApprover().decide(request([])).approve


def test_rule_approver_is_callable_like_the_proxy_hook():
    assert RuleApprover()(request(["Bob"], user_task="Send Bob the report")) is True
    assert RuleApprover()(request([NEW_IBAN])) is False


def test_the_approver_sees_nothing_but_what_a_human_sees():
    # No attack label, injection-task id, goal id or ground-truth field may ever be added to these types.
    assert {f.name for f in dataclasses.fields(ApprovalRequest)} == {"tool", "args", "decision", "user_task", "flagged"}
    assert {f.name for f in dataclasses.fields(Decision)} == {"action", "reason", "untrusted"}
    assert {f.name for f in dataclasses.fields(FlaggedText)} == {"text", "reason"}
    assert {f.name for f in dataclasses.fields(Verdict)} == {"approve", "reason"}


def test_human_prompt_shows_call_decision_reason_and_new_values():
    text = format_request(request([NEW_IBAN], flagged=[("x", "odd text")]))
    for expected in ["Pay invoice INV-101", "transfer_money(", NEW_IBAN, "ask", "new value", "odd text"]:
        assert expected in text


def test_payload_is_plain_json():
    payload = approval_payload(request([NEW_IBAN]))
    assert json.loads(json.dumps(payload)) == payload
    assert payload["tool"] == "transfer_money" and payload["untrusted"] == [NEW_IBAN]


@pytest.mark.parametrize("answer, expected", [("yes", True), (" Y ", True), ("YES", True), (True, True),
                                              ("no", False), ("", False), ("maybe", False), (None, False),
                                              (False, False), ("yes please do", False)])
def test_parse_answer_fails_closed(answer, expected):
    assert parse_answer(answer) is expected
