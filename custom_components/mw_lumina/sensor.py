"""MW Lúmina — sensors por ambiente: o alvo circadiano de agora."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["coordinator"]
    store = hass.data[DOMAIN]["store"]
    entities = []
    for room_key in store.room_keys():
        entities.append(AlvoSensor(coordinator, room_key))
    async_add_entities(entities)


class AlvoSensor(CoordinatorEntity, SensorEntity):
    """Estado = Kelvin alvo; atributos = brilho, fonte, modificadores."""

    def __init__(self, coordinator, room_key: str) -> None:
        super().__init__(coordinator)
        self.room_key = room_key
        room = coordinator.store.get_room(room_key) or {}
        self._attr_name = f"Alvo {room.get('name', room_key)}"
        self._attr_unique_id = f"{room_key}_alvo"
        self._attr_translation_key = "alvo"
        self._attr_native_unit_of_measurement = "°K"
        self._attr_icon = "mdi:temperature-kelvin"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room_key)},
            name=f"MW Lúmina · {room.get('name', room_key)}",
            manufacturer=MANUFACTURER,
            model="MW Lúmina Ambiente",
        )

    @property
    def native_value(self) -> str | None:
        room_targets = (self.coordinator.data or {}).get("targets", {}).get(self.room_key, {})
        if not room_targets:
            return None
        first = next(iter(room_targets.values()))
        return str(first.get("kelvin"))

    @property
    def extra_state_attributes(self) -> dict:
        room_targets = (self.coordinator.data or {}).get("targets", {}).get(self.room_key, {})
        data = (self.coordinator.data or {})
        scene_active = data.get("scenes_active", {}).get(self.room_key)
        return {
            "ambientes_luzes": room_targets,
            "modo": "manual" if self.room_key in self.coordinator.room_manual else "auto",
            "cena_ativa": scene_active,
            "elevacao_sol": data.get("elevation"),
            "ambiente": data.get("ambient"),
        }
