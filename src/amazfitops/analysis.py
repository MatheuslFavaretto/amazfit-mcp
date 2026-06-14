"""Fase 3 — análise cruzada (funções puras sobre os dataclasses).

Duas peças objetivas que valem código (o resto da análise o Claude faz em cima das tools):
- **ACWR**: razão entre carga aguda (semana atual) e crônica (média móvel ~4 semanas) em U.A.
  Indicador clássico de risco de overtraining (Gabbett). Funciona só com a planilha.
- **Join carga × recuperação por data**: casa a sessão de treino (se a célula DATA estiver
  preenchida) com a recuperação do relógio daquele dia. É o cruzamento "onde mora o valor".
"""

from __future__ import annotations

import datetime as dt

from .models import RecoveryDay, Week


def weekly_load(weeks: list[Week]) -> list[dict]:
    """Carga por semana: U.A. total (PSE×tempo), VTT total e nº de sessões registradas."""
    rows = []
    for w in weeks:
        ua = sum(s.carga_ua for s in w.sessions if s.carga_ua is not None)
        vtt = sum(s.vtt_session for s in w.sessions if s.logged)
        logged = sum(1 for s in w.sessions if s.logged)
        rows.append(
            {
                "week": w.week,
                "carga_ua": round(ua, 1),
                "vtt": round(vtt, 1),
                "sessions_logged": logged,
            }
        )
    return rows


def _acwr_zone(ratio: float | None) -> str:
    if ratio is None:
        return "sem dado"
    if ratio < 0.8:
        return "baixa carga (destreino)"
    if ratio <= 1.3:
        return "faixa ótima"
    if ratio <= 1.5:
        return "atenção"
    return "risco alto"


def acwr_series(weeks: list[Week], window: int = 4) -> list[dict]:
    """ACWR por semana. Crônica = média móvel de U.A. nas últimas ``window`` semanas (inclui a atual)."""
    load = weekly_load(weeks)
    ua = [r["carga_ua"] for r in load]
    out = []
    for i, row in enumerate(load):
        acute = row["carga_ua"]
        chronic_vals = ua[max(0, i - window + 1) : i + 1]
        chronic = sum(chronic_vals) / len(chronic_vals) if chronic_vals else 0.0
        # semana sem carga não tem ACWR -> evita falso "destreino" nas semanas vazias
        ratio = round(acute / chronic, 2) if (acute > 0 and chronic > 0) else None
        out.append(
            {**row, "chronic_avg_ua": round(chronic, 1), "acwr": ratio, "acwr_zone": _acwr_zone(ratio)}
        )
    return out


def _week_anchor(week: Week) -> dt.date | None:
    """Data do 'dia 0' (segunda) da semana, inferida de qualquer dia com DATA preenchida.

    A semana é Segunda→Domingo consecutiva, então basta uma data: âncora = data − day_index.
    Daí qualquer dia d tem data = âncora + d.
    """
    for s in week.sessions:
        if s.date:
            try:
                return dt.date.fromisoformat(s.date) - dt.timedelta(days=s.day_index)
            except ValueError:
                continue
    return None


def compare_load_recovery(
    weeks: list[Week],
    recovery: dict[str, RecoveryDay],
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Junta treino e recuperação por DATA (ISO) — o cruzamento central do projeto.

    Basta UMA data preenchida por semana na planilha: as outras são inferidas (semana
    consecutiva). Dias só com recuperação (sem treino) também entram, com ``trained: false`` —
    úteis pra ver a resposta do corpo no dia seguinte a uma sessão pesada.
    """
    sessions_by_date: dict[str, tuple[int, object]] = {}
    for w in weeks:
        anchor = _week_anchor(w)
        for s in w.sessions:
            if not s.logged:
                continue
            day = s.date
            if not day and anchor is not None:
                day = (anchor + dt.timedelta(days=s.day_index)).isoformat()
            if day:
                sessions_by_date[day] = (w.week, s)

    def in_range(d: str) -> bool:
        return (start is None or d >= start) and (end is None or d <= end)

    rows = []
    for d in sorted(x for x in (set(sessions_by_date) | set(recovery)) if in_range(x)):
        row: dict = {"date": d, "trained": d in sessions_by_date}
        if d in sessions_by_date:
            week, s = sessions_by_date[d]
            row.update(
                {
                    "week": week,
                    "day": s.day,
                    "carga_ua": s.carga_ua,
                    "vtt": s.vtt_session,
                    "readiness_subjetiva": s.readiness,
                }
            )
        r = recovery.get(d)
        if r is not None:
            row.update(
                {
                    "resting_hr": r.resting_hr,
                    "hrv_sdnn": r.hrv_sdnn,
                    "sleep_h": (r.sleep or {}).get("asleep_h"),
                }
            )
        rows.append(row)
    return rows
