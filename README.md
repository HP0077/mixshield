# MixShield

Benchmark and open-source guardrail that protects tool-using AI agents from hidden instructions (indirect prompt injection) written in English, Hindi and Hinglish.

## Headline result

_TODO (Day 9): one sentence and one chart. Numbers come only from the finished experiments._

## Demo

_TODO: demo GIF (attack email, screen flag, blocked transfer, normal payment goes through)._

## Links

- Video: _TODO_
- Playground: _TODO (Hugging Face Space)_

## Meta models used

- Muse Spark: agent in the benchmark.
- Muse Spark Open: agent, and the code-mixing-aware classifier inside the MixShield screen.
- Llama Prompt Guard 2 (86M) and Llama Guard 3 (1B): baseline detectors.

## Quickstart

_TODO: the package is not published yet. Until then, install from a clone:_

```
pip install -e ".[proxy]"
```

Put any MCP server behind the proxy:

```
mixshield proxy --upstream "<command that starts any MCP server>"
```

Python:

```python
from mixshield import Shield
shield = Shield(policy="default")
verdict = shield.screen(text)  # flagged, score, language, reason
decision = shield.check_call(tool, args, user_task, untrusted_texts)  # allow | block | ask
```

_TODO: check that this matches the final interface before release._

## How it works

### Input screen

_TODO: normalise the text, score it with Prompt Guard 2 and with Muse Spark Open as a classifier, flag if either passes its threshold._

### Action gate

Every proposed tool call is checked and gets one of three answers:

- **allow**: every checked value is trusted.
- **block**: an untrusted value appears in text the screen flagged.
- **ask**: an untrusted value that is not from flagged text; a human confirms.

_TODO: trusted data, checked arguments, known gaps._

### Human approval

_TODO: how "ask" decisions pause for a yes/no, and the rule used in experiments._

## Results

_TODO (Day 8): E1 to E5 tables and charts._

## How we kept results honest

_TODO: attack success measured by AgentDojo's own state-based scorer; thresholds tuned on the dev split only; sanity checks before any number is trusted._

## Limitations

_TODO._

## Built during the hackathon / Used as-is

**Built during the hackathon**

_TODO_

**Used as-is**

_TODO (AgentDojo, Llama Prompt Guard 2, Llama Guard 3, Muse Spark models, Gradio, MCP SDK, LangGraph)._

## Ethics

_TODO: link to `docs/ethics.md` once it is written._

## Licence

MIT. See [LICENSE](LICENSE).
