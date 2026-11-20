from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_real_llm_config(monkeypatch, request):
    """Testes nunca leem o .env real nem chamam a IA de verdade."""
    if request.node.get_closest_marker("real_llm_config"):
        return
    monkeypatch.setattr("netdoctor.explain.llm.load_config", lambda *a, **k: None)


def pytest_configure(config):
    config.addinivalue_line("markers", "real_llm_config: usa o load_config verdadeiro")


@pytest.fixture
def fixture_text():
    def _read(relative: str) -> str:
        return (FIXTURES / relative).read_text(encoding="utf-8")

    return _read
