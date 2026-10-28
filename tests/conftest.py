import pytest

# Tests must run on a clean machine (CI): no API keys, no model downloads. bench.adapters loads .env when it is
# imported, so the keys are removed again before every test. A test that needs one fails here instead of quietly
# spending money or downloading a model on a developer machine.
SECRET_ENV = ["MODEL_API_KEY", "BASETEN_API_KEY", "HF_TOKEN"]


@pytest.fixture(autouse=True)
def no_keys_no_downloads(monkeypatch):
    for name in SECRET_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
