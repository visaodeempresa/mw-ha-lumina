"""MW Lúmina — coordinator: o pulso da casa.

A cada ciclo calcula alvos por ambiente e aplica nas luzes Φ ON (nunca liga
luz apagada). Detecta mudanças manuais (quem mexeu não foi o Lúmina) e coloca
o ambiente em modo manual até o usuário reativar o Auto.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    COMMIT_MIN_CYCLE_SECONDS,
    DOMAIN,
    MANUAL_DEBOUNCE_CYCLES,
)
from .engine import needs_apply, resolve_target
from .solar import day_profile
from .store import LuminaStore

_LOGGER = logging.getLogger(__name__)


class LuminaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Cérebro calculado: alvos por ambiente, modos, cenas expiráveis, previsões."""

    def __init__(self, hass: HomeAssistant, store: LuminaStore, entry_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=COMMIT_MIN_CYCLE_SECONDS),
        )
        self.hass = hass
        self.store = store
        self.entry_id = entry_id

        # runtime (não persistido)
        self.room_scenes: dict[str, dict] = {}
        self.previews: dict[str, dict] = {}
        self.room_manual: set[str] = set()
        self.manual_counts: dict[str, int] = {}
        self.ours_contexts: set[str] = set()

        latitude = hass.config.latitude
        longitude = hass.config.longitude
        if latitude is None or longitude is None:
            latitude, longitude = 0.0, 0.0
        self.latitude = float(latitude)
        self.longitude = float(longitude)

    # ------------------------------------------------------------------
    # ciclo
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        config = self.store.config
        self._expire_runtime()
        self._detect_manual_rooms()

        now = dt_util.now()  # horário local do HA
        from .solar import elevation_at

        elevation = elevation_at(
            datetime.now(UTC), self.latitude, self.longitude
        )
        ambient = self._read_ambient(config)

        targets: dict[str, dict] = {}
        applies: dict[str, dict] = {}
        for room_key, room in config.get("rooms", {}).items():
            mod_config = self._mode_config(room_key, room)
            light_targets = {}
            for entity_id in room.get("lights", []):
                state = self.hass.states.get(entity_id)
                if state is None or state.state != "on":
                    continue  # não acordamos luz apagada
                # preview ativo vence tudo (janela curta de teste pelo painel)
                preview = self.previews.get(room_key)
                if preview:
                    target_resolved = type(
                        "T",
                        (),
                        {
                            "kelvin": preview["kelvin"],
                            "brightness": preview["brightness"],
                            "source": "previsão",
                            "modifiers": ["preview"],
                        },
                    )()
                    as_dict = {
                        "kelvin": target_resolved.kelvin,
                        "brightness": target_resolved.brightness,
                        "source": target_resolved.source,
                        "modifiers": target_resolved.modifiers,
                    }
                else:
                    resolved = resolve_target(
                        now_local=now,
                        elevation=elevation,
                        house_cfg=config.get("house", {}),
                        room_cfg=mod_config,
                        light_cfg=self.store.light_cfg(entity_id),
                        room_scene=self.room_scenes.get(room_key),
                        custom_scenes=config.get("scenes", {}),
                        ambient=ambient,
                    )
                    as_dict = resolved.as_dict()
                light_targets[entity_id] = as_dict
                if self._needs_service_call(state, as_dict):
                    applies[entity_id] = as_dict
            targets[room_key] = light_targets

        await self._apply(applies)
        data = {
            "now": now.isoformat(),
            "elevation": elevation,
            "ambient": ambient,
            "targets": targets,
            "rooms_manual": sorted(self.room_manual),
            "scenes_active": self.room_scenes,
            "sun_profile": self._sun_profile(),
        }
        return data

    def _mode_config(self, room_key: str, room: dict) -> dict:
        if room_key in self.room_manual:
            override = dict(room)
            override["schedule"] = {"blocks": []}  # modo manual: congelar
            return override
        return room

    def _needs_service_call(self, state, target_dict: dict) -> bool:
        current_kelvin = state.attributes.get("color_temp_kelvin")
        brightness_pct = state.attributes.get("brightness_pct")
        target = type("T", (), target_dict)()
        return needs_apply(current_kelvin, brightness_pct, target)

    async def _apply(self, applies: dict[str, dict]) -> None:
        if not applies:
            return
        for entity_id, target in applies.items():
            context = Context()
            if isinstance(context.id, str):
                self.ours_contexts.add(context.id)
            kwargs: dict[str, Any] = {
                "entity_id": entity_id,
                "brightness_pct": max(1, min(100, target["brightness"])),
            }
            state = self.hass.states.get(entity_id)
            sc = state.attributes.get("supported_color_modes", []) if state else []
            if "color_temp" in sc and state:
                kwargs["kelvin"] = max(
                    state.attributes.get("min_color_temp_kelvin", 2000),
                    min(state.attributes.get("max_color_temp_kelvin", 5000), target["kelvin"]),
                )
            kwargs["transition"] = 2.0
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    kwargs,
                    context=context,
                    blocking=False,
                )
                _LOGGER.debug(
                    "MW Lúmina: %s -> %sK %s%% (%s)",
                    entity_id, target["kelvin"], target["brightness"], target["source"],
                )
            except Exception:  # erro de dispositivo nunca derruba o ciclo
                _LOGGER.exception("MW Lúmina: falha aplicando %s", entity_id)

    # ------------------------------------------------------------------
    # modos e cenas
    # ------------------------------------------------------------------

    def set_scene(self, room_key: str | None, scene_id: str, minutes: int) -> bool:
        """Ativa a cena em um ambiente ou na casa inteira (None)."""
        until = (dt_util.now() + timedelta(minutes=minutes)).isoformat()
        for key in self._scope(room_key):
            self.room_scenes[key] = {"id": scene_id, "until": until}
            self.room_manual.discard(key)
        self._refresh()
        return True

    def clear_scene(self, room_key: str | None) -> None:
        for key in self._scope(room_key):
            self.room_scenes.pop(key, None)
        self._refresh()

    def set_mode(self, room_key: str, mode: str) -> None:
        if mode == "manual":
            self.room_manual.add(room_key)
            self.room_scenes.pop(room_key, None)
        else:
            self.room_manual.discard(room_key)
        self._refresh()

    def preview(self, room_key: str | None, kelvin: int, brightness: int, seconds: int) -> None:
        until = (dt_util.now() + timedelta(seconds=seconds)).isoformat()
        for key in self._scope(room_key):
            self.previews[key] = {"kelvin": kelvin, "brightness": brightness, "until": until}
        self._refresh()

    def _scope(self, room_key: str | None) -> list[str]:
        if room_key is None:
            return list(self.store.room_keys())
        return [room_key]

    def _expire_runtime(self) -> None:
        now = dt_util.now()
        for key in list(self.room_scenes):
            until = self.room_scenes[key].get("until")
            try:
                if isinstance(until, str) and datetime.fromisoformat(until) < now:
                    _LOGGER.info("MW Lúmina: cena expirada em %s", key)
                    self.room_scenes.pop(key)
            except ValueError:
                self.room_scenes.pop(key)
        for key in list(self.previews):
            until = self.previews[key].get("until")
            try:
                if isinstance(until, str) and datetime.fromisoformat(until) < now:
                    self.previews.pop(key)
            except ValueError:
                self.previews.pop(key)

    # ------------------------------------------------------------------
    # detecção de modo manual
    # ------------------------------------------------------------------

    def _detect_manual_rooms(self) -> None:
        config = self.store.config
        for room_key, room in config.get("rooms", {}).items():
            if room_key in self.room_manual:
                continue
            divergent_any = False
            for entity_id in room.get("lights", []):
                state = self.hass.states.get(entity_id)
                if state is None or state.state != "on":
                    continue
                if state.context and state.context.id in self.ours_contexts:
                    continue  # nossa mudança esperada
                divergent_any = True
            if divergent_any:
                self.manual_counts[room_key] = self.manual_counts.get(room_key, 0) + 1
                if self.manual_counts.get(room_key, 0) >= MANUAL_DEBOUNCE_CYCLES:
                    _LOGGER.info("MW Lúmina: %s entrou em modo manual", room_key)
                    self.room_manual.add(room_key)
                    self.manual_counts[room_key] = 0

    # ------------------------------------------------------------------
    # ambiente
    # ------------------------------------------------------------------

    def _read_ambient(self, config: dict) -> dict[str, Any]:
        ambient_cfg = (config.get("house") or {}).get("ambient", {})
        ambient: dict[str, Any] = {
            "temp": None,
            "humidity": None,
            "condition": None,
            "cloud_coverage": None,
        }
        temp_id = ambient_cfg.get("temp_sensor")
        hum_id = ambient_cfg.get("humidity_sensor")
        weather_id = ambient_cfg.get("weather_entity")
        if temp_id:
            st = self.hass.states.get(temp_id)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    ambient["temp"] = float(st.state)
                except ValueError:
                    pass
        if hum_id:
            st = self.hass.states.get(hum_id)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    ambient["humidity"] = float(st.state)
                except ValueError:
                    pass
        if weather_id:
            st = self.hass.states.get(weather_id)
            if st and st.state not in ("unavailable", "unknown"):
                ambient["condition"] = st.state
                cloud = st.attributes.get("cloud_coverage")
                if cloud is not None:
                    try:
                        ambient["cloud_coverage"] = float(cloud)
                    except (TypeError, ValueError):
                        pass
        return ambient

    # ------------------------------------------------------------------
    # utilidades p/ painel
    # ------------------------------------------------------------------

    def _sun_profile(self) -> list[dict]:
        from datetime import datetime as dt2

        return day_profile(dt2.now(UTC), self.latitude, self.longitude, step_minutes=20)

    def snapshot(self) -> dict[str, Any]:
        return self.data or {}

    def _refresh(self) -> None:
        self.hass.async_create_task(self.async_request_refresh())
