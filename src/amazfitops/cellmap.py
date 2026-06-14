"""O mapa de células da planilha — único lugar com posições fixas.

A planilha quebra fácil se a estrutura mudar, então TODA dependência de
"qual linha/coluna é o quê" mora aqui. O resto do código fala em termos de
``base_row(dia)`` e dos nomes de coluna abaixo.

Layout descoberto por inspeção (verificado contra as fórmulas das abas de
agregação ``C.I DIÁRIA``, `` C.I SEMANAL`` e ``C.E DIÁRIA E SEMANAL``):

Cada aba ``SEM N`` tem 7 blocos verticais de 18 linhas (um por dia da semana).
O bloco do dia ``d`` (0 = SEGUNDA … 6 = DOMINGO) começa em ``base = 1 + 18*d``.

Relativo ao ``base`` (que é a linha de cabeçalho do bloco):
  base+1  -> linha do dia: nome (A), data (E), bem-estar (L/M/N/O)
  base+4  -> primeira linha de exercício; PSE da sessão em AE
  base+6  -> tempo total da sessão (min) em AG
  base+15 -> última linha de exercício (até 12 exercícios)

As 5 séries ocupam grupos fixos de colunas (reps / peso / veloc):
  série 1: B C D   |  série 2: G H I   |  série 3: L M N
  série 4: Q R S   |  série 5: V W X

VTT (reps*peso), VTT-sessão e Carga U.A. (PSE*Tempo) existem como fórmulas na
planilha, mas são RECALCULADOS em ``spreadsheet.py`` a partir dos inputs crus —
o valor em cache do openpyxl não é confiável em arquivo recém-editado.
"""

from __future__ import annotations

import re
import unicodedata

from openpyxl.utils import column_index_from_string as _ci

# --- geometria dos blocos de dia ---
N_DAYS = 7
BLOCK_SIZE = 18
FIRST_BASE = 1

# nomes canônicos (fallback se a célula do nome estiver vazia)
DAY_NAMES = [
    "SEGUNDA-FEIRA",
    "TERÇA-FEIRA",
    "QUARTA-FEIRA",
    "QUINTA-FEIRA",
    "SEXTA-FEIRA",
    "SÁBADO",
    "DOMINGO",
]

# --- offsets relativos ao base ---
OFF_DAY = 1          # linha do dia (nome, data, bem-estar)
OFF_EX_FIRST = 4     # primeira linha de exercício
OFF_EX_LAST = 15     # última linha de exercício (12 linhas no total)
OFF_PSE = 4          # PSE da sessão (col AE)
OFF_TEMPO = 6        # tempo total da sessão em min (col AG)

# --- colunas (índices 1-based) ---
COL_DAYNAME = _ci("A")
COL_DATE = _ci("E")
COL_SONO = _ci("L")
COL_ESTRESSE = _ci("M")
COL_FADIGA = _ci("N")
COL_DOR = _ci("O")
COL_EX_NAME = _ci("A")
COL_PSE = _ci("AE")
COL_TEMPO = _ci("AG")

# (reps, peso, veloc) por série
SERIES_COLS = [
    (_ci("B"), _ci("C"), _ci("D")),
    (_ci("G"), _ci("H"), _ci("I")),
    (_ci("L"), _ci("M"), _ci("N")),
    (_ci("Q"), _ci("R"), _ci("S")),
    (_ci("V"), _ci("W"), _ci("X")),
]

# região a materializar ao ler uma aba SEM (cobre 7 blocos + col AJ)
MAX_ROW = FIRST_BASE + BLOCK_SIZE * N_DAYS + 4   # 131
MAX_COL = _ci("AJ")                              # 36

# abas de semana: "SEM 1" .. "SEM 12" (tolera espaços e caixa)
WEEK_SHEET_RE = re.compile(r"^\s*SEM\s*(\d+)\s*$", re.IGNORECASE)


def base_row(day_index: int) -> int:
    """Linha-base do bloco do dia (0 = segunda … 6 = domingo)."""
    if not 0 <= day_index < N_DAYS:
        raise ValueError(f"day_index fora de 0..{N_DAYS - 1}: {day_index}")
    return FIRST_BASE + BLOCK_SIZE * day_index


def normalize(text: object) -> str:
    """Minúsculas, sem acento, sem espaços nas pontas — para casar nomes."""
    s = unicodedata.normalize("NFKD", str(text).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip()
