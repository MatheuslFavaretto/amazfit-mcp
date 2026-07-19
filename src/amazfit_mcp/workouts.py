"""Reading workouts (running/activities) from Health Auto Export (Apple Health).

Same source as recovery: the iOS **Health Auto Export** app drops JSON into a folder
(``config.recovery_dir()``) and this module only READS and normalizes — ingestion
happens in the app.

Health Auto Export format:
    { "data": { "workouts": [ {...}, ... ] } }
  The fields of each workout vary by app version, so parsing is defensive and
  tries multiple keys:
  - name: ``name`` / ``workoutName``
  - start/end: ``start`` / ``end`` ("yyyy-MM-dd HH:mm:ss Z" and variants)
  - ``duration``: if the number is > 1000 we assume SECONDS (newer exports),
    otherwise MINUTES (older exports) — heuristic: real workouts rarely exceed
    1000 minutes (~16h), so values above that only make sense in seconds
  - ``distance``: {"qty","units"} or plain number (assumes km); mi -> km
  - active energy: ``activeEnergyBurned`` / ``activeEnergy`` ({"qty"} in kcal)
  - avg/max HR: ``avgHeartRate``/``heartRateAvg`` and ``maxHeartRate``/``heartRateMax``
    (plain number or {"qty": ...})

Banister TRIMP per workout: ``trimp = dur_min * HRr * 0.64 * exp(1.92 * HRr)``,
with ``HRr = (avg_hr - hr_rest) / (hr_max - hr_rest)`` clamped to [0, 1] and
hr_rest/hr_max coming from ``config.hr_bounds()``. No avg HR (or duration) -> None.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path

from . import config
from .recovery import _num, _parse_day

_DT_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

# substring (lowercase) in the workout name -> normalized kind
_KIND_PATTERNS = (
    ("run", "run"),          # "Running", "Outdoor Run", "Indoor Run"
    ("walk", "walk"),        # "Walking", "Outdoor Walk"
    ("cycl", "ride"),        # "Cycling"
    ("ride", "ride"),        # "Outdoor Ride"
    ("bike", "ride"),
    ("strength", "strength"),  # "Strength Training", "Traditional Strength Training"
    ("weight", "strength"),
    ("swim", "swim"),        # "Swimming", "Pool Swim"
)

_MI_TO_KM = 1.609344


@dataclass
class Workout:
    """A workout/activity from the watch, normalized."""

    date: str                     # ISO "YYYY-MM-DD" (day of the start)
    start: str | None             # ISO datetime of the start (or None)
    end: str | None               # ISO datetime of the end (or None)
    name: str                     # raw name from the export ("Outdoor Run", ...)
    kind: str                     # "run"|"walk"|"ride"|"strength"|"swim"|"other"
    duration_min: float | None    # duration in minutes
    distance_km: float | None     # distance in km (mi converted)
    pace_min_km: float | None     # duration_min / distance_km; None without distance
    avg_hr: float | None          # average HR (bpm)
    max_hr: float | None          # max HR (bpm)
    kcal: float | None            # active energy (kcal)
    trimp: float | None           # Banister TRIMP; None without avg HR


def _parse_dt(value) -> dt.datetime | None:
    """Any datetime format from the export -> ``datetime`` (or None)."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in _DT_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _qty(value) -> float | None:
    """Plain number or dict {"qty": <num>, ...} -> float."""
    if isinstance(value, dict):
        value = value.get("qty")
    return _num(value)


def _first_qty(raw: dict, keys: tuple[str, ...]) -> float | None:
    """First numeric value found among the candidate keys."""
    for key in keys:
        val = _qty(raw.get(key))
        if val is not None:
            return val
    return None


def _kind(name: str) -> str:
    low = name.lower()
    for sub, kind in _KIND_PATTERNS:
        if sub in low:
            return kind
    return "other"


def _duration_min(raw: dict, start: dt.datetime | None, end: dt.datetime | None) -> float | None:
    """Duration in minutes. Heuristic: ``duration`` > 1000 is seconds, else minutes.

    Without ``duration``, falls back to the ``end - start`` delta when both exist.
    """
    val = _qty(raw.get("duration"))
    if val is not None:
        return round(val / 60.0, 1) if val > 1000 else round(val, 1)
    if start and end:
        try:
            return round((end - start).total_seconds() / 60.0, 1)
        except TypeError:  # aware vs naive: cannot subtract
            return None
    return None


def _distance_km(value) -> float | None:
    """{"qty","units"} or plain number -> km (mi and m converted)."""
    if isinstance(value, dict):
        qty = _num(value.get("qty"))
        units = str(value.get("units") or "km").strip().lower()
    else:
        qty, units = _num(value), "km"
    if qty is None:
        return None
    if units in ("mi", "mile", "miles"):
        qty *= _MI_TO_KM
    elif units in ("m", "meter", "meters"):
        qty /= 1000.0
    return round(qty, 3)


def _trimp(duration_min: float | None, avg_hr: float | None) -> float | None:
    """Banister TRIMP; None without duration or avg HR."""
    if duration_min is None or avg_hr is None:
        return None
    hr_rest, hr_max = config.hr_bounds()
    span = hr_max - hr_rest
    if span <= 0:
        return None
    hrr = min(1.0, max(0.0, (avg_hr - hr_rest) / span))
    return round(duration_min * hrr * 0.64 * math.exp(1.92 * hrr), 1)


def _parse_workout(raw: dict) -> Workout | None:
    name = str(raw.get("name") or raw.get("workoutName") or "Unknown")
    start_dt = _parse_dt(raw.get("start"))
    end_dt = _parse_dt(raw.get("end"))
    date = _parse_day(raw.get("start")) or _parse_day(raw.get("date")) or _parse_day(raw.get("end"))
    if not date:
        return None

    duration_min = _duration_min(raw, start_dt, end_dt)
    distance_km = _distance_km(raw.get("distance"))
    avg_hr = _first_qty(raw, ("avgHeartRate", "heartRateAvg", "averageHeartRate"))
    max_hr = _first_qty(raw, ("maxHeartRate", "heartRateMax"))
    pace = (
        round(duration_min / distance_km, 2)
        if duration_min is not None and distance_km
        else None
    )
    return Workout(
        date=date,
        start=start_dt.isoformat() if start_dt else None,
        end=end_dt.isoformat() if end_dt else None,
        name=name,
        kind=_kind(name),
        duration_min=duration_min,
        distance_km=distance_km,
        pace_min_km=pace,
        avg_hr=avg_hr,
        max_hr=max_hr,
        kcal=_first_qty(raw, ("activeEnergyBurned", "activeEnergy")),
        trimp=_trimp(duration_min, avg_hr),
    )


def load_workouts(directory: str | Path | None = None) -> list[Workout]:
    """Reads every JSON in the folder and returns workouts sorted by start."""
    directory = Path(directory) if directory else config.recovery_dir()
    if not directory.exists():
        return []

    out: list[Workout] = []
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        for raw in (doc.get("data") or {}).get("workouts") or []:
            if isinstance(raw, dict):
                workout = _parse_workout(raw)
                if workout:
                    out.append(workout)
    out.sort(key=lambda w: (w.date, w.start or ""))
    return out


def get_workouts(
    start: str,
    end: str,
    kind: str | None = None,
    directory: str | Path | None = None,
) -> list[Workout]:
    """Workouts between ``start`` and ``end`` (ISO, inclusive), optionally by kind."""
    s, e = _parse_day(start), _parse_day(end)
    kind = kind.strip().lower() if kind else None
    return [
        w
        for w in load_workouts(directory)
        if (s is None or w.date >= s)
        and (e is None or w.date <= e)
        and (kind is None or w.kind == kind)
    ]
