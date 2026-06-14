"""Servidor MCP do AmazFitOps — expõe a planilha de treino como tools.

A análise (cruzar carga × recuperação, detectar overtraining, etc.) é feita pelo
Claude. Aqui só servimos os dados de forma limpa e com unidades explícitas.
"""

from __future__ import annotations

from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from . import analysis as an
from . import cellmap as cm
from . import config
from . import recovery as rec
from . import spreadsheet as sp

mcp = FastMCP("AmazFitOps")

# nome do dia (normalizado) -> índice 0..6
_DAY_ALIASES = {
    "segunda": 0, "segunda-feira": 0, "seg": 0, "monday": 0, "mon": 0,
    "terca": 1, "terca-feira": 1, "ter": 1, "tuesday": 1, "tue": 1,
    "quarta": 2, "quarta-feira": 2, "qua": 2, "wednesday": 2, "wed": 2,
    "quinta": 3, "quinta-feira": 3, "qui": 3, "thursday": 3, "thu": 3,
    "sexta": 4, "sexta-feira": 4, "sex": 4, "friday": 4, "fri": 4,
    "sabado": 5, "sab": 5, "saturday": 5, "sat": 5,
    "domingo": 6, "dom": 6, "sunday": 6, "sun": 6,
}


def _resolve_day(day: int | str) -> int:
    """Aceita índice 1–7 (1 = segunda) ou nome em PT/EN. Retorna 0..6."""
    if isinstance(day, bool):
        raise ValueError("dia inválido")
    if isinstance(day, (int, float)):
        i = int(day)
        if 1 <= i <= 7:
            return i - 1
        if i == 0:  # tolera 0-index
            return 0
        raise ValueError(f"índice de dia fora de 1..7: {day}")
    n = cm.normalize(day)
    if n.isdigit():
        return _resolve_day(int(n))
    if n in _DAY_ALIASES:
        return _DAY_ALIASES[n]
    base = n.replace("-feira", "").strip()
    if base in _DAY_ALIASES:
        return _DAY_ALIASES[base]
    raise ValueError(f"dia não reconhecido: {day!r}")


@mcp.tool()
def list_weeks() -> list[dict]:
    """Lista todas as semanas da planilha com indicadores de resumo.

    Para cada semana (aba SEM N): intervalo de datas, nº de sessões registradas
    (treinadas de verdade) vs planejadas, VTT total, Carga U.A. total, prontidão
    média e ``has_data`` (se houve treino registrado). Use para descobrir quais
    semanas têm dados antes de pedir detalhes.
    """
    return sp.list_summary(sp.load_weeks())


@mcp.tool()
def get_week_summary(week: int) -> dict:
    """Resumo de uma semana, com a quebra por dia.

    Retorna VTT semanal, Carga de treino semanal em U.A. (PSE × tempo),
    sessões feitas/planejadas, prontidão média e, por dia, VTT/U.A./prontidão e
    se foi treinado. ``week`` é o número da aba (1 = SEM 1).
    """
    weeks = sp.load_weeks()
    return sp.week_summary(sp.find_week(weeks, week))


@mcp.tool()
def get_session(week: int, day: int | str) -> dict:
    """Detalha um treino específico (uma semana + um dia).

    ``day`` aceita nome ("sábado", "segunda") ou índice 1–7 (1 = segunda).
    Retorna data, exercícios com séries (reps/peso/veloc/VTT por série),
    VTT da sessão, PSE, tempo, Carga U.A. e o bem-estar do dia
    (sono/estresse/fadiga/dor + prontidão).
    """
    weeks = sp.load_weeks()
    w = sp.find_week(weeks, week)
    session = w.sessions[_resolve_day(day)]
    out = asdict(session)
    out["week"] = w.week
    return out


@mcp.tool()
def get_exercise_history(exercise: str, weeks: list[int] | None = None) -> dict:
    """Progressão de um exercício ao longo das semanas.

    Casa o nome de forma flexível (ignora acento/caixa e tolera os typos da
    planilha, ex.: "agacamento"). Para cada semana em que o exercício aparece,
    retorna peso máximo, volume total (VTT) e as séries. ``weeks`` opcional
    filtra por números de semana. Use para responder "estou progredindo no X?".
    """
    all_weeks = sp.load_weeks()
    if weeks:
        wanted = set(weeks)
        all_weeks = [w for w in all_weeks if w.week in wanted]
    return sp.exercise_history(all_weeks, exercise)


@mcp.tool()
def get_recovery(date: str) -> dict:
    """Recuperação de um dia, vinda do Amazfit GTR 4 via Apple Health.

    Retorna FC de repouso (bpm), HRV SDNN (ms), freq. respiratória e sono
    (horas dormidas + fases deep/rem/core). ``date`` no formato YYYY-MM-DD.
    Se não houver dado para a data, retorna ``found: false``.
    """
    r = rec.get_recovery(date)
    if r is None:
        return {"date": date, "found": False, "note": "sem dado de recuperação para essa data"}
    out = asdict(r)
    out["found"] = True
    return out


@mcp.tool()
def get_recovery_range(start: str, end: str) -> list[dict]:
    """Série temporal de recuperação entre duas datas (YYYY-MM-DD), inclusive.

    Use para ver tendência de FC de repouso / HRV / sono ao longo dos dias e
    cruzar com a carga de treino da planilha.
    """
    return [asdict(r) for r in rec.get_recovery_range(start, end)]


@mcp.tool()
def recovery_status() -> dict:
    """Diagnóstico da fonte de recuperação (Fase 0): quantos dias há, o intervalo,
    o dado mais recente e a pasta lida. Use para confirmar que o sync
    Apple Health → Health Auto Export → Mac está funcionando.
    """
    recs = rec.load_recovery()
    days = sorted(recs)
    return {
        "days_with_data": len(days),
        "date_range": [days[0], days[-1]] if days else None,
        "latest": asdict(recs[days[-1]]) if days else None,
        "recovery_dir": str(config.recovery_dir()),
    }


@mcp.tool()
def get_training_load(window: int = 4) -> list[dict]:
    """Progressão de carga semana a semana + ACWR (risco de overtraining).

    Para cada semana: VTT total, Carga U.A. total, e o ACWR = carga aguda (semana atual)
    dividida pela crônica (média móvel de ``window`` semanas, incl. a atual). Faixas do
    ``acwr_zone``: <0,8 baixa carga · 0,8–1,3 ótima · 1,3–1,5 atenção · >1,5 risco alto.
    Só depende da planilha (não precisa do relógio).
    """
    return an.acwr_series(sp.load_weeks(), window=window)


@mcp.tool()
def compare_load_recovery(start: str, end: str) -> list[dict]:
    """Cruza carga de treino (planilha) com recuperação (relógio) por data — o coração do projeto.

    Para cada dia entre ``start`` e ``end`` (YYYY-MM-DD): se treinou, a Carga U.A./VTT e a
    prontidão subjetiva; e a recuperação objetiva do dia (FC de repouso, HRV, sono). Dias só
    com recuperação aparecem com ``trained: false`` — bons pra ver a resposta no dia seguinte a
    uma sessão pesada (FC repouso ↑ / HRV ↓). Basta UMA data preenchida por semana na planilha —
    as demais são inferidas.
    """
    weeks = sp.load_weeks()
    recovery = rec.load_recovery()
    return an.compare_load_recovery(
        weeks, recovery, start=rec._parse_day(start), end=rec._parse_day(end)
    )


def main() -> None:
    """Entry point (stdio). Registrado como script ``amazfitops``."""
    mcp.run()


if __name__ == "__main__":
    main()
