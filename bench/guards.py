"""Llama Prompt Guard 2 (86M) scorer. Long text is cut into 512-token chunks; the score is the max."""

import os

import torch
from dotenv import load_dotenv
from transformers import AutoModelForSequenceClassification, AutoTokenizer

load_dotenv()  # HF_TOKEN and HF_HOME come from .env / the environment

MODEL_ID = "meta-llama/Llama-Prompt-Guard-2-86M"
WINDOW = 512


class PromptGuard2:
    def __init__(self) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=os.environ.get("HF_TOKEN"))
        self.model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID, token=os.environ.get("HF_TOKEN"))
        self.model.eval()
        # Label 1 is "malicious" (label 0 is benign).
        assert self.model.config.id2label[1].lower() in ("label_1", "malicious"), self.model.config.id2label

    def score(self, text: str) -> float:
        ids = self.tokenizer(text, add_special_tokens=False)["input_ids"]
        body = WINDOW - 2  # room for the start and end tokens
        chunks = [ids[i:i + body] for i in range(0, max(len(ids), 1), body)]
        best = 0.0
        with torch.no_grad():
            for chunk in chunks:
                input_ids = torch.tensor([[self.tokenizer.cls_token_id, *chunk, self.tokenizer.sep_token_id]])
                logits = self.model(input_ids=input_ids).logits
                best = max(best, torch.softmax(logits, dim=-1)[0, 1].item())
        return best
