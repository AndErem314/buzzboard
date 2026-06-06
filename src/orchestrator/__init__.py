"""
BuzzBoard Orchestrator — file watcher + Kanban engine.

Phase 3 implementation.
Watches inbox/ for new voice memos, creates Kanban cards for each stage
of the pipeline, and tracks status through to completion.
"""

from __future__ import annotations


class Orchestrator:
    """File-system watcher + Kanban task router."""

    def __init__(self, inbox_dir: str = "inbox"):
        self.inbox_dir = inbox_dir

    def start(self):
        raise NotImplementedError("Orchestrator — Phase 3")
