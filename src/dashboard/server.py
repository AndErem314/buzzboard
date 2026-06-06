"""
BuzzBoard Dashboard — FastAPI web UI for the Kanban board.

Serves:
  /               HTML dashboard with live Kanban board
  /api/board      JSON: all tasks grouped by stage
  /api/tasks/{id} JSON: task details + event log
  /api/stats      JSON: board statistics
  /api/hives/{id} JSON: hive inspection history
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..db.kanban import KanbanBoard
from .. import config as cfg


# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="BuzzBoard Dashboard",
    description="Multi-agent beehive inspection pipeline monitor",
    version="0.1.0",
)

board = KanbanBoard(str(cfg.KANBAN_DB))


# ── API endpoints ───────────────────────────────────────────────────────────

@app.get("/api/board")
def api_board():
    """Return all tasks grouped by stage."""
    tasks = board.get_all_tasks()
    by_stage: dict[str, list[dict]] = {s: [] for s in ["inbox", "transcribing", "editing", "extracting", "storing", "done", "failed"]}
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


# ── HTML dashboard ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the Kanban dashboard HTML."""
    return HTML_TEMPLATE


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🐝 BuzzBoard Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
h1 { font-size: 1.6em; margin-bottom: 10px; }
h1 span { font-size: 0.6em; color: #888; }
.board { display: grid; grid-template-columns: repeat(7, 1fr); gap: 12px; margin: 20px 0; }
.column { background: #16213e; border-radius: 10px; padding: 12px; min-height: 120px; }
.column h3 { font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 2px solid #0f3460; }
.column h3 .count { float: right; background: #0f3460; padding: 2px 8px; border-radius: 10px; font-size: 0.85em; }
.card { background: #1f4068; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer; font-size: 0.8em; transition: background 0.15s; }
.card:hover { background: #2663a3; }
.card .id { font-weight: 600; }
.card .time { font-size: 0.75em; color: #999; margin-top: 3px; }
.card.failed { border-left: 3px solid #e74c3c; }
.card.done { border-left: 3px solid #2ecc71; }
.card.active { border-left: 3px solid #f39c12; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
.stats { display: flex; gap: 20px; margin-bottom: 20px; }
.stat { background: #16213e; border-radius: 8px; padding: 12px 18px; }
.stat .value { font-size: 1.8em; font-weight: 700; }
.stat .label { font-size: 0.75em; color: #888; }
.task-detail { background: #16213e; border-radius: 10px; padding: 16px; margin-top: 20px; display: none; }
.task-detail.visible { display: block; }
.task-detail h2 { margin-bottom: 10px; }
.events-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.85em; }
.events-table th { text-align: left; padding: 6px 10px; background: #0f3460; }
.events-table td { padding: 6px 10px; border-bottom: 1px solid #0f3460; }
.refresh { font-size: 0.75em; color: #666; margin-top: 20px; text-align: center; }
.error { color: #e74c3c; }
.hive-select { margin-bottom: 12px; }
.hive-select select { background: #1f4068; color: #e0e0e0; border: 1px solid #0f3460; padding: 4px 8px; border-radius: 4px; }
</style>
</head>
<body>
<h1>🐝 BuzzBoard <span>Kanban Dashboard</span></h1>

<div class="stats" id="stats"></div>

<div class="board" id="board"></div>

<div class="task-detail" id="detail">
    <h2 id="detail-title"></h2>
    <div id="detail-meta"></div>
    <table class="events-table" id="events-table">
        <thead><tr><th>Agent</th><th>Action</th><th>Duration</th><th>Time</th></tr></thead>
        <tbody id="events-body"></tbody>
    </table>
</div>

<div class="refresh">Auto-refreshes every 10s · <span id="refresh-countdown"></span></div>

<script>
const STAGES = ["inbox", "transcribing", "editing", "extracting", "storing", "done", "failed"];
const STAGE_LABELS = {
    inbox: "📥 Inbox", transcribing: "🎙️ Transcribing", editing: "✏️ Editing",
    extracting: "🔍 Extracting", storing: "📁 Storing", done: "✅ Done", failed: "❌ Failed"
};

async function load() {
    const resp = await fetch("/api/board");
    const data = await resp.json();
    renderStats(data.stats);
    renderBoard(data.stages);
}

function renderStats(stats) {
    document.getElementById("stats").innerHTML = `
        <div class="stat"><div class="value">${stats.total_tasks}</div><div class="label">Total Tasks</div></div>
        <div class="stat"><div class="value">${stats.total_events}</div><div class="label">Events Logged</div></div>
        <div class="stat"><div class="value">${stats.avg_duration_seconds ? stats.avg_duration_seconds + 's' : '—'}</div><div class="label">Avg Duration</div></div>
    `;
}

function renderBoard(stages) {
    const board = document.getElementById("board");
    board.innerHTML = STAGES.map(s => {
        const tasks = stages[s] || [];
        const count = tasks.length;
        return `<div class="column">
            <h3>${STAGE_LABELS[s]} <span class="count">${count}</span></h3>
            ${tasks.map(t => {
                let cls = "card";
                if (t.stage === "failed") cls += " failed";
                else if (t.stage === "done") cls += " done";
                else if (t.stage !== "inbox") cls += " active";
                const time = t.updated_at ? t.updated_at.slice(11, 19) : t.created_at.slice(11, 19);
                return `<div class="${cls}" onclick="showTask('${t.id}')">
                    <div class="id">${t.id}</div>
                    <div class="time">${time}</div>
                    ${t.error ? `<div class="error">⚠ ${t.error.slice(0, 50)}</div>` : ''}
                </div>`;
            }).join("")}
        </div>`;
    }).join("");
}

async function showTask(id) {
    const resp = await fetch(`/api/tasks/${id}`);
    const data = await resp.json();
    const t = data.task;
    const detail = document.getElementById("detail");
    detail.classList.add("visible");
    document.getElementById("detail-title").textContent = `${t.id} — ${t.stage}`;
    document.getElementById("detail-meta").innerHTML = `
        Hive: ${t.hive_id} · File: ${t.audio_file} · Created: ${t.created_at.slice(0, 19)}
        ${t.error ? `<br><span class="error">⚠ ${t.error.slice(0, 200)}</span>` : ''}
    `;
    document.getElementById("events-body").innerHTML = data.events.map(e =>
        `<tr>
            <td>${e.agent}</td>
            <td>${e.action}</td>
            <td>${e.duration_ms ? e.duration_ms.toFixed(0) + 'ms' : '—'}</td>
            <td>${e.created_at.slice(11, 19)}</td>
        </tr>`
    ).join("") || '<tr><td colspan="4">No events logged</td></tr>';
    detail.scrollIntoView({behavior: "smooth"});
}

// Auto-refresh
let countdown = 10;
setInterval(() => { countdown--; document.getElementById("refresh-countdown").textContent = countdown + 's'; }, 1000);
setInterval(() => { load(); countdown = 10; }, 10000);
load();
</script>
</body>
</html>"""


# ── Server runner ───────────────────────────────────────────────────────────

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
