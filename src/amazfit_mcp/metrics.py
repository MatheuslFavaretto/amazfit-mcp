"""Garmin/TrainingPeaks-style longitudinal metrics (pure functions, no I/O).

Three blocks:
- **Daily load**: sums spreadsheet A.U. (RPE × time) + workout TRIMP per date.
- **CTL/ATL/TSB** (Banister/Coggan): EWMA of the daily load. CTL ~ fitness (42d),
  ATL ~ fatigue (7d), TSB ~ form (YESTERDAY's fitness − fatigue).
- **Trends + readiness**: baseline/z-score of the recovery metrics and a transparent
  0–100 score with a per-component breakdown (Claude explains on top of it).
"""

from __future__ import annotations

import datetime as dt
from statistics import mean, pstdev

from .analysis import _week_anchor
from .models import RecoveryDay, Week

# ------------------------------------------------------------------ daily load


def _field(obj, key):
    """Attribute-or-key access: takes dataclasses/objects or dicts (generic workouts)."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def daily_load_series(weeks: list[Week], workouts=()) -> list[dict]:
    """Daily load in A.U.: ``logged`` spreadsheet sessions + workout ``trimp``.

    A session's date comes from the DATE cell or is inferred from the week anchor
    (same pattern as ``analysis.compare_load_recovery``). Workouts are objects or
    dicts with ``date`` (ISO) and ``trimp``. Only days with load are returned.
    """
    by_day: dict[str, dict] = {}

    def add(day: str, amount: float, source: str) -> None:
        row = by_day.setdefault(day, {"load": 0.0, "sources": []})
        row["load"] += amount
        if source not in row["sources"]:
            row["sources"].append(source)

    for w in weeks:
        anchor = _week_anchor(w)
        for s in w.sessions:
            if not s.logged or not s.carga_ua:
                continue
            day = s.date
            if not day and anchor is not None:
                day = (anchor + dt.timedelta(days=s.day_index)).isoformat()
            if day:
                add(day, s.carga_ua, "spreadsheet")

    for wo in workouts:
        day, trimp = _field(wo, "date"), _field(wo, "trimp")
        if day and trimp:
            add(str(day)[:10], float(trimp), "workout")

    return [
        {"date": d, "load": round(row["load"], 1), "sources": row["sources"]}
        for d, row in sorted(by_day.items())
        if row["load"] > 0
    ]


# -------------------------------------------------------------- fitness/fatigue


def fitness_fatigue(
    daily_loads: list[dict],
    ctl_days: int = 42,
    atl_days: int = 7,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """CTL/ATL/TSB per day (Banister model in Coggan's EWMA form).

    The series is CONTINUOUS from first to last day: rest days enter with load 0
    (that is what makes CTL/ATL decay on rest). Recursions::

        CTL_t = CTL_{t-1} + (load_t − CTL_{t-1}) / ctl_days
        ATL_t = ATL_{t-1} + (load_t − ATL_{t-1}) / atl_days
        TSB_t = CTL_{t-1} − ATL_{t-1}   # TODAY's form = YESTERDAY's fitness/fatigue

    ``daily_loads`` is the output of ``daily_load_series`` (or any list of
    dicts/objects with ``date`` and ``load``). Initial state CTL=ATL=0 — the first
    ~ctl_days are the model's warm-up ramp.
    """
    loads: dict[str, float] = {}
    for row in daily_loads:
        day = _field(row, "date")
        if day:
            loads[str(day)[:10]] = float(_field(row, "load") or 0.0)

    first = start or (min(loads) if loads else None)
    last = end or (max(loads) if loads else None)
    if first is None or last is None:
        return []

    ctl = atl = 0.0
    out: list[dict] = []
    day = dt.date.fromisoformat(first)
    stop = dt.date.fromisoformat(last)
    while day <= stop:
        iso = day.isoformat()
        load = loads.get(iso, 0.0)
        tsb = ctl - atl  # before updating: yesterday's values
        ctl += (load - ctl) / ctl_days
        atl += (load - atl) / atl_days
        out.append(
            {
                "date": iso,
                "load": round(load, 1),
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(tsb, 1),
            }
        )
        day += dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------- trends

_METRIC_GETTERS = {
    "resting_hr": lambda r: r.resting_hr,
    "hrv_sdnn": lambda r: r.hrv_sdnn,
    "sleep_h": lambda r: (r.sleep or {}).get("asleep_h"),
}

_MIN_BASELINE_DAYS = 5  # below this the z-score is not reliable


def trend_series(
    recovery: dict[str, RecoveryDay], metric: str, baseline_days: int = 28
) -> list[dict]:
    """Daily value + baseline (mean of PRIOR days in the window) + std + z-score.

    ``metric`` ∈ {"resting_hr", "hrv_sdnn", "sleep_h"}. A day's baseline only uses
    prior days within ``baseline_days`` (the day itself is excluded — otherwise
    today's deviation would contaminate the ruler). ``z`` is None with <5 baseline
    days or std 0.
    """
    if metric not in _METRIC_GETTERS:
        raise ValueError(f"unknown metric: {metric!r} (use {sorted(_METRIC_GETTERS)})")
    get = _METRIC_GETTERS[metric]

    points = [(d, v) for d in sorted(recovery) if (v := get(recovery[d])) is not None]
    out: list[dict] = []
    for i, (day, value) in enumerate(points):
        window_start = (dt.date.fromisoformat(day) - dt.timedelta(days=baseline_days)).isoformat()
        prior = [pv for pd, pv in points[:i] if pd >= window_start]
        baseline = mean(prior) if prior else None
        std = pstdev(prior) if len(prior) >= 2 else None
        z = None
        if len(prior) >= _MIN_BASELINE_DAYS and std:
            z = round((value - baseline) / std, 2)
        out.append(
            {
                "date": day,
                "value": value,
                "baseline": round(baseline, 2) if baseline is not None else None,
                "std": round(std, 2) if std is not None else None,
                "z": z,
            }
        )
    return out


# ------------------------------------------------------------------- readiness

# weight per component — renormalized when data is missing
_WEIGHTS = {"hrv": 30, "rhr": 25, "sleep": 20, "tsb": 15, "subjective": 10}


def _clamp(x: float) -> float:
    return round(min(100.0, max(0.0, x)), 1)


def zone(score: float | None) -> str:
    """Qualitative readiness band: ready / ok / caution / rest."""
    if score is None:
        return "no data"
    if score >= 75:
        return "ready"
    if score >= 50:
        return "ok"
    if score >= 25:
        return "caution"
    return "rest"


def readiness_score(
    date: str,
    recovery: dict[str, RecoveryDay],
    tsb: float | None = None,
    subjective: float | None = None,
) -> dict:
    """0–100 readiness score with a transparent per-component breakdown.

    Components (each becomes 0–100; missing ones are skipped and weights renormalized):
    - **hrv** (30): HRV z-score vs baseline — z=+1 is good → ``50 + 25·z``.
    - **rhr** (25): resting-HR z-score INVERTED — z=+1 is bad → ``50 − 25·z``.
    - **sleep** (20): hours slept vs baseline → ``100·value/baseline`` (capped at 100).
    - **tsb** (15): form from the CTL/ATL model, mapped from [−30, +15] → 0–100.
    - **subjective** (10): 0–5 spreadsheet readiness → ``value·20``.

    Final score = rounded weighted mean. With NO component at all → score None.
    """
    components: dict[str, dict] = {}

    def trend_at(metric: str) -> dict | None:
        for row in trend_series(recovery, metric):
            if row["date"] == date:
                return row
        return None

    hrv = trend_at("hrv_sdnn")
    if hrv and hrv["z"] is not None:
        components["hrv"] = {"value": hrv["z"], "score": _clamp(50 + 25 * hrv["z"])}
    rhr = trend_at("resting_hr")
    if rhr and rhr["z"] is not None:
        components["rhr"] = {"value": rhr["z"], "score": _clamp(50 - 25 * rhr["z"])}
    sleep = trend_at("sleep_h")
    if sleep and sleep["baseline"]:
        components["sleep"] = {
            "value": sleep["value"],
            "score": _clamp(100 * sleep["value"] / sleep["baseline"]),
        }
    if tsb is not None:
        components["tsb"] = {"value": tsb, "score": _clamp((tsb + 30) / 45 * 100)}
    if subjective is not None:
        components["subjective"] = {"value": subjective, "score": _clamp(subjective * 20)}

    for name, comp in components.items():
        comp["weight"] = _WEIGHTS[name]

    if not components:
        return {
            "date": date,
            "score": None,
            "components": {},
            "note": "no data: no component available for this day (HRV/RHR need "
            f"≥{_MIN_BASELINE_DAYS} baseline days; sleep needs a baseline; "
            "tsb/subjective were not provided)",
        }

    total_w = sum(c["weight"] for c in components.values())
    score = round(sum(c["score"] * c["weight"] for c in components.values()) / total_w)
    return {
        "date": date,
        "score": score,
        "zone": zone(score),
        "components": components,
        "note": f"{len(components)} of {len(_WEIGHTS)} components with data; "
        f"weights renormalized over {total_w}/100",
    }
