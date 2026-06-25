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


@app.get("/favicon.ico")
async def favicon():
    """Silence the browser's automatic favicon request — no 404 noise."""
    from fastapi.responses import Response
    # Tiny bee emoji as inline SVG
    return Response(
        content=(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<text y="80" font-size="80">🐝</text>'
            "</svg>"
        ),
        media_type="image/svg+xml",
    )


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

def run_server(host: str = "0.0.0.0", port: int = 8099, reload: bool = False):
    """Start the dashboard server (blocking)."""
    import uvicorn
    uvicorn.run(
        "src.dashboard.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )