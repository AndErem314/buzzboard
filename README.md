# 🐝 BuzzBoard

**Multi-agent beehive inspection assistant — voice memos become structured Obsidian notes through a local AI pipeline.**

Drop a voice memo from your hive inspection into `inbox/`. Six specialized agents transcribe it, split multi-hive recordings, structure the content, extract key data points, store it in your Obsidian vault by hive, and analyze historical trends — all running on your machine, no cloud required.

> **Runs entirely locally:** Whisper for speech-to-text, Ollama for LLM reasoning, Obsidian for storage. Your hive data never leaves your computer.

---

## Architecture

```
Voice Memo (any filename)
         │
    ┌────▼────┐  ┌──────────┐  ┌────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐
    │Transcriber│─▶│ Splitter  │─▶│ Editor │─▶ │Extractor│─▶ │ Storage  │─▶│ Trend  │
    │  Agent    │  │  Agent*   │  │ Agent  │  │  Agent  │  │  Agent   │  │ Agent  │
    └─────────┘    └──────────┘  └────────┘  └──────────┘  └─────────┘  └────────┘
    Whisper STT     LLM split     LLM clean   LLM extract    Obsidian     LLM analyze
                   *multi-hive only
```

**Multi-hive support:** Voice memos with non-standard filenames (e.g. `Neue Aufnahme 2.m4a`) often cover several hives in one recording. The HiveSplitter agent detects this from the transcript, splits it into per-hive segments, and processes each independently. Single-hive files (matching `H07_2026-06-06.m4a`) skip the splitter entirely and flow straight from Transcriber to Editor.

**Timestamp filtering:** The file watcher (`buzzboard watch`) defaults to `--recent`, processing only files added since the last poll cycle. Pass `--all` to reprocess everything in `inbox/` (useful after a crash or for bulk imports).

Every agent reads a JSON artifact from the previous one, applies its transformation, and writes a new artifact — a fully auditable pipeline with content hashing at each step. A SQLite-backed Kanban board tracks every task through seven stages (inbox → transcribing → editing → extracting → storing → done / failed).

## Why BuzzBoard?

| Principle | How |
|---|---|
| **Local-first** | Everything runs on your machine — Whisper, Ollama, SQLite. No API keys, no cloud dependency, no data leaving your computer |
| **Multi-agent by design** | Six specialized agents with clear contracts. Each does one thing well, passing structured JSON handoffs — not one monolithic LLM call |
| **Auditable pipeline** | Every agent output is hashed. Every action is logged with timestamps and durations. You can trace any inspection from raw audio to Obsidian note |
| **Real domain expertise** | Beekeeping-specific prompts, terminology, and data models. The agents understand queen status, brood patterns, mite counts, swarm indicators, and honey stores |
| **Multi-hive aware** | Automatically handles voice memos covering multiple hives. The Splitter identifies each hive from the transcript and creates per-hive records |
| **Obsidian-native** | Notes use YAML frontmatter with Dataview-compatible fields. Each hive gets its own directory, index, and query block — your vault stays organized |
| **Graceful degradation** | If an LLM returns garbage, agents fall back to data-driven defaults. If Ollama is down, you get a clear error — not silent corruption |

## Agents

| Agent | Role | Input → Output | Model |
|---|---|---|---|
| **Transcriber** | Speech-to-text | Audio file → `RawTranscript` | Whisper (medium) |
| **HiveSplitter** | Split multi-hive transcripts | `RawTranscript` → N × `RawTranscript` (per-hive) | Ollama (llama3.1:8b) |
| **Editor** | Clean & structure raw text | `RawTranscript` → `CleanedNote` | Ollama (llama3.1:8b) |
| **Extractor** | Pull structured fields | `CleanedNote` → `StructuredRecord` | Ollama (llama3.1:8b) |
| **Storage** | Write to Obsidian vault | `StructuredRecord` → Markdown | — |
| **Trend** | Historical pattern analysis | Multiple records → `TrendReport` | Ollama (llama3.1:8b) |

**Shared components:**
- **OllamaClient** — shared chat API wrapper with retry, JSON mode, and health checks
- **Kanban board** — SQLite-backed task tracker with audit event log (7 stages: inbox, transcribing, editing, extracting, storing, done, failed)
- **Orchestrator** — file watcher that auto-runs the pipeline on new voice memos, with multi-hive routing and timestamp filtering
- **Web dashboard** — FastAPI + Uvicorn, live Kanban board at `http://localhost:8099` (HTML/CSS/JS fully separated under `src/dashboard/static/`)

### Processing Model

The pipeline processes files **sequentially** — one voice memo at a time, agent by agent. For multi-hive files, each hive segment is processed in order through Editor → Extractor → Storage. This is a deliberate tradeoff: BuzzBoard runs entirely on your hardware with no cloud dependency. A local Ollama instance can only serve one LLM request at a time anyway, so parallel processing wouldn't meaningfully improve throughput. What you gain is complete privacy — your hive inspection data, audio recordings, and notes never leave your machine.

For a beekeeper processing one or two inspections per visit, sequential processing completes in seconds. The file watcher (`buzzboard watch`) handles batching: drop several files in `inbox/` and they'll all be processed in order.

## Project Structure

```
buzzboard/
├── src/
│   ├── agents/
│   │   ├── base.py              # BuzzAgent ABC — JSON handoff protocol
│   │   ├── transcriber.py       # Whisper speech-to-text agent
│   │   ├── splitter.py          # Multi-hive transcript splitter (LLM)
│   │   ├── editor.py            # LLM cleaning & structuring agent
│   │   ├── extractor.py         # LLM data extraction agent
│   │   ├── storage.py           # Obsidian markdown writer agent
│   │   ├── trend.py             # Historical pattern analysis agent
│   │   ├── ollama_client.py     # Shared Ollama API wrapper
│   │   └── prompts.py           # Versioned beekeeping system prompts
│   ├── schema/
│   │   └── __init__.py          # Pydantic data contracts (all 5 models)
│   ├── orchestrator/
│   │   └── __init__.py          # File watcher + pipeline runner (multi-hive aware)
│   ├── db/
│   │   └── kanban.py            # SQLite Kanban board + audit log
│   ├── dashboard/
│   │   ├── server.py            # FastAPI routes + bootstrap
│   │   └── static/              # UI assets (separated from Python)
│   │       ├── index.html       # Dashboard scaffold
│   │       ├── style.css        # Dark-teal theme + design tokens
│   │       └── app.js           # Vanilla-JS controller (no build step)
│   ├── cli.py                   # Click CLI — buzzboard start/process/watch/trends/board/…
│   └── config.py                # .env loader with typed config
├── tests/
│   ├── test_agents.py           # Editor, Extractor, Trend, Splitter agents
│   ├── test_phase3.py           # Kanban, Storage, filename parsing
│   └── test_dashboard.py        # Static-asset integrity + route smoke tests
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

# 2. Pull the LLM model (~5 GB for llama3.1:8b)
ollama pull llama3.1:8b

# 3. Configure
cp .env.example .env
# Edit .env and set BUZZBOARD_OBSIDIAN_VAULT to your Obsidian vault path

# 4. Create the working directories
mkdir -p inbox archive pipeline

# 5. Verify everything is wired correctly
buzzboard status        # shows pipeline + config summary
buzzboard config        # shows resolved paths and model choices

# 6. Drop voice memos into inbox/ and start everything
cp ~/Desktop/H07_2026-06-06.m4a inbox/
buzzboard start          # → http://localhost:8099 with live Kanban + pipeline
```

That's it — one command starts the web dashboard **and** the pipeline watcher. Drop new voice memos into `inbox/` while it's running and they'll be processed automatically.

> **Note:** the `inbox/` and `archive/` directories are git-ignored — BuzzBoard creates them on first run, but creating them explicitly avoids the first-run warning.

## CLI Reference

```bash
# Start everything: dashboard + pipeline watcher (the only command you need)
buzzboard start [--host 127.0.0.1] [--port 8099]

# Full pipeline on a single file (auto-detects multi-hive)
buzzboard process inbox/H07_2026-06-06.m4a [--obsidian-vault ~/Documents/Obsidian]
buzzboard process "inbox/Neue Aufnahme 2.m4a"

# Transcribe only (without further processing)
buzzboard transcribe inbox/recording.m4a

# Split a multi-hive transcript into per-hive artifacts
buzzboard split pipeline/rawtranscript_abc123.json

# Watch inbox/ and auto-process new files (CLI only, no dashboard)
buzzboard watch [--once] [--recent|--all] [--obsidian-vault ~/Documents/Obsidian]

# Analyze historical trends for a hive
buzzboard trends H07 [--obsidian-vault ~/Documents/Obsidian]

# View Kanban board with task status
buzzboard board

# View event log for a specific task
buzzboard events H07_2026-06-06

# Show current configuration + pipeline status
buzzboard status
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
| `BUZZBOARD_OLLAMA_MODEL` | `llama3.1:8b` | LLM for Splitter, Editor, Extractor, Trend agents |
| `BUZZBOARD_OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `BUZZBOARD_INBOX_DIR` | `inbox` | Where voice memos land |
| `BUZZBOARD_PIPELINE_DIR` | `pipeline` | JSON artifacts between agents |
| `BUZZBOARD_ARCHIVE_DIR` | `archive` | Processed audio moved here |
| `BUZZBOARD_WHISPER_MODEL` | `medium` | Whisper size: tiny/base/small/medium/large |
| `BUZZBOARD_WHISPER_BACKEND` | `whisper` | `whisper` (Python) or `whisper-cpp` (faster CLI) |
| `BUZZBOARD_KANBAN_DB` | `pipeline/kanban.db` | SQLite Kanban database path |

## Requirements

- **Python 3.11+**
- **[Ollama](https://ollama.com)** with a model pulled (default `llama3.1:8b`)
- **[Whisper](https://github.com/openai/whisper)** for speech-to-text
- **[Obsidian](https://obsidian.md)** for note storage (optional — pipeline works without it)

### Hardware Recommendations

BuzzBoard runs on Apple Silicon natively. RAM requirements scale with the model sizes you choose:

| Whisper model | RAM needed | Speed (1-min audio, M-series) | Notes |
|---|---|---|---|
| `tiny` / `base` | ~2 GB | ~10-20 sec | Fastest; lower transcription accuracy |
| `small` | ~3 GB | ~30-60 sec | Reasonable middle ground |
| **`medium`** *(default)* | ~5 GB | ~1-2 min | Best accuracy-to-speed for 16 GB machines |
| `large` | ~10 GB | ~3-5 min | Maximum accuracy; needs ≥24 GB RAM |

| Ollama model | RAM needed | Notes |
|---|---|---|
| `llama3.2:3b` | ~2 GB | Good on 16 GB machines |
| **`llama3.1:8b`** *(default)* | ~5 GB | Better quality; needs ≥16 GB |
| `llama3.1:70b` | ~40 GB | Workstation-class only |

**Practical minimum (16 GB unified memory):**
- Mac mini M2 / MacBook Air M2: works with `medium` Whisper + `llama3.2:3b` Ollama. Slow but reliable.
- MacBook Pro M3 / Mac mini M2 Pro (16 GB): runs `medium` + `llama3.1:8b` comfortably — this is the sweet spot for typical beekeeping use.

**Recommended (24 GB+):**
- Mac mini M2 Pro / M4 Pro, MacBook Pro M3 Pro / M4 Pro: `medium` Whisper + `llama3.1:8b` with headroom for parallel browser/Obsidian usage.

**Workstation (48 GB+):**
- Mac Studio M2 Ultra / M4 Max: enables `large` Whisper + `llama3.1:8b` for maximum transcription accuracy and faster LLM inference.

> Whisper uses the Apple Neural Engine for fast transcription on M-series chips. Intel Macs are unsupported — Whisper falls back to CPU and is significantly slower.

## Development

```bash
pip install -e ".[dev]"
pytest                    # 61 tests, all passing
ruff check src/           # Lint
```

## License

MIT.