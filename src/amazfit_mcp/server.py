"""amazfit-mcp server — exposes the training spreadsheet and watch data as tools.

The analysis (crossing load × recovery, spotting overtraining, etc.) is done by
Claude. Here we only serve the data cleanly, with explicit units.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from . import analysis as an
from . import cellmap as cm
from . import config
from . import metrics as mx
from . import obsidian as obs
from . import recovery as rec
from . import report as rp
from . import spreadsheet as sp
from . import workouts as wk

mcp = FastMCP("amazfit-mcp")

# normalized day name -> index 0..6 (PT + EN, the user speaks Portuguese)
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
    """Accepts index 1–7 (1 = Monday) or a PT/EN day name. Returns 0..6."""
    if isinstance(day, bool):
        raise ValueError("invalid day")
    if isinstance(day, (int, float)):
        i = int(day)
        if 1 <= i <= 7:
            return i - 1
        if i == 0:  # tolerate 0-index
            return 0
        raise ValueError(f"day index outside 1..7: {day}")
    n = cm.normalize(day)
    if n.isdigit():
        return _resolve_day(int(n))
    if n in _DAY_ALIASES:
        return _DAY_ALIASES[n]
    base = n.replace("-feira", "").strip()
    if base in _DAY_ALIASES:
        return _DAY_ALIASES[base]
    raise ValueError(f"unrecognized day: {day!r}")


@mcp.tool()
def list_weeks() -> list[dict]:
    """List every spreadsheet week with summary indicators.

    For each week (sheet "SEM N"): date range, number of logged sessions (actually
    trained) vs planned, total VTT (volume: reps × weight), total load in A.U.
    (RPE × time), average readiness and ``has_data``. Use it to discover which
    weeks have data before asking for details.
    """
    return sp.list_summary(sp.load_weeks())


@mcp.tool()
def get_week_summary(week: int) -> dict:
    """Summary of one week, with the per-day breakdown.

    Returns weekly VTT, weekly training load in A.U. (RPE × time), sessions
    done/planned, average readiness and, per day, VTT / A.U. / readiness and
    whether it was trained. ``week`` is the sheet number (1 = "SEM 1").
    """
    weeks = sp.load_weeks()
    return sp.week_summary(sp.find_week(weeks, week))


@mcp.tool()
def get_session(week: int, day: int | str) -> dict:
    """Details of one specific training session (a week + a day).

    ``day`` accepts a PT/EN day name ("sábado", "monday") or index 1–7 (1 = Monday).
    Returns date, exercises with sets (reps/weight/speed/VTT per set), session VTT,
    session RPE, duration, load in A.U. and the day's wellness
    (sleep/stress/fatigue/soreness + readiness).
    """
    weeks = sp.load_weeks()
    w = sp.find_week(weeks, week)
    session = w.sessions[_resolve_day(day)]
    out = asdict(session)
    out["week"] = w.week
    return out


@mcp.tool()
def get_exercise_history(exercise: str, weeks: list[int] | None = None) -> dict:
    """Progression of one exercise across weeks.

    Matches the name flexibly (ignores accents/case and tolerates the spreadsheet's
    typos, e.g. "agacamento"). For each week where the exercise shows up, returns
    max weight, total volume (VTT) and the sets. Optional ``weeks`` filters by week
    numbers. Use it to answer "am I progressing on X?".
    """
    all_weeks = sp.load_weeks()
    if weeks:
        wanted = set(weeks)
        all_weeks = [w for w in all_weeks if w.week in wanted]
    return sp.exercise_history(all_weeks, exercise)


@mcp.tool()
def get_recovery(date: str) -> dict:
    """One day of recovery data from the Amazfit GTR 4 via Apple Health.

    Returns resting HR (bpm), HRV SDNN (ms), respiratory rate and sleep (hours
    slept + deep/rem/core phases). ``date`` in YYYY-MM-DD. If there is no data
    for the date, returns ``found: false``.
    """
    r = rec.get_recovery(date)
    if r is None:
        return {"date": date, "found": False, "note": "no recovery data for this date"}
    out = asdict(r)
    out["found"] = True
    return out


@mcp.tool()
def get_recovery_range(start: str, end: str) -> list[dict]:
    """Recovery time series between two dates (YYYY-MM-DD), inclusive.

    Use it to watch resting HR / HRV / sleep trends across days and cross them
    with the spreadsheet's training load.
    """
    return [asdict(r) for r in rec.get_recovery_range(start, end)]


@mcp.tool()
def recovery_status() -> dict:
    """Diagnostics of the recovery source (Phase 0): how many days exist, the range,
    the most recent data point and the folder being read. Use it to confirm the
    Apple Health → Health Auto Export → Mac sync is working.
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
    """Week-by-week load progression + ACWR (overtraining risk).

    For each week: total VTT, total load in A.U., and ACWR = acute load (current
    week) divided by chronic (rolling mean over ``window`` weeks, incl. current).
    ``acwr_zone`` bands: <0.8 low load (detraining) · 0.8–1.3 optimal ·
    1.3–1.5 caution · >1.5 high risk. Spreadsheet-only (no watch needed).
    """
    return an.acwr_series(sp.load_weeks(), window=window)


@mcp.tool()
def compare_load_recovery(start: str, end: str) -> list[dict]:
    """Crosses training load (spreadsheet) with recovery (watch) by date — the project's core.

    For each day between ``start`` and ``end`` (YYYY-MM-DD): if trained, the A.U.
    load / VTT and the subjective readiness; plus the day's objective recovery
    (resting HR, HRV, sleep). Recovery-only days come with ``trained: false`` —
    good for seeing the response the day after a heavy session (resting HR ↑ /
    HRV ↓). ONE filled date per spreadsheet week is enough — the rest are inferred.
    """
    weeks = sp.load_weeks()
    recovery = rec.load_recovery()
    return an.compare_load_recovery(
        weeks, recovery, start=rec._parse_day(start), end=rec._parse_day(end)
    )


@mcp.tool()
def get_workouts(start: str, end: str, kind: str | None = None) -> list[dict]:
    """Watch workouts/activities (running, walking, cycling...) via Health Auto Export.

    For each workout between ``start`` and ``end`` (YYYY-MM-DD, inclusive):
    normalized kind (run/walk/ride/strength/swim/other), duration, distance (km),
    pace (min/km), avg/max HR, kcal and **TRIMP** (Banister's internal load —
    comparable to the spreadsheet's A.U. load). Optional ``kind`` filters by type
    (e.g. "run"). Requires Workouts enabled in the export.
    """
    return [asdict(w) for w in wk.get_workouts(start, end, kind)]


@mcp.tool()
def get_fitness_fatigue(ctl_days: int = 42, atl_days: int = 7) -> list[dict]:
    """Day-by-day Fitness/Fatigue/Form (CTL/ATL/TSB model, Garmin/TrainingPeaks-style).

    Daily load = spreadsheet A.U. + watch workout TRIMP. CTL = ``ctl_days``
    exponential average (fitness), ATL = ``atl_days`` (acute fatigue),
    TSB = yesterday's CTL − ATL (form: negative = accumulated fatigue, positive =
    fresh). Complements the weekly ACWR of ``get_training_load`` with daily resolution.
    """
    loads = mx.daily_load_series(sp.load_weeks(), wk.load_workouts())
    return mx.fitness_fatigue(loads, ctl_days=ctl_days, atl_days=atl_days)


@mcp.tool()
def get_trends(metric: str = "hrv_sdnn", baseline_days: int = 28) -> list[dict]:
    """Trend of a recovery metric against its own baseline.

    ``metric`` ∈ {"resting_hr", "hrv_sdnn", "sleep_h"}. For each day with data:
    value, baseline (mean of the prior ``baseline_days`` days) and z-score
    (deviations from normal — HRV below / resting HR above baseline = sign of
    incomplete recovery).
    """
    return mx.trend_series(rec.load_recovery(), metric, baseline_days=baseline_days)


def _daily_payloads(start: str | None, end: str | None) -> dict[str, dict]:
    """Assemble, per date, the session + recovery + workouts + form-metrics bundle."""
    weeks = sp.load_weeks()
    recovery = rec.load_recovery()
    sessions = obs.sessions_by_date(weeks)
    all_workouts = wk.load_workouts()
    workouts_by_day: dict[str, list] = {}
    for w in all_workouts:
        workouts_by_day.setdefault(w.date, []).append(w)

    ff = {r["date"]: r for r in mx.fitness_fatigue(mx.daily_load_series(weeks, all_workouts))}

    payloads: dict[str, dict] = {}
    for d in sorted(set(sessions) | set(recovery) | set(workouts_by_day)):
        if (start and d < start) or (end and d > end):
            continue
        metrics_d = None
        f = ff.get(d)
        if f:
            session = sessions.get(d)
            rs = mx.readiness_score(
                d, recovery, tsb=f["tsb"], subjective=session.readiness if session else None
            )
            metrics_d = {
                "ctl": f["ctl"], "atl": f["atl"], "tsb": f["tsb"],
                "readiness_score": rs.get("score"),
            }
        payloads[d] = {
            "session": sessions.get(d),
            "recovery": recovery.get(d),
            "workouts": workouts_by_day.get(d, ()),
            "metrics": metrics_d,
        }
    return payloads


@mcp.tool()
def get_readiness(date: str | None = None) -> dict:
    """Readiness to train (0–100) with a transparent per-component breakdown.

    Combines HRV and resting HR vs a 28-day baseline, sleep vs average, form (TSB)
    and the spreadsheet's subjective readiness — weights renormalized when data is
    missing. Returns the score, the zone (ready/ok/caution/rest) and each component
    with value and weight, so the "why" can be explained. ``date`` defaults to the
    most recent day with recovery data.
    """
    recovery = rec.load_recovery()
    day = (rec._parse_day(date) or date) if date else (
        max(recovery) if recovery else dt.date.today().isoformat()
    )
    weeks = sp.load_weeks()
    ff = {r["date"]: r for r in mx.fitness_fatigue(mx.daily_load_series(weeks, wk.load_workouts()))}
    session = obs.sessions_by_date(weeks).get(day)
    return mx.readiness_score(
        day,
        recovery,
        tsb=(ff.get(day) or {}).get("tsb"),
        subjective=session.readiness if session else None,
    )


@mcp.tool()
def daily_note(date: str) -> str:
    """Daily Markdown note (Obsidian format) for one day — writes nothing to disk.

    Joins strength training, watch activities, recovery and form (CTL/ATL/TSB,
    readiness) into a note with YAML frontmatter. Use ``export_obsidian`` to write
    into the vault.
    """
    d = rec._parse_day(date) or date
    p = _daily_payloads(d, d).get(d)
    if not p:
        return f"# {d}\n\nNo data for this day."
    return obs.render_daily_note(
        d, session=p["session"], recovery=p["recovery"],
        workouts=p["workouts"], metrics=p["metrics"],
    )


@mcp.tool()
def export_obsidian(start: str, end: str) -> dict:
    """Export daily Markdown notes to the Obsidian vault (one note per day with data).

    Writes ``YYYY-MM-DD.md`` into ``AMAZFIT_MCP_OBSIDIAN_DIR`` (YAML frontmatter
    ready for Dataview), overwriting idempotently and skipping empty days. Returns
    how many notes were written and where.
    """
    paths = obs.export_notes(_daily_payloads(rec._parse_day(start), rec._parse_day(end)))
    return {"written": len(paths), "files": paths, "dir": str(config.obsidian_dir())}


@mcp.tool()
def export_health_report(days: int = 30) -> dict:
    """Generate a self-contained HTML health report and write it to disk.

    One page with the latest recovery + readiness tiles, a CTL/ATL/TSB time-series
    chart over the last ``days`` days and the recent workouts table. Static SVG,
    no external assets — open in any browser or share as-is. Writes
    ``report-<date>.html`` into ``AMAZFIT_MCP_REPORT_DIR`` (default ``data/reports``)
    and returns the path.
    """
    weeks = sp.load_weeks()
    recovery = rec.load_recovery()
    all_workouts = wk.load_workouts()
    ff = mx.fitness_fatigue(mx.daily_load_series(weeks, all_workouts))
    form_series = ff[-days:] if days > 0 else ff
    latest_day = max(recovery) if recovery else None
    today = form_series[-1]["date"] if form_series else dt.date.today().isoformat()
    readiness = get_readiness(latest_day) if latest_day else {}
    html = rp.render_health_report(
        form_series,
        latest_recovery=recovery.get(latest_day) if latest_day else None,
        readiness=readiness,
        workouts=all_workouts[-10:],
        generated=today,
    )
    path = rp.export_report(html, date=today)
    return {"path": path, "days": len(form_series), "workouts": min(len(all_workouts), 10)}


def main() -> None:
    """Entry point (stdio). Registered as the ``amazfit-mcp`` script."""
    mcp.run()


if __name__ == "__main__":
    main()
