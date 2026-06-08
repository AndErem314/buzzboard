"""
BuzzBoard configuration — all paths and settings via environment variables.

Load a .env file (if present) and expose typed config values.
Every BuzzBoard component reads from here — no hardcoded paths.

Environment variables:
    BUZZBOARD_INBOX_DIR        Voice memos land here       (default: ./inbox)
    BUZZBOARD_PIPELINE_DIR     Pipeline artifacts          (default: ./pipeline)
    BUZZBOARD_ARCHIVE_DIR      Processed audio moved here  (default: ./archive)
    BUZZBOARD_OBSIDIAN_VAULT   Path to Obsidian vault      (default: unset)
    BUZZBOARD_OLLAMA_MODEL     Ollama model name           (default: llama3.1:8b)
    BUZZBOARD_OLLAMA_HOST      Ollama API URL              (default: http://localhost:11434)
    BUZZBOARD_WHISPER_MODEL    Whisper model size          (default: base)
    BUZZBOARD_WHISPER_BACKEND  whisper or whisper-cpp      (default: whisper)
    BUZZBOARD_KANBAN_DB        Kanban SQLite database      (default: ./pipeline/kanban.db)
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env file from project root if it exists. Runs once at import."""
    env_file = Path.cwd() / ".env"
    if not env_file.exists():
        # Try project root relative to this file
        env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()


# ── Paths ───────────────────────────────────────────────────────────────────

INBOX_DIR = Path(os.getenv("BUZZBOARD_INBOX_DIR", "inbox"))
PIPELINE_DIR = Path(os.getenv("BUZZBOARD_PIPELINE_DIR", "pipeline"))
ARCHIVE_DIR = Path(os.getenv("BUZZBOARD_ARCHIVE_DIR", "archive"))

_obsidian_raw = os.getenv("BUZZBOARD_OBSIDIAN_VAULT", "")
OBSIDIAN_VAULT = Path(_obsidian_raw) if _obsidian_raw else None

KANBAN_DB = Path(os.getenv("BUZZBOARD_KANBAN_DB", "pipeline/kanban.db"))

# ── Models ──────────────────────────────────────────────────────────────────

OLLAMA_MODEL = os.getenv("BUZZBOARD_OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_HOST = os.getenv("BUZZBOARD_OLLAMA_HOST", "http://localhost:11434")

WHISPER_MODEL = os.getenv("BUZZBOARD_WHISPER_MODEL", "medium")
WHISPER_BACKEND = os.getenv("BUZZBOARD_WHISPER_BACKEND", "whisper")


# ── Convenience ─────────────────────────────────────────────────────────────

def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def print_config() -> str:
    """Return a human-readable config summary."""
    lines = [
        "🐝 BuzzBoard Configuration",
        "=" * 40,
        f"  Inbox:        {INBOX_DIR.absolute()}",
        f"  Pipeline:     {PIPELINE_DIR.absolute()}",
        f"  Archive:      {ARCHIVE_DIR.absolute()}",
        f"  Obsidian:     {OBSIDIAN_VAULT.absolute() if OBSIDIAN_VAULT else '(not set)'}",
        f"  Kanban DB:    {KANBAN_DB}",
        f"  Ollama model: {OLLAMA_MODEL}",
        f"  Ollama host:  {OLLAMA_HOST}",
        f"  Whisper:      {WHISPER_BACKEND}/{WHISPER_MODEL}",
    ]
    return "\n".join(lines)
