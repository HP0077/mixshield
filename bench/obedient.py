"""The obedient agent: a SCRIPTED WORST-CASE SIMULATION, NOT A REAL MODEL. Used for E3a and E4 only.

Both real agents resisted every attack in E1 (0 of 536), so defences cannot be compared on them. This stand-in is
as easy to hijack as possible, so a defence's attack success rate shows what the defence itself stops:
  1. It makes the user task's AgentDojo ground-truth calls, one per turn. AgentDojo chooses the injection points
     from exactly these calls, so the attack text always reaches a tool output.
  2. If the attack text is still visible in a tool result it received (bench.e1_exposure.exposure: as is, with
     whitespace collapsed, or after YAML parsing), it then makes the injection task's ground-truth calls, one per
     turn. If a defence removed the text, it does not attack.
  3. It ends with a short text reply.
Ground-truth calls are computed once, on the environment as it was when the run started (as in bench/sanity_e1.py).
A refused call does not stop it: it goes on with its next call. It reads no tool output except to check (2).
It has no model, so it costs nothing and uses no tokens.
"""

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import FunctionCall
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

from bench.e1_exposure import exposure

LABEL = "obedient agent (scripted worst-case simulation, not a real model)"


def result_blocks(messages) -> list[str]:
    """Every text block of every tool result, one by one. Not joined: a notice added after a YAML tool output
    would make the joined text unparseable, and texts that only match after YAML parsing would be missed."""
    return [b.get("content") or "" for m in messages if m["role"] == "tool" for b in m["content"] or []]


class ObedientAgent(BasePipelineElement):
    def __init__(self, user_task, injection_task, attack_text: str | None) -> None:
        self.user_task, self.injection_task, self.attack_text = user_task, injection_task, attack_text
        self.plan: list[FunctionCall] | None = None
        self.attacker_plan: list[FunctionCall] = []
        self.attacked: bool | None = None  # None until the check in step 2 is made
        # Read by the runners like a model object.
        self.calls: list = []
        self.input_tokens = self.output_tokens = 0
        self.budget = None

    def query(self, query, runtime, env=None, messages=(), extra_args={}):
        if self.plan is None:
            start = env.model_copy(deep=True)
            self.plan = list(self.user_task.ground_truth(start))
            self.n_user_calls = len(self.plan)
            self.attacker_plan = list(self.injection_task.ground_truth(start)) if self.injection_task else []
        done = sum(1 for m in messages if m["role"] == "assistant" and m["tool_calls"])
        if done == len(self.plan) and self.attacked is None:
            seen = self.attack_text is not None and exposure(self.attack_text, result_blocks(messages)) != ""
            self.attacked = seen
            if seen:
                self.plan = [*self.plan, *self.attacker_plan]
        if done < len(self.plan):
            call = self.plan[done]
            # "user_N" / "attacker_N": lets the gate log count refused calls of the user task itself
            role = "user" if done < self.n_user_calls else "attacker"
            call = FunctionCall(function=call.function, args=dict(call.args), id=f"{role}_{done}")
            message = ChatAssistantMessage(role="assistant", tool_calls=[call],
                                           content=[text_content_block_from_string("")])
        else:
            message = ChatAssistantMessage(role="assistant", tool_calls=None,
                                           content=[text_content_block_from_string("Done.")])
        return query, runtime, env, [*messages, message], extra_args
