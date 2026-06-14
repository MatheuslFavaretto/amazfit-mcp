"""Leitura do store de recuperação (Amazfit GTR 4 via Apple Health).

Fonte (Fase 2): o app iOS **Health Auto Export** escreve JSON do Apple Health numa pasta
(iCloud Drive ou local). Este módulo só LÊ esses arquivos e normaliza por data — a extração
fica fora do MCP (desacoplado, estilo SRE: a ingestão é o app; aqui é só a query).

Formato do Health Auto Export (verificado na wiki oficial):
    { "data": { "metrics": [ {"name","units","data":[...]} , ... ] } }
  - métricas de quantidade (resting_heart_rate, heart_rate_variability, respiratory_rate):
      cada ponto = {"qty": <num>, "date": "yyyy-MM-dd HH:mm:ss Z"}
  - sleep_analysis: cada ponto = {"date":"yyyy-MM-dd","asleep","deep","rem","core","inBed",
      "totalSleep","sleepStart","sleepEnd"}  (durações em horas)
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from . import config
from .models import RecoveryDay

# nome no Health Auto Export -> campo no RecoveryDay
QUANTITY_METRICS = {
    "resting_heart_rate": "resting_hr",
    "heart_rate_variability": "hrv_sdnn",
    "respiratory_rate": "respiratory_rate",
}
SLEEP_METRIC = "sleep_analysis"

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_day(value) -> str | None:
    """Qualquer formato de data do export -> dia ISO 'YYYY-MM-DD'."""
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
    """Lê todos os JSON da pasta e devolve {dia ISO: RecoveryDay}."""
    directory = Path(directory) if directory else config.recovery_dir()
    if not directory.exists():
        return {}

    quantities: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    sleep_by_day: dict[str, dict] = {}

    for metric in _iter_metrics(directory):
        name = metric.get("name")
        points = metric.get("data") or []
        if name in QUANTITY_METRICS:
            field = QUANTITY_METRICS[name]
            for pt in points:
                day = _parse_day(pt.get("date"))
                qty = _num(pt.get("qty"))
                if day and qty is not None:
                    quantities[day][field].append(qty)
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
            hrv_sdnn=avg(day, "hrv_sdnn"),
            respiratory_rate=avg(day, "respiratory_rate"),
            sleep=sleep_by_day.get(day),
        )
    return out


def get_recovery(date: str, directory: str | Path | None = None) -> RecoveryDay | None:
    return load_recovery(directory).get(_parse_day(date))


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
