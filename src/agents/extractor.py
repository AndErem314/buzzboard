"""
ExtractorAgent — pulls structured fields from cleaned inspection notes.

Phase 2 implementation.
Takes a CleanedNote, runs it through Ollama to extract machine-readable fields
(hive_id, date, queen_seen, mite_count, honey_frames, issues, actions, severity).
Outputs a StructuredRecord JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BuzzAgent


class ExtractorAgent(BuzzAgent):
    """Cleaned note → StructuredRecord (LLM-powered extraction)."""

    def __init__(
        self,
        ollama_model: str = "llama3.2:3b",
        ollama_host: str = "http://localhost:11434",
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="extractor", pipeline_dir=pipeline_dir)
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host

    def process(self, input_path: Path) -> Path:
        raise NotImplementedError("ExtractorAgent — Phase 2")
