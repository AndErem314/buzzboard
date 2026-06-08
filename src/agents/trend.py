"""
TrendAgent — analyzes historical inspection patterns and generates alerts.

Phase 7 implementation.
Reads all StructuredRecords for a hive, sends them to Ollama with a trend
analysis prompt, and produces a TrendReport with patterns, risks, and
actionable recommendations.

Input:  directory containing StructuredRecord JSON artifacts (record_*.json)
Output: TrendReport JSON artifact
"""

from __future__ import annotations

import json
from datetime import date as date_type
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .base import BuzzAgent
from .ollama_client import OllamaClient
from .prompts import TREND_SYSTEM_PROMPT
from ..schema import StructuredRecord, TrendReport, read_artifact, write_artifact


# ── User prompt template ────────────────────────────────────────────────────

TREND_USER_TEMPLATE = """Analyze all inspection records below for hive {hive_id} and
produce a trend report.

Records ({count} inspections, {date_first} → {date_last}):

{records_text}

Return valid JSON with your trend analysis."""


class TrendAgent(BuzzAgent):
    """
    Historical inspection records → trend analysis + recommendations (LLM-powered).

    Reads multiple StructuredRecord artifacts for a hive from a directory,
    identifies patterns (mite trends, queen issues, recurring problems), and
    produces a trend report with severity classification and recommendations.

    Input directory can be:
      - A hive's .buzzboard/ subdirectory (containing record_*.json)
      - Any directory with StructuredRecord JSON files
    """

    def __init__(
        self,
        ollama_model: str = "llama3.1:8b",
        ollama_host: str = "http://localhost:11434",
        pipeline_dir: Optional[Path] = None,
    ):
        super().__init__(name="trend", pipeline_dir=pipeline_dir)
        self.ollama = OllamaClient(model=ollama_model, host=ollama_host)

    def process(self, input_path: Path) -> Path:
        """
        Read all StructuredRecords from a directory → trend analysis via Ollama.

        Args:
            input_path: Directory containing record_*.json files.
                        Can be the hive's .buzzboard/ subdir or any directory
                        with StructuredRecord artifacts.

        Returns:
            Path to the output TrendReport JSON artifact.
        """
        # 1. Discover records
        record_dir = self._resolve_record_dir(input_path)
        record_files = sorted(record_dir.glob("record_*.json"))
        if not record_files:
            raise FileNotFoundError(
                f"No record_*.json files found in {record_dir}. "
                f"Run the pipeline first to generate inspection records."
            )

        # 2. Load all records
        records: list[StructuredRecord] = []
        for rf in record_files:
            try:
                records.append(read_artifact(rf, StructuredRecord))
            except Exception as e:
                print(f"  ⚠️  Skipping {rf.name}: {e}")

        if not records:
            raise RuntimeError(f"Could not parse any records from {record_dir}")

        records.sort(key=lambda r: r.inspection_date)
        hive_id = records[0].hive_id
        date_first = records[0].inspection_date.isoformat()
        date_last = records[-1].inspection_date.isoformat()

        print(f"  📊 Trend: {hive_id} — {len(records)} inspection(s)")
        print(f"     Range: {date_first} → {date_last}")

        # 3. Build prompt with all records
        records_text = self._format_records(records)
        user_prompt = TREND_USER_TEMPLATE.format(
            hive_id=hive_id,
            count=len(records),
            date_first=date_first,
            date_last=date_last,
            records_text=records_text,
        )

        # 4. Call Ollama
        try:
            response_text = self.ollama.chat(
                system=TREND_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=0.2,
            )
        except ConnectionError as e:
            raise RuntimeError(
                f"TrendAgent needs Ollama. {e}\n"
                f"Install: brew install ollama && ollama serve\n"
                f"Pull model: ollama pull {self.ollama.model}"
            )

        # 5. Parse response into TrendReport
        report = self._parse_response(response_text, hive_id, records)

        # 6. Write output
        output_path, content_hash = write_artifact(report, self.pipeline_dir)

        print(f"     Inspections: {report.inspections_analyzed}")
        print(f"     Severity: {report.overall_severity}")
        print(f"     Issues: {len(report.recurring_issues)} recurring")
        print(f"     Recs: {len(report.recommendations)}")
        print(f"     Hash: {content_hash}")

        return output_path

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _resolve_record_dir(self, input_path: Path) -> Path:
        """
        Resolve the directory containing StructuredRecord JSON files.

        If input_path is a .buzzboard/ directory, use it directly.
        If input_path is a hive directory (e.g., Hives/H07/), look for
        the .buzzboard/ subdirectory first, then fall back to the directory itself.
        """
        if input_path.name == ".buzzboard":
            return input_path
        buzzboard_subdir = input_path / ".buzzboard"
        if buzzboard_subdir.exists():
            return buzzboard_subdir
        return input_path

    def _format_records(self, records: list[StructuredRecord]) -> str:
        """Format all records into a compact text block for the LLM prompt."""
        lines = []
        for i, r in enumerate(records, 1):
            lines.append(
                f"[{i}] {r.inspection_date.isoformat()}: "
                f"queen_seen={r.queen_seen}, "
                f"brood_health={r.brood_health or 'N/A'}, "
                f"mite_count={r.mite_count}, "
                f"honey_frames={r.honey_frames}, "
                f"severity={r.severity or 'normal'}"
            )
            if r.issues:
                lines.append(f"    issues: {'; '.join(r.issues)}")
            if r.actions_required:
                lines.append(f"    actions: {'; '.join(r.actions_required)}")
        return "\n".join(lines)

    def _parse_response(
        self, text: str, hive_id: str, records: list[StructuredRecord]
    ) -> TrendReport:
        """Parse LLM JSON response into a TrendReport, with fallback."""
        try:
            data = json.loads(text)
            # Normalize date fields
            data = _normalize_trend_dates(data, records)
            # Ensure required fields
            data.setdefault("hive_id", hive_id)
            data.setdefault("inspections_analyzed", len(records))
            data.setdefault("summary", data.get("summary", text[:500]))
            data.setdefault("queen_performance", "")
            data.setdefault("mite_trajectory", "")
            data.setdefault("honey_trend", "")
            data.setdefault("recurring_issues", [])
            data.setdefault("swarm_risk", "")
            data.setdefault("recommendations", [])
            data.setdefault("overall_severity", "normal")
            return TrendReport(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            # Graceful degradation: build a basic report from raw data
            print(f"     ⚠️  JSON parse failed, building fallback report")
            return _build_fallback_report(hive_id, records, text)


def _normalize_trend_dates(data: dict, records: list[StructuredRecord]) -> dict:
    """Convert string dates in LLM response to date objects."""
    for field in ("date_range_first", "date_range_last"):
        raw = data.get(field)
        if isinstance(raw, str):
            try:
                data[field] = date_type.fromisoformat(raw)
            except ValueError:
                data[field] = None
        elif raw is None:
            data[field] = None
    # Set from records if missing
    if not data.get("date_range_first") and records:
        data["date_range_first"] = records[0].inspection_date
    if not data.get("date_range_last") and records:
        data["date_range_last"] = records[-1].inspection_date
    return data


def _build_fallback_report(
    hive_id: str,
    records: list[StructuredRecord],
    raw_response: str = "",
) -> TrendReport:
    """Build a basic TrendReport from raw data when LLM parsing fails."""
    issues_all = []
    for r in records:
        issues_all.extend(r.issues)

    # Count recurring issues (appear in >1 inspection)
    from collections import Counter
    issue_counts = Counter(issues_all)
    recurring = [issue for issue, count in issue_counts.items() if count > 1]

    # Compute mite trend
    mite_values = [r.mite_count for r in records if r.mite_count is not None]
    mite_traj = "insufficient data"
    if len(mite_values) >= 2:
        if mite_values[-1] > mite_values[0]:
            mite_traj = f"rising ({mite_values[0]} → {mite_values[-1]})"
        elif mite_values[-1] < mite_values[0]:
            mite_traj = f"falling ({mite_values[0]} → {mite_values[-1]})"
        else:
            mite_traj = f"stable at {mite_values[0]}"

    return TrendReport(
        hive_id=hive_id,
        inspections_analyzed=len(records),
        date_range_first=records[0].inspection_date if records else None,
        date_range_last=records[-1].inspection_date if records else None,
        summary=f"Trend analysis for {len(records)} inspection(s). "
                + (raw_response[:300] if raw_response else "LLM analysis unavailable."),
        mite_trajectory=mite_traj,
        recurring_issues=recurring,
        overall_severity=_worst_severity(records),
    )


def _worst_severity(records: list[StructuredRecord]) -> str:
    """Return the worst severity across all records."""
    severity_rank = {"normal": 0, "attention": 1, "urgent": 2}
    worst = "normal"
    for r in records:
        if r.severity and severity_rank.get(r.severity, 0) > severity_rank.get(worst, 0):
            worst = r.severity
    return worst
