# AmazFitOps — notas de arquitetura

> Documentação técnica do projeto: estrutura da planilha, store de recuperação, decisões e
> roadmap. Atualizado em jun/2026.

## O que é

Servidor **MCP** (FastMCP, Python) que transforma o Claude num analista de treino de força.
Mentalidade de **Ops/SRE** aplicada ao treino: monitorar, medir, alertar — cruzando **carga
de treino** (planilha) com **recuperação** (relógio + subjetiva). Primeiro projeto MCP;
serve como ferramenta + aprendizado + peça de portfólio.

**Princípio condutor:** o Claude já é a camada de análise (de graça). O projeto só **expõe os
dados como tools**. Sem frontend, sem hospedagem, sem UI.

## Stack

- Python ≥ 3.10 (o `python3` do macOS é 3.9 — usar Homebrew `python3.12`).
- FastMCP (SDK oficial `mcp`); `openpyxl` (leitura read-only).
- Sem `uv` no ambiente; usamos `venv` + `pip install -e .`. Uso = **Claude Code CLI**
  (não Desktop): registro via `claude mcp add` / `.mcp.json`.

## Estado atual

- **Fase 1 (MCP da planilha) — implementada.** 4 tools: `list_weeks`, `get_week_summary`,
  `get_session`, `get_exercise_history`.
- **Fase 2 (recuperação) — implementada (leitura).** 3 tools: `get_recovery`, `get_recovery_range`,
  `recovery_status`, lendo o store de JSON do Apple Health (`recovery.py`).
- **Fase 3 (análise cruzada) — implementada.** 2 tools: `get_training_load` (ACWR) e
  `compare_load_recovery` (join por data), em `analysis.py`.
- **9 tools, 35 testes verdes** contra fixtures sintéticas (planilha + recuperação, datas alinhadas).
- **Fase 0 (ativar o sync no iPhone) — pendente (configuração manual no iPhone).** Único passo que falta pra dado real.

## A planilha (estrutura REAL, verificada)

Planilha trimestral: abas `SEM 1`..`SEM 12` (o código detecta via regex `^SEM \d+$`, então
funciona com 4 ou 12). Fonte de verdade: `data/planilha.xlsx` (env `AMAZFITOPS_XLSX`).

Cada aba `SEM N` tem **7 blocos verticais de 18 linhas** (um por dia). O bloco do dia `d`
(0 = SEG … 6 = DOM) começa em `base = 1 + 18*d` → `[1, 19, 37, 55, 73, 91, 109]`.
O mapa completo vive em `src/amazfitops/cellmap.py`:

| Item | Célula (relativa ao `base`) |
|---|---|
| Nome do dia / Data | `A(base+1)` / `E(base+1)` |
| Sono / Estresse / Fadiga / Dor | `L / M / N / O (base+1)` |
| Exercícios (até 12) | `A(base+4)` … `A(base+15)` |
| Séries 1–5 (reps/peso/veloc) | `B C D` · `G H I` · `L M N` · `Q R S` · `V W X` |
| PSE da sessão | `AE(base+4)` |
| Tempo (min) | `AG(base+6)` |

**Derivados são recalculados em Python**, não lidos da planilha: VTT = reps×peso;
VTT-sessão = Σ; Carga U.A. = PSE×Tempo; prontidão = média(sono,estresse,fadiga,dor).
Motivo: `openpyxl(data_only=True)` só devolve o valor em cache do Excel, que vem `None`/`#DIV/0!`
em arquivo recém-editado. O parser trata `None` e strings de erro como ausente.

**"Sessão registrada"** = algum `peso > 0` no dia (distingue do dia só *planejado*, cujas reps já
vêm preenchidas no template).

Há abas de agregação (`C.I DIÁRIA`, ` C.I SEMANAL` — nome com espaço!, `C.E DIÁRIA E SEMANAL`)
cujas fórmulas foram a fonte para derivar o mapa. **Não** as usamos como fonte de dados (têm um
bug — sessão 6 lê `S92` em vez de `L92` — e a aba U.A. só cobre SEG–SEX). Calculamos tudo a
partir dos blocos `SEM`, cobrindo os 7 dias.

## Decisões tomadas

- Nome: **AmazFitOps**. MCP custom (não app). FastMCP, sem framework exótico. Read-only primeiro.
- Planilha-fonte: versão trimestral de 12 semanas; semanas detectadas dinamicamente.
- Validação por **fixture sintética** versionada (`tests/fixtures/sample.xlsx`); dado real fora do git.
- **Recuperação no iPhone — DECIDIDO: via Apple Health.** Setup: **iPhone + GTR 4**, o que
  descarta Health Connect e ler o DB do app (ambos Android). Caminho escolhido (jun/2026):
  `GTR 4 → Zepp → Apple Health → app Health Auto Export (JSON no iCloud) → o Mac lê`. Robusto, sem
  senha do Zepp, sem engenharia reversa (a Zepp passou a sincronizar HRV pro Apple Health em 2025).
  Alternativa preterida: API da nuvem Zepp/Huami (`huami-token`) — mais dados (estresse/PAI) porém
  frágil e zona cinzenta ToS; pode entrar como 2ª fonte depois (store é desacoplado). NÃO instalar
  MCP de terceiros para Zepp.

## Recuperação — store e formato (Fase 2, implementada)

`recovery.py` lê todos os `*.json` da pasta `AMAZFITOPS_RECOVERY_DIR` (default `data/recovery`;
em produção, a pasta do iCloud onde o Health Auto Export dropa os exports) e normaliza por dia.
Formato do Health Auto Export: `{"data":{"metrics":[{"name","units","data":[...]}]}}` — pontos de
quantidade têm `qty`+`date`; `sleep_analysis` tem `asleep/deep/rem/core/inBed/sleepStart/sleepEnd`.
Mapeamos `resting_heart_rate`→FC repouso, `heart_rate_variability`→HRV SDNN, `respiratory_rate`,
e o sono. Datas no formato `yyyy-MM-dd HH:mm:ss Z` (quantidade) e `yyyy-MM-dd` (sono).

## Roadmap

- **Fase 0 (pendente, configuração manual)** — ativar Zepp → Apple Health (incl. HRV) e configurar o
  Health Auto Export exportando JSON pro iCloud; apontar `AMAZFITOPS_RECOVERY_DIR` pra lá. Critério
  de pronto: `recovery_status` mostra o dado de ontem. Passo a passo no README.
- **Fase 3 — análise cruzada — implementada** (`analysis.py`): `get_training_load` (ACWR =
  aguda/crônica, faixas de risco) e `compare_load_recovery` (join treino × recuperação por data,
  exige a célula DATA preenchida). Em cima disso o Claude interpreta; a versão subjetiva (U.A./VTT
  × prontidão da planilha) já funciona sem o relógio.

## Repos de referência (jun/2026)

Estudar o **método de extração** (a parte difícil), não copiar cego.
- `argrento/huami-token` (Python, maduro) — token de auth da nuvem Huami/Zepp. **Chave da Fase 0.**
- `lcanis/zepp-food-extractor`, `H3llK33p3r/zepp-fit-extractor` — exemplos de falar com a API da nuvem.
- `n0Pnyk/zepp-health-skill` e `.../zepp-health-analytics` — precedentes da camada de análise/scoring.
- ~~`ndesgranges/zepp-health-ha`~~ (lê DB Android) — **não se aplica (iPhone)**.
