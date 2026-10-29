"""MW Lúmina — serviços (voz, automações e a assistente Letícia)."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall
import voluptuous as vol

from .const import DOMAIN, SCENE_DEFAULT_MINUTES
from .scenes import resolve_scene

_LOGGER = logging.getLogger(__name__)

SERVICE_APPLY_SCENE = "apply_scene"
SERVICE_SET_MODE = "set_mode"
SERVICE_CLEAR_SCENE = "clear_scene"

SCHEMA_APPLY_SCENE = vol.Schema(
    {
        vol.Required("scene"): str,
        vol.Optional("room"): str,
        vol.Optional("minutes", default=SCENE_DEFAULT_MINUTES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=24 * 60)
        ),
    }
)

SCHEMA_SET_MODE = vol.Schema(
    {
        vol.Required("room"): str,
        vol.Required("mode"): vol.In(["auto", "manual"]),
    }
)

SCHEMA_CLEAR_SCENE = vol.Schema({vol.Optional("room"): str})


async def async_register_services(hass: HomeAssistant) -> None:
    """Registra os serviços usando o estado runtime do coordinator."""

    async def async_apply_scene(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN]["coordinator"]
        scene_id = call.data["scene"]
        config_scenes = hass.data[DOMAIN]["store"].config.get("scenes", {})
        if resolve_scene(scene_id, config_scenes) is None:
            _LOGGER.warning("MW Lúmina: cena desconhecida '%s'", scene_id)
            return
        minutes = int(call.data.get("minutes", SCENE_DEFAULT_MINUTES))
        coordinator.set_scene(call.data.get("room"), scene_id, minutes)
        _LOGGER.info("MW Lúmina: cena %s aplicada (%s min)", scene_id, minutes)

    async def async_set_mode(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN]["coordinator"]
        coordinator.set_mode(call.data["room"], call.data["mode"])

    async def async_clear_scene(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN]["coordinator"]
        coordinator.clear_scene(call.data.get("room"))

    hass.services.async_register(DOMAIN, SERVICE_APPLY_SCENE, async_apply_scene, SCHEMA_APPLY_SCENE)
    hass.services.async_register(DOMAIN, SERVICE_SET_MODE, async_set_mode, SCHEMA_SET_MODE)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_SCENE, async_clear_scene, SCHEMA_CLEAR_SCENE)
