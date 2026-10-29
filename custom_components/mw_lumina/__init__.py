"""MW Lúmina — ponto de entrada da integração no Home Assistant.

Fases: 1 = circadiano + ambientes + cenas + painel. A fase 2 (IA/câmera)
mantém contratos prontos aqui, mas permanece desligada até a próxima entrega.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import websocket_api as lumina_ws
from .const import (
    DOMAIN,
    PANEL_ICON,
    PANEL_STATIC_PATH,
    PANEL_TITLE,
    PANEL_URL,
)
from .coordinator import LuminaCoordinator
from .services import async_register_services
from .store import LuminaStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "select"]


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Setup do componente: nada além de registrar constantes."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        store = LuminaStore(hass)
        await store.async_load()
        if not store.config.get("rooms"):
            await store.async_bootstrap()

        coordinator = LuminaCoordinator(hass, store, entry.entry_id)
        await coordinator.async_config_entry_first_refresh()

        hass.data[DOMAIN] = {
            "store": store,
            "coordinator": coordinator,
            "entry_id": entry.entry_id,
        }

        # API WebSocket do painel + serviços
        lumina_ws.async_register(hass)
        await async_register_services(hass)

        # Painel visual (página estática + sidebar)
        await _register_panel(hass)

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        _LOGGER.info("MW Lúmina: pronta com %s ambientes", len(store.room_keys()))
        return True
    except ConfigEntryNotReady:
        raise
    except Exception:
        _LOGGER.exception("MW Lúmina: falha no setup")
        return False


async def _register_panel(hass: HomeAssistant) -> None:
    import os

    panel_dir = os.path.join(os.path.dirname(__file__), "panel")
    hass.http.register_static_path(
        PANEL_STATIC_PATH, panel_dir, cache_headers=False
    )
    await hass.frontend.async_register_built_in_panel(
        component_name="custom",
        frontend_url_path=PANEL_URL,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=True,
        config={
            "_panel_custom": {
                "name": "lumina-panel",
                "embed_iframe": True,
                "url": f"{PANEL_STATIC_PATH}/index.html",
                "trust_external": False,
            }
        },
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    try:
        hass.frontend.async_unregister_built_in_panel(PANEL_URL)
    except (AttributeError, KeyError):
        pass
    if unload_ok:
        hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
