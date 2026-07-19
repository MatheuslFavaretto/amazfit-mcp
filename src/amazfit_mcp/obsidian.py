"""Daily Markdown note exporter for Obsidian.

Deterministic, day-centric notes (inspired by dimonier/amazfit-sync): one note per
day with a flat YAML frontmatter (queryable via Dataview) and sections for strength
training (spreadsheet), watch activities, recovery (Apple Health) and form (CTL/ATL/TSB).
Same input → same text; sections without data are omitted.

Workouts and metrics arrive as generic structures (dicts or objects) so this module
is not coupled to the modules that produce them — the server assembles the payload.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import config
from .analysis import _week_anchor
from .models import RecoveryDay, Session, Week

# workout kind -> emoji of the line in "## Activities"
_KIND_EMOJI = {
    "run": "🏃",
    "walk": "🚶",
    "ride": "🚴",
    "strength": "🏋️",
    "swim": "🏊",
    "other": "⏱️",
}


def _num(value) -> float | None:
    """Number or None (bool does not count as a number)."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _fmt(value) -> str:
    """Number with at most 1 decimal place, no scientific notation."""
    r = round(float(value), 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def _pace(min_per_km: float) -> str:
    """Pace in decimal min/km -> "M:SS" (6.5 -> "6:30")."""
    minutes = int(min_per_km)
    seconds = round((min_per_km - minutes) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d}"


def _wget(workout, key: str):
    """Field of a generic workout — accepts dict or object."""
    if isinstance(workout, dict):
        return workout.get(key)
    return getattr(workout, key, None)


def _frontmatter(date, session, recovery, workouts, metrics) -> list[str]:
    """Flat YAML keys — only included when there is data."""
    pairs: list[tuple[str, str]] = [("date", date), ("tags", "[amazfit-mcp]")]
    if session is not None:
        pairs.append(("trained", "true" if session.logged else "false"))
        if session.logged:
            if session.carga_ua is not None:
                pairs.append(("carga_ua", _fmt(session.carga_ua)))
            pairs.append(("vtt", _fmt(session.vtt_session)))
            if session.readiness is not None:
                pairs.append(("subjective_readiness", _fmt(session.readiness)))
    if recovery is not None:
        for key, val in (
            ("resting_hr", recovery.resting_hr),
            ("hrv_sdnn", recovery.hrv_sdnn),
            ("sleep_h", (recovery.sleep or {}).get("asleep_h")),
        ):
            if _num(val) is not None:
                pairs.append((key, _fmt(val)))
    trimps = [t for t in (_num(_wget(w, "trimp")) for w in workouts) if t is not None]
    if trimps:
        pairs.append(("trimp_total", _fmt(sum(trimps))))
    for key in ("ctl", "atl", "tsb", "readiness_score"):
        val = _num((metrics or {}).get(key))
        if val is not None:
            pairs.append((key, _fmt(val)))
    return ["---", *[f"{k}: {v}" for k, v in pairs], "---"]


def _section_strength(session) -> list[str]:
    lines: list[str] = ["", "## Strength training", ""]
    if session.pse is not None:
        lines.append(f"- RPE: {_fmt(session.pse)}")
    if session.tempo_min is not None:
        lines.append(f"- Duration: {_fmt(session.tempo_min)} min")
    if session.carga_ua is not None:
        lines.append(f"- Load: {_fmt(session.carga_ua)} A.U.")
    lines.append(f"- Session VTT: {_fmt(session.vtt_session)}")
    rows = []
    for ex in session.exercises:
        series = " · ".join(
            f"{_fmt(s.reps)}×{_fmt(s.peso)}"
            for s in ex.sets
            if s.reps is not None and s.peso is not None
        )
        if series:
            rows.append(f"| {ex.name} | {series} | {_fmt(ex.vtt)} |")
    if rows:
        lines += ["", "| Exercise | Sets (reps×weight) | VTT |", "| --- | --- | --- |", *rows]
    return lines


def _section_activities(workouts) -> list[str]:
    lines: list[str] = []
    for w in workouts:
        kind = str(_wget(w, "kind") or "other").lower()
        emoji = _KIND_EMOJI.get(kind, _KIND_EMOJI["other"])
        name = _wget(w, "name") or kind
        bits = []
        duration = _num(_wget(w, "duration_min"))
        if duration is not None:
            bits.append(f"{_fmt(duration)} min")
        distance = _num(_wget(w, "distance_km"))
        if distance is not None:
            bits.append(f"{_fmt(distance)} km")
        pace = _num(_wget(w, "pace_min_km"))
        if pace is not None:
            bits.append(f"{_pace(pace)} /km")
        avg_hr = _num(_wget(w, "avg_hr"))
        if avg_hr is not None:
            bits.append(f"HR {_fmt(avg_hr)} bpm")
        trimp = _num(_wget(w, "trimp"))
        if trimp is not None:
            bits.append(f"TRIMP {_fmt(trimp)}")
        suffix = f" — {' · '.join(bits)}" if bits else ""
        lines.append(f"- {emoji} {name}{suffix}")
    return ["", "## Activities", "", *lines] if lines else []


def _section_recovery(recovery: RecoveryDay) -> list[str]:
    lines: list[str] = []
    if recovery.resting_hr is not None:
        lines.append(f"- Resting HR: {_fmt(recovery.resting_hr)} bpm")
    if recovery.hr_avg is not None:
        lines.append(f"- Avg HR: {_fmt(recovery.hr_avg)} bpm")
    if recovery.hrv_sdnn is not None:
        lines.append(f"- HRV (SDNN): {_fmt(recovery.hrv_sdnn)} ms")
    if recovery.respiratory_rate is not None:
        lines.append(f"- Respiration: {_fmt(recovery.respiratory_rate)} breaths/min")
    sleep = recovery.sleep or {}
    asleep = _num(sleep.get("asleep_h"))
    if asleep is not None:
        phases = " · ".join(
            f"{label} {_fmt(sleep[key])}"
            for label, key in (("deep", "deep_h"), ("rem", "rem_h"), ("core", "core_h"))
            if _num(sleep.get(key)) is not None
        )
        lines.append(f"- Sleep: {_fmt(asleep)} h" + (f" ({phases})" if phases else ""))
    return ["", "## Recovery", "", *lines] if lines else []


def _section_form(metrics: dict) -> list[str]:
    vals = {k: _num(metrics.get(k)) for k in ("ctl", "atl", "tsb", "readiness_score")}
    if all(v is None for v in vals.values()):
        return []
    bits = [
        f"{label} {_fmt(vals[key])}"
        for label, key in (
            ("CTL", "ctl"), ("ATL", "atl"), ("TSB", "tsb"), ("Readiness", "readiness_score"),
        )
        if vals[key] is not None
    ]
    lines = ["", "## Form", "", f"- {' · '.join(bits)}"]
    tsb = vals["tsb"]
    if tsb is not None:
        interp = "accumulated fatigue" if tsb < -10 else ("fresh" if tsb > 5 else "neutral")
        lines.append(f"- Interpretation: {interp}")
    return lines


def render_daily_note(
    date: str,
    session: Session | None = None,
    recovery: RecoveryDay | None = None,
    workouts=(),
    metrics: dict | None = None,
) -> str:
    """Render the daily Markdown note for a day. Deterministic: same input, same text.

    Sections without data are omitted; the frontmatter only carries keys with values.
    ``workouts`` accepts dicts or objects with date/name/kind/duration_min/distance_km/
    pace_min_km/avg_hr/trimp; ``metrics`` is an optional dict {ctl, atl, tsb, readiness_score}.
    """
    workouts = list(workouts or ())
    parts = _frontmatter(date, session, recovery, workouts, metrics)
    parts += ["", f"# {date}"]
    if session is not None and session.logged:
        parts += _section_strength(session)
    parts += _section_activities(workouts)
    if recovery is not None:
        parts += _section_recovery(recovery)
    if metrics:
        parts += _section_form(metrics)
    return "\n".join(parts) + "\n"


def sessions_by_date(weeks: list[Week]) -> dict[str, Session]:
    """Logged sessions keyed by ISO date — same pattern as ``analysis.compare_load_recovery``.

    Days without a filled DATE cell get a date inferred from the week anchor (Monday),
    since a spreadsheet week is a consecutive Monday→Sunday block.
    """
    out: dict[str, Session] = {}
    for w in weeks:
        anchor = _week_anchor(w)
        for s in w.sessions:
            if not s.logged:
                continue
            day = s.date
            if not day and anchor is not None:
                day = (anchor + dt.timedelta(days=s.day_index)).isoformat()
            if day:
                out[day] = s
    return out


def export_notes(dates_payload: dict[str, dict], directory=None) -> list[str]:
    """Write one ``<date>.md`` per day into ``directory`` (default ``config.obsidian_dir()``).

    ``dates_payload`` = {date: {"session","recovery","workouts","metrics"}} assembled
    by the server. Dates whose payload produces no section (an "empty" note, title
    only) are skipped. Overwrites idempotently; returns the list of written paths.
    """
    directory = Path(directory) if directory is not None else config.obsidian_dir()
    directory.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for date in sorted(dates_payload):
        payload = dates_payload[date] or {}
        note = render_daily_note(
            date,
            session=payload.get("session"),
            recovery=payload.get("recovery"),
            workouts=payload.get("workouts") or (),
            metrics=payload.get("metrics"),
        )
        if "\n## " not in note:  # empty note (frontmatter + title only) -> skip
            continue
        path = directory / f"{date}.md"
        path.write_text(note, encoding="utf-8")
        written.append(str(path))
    return written
