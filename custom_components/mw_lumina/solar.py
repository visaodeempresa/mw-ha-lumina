"""Cálculo astronômico solar de baixo custo — puramente local (offline).

Posição do Sol via Astronomical Almanac low-precision (erro < 0.3 graus),
suficiente para determinação de Kelvin/brilho circadiano.
"""

from __future__ import annotations

from datetime import UTC, datetime
import math


def _julian_day(dt_utc: datetime) -> float:
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def solar_position(
    dt_utc: datetime,
    latitude: float,
    longitude: float,
) -> dict[str, float]:
    """Elevação e azimute do Sol, em graus, para um instante UTC.

    `dt_utc`: datetime consciente de fuso (será normalizado para UTC).
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    n = _julian_day(dt_utc.astimezone(UTC)) - 2451545.0

    # geometria orbital
    l_geo = (280.460 + 0.9856474 * n) % 360.0
    g = (357.528 + 0.9856003 * n) % 360.0
    lam = l_geo + 1.915 * math.sin(math.radians(g)) + 0.020 * math.sin(
        math.radians(2 * g)
    )
    eps = 23.439 - 0.0000004 * n

    lam_r = math.radians(lam)
    eps_r = math.radians(eps)
    decl = math.degrees(math.asin(math.sin(eps_r) * math.sin(lam_r)))
    right_asc = math.degrees(
        math.atan2(math.cos(eps_r) * math.sin(lam_r), math.cos(lam_r))
    ) % 360.0

    # tempo sideral local e ângulo horário
    gmst = (18.697374558 + 24.06570982441908 * n) % 24.0
    ha = (gmst * 15.0 + longitude - right_asc + 540.0) % 360.0 - 180.0

    lat_r = math.radians(latitude)
    decl_r = math.radians(decl)
    ha_r = math.radians(ha)
    sin_alt = (
        math.sin(lat_r) * math.sin(decl_r) + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    )
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    azimuth = math.degrees(
        math.atan2(
            -math.sin(ha_r),
            (math.tan(lat_r) * math.cos(decl_r) - math.sin(decl_r) * math.cos(ha_r)),
        )
    ) % 360.0
    return {"elevation": round(elevation, 2), "azimuth": round(azimuth, 2)}


def elevation_at(
    dt_utc: datetime,
    latitude: float,
    longitude: float,
) -> float:
    """Convenience: apenas a elevação em graus."""
    return solar_position(dt_utc, latitude, longitude)["elevation"]


def day_profile(
    dt_utc: datetime,
    latitude: float,
    longitude: float,
    step_minutes: int = 20,
) -> list[dict]:
    """Perfil de elevação a cada `step_minutes` para 24 h a partir de `dt_utc`.

    Usado para desenhar a curva do painel e informar eventos próximos.
    """
    base = dt_utc.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    samples: list[dict] = []
    for i in range(0, int(24 * 60 / step_minutes) + 1):
        t = base + _timedelta(minutes=i * step_minutes)
        pos = solar_position(t, latitude, longitude)
        samples.append(
            {
                "iso": t.astimezone(dt_utc.tzinfo).isoformat(),
                "elevation": pos["elevation"],
                "azimuth": pos["azimuth"],
            }
        )
    return samples


def _timedelta(**kwargs):
    from datetime import timedelta

    return timedelta(**kwargs)


def solar_events_today(
    dt_utc: datetime,
    latitude: float,
    longitude: float,
) -> dict[str, str | None]:
    """Marcadores aproximados do dia local: nascer/pôr (~0°), crepúsculo (-6°), meio-dia.

    A janela cobre 24 h centrada no meio-dia local, então os eventos do dia de
    referência cabem dentro dela.
    """
    local_day_start = (dt_utc - _timedelta(hours=12)).astimezone(UTC)
    profile = day_profile(local_day_start, latitude, longitude, step_minutes=5)
    times = [datetime.fromisoformat(p["iso"]) for p in profile]
    elevs = [p["elevation"] for p in profile]

    def crossing(level: float, rising: bool) -> str | None:
        sign = 1.0 if rising else -1.0
        for i in range(1, len(elevs)):
            a, b = elevs[i - 1] - level, elevs[i] - level
            if a * b < 0 and sign * (b - a) > 0:
                frac = (level - elevs[i - 1]) / (elevs[i] - elevs[i - 1])
                span = (times[i] - times[i - 1]).total_seconds()
                t = times[i - 1] + _timedelta(seconds=span * frac)
                return t.isoformat()
            if a == 0.0:
                return times[i - 1].isoformat()
        return None

    max_idx = max(range(len(times)), key=lambda i: elevs[i])
    return {
        "nascer": crossing(0.0, True),
        "poente": crossing(0.0, False),
        "crepusculo_amanhecer": crossing(-6.0, True),
        "crepusculo_poente": crossing(-6.0, False),
        "meio_dia": times[max_idx].isoformat(),
    }
