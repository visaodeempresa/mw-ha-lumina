"""MW Lúmina — entidades select: modo Auto/Manual por ambiente."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]
    store = hass.data[DOMAIN]["store"]
    entities = []
    for room_key in store.room_keys():
        entities.append(ModoSelect(coordinator, room_key))
    async_add_entities(entities)


class ModoSelect(CoordinatorEntity, SelectEntity):
    """Auto = Lúmina organiza; Manual = Lúmina não mexe."""

    def __init__(self, coordinator, room_key: str) -> None:
        super().__init__(coordinator)
        self.room_key = room_key
        room = coordinator.store.get_room(room_key) or {}
        self._attr_name = f"Modo {room.get('name', room_key)}"
        self._attr_unique_id = f"{room_key}_modo"
        self._attr_translation_key = "modo"
        self._attr_options = ["auto", "manual"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room_key)},
            name=f"MW Lúmina · {room.get('name', room_key)}",
            manufacturer=MANUFACTURER,
            model="MW Lúmina Ambiente",
        )

    @property
    def current_option(self):
        manual = self.room_key in self.coordinator.room_manual
        return "manual" if manual else "auto"

    async def async_select_option(self, option: str):
        self.coordinator.set_mode(self.room_key, option)

    @callback
    def _handle_coordinator_update(self):
        super()._handle_coordinator_update()
        self.async_write_ha_state()
