"""MW Lúmina — constantes compartilhadas.

Lúmina: a luz que se adapta a você. Núcleo circadiano determinístico,
100% offline (nenhuma chamada externa para calcular alvos de luz).
"""

from __future__ import annotations

DOMAIN = "mw_lumina"
DOMAIN_FRIENDLY = "MW Lúmina"
MANUFACTURER = "Visão de Empresa"

# Painel (registrado em __init__.py)
PANEL_URL = "lumina"
PANEL_STATIC_PATH = "/lumina-panel"
PANEL_TITLE = "MW Lúmina"
PANEL_ICON = "mdi:lightbulb-auto"

# Agendador
COMMIT_MIN_CYCLE_SECONDS = 20.0
DELTA_KELVIN_TOLERANCE = 30.0  # °K mínimos para mexer numa luz
DELTA_BRIGHTNESS_TOLERANCE = 2.0  # % mínimos para mexer numa luz
MANUAL_DEBOUNCE_CYCLES = 2  # ciclos seguidos divergentes -> modo manual
PREVIEW_DEFAULT_SECONDS = 60
SCENE_DEFAULT_MINUTES = 90

# Ambiente (sensores opcionais)
KELVIN_THERMAL_MAX = 400.0
KELVIN_THERMAL_STEP = 25.0
HUMIDITY_WARM_THRESHOLD = 70.0
CLOUD_DIM_FACTOR = 0.18
WEATHER_WARM_STATES = frozenset(
    {"rainy", "pouring", "snowy", "snowy-rainy", "hail", "lightning", "fog", "windy-variant"}
)
WEATHER_COOL_STATES = frozenset({"sunny", "clear-night"})

# Sleeptime (proteção noturna, pós-cena/post-bloco)
NIGHT_LOCK_MAX_KELVIN = 2200.0
NIGHT_LOCK_MAX_BRIGHTNESS = 15.0

# limites físicos
KELVIN_MIN = 1500
KELVIN_MAX = 6500
BRIGHTNESS_MIN = 1
