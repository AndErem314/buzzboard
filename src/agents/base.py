"""
Abstract base class for all BuzzBoard agents.

Every agent in the pipeline inherits from BuzzAgent.  This enforces:
  - Consistent JSON-in / JSON-out handoffs
  - Content hashing for audit-trail integrity
  - A uniform process(input_path) → output_path contract

To add a new agent: subclass BuzzAgent, implement process(), done.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..schema import PipelineArtifact


class BuzzAgent(ABC):
    """
    Base agent that enforces the BuzzBoard handoff protocol.

    Subclass and implement ``process(input_path) -> output_path``.
    The base class handles artifact tracking, hashing, and JSON I/O.

    Lifecycle per run:
        1. load_input(input_path)  → dict
        2. process(input_path)     → Path (your logic)
        3. _track_artifact(...)    → PipelineArtifact (auto)
    """

    def __init__(self, name: str, pipeline_dir: Optional[Path] = None):
        self.name = name
        self.pipeline_dir = pipeline_dir or Path("pipeline")

    # ── Public API ──────────────────────────────────────────────────────────

    def run(self, input_path: Path) -> tuple[Path, PipelineArtifact]:
        """
        Execute the agent on an input artifact.

        Returns (output_path, artifact) so callers can chain agents.
        """
        start = time.perf_counter()
        output_path = self.process(input_path)
        elapsed_ms = (time.perf_counter() - start) * 1000

        artifact = self._track_artifact(
            input_path=str(input_path),
            output_path=str(output_path),
            duration_ms=elapsed_ms,
        )
        return output_path, artifact

    @abstractmethod
    def process(self, input_path: Path) -> Path:
        """
        Transform input → output.  Concrete agents implement this.

        Args:
            input_path: Path to the input JSON artifact from the upstream agent
                        (or the raw audio file for the Transcriber).

        Returns:
            Path to the output JSON artifact.
        """
        ...

    # ── JSON I/O helpers ────────────────────────────────────────────────────

    @staticmethod
    def load_json(path: Path) -> dict:
        """Read a JSON artifact into a dict."""
        return json.loads(path.read_text())

    @staticmethod
    def write_json(data: dict, output_dir: Path, prefix: str = "artifact") -> tuple[Path, str]:
        """Write dict as JSON, return (path, content_hash)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2, default=str)
        file_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        out_path = output_dir / f"{prefix}_{file_hash}.json"
        out_path.write_text(content)
        return out_path, file_hash

    # ── Internal ────────────────────────────────────────────────────────────

    def _track_artifact(
        self,
        input_path: str,
        output_path: str,
        duration_ms: float,
    ) -> PipelineArtifact:
        """Record this run as a PipelineArtifact for the audit trail."""
        content = Path(output_path).read_text() if Path(output_path).exists() else ""
        return PipelineArtifact.from_content(
            content=content,
            stage=self.name,
            agent=self.__class__.__name__,
            input_path=input_path,
            output_path=output_path,
            duration_ms=duration_ms,
            hive_id="unknown",  # overridden per agent
        )
