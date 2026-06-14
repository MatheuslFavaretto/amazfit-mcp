# AmazFitOps

> Mentalidade de **Ops/SRE** aplicada ao treino de força: monitorar, medir e cruzar
> **carga de treino** com **recuperação**. Um servidor **MCP** em Python que transforma o
> Claude num analista de treino pessoal.

O Claude já é a camada de análise. O trabalho deste projeto é **expor os dados como tools** —
sem frontend, sem hospedagem, sem UI para manter.

- **Carga de treino** vem de uma planilha de controle (`.xlsx`): VTT (volume = reps × peso) e
  Carga em U.A. (PSE × tempo, *session-RPE* de Foster), por série / sessão / semana.
- **Recuperação** vem de um **Amazfit GTR 4** (Fase 2 — ver [Roadmap](#roadmap)). A própria
  planilha já traz recuperação **subjetiva** (sono / estresse / fadiga / dor) por sessão.

## Status

**Fases 1, 2 e 3 entregues** — 9 tools, 35 testes verdes. Falta só você ativar o sync no iPhone
(ver [Configurar o Amazfit](#configurar-o-amazfit-apple-health--fase-0)) pra entrar dado real do
relógio; o código que lê e cruza já está pronto e testado.

## Tools

**Carga de treino (planilha):**

| Tool | O que faz |
|---|---|
| `list_weeks()` | Lista as semanas com datas, sessões feitas/planejadas, VTT, U.A. e `has_data`. |
| `get_week_summary(week)` | Resumo da semana + quebra por dia (VTT, U.A., prontidão, feito?). |
| `get_session(week, day)` | Detalha um treino: séries (reps/peso/veloc/VTT), PSE, tempo, U.A., bem-estar. `day` aceita nome ("sábado") ou 1–7. |
| `get_exercise_history(exercise, weeks?)` | Progressão de um exercício (peso máx., volume) entre semanas. Casa nome de forma flexível. |

**Recuperação (Amazfit GTR 4 via Apple Health):**

| Tool | O que faz |
|---|---|
| `get_recovery(date)` | FC de repouso, HRV, freq. respiratória e sono (horas + fases) de um dia. |
| `get_recovery_range(start, end)` | Série temporal de recuperação entre duas datas. |
| `recovery_status()` | Diagnóstico: quantos dias há, intervalo, dado mais recente e a pasta lida. |

**Análise cruzada (Fase 3):**

| Tool | O que faz |
|---|---|
| `get_training_load(window?)` | Carga por semana + **ACWR** (aguda/crônica), indicador de overtraining. |
| `compare_load_recovery(start, end)` | Junta carga de treino e recuperação **por data** — o cruzamento central. |

## Setup

Requer Python ≥ 3.10 (o `python3` do macOS é 3.9 — use o do Homebrew).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .          # instala as dependências (mcp, openpyxl)

# aponte para sua planilha (default: data/planilha.xlsx, que é gitignored)
export AMAZFITOPS_XLSX="$PWD/data/planilha.xlsx"

# subir o servidor (stdio)
PYTHONPATH=src .venv/bin/python -m amazfitops
```

> O pacote vive em `src/`. Rodamos via `PYTHONPATH=src python -m amazfitops` em vez do
> console script porque o `.pth` de editable do setuptools não é honrado de forma confiável
> quando o projeto fica sob `~/Documents` (TCC) no macOS — `PYTHONPATH` é explícito e à prova
> de bala.

## Registrar no Claude Code

```bash
claude mcp add amazfitops \
  --env PYTHONPATH="$PWD/src" \
  --env AMAZFITOPS_XLSX="$PWD/data/planilha.xlsx" \
  --env AMAZFITOPS_RECOVERY_DIR="$PWD/data/recovery" \
  -- "$PWD/.venv/bin/python" -m amazfitops
```

Depois, no Claude: *"como foi meu sábado da semana 1?"*, *"resumo da semana 1"*,
*"estou progredindo no agachamento?"*.

## Desenvolvimento

```bash
# gera a fixture sintética a partir do template
.venv/bin/python tests/make_fixture.py

# testes
.venv/bin/python -m pytest

# inspecionar as tools interativamente (MCP Inspector, requer Node):
AMAZFITOPS_XLSX="$PWD/tests/fixtures/sample.xlsx" PYTHONPATH=src \
  npx @modelcontextprotocol/inspector .venv/bin/python -m amazfitops
```

### Como o código está organizado

- `cellmap.py` — **único** lugar com posições de célula. A planilha usa posições fixas e quebra
  fácil se a estrutura mudar; isolar aqui é a defesa.
- `spreadsheet.py` — lê só os *inputs crus* e **recalcula** VTT e U.A. (o valor em cache das
  fórmulas do Excel não é confiável em arquivo recém-editado).
- `recovery.py` — lê o store de JSON do Apple Health (Health Auto Export) e normaliza por dia.
- `analysis.py` — Fase 3: ACWR e o join carga × recuperação por data.
- `server.py` — as 9 tools do FastMCP. `models.py` — dataclasses dos retornos.

Dados pessoais (`data/*.xlsx`, `data/recovery/`) ficam fora do git; só a fixture sintética é versionada.

## Configurar o Amazfit (Apple Health) — Fase 0

Fluxo: `GTR 4 → app Zepp → Apple Health → app Health Auto Export → JSON no iCloud → o Mac lê`.
Não há API oficial; este é o caminho robusto para iPhone (sem senha do Zepp, sem engenharia reversa).
A extração fica **fora do MCP** — o app escreve os JSON, as tools só leem (desacoplado, estilo SRE).

1. **Zepp → Apple Health:** no app Zepp (iPhone), Perfil → Apple Saúde, ligar **FC, FC de repouso,
   Sono e HRV**. (HRV passou a sincronizar em 2025; se o toggle não aparecer, atualize o app.)
2. **Health Auto Export:** instalar o app, criar uma automação **diária**, formato **JSON**, métricas
   `resting_heart_rate`, `heart_rate_variability`, `respiratory_rate`, `sleep_analysis`, destino uma
   pasta no **iCloud Drive** (ex.: `HealthAutoExport/`).
3. **Apontar o MCP para a pasta** — re-registrar com `AMAZFITOPS_RECOVERY_DIR` na pasta do iCloud:
   ```bash
   claude mcp remove amazfitops -s local
   claude mcp add amazfitops \
     --env PYTHONPATH="$PWD/src" \
     --env AMAZFITOPS_XLSX="$PWD/data/planilha.xlsx" \
     --env AMAZFITOPS_RECOVERY_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/HealthAutoExport" \
     -- "$PWD/.venv/bin/python" -m amazfitops
   ```
4. **Validar:** no Claude, peça `recovery_status` — deve mostrar o dado de ontem. Esse é o critério da Fase 0.

> Sono assumido em horas (padrão do Health Auto Export — validar com o primeiro export real).
> Estresse/PAI são proprietários do Zepp e podem não ir pro Apple Health; FC-repouso + sono + HRV
> já cobrem o essencial de recuperação (e a planilha já tem estresse subjetivo).

## Roadmap

- **Fase 0 (sua parte) — ativar o Apple Health** (passos acima). É o único passo que falta pra entrar
  dado real do relógio; o código que lê já está pronto e testado.
- **Fase 3 — análise cruzada — implementada** (`get_training_load` com ACWR + `compare_load_recovery`).
  Em cima das tools, o Claude interpreta: peça *"compare minha carga da semana com minha recuperação"*
  ou *"meu ACWR está em zona de risco?"*. A versão subjetiva (U.A./VTT × prontidão) já funciona sem o relógio.
