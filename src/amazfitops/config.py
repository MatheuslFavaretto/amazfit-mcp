"""Resolução do caminho da planilha.

O MCP lê o caminho da variável de ambiente ``AMAZFITOPS_XLSX``. Se ela não estiver
definida, cai no default ``data/planilha.xlsx`` na raiz do projeto (gitignored).
Para rodar contra a fixture sintética, aponte a env para ``tests/fixtures/sample.xlsx``.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = PROJECT_ROOT / "data" / "planilha.xlsx"
DEFAULT_RECOVERY_DIR = PROJECT_ROOT / "data" / "recovery"

ENV_VAR = "AMAZFITOPS_XLSX"
RECOVERY_ENV = "AMAZFITOPS_RECOVERY_DIR"


def xlsx_path() -> Path:
    """Caminho da planilha a ser lida (env ``AMAZFITOPS_XLSX`` ou default)."""
    env = os.environ.get(ENV_VAR)
    return Path(env).expanduser() if env else DEFAULT_XLSX


def recovery_dir() -> Path:
    """Pasta com os JSON de recuperação do Health Auto Export.

    Env ``AMAZFITOPS_RECOVERY_DIR`` ou default ``data/recovery``. Aponte para a pasta do
    iCloud Drive onde o app dropa os exports, p.ex.:
    ``~/Library/Mobile Documents/com~apple~CloudDocs/HealthAutoExport``.
    """
    env = os.environ.get(RECOVERY_ENV)
    return Path(env).expanduser() if env else DEFAULT_RECOVERY_DIR
