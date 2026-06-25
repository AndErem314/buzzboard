"""
BuzzBoard Dashboard — FastAPI web UI for the Kanban board.

Serves:
  /             HTML dashboard (static/index.html)
  /static/*     CSS, JS, and other assets
  /api/board    JSON: all tasks grouped by stage
  /api/tasks/{id}  JSON: task details + event log
  /api/stats    JSON: board statistics
  /api/hives/{id}  JSON: hive inspection history

All UI files live under `static/` — see static/index.html, style.css,
app.js. No HTML or JS is embedded in this module, so a designer can
iterate on the UI without touching Python.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..db.kanban import KanbanBoard
from .. import config as cfg


# ── Paths ────────────────────────────────────────────────────────────────
# `static/` lives next to this server.py file so the dashboard works
# regardless of the process's CWD.

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


# ── FastAPI app ───────────────────────────────────────────────────────────

app = FastAPI(
    title="BuzzBoard Dashboard",
    description="Multi-agent beehive inspection pipeline monitor",
    version="0.2.0",
)

board = KanbanBoard(str(cfg.KANBAN_DB))


# ── API endpoints ─────────────────────────────────────────────────────────

@app.get("/api/board")
def api_board():
    """Return all tasks grouped by stage."""
    tasks = board.get_all_tasks()
    by_stage: dict[str, list[dict]] = {
        s: [] for s in ["inbox", "transcribing", "editing", "extracting", "storing", "done", "failed"]
    }
    for t in tasks:
        stage = t.get("stage", "inbox")
        if stage in by_stage:
            by_stage[stage].append(t)
    return {"stages": by_stage, "stats": board.get_stats()}


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str):
    """Return task details + full event log."""
    task = board.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    events = board.get_events(task_id)
    return {"task": task, "events": events}


@app.get("/api/stats")
def api_stats():
    """Return board-level statistics."""
    return board.get_stats()


@app.get("/api/hives/{hive_id}")
def api_hive(hive_id: str):
    """Return all inspections for a given hive."""
    return board.get_hive_history(hive_id)


# ── HTML / static ─────────────────────────────────────────────────────────

# Mount /static first so /  can be served as the bare index route.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the Kanban dashboard HTML from disk."""
    if not INDEX_HTML.exists():
        # Fallback: if the static dir is missing (e.g. installed via pip
        # without package_data), surface a helpful 500 instead of crashing.
        raise HTTPException(
            status_code=500,
            detail=f"Dashboard assets missing: {INDEX_HTML}",
        )
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


# ── Server runner ─────────────────────────────────────────────────────────

def run_server(
    host: str = "0.0.0.0",
    port: int = 8099,
    reload: bool = False,
    watch: bool = False,
    watch_kwargs: dict | None = None,
):
    """Start the dashboard server (blocking).

    Args:
        watch: If True, start the orchestrator watcher in a background thread.
        watch_kwargs: Extra kwargs forwarded to Orchestrator (e.g. ollama_model,
            obsidian_vault, whisper_model, poll_interval, recent_only).
    """
    if watch:
        _start_watcher(**(watch_kwargs or {}))

    import uvicorn

    uvicorn.run(
        "src.dashboard.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def _start_watcher(
    obsidian_vault: Path | None = None,
    poll_interval: float = 5.0,
    **orch_kwargs,
):
    """Launch the orchestrator watcher in a daemon background thread.

    The orchestrator runs independently — the dashboard reads the same
    Kanban DB, so UI updates appear automatically as tasks progress.
    """
    from ..orchestrator import Orchestrator

    orch = Orchestrator(
        inbox_dir=str(cfg.INBOX_DIR),
        obsidian_vault=obsidian_vault if obsidian_vault else cfg.OBSIDIAN_VAULT,
        ollama_model=orch_kwargs.get("ollama_model", cfg.OLLAMA_MODEL),
        pipeline_dir=str(cfg.PIPELINE_DIR),
        kanban_db=str(cfg.KANBAN_DB),
        whisper_backend=orch_kwargs.get("whisper_backend", cfg.WHISPER_BACKEND),
        whisper_model=orch_kwargs.get("whisper_model", cfg.WHISPER_MODEL),
    )

    def _watch_loop():
        # Small delay so the dashboard prints its banner first
        import time

        time.sleep(1.5)
        print("\n👁️  Pipeline watcher started — processing inbox/ ...\n")
        orch.run_once(recent_only=orch_kwargs.get("recent_only", True))

    thread = threading.Thread(target=_watch_loop, daemon=True)
    thread.start()