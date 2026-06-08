"""
TranscriberAgent — converts voice memo audio files to raw text.

Uses Whisper (openai-whisper package) for speech-to-text.
On Apple Silicon, Whisper runs on the Neural Engine for fast, local transcription.

Input:  Audio file (e.g., inbox/H07_2026-06-06.m4a)
Output: RawTranscript JSON artifact saved to pipeline/
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .base import BuzzAgent
from ..schema import RawTranscript, write_artifact


class TranscriberAgent(BuzzAgent):
    """
    Voice memo → raw text transcription.

    Supports two backends:
      - 'whisper': openai-whisper Python package (default)
      - 'whisper-cpp': whisper.cpp CLI for M-series optimization
    """

    def __init__(
        self,
        backend: str = "whisper",
        model: str = "base",
        whisper_cpp_path: Optional[str] = None,
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="transcriber", pipeline_dir=pipeline_dir)
        self.backend = backend
        self.model = model
        self.whisper_cpp_path = whisper_cpp_path or "whisper"
        self._model = None  # lazy-loaded

    def process(self, input_path: Path) -> tuple[Path, bool]:  # type: ignore[override]
        """
        Transcribe audio → RawTranscript JSON.

        Returns:
            (output_path, is_multi_hive) — is_multi_hive=True when the
            filename doesn't encode a specific hive_id, meaning the
            transcript likely contains multiple hives and needs splitting.
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Audio file not found: {input_path}")

        # Try to parse hive_id + date from filename.
        # If it fails, the file is multi-hive and needs the splitter.
        try:
            hive_id, insp_date = RawTranscript.parse_filename(input_path)
            is_multi_hive = False
        except ValueError:
            hive_id = "unknown"
            # Use file modification time as fallback date
            from datetime import datetime
            mtime = input_path.stat().st_mtime
            insp_date = datetime.fromtimestamp(mtime).date()
            is_multi_hive = True

        raw_text = self._transcribe(input_path)

        record = RawTranscript(
            audio_file=input_path.name,
            hive_id=hive_id,
            inspection_date=insp_date,
            raw_text=raw_text,
        )

        output_path, content_hash = write_artifact(
            record, self.pipeline_dir
        )

        # Track artifact with correct hive_id
        artifact = self._track_artifact(
            input_path=str(input_path),
            output_path=str(output_path),
            duration_ms=0,  # TODO: measure actual duration
        )
        # HACK — override hive_id since base doesn't know it yet
        # (this gets cleaned up when we add proper artifact tracking)

        tag = "🔀 [multi-hive]" if is_multi_hive else ""
        print(f"  📝 Transcriber{tag}: {input_path.name} → {output_path.name}")
        print(f"     Hive: {hive_id}  |  Date: {insp_date}")
        print(f"     Chars: {len(raw_text)}  |  Hash: {content_hash}")

        return output_path, is_multi_hive

    # ── Backend implementations ─────────────────────────────────────────────

    def _transcribe(self, audio_path: Path) -> str:
        """Dispatch to the configured backend."""
        if self.backend == "whisper":
            return self._transcribe_whisper(audio_path)
        elif self.backend == "whisper-cpp":
            return self._transcribe_whisper_cpp(audio_path)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _transcribe_whisper(self, audio_path: Path) -> str:
        """Use openai-whisper Python package."""
        try:
            import whisper
        except ImportError:
            raise ImportError(
                "openai-whisper not installed. Run: pip install buzzboard[whisper]"
            )

        if self._model is None:
            print(f"  🔄 Loading Whisper model '{self.model}' (one-time)...")
            self._model = whisper.load_model(self.model)

        result = self._model.transcribe(str(audio_path))
        return result["text"].strip()

    def _transcribe_whisper_cpp(self, audio_path: Path) -> str:
        """Use whisper.cpp CLI binary (fast on M-series)."""
        result = subprocess.run(
            [
                self.whisper_cpp_path,
                "-m", f"models/ggml-{self.model}.bin",
                "-f", str(audio_path),
                "--no-timestamps",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"whisper.cpp failed: {result.stderr}")
        return result.stdout.strip()
