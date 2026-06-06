"""
BuzzBoard Kanban Engine — SQLite-backed board + audit trail.

Tracks every voice memo through the multi-agent pipeline:
  inbox → transcribing → editing → extracting → storing → done

Each task row carries: hive_id, date, current stage, timestamps, events.
The event log records every agent action with input/output hashes.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


STAGES = ["inbox", "transcribing", "editing", "extracting", "storing", "done", "failed"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,          -- e.g. "H07_2026-06-06"
    hive_id     TEXT NOT NULL,
    audio_file  TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT 'inbox',
    priority    INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    completed_at TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    agent       TEXT NOT NULL,             -- transcriber | editor | extractor | storage
    action      TEXT NOT NULL,             -- started | completed | failed
    input_hash  TEXT,
    output_hash TEXT,
    duration_ms REAL,
    details     TEXT,                      -- free-form JSON or notes
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_stage ON tasks(stage);
CREATE INDEX IF NOT EXISTS idx_tasks_hive ON tasks(hive_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent);
"""


class KanbanBoard:
    """
    SQLite-backed Kanban board for the BuzzBoard pipeline.

    Usage:
        board = KanbanBoard("pipeline/kanban.db")
        board.create_task("H07_2026-06-06", "H07", "H07_2026-06-06.m4a")
        board.move_to("H07_2026-06-06", "transcribing")
        board.log_event("H07_2026-06-06", "transcriber", "started", ...)
    """

    def __init__(self, db_path: Path | str = "pipeline/kanban.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    # ── Task lifecycle ──────────────────────────────────────────────────────

    def create_task(self, task_id: str, hive_id: str, audio_file: str) -> str:
        """Register a new voice memo. Returns task_id."""
        now = datetime.now().isoformat()
        self._conn.execute(
            """INSERT OR IGNORE INTO tasks (id, hive_id, audio_file, stage, created_at, updated_at)
               VALUES (?, ?, ?, 'inbox', ?, ?)""",
            (task_id, hive_id, audio_file, now, now),
        )
        self._conn.commit()
        return task_id

    def move_to(self, task_id: str, stage: str):
        """Transition a task to a new stage."""
        if stage not in STAGES:
            raise ValueError(f"Unknown stage: {stage}. Must be one of {STAGES}")
        now = datetime.now().isoformat()
        updates = {"stage": stage, "updated_at": now}
        if stage == "done":
            updates["completed_at"] = now
        elif stage == "failed":
            updates["completed_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        self._conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?", values
        )
        self._conn.commit()

    def fail_task(self, task_id: str, error: str):
        """Mark a task as failed with an error message."""
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE tasks SET stage = 'failed', error = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (error[:500], now, now, task_id),
        )
        self._conn.commit()

    # ── Event log ───────────────────────────────────────────────────────────

    def log_event(
        self,
        task_id: str,
        agent: str,
        action: str,
        input_hash: str = "",
        output_hash: str = "",
        duration_ms: float = 0.0,
        details: str = "",
    ):
        """Record an agent action in the audit trail."""
        now = datetime.now().isoformat()
        self._conn.execute(
            """INSERT INTO events (task_id, agent, action, input_hash, output_hash, duration_ms, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, agent, action, input_hash, output_hash, duration_ms, details, now),
        )
        self._conn.commit()

    # ── Queries ─────────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get a single task by ID."""
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def get_tasks_by_stage(self, stage: str) -> list[dict]:
        """List all tasks in a given stage."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE stage = ? ORDER BY created_at DESC", (stage,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_tasks(self) -> list[dict]:
        """List all tasks, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events(self, task_id: str) -> list[dict]:
        """Get the full event log for a task."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Return board-level statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        by_stage = {}
        for row in self._conn.execute(
            "SELECT stage, COUNT(*) as cnt FROM tasks GROUP BY stage"
        ).fetchall():
            by_stage[row["stage"]] = row["cnt"]

        total_events = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        # Average pipeline duration for completed tasks
        avg_dur = self._conn.execute(
            """SELECT AVG(
                   (julianday(completed_at) - julianday(created_at)) * 86400
               ) FROM tasks WHERE stage = 'done'"""
        ).fetchone()[0]

        return {
            "total_tasks": total,
            "by_stage": by_stage,
            "total_events": total_events,
            "avg_duration_seconds": round(avg_dur, 1) if avg_dur else None,
        }

    def get_hive_history(self, hive_id: str) -> list[dict]:
        """Get all tasks for a specific hive, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE hive_id = ? ORDER BY created_at DESC",
            (hive_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Display ─────────────────────────────────────────────────────────────

    def print_board(self) -> str:
        """Render the Kanban board as a text table."""
        lines = []
        lines.append("🐝 BuzzBoard Kanban")
        lines.append("=" * 70)
        lines.append(f"{'Stage':<16} {'Count':>6}  {'Latest Task':<40}")
        lines.append("-" * 70)

        for stage in STAGES:
            tasks = self.get_tasks_by_stage(stage)
            count = len(tasks)
            latest = tasks[0]["id"] if tasks else "—"
            lines.append(f"{stage:<16} {count:>6}  {latest:<40}")

        lines.append("-" * 70)
        stats = self.get_stats()
        lines.append(f"Total tasks: {stats['total_tasks']}  |  "
                     f"Events logged: {stats['total_events']}  |  "
                     f"Avg duration: {stats['avg_duration_seconds'] or 'N/A'}s")
        return "\n".join(lines)

    def close(self):
        self._conn.close()
