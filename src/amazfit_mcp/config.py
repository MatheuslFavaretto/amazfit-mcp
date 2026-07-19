"""Path and parameter resolution.

The MCP reads the spreadsheet path from the ``AMAZFIT_MCP_XLSX`` environment
variable. When unset, it falls back to ``data/planilha.xlsx`` at the project root
(gitignored). To run against the synthetic fixture, point the env to
``tests/fixtures/sample.xlsx``.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = PROJECT_ROOT / "data" / "planilha.xlsx"
DEFAULT_RECOVERY_DIR = PROJECT_ROOT / "data" / "recovery"
DEFAULT_OBSIDIAN_DIR = PROJECT_ROOT / "data" / "obsidian"

ENV_VAR = "AMAZFIT_MCP_XLSX"
RECOVERY_ENV = "AMAZFIT_MCP_RECOVERY_DIR"
OBSIDIAN_ENV = "AMAZFIT_MCP_OBSIDIAN_DIR"
HR_MAX_ENV = "AMAZFIT_MCP_HR_MAX"
HR_REST_ENV = "AMAZFIT_MCP_HR_REST"


def xlsx_path() -> Path:
    """Path of the spreadsheet to read (env ``AMAZFIT_MCP_XLSX`` or default)."""
    env = os.environ.get(ENV_VAR)
    return Path(env).expanduser() if env else DEFAULT_XLSX


def recovery_dir() -> Path:
    """Folder with the Health Auto Export recovery JSON files.

    Env ``AMAZFIT_MCP_RECOVERY_DIR`` or default ``data/recovery``. Point it to the
    iCloud Drive folder where the app drops the exports, e.g.:
    ``~/Library/Mobile Documents/com~apple~CloudDocs/HealthAutoExport``.
    """
    env = os.environ.get(RECOVERY_ENV)
    return Path(env).expanduser() if env else DEFAULT_RECOVERY_DIR


def obsidian_dir() -> Path:
    """Obsidian vault folder where the daily notes are written.

    Env ``AMAZFIT_MCP_OBSIDIAN_DIR`` or default ``data/obsidian`` (gitignored).
    Point it to a subfolder of your vault, e.g. ``~/Obsidian/Training/Daily``.
    """
    env = os.environ.get(OBSIDIAN_ENV)
    return Path(env).expanduser() if env else DEFAULT_OBSIDIAN_DIR


def hr_bounds() -> tuple[float, float]:
    """(resting HR, max HR) for the TRIMP calculation — envs ``AMAZFIT_MCP_HR_REST`` /
    ``AMAZFIT_MCP_HR_MAX``, conservative defaults 60/190."""
    def _env(name: str, default: float) -> float:
        raw = os.environ.get(name)
        try:
            return float(raw) if raw else default
        except ValueError:
            return default

    return _env(HR_REST_ENV, 60.0), _env(HR_MAX_ENV, 190.0)
