"""Curva solar: meia-noite escura, no de Brasília claro."""


from datetime import UTC, datetime

from custom_components.mw_lumina.solar import elevation_at, solar_events_today

BRASILIA = (-15.839851355229362, -48.036003112792976)


def _utc(y, m, d, hh, mm=0, timezone_offset=-3):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def test_dia_solstice_para_de_dia():
    # meio-dia de Brasília (12:00 local = 15:00 UTC) em outubro: sol quase a pino
    noon_utc = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    elev = elevation_at(noon_utc, *BRASILIA)
    assert elev > 55.0, f"meio-dia de outubro deveria estar alto (got {elev})"


def test_noite_escura():
    midnight_utc = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)  # 00:00 local
    elev = elevation_at(midnight_utc, *BRASILIA)
    assert elev < -30.0


def test_nascer_troveira():
    dawn_utc = datetime(2026, 10, 15, 9, 40, tzinfo=UTC)  # ~06:40 local
    elev = elevation_at(dawn_utc, *BRASILIA)
    assert -2.0 < elev < 25.0


def test_eventos_do_dia_tem_nascer_e_poente():
    noon_utc = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    events = solar_events_today(noon_utc, *BRASILIA)
    assert events["nascer"] is not None
    assert events["poente"] is not None
    assert datetime.fromisoformat(events["nascer"]) < datetime.fromisoformat(events["meio_dia"])
    assert datetime.fromisoformat(events["meio_dia"]) < datetime.fromisoformat(events["poente"])


def test_periodo_negativo_no_hemisferio_norte_inverno():
    # Chicago, 21 dez: meio-dia curto, noite longa
    noon_utc = datetime(2026, 12, 21, 18, 0, tzinfo=UTC)
    elev = elevation_at(noon_utc, 41.88, -87.63)
    assert 0.0 < elev < 30.0
