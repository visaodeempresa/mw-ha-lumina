"""Cenas: registro coeso, resolução e fallback customizado."""

from custom_components.mw_lumina.scenes import SCENE_ORDER, SCENES, resolve_scene


def test_registro_cenas_integro():
    assert len(SCENES) >= 10
    for sid, scene in SCENES.items():
        assert 1500 <= scene.kelvin <= 5800, sid
        assert 1 <= scene.brightness <= 100, sid
        assert scene.name and scene.description, sid
    assert len(SCENE_ORDER) == len(SCENES)


def test_ids_unicos_e_nomes_distintos():
    names = [s.name for s in SCENES.values()]
    assert len(names) == len(set(names))


def test_cenas_obrigatorias_do_briefing():
    for esperadas in ("por_do_sol", "cinema", "trabalho", "descanso", "festa"):
        assert esperadas in SCENES


def test_cinema_mais_quente_e_escurecido_que_trabalho():
    assert SCENES["cinema"].kelvin < SCENES["trabalho"].kelvin
    assert SCENES["cinema"].brightness < SCENES["trabalho"].brightness / 5


def test_cena_customizada_faz_fallback():
    scene = resolve_scene("cinema", {})
    assert scene is not None and scene.name == "Cinema"

    custom = resolve_scene(
        "minha_cena", {"minha_cena": {"name": "Zen", "kelvin": 2800, "brightness": 30}}
    )
    assert custom.kelvin == 2800
    assert resolve_scene("fantasma", {}) is None
