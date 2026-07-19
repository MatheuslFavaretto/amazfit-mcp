"""Testes do módulo de workouts (Health Auto Export / Apple Health)."""

import math
from pathlib import Path

import pytest

from amazfit_mcp import workouts as wk

FIXDIR = Path(__file__).resolve().parent / "fixtures" / "recovery"


@pytest.fixture(scope="module")
def ws():
    return wk.load_workouts(FIXDIR)


def _by_date(ws, date, kind=None):
    return [w for w in ws if w.date == date and (kind is None or w.kind == kind)]


def test_carrega_e_ordena_por_inicio(ws):
    assert len(ws) == 6
    assert [w.date for w in ws] == sorted(w.date for w in ws)
    # dois workouts no mesmo dia (11-16): força de manhã, corrida à noite
    dia16 = _by_date(ws, "2024-11-16")
    assert [w.kind for w in dia16] == ["strength", "run"]


def test_variantes_de_chaves(ws):
    # workoutName + avgHeartRate como número puro
    run = _by_date(ws, "2024-11-05")[0]
    assert run.name == "Running" and run.kind == "run"
    assert run.avg_hr == 125 and run.max_hr == 152
    assert run.kcal == 305  # activeEnergy sem "units"
    # heartRateAvg/heartRateMax como dict {"qty"}
    run_mi = _by_date(ws, "2024-11-09")[0]
    assert run_mi.avg_hr == 152 and run_mi.max_hr == 175


def test_duration_segundos_vs_minutos(ws):
    # 1800 (> 1000) é segundos -> 30 min; 30 (<= 1000) já é minutos
    assert _by_date(ws, "2024-11-04")[0].duration_min == 30.0
    assert _by_date(ws, "2024-11-05")[0].duration_min == 30.0


def test_conversao_mi_para_km(ws):
    run = _by_date(ws, "2024-11-09")[0]
    assert run.distance_km == pytest.approx(8.047, abs=0.001)  # 5 mi * 1.609344
    assert run.pace_min_km == pytest.approx(5.59, abs=0.01)    # 45 min / 8.047 km


def test_trimp_calculado_a_mao(monkeypatch):
    monkeypatch.setenv("AMAZFIT_MCP_HR_REST", "60")
    monkeypatch.setenv("AMAZFIT_MCP_HR_MAX", "190")
    run = _by_date(wk.load_workouts(FIXDIR), "2024-11-05")[0]
    # HRr = (125-60)/(190-60) = 0.5; trimp = 30 * 0.5 * 0.64 * e^0.96 = 25.07 -> 25.1
    assert run.trimp == 25.1
    assert run.trimp == round(30 * 0.5 * 0.64 * math.exp(1.92 * 0.5), 1)


def test_sem_fc_trimp_none(ws):
    strength = _by_date(ws, "2024-11-16", kind="strength")[0]
    assert strength.avg_hr is None and strength.trimp is None
    assert strength.kcal == 250 and strength.duration_min == 55.0
    assert strength.distance_km is None and strength.pace_min_km is None


def test_campos_faltando_nao_quebram(ws):
    # só name/start/end: duração cai no delta end-start, resto None
    run = _by_date(ws, "2024-11-16", kind="run")[0]
    assert run.duration_min == 20.0
    assert run.distance_km is None and run.pace_min_km is None
    assert run.avg_hr is None and run.trimp is None and run.kcal is None


def test_kind_normalizado(ws):
    assert {w.kind for w in ws} == {"run", "walk", "strength"}
    assert len([w for w in ws if w.kind == "run"]) == 4


def test_filtro_por_range_e_kind():
    out = wk.get_workouts("2024-11-04", "2024-11-10", directory=FIXDIR)
    assert [w.date for w in out] == ["2024-11-04", "2024-11-05", "2024-11-09", "2024-11-10"]
    runs = wk.get_workouts("2024-11-04", "2024-11-10", kind="run", directory=FIXDIR)
    assert len(runs) == 3 and all(w.kind == "run" for w in runs)
    walks = wk.get_workouts("2024-11-01", "2024-11-30", kind="walk", directory=FIXDIR)
    assert len(walks) == 1 and walks[0].name == "Outdoor Walk"


def test_pasta_inexistente_nao_quebra():
    assert wk.load_workouts(FIXDIR.parent / "naoexiste") == []
