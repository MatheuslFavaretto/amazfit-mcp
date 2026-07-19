"""Testes do exportador de notas diárias Obsidian."""

from types import SimpleNamespace

import pytest

from amazfit_mcp import obsidian as ob
from amazfit_mcp.models import Exercise, RecoveryDay, Session, SetEntry, Week


def make_session(logged: bool = True, date: str | None = "2024-11-09") -> Session:
    sets = [
        SetEntry(serie=1, reps=8, peso=60, veloc=None, vtt=480.0),
        SetEntry(serie=2, reps=8, peso=60, veloc=None, vtt=480.0),
        SetEntry(serie=3, reps=6, peso=70, veloc=None, vtt=420.0),
        SetEntry(serie=4, reps=None, peso=None, veloc=None, vtt=0.0),  # série vazia
    ]
    ex = Exercise(name="Supino reto", sets=sets, vtt=1380.0)
    return Session(
        day_index=5, day="SÁBADO", date=date, exercises=[ex],
        pse=8, tempo_min=60, carga_ua=480.0, vtt_session=1380.0,
        wellness={}, readiness=7.5, logged=logged, planned=True,
    )


def make_recovery() -> RecoveryDay:
    return RecoveryDay(
        date="2024-11-09", resting_hr=56.0, hr_avg=72.0, hrv_sdnn=54.0,
        respiratory_rate=14.5,
        sleep={"asleep_h": 7.1, "deep_h": 1.2, "rem_h": 1.8, "core_h": 4.1,
               "in_bed_h": 7.6, "start": "2024-11-08 23:10", "end": "2024-11-09 06:50"},
    )


WORKOUT_DICT = {
    "date": "2024-11-09", "name": "Corrida leve", "kind": "run",
    "duration_min": 33.8, "distance_km": 5.2, "pace_min_km": 6.5,
    "avg_hr": 148, "trimp": 85.0,
}
METRICS = {"ctl": 42.3, "atl": 55.1, "tsb": -12.8, "readiness_score": 61}


@pytest.fixture()
def nota_completa():
    return ob.render_daily_note(
        "2024-11-09", session=make_session(), recovery=make_recovery(),
        workouts=[WORKOUT_DICT], metrics=METRICS,
    )


def test_frontmatter_completo(nota_completa):
    fm = nota_completa.split("---")[1]
    for line in (
        "date: 2024-11-09", "tags: [amazfit-mcp]", "trained: true",
        "carga_ua: 480", "vtt: 1380", "subjective_readiness: 7.5",
        "resting_hr: 56", "hrv_sdnn: 54", "sleep_h: 7.1",
        "trimp_total: 85", "ctl: 42.3", "atl: 55.1", "tsb: -12.8",
        "readiness_score: 61",
    ):
        assert f"\n{line}\n" in f"\n{fm}\n" or f"\n{line}\n" in fm, line


def test_todas_as_secoes(nota_completa):
    assert "# 2024-11-09" in nota_completa
    for sec in ("## Strength training", "## Activities", "## Recovery", "## Form"):
        assert sec in nota_completa
    # séries compactadas pulando a série vazia
    assert "| Supino reto | 8×60 · 8×60 · 6×70 | 1380 |" in nota_completa
    # atividade: emoji por kind, pace M:SS
    assert "🏃 Corrida leve" in nota_completa
    assert "6:30 /km" in nota_completa and "TRIMP 85" in nota_completa
    # sono com fases e vírgula decimal no corpo
    assert "Sleep: 7.1 h (deep 1.2 · rem 1.8 · core 4.1)" in nota_completa
    # forma com interpretação (tsb -12.8 < -10)
    assert "accumulated fatigue" in nota_completa


def test_determinismo():
    args = dict(session=make_session(), recovery=make_recovery(),
                workouts=[WORKOUT_DICT], metrics=METRICS)
    assert ob.render_daily_note("2024-11-09", **args) == ob.render_daily_note("2024-11-09", **args)


def test_omite_secoes_sem_dado():
    nota = ob.render_daily_note("2024-11-10", recovery=make_recovery())
    assert "## Recovery" in nota
    for ausente in ("## Strength training", "## Activities", "## Form", "sem dados"):
        assert ausente not in nota
    assert "trained" not in nota  # sem session -> chave omitida


def test_sessao_nao_registrada_sem_secao_de_treino():
    nota = ob.render_daily_note("2024-11-10", session=make_session(logged=False))
    assert "trained: false" in nota
    assert "## Strength training" not in nota
    assert "carga_ua" not in nota


def test_workout_dict_e_objeto_equivalentes():
    ns = SimpleNamespace(**WORKOUT_DICT)
    nota_dict = ob.render_daily_note("2024-11-09", workouts=[WORKOUT_DICT])
    nota_obj = ob.render_daily_note("2024-11-09", workouts=[ns])
    assert nota_dict == nota_obj
    assert "trimp_total: 85" in nota_obj


def test_interpretacao_tsb():
    assert "fresh" in ob.render_daily_note("2024-11-09", metrics={"tsb": 6.0})
    assert "neutral" in ob.render_daily_note("2024-11-09", metrics={"tsb": 0.0})


def test_sessions_by_date_infere_datas():
    # só o sábado tem DATA -> segunda (day_index 0) inferida via âncora da semana
    seg = make_session(date=None)
    seg.day_index, seg.day = 0, "SEGUNDA"
    sab = make_session(date="2024-11-09")
    vazia = make_session(logged=False, date=None)
    vazia.day_index = 2
    week = Week(week=1, sheet="SEM 1", sessions=[seg, sab, vazia])
    out = ob.sessions_by_date([week])
    assert set(out) == {"2024-11-04", "2024-11-09"}  # não logada fica de fora


def test_export_escreve_pula_e_sobrescreve(tmp_path):
    payload = {
        "2024-11-09": {"session": make_session(), "recovery": make_recovery(),
                       "workouts": [WORKOUT_DICT], "metrics": METRICS},
        "2024-11-10": {"recovery": make_recovery()},
        "2024-11-11": {},  # nota vazia -> pulada
    }
    paths = ob.export_notes(payload, directory=tmp_path)
    assert paths == [str(tmp_path / "2024-11-09.md"), str(tmp_path / "2024-11-10.md")]
    assert not (tmp_path / "2024-11-11.md").exists()
    before = (tmp_path / "2024-11-09.md").read_text(encoding="utf-8")
    assert before == ob.render_daily_note(
        "2024-11-09", session=make_session(), recovery=make_recovery(),
        workouts=[WORKOUT_DICT], metrics=METRICS,
    )
    # idempotente: segunda exportação sobrescreve com o mesmo conteúdo
    paths2 = ob.export_notes(payload, directory=tmp_path)
    assert paths2 == paths
    assert (tmp_path / "2024-11-09.md").read_text(encoding="utf-8") == before


def test_export_cria_diretorio(tmp_path):
    dest = tmp_path / "vault" / "Daily"
    paths = ob.export_notes({"2024-11-09": {"session": make_session()}}, directory=dest)
    assert paths == [str(dest / "2024-11-09.md")]
