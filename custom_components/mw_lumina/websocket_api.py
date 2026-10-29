"""MW Lúmina — API WebSocket para o painel visual.

Comandos prefixados `lumina/`. Autenticação padrão do HA WebSocket.
"""

from __future__ import annotations

import logging

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN, SCENE_DEFAULT_MINUTES
from .scenes import SCENES, resolve_scene

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/config_get",
    }
)
@websocket_api.async_response
async def ws_config_get(hass, connection, msg):
    store = hass.data[DOMAIN]["store"]
    coordinator = hass.data[DOMAIN]["coordinator"]
    connection.send_result(
        msg["id"],
        {
            "config": store.config,
            "state": coordinator.data or {},
            "predefined_scenes": {sid: {
                "name": s.name,
                "icon": s.icon,
                "kelvin": s.kelvin,
                "brightness": s.brightness,
                "description": s.description,
            } for sid, s in SCENES.items()},
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/config_save",
        vol.Required("patch"): dict,
    }
)
@websocket_api.async_response
async def ws_config_save(hass, connection, msg):
    store = hass.data[DOMAIN]["store"]
    try:
        await store.save(msg["patch"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_config", str(err))
        return
    coordinator = hass.data[DOMAIN]["coordinator"]
    await coordinator.async_refresh()
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/discover",
    }
)
@websocket_api.async_response
async def ws_discover(hass, connection, msg):
    areas_ws = [
        {"id": area.id, "name": area.name}
        for area in (hass.config.areas or {}).values()
    ]
    lights_out = []
    for st in hass.states.async_all("light"):
        attrs = st.attributes
        lights_out.append(
            {
                "entity_id": st.entity_id,
                "name": attrs.get("friendly_name", st.entity_id),
                "area_id": _area_for_entity(hass, st),
                "state": st.state,
                "supported_color_modes": attrs.get("supported_color_modes", []),
                "supports_brightness": attrs.get("supported_features", 0) > 0
                or "brightness" in attrs,
                "min_kelvin": attrs.get("min_color_temp_kelvin", 2000),
                "max_kelvin": attrs.get("max_color_temp_kelvin", 5000),
            }
        )
    connection.send_result(msg["id"], {"areas": areas_ws, "lights": lights_out})


def _area_for_entity(hass: HomeAssistant, state) -> str | None:
    """Área da luz via device registry (com fallback por entity registry)."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    entry = er.async_get(hass).async_get(state.entity_id)
    if entry:
        if entry.area_id:
            return entry.area_id
        if entry.device_id:
            device = dr.async_get(hass).async_get(entry.device_id)
            if device:
                return device.area_id
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/scene_apply",
        vol.Required("scene"): str,
        vol.Optional("room"): str,
        vol.Optional("minutes", default=SCENE_DEFAULT_MINUTES): cv.positive_int,
    }
)
@websocket_api.async_response
async def ws_scene_apply(hass, connection, msg):
    coordinator = hass.data[DOMAIN]["coordinator"]
    scene_id = msg["scene"]
    if resolve_scene(scene_id, hass.data[DOMAIN]["store"].config.get("scenes", {})) is None:
        connection.send_error(msg["id"], "invalid_scene", f"cena desconhecida: {scene_id}")
        return
    coordinator.set_scene(msg.get("room"), scene_id, msg.get("minutes", SCENE_DEFAULT_MINUTES))
    connection.send_result(msg["id"], {"applied": True, "scene": scene_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/scene_clear",
        vol.Optional("room"): str,
    }
)
@websocket_api.async_response
async def ws_scene_clear(hass, connection, msg):
    coordinator = hass.data[DOMAIN]["coordinator"]
    coordinator.clear_scene(msg.get("room"))
    connection.send_result(msg["id"], {"cleared": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/mode_set",
        vol.Required("room"): str,
        vol.Required("mode"): vol.In(["auto", "manual"]),
    }
)
@websocket_api.async_response
async def ws_mode_set(hass, connection, msg):
    coordinator = hass.data[DOMAIN]["coordinator"]
    coordinator.set_mode(msg["room"], msg["mode"])
    connection.send_result(msg["id"], {"room": msg["room"], "mode": msg["mode"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/preview",
        vol.Required("kelvin"): cv.positive_int,
        vol.Required("brightness"): cv.positive_int,
        vol.Optional("room"): str,
        vol.Optional("seconds", default=60): cv.positive_int,
    }
)
@websocket_api.async_response
async def ws_preview(hass, connection, msg):
    coordinator = hass.data[DOMAIN]["coordinator"]
    coordinator.preview(
        msg.get("room"), msg["kelvin"], msg["brightness"], msg.get("seconds", 60)
    )
    connection.send_result(msg["id"], {"previewing": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lumina/state_get",
    }
)
@websocket_api.async_response
async def ws_state_get(hass, connection, msg):
    coordinator = hass.data[DOMAIN]["coordinator"]
    connection.send_result(msg["id"], {"state": coordinator.data or {}})


def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_config_get)
    websocket_api.async_register_command(hass, ws_config_save)
    websocket_api.async_register_command(hass, ws_discover)
    websocket_api.async_register_command(hass, ws_scene_apply)
    websocket_api.async_register_command(hass, ws_scene_clear)
    websocket_api.async_register_command(hass, ws_mode_set)
    websocket_api.async_register_command(hass, ws_preview)
    websocket_api.async_register_command(hass, ws_state_get)
