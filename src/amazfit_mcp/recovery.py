"""Recovery store reader (Amazfit GTR 4 via Apple Health).

Source (Phase 2): the iOS app **Health Auto Export** writes Apple Health JSON into a
folder (iCloud Drive or local). This module only READS those files and normalizes
them by date — extraction stays outside the MCP (decoupled, SRE-style: ingestion is
the app's job; here it is query only).

Health Auto Export format (verified against the official wiki):
    { "data": { "metrics": [ {"name","units","data":[...]} , ... ] } }
  - quantity metrics (resting_heart_rate, heart_rate_variability, respiratory_rate):
      each point = {"qty": <num>, "date": "yyyy-MM-dd HH:mm:ss Z"}
  - sleep_analysis: each point = {"date":"yyyy-MM-dd","asleep","deep","rem","core","inBed",
      "totalSleep","sleepStart","sleepEnd"}  (durations in hours)
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from . import config
from .models import RecoveryDay

# Health Auto Export name -> (RecoveryDay field, value keys to try in order)
# heart_rate (day's average HR) comes aggregated as Min/Avg/Max; the rest come as qty.
QUANTITY_METRICS = {
    "resting_heart_rate": ("resting_hr", ("qty",)),
    "heart_rate": ("hr_avg", ("Avg", "avg", "qty")),
    "heart_rate_variability": ("hrv_sdnn", ("qty",)),
    "respiratory_rate": ("respiratory_rate", ("qty",)),
}
SLEEP_METRIC = "sleep_analysis"

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_day(value) -> str | None:
    """Any export date format -> ISO day 'YYYY-MM-DD'."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s[:10] if len(s) >= 10 else None


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _iter_metrics(directory: Path):
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        yield from ((doc.get("data") or {}).get("metrics") or [])


def load_recovery(directory: str | Path | None = None) -> dict[str, RecoveryDay]:
    """Read every JSON in the folder and return {ISO day: RecoveryDay}."""
    directory = Path(directory) if directory else config.recovery_dir()
    if not directory.exists():
        return {}

    quantities: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    sleep_by_day: dict[str, dict] = {}

    for metric in _iter_metrics(directory):
        name = metric.get("name")
        points = metric.get("data") or []
        if name in QUANTITY_METRICS:
            field, value_keys = QUANTITY_METRICS[name]
            for pt in points:
                day = _parse_day(pt.get("date"))
                val = None
                for key in value_keys:
                    val = _num(pt.get(key))
                    if val is not None:
                        break
                if day and val is not None:
                    quantities[day][field].append(val)
        elif name == SLEEP_METRIC:
            for pt in points:
                day = _parse_day(pt.get("date"))
                if not day:
                    continue
                asleep = _num(pt.get("asleep"))
                sleep_by_day[day] = {
                    "asleep_h": asleep if asleep is not None else _num(pt.get("totalSleep")),
                    "deep_h": _num(pt.get("deep")),
                    "rem_h": _num(pt.get("rem")),
                    "core_h": _num(pt.get("core")),
                    "in_bed_h": _num(pt.get("inBed")),
                    "start": pt.get("sleepStart"),
                    "end": pt.get("sleepEnd"),
                }

    def avg(day: str, field: str) -> float | None:
        vals = quantities.get(day, {}).get(field)
        return round(sum(vals) / len(vals), 1) if vals else None

    out: dict[str, RecoveryDay] = {}
    for day in sorted(set(quantities) | set(sleep_by_day)):
        out[day] = RecoveryDay(
            date=day,
            resting_hr=avg(day, "resting_hr"),
            hr_avg=avg(day, "hr_avg"),
            hrv_sdnn=avg(day, "hrv_sdnn"),
            respiratory_rate=avg(day, "respiratory_rate"),
            sleep=sleep_by_day.get(day),
        )
    return out


def get_recovery(date: str, directory: str | Path | None = None) -> RecoveryDay | None:
    day = _parse_day(date)
    return load_recovery(directory).get(day) if day else None


def get_recovery_range(
    start: str, end: str, directory: str | Path | None = None
) -> list[RecoveryDay]:
    s, e = _parse_day(start), _parse_day(end)
    recs = load_recovery(directory)
    return [
        recs[d]
        for d in sorted(recs)
        if (s is None or d >= s) and (e is None or d <= e)
    ]
