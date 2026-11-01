"""Records every real model call of a playground run or check, for the "Live model calls" panel (demo/viewer.py).

The playground's screen and agent are wrapped, not changed: Screen takes its Prompt Guard 2 scorer and its classifier
as replaceable parts, and the agent gets its OpenAI client passed in. Each wrapper reports a call twice, when it starts
and when it ends, to the sink of the current run (a context variable, so two visitors' runs never mix: a run's
thread sets it, and asyncio.to_thread passes it on to the screen's worker thread).

Only what the call itself sent and got back is reported: the start of the text, the score, the flag and reason, the
tool call. Never a key, a header or an error message (an error is reported by its type only).
"""

import itertools
import json
import threading
import time
from contextvars import ContextVar
from types import SimpleNamespace

PROMPT_GUARD = "Llama Prompt Guard 2 86M (local)"
CLASSIFIER = "Muse Spark Open (Baseten)"
AGENT = "Muse Spark Open, agent (Baseten)"
SENT_CHARS = 80
REASON_CHARS = 120

SINK: ContextVar = ContextVar("model_call_sink", default=None)
_ids = itertools.count(1)
_ids_lock = threading.Lock()


def short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _start(model: str, sent: str) -> tuple[int, float] | None:
    sink = SINK.get()
    if sink is None:
        return None
    with _ids_lock:
        call_id = next(_ids)
    sink({"id": call_id, "model": model, "sent": short(sent, SENT_CHARS), "back": None, "secs": None})
    return call_id, time.monotonic()


def _end(started, model: str, sent: str, back: str) -> None:
    sink = SINK.get()
    if sink is None or started is None:
        return
    call_id, t0 = started
    sink({"id": call_id, "model": model, "sent": short(sent, SENT_CHARS), "back": back,
          "secs": round(time.monotonic() - t0, 2)})


class TimedPromptGuard:
    """Prompt Guard 2 (anything with .score(text)), reporting each score."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def score(self, text: str) -> float:
        started = _start(PROMPT_GUARD, text)
        try:
            value = self.inner.score(text)
        except Exception as exc:
            _end(started, PROMPT_GUARD, text, f"error: {type(exc).__name__}")
            raise
        _end(started, PROMPT_GUARD, text, f"score {float(value):.4f}")
        return value


class TimedClassifier:
    """The Muse Spark Open classifier (text -> (flagged, score, reason)), reporting each verdict."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def __call__(self, text: str):
        started = _start(CLASSIFIER, text)
        try:
            flagged, score, reason = self.inner(text)
        except Exception as exc:
            _end(started, CLASSIFIER, text, f"error: {type(exc).__name__}")
            raise
        _end(started, CLASSIFIER, text, f"flagged: {'yes' if flagged else 'no'}. {short(reason, REASON_CHARS)}")
        return flagged, score, reason


def tool_calls_text(message) -> str:
    """The agent's reply: its tool calls as name(arguments), or the start of its text."""
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return "answer: " + short(getattr(message, "content", "") or "", SENT_CHARS)
    parts = []
    for c in calls:
        try:
            args = json.loads(c.function.arguments or "{}")
            shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        except (ValueError, AttributeError):
            shown = short(c.function.arguments, SENT_CHARS)
        parts.append(f"{c.function.name}({shown})")
    return "tool call: " + "; ".join(parts)


class TimedClient:
    """An OpenAI async client for the agent, reporting each chat request. Only .chat.completions.create is used."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        sent = "tool call request"
        started = _start(AGENT, sent)
        try:
            response = await self.inner.chat.completions.create(**kwargs)
        except Exception as exc:
            _end(started, AGENT, sent, f"error: {type(exc).__name__}")
            raise
        _end(started, AGENT, sent, tool_calls_text(response.choices[0].message))
        return response


def install(screen) -> None:
    """Wrap a Screen's Prompt Guard 2 and classifier once. A Prompt Guard 2 that did not load (None) is left alone,
    so the screen still fails closed on it."""
    if screen.prompt_guard is not None and not isinstance(screen.prompt_guard, TimedPromptGuard):
        screen.prompt_guard = TimedPromptGuard(screen.prompt_guard)
    if not isinstance(screen.classifier, TimedClassifier):
        screen.classifier = TimedClassifier(screen.classifier)
