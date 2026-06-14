"""Testes da Fase 1 contra a fixture sintética (números conhecidos)."""

import datetime as dt
from pathlib import Path

import pytest

from amazfitops import spreadsheet as sp
from amazfitops import server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.xlsx"


@pytest.fixture(scope="module")
def weeks():
    assert FIXTURE.exists(), "rode: python tests/make_fixture.py"
    return sp.load_weeks(FIXTURE)


def test_detecta_12_semanas(weeks):
    assert [w.week for w in weeks] == list(range(1, 13))


def test_sessao_sabado_semana1(weeks):
    s = sp.find_week(weeks, 1).sessions[5]  # sábado
    assert s.day == "SÁBADO"
    assert s.date == "2024-11-09"
    assert s.logged is True
    assert s.vtt_session == 5000.0          # 3200 + 1800
    assert s.pse == 8.0 and s.tempo_min == 60.0
    assert s.carga_ua == 480.0              # 8 * 60
    assert s.readiness == 4.0               # média(4,5,4,3)
    nomes = [e.name for e in s.exercises]
    assert nomes == ["Agachamento Livre", "Supino Reto"]
    agacho = s.exercises[0]
    assert len(agacho.sets) == 4 and agacho.vtt == 3200.0


def test_vtt_recalculado_ignora_cache(weeks):
    # O openpyxl perde o cache das fórmulas ao salvar; o VTT 3200 só existe
    # porque recalculamos reps*peso a partir dos inputs.
    agacho = sp.find_week(weeks, 1).sessions[5].exercises[0]
    assert agacho.sets[0].vtt == 800.0      # 10 * 80


def test_resumo_semana1(weeks):
    r = sp.week_summary(sp.find_week(weeks, 1))
    assert r["sessions_logged"] == 2        # segunda + sábado
    assert r["vtt_total"] == 9800.0         # 4800 + 5000
    assert r["carga_ua_total"] == 830.0     # 350 + 480
    assert r["readiness_avg"] == 4.5        # média(5.0, 4.0)
    assert r["date_range"] == ["2024-11-04", "2024-11-09"]


def test_list_summary_marca_has_data(weeks):
    resumo = {x["week"]: x for x in sp.list_summary(weeks)}
    assert resumo[1]["has_data"] is True
    assert resumo[2]["has_data"] is True
    assert resumo[3]["has_data"] is False


def test_dias_planejados_vazios_nao_contam(weeks):
    # Domingo da semana 1 não foi escrito -> nem planejado nem registrado.
    dom = sp.find_week(weeks, 1).sessions[6]
    assert dom.logged is False and dom.planned is False


def test_exercise_history_progressao(weeks):
    h = sp.exercise_history(weeks, "agachamento")
    assert h["matched_names"] == ["Agachamento Livre"]
    assert h["weeks_found"] == 2
    by_week = {w["week"]: w for w in h["history"]}
    assert by_week[1]["max_peso"] == 80.0 and by_week[1]["total_vtt"] == 3200.0
    assert by_week[2]["max_peso"] == 85.0 and by_week[2]["total_vtt"] == 3400.0


def test_history_casa_typo(weeks):
    # match flexível: "supino" acha "Supino Reto"
    h = sp.exercise_history(weeks, "supino")
    assert "Supino Reto" in h["matched_names"]


@pytest.mark.parametrize(
    "entrada,esperado",
    [("sábado", 5), ("sabado", 5), ("SÁBADO", 5), ("sab", 5),
     ("segunda", 0), ("segunda-feira", 0), (1, 0), (6, 5), (7, 6), ("3", 2)],
)
def test_resolve_day(entrada, esperado):
    assert server._resolve_day(entrada) == esperado


def test_resolve_day_invalido():
    with pytest.raises(ValueError):
        server._resolve_day("blursday")


def test_date_aceita_datetime_string_e_erros():
    assert sp._date(dt.datetime(2024, 11, 9)) == "2024-11-09"
    assert sp._date(dt.date(2024, 11, 9)) == "2024-11-09"
    assert sp._date("09/11/2024") == "2024-11-09"   # texto dd/mm/aaaa
    assert sp._date("2024-11-09") == "2024-11-09"
    assert sp._date(None) is None
    assert sp._date("#DIV/0!") is None
