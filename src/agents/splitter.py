"""
HiveSplitterAgent — splits multi-hive inspection transcripts into per-hive segments.

Takes a RawTranscript artifact where the raw_text contains observations for
multiple hives, uses Ollama to identify each hive and its segment, then outputs
a separate RawTranscript artifact for each hive found.

Input:  RawTranscript JSON (with hive_id="unknown" or "multi")
Output: Multiple RawTranscript JSON artifacts (one per hive)
"""

from __future__ import annotations

import json
from datetime import date as date_type
from pathlib import Path
from typing import Optional

from .base import BuzzAgent
from .ollama_client import OllamaClient
from .prompts import SPLITTER_SYSTEM_PROMPT, SPLITTER_USER_TEMPLATE
from ..schema import RawTranscript, write_artifact


class HiveSplitterAgent(BuzzAgent):
    """
    Multi-hive transcript → per-hive RawTranscript artifacts.

    Uses Ollama to parse a single transcript into individual hive segments,
    each with its own hive_id and observation text. This enables the rest
    of the pipeline (Editor → Extractor → Storage) to process each hive
    independently.
    """

    def __init__(
        self,
        ollama_model: str = "llama3.1:8b",
        ollama_host: str = "http://localhost:11434",
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="splitter", pipeline_dir=pipeline_dir)
        self.ollama = OllamaClient(model=ollama_model, host=ollama_host)

    def process(self, input_path: Path) -> list[Path]:  # type: ignore[override]
        """
        Read a multi-hive RawTranscript → call Ollama → write per-hive RawTranscripts.

        Args:
            input_path: Path to a RawTranscript JSON artifact (multi-hive).

        Returns:
            List of Paths to per-hive RawTranscript artifacts.
        """
        # 1. Load input
        raw = BuzzAgent.load_json(Path(input_path))

        raw_text = raw.get("raw_text", "")
        original_file = raw.get("audio_file", input_path.name)

        print(f"  🔀 HiveSplitter: {original_file}")
        print(f"     Raw chars: {len(raw_text)}")

        if not raw_text.strip():
            raise ValueError("Raw transcript is empty — nothing to split")

        # 2. Build prompt
        user_prompt = SPLITTER_USER_TEMPLATE.format(raw_text=raw_text)

        # 3. Call Ollama
        try:
            response_text = self.ollama.chat(
                system=SPLITTER_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=0.0,  # deterministic splitting
                json_mode=True,
            )
        except ConnectionError as e:
            raise RuntimeError(
                f"HiveSplitterAgent needs Ollama. {e}\n"
                f"Install: brew install ollama && ollama serve\n"
                f"Pull model: ollama pull {self.ollama.model}"
            )

        # 4. Parse response into hive segments
        segments = self._parse_response(response_text, raw)

        if not segments:
            # Fallback: treat as single-hive with original hive_id
            print(f"     ⚠️  No hives detected by splitter — treating as single-hive")
            existing_hive = raw.get("hive_id", "unknown")
            segments = [{
                "hive_id": existing_hive if existing_hive != "unknown" else "H0",
                "segment_text": raw_text,
            }]

        # 5. Write per-hive RawTranscript artifacts
        output_paths = []
        for seg in segments:
            hive_id = seg["hive_id"]
            seg_text = seg["segment_text"]

            # Determine inspection date: LLM-identified date or fallback
            insp_date = self._resolve_date(seg.get("inspection_date"), raw)

            record = RawTranscript(
                audio_file=original_file,
                hive_id=hive_id,
                inspection_date=insp_date,
                raw_text=seg_text,
            )

            out_path, content_hash = write_artifact(record, self.pipeline_dir)
            output_paths.append(out_path)

            print(f"     🐝 {hive_id}: {len(seg_text)} chars → {out_path.name}")

        print(f"     Split into {len(output_paths)} hive(s)")
        return output_paths

    def _parse_response(self, text: str, raw: dict) -> list[dict]:
        """Parse the Ollama JSON response into a list of hive segments."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(f"     ⚠️  Splitter JSON parse failed — falling back to regex")
            return self._regex_fallback(raw.get("raw_text", ""))

        # Extract inspection_date (may be used per segment)
        inspection_date = data.get("inspection_date")

        hives = data.get("hives", [])
        if not hives:
            return []

        # Normalize: ensure each segment has hive_id and segment_text
        segments = []
        for h in hives:
            hive_id = self._normalize_hive_id(h.get("hive_id", ""))
            if not hive_id:
                continue
            segments.append({
                "hive_id": hive_id,
                "segment_text": h.get("segment_text", ""),
                "inspection_date": inspection_date,
            })

        return segments

    def _normalize_hive_id(self, raw_id: str) -> str:
        """Normalize various hive ID formats to 'H<number>'."""
        import re

        raw_id = raw_id.strip()

        # Already in correct format: "H07", "H1", "H12"
        if re.match(r"^H\d+$", raw_id):
            return raw_id

        # "Hive 1", "Hive number 5", "hive seven" → extract number
        match = re.search(r"\d+", raw_id)
        if match:
            return f"H{match.group()}"

        # Word numbers: "hive seven" → "H7"
        word_map = {
            "one": "1", "two": "2", "three": "3", "four": "4",
            "five": "5", "six": "6", "seven": "7", "eight": "8",
            "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
            "thirteen": "13", "fourteen": "14", "fifteen": "15",
        }
        for word, num in word_map.items():
            if word in raw_id.lower():
                return f"H{num}"

        return ""

    def _regex_fallback(self, raw_text: str) -> list[dict]:
        """
        Fallback: use regex to find hive mentions when LLM parsing fails.
        This is less accurate but ensures the pipeline doesn't stall.
        """
        import re

        # Patterns like "Hive 1", "Hive number 5", "Hive 07", "hive seven"
        patterns = [
            r"(?i)hive\s+(?:number\s+)?(\d+)",   # Hive 1, Hive number 5
            r"(?i)hive\s+#\s*(\d+)",              # Hive #1
            r"\bH(\d+)\b",                         # H07, H1
        ]

        hive_spans = []
        for pattern in patterns:
            for m in re.finditer(pattern, raw_text):
                num = m.group(1)
                hive_spans.append((m.start(), f"H{int(num)}"))

        if not hive_spans:
            return []

        # Sort by position
        hive_spans.sort()

        # Build segments: text between hive mentions belongs to the preceding hive
        segments = []
        for i, (pos, hive_id) in enumerate(hive_spans):
            start = pos
            end = hive_spans[i + 1][0] if i + 1 < len(hive_spans) else len(raw_text)
            seg_text = raw_text[start:end].strip()
            # Clean up: remove leading "Hive N" / "H07" prefix
            seg_text = re.sub(r"(?i)^hive\s+(?:number\s+)?\d+\b[:—–\-]?\s*", "", seg_text)
            seg_text = re.sub(r"^H\d+\b[:—–\-]?\s*", "", seg_text)
            if seg_text:
                segments.append({
                    "hive_id": hive_id,
                    "segment_text": seg_text.strip(),
                })

        return segments

    def _resolve_date(self, llm_date: Optional[str], raw: dict) -> date_type:
        """Resolve the inspection date from LLM output or fallback sources."""
        if llm_date:
            try:
                return date_type.fromisoformat(llm_date)
            except (ValueError, TypeError):
                pass

        # Try the original RawTranscript date
        raw_date = raw.get("inspection_date")
        if raw_date:
            try:
                if isinstance(raw_date, str):
                    return date_type.fromisoformat(raw_date)
                elif isinstance(raw_date, date_type):
                    return raw_date
            except (ValueError, TypeError):
                pass

        # Final fallback: today
        return date_type.today()
