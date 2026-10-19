# ChickenSVA

**An AI-powered genomic knowledge agent for structural variant imputation and interpretation in the chicken genome**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-online%20%2B%20open--source-blue)

ChickenSVA combines a **Comprehensive Chicken Reference Panel (CCRP, 2,063 genomes across 78 global populations)** with an **LLM-driven agent** that lets researchers query, impute, and interpret chicken structural variants (SVs) through natural language — no scripting required.

> **Online platform.** ChickenSVA is also operated as a hosted web service requiring no installation or API key. The service URL is provided to journal reviewers during peer review and will be added here upon publication. This repository serves users who want to (i) inspect/reproduce the methods, (ii) deploy locally, or (iii) build on the agent framework. 中文说明见 [README.zh-CN.md](README.zh-CN.md)。

---

## Table of contents

- [What ChickenSVA can do](#what-chickensva-can-do)
- [Architecture](#architecture)
- [Installation](#installation)
  - [Option A — Docker (recommended)](#option-a--docker-recommended)
  - [Option B — Conda](#option-b--conda)
- [Configuration](#configuration)
- [Quick start](#quick-start)
- [Example dataset and demo](#example-dataset-and-demo)
- [Full data release (CCRP)](#full-data-release-ccrp)
- [Repository layout](#repository-layout)
- [Tutorial video](#tutorial-video)
- [Citation](#citation)
- [License](#license)

## What ChickenSVA can do

Ask questions in plain English (or Chinese) and the agent selects and chains the right tools:

| Capability | Example question |
|---|---|
| **SV query** | "Show all deletions on chr5 between 10–12 Mb and their breed frequencies" |
| **Genome annotation** | "Which genes overlap the SV with ID DEL_chr5_10342?" |
| **Breed profiles & association** | "Which SVs show the largest frequency differences between wild and commercial broiler populations, and are they near body-weight genes?" |
| **Genome-wide scan** | "Scan SV frequencies against breed-average body weight" |
| **SV genotype imputation** | "Impute SV genotypes for my low-pass WGS / SNP-chip samples" (Beagle-based, reference panel provided) |
| **Literature grounding (optional)** | "What published evidence links this locus to growth traits?" |

Results are returned as structured tables with hard "no record found" guarantees — the agent is not allowed to fabricate database content, and every answer is traceable to the underlying tool call shown in the chat.

## Architecture

```
Browser ── HTTP/WS ─▶ Nginx (:80)
                        │  /api/  /ws/  ──▶ FastAPI backend (:9801)
                        │                    ├── AgentCore (tool planning, session memory)
                        │                    ├── LLM (OpenAI-compatible: DeepSeek / Qwen / OpenRouter)
                        │                    └── optional RAG (Dify literature KB)
                        └── static  ──▶ Vue 3 frontend (dist/)
FastAPI backend ── HTTP ─▶ MCP tool server (:9802, Flask)
                             ├── SV / annotation / association / GWAS tools
                             └── Beagle imputation engine (Java)
```

- **Backend** (`agent_framework/backend/`): FastAPI + WebSocket chat, agent orchestration, quota/rate limiting, BYOK key handling.
- **MCP tool server** (`mcp/`): Flask service exposing the bioinformatics tools over an MCP-style HTTP interface (`/mcp/v1/tools/list`, `/mcp/v1/tools/call`).
- **Frontend** (`agent_framework/frontend/`): Vue 3 + TypeScript + Element Plus chat UI with an LLM settings panel.
- **Data modules** (`data/`, `annotation/`, `refpanel/`): SV frequency tables, phenotype manager, GFF3 annotation query, Beagle runner.

## Installation

### Requirements

- Linux (tested on Ubuntu); 8 GB RAM; 20 GB free disk for the full CCRP (the bundled example dataset needs < 100 MB)
- Docker **or** Conda (Option B additionally needs Node.js ≥ 18 to build the frontend)
- An API key for at least one LLM provider (DeepSeek / Alibaba Qwen / OpenRouter) — individual users can bring their own key in the web UI; a server-level key is optional

### Option A — Docker (recommended)

```bash
git clone https://github.com/goodcqzz/ChickenSVA.git
cd ChickenSVA
cp config/chickensv.env.example config/chickensv.env   # edit: set your LLM API key
docker compose up -d --build
# Web UI:      http://127.0.0.1:9800
# API health:  http://127.0.0.1:9800/api/v1/health
```

### Option B — Conda

```bash
git clone https://github.com/goodcqzz/ChickenSVA.git
cd ChickenSVA
bash setup-env.sh                       # conda env "gaoai" from environment.yml (Python 3.11)
cp config/chickensv.env.example config/chickensv.env   # set your LLM API key
cd agent_framework/frontend && npm install && npm run build && cd ../..
bash start.sh --backend                 # starts MCP (:9802) + backend (:9801), localhost only
# open http://127.0.0.1:9800 — or put Nginx in front for production (see deploy/)
```

Utilities: `bash start.sh --status` (status), `bash stop.sh` (stop app services; never touches system Nginx), `bash setup-production.sh` (systemd + Nginx installation for servers).

## Configuration

All runtime configuration lives in **`config/chickensv.env`** (copy from `chickensv.env.example`, which is fully annotated):

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `OPENROUTER_API_KEY` | Optional platform-level LLM keys; users can instead paste their own key in the web UI (kept in the browser session only, never persisted server-side) |
| `DEEPSEEK_MODEL` | Platform default model (e.g. `deepseek-v4-flash`) |
| `PERSIST_USER_API_KEYS` | Keep `false` for public deployments |
| `DIFY_API_BASE` / `DIFY_API_KEY` / `DIFY_DATASET_*` | Optional literature knowledge base (Dify). Leave empty to disable the RAG feature |
| Quota / rate-limit / session groups | See the annotated example file |

Default ports: web entry `9800`, backend `9801` (localhost), MCP tools `9802` (localhost).

## Quick start

1. Open the web UI (`http://127.0.0.1:9800`, or your deployment URL).
2. (Optional) open **LLM settings** and paste your own API key — it stays in your browser session only.
3. Chat with the agent, e.g.:
   - `查询 5 号染色体 10 Mb–12 Mb 区域内的 SV，并列出各品种的频率`
   - `Which deletions near MYOCD differ most between wild and commercial populations?`
   - `Help me set up an imputation workspace` → the agent walks through file upload → validation → Beagle run → result download.
4. Tool calls made by the agent are displayed in the chat, so every answer can be traced back to the database.

## Example dataset and demo

`examples/` contains a miniature, self-contained dataset extracted from the CCRP (one chromosome region, subset of samples) plus a runnable demo:

```bash
cd examples
bash run_demo.sh     # SV query + annotation + a toy imputation, end-to-end
```

See `examples/README.md` for inputs and expected outputs.

## Data bundled vs. full data release

**Bundled in this repository (~24 MB)**: the SV frequency table across 78 breeds
(`data/2063_SV_frq.csv`) and the breed phenotype table (`data/鸡种表型-2024.csv`).
With these, SV query, annotation lookup against cached gene info, breed profiles,
and association analyses work out of the box after deployment.

**Full data release (Zenodo, [DOI pending])**, needed only for specific features:
the genome annotation GFF3 (~228 MB, required for `query_annotation` on the
genome file), and the complete imputation reference panels (~9 GB, required for
SV genotype imputation). A one-command download script
(`scripts/download_ccrp.sh`) will be added once the DOI is issued.

## Repository layout

```
SV_caller/                  SV discovery pipeline used to build the CCRP
                            (assembly-based: Minigraph, PAV, SVIM-asm; HiFi-based:
                            Sniffles2, cuteSV, SVIM; graph-based genotyping)
agent_framework/backend/    FastAPI backend, agent core, security, task queue
agent_framework/frontend/   Vue 3 chat UI
mcp/                        MCP HTTP tool server (SV / annotation / association / imputation)
data/                       SV frequency + phenotype loaders
annotation/                 GFF3 parsing and annotation queries
refpanel/                   Beagle runner and panel management
deploy/                     Nginx / systemd templates and run scripts
examples/                   Miniature demo dataset and scripts
config/                     chickensv.env.example (all runtime settings)
```

## Tutorial video

A step-by-step video — clean machine → installation (Docker and Conda) → configuration → representative analyses → results, plus a walkthrough of the online platform — is available at **[link pending]**.

## Citation

If you use ChickenSVA or the CCRP, please cite:

```bibtex
@article{chickensva2026,
  title   = {ChickenSVA: An AI-powered genomic knowledge agent for structural variant
             imputation and interpretation in the chicken genome},
  author  = {Gao, Chaoqun and others},
  journal = {iMetaOmics},
  year    = {2026},
  note    = {DOI will be added upon acceptance}
}
```

## License

Released under the [MIT License](LICENSE). `refpanel/beagle.jar` is third-party software ([Beagle 5.x](https://faculty.uw.edu/browning/beagle/beagle.html)) and is governed by its own license terms.

## Contact

- Issues: https://github.com/goodcqzz/ChickenSVA/issues
- Correspondence: [corresponding author email]
