"""Phase 3 — cross analysis (pure functions over the dataclasses).

Two objective pieces worth writing code for (Claude does the rest of the analysis
on top of the tools):
- **ACWR**: acute (current week) to chronic (~4-week rolling mean) load ratio in A.U.
  Classic overtraining-risk indicator (Gabbett). Works with the spreadsheet alone.
- **Load × recovery join by date**: matches a training session (when the DATE cell is
  filled) with that day's watch recovery. This crossing is where the value lives.
"""

from __future__ import annotations

import datetime as dt

from .models import RecoveryDay, Week


def weekly_load(weeks: list[Week]) -> list[dict]:
    """Load per week: total A.U. (RPE×time), total VTT and number of logged sessions."""
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
        return "no data"
    if ratio < 0.8:
        return "low load (detraining)"
    if ratio <= 1.3:
        return "optimal"
    if ratio <= 1.5:
        return "caution"
    return "high risk"


def acwr_series(weeks: list[Week], window: int = 4) -> list[dict]:
    """ACWR per week. Chronic = rolling mean of A.U. over the last ``window`` weeks (incl. current)."""
    load = weekly_load(weeks)
    ua = [r["carga_ua"] for r in load]
    out = []
    for i, row in enumerate(load):
        acute = row["carga_ua"]
        chronic_vals = ua[max(0, i - window + 1) : i + 1]
        chronic = sum(chronic_vals) / len(chronic_vals) if chronic_vals else 0.0
        # a week without load has no ACWR -> avoids a false "detraining" on empty weeks
        ratio = round(acute / chronic, 2) if (acute > 0 and chronic > 0) else None
        out.append(
            {**row, "chronic_avg_ua": round(chronic, 1), "acwr": ratio, "acwr_zone": _acwr_zone(ratio)}
        )
    return out


def _week_anchor(week: Week) -> dt.date | None:
    """Date of the week's "day 0" (Monday), inferred from any day with a filled DATE.

    The week is a consecutive Monday→Sunday block, so one date is enough:
    anchor = date − day_index. Then any day d has date = anchor + d.
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
    """Joins training and recovery by ISO DATE — the project's central crossing.

    One filled date per spreadsheet week is enough: the others are inferred
    (consecutive week). Days with recovery only (no training) are included too, with
    ``trained: false`` — useful to see the body's response the day after a heavy session.
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
                    "subjective_readiness": s.readiness,
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
