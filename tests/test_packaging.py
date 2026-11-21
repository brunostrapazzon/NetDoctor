"""O que o build do .exe pressupõe sobre o pacote."""

import re
from importlib import resources
from pathlib import Path

import netdoctor
from netdoctor.ui import app

ROOT = Path(__file__).parent.parent


def test_version_is_plain_semver():
    # O .spec converte a versão em 4 números para o recurso de versão do Windows.
    assert re.fullmatch(r"\d+\.\d+\.\d+", netdoctor.__version__)


def test_data_files_are_package_resources():
    # collect_data_files("netdoctor") só leva o que está dentro do pacote.
    assert resources.files("netdoctor.core").joinpath("thresholds.toml").is_file()
    assert resources.files("netdoctor.ui").joinpath("netdoctor.ico").is_file()
    assert app.ICON_PATH.is_file()


def test_pyproject_ships_the_same_data():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"core/*.toml"' in text and '"ui/*.ico"' in text


def test_release_tag_check_matches_version_source():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "netdoctor.__version__" in workflow
    assert "packaging/netdoctor.spec" in workflow
