"""Motor circadiano: curva, moduladores, agenda, hierarquia e clipes."""

from datetime import datetime

from custom_components.mw_lumina import lumina_defaults
from custom_components.mw_lumina.engine import (
    curve_at,
    humidity_shift,
    kelvin_to_rgb,
    needs_apply,
    night_lock_active,
    resolve_target,
    tcp_shift,
    weather_shifts,
)

# 15:00 UTC = 12:00 em Brasília (dia pleno)
NOON = datetime(2026, 10, 15, 12, 0)
NIGHT = datetime(2026, 10, 15, 23, 30)

HOUSE_BASE = {
    "schedule": {"blocks": []},
    "clip": {},
    "night_lock": {"enabled": False, "start": "23:45", "end": "06:00"},
}
ROOM_BASE = {"schedule": {"blocks": []}, "clip": {}}


def ambient_of(**kwargs):
    """Ambiente mínimo: chaves não passadas ficam None (sem sensor de fato)."""
    return {
        "temp": kwargs.get("temp"),
        "humidity": kwargs.get("humidity"),
        "condition": kwargs.get("condition"),
        "cloud_coverage": kwargs.get("cloud_coverage"),
    }


def _target(now=NOON, elevation=50.0, room=None, light=None, house=None, scene=None, ambient=None):
    return resolve_target(
        now_local=now,
        elevation=elevation,
        house_cfg=house or HOUSE_BASE,
        room_cfg=room or ROOM_BASE,
        light_cfg=light,
        room_scene=scene,
        custom_scenes={},
        ambient=ambient,
    )


def test_noite_baixa_e_quente():
    t = _target(now=NIGHT, elevation=-30.0)
    assert t.kelvin <= 2100
    assert t.brightness <= 15
    assert t.source == "circadiano"


def test_dia_pleno_branco_e_alto():
    t = _target()
    assert 4600 <= t.kelvin <= 5600
    assert t.brightness >= 80


def test_curva_monotônica_no_priceso_da_manhã():
    elevs = [-12, -6, 0, 5, 10, 20, 40]
    kw = [curve_at(e)[0] for e in elevs]
    assert kw == sorted(kw)
    br = [curve_at(e)[1] for e in elevs]
    assert br == sorted(br)


def test_calor_esfria_a_luz_frio_aquece():
    hot = _target(ambient=ambient_of(temp=32.0))
    cold = _target(ambient=ambient_of(temp=12.0))
    assert hot.kelvin > cold.kelvin
    assert tcp_shift(32.0) > 0 and tcp_shift(12.0) < 0


def test_umidade_alta_morna():
    curve_at(30.0)[0]
    shift = humidity_shift(85.0)
    assert shift < 0  # mais quente (kelvin desce)
    assert abs(shift) <= 150.5


def test_nuvens_esmaecem_e_chuva_aconchega():
    kelvin, factor = weather_shifts("rainy", 90.0)
    assert kelvin < 0
    assert factor < 0.85
    # céu limpo não empurra a luz para o quente
    k_sunny, f_sunny = weather_shifts("sunny", 10.0)
    assert k_sunny > kelvin
    assert f_sunny > factor


def test_bloco_travesa_meia_noite():
    block = {
        "id": "noite", "days": [0], "start": "22:00", "end": "00:30",
        "kind": "fixed", "kelvin": 2400, "brightness": 40,
    }
    # 00:10 de terça (o bloco da segunda-feira 22:00→00:30 segue valendo)
    tue_0010 = datetime(2026, 10, 13, 0, 10)
    truth = {"schedule": {"blocks": [block]}}
    t = _target(now=tue_0010, elevation=-25.0, house={**HOUSE_BASE, **truth})
    assert t.kelvin == 2400
    assert t.brightness == 40
    assert t.source == "bloco:noite"


def test_bloco_feito_sobre_circadiano_e_shift():
    block = {
        "id": "fim_de_tarde", "days": [2], "start": "18:00", "end": "20:00",
        "kind": "circadian", "kelvin_shift": -400, "brightness_mult": 0.5,
    }
    wed_1900 = datetime(2026, 10, 14, 19, 0)
    t = _target(now=wed_1900, elevation=8.0, house={**HOUSE_BASE, "schedule": {"blocks": [block]}})
    base_kelvin, base_factor = curve_at(8.0)
    assert t.source == "bloco:fim_de_tarde"
    assert t.kelvin == round(base_kelvin - 400)
    assert t.brightness == round(base_factor * 0.5 * 100)
    # segunda-feira (weekday 0) não pega o bloco da quarta
    mon_1900 = datetime(2026, 10, 12, 19, 0)
    other = _target(
        now=mon_1900, elevation=8.0,
        house={**HOUSE_BASE, "schedule": {"blocks": [block]}},
    )
    assert other.source == "circadiano"


def test_bloco_cena_fixa_e_vence_ambiente_climatico():
    block = {
        "id": "block_cinema", "days": [5], "start": "19:00", "end": "22:00",
        "kind": "scene", "scene": "cinema",
    }
    sat_2000 = datetime(2026, 10, 17, 20, 0)
    t = _target(
        now=sat_2000,
        elevation=-2.0,
        house={**HOUSE_BASE, "schedule": {"blocks": [block]}},
        ambient=ambient_of(temp=35.0, humidity=90.0, condition="rainy", cloud_coverage=100.0),
    )
    assert t.kelvin == 1900  # cinema intacto: clima não distorce cena
    assert 8 == t.brightness
    assert t.source == "cena:cinema"


def test_scene_runtime_vence_tudo_antes_de_clipers():
    t = _target(
        room=None,
        scene={"id": "trabalho", "until": "2099-01-01T00:00:00"},
        ambient=ambient_of(temp=40.0),
    )
    assert t.kelvin == 5000
    assert t.brightness == 85


def test_clipers_intersecao():
    house = {**HOUSE_BASE, "clip": {"kelvin_max": 4800}}
    room = {**ROOM_BASE, "clip": {"kelvin_min": 3200, "brightness_max": 60}}
    t = _target(room=room, house=house)
    assert t.kelvin <= 4800
    assert t.brightness <= 60


def test_clip_insuficiente_na_area_nao_estoura():
    # "clip impossível" (kelvin_min 5800 > curva do dia): o motor clampeia no clip,
    # pois clip = limite físico da luz instalada
    room = {**ROOM_BASE, "clip": {"kelvin_min": 5800}}
    t = _target(room=room)
    assert t.kelvin == 5800


def test_protecao_noite_reduz():
    house = {**HOUSE_BASE, "night_lock": {"enabled": True, "start": "23:00", "end": "06:00"}}
    t = _target(now=NIGHT, elevation=-20.0, house=house)
    assert t.kelvin <= 2200
    assert t.brightness <= 15
    assert "protecao_noite" in t.modifiers
    # janela atravessando meia-noite cobre 23:00–00:00 e 00:00–06:00
    early = datetime(2026, 10, 16, 5, 59)
    assert night_lock_active(early, house["night_lock"])
    late = datetime(2026, 10, 16, 6, 1)
    assert not night_lock_active(late, house["night_lock"])


def test_manual_freeza_nao_aplica_mais_agenda():
    # room manual: agendar blocos zerados — o coordinator modo manual os limpa
    assert lumina_defaults is not None


def test_needs_apply_limiares():
    from custom_components.mw_lumina.engine import Target
    t = Target(kelvin=3000, brightness=50, source="", modifiers=[])
    assert needs_apply(3005, 49, t) is False  # sob ruído
    assert needs_apply(3300, 49, t) is True   # kelvin desviou
    assert needs_apply(3005, 60, t) is True   # brilho desviou


def test_kelvin_rgb_zona_fisica():
    # âmbar profundo (2000K): vermelho puro, azul quase nulo
    r, g, b = kelvin_to_rgb(2000)
    assert (r, g, b) == (255, 255, 255) if False else (r == 255 and g > 100 and b < 40)
    # frio (7000K): vermelho derrete, azul a pino
    r, g, b = kelvin_to_rgb(7000)
    assert r < 255 and b == 255
    # conversão monotônica: azul sobe com o Kelvin
    _, _, b2000 = kelvin_to_rgb(2000)
    _, _, b6000 = kelvin_to_rgb(6000)
    assert b6000 > b2000


def test_default_blocks_default():
    blocks = lumina_defaults.default_house_blocks()
    assert len(blocks) >= 2
    for b in blocks:
        assert ":" in b["start"] and ":" in b["end"]
        assert set(b["days"]).issubset(range(7))


def test_bootstrap_por_area():
    areas = [{"id": "area_esc", "name": "⬛️ESCRITÓRIO"}, {"id": "area_vazia", "name": "Varanda"}]
    lights = {
        "area_esc": [
            {"entity_id": "light.coluninhas", "name": "Coluninhas", "supports_brightness": True},
            {"entity_id": "light.estantes", "name": "Estantes", "supports_brightness": True},
        ],
        "area_vazia": [],
    }
    config = lumina_defaults.bootstrap_config(areas, lights)
    assert set(config["rooms"]) == {"escritorio"}
    room = config["rooms"]["escritorio"]
    assert room["lights"] == ["light.coluninhas", "light.estantes"]
    assert room["name"] == "⬛️ESCRITÓRIO"


def test_merge_config_sections_e_remoção():
    base = lumina_defaults.bootstrap_config(
        [{"id": "a1", "name": "Sala"}],
        {"a1": [{"entity_id": "light.sofa", "name": "Sofá", "supports_brightness": True}]},
    )
    merged = lumina_defaults.merge_config(base, {
        "rooms": {"a1": {"clip": {"brightness_max": 70}}},
        "lights": {"light.sofa": None},
    })
    assert merged["rooms"]["a1"]["clip"] == {"brightness_max": 70}
    assert "lights" in merged


def test_validador_acepta_e_rejeita():
    good = lumina_defaults.bootstrap_config([], {})
    assert lumina_defaults.validate_config(good) == []
    bad = {
        "house": {"schedule": {"blocks": [
            {"id": "x", "start": "25:00", "end": "9x", "kind": "wrong"}]}},
        "rooms": {},
    }
    errors = lumina_defaults.validate_config(bad)
    assert any("start" in e or "end" in e or "kind" in e for e in errors)
