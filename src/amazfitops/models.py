"""Estruturas de dados dos retornos (serializáveis via ``dataclasses.asdict``)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SetEntry:
    serie: int
    reps: float | None
    peso: float | None
    veloc: float | None
    vtt: float  # reps * peso (recalculado)


@dataclass
class Exercise:
    name: str
    sets: list[SetEntry]
    vtt: float  # soma do VTT das séries


@dataclass
class Session:
    day_index: int          # 0..6
    day: str                # "SÁBADO"
    date: str | None        # ISO "YYYY-MM-DD" ou None
    exercises: list[Exercise]
    pse: float | None        # PSE da sessão (~0–10)
    tempo_min: float | None  # duração em minutos
    carga_ua: float | None   # PSE * tempo (Foster session-RPE)
    vtt_session: float       # soma do VTT de todos os exercícios
    wellness: dict           # sono / estresse / fadiga / dor
    readiness: float | None  # média do bem-estar (prontidão)
    logged: bool             # treinou de verdade? (algum peso > 0)
    planned: bool            # dia tem exercícios listados?


@dataclass
class Week:
    week: int
    sheet: str
    sessions: list[Session] = field(default_factory=list)


@dataclass
class RecoveryDay:
    """Recuperação de um dia, vinda do relógio via Apple Health."""
    date: str                       # ISO "YYYY-MM-DD"
    resting_hr: float | None        # FC de repouso (bpm)
    hrv_sdnn: float | None          # HRV SDNN (ms)
    respiratory_rate: float | None  # freq. respiratória (resp/min)
    sleep: dict | None              # {asleep_h, deep_h, rem_h, core_h, in_bed_h, start, end}
