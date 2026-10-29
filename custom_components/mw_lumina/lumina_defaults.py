"""MW Lúmina — padrões de fábrica e utilidades de config (módulo puro).

Tudo que暧 constrói a configuração inicial (descoberta por áreas do HA, blocos
de horário default, validação de mutações) vive aquí para ser testável sem HA.
"""

from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

DEFAULT_HOUSE = {
    "name": "Minha Casa",
    "schedule": {"blocks": []},
    "clip": {},
    "night_lock": {
        "enabled": True,
        "start": "23:45",
        "end": "06:00",
    },
    "ambient": {
        "temp_sensor": None,
        "humidity_sensor": None,
        "weather_entity": None,
    },
}

# ---------------------------------------------------------------------------
# blocos default de horário
# ---------------------------------------------------------------------------


def default_house_blocks() -> list[dict]:
    """Blocos default em nível de casa: ritmo de noite de trabalho e fim de semana."""
    return [
        {
            "id": "noite_descendo",
            "name": "Noite descendo (dom sex)",
            "days": [4, 0, 1, 2, 3],
            "start": "22:00",
            "end": "00:30",
            "kind": "circadian",
            "kelvin_shift": -250,
            "brightness_mult": 0.55,
        },
        {
            "id": "noite_descendo_fds",
            "name": "Noite descendo (sáb/dom)",
            "days": [5, 6],
            "start": "22:00",
            "end": "01:30",
            "kind": "circadian",
            "kelvin_shift": -250,
            "brightness_mult": 0.70,
        },
        {
            "id": "manha_cedo",
            "name": "Manhã cedo (corredor)",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "start": "05:30",
            "end": "07:30",
            "kind": "circadian",
            "kelvin_shift": 150,
            "brightness_mult": 0.80,
        },
    ]


def default_scene_schedule(scene_id: str, days: list[int], start: str, end: str) -> dict:
    """Helper para blocos que fixam uma cena (ex.: cinema fim de semana)."""
    return {
        "id": f"bloco_{scene_id}",
        "name": f"Cena {scene_id}",
        "days": days,
        "start": start,
        "end": end,
        "kind": "scene",
        "scene": scene_id,
    }


def slugify_room_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or f"ambiente_{abs(hash(name.lower())) % 99999}"


# ---------------------------------------------------------------------------
# bootstrap de descoberta
# ---------------------------------------------------------------------------


def bootstrap_config(areas: list[dict], lights_by_area: dict[str, list[dict]]) -> dict:
    """Gera o config patrão a partir das áreas + luzes descobertas no HA.

    areas: [{"id", "name"}]; lights_by_area: {area_id: [{entity_id, name,
    supports_color_temp, min_kelvin, max_kelvin, supports_brightness}]}.
    """
    config = {
        "version": 1,
        "house": deepcopy(DEFAULT_HOUSE),
        "rooms": {},
        "lights": {},
        "scenes": {},
    }
    config["house"]["schedule"]["blocks"] = default_house_blocks()

    for area in areas:
        area_id, area_name = area["id"], area.get("name") or area["id"]
        lights = lights_by_area.get(area_id, [])
        dimmable = [
            meta for meta in lights if meta.get("supports_brightness", True)
        ]
        if not dimmable:
            continue
        room_key = slugify_room_key(area_name)
        config["rooms"][room_key] = {
            "name": area_name,
            "area_id": area_id,
            "lights": [meta["entity_id"] for meta in dimmable],
            "kind": "inherit",
            "schedule": {"blocks": []},
            "clip": {},
        }

    return config


def validate_config(config: dict) -> list[str]:
    """Sanity-check das mutações vindo do painel/serviços. Retorna erros."""
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["config não é um objeto"]
    house = config.get("house")
    if not isinstance(house, dict):
        errors.append("house ausente")
        house = {}
    for key, value in (
        ("night_lock", dict), ("ambient", dict), ("schedule", dict), ("clip", dict)
    ):
        section = house.get(key)
        if section is not None and not isinstance(section, value):
            errors.append(f"house.{key} deve ser objeto")

    rooms = config.get("rooms")
    if rooms is not None and not isinstance(rooms, dict):
        errors.append("rooms deve ser objeto")
    else:
        for room_key, room in (rooms or {}).items():
            if not isinstance(room, dict):
                errors.append(f"rooms[{room_key}] deve ser objeto")
                continue
            lights = room.get("lights")
            if lights is not None and not isinstance(lights, list):
                errors.append(f"rooms[{room_key}].lights deve ser lista")

    lights = config.get("lights")
    if lights is not None and not isinstance(lights, dict):
        errors.append("lights deve ser objeto")

    blocks = (house.get("schedule", {}) or {}).get("blocks", [])
    if blocks and isinstance(blocks, list):
        for i, block in enumerate(blocks):
            if not isinstance(block, dict):
                errors.append(f"block[{i}] deve ser objeto")
                continue
            kind = block.get("kind", "circadian")
            if kind not in ("circadian", "fixed", "scene"):
                errors.append(f"block[{i}].kind inválido: {kind}")
            hhmm = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
            if not hhmm.match(str(block.get("start", ""))):
                errors.append(f"block[{i}].start inválido (HH:MM)")
            if not hhmm.match(str(block.get("end", ""))):
                errors.append(f"block[{i}].end inválido (HH:MM)")
            days = block.get("days", [])
            if days and (not isinstance(days, list) or any(d not in range(7) for d in days)):
                errors.append(f"block[{i}].days inválido")
    return errors


def merge_config(current: dict, patch: dict) -> dict:
    """Aplica patch por seção (house/rooms/lights/scenes) preservando chaves novas."""
    result = deepcopy(current)
    for section in ("house", "rooms", "lights", "scenes"):
        if section not in patch:
            continue
        patch_section = patch[section]
        if not isinstance(patch_section, dict):
            continue
        if section == "house" and not isinstance(result.get(section), dict):
            result[section] = deepcopy(DEFAULT_HOUSE)
        target = result.setdefault(section, {})
        if section == "house":
            for sub, value in patch_section.items():
                if isinstance(value, dict) and isinstance(target.get(sub), dict):
                    target[sub].update(value)
                else:
                    target[sub] = deepcopy(value)
        else:
            for key, value in patch_section.items():
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = deepcopy(value)
    return result
