"""Return-value data structures (serializable via ``dataclasses.asdict``).

Field names mirror the spreadsheet's domain vocabulary on purpose (PSE = session
RPE, peso = weight, VTT = volume total, carga_ua = load in arbitrary units) — they
are part of the tool API surface and stay stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SetEntry:
    serie: int
    reps: float | None
    peso: float | None   # weight (kg)
    veloc: float | None  # bar speed, when logged
    vtt: float  # reps * weight (recomputed)


@dataclass
class Exercise:
    name: str
    sets: list[SetEntry]
    vtt: float  # sum of the sets' VTT


@dataclass
class Session:
    day_index: int          # 0..6
    day: str                # "SÁBADO" (sheet's day label)
    date: str | None        # ISO "YYYY-MM-DD" or None
    exercises: list[Exercise]
    pse: float | None        # session RPE (~0–10)
    tempo_min: float | None  # duration in minutes
    carga_ua: float | None   # RPE * time (Foster session-RPE), in A.U.
    vtt_session: float       # sum of every exercise's VTT
    wellness: dict           # sleep / stress / fatigue / soreness
    readiness: float | None  # wellness average (readiness)
    logged: bool             # actually trained? (some weight > 0)
    planned: bool            # day has exercises listed?


@dataclass
class Week:
    week: int
    sheet: str
    sessions: list[Session] = field(default_factory=list)


@dataclass
class RecoveryDay:
    """One day of recovery, from the watch via Apple Health."""
    date: str                       # ISO "YYYY-MM-DD"
    resting_hr: float | None        # resting HR (bpm)
    hr_avg: float | None            # day's average HR (bpm)
    hrv_sdnn: float | None          # HRV SDNN (ms)
    respiratory_rate: float | None  # respiratory rate (breaths/min)
    sleep: dict | None              # {asleep_h, deep_h, rem_h, core_h, in_bed_h, start, end}
