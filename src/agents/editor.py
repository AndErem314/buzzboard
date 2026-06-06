"""
EditorAgent — cleans and structures raw transcripts using an LLM (Ollama).

Takes a RawTranscript JSON artifact, sends it to Ollama with a beekeeping-specific
prompt, and outputs a CleanedNote with sections for Observations, Issues, Actions,
Queen Status, Brood Pattern, Honey Stores, and Temperament.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .base import BuzzAgent
from .ollama_client import OllamaClient
from .prompts import EDITOR_SYSTEM_PROMPT, EDITOR_USER_TEMPLATE
from ..schema import CleanedNote, RawTranscript, read_artifact, write_artifact


class EditorAgent(BuzzAgent):
    """
    Raw transcript → structured inspection note (LLM-powered).

    Uses Ollama to transform messy voice transcripts into clean, well-organized
    beekeeping inspection notes with standardized terminology.
    """

    def __init__(
        self,
        ollama_model: str = "llama3.1:8b",
        ollama_host: str = "http://localhost:11434",
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="editor", pipeline_dir=pipeline_dir)
        self.ollama = OllamaClient(model=ollama_model, host=ollama_host)

    def process(self, input_path: Path) -> Path:
        """
        Read RawTranscript → call Ollama → write CleanedNote.

        Args:
            input_path: Path to a RawTranscript JSON artifact.

        Returns:
            Path to the output CleanedNote JSON artifact.
        """
        # 1. Load input
        raw = read_artifact(input_path, RawTranscript)

        print(f"  📝 Editor: {raw.hive_id} — {raw.inspection_date}")
        print(f"     Raw chars: {len(raw.raw_text)}")

        # 2. Build prompt
        user_prompt = EDITOR_USER_TEMPLATE.format(
            hive_id=raw.hive_id,
            inspection_date=raw.inspection_date.isoformat(),
            raw_text=raw.raw_text,
        )

        # 3. Call Ollama
        try:
            response_text = self.ollama.chat(
                system=EDITOR_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=0.1,
            )
        except ConnectionError as e:
            raise RuntimeError(
                f"EditorAgent needs Ollama. {e}\n"
                f"Install: brew install ollama && ollama serve\n"
                f"Pull model: ollama pull {self.ollama.model}"
            )

        # 4. Parse response into CleanedNote
        cleaned = self._parse_response(response_text, raw.hive_id, raw.inspection_date)

        # 5. Attach reference back to raw transcript
        cleaned.raw_reference = self._hash_content(raw.raw_text)

        # 6. Write output
        output_path, content_hash = write_artifact(cleaned, self.pipeline_dir)

        print(f"     Sections: observations={bool(cleaned.observations)}, "
              f"issues={len(cleaned.issues)}, actions={len(cleaned.actions)}")
        print(f"     Queen: {cleaned.queen_status or 'N/A'}  |  "
              f"Brood: {cleaned.brood_pattern or 'N/A'}  |  "
              f"Hash: {content_hash}")

        return output_path

    def _parse_response(
        self, text: str, hive_id: str, inspection_date
    ) -> CleanedNote:
        """Parse LLM JSON response into a CleanedNote, with fallback."""
        try:
            data = json.loads(text)
            # Normalize date: LLMs return strings, Pydantic wants date objects
            data = _normalize_dates(data, inspection_date)
            # Ensure required fields are present
            data.setdefault("hive_id", hive_id)
            data.setdefault("observations", text[:500])  # fallback: use raw text
            data.setdefault("issues", [])
            data.setdefault("actions", [])
            data.setdefault("swarm_indicators", [])
            data.setdefault("raw_reference", "")  # LLM can't provide this
            return CleanedNote(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            # Graceful degradation: wrap raw response as observations
            print(f"     ⚠️  JSON parse failed, using raw response as observations")
            return CleanedNote(
                hive_id=hive_id,
                inspection_date=inspection_date,
                observations=text[:2000],
                raw_reference="",
            )

    @staticmethod
    def _hash_content(text: str) -> str:
        import hashlib
        return hashlib.sha256(text.encode()).hexdigest()[:12]


def _normalize_dates(data: dict, fallback_date) -> dict:
    """Convert string dates to date objects. LLMs return strings; Pydantic needs date."""
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
