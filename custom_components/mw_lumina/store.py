"""MW Lúmina — Store de configuração (fonte única de verdade).

O painel visual é a principal forma de configurar: o Store guarda a estrutura
(casa → ambientes → luzes → cenas) persistida via HA Store .storage.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import lumina_defaults
from .const import DOMAIN
from .engine import clip_for, resolve_target  # noqa: F401  (re-export p/ painel de testes)
from .lumina_defaults import bootstrap_config, validate_config

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


class LuminaStore:
    """Contêiner da config persistida + acesso convencional em runtime."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_config")
        self._config: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        data = await self._store.async_load()
        self._config = data or {}
        return self._config

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    async def save(self, patch: dict | None = None) -> None:
        if patch is not None:
            self._config = lumina_defaults.merge_config(self._config, patch)
        errors = validate_config(self._config)
        if errors:
            raise ValueError(f"config inválida: {'; '.join(errors)}")
        await self._store.async_save(self._config)
        _LOGGER.info("MW Lúmina: config persistida (ver=%s)", self._config.get("version"))

    async def replace(self, config: dict) -> None:
        errors = validate_config(config)
        if errors:
            raise ValueError(f"config inválida: {'; '.join(errors)}")
        self._config = config
        await self._store.async_save(config)

    # ------------------------------------------------------------------
    # bootstrap de descoberta (chamado apenas quando não há config)
    # ------------------------------------------------------------------

    async def async_bootstrap(self) -> None:
        """Descobre áreas + luzes e cria o config inicial se estiver vazio."""
        if self._config.get("rooms"):
            return

        # áreas via config registry (API interna, sem rede)
        areas = [
            {"id": area.id, "name": area.name}
            for area in (self.hass.config.areas or {}).values()
        ]
        light_states = {
            state.entity_id: state
            for state in self.hass.states.async_all("light")
        }

        def light_meta(entity_id: str) -> dict:
            state = light_states.get(entity_id)
            attributes = state.attributes if state else {}
            color_modes = attributes.get("supported_color_modes") or []
            return {
                "entity_id": entity_id,
                "name": attributes.get("friendly_name", entity_id),
                "supports_brightness": attributes.get("supported_features", 0) > 0
                or "brightness" in attributes,
                "supports_color_temp": "color_temp" in color_modes
                or attributes.get("color_temp_kelvin") is not None,
                "supports_rgb": bool({"rgb", "rgbw", "rgbww", "hs", "xy"} & set(color_modes))
                or attributes.get("rgb_color") is not None,
                "min_kelvin": attributes.get("min_color_temp_kelvin", 2000),
                "max_kelvin": attributes.get("max_color_temp_kelvin", 5000),
            }

        lights_by_area: dict[str, list[dict]] = {}
        registry_lights: list[str] = []
        for entity_id in light_states:
            (
                self.hass.states.async_get(entity_id).attributes
                .get("device_id")
            ) if self.hass.states.async_get(entity_id) else None
            registry_lights.append(entity_id)

        # para agregar por área usamos o device/area dos estados (device_id)
        # fallback: agrupar heurístico por prefixo (escritorio_*, sala_*)
        for entity_id in registry_lights:
            area_id = self._area_for_light(entity_id)
            if area_id is None:
                continue
            lights_by_area.setdefault(area_id, []).append(light_meta(entity_id))

        self._config = bootstrap_config(areas, lights_by_area)
        await self._store.async_save(self._config)
        _LOGGER.info(
            "MW Lúmina: bootstrap com %s ambientes", len(self._config.get("rooms", {}))
        )

    def _area_for_light(self, entity_id: str) -> str | None:
        """Resolve área da luz via device registry; None se área desconhecida."""
        device_registry = None
        try:
            from homeassistant.helpers import device_registry as dr

            device_registry = dr.async_get(self.hass)
        except ImportError:
            return None

        state = self.hass.states.async_get(entity_id)
        if state is None:
            return None
        device_ids = state.attributes.get("device_id")
        # alguns estados trinketam device_id fora do attributes — fallback via registry
        if not device_ids:
            try:
                from homeassistant.helpers import entity_registry as er

                entry = er.async_get(self.hass).async_get(entity_id)
                if entry:
                    device_ids = entry.device_id
            except ImportError:
                device_ids = None
        if not device_ids:
            return None
        device_id = device_ids if isinstance(device_ids, str) else device_ids[0]
        device = device_registry.async_get(device_id)
        if device is None:
            return None
        return device.area_id

    # ------------------------------------------------------------------

    def get_room(self, room_key: str) -> dict | None:
        return self._config.get("rooms", {}).get(room_key)

    def get_house(self) -> dict:
        return self._config.get("house", {})

    def light_cfg(self, entity_id: str) -> dict | None:
        return self._config.get("lights", {}).get(entity_id)

    def room_keys(self) -> list[str]:
        return list(self._config.get("rooms", {}))

    def all_lights(self) -> list[str]:
        out: list[str] = []
        for room in self._config.get("rooms", {}).values():
            out.extend(room.get("lights", []))
        out.extend(self._config.get("lights", {}))
        return sorted(set(out))
