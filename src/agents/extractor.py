"""
ExtractorAgent — pulls structured fields from cleaned inspection notes.

Takes a CleanedNote JSON artifact, sends it to Ollama with an extraction prompt,
and outputs a StructuredRecord with machine-readable fields (queen_seen, mite_count,
honey_frames, severity, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .base import BuzzAgent
from .ollama_client import OllamaClient
from .prompts import EXTRACTOR_SYSTEM_PROMPT, EXTRACTOR_USER_TEMPLATE
from ..schema import CleanedNote, StructuredRecord, read_artifact, write_artifact


class ExtractorAgent(BuzzAgent):
    """
    Cleaned note → StructuredRecord (LLM-powered extraction).

    Uses Ollama to pull machine-readable fields from a human-readable
    inspection note: booleans, integers, enums, and categorized lists.
    """

    def __init__(
        self,
        ollama_model: str = "llama3.1:8b",
        ollama_host: str = "http://localhost:11434",
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="extractor", pipeline_dir=pipeline_dir)
        self.ollama = OllamaClient(model=ollama_model, host=ollama_host)

    def process(self, input_path: Path) -> Path:
        """
        Read CleanedNote → call Ollama → write StructuredRecord.

        Args:
            input_path: Path to a CleanedNote JSON artifact.

        Returns:
            Path to the output StructuredRecord JSON artifact.
        """
        # 1. Load input
        note = read_artifact(input_path, CleanedNote)

        print(f"  🔍 Extractor: {note.hive_id} — {note.inspection_date}")

        # 2. Build prompt — pass the full cleaned note as context
        cleaned_text = note.model_dump_json(indent=2)
        user_prompt = EXTRACTOR_USER_TEMPLATE.format(
            hive_id=note.hive_id,
            inspection_date=note.inspection_date.isoformat(),
            cleaned_note=cleaned_text,
        )

        # 3. Call Ollama
        try:
            response_text = self.ollama.chat(
                system=EXTRACTOR_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=0.0,  # zero temperature for extraction = deterministic
            )
        except ConnectionError as e:
            raise RuntimeError(
                f"ExtractorAgent needs Ollama. {e}\n"
                f"Install: brew install ollama && ollama serve\n"
                f"Pull model: ollama pull {self.ollama.model}"
            )

        # 4. Parse response into StructuredRecord
        record = self._parse_response(response_text, note.hive_id, note.inspection_date)

        # 5. Write output
        output_path, content_hash = write_artifact(record, self.pipeline_dir)

        print(f"     Queen seen: {record.queen_seen}  |  "
              f"Mites: {record.mite_count or 'N/A'}  |  "
              f"Honey frames: {record.honey_frames or 'N/A'}")
        print(f"     Severity: {record.severity or 'normal'}  |  "
              f"Next inspection: {record.next_inspection_days or 'N/A'}d  |  "
              f"Hash: {content_hash}")

        return output_path

    def _parse_response(
        self, text: str, hive_id: str, inspection_date
    ) -> StructuredRecord:
        """Parse LLM JSON response into a StructuredRecord, with fallback."""
        try:
            data = json.loads(text)
            # Normalize date: LLMs return strings, Pydantic wants date objects
            data = _normalize_extraction_dates(data, inspection_date)
            data.setdefault("hive_id", hive_id)
            data.setdefault("issues", [])
            data.setdefault("actions_required", [])
            return StructuredRecord(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"     ⚠️  JSON parse failed: {e}")
            return StructuredRecord(
                hive_id=hive_id,
                inspection_date=inspection_date,
                issues=["LLM extraction failed — see cleaned note"],
            )


def _normalize_extraction_dates(data: dict, fallback_date) -> dict:
    """Convert string dates to date objects for StructuredRecord."""
    from datetime import date as date_type

    raw = data.get("inspection_date")
    if isinstance(raw, str):
        try:
            data["inspection_date"] = date_type.fromisoformat(raw)
        except ValueError:
            data["inspection_date"] = fallback_date
    elif raw is None:
        data["inspection_date"] = fallback_date
    return data
