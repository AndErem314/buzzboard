# 🐝 BuzzBoard

**Multi-agent beehive inspection assistant — voice memos become structured Obsidian notes through a local AI pipeline.**

Drop a voice memo from your hive inspection into `inbox/`. Five specialized agents transcribe it, structure the content, extract key data points, store it in your Obsidian vault by hive, and analyze historical trends — all running on your machine, no cloud required.

> **Runs entirely locally:** Whisper for speech-to-text, Ollama for LLM reasoning, Obsidian for storage. Your hive data never leaves your computer.

---

## Architecture

```
Voice Memo (inbox/H07_2026-06-06.m4a)
         │
    ┌────▼────┐     ┌────────┐     ┌──────────┐     ┌─────────┐     ┌────────┐
    │Transcriber│ ──▶│ Editor │ ──▶ │Extractor│ ──▶ │ Storage  │ ──▶│ Trend  │
    │  Agent   │     │ Agent  │     │  Agent  │     │  Agent   │     │ Agent  │
    └─────────┘     └────────┘     └──────────┘     └─────────┘     └────────┘
    Whisper STT      LLM clean      LLM extract      Obsidian       LLM analyze
```

Every agent reads a JSON artifact from the previous one, applies its transformation, and writes a new artifact — a fully auditable pipeline with content hashing at each step. A SQLite-backed Kanban board tracks every task through seven stages.

## Why BuzzBoard?

| Principle | How |
|---|---|
| **Local-first** | Everything runs on your machine — Whisper, Ollama, SQLite. No API keys, no cloud dependency, no data leaving your computer |
| **Multi-agent by design** | Five specialized agents with clear contracts. Each does one thing well, passing structured JSON handoffs — not one monolithic LLM call |
| **Auditable pipeline** | Every agent output is hashed. Every action is logged with timestamps and durations. You can trace any inspection from raw audio to Obsidian note |
| **Real domain expertise** | Beekeeping-specific prompts, terminology, and data models. The agents understand queen status, brood patterns, mite counts, swarm indicators, and honey stores |
| **Obsidian-native** | Notes use YAML frontmatter with Dataview-compatible fields. Each hive gets its own directory, index, and query block — your vault stays organized |
| **Graceful degradation** | If an LLM returns garbage, agents fall back to data-driven defaults. If Ollama is down, you get a clear error — not silent corruption |

## Agents

| Agent | Role | Input → Output | Model |
|---|---|---|---|
| **Transcriber** | Speech-to-text | Audio file → `RawTranscript` | Whisper (base) |
| **Editor** | Clean & structure raw text | `RawTranscript` → `CleanedNote` | Ollama (llama3.1:8b) |
| **Extractor** | Pull structured fields | `CleanedNote` → `StructuredRecord` | Ollama (llama3.1:8b) |
| **Storage** | Write to Obsidian vault | `StructuredRecord` → Markdown | — |
| **Trend** | Historical pattern analysis | Multiple records → `TrendReport` | Ollama (llama3.1:8b) |

**Shared components:**
- **OllamaClient** — shared chat API wrapper with retry, JSON mode, and health checks
- **Kanban board** — SQLite-backed task tracker with audit event log
- **Orchestrator** — file watcher that auto-runs the pipeline on new voice memos
- **Web dashboard** — FastAPI + Uvicorn, live Kanban board at `http://localhost:8099`

### Processing Model

The pipeline processes files **sequentially** — one voice memo at a time, agent by agent. This is a deliberate tradeoff: BuzzBoard runs entirely on your hardware with no cloud dependency. A local Ollama instance can only serve one LLM request at a time anyway, so parallel processing wouldn't meaningfully improve throughput. What you gain is complete privacy — your hive inspection data, audio recordings, and notes never leave your machine.

For a beekeeper processing one or two inspections per visit, sequential processing completes in seconds. The file watcher (`buzzboard watch`) handles batching: drop several files in `inbox/` and they'll all be processed in order.

## Project Structure

```
buzzboard/
├── src/
│   ├── agents/
│   │   ├── base.py              # BuzzAgent ABC — JSON handoff protocol
│   │   ├── transcriber.py       # Whisper speech-to-text agent
│   │   ├── editor.py            # LLM cleaning & structuring agent
│   │   ├── extractor.py         # LLM data extraction agent
│   │   ├── storage.py           # Obsidian markdown writer agent
│   │   ├── trend.py             # Historical pattern analysis agent
│   │   ├── ollama_client.py     # Shared Ollama API wrapper
│   │   └── prompts.py           # Versioned beekeeping system prompts
│   ├── schema/
│   │   └── __init__.py          # Pydantic data contracts (all 5 models)
│   ├── orchestrator/
│   │   └── __init__.py          # File watcher + pipeline runner
│   ├── db/
│   │   └── kanban.py            # SQLite Kanban board + audit log
│   ├── dashboard/
│   │   └── server.py            # FastAPI web dashboard
│   ├── cli.py                   # Click CLI — buzzboard process/watch/trends/board/dashboard
│   └── config.py                # .env loader with typed config
├── tests/
│   ├── test_agents.py           # 12 tests — Editor, Extractor, Trend agents
│   └── test_phase3.py           # 18 tests — Kanban, Storage, filename parsing
├── pyproject.toml
├── .env.example
└── README.md
```

## Quick Start

```bash
# 1. Clone + install
git clone https://github.com/AndErem314/buzzboard.git
cd buzzboard
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[whisper,ollama,dashboard]"

# 2. Pull the LLM model
ollama pull llama3.1:8b

# 3. Configure
cp .env.example .env
# Set BUZZBOARD_OBSIDIAN_VAULT to your Obsidian vault path

# 4. Verify everything works
buzzboard config

# 5. Process a voice memo
buzzboard process inbox/H07_2026-06-06.m4a

# 6. Or auto-process everything in inbox/
buzzboard watch --once
```

## CLI Reference

```bash
# Full pipeline on a single file
buzzboard process inbox/H07_2026-06-06.m4a [--obsidian-vault ~/Documents/Obsidian]

# Watch inbox/ and auto-process new files (--once: process pending, then exit)
buzzboard watch [--once] [--obsidian-vault ~/Documents/Obsidian]

# Analyze historical trends for a hive
buzzboard trends H07 [--obsidian-vault ~/Documents/Obsidian]

# View Kanban board with task status
buzzboard board

# View event log for a specific task
buzzboard events H07_2026-06-06

# Start web dashboard (http://localhost:8099)
buzzboard dashboard

# Show current configuration
buzzboard config
```

## Obsidian Integration

Notes are written as structured markdown with YAML frontmatter:

```
{HIVES_DIR}/H07/
├── 2026-05-08.md          # Individual inspection notes
├── 2026-06-06.md
├── H07_Index.md            # Auto-generated index table + Dataview query
└── .buzzboard/             # Pipeline artifact provenance
    ├── record_2026-05-08.json
    └── note_2026-05-08.json
```

Each note's frontmatter is Dataview-compatible — open Obsidian and run queries like "show all hives where mite count exceeds 3" or "inspections where queen was not seen."

## Configuration

All settings via `.env` file (never committed to git):

| Variable | Default | Description |
|---|---|---|
| `BUZZBOARD_OBSIDIAN_VAULT` | *(required)* | Path to your Obsidian vault |
| `BUZZBOARD_OLLAMA_MODEL` | `llama3.1:8b` | LLM for Editor, Extractor, Trend agents |
| `BUZZBOARD_OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `BUZZBOARD_INBOX_DIR` | `inbox` | Where voice memos land |
| `BUZZBOARD_PIPELINE_DIR` | `pipeline` | JSON artifacts between agents |
| `BUZZBOARD_ARCHIVE_DIR` | `archive` | Processed audio moved here |
| `BUZZBOARD_WHISPER_MODEL` | `base` | Whisper model size (tiny/base/small/medium) |
| `BUZZBOARD_WHISPER_BACKEND` | `whisper` | `whisper` or `whisper-cpp` |
| `BUZZBOARD_KANBAN_DB` | `pipeline/kanban.db` | SQLite Kanban database path |

## Requirements

- **Python 3.11+**
- **[Ollama](https://ollama.com)** with a model pulled
- **[Whisper](https://github.com/openai/whisper)** for speech-to-text
- **[Obsidian](https://obsidian.md)** for note storage (optional — pipeline works without it)

**Hardware:** Runs on 16 GB RAM with quantized models (`llama3.2:3b`). Apple Silicon (M-series) is recommended — Whisper uses the Neural Engine for fast transcription.

## Development

```bash
pip install -e ".[dev]"
pytest                    # 30 tests, all passing
ruff check src/           # Lint
```

## License

MIT — see [LICENSE](LICENSE).
