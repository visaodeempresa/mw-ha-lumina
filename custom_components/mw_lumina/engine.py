"""MW Lúmina — motor circadiano determinístico (Fase 1, módulo puro).

Cadeia de decisão por luz (menor → maior prioridade):

  circadiano (curva solar) → bloco de horário → cena/respiro ativo → clipes.

Efeitos ambientais (temperatura, umidade, clima) modulam a curva circadiana
e os blocos do tipo `circadian`, mas nunca distorcem uma cena explícita.
Nada aqui depende de rede: o cálculo é local, então a integração funciona
100% offline.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .const import (
    BRIGHTNESS_MIN,
    CLOUD_DIM_FACTOR,
    DELTA_BRIGHTNESS_TOLERANCE,
    DELTA_KELVIN_TOLERANCE,
    HUMIDITY_WARM_THRESHOLD,
    KELVIN_MAX,
    KELVIN_MIN,
    KELVIN_THERMAL_MAX,
    KELVIN_THERMAL_STEP,
    NIGHT_LOCK_MAX_BRIGHTNESS,
    NIGHT_LOCK_MAX_KELVIN,
    WEATHER_COOL_STATES,
    WEATHER_WARM_STATES,
)
from .scenes import resolve_scene

# Curva circadiana: (elevação °, kelvin, fator de brilho 0..1)
# baseada em melanopsina (480 nm): noite ≤ 1800K e sub-baixa, manhã escalonando
# para o branquinho do meio-dia, crepúsculo derivando para âmbar.
CURVE: list[tuple[float, float, float]] = [
    (-90.0, 1700.0, 0.08),
    (-18.0, 1750.0, 0.10),
    (-12.0, 1850.0, 0.14),
    (-6.0, 2050.0, 0.22),
    (-3.0, 2250.0, 0.34),
    (0.0, 2500.0, 0.48),
    (4.0, 2900.0, 0.70),
    (10.0, 3400.0, 0.85),
    (20.0, 4200.0, 0.93),
    (40.0, 5000.0, 0.97),
    (90.0, 5600.0, 1.00),
]

DAYSTART = 0  # segunda-feira (weekday do datetime.isoweekday - 1)


@dataclass(slots=True)
class Target:
    """Alvo resolvido para uma luz ou conjunto de luzes."""

    kelvin: int
    brightness: int  # percentual 1..100
    source: str      # "circadiano" | "bloco:<id>" | "cena:<id>" | "previsão"
    modifiers: list[str]

    def as_dict(self) -> dict:
        return {
            "kelvin": self.kelvin,
            "brightness": self.brightness,
            "source": self.source,
            "modifiers": self.modifiers,
        }


def curve_at(elevation: float) -> tuple[float, float]:
    """Interpolação linear por elevação na CURVE."""
    elevs = [p[0] for p in CURVE]
    if elevation <= elevs[0]:
        return CURVE[0][1], CURVE[0][2]
    if elevation >= elevs[-1]:
        return CURVE[-1][1], CURVE[-1][2]
    for i in range(1, len(CURVE)):
        if elevation <= CURVE[i][0]:
            x0, k0, b0 = CURVE[i - 1]
            x1, k1, b1 = CURVE[i]
            f = (elevation - x0) / (x1 - x0)
            return (
                k0 + (k1 - k0) * f,
                b0 + (b1 - b0) * f,
            )
    return CURVE[-1][1], CURVE[-1][2]


def kelvin_to_rgb(kelvin: float) -> tuple[int, int, int]:
    """Conversão Kelvin→RGB (aproximação de corpo negro — Tanner Helland)."""
    t = max(1000.0, min(40000.0, kelvin)) / 100.0

    def clamp(x: float) -> int:
        return max(0, min(255, round(x)))

    if t <= 66:
        red = 255
        green = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        red = 329.698727446 * ((t - 60) ** -0.1332047592)
        green = 288.1221695283 * ((t - 60) ** -0.0755148492)

    if t >= 66:
        blue = 255
    elif t <= 19:
        blue = 0
    else:
        blue = 138.5177312231 * math.log(t - 10) - 305.0447927307

    return clamp(red), clamp(green), clamp(blue)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def tcp_shift(temp_c: float | None) -> float:
    """Modulação térmica (°K). Calor → mais fresco; frio → mais quente/acolhedor."""
    if temp_c is None:
        return 0.0
    return max(-350.0, min(KELVIN_THERMAL_MAX, (temp_c - 22.0) * KELVIN_THERMAL_STEP))


def humidity_shift(humidity: float | None) -> float:
    """Alta umidade → luz mais morna (ar mais pesado pede luz mais amena)."""
    if humidity is None or humidity <= HUMIDITY_WARM_THRESHOLD:
        return 0.0
    return -min((humidity - HUMIDITY_WARM_THRESHOLD) * 5.0, 150.0)


def weather_shifts(
    condition: str | None, cloud_coverage: float | None
) -> tuple[float, float]:
    """Retorna (shift_kelvin, factor_brightness) para o clima atual."""
    kelvin = 0.0
    factor = 1.0
    if cloud_coverage is not None:
        clouds = max(0.0, min(100.0, cloud_coverage))
        factor *= 1.0 - CLOUD_DIM_FACTOR * (clouds / 100.0)
    if condition in WEATHER_WARM_STATES:
        kelvin -= 150.0  # chuva/neblina pede aconchego
    elif condition in WEATHER_COOL_STATES:
        kelvin += 40.0  # céu aberto, siga claro
    return kelvin, factor


def night_lock_active(
    now_local, lock: dict | None
) -> bool:
    """Janela de proteção noturna (`{"enabled", "start", "end"}`), suporta virada."""
    if not lock or not lock.get("enabled"):
        return False
    start = str(lock.get("start", "23:45"))
    end = str(lock.get("end", "06:00"))
    hhmm = now_local.strftime("%H:%M")
    if start <= end:
        return start <= hhmm < end
    return hhmm >= start or hhmm < end  # janela atravessando a meia-noite


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        h, m = value.split(":")
        return int(h) % 24, int(m) % 60
    except (ValueError, AttributeError):
        return (0, 0)


def block_matches(block: dict, now_local) -> bool:
    """Bloco: `{"days": [0..6], "start": "HH:MM", "end": "HH:MM"}`.

    Blocos com `end <= start` atravessam a meia-noite: o dia válido é o do `start`.
    """
    days = block.get("days")
    if days and now_local.weekday() not in days:
        # blocos noturnos (end <= start) também atendem o dia anterior
        if not (parse_hhmm(block.get("start", "")) >= parse_hhmm(block.get("end", ""))):
            return False
        from datetime import timedelta

        if (now_local - timedelta(days=1)).weekday() not in days:
            return False
    now_min = now_local.hour * 60 + now_local.minute
    start = parse_hhmm(block.get("start", "00:00"))
    end = parse_hhmm(block.get("end", "23:59"))
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]
    if s <= e:
        return s <= now_min < e
    return now_min >= s or now_min < e  # atravessa a meia-noite


def longest_block_wins(blocks: list[dict], now_local) -> dict | None:
    """Em sobreposição de blocos, vence o mais longo (mais intencional)."""
    matches = [b for b in blocks if block_matches(b, now_local)]
    if not matches:
        return None
    return max(matches, key=lambda b: _block_span_minutes(b))


def _block_span_minutes(block: dict) -> int:
    s = parse_hhmm(block.get("start", "00:00"))
    e = parse_hhmm(block.get("end", "23:59"))
    span = (e[0] * 60 + e[1]) - (s[0] * 60 + s[1])
    if span <= 0:
        span += 24 * 60
    return span


def schedule_for(level_cfg: dict) -> list[dict]:
    return (level_cfg or {}).get("schedule", {}).get("blocks", []) or []


def clip_for(
    house_cfg: dict, room_cfg: dict, light_cfg: dict | None
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Interseta clipes: faixa de Kelvin + teto de brilho (casa ⊗ ambiente ⊗ luz)."""
    k_lo, k_hi = KELVIN_MIN, KELVIN_MAX
    b_hi = 100.0
    for cfg in (house_cfg, room_cfg, light_cfg):
        clip = (cfg or {}).get("clip", {})
        k_lo = max(k_lo, float(clip.get("kelvin_min", KELVIN_MIN)))
        k_hi = min(k_hi, float(clip.get("kelvin_max", KELVIN_MAX)))
        b_hi = min(b_hi, float(clip.get("brightness_max", 100.0)))
    if k_lo > k_hi:
        k_lo = k_hi
    return (k_lo, k_hi), (BRIGHTNESS_MIN, b_hi)


def resolve_target(
    *,
    now_local,
    elevation: float,
    house_cfg: dict,
    room_cfg: dict,
    light_cfg: dict | None,
    room_scene: dict | None,
    custom_scenes: dict[str, dict] | None,
    ambient: dict | None = None,
) -> Target:
    """Resolve o alvo final de Kelvin + brilho (%) para uma luz do ambiente.

    `room_scene` = {"id", "until"} se houver cena ativa (with expiração).
    `ambient` = {"temp": float|None, "humidity": float|None,
                 "condition": str|None, "cloud_coverage": float|None}.
    """
    ambient = ambient or {}
    modifiers: list[str] = []

    # 1) Cena ativa tem a palavra final antes dos clipes
    if room_scene and room_scene.get("until"):
        scene = resolve_scene(room_scene["id"], custom_scenes or {})
        if scene:
            target = Target(
                kelvin=scene.kelvin,
                brightness=scene.brightness,
                source=f"cena:{scene.id}",
                modifiers=[],
            )
            return _finalize(target, house_cfg, room_cfg, light_cfg, now_local, modifiers)
        # cena desconhecida: segue o fluxo normal

    # 2) Bloco de horário: mais longe-reach primeiro na hierarquia luz→ambiente→casa
    block = None
    for cfg in (light_cfg, room_cfg, house_cfg):
        block = longest_block_wins(schedule_for(cfg), now_local)
        if block:
            # marca o nível onde o bloco veio (luz tem prioridade)
            block = dict(block)
            break

    # 3) Decisão base
    if block and block.get("kind") == "scene":
        scene = resolve_scene(block.get("scene", ""), custom_scenes or {})
        if scene:
            modifiers.append(f"bloco:{block.get('id', 's/n')}")
            target = Target(
                kelvin=scene.kelvin,
                brightness=scene.brightness,
                source=f"cena:{scene.id}",
                modifiers=modifiers,
            )
            return _finalize(target, house_cfg, room_cfg, light_cfg, now_local, modifiers)
        block = None  # cena inexistente: deixa circadiano cuidar

    if block and block.get("kind") == "fixed":
        target = Target(
            kelvin=float(block.get("kelvin", 2700)),
            brightness=float(block.get("brightness", 50)),
            source=f"bloco:{block.get('id', 's/n')}",
            modifiers=modifiers,
        )
        return _finalize(target, house_cfg, room_cfg, light_cfg, now_local, modifiers)

    # 4) Circadiano (curva solar + modulações ambientais + shifts do bloco)
    base_kelvin, base_factor = curve_at(elevation)
    kelvin = base_kelvin
    factor = base_factor

    temp = ambient.get("temp")
    hum = ambient.get("humidity")
    condition = ambient.get("condition")
    cloud = ambient.get("cloud_coverage")

    shift = tcp_shift(temp)
    if shift != 0.0:
        kelvin += shift
        modifiers.append(
            "clima_quente" if shift < 0 else "clima_frio"
        )
    h_shift = humidity_shift(hum)
    if h_shift != 0.0:
        kelvin += h_shift
        modifiers.append("umidade")
    w_kelvin, w_factor = weather_shifts(condition, cloud)
    if w_kelvin != 0.0:
        kelvin += w_kelvin
        modifiers.append("condicao")
    factor *= w_factor
    if cloud is not None:
        modifiers.append("nuvens")

    if block and block.get("kind") == "circadian":
        kelvin += float(block.get("kelvin_shift", 0.0))
        factor *= float(block.get("brightness_mult", 1.0))
        modifiers.append(f"bloco:{block.get('id', 's/n')}")

    target = Target(
        kelvin=kelvin,
        brightness=factor * 100.0,
        source=(
            f"bloco:{block.get('id', 's/n')}"
            if (block and block.get("kind") == "circadian")
            else "circadiano"
        ),
        modifiers=modifiers,
    )
    return _finalize(target, house_cfg, room_cfg, light_cfg, now_local, modifiers)


def _finalize(
    target: Target,
    house_cfg: dict,
    room_cfg: dict,
    light_cfg: dict | None,
    now_local,
    modifiers: list[str],
) -> Target:
    (k_lo, k_hi), (b_lo, b_hi) = clip_for(house_cfg, room_cfg, light_cfg)
    kelvin = max(k_lo, min(k_hi, target.kelvin))
    brightness = max(b_lo, min(b_hi, target.brightness))

    # 5) Proteção noturna vem por último (reduz até cena ativa, se o dono quiser)
    lock = house_cfg.get("night_lock")
    if night_lock_active(now_local, lock):
        kelvin = min(kelvin, NIGHT_LOCK_MAX_KELVIN)
        brightness = min(brightness, NIGHT_LOCK_MAX_BRIGHTNESS)
        modifiers.append("protecao_noite")

    return Target(
        kelvin=round(kelvin),
        brightness=round(brightness),
        source=target.source,
        modifiers=modifiers,
    )


def needs_apply(
    current_kelvin: float | None,
    current_brightness: float | None,
    target: Target,
) -> bool:
    """Prioriza Repelir: só toca na luz quando o desvio é perceptível."""
    if current_kelvin is None or current_brightness is None:
        return True
    if abs(current_kelvin - target.kelvin) >= DELTA_KELVIN_TOLERANCE:
        return True
    if abs(current_brightness - target.brightness) >= DELTA_BRIGHTNESS_TOLERANCE:
        return True
    return False
