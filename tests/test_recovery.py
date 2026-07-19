"""Testes da Fase 2 (recuperação via Apple Health / Health Auto Export)."""

from pathlib import Path

import pytest

from amazfit_mcp import recovery as rec
from amazfit_mcp import server

FIXDIR = Path(__file__).resolve().parent / "fixtures" / "recovery"


@pytest.fixture(scope="module")
def recs():
    return rec.load_recovery(FIXDIR)


def test_parseia_os_dias(recs):
    assert set(recs) == {"2024-11-04", "2024-11-05", "2024-11-09", "2024-11-10", "2024-11-16"}


def test_recuperacao_do_sabado(recs):
    r = recs["2024-11-09"]
    assert r.resting_hr == 56.0
    assert r.hr_avg == 72.0          # heart_rate vem como Min/Avg/Max -> pegamos o Avg
    assert r.hrv_sdnn == 54.0
    assert r.respiratory_rate == 14.5
    assert r.sleep["asleep_h"] == 7.1 and r.sleep["deep_h"] == 1.2


def test_sinal_de_fadiga_pos_sessao(recs):
    # domingo (11-10) após sábado pesado (11-09): FC repouso sobe, HRV cai
    sab, dom = recs["2024-11-09"], recs["2024-11-10"]
    assert dom.resting_hr > sab.resting_hr
    assert dom.hrv_sdnn < sab.hrv_sdnn


def test_formatos_de_data_caem_no_mesmo_dia(recs):
    # qty usa "YYYY-MM-DD HH:MM:SS Z"; sleep usa "YYYY-MM-DD" -> mesmo dia
    r = recs["2024-11-04"]
    assert r.resting_hr is not None and r.sleep is not None


def test_range(recs):
    out = rec.get_recovery_range("2024-11-04", "2024-11-10", FIXDIR)
    assert [r.date for r in out] == ["2024-11-04", "2024-11-05", "2024-11-09", "2024-11-10"]


def test_pasta_inexistente_nao_quebra():
    assert rec.load_recovery(FIXDIR.parent / "naoexiste") == {}


def test_tools_via_server(monkeypatch):
    monkeypatch.setenv("AMAZFIT_MCP_RECOVERY_DIR", str(FIXDIR))
    out = server.get_recovery("2024-11-09")
    assert out["found"] is True and out["resting_hr"] == 56.0
    st = server.recovery_status()
    assert st["days_with_data"] == 5
    assert st["date_range"] == ["2024-11-04", "2024-11-16"]
    assert st["latest"]["date"] == "2024-11-16"


def test_get_recovery_ausente(monkeypatch, tmp_path):
    monkeypatch.setenv("AMAZFIT_MCP_RECOVERY_DIR", str(tmp_path))
    out = server.get_recovery("2024-01-01")
    assert out["found"] is False
