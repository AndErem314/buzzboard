# 🐝 BuzzBoard

**Multi-agent beehive inspection assistant — voice memos → structured Obsidian notes via local LLMs.**

Drop a voice memo from your hive inspection into `inbox/`. BuzzBoard's agent pipeline transcribes it, structures the content, extracts key data points, and writes a formatted note to your Obsidian vault — organized by hive.

> **Status:** ✅ Phase 3 — full pipeline + Kanban board + file watcher + Obsidian integration. Dashboard and trend analysis coming in Phases 4–7.

---

## Architecture

```
Voice Memo (inbox/H07_2026-06-06.m4a)
         │
    ┌────▼────┐     ┌────────┐     ┌──────────┐     ┌─────────┐
    │Transcriber│ ──▶│ Editor │ ──▶ │Extractor│ ──▶ │ Storage  │
    │  Agent   │     │ Agent  │     │  Agent  │     │  Agent   │
    └─────────┘     └────────┘     └──────────┘     └─────────┘
    Whisper STT      LLM clean      LLM extract      Obsidian
```

Each agent reads a JSON artifact from the previous agent and writes its output as a new JSON artifact — a clean, auditable pipeline with content hashing at every step.

## Quick Start

```bash
# 1. Clone + install
git clone https://github.com/AndErem314/buzzboard.git
cd buzzboard
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[whisper]"

# 2. Configure (copy + edit)
cp .env.example .env
# Edit BUZZBOARD_OBSIDIAN_VAULT to point to your Obsidian vault

# 3. Verify
buzzboard config

# 4. Process a voice memo
buzzboard process inbox/H07_2026-06-06.m4a

# 5. Or watch inbox/ and auto-process everything
buzzboard watch --once
```

## Configuration

All paths and models are set via a `.env` file (or environment variables).  
None are committed to git — each user creates their own.

| Variable | Default | Description |
|---|---|---|
| `BUZZBOARD_INBOX_DIR` | `inbox` | Where voice memos land |
| `BUZZBOARD_PIPELINE_DIR` | `pipeline` | JSON artifacts between agents |
| `BUZZBOARD_ARCHIVE_DIR` | `archive` | Processed audio moved here |
| `BUZZBOARD_OBSIDIAN_VAULT` | *(required)* | Path to your Obsidian vault |
| `BUZZBOARD_KANBAN_DB` | `pipeline/kanban.db` | SQLite Kanban database |
| `BUZZBOARD_OLLAMA_MODEL` | `llama3.1:8b` | LLM for Editor + Extractor |
| `BUZZBOARD_OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `BUZZBOARD_WHISPER_MODEL` | `base` | Whisper model size |
| `BUZZBOARD_WHISPER_BACKEND` | `whisper` | `whisper` or `whisper-cpp` |

See `.env.example` for the full template with comments.

### Requirements

- Python 3.11+
- [Ollama](https://ollama.com) with a model pulled (`ollama pull llama3.1:8b`)
- [Whisper](https://github.com/openai/whisper) (for transcription)
- [Obsidian](https://obsidian.md) (for note storage)

Runs on **16 GB RAM** with quantized models (`llama3.2:3b`).  
Native Apple Silicon support via Neural Engine.

## Agents

| Agent | Phase | Does | Model |
|---|---|---|---|
| **Transcriber** | ✅ Phase 1 | Voice → raw text | Whisper (base/small) |
| **Editor** | ✅ Phase 2 | Raw text → structured note | Ollama (llama3.1:8b / llama3.2:3b) |
| **Extractor** | ✅ Phase 2 | Note → structured data | Ollama (llama3.1:8b / llama3.2:3b) |
| **Storage** | ✅ Phase 3 | Data → Obsidian markdown | — |
| **Orchestrator** | ✅ Phase 3 | File watcher + Kanban routing | — |
| **Dashboard** | 🔜 Phase 4 | Web UI for board | FastAPI |
| **Trend** | 🔜 Phase 7 | Pattern detection + alerts | Ollama |

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/
```

## License

MIT — see [LICENSE](LICENSE) file.
