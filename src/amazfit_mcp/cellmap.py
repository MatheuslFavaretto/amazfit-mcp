"""The spreadsheet cell map — the only place with hard-coded positions.

The spreadsheet breaks easily if its structure changes, so EVERY dependency on
"which row/column is what" lives here. The rest of the code speaks in terms of
``base_row(day)`` and the column names below.

Layout discovered by inspection (verified against the formulas of the
aggregation sheets ``C.I DIÁRIA``, `` C.I SEMANAL`` and ``C.E DIÁRIA E SEMANAL``):

Each ``SEM N`` (week) sheet has 7 vertical blocks of 18 rows (one per weekday).
The block for day ``d`` (0 = MONDAY … 6 = SUNDAY) starts at ``base = 1 + 18*d``.

Relative to ``base`` (the block's header row):
  base+1  -> day row: name (A), date (E), wellness (L/M/N/O)
  base+4  -> first exercise row; session RPE (PSE) in AE
  base+6  -> total session time (min) in AG
  base+15 -> last exercise row (up to 12 exercises)

The 5 sets occupy fixed column groups (reps / weight / velocity):
  set 1: B C D   |  set 2: G H I   |  set 3: L M N
  set 4: Q R S   |  set 5: V W X

VTT (reps*weight), session VTT and Load in A.U. (RPE*time) exist as formulas in
the spreadsheet, but are RECOMPUTED in ``spreadsheet.py`` from the raw inputs —
openpyxl's cached value is unreliable in a freshly edited file.
"""

from __future__ import annotations

import re
import unicodedata

from openpyxl.utils import column_index_from_string as _ci

# --- day-block geometry ---
N_DAYS = 7
BLOCK_SIZE = 18
FIRST_BASE = 1

# canonical names (fallback when the name cell is empty)
DAY_NAMES = [
    "SEGUNDA-FEIRA",
    "TERÇA-FEIRA",
    "QUARTA-FEIRA",
    "QUINTA-FEIRA",
    "SEXTA-FEIRA",
    "SÁBADO",
    "DOMINGO",
]

# --- offsets relative to base ---
OFF_DAY = 1          # day row (name, date, wellness)
OFF_EX_FIRST = 4     # first exercise row
OFF_EX_LAST = 15     # last exercise row (12 rows total)
OFF_PSE = 4          # session RPE / PSE (col AE)
OFF_TEMPO = 6        # total session time in min (col AG)

# --- columns (1-based indices) ---
COL_DAYNAME = _ci("A")
COL_DATE = _ci("E")
COL_SONO = _ci("L")
COL_ESTRESSE = _ci("M")
COL_FADIGA = _ci("N")
COL_DOR = _ci("O")
COL_EX_NAME = _ci("A")
COL_PSE = _ci("AE")
COL_TEMPO = _ci("AG")

# (reps, weight, velocity) per set
SERIES_COLS = [
    (_ci("B"), _ci("C"), _ci("D")),
    (_ci("G"), _ci("H"), _ci("I")),
    (_ci("L"), _ci("M"), _ci("N")),
    (_ci("Q"), _ci("R"), _ci("S")),
    (_ci("V"), _ci("W"), _ci("X")),
]

# region to materialize when reading a SEM sheet (covers 7 blocks + col AJ)
MAX_ROW = FIRST_BASE + BLOCK_SIZE * N_DAYS + 4   # 131
MAX_COL = _ci("AJ")                              # 36

# week sheets: "SEM 1" .. "SEM 12" (tolerates spaces and casing)
WEEK_SHEET_RE = re.compile(r"^\s*SEM\s*(\d+)\s*$", re.IGNORECASE)


def base_row(day_index: int) -> int:
    """Base row of the day's block (0 = Monday … 6 = Sunday)."""
    if not 0 <= day_index < N_DAYS:
        raise ValueError(f"day_index out of 0..{N_DAYS - 1}: {day_index}")
    return FIRST_BASE + BLOCK_SIZE * day_index


def normalize(text: object) -> str:
    """Lowercase, accent-stripped, trimmed — for name matching."""
    s = unicodedata.normalize("NFKD", str(text).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip()
