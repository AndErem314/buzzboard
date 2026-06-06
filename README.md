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
# Install
git clone https://github.com/AndErem314/buzzboard.git
cd buzzboard
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[whisper]"

# Transcribe a voice memo
buzzboard transcribe inbox/H07_2026-06-06.m4a

# Run the full pipeline (coming in Phase 2+)
buzzboard process inbox/H07_2026-06-06.m4a
```

### Requirements

- Python 3.11+
- [Whisper](https://github.com/openai/whisper) (for transcription)
- [Ollama](https://ollama.com) (for LLM agents — Phase 2+)
- [Obsidian](https://obsidian.md) (for note storage — Phase 3+)

Runs on **16 GB RAM** with quantized models. Native Apple Silicon support via Neural Engine.

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
