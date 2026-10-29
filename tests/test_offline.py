"""A integração inteira é offline-first: sem rede no caminho do cálculo."""

import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).parent.parent / "custom_components" / "mw_lumina"

PROIBIDOS_NOS_MODULOS_CALCULO = ["requests", "urllib", "httpx", "aiohttp", "socket"]


def test_puro_calculo_nao_importa_rede():
    """engine.py, solar.py, scenes.py e lumina_defaults.py jamais falam com a internet."""
    for modulo in ("engine.py", "solar.py", "scenes.py", "lumina_defaults.py"):
        src = (RAIZ / modulo).read_text()
        for proibido in PROIBIDOS_NOS_MODULOS_CALCULO:
            assert f"import {proibido}" not in src, f"{modulo} importa {proibido}"
            assert f"from {proibido}" not in src, f"{modulo} chama {proibido}"


def test_sem_segrefo_versionado():
    """Nenhum token/chave no código (varre o repositório, fora de CI e testes)."""
    padrao = re.compile(
        r"(ghp_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9]{20,}$|sk-[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_\-]{20,})"
    )
    for path in RAIZ.parent.parent.rglob("*"):
        if path.suffix not in (".py", ".js", ".json", ".yaml", ".yml", ".md", ".html", ".css"):
            continue
        if any(part in {".git", "__pycache__", ".github", "tests", ".venv"} for part in path.parts):
            continue
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue
        assert not padrao.search(content), f"token suspeito em {path}"


def test_coordinator_importa_offline_ok():
    pytest.importorskip("homeassistant")
    from custom_components.mw_lumina import coordinator as coord_mod  # noqa: F401
    from custom_components.mw_lumina.const import DOMAIN

    assert DOMAIN == "mw_lumina"
