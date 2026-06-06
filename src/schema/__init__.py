"""
BuzzBoard data contracts.

Every agent reads and writes these Pydantic models — this is the protocol
that guarantees consistent handoffs through the multi-agent pipeline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class RawTranscript(BaseModel):
    """Agent 1 (Transcriber) output: raw voice-to-text transcript."""

    audio_file: str = Field(description="Original audio filename, e.g. H07_2026-06-06.m4a")
    hive_id: str = Field(description="Hive identifier, e.g. H07")
    inspection_date: date = Field(description="Date of inspection")
    raw_text: str = Field(description="Verbatim transcription from Whisper")
    duration_seconds: float = Field(default=0.0, description="Audio duration in seconds")
    transcribed_at: datetime = Field(
        default_factory=datetime.now, description="When transcription completed"
    )

    @classmethod
    def parse_filename(cls, audio_path: Path) -> tuple[str, date]:
        """
        Extract hive_id and date from filenames like 'H07_2026-06-06.m4a'
        or 'H12_20260606_1430.m4a'.
        """
        import re

        stem = audio_path.stem
        # Pattern: H<digits>_YYYY-MM-DD (with optional _HHMM suffix)
        match = re.match(r"(H\d+)_(\d{4}-\d{2}-\d{2})(?:_\d{4})?", stem)
        if not match:
            raise ValueError(
                f"Cannot parse filename '{audio_path.name}'. "
                f"Expected format: H<number>_YYYY-MM-DD.ext (e.g. H07_2026-06-06.m4a)"
            )
        return match.group(1), date.fromisoformat(match.group(2))


class CleanedNote(BaseModel):
    """Agent 2 (Editor) output: LLM-cleaned, structured inspection note."""

    hive_id: str
    inspection_date: date
    observations: str = Field(description="General observations from the inspection")
    issues: list[str] = Field(default_factory=list, description="Problems found")
    actions: list[str] = Field(default_factory=list, description="Actions to take")
    queen_status: Optional[str] = Field(
        default=None, description="One of: seen, not_seen, cells_present, supersedure"
    )
    brood_pattern: Optional[str] = Field(
        default=None, description="One of: solid, spotty, drone_layer, none"
    )
    honey_stores: Optional[str] = Field(
        default=None, description="One of: abundant, adequate, low, empty"
    )
    pollen_stores: Optional[str] = Field(
        default=None, description="One of: abundant, adequate, low, empty"
    )
    temperament: Optional[str] = Field(
        default=None, description="One of: calm, nervous, aggressive, defensive"
    )
    swarm_indicators: list[str] = Field(
        default_factory=list, description="Queen cells, congestion, etc."
    )
    raw_reference: str = Field(description="Hash reference back to the raw transcript")
    cleaned_at: datetime = Field(default_factory=datetime.now)


class StructuredRecord(BaseModel):
    """Agent 3 (Extractor) output: machine-readable structured fields."""

    hive_id: str
    inspection_date: date
    queen_seen: bool = Field(default=False)
    brood_health: Optional[str] = Field(default=None)
    mite_count: Optional[int] = Field(default=None)
    honey_frames: Optional[int] = Field(default=None)
    issues: list[str] = Field(default_factory=list)
    actions_required: list[str] = Field(default_factory=list)
    next_inspection_days: Optional[int] = Field(
        default=None, description="Recommended days until next inspection"
    )
    severity: Optional[str] = Field(
        default=None, description="normal, attention, urgent"
    )
    extracted_at: datetime = Field(default_factory=datetime.now)


class PipelineArtifact(BaseModel):
    """Generic container for tracking artifacts through the pipeline."""

    artifact_id: str = Field(description="Unique hash of artifact content")
    stage: str = Field(description="transcribe | edit | extract | store")
    hive_id: str
    input_path: str
    output_path: str
    agent: str
    duration_ms: float
    created_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_content(cls, content: str, stage: str, agent: str, **kwargs) -> "PipelineArtifact":
        artifact_id = hashlib.sha256(content.encode()).hexdigest()[:12]
        return cls(artifact_id=artifact_id, stage=stage, agent=agent, **kwargs)


# ── Helper: read/write JSON artifacts ──────────────────────────────────────

def write_artifact(data: BaseModel, output_dir: Path) -> tuple[Path, str]:
    """Serialize a Pydantic model to JSON and return (path, content_hash)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    content = data.model_dump_json(indent=2)
    file_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
    model_name = type(data).__name__.lower()
    out_path = output_dir / f"{model_name}_{file_hash}.json"
    out_path.write_text(content)
    return out_path, file_hash


def read_artifact(path: Path, model_cls: type[BaseModel]) -> BaseModel:
    """Deserialize a JSON artifact back into its Pydantic model."""
    return model_cls.model_validate_json(path.read_text())
