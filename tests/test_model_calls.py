"""The "Live model calls" panel: what the wrappers report, and that no key ever reaches the page."""

import asyncio
from types import SimpleNamespace

import pytest

from demo import model_calls, viewer

KEY = "sk-test-SECRET-0123456789"


class FakePromptGuard:
    def score(self, text):
        return 0.0009


def fake_classifier(text):
    return True, 0.92, "Email asks to pay a new bank account."


def failing_classifier(text):
    raise RuntimeError(f"401 Unauthorized: bad key {KEY} (Authorization: Bearer {KEY})")


def tool_call_response():
    call = SimpleNamespace(function=SimpleNamespace(
        name="transfer_money", arguments='{"iban": "ZZ00DEMO0000000001", "amount": 120.0}'))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[call]))])


class FakeAsyncClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        if self.fail:
            raise RuntimeError(f"connection refused, api_key={KEY}")
        return tool_call_response()


def collect(fn):
    """Run fn() with a sink; return the calls as the panel would hold them."""
    calls = []
    token = model_calls.SINK.set(lambda data: viewer.merge_call(calls, {**data, "t": 0.0}))
    try:
        fn()
    finally:
        model_calls.SINK.reset(token)
    return calls


def test_reports_real_values():
    def go():
        model_calls.TimedPromptGuard(FakePromptGuard()).score("Namaste Emma, hamara bank account badal gaya hai.")
        model_calls.TimedClassifier(fake_classifier)("Namaste Emma, hamara bank account badal gaya hai.")
        asyncio.run(model_calls.TimedClient(FakeAsyncClient()).chat.completions.create(model="m", messages=[]))

    calls = collect(go)
    assert [c["model"] for c in calls] == [model_calls.PROMPT_GUARD, model_calls.CLASSIFIER, model_calls.AGENT]
    assert calls[0]["back"] == "score 0.0009"
    assert calls[1]["back"] == "flagged: yes. Email asks to pay a new bank account."
    assert calls[2]["sent"] == "tool call request"
    assert calls[2]["back"] == "tool call: transfer_money(iban='ZZ00DEMO0000000001', amount=120.0)"
    assert all(c["secs"] is not None for c in calls)


def test_start_is_reported_before_the_end():
    seen = []
    token = model_calls.SINK.set(lambda data: seen.append(dict(data)))
    try:
        model_calls.TimedClassifier(fake_classifier)("text")
    finally:
        model_calls.SINK.reset(token)
    assert seen[0]["back"] is None and seen[0]["secs"] is None
    assert seen[1]["id"] == seen[0]["id"] and seen[1]["back"].startswith("flagged: yes")


def test_long_text_is_cut():
    calls = collect(lambda: model_calls.TimedPromptGuard(FakePromptGuard()).score("x " * 200))
    assert len(calls[0]["sent"]) <= model_calls.SENT_CHARS


def test_no_sink_records_nothing():
    assert model_calls.SINK.get() is None
    assert model_calls.TimedClassifier(fake_classifier)("text")[0] is True


def test_panel_never_contains_the_api_key(monkeypatch):
    for name in ("BASETEN_API_KEY", "MODEL_API_KEY", "HF_TOKEN"):
        monkeypatch.setenv(name, KEY)

    def go():
        with pytest.raises(RuntimeError):
            model_calls.TimedClassifier(failing_classifier)(f"some text")
        with pytest.raises(RuntimeError):
            asyncio.run(model_calls.TimedClient(FakeAsyncClient(fail=True)).chat.completions.create(model="m"))
        model_calls.TimedClassifier(fake_classifier)("normal text")

    calls = collect(go)
    assert calls[0]["back"] == "error: RuntimeError"
    assert calls[1]["back"] == "error: RuntimeError"
    run = viewer.new_run("simulated", True, "banner", "task")
    for c in calls:
        viewer.apply(run, "model_call", c)
    for page in (viewer.calls_html(calls), viewer.render(run)):
        assert KEY not in page
        assert "Bearer" not in page and "api_key" not in page


def test_merge_keeps_start_time():
    calls = []
    viewer.merge_call(calls, {"id": 1, "t": 1.5, "model": "m", "sent": "s", "back": None, "secs": None})
    viewer.merge_call(calls, {"id": 1, "t": 4.0, "model": "m", "sent": "s", "back": "score 0.1000", "secs": 2.5})
    assert calls == [{"id": 1, "t": 1.5, "model": "m", "sent": "s", "back": "score 0.1000", "secs": 2.5}]


def test_old_replay_says_it_has_no_call_log():
    run = viewer.replay({"mode": "simulated", "protected": True, "banner": "b", "task": "t", "events": [],
                         "recorded_at": "2026-10-31 11:31 UTC"})
    assert "has no call log" in viewer.render(run)


def test_install_wraps_once():
    screen = SimpleNamespace(prompt_guard=FakePromptGuard(), classifier=fake_classifier)
    model_calls.install(screen)
    model_calls.install(screen)
    assert isinstance(screen.prompt_guard, model_calls.TimedPromptGuard)
    assert not isinstance(screen.prompt_guard.inner, model_calls.TimedPromptGuard)
    assert isinstance(screen.classifier, model_calls.TimedClassifier)
