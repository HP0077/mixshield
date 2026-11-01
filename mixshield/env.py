"""Loads .env, and treats a key that is empty (or only spaces) as not set.

`copy .env.example .env` leaves lines like `HF_TOKEN=`. python-dotenv then sets HF_TOKEN to an empty string, and
Hugging Face sends the header "Authorization: Bearer " (nothing after it), which fails with "Illegal header value".
An unset variable means "no token", so the empty ones are removed from os.environ right after .env is loaded.
"""

import os

from dotenv import load_dotenv

KEYS = ("HF_TOKEN", "BASETEN_API_KEY", "MODEL_API_KEY")


def clear_empty_keys(environ=None) -> list[str]:
    """Remove each of KEYS whose value is empty or only whitespace. Returns the names removed (never the values)."""
    environ = os.environ if environ is None else environ
    removed = [name for name in KEYS if name in environ and not environ[name].strip()]
    for name in removed:
        del environ[name]
    return removed


def load_env(path=None) -> None:
    """load_dotenv() (the .env found from this file upwards, or `path`), then clear_empty_keys()."""
    load_dotenv(dotenv_path=path)
    clear_empty_keys()
