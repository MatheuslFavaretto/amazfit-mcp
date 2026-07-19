"""Testes das métricas longitudinais (carga diária, CTL/ATL/TSB, tendências, readiness)."""

import datetime as dt
from types import SimpleNamespace

import pytest

from amazfit_mcp import metrics as mx
from amazfit_mcp.models import RecoveryDay, Session, Week


def _sess(day_index, date=None, carga=None, logged=True):
    return Session(day_index, "DIA", date, [], None, None, carga, 0.0, {}, None, logged, True)


def _rec(date, rhr=None, hrv=None, sleep_h=None):
    sleep = {"asleep_h": sleep_h} if sleep_h is not None else None
    return RecoveryDay(date, rhr, None, hrv, None, sleep)


# ---------------------------------------------------------------- carga diária


def test_daily_load_ancora_inferida_e_workout_no_mesmo_dia():
    # segunda com data (âncora), sábado logado SEM data -> inferido 2024-03-09
    seg = _sess(0, "2024-03-04", None, logged=False)
    sab = _sess(5, None, 480.0)
    w2 = Week(2, "SEM 2", [_sess(2, "2024-03-13", 200.0)])  # data explícita
    workouts = [
        {"date": "2024-03-09", "trimp": 50.0},              # dict, soma no sábado
        SimpleNamespace(date="2024-03-11", trimp=35.0),      # objeto, dia só de workout
        {"date": "2024-03-12", "trimp": None},               # sem trimp -> ignorado
    ]
    rows = mx.daily_load_series([Week(1, "SEM 1", [seg, sab]), w2], workouts)

    assert [r["date"] for r in rows] == ["2024-03-09", "2024-03-11", "2024-03-13"]
    assert rows[0]["load"] == 530.0 and rows[0]["sources"] == ["spreadsheet", "workout"]
    assert rows[1]["load"] == 35.0 and rows[1]["sources"] == ["workout"]
    assert rows[2]["load"] == 200.0 and rows[2]["sources"] == ["spreadsheet"]


def test_daily_load_semana_sem_ancora_fica_de_fora():
    rows = mx.daily_load_series([Week(1, "SEM 1", [_sess(1, None, 999.0)])])
    assert rows == []


# ------------------------------------------------------------- fitness/fadiga


def _const_loads(start, days, load):
    d0 = dt.date.fromisoformat(start)
    return [
        {"date": (d0 + dt.timedelta(days=i)).isoformat(), "load": load}
        for i in range(days)
    ]


def test_ewma_converge_para_carga_constante():
    series = mx.fitness_fatigue(_const_loads("2023-01-01", 600, 100.0))
    last = series[-1]
    assert last["ctl"] == 100.0 and last["atl"] == 100.0  # CTL/ATL -> load
    assert abs(last["tsb"]) <= 0.1                        # forma zera no equilíbrio


def test_tsb_negativo_apos_pico_de_carga():
    loads = _const_loads("2024-01-01", 28, 50.0) + _const_loads("2024-01-29", 7, 300.0)
    series = mx.fitness_fatigue(loads)
    assert series[-1]["tsb"] < 0  # ATL (7d) sobe muito mais rápido que CTL (42d)


def test_serie_continua_preenche_dias_sem_treino():
    series = mx.fitness_fatigue(
        [{"date": "2024-01-01", "load": 100.0}, {"date": "2024-01-05", "load": 200.0}]
    )
    assert [r["date"] for r in series] == [
        "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"
    ]
    assert series[1]["load"] == 0.0
    assert series[0]["tsb"] == 0.0  # dia 1: ontem não existe -> CTL=ATL=0


def test_fitness_fatigue_vazio():
    assert mx.fitness_fatigue([]) == []


# ------------------------------------------------------------------ tendências


def test_trend_z_score_na_mao():
    # baseline [50,52,48,50,50]: média 50, pstdev = sqrt(8/5) = 1.2649
    rec = {
        d: _rec(d, rhr=v)
        for d, v in zip(
            ["2024-04-01", "2024-04-02", "2024-04-03", "2024-04-04", "2024-04-05"],
            [50.0, 52.0, 48.0, 50.0, 50.0],
            strict=True,
        )
    }
    rec["2024-04-06"] = _rec("2024-04-06", rhr=55.0)
    rec["2024-02-01"] = _rec("2024-02-01", rhr=100.0)  # fora da janela de 28d -> não entra

    rows = {r["date"]: r for r in mx.trend_series(rec, "resting_hr")}
    r = rows["2024-04-06"]
    assert r["baseline"] == 50.0 and r["std"] == 1.26
    assert r["z"] == round(5 / 1.2649110640673518, 2) == 3.95
    # <5 dias de baseline -> z None (2024-04-03 só tem 2 anteriores na janela)
    assert rows["2024-04-03"]["z"] is None and rows["2024-04-03"]["baseline"] == 51.0


def test_trend_std_zero_da_z_none():
    rec = {f"2024-04-0{i}": _rec(f"2024-04-0{i}", hrv=60.0) for i in range(1, 8)}
    rows = mx.trend_series(rec, "hrv_sdnn")
    assert all(r["z"] is None for r in rows)  # std == 0 em toda a série
    assert rows[-1]["baseline"] == 60.0


def test_trend_metric_invalida():
    with pytest.raises(ValueError):
        mx.trend_series({}, "vo2max")


# ------------------------------------------------------------------- readiness


def _recovery_semana():
    """5 dias de baseline + dia alvo 2024-05-06 (HRV/RHR acima, sono abaixo)."""
    days = ["2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05"]
    hrvs = [60.0, 62.0, 58.0, 60.0, 60.0]
    rhrs = [50.0, 52.0, 48.0, 50.0, 50.0]
    rec = {
        d: _rec(d, rhr=r, hrv=h, sleep_h=7.0)
        for d, r, h in zip(days, rhrs, hrvs, strict=True)
    }
    rec["2024-05-06"] = _rec("2024-05-06", rhr=52.0, hrv=62.0, sleep_h=6.0)
    return rec


def test_readiness_completo():
    out = mx.readiness_score("2024-05-06", _recovery_semana(), tsb=-5.0, subjective=3.5)
    comps = out["components"]
    assert set(comps) == {"hrv", "rhr", "sleep", "tsb", "subjective"}
    assert sum(c["weight"] for c in comps.values()) == 100
    # componentes conferidos na mão (z = 2/1.2649 = 1.58 pros dois lados)
    assert comps["hrv"]["score"] == 89.5       # 50 + 25*1.58
    assert comps["rhr"]["score"] == 10.5       # 50 - 25*1.58 (invertido)
    assert comps["sleep"]["score"] == 85.7      # 100 * 6/7
    assert comps["tsb"]["score"] == 55.6       # (-5+30)/45 * 100
    assert comps["subjective"]["score"] == 70.0  # 3.5 * 20
    # score final = média ponderada do próprio breakdown (transparência)
    esperado = round(sum(c["score"] * c["weight"] for c in comps.values()) / 100)
    assert out["score"] == esperado == 62
    assert out["zone"] == "ok"


def test_readiness_parcial_renormaliza_pesos():
    # só tsb (15) + subjetiva (10): pesos renormalizados sobre 25
    out = mx.readiness_score("2024-05-06", {}, tsb=-7.5, subjective=4.0)
    assert set(out["components"]) == {"tsb", "subjective"}
    assert out["components"]["tsb"]["score"] == 50.0
    assert out["components"]["subjective"]["score"] == 80.0
    assert out["score"] == round((50.0 * 15 + 80.0 * 10) / 25) == 62


def test_readiness_so_subjetiva():
    out = mx.readiness_score("2024-05-06", {}, subjective=4.0)
    assert out["score"] == 80 and out["zone"] == "ready"


def test_readiness_sem_nenhum_dado():
    out = mx.readiness_score("2024-05-06", {})
    assert out["score"] is None and out["components"] == {}
    assert "no data" in out["note"]


def test_zone():
    assert mx.zone(90) == "ready" and mx.zone(75) == "ready"
    assert mx.zone(74) == "ok" and mx.zone(50) == "ok"
    assert mx.zone(49) == "caution" and mx.zone(25) == "caution"
    assert mx.zone(24) == "rest" and mx.zone(0) == "rest"
    assert mx.zone(None) == "no data"
