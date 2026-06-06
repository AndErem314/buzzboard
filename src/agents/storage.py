"""
StorageAgent — writes inspection records to an Obsidian vault.

Phase 3 implementation.
Takes a StructuredRecord + CleanedNote and writes them as markdown files
inside the Obsidian vault, organized by hive:
    {vault}/Hives/H{NN}/YYYY-MM-DD.md

Each note uses YAML frontmatter for Dataview compatibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BuzzAgent


class StorageAgent(BuzzAgent):
    """Structured record → Obsidian vault markdown."""

    def __init__(
        self,
        obsidian_vault: Path,
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="storage", pipeline_dir=pipeline_dir)
        self.vault = obsidian_vault

    def process(self, input_path: Path) -> Path:
        raise NotImplementedError("StorageAgent — Phase 3")
