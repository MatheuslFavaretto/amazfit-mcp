"""Testes da Fase 3 (ACWR + join carga × recuperação) sobre as duas fixtures."""

from pathlib import Path

import pytest

from amazfit_mcp import analysis as an
from amazfit_mcp import recovery as rec
from amazfit_mcp import spreadsheet as sp
from amazfit_mcp.models import Exercise, Session, SetEntry, Week

FX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def weeks():
    return sp.load_weeks(FX / "sample.xlsx")


@pytest.fixture(scope="module")
def recovery():
    return rec.load_recovery(FX / "recovery")


def test_weekly_load(weeks):
    load = {r["week"]: r for r in an.weekly_load(weeks)}
    assert load[1]["carga_ua"] == 830.0 and load[1]["vtt"] == 9800.0
    assert load[2]["carga_ua"] == 520.0


def test_acwr(weeks):
    s = {r["week"]: r for r in an.acwr_series(weeks, window=4)}
    assert s[1]["acwr"] == 1.0                       # semana 1 sozinha -> aguda == crônica
    assert s[1]["acwr_zone"] == "optimal"
    assert s[2]["acwr"] == round(520 / 675, 2)        # 520 / média(830,520) = 0.77


def test_join_carga_recuperacao(weeks, recovery):
    rows = {
        r["date"]: r
        for r in an.compare_load_recovery(weeks, recovery, "2024-11-04", "2024-11-16")
    }
    assert set(rows) == {"2024-11-04", "2024-11-05", "2024-11-09", "2024-11-10", "2024-11-16"}
    # sábado: treino + recuperação juntos
    assert rows["2024-11-09"]["trained"] is True
    assert rows["2024-11-09"]["carga_ua"] == 480.0 and rows["2024-11-09"]["resting_hr"] == 56.0
    # domingo: sem treino, mas mostra a fadiga (HRV baixo)
    assert rows["2024-11-10"]["trained"] is False and rows["2024-11-10"]["hrv_sdnn"] == 41.0
    # terça: só recuperação
    assert rows["2024-11-05"]["trained"] is False and "carga_ua" not in rows["2024-11-05"]


def test_tools_via_server(monkeypatch):
    monkeypatch.setenv("AMAZFIT_MCP_XLSX", str(FX / "sample.xlsx"))
    monkeypatch.setenv("AMAZFIT_MCP_RECOVERY_DIR", str(FX / "recovery"))
    from amazfit_mcp import server

    rows = server.compare_load_recovery("2024-11-09", "2024-11-10")
    assert [r["date"] for r in rows] == ["2024-11-09", "2024-11-10"]
    load = {r["week"]: r for r in server.get_training_load()}
    assert load[1]["acwr"] == 1.0


def test_acwr_semana_sem_dado_e_none(weeks):
    # semanas 3..12 da fixture não têm treino -> ACWR None / "no data", não "destreino"
    s = {r["week"]: r for r in an.acwr_series(weeks, window=4)}
    assert s[3]["acwr"] is None and s[3]["acwr_zone"] == "no data"


def test_infere_ancora_da_semana():
    sessions = [
        Session(i, "X", None, [], None, None, None, 0.0, {}, None, False, False)
        for i in range(7)
    ]
    sessions[2].date = "2024-03-06"  # quarta -> âncora = segunda 2024-03-04
    anchor = an._week_anchor(Week(1, "SEM 1", sessions))
    assert anchor.isoformat() == "2024-03-04"


def test_compare_usa_data_inferida(recovery):
    # sábado logado SEM data própria; segunda tem data -> sábado inferido 11-09 casa recuperação
    seg = Session(0, "SEGUNDA", "2024-11-04", [], None, None, None, 0.0, {}, None, False, False)
    sab = Session(
        5, "SÁBADO", None,
        [Exercise("Agacho", [SetEntry(1, 10, 80, 2, 800.0)], 800.0)],
        8.0, 60.0, 480.0, 800.0, {}, None, True, True,
    )
    rows = {
        r["date"]: r
        for r in an.compare_load_recovery([Week(1, "SEM 1", [seg, sab])], recovery)
    }
    assert rows["2024-11-09"]["trained"] is True
    assert rows["2024-11-09"]["carga_ua"] == 480.0
    assert rows["2024-11-09"]["resting_hr"] == 56.0
