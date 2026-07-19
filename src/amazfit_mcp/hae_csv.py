"""Extractor: Health Auto Export **CSV dump** -> store JSON (zero reader changes).

The Health Auto Export iPhone app can export everything as a folder of CSVs (one
aggregate daily-metrics file plus one Workouts file) instead of the daily JSON
automation the store expects. This module converts that dump into a single
Health Auto Export-shaped JSON — ``{"data": {"metrics": [...], "workouts": [...]}}``
— written into the store folder, so ``recovery.py`` and ``workouts.py`` read it
with zero changes. Same pattern as ``zepp_cloud.py``: extraction is a stdlib CLI,
the MCP stays read-only.

Column headers are localized by the phone's language; matching is done on
normalized text (lowercase, accent-stripped) with PT + EN aliases.

Usage:
    python -m amazfit_mcp.hae_csv <export_dir> [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import config
from .cellmap import normalize

_KJ_TO_KCAL = 1 / 4.184

# metric name in the store JSON -> (value key, normalized-header aliases)
_DAILY_COLUMNS = {
    "resting_heart_rate": ("qty", ("frequencia cardiaca em repouso", "resting heart rate")),
    "heart_rate": ("Avg", ("frequencia cardiaca [media]", "heart rate [avg]")),
    "heart_rate_variability": (
        "qty", ("variabilidade da frequencia cardiaca", "heart rate variability")
    ),
    "respiratory_rate": ("qty", ("taxa respiratoria", "respiratory rate")),
}

# sleep_analysis point key -> normalized aliases of the phase inside "[...]"
_SLEEP_PHASES = {
    "asleep": ("adormecido", "asleep"),
    "totalSleep": ("total",),
    "deep": ("profundo", "deep"),
    "rem": ("rem",),
    "core": ("nucleo", "core"),
    "inBed": ("na cama", "in bed"),
}
_SLEEP_MARKERS = ("analise do sono [", "sleep analysis [")
_DATE_HEADERS = ("data/hora", "date/time", "date")

# workout CSV column -> normalized-header aliases (units live in the header)
_WORKOUT_COLUMNS = {
    "distance": ("distancia", "distance"),
    "avg_hr": ("freq. cardiaca media", "cardiaca media", "avg. heart rate", "avg heart rate"),
    "max_hr": ("freq. cardiaca maxima", "cardiaca maxima", "max. heart rate", "max heart rate"),
    "energy": ("energia ativa", "active energy"),
}

# localized workout type -> name whose substring workouts._kind() recognizes
_WORKOUT_NAMES = {
    "correr": "Outdoor Run",
    "interno correr": "Indoor Run",
    "caminhada": "Outdoor Walk",
    "ciclismo": "Outdoor Cycling",
    "interno ciclismo": "Indoor Cycling",
    "treinamento de forca funcional": "Functional Strength Training",
    "treinamento de forca tradicional": "Traditional Strength Training",
    "natacao": "Pool Swim",
}


def _num(value: object) -> float | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_column(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    """First header whose normalized text contains one of the aliases."""
    for h in headers:
        n = normalize(h)
        if any(a in n for a in aliases):
            return h
    return None


def convert_daily(path: Path) -> list[dict]:
    """Aggregate daily-metrics CSV -> Health Auto Export ``metrics`` list."""
    with open(path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        date_col = _find_column(headers, _DATE_HEADERS)
        if date_col is None:
            return []
        quantity_cols = {
            name: (col, key)
            for name, (key, aliases) in _DAILY_COLUMNS.items()
            if (col := _find_column(headers, aliases)) is not None
        }
        sleep_cols = {
            point_key: col
            for point_key, phases in _SLEEP_PHASES.items()
            if (col := _find_column(
                headers,
                tuple(f"{m}{p}]" for m in _SLEEP_MARKERS for p in phases),
            )) is not None
        }

        metrics: dict[str, list[dict]] = {name: [] for name in quantity_cols}
        sleep_points: list[dict] = []
        for row in reader:
            day = str(row.get(date_col) or "")[:10]
            if not day:
                continue
            for name, (col, key) in quantity_cols.items():
                val = _num(row.get(col))
                if val is not None:
                    metrics[name].append({key: val, "date": f"{day} 00:00:00"})
            sleep = {k: _num(row.get(col)) for k, col in sleep_cols.items()}
            if any(v is not None for v in sleep.values()):
                sleep_points.append({"date": day, **sleep})

    out = [{"name": n, "units": "", "data": pts} for n, pts in metrics.items() if pts]
    if sleep_points:
        out.append({"name": "sleep_analysis", "units": "hr", "data": sleep_points})
    return out


def _duration_min(value: object) -> float | None:
    """"HH:MM:SS" -> minutes (kept under 1000 so workouts.py reads it as minutes)."""
    try:
        h, m, s = (int(x) for x in str(value).strip().split(":"))
    except ValueError:
        return None
    return round(h * 60 + m + s / 60.0, 1)


def _with_seconds(value: object) -> str:
    """"YYYY-MM-DD HH:MM" -> "YYYY-MM-DD HH:MM:SS" (formats workouts.py parses)."""
    s = str(value or "").strip()
    return f"{s}:00" if len(s) == 16 else s


def convert_workouts(path: Path) -> list[dict]:
    """Workouts CSV -> Health Auto Export ``workouts`` list (kcal, km, minutes)."""
    with open(path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        cols = {
            field: col
            for field, aliases in _WORKOUT_COLUMNS.items()
            if (col := _find_column(headers, aliases)) is not None
        }
        energy_in_kj = "(kj)" in normalize(cols.get("energy", ""))

        out: list[dict] = []
        for row in reader:
            typ = str(row.get("Workout Type") or "").strip()
            start = _with_seconds(row.get("Start"))
            if not typ or not start:
                continue
            energy = _num(row.get(cols["energy"])) if "energy" in cols else None
            if energy is not None and energy_in_kj:
                energy = round(energy * _KJ_TO_KCAL, 1)
            workout: dict = {
                "name": _WORKOUT_NAMES.get(normalize(typ), typ),
                "start": start,
                "end": _with_seconds(row.get("End")),
                "duration": _duration_min(row.get("Duration")),
                "activeEnergy": energy,
            }
            if "distance" in cols:
                workout["distance"] = {"qty": _num(row.get(cols["distance"])), "units": "km"}
            if "avg_hr" in cols:
                workout["avgHeartRate"] = _num(row.get(cols["avg_hr"]))
            if "max_hr" in cols:
                workout["maxHeartRate"] = _num(row.get(cols["max_hr"]))
            out.append(workout)
    return out


def convert_dump(export_dir: Path, out_dir: Path | None = None) -> Path:
    """Convert a Health Auto Export CSV dump folder into one store JSON.

    Looks for ``HealthAutoExport-*.csv`` (daily metrics) and ``Workouts-*.csv``
    inside ``export_dir``; either may be absent. Writes ``csv-<dump name>.json``
    into ``out_dir`` (default: the recovery store) and returns the path.
    """
    export_dir = Path(export_dir)
    daily = sorted(export_dir.glob("HealthAutoExport-*.csv"))
    workouts = sorted(export_dir.glob("Workouts-*.csv"))
    if not daily and not workouts:
        raise FileNotFoundError(
            f"no HealthAutoExport-*.csv or Workouts-*.csv in {export_dir}"
        )
    doc = {
        "data": {
            "metrics": convert_daily(daily[-1]) if daily else [],
            "workouts": convert_workouts(workouts[-1]) if workouts else [],
        }
    }
    out_dir = Path(out_dir) if out_dir is not None else config.recovery_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"csv-{export_dir.name or 'dump'}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Health Auto Export CSV dump into the amazfit-mcp store."
    )
    parser.add_argument("export_dir", help="folder with the HealthAutoExport CSV dump")
    parser.add_argument("--out", default=None, help="output folder (default: the store)")
    args = parser.parse_args(argv)
    try:
        path = convert_dump(Path(args.export_dir).expanduser(), args.out)
    except (FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
