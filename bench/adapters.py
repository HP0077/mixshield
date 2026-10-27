"""Build AgentDojo pipelines for the two Meta models (Muse Spark, Muse Spark Open)."""

import os

import openai
from agentdojo.agent_pipeline import AgentPipeline, PipelineConfig
from agentdojo.agent_pipeline.llms.openai_llm import (
    OpenAILLM,
    _function_to_openai,
    _message_to_openai,
    _openai_to_assistant_message,
    chat_completion_request,
)
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.models import MODEL_NAMES
from dotenv import load_dotenv

load_dotenv()

MODELS = {
    "muse-spark": {
        "model_id": "muse-spark-1.3",
        "base_url": "https://api.meta.ai/v1",
        "key_env": "MODEL_API_KEY",
    },
    "muse-spark-open": {
        "model_id": "meta-models/muse-spark-open-1026",
        "base_url": "https://inference.baseten.co/v1",
        "key_env": "BASETEN_API_KEY",
    },
}

# AgentDojo's built-in attacks look up the model name here.
for _cfg in MODELS.values():
    MODEL_NAMES[_cfg["model_id"]] = "AI assistant"


class SystemRoleOpenAILLM(OpenAILLM):
    """Same as OpenAILLM, but sends system messages as role "system", not "developer"."""

    def query(self, query, runtime, env=EmptyEnv(), messages=[], extra_args={}):
        openai_messages = []
        for message in messages:
            converted = _message_to_openai(message, self.model)
            if converted["role"] == "developer":
                converted["role"] = "system"
            openai_messages.append(converted)
        tools = [_function_to_openai(t) for t in runtime.functions.values()]
        completion = chat_completion_request(
            self.client, self.model, openai_messages, tools, self.reasoning_effort, self.temperature
        )
        output = _openai_to_assistant_message(completion.choices[0].message)
        return query, runtime, env, [*messages, output], extra_args


def make_llm(key: str) -> SystemRoleOpenAILLM:
    cfg = MODELS[key]
    client = openai.OpenAI(api_key=os.environ[cfg["key_env"]], base_url=cfg["base_url"])
    llm = SystemRoleOpenAILLM(client, cfg["model_id"])
    llm.name = cfg["model_id"]
    return llm


def make_pipeline(key: str, defense: str | None = None) -> AgentPipeline:
    config = PipelineConfig(
        llm=make_llm(key),
        model_id=None,
        defense=defense,
        system_message_name=None,
        system_message=None,
    )
    return AgentPipeline.from_config(config)
