"""An empty key (the `HF_TOKEN=` line of a copied .env.example) must count as not set."""

import os

import pytest

from mixshield import env


@pytest.fixture
def clean_environ(monkeypatch):
    """os.environ replaced by a copy without the three keys, so nothing leaks out of the test."""
    copy = {k: v for k, v in os.environ.items() if k not in env.KEYS}
    monkeypatch.setattr(os, "environ", copy)
    return copy


@pytest.mark.parametrize("empty", ["", " ", "   ", "\t", " \n"])
def test_empty_hf_token_is_treated_as_unset(clean_environ, empty):
    clean_environ["HF_TOKEN"] = empty
    assert env.clear_empty_keys() == ["HF_TOKEN"]
    assert "HF_TOKEN" not in os.environ
    assert os.environ.get("HF_TOKEN") is None  # what prompt_guard.py passes as token=: None, not "" (no "Bearer " header)


def test_all_three_keys_are_cleared_when_empty(clean_environ):
    for name in env.KEYS:
        clean_environ[name] = "  "
    assert sorted(env.clear_empty_keys()) == sorted(env.KEYS)
    assert not any(name in os.environ for name in env.KEYS)


def test_a_real_value_is_kept(clean_environ):
    clean_environ["HF_TOKEN"] = "hf_realvalue"
    clean_environ["BASETEN_API_KEY"] = ""
    assert env.clear_empty_keys() == ["BASETEN_API_KEY"]
    assert os.environ["HF_TOKEN"] == "hf_realvalue"


def test_other_variables_are_not_touched(clean_environ):
    clean_environ["SOMETHING_ELSE"] = ""
    env.clear_empty_keys()
    assert os.environ["SOMETHING_ELSE"] == ""


def test_load_env_from_a_copied_env_example(clean_environ, tmp_path):
    path = tmp_path / ".env"
    path.write_text("BASETEN_API_KEY=\nHF_TOKEN=\nMODEL_API_KEY=real-value\n", encoding="utf-8")
    env.load_env(path)
    assert "HF_TOKEN" not in os.environ and "BASETEN_API_KEY" not in os.environ
    assert os.environ["MODEL_API_KEY"] == "real-value"


def test_the_repo_env_example_has_empty_values_that_get_cleared(clean_environ):
    from pathlib import Path
    example = Path(__file__).resolve().parent.parent / ".env.example"
    env.load_env(example)
    assert all(name not in os.environ for name in env.KEYS)
