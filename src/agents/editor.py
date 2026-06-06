"""
EditorAgent — cleans and structures raw transcripts using an LLM.

Phase 2 implementation.
Takes a RawTranscript JSON, runs it through Ollama with a beekeeping-specific
prompt, and outputs a CleanedNote with sections for Observations, Issues,
Actions, Queen Status, Brood Pattern, Honey Stores, and Temperament.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BuzzAgent


class EditorAgent(BuzzAgent):
    """Raw transcript → structured inspection note (LLM-powered)."""

    def __init__(
        self,
        ollama_model: str = "llama3.2:3b",
        ollama_host: str = "http://localhost:11434",
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="editor", pipeline_dir=pipeline_dir)
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host

    def process(self, input_path: Path) -> Path:
        raise NotImplementedError("EditorAgent — Phase 2")
