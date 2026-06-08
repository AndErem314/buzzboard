"""
BuzzBoard CLI — the single entry point for the multi-agent pipeline.

Usage:
    buzzboard transcribe inbox/H07_2026-06-06.m4a    # Voice → text only
    buzzboard process inbox/H07_2026-06-06.m4a        # Full pipeline
    buzzboard watch                                     # Auto-process inbox/
    buzzboard status                                    # Show Kanban board
    buzzboard board                                     # Kanban board detail
"""

from __future__ import annotations

from pathlib import Path

import click

from .agents.transcriber import TranscriberAgent
from .agents.splitter import HiveSplitterAgent
from .agents.editor import EditorAgent
from .agents.extractor import ExtractorAgent
from .agents.storage import StorageAgent
from .agents.trend import TrendAgent
from .orchestrator import Orchestrator
from .db.kanban import KanbanBoard
from .schema import TrendReport, read_artifact
from . import config as cfg


# ── Helper: Editor → Extractor → Storage for a single hive ───────────────

def _run_editor_extractor_storage(
    input_path: Path,
    output_dir: Path,
    ollama_model: str,
    ollama_host: str,
    obsidian_vault: Path | None,
):
    """Run Editor → Extractor → Storage on a single-hive transcript."""
    # Stage: Editor
    click.echo("Editor (LLM)")
    click.echo()
    try:
        editor = EditorAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        cleaned_path = editor.process(input_path)
    except RuntimeError as e:
        click.echo(f"❌ Editor failed: {e}", err=True)
        raise SystemExit(1)

    # Stage: Extractor
    click.echo(f"\nExtractor (LLM)")
    click.echo()
    try:
        extractor = ExtractorAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        record_path = extractor.process(cleaned_path)
    except RuntimeError as e:
        click.echo(f"❌ Extractor failed: {e}", err=True)
        raise SystemExit(1)

    # Stage: Storage
    click.echo(f"\nStorage (Obsidian)")
    click.echo()
    if obsidian_vault:
        try:
            storage = StorageAgent(
                obsidian_vault=obsidian_vault,
                pipeline_dir=output_dir,
            )
            note_path = storage.process(record_path)
            click.echo(f"  ✅ Wrote to Obsidian: {note_path}")
        except (FileNotFoundError, RuntimeError) as e:
            click.echo(f"❌ Storage failed: {e}", err=True)
            raise SystemExit(1)
    else:
        click.echo("  ⏭️  Skipping — no Obsidian vault specified")


@click.group()
@click.version_option(package_name="buzzboard", message="BuzzBoard %(version)s 🐝")
def cli():
    """BuzzBoard — multi-agent beehive inspection assistant.

    Drop voice memos in inbox/, let the agents do the rest.
    Structured Obsidian notes appear in your vault, organized by hive.
    """
    pass


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--backend", default="whisper", type=click.Choice(["whisper", "whisper-cpp"]),
    help="Speech-to-text backend (default: whisper)"
)
@click.option(
    "--model", default="base",
    help="Whisper model size: tiny, base, small, medium, large"
)
@click.option(
    "--output-dir", default="pipeline", type=click.Path(path_type=Path),
    help="Directory for pipeline artifacts"
)
def transcribe(
    audio_file: Path,
    backend: str,
    model: str,
    output_dir: Path,
):
    """Transcribe a single voice memo to raw text.

    Works with both single-hive (H07_YYYY-MM-DD.m4a) and generic filenames.
    Generic filenames are flagged as multi-hive — use 'buzzboard split' next.
    """
    agent = TranscriberAgent(
        backend=backend,
        model=model,
        pipeline_dir=output_dir,
    )
    try:
        output_path, is_multi = agent.process(audio_file)
        click.echo(f"\n✅ Done: {output_path}")
        if is_multi:
            click.echo(f"🔀 Multi-hive detected — run 'buzzboard split {output_path}'")
    except FileNotFoundError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--backend", default="whisper", type=click.Choice(["whisper", "whisper-cpp"]))
@click.option("--whisper-model", default="base", help="Whisper model size")
@click.option("--output-dir", default="pipeline", type=click.Path(path_type=Path))
@click.option(
    "--ollama-model", default="llama3.1:8b",
    help="Ollama model for Editor + Extractor agents"
)
@click.option(
    "--ollama-host", default="http://localhost:11434",
    help="Ollama API host"
)
@click.option("--skip-transcribe", is_flag=True, help="Skip transcription (use existing raw JSON)")
@click.option(
    "--obsidian-vault", default=None, type=click.Path(path_type=Path),
    help="Path to Obsidian vault for Storage agent (default: $BUZZBOARD_OBSIDIAN_VAULT)"
)
def process(
    audio_file: Path,
    backend: str,
    whisper_model: str,
    output_dir: Path,
    ollama_model: str,
    ollama_host: str,
    skip_transcribe: bool,
    obsidian_vault: Path | None,
):
    """Run the full BuzzBoard pipeline on a voice memo.

    Pipeline:  Transcriber → [Splitter] → Editor → Extractor → Storage

    For single-hive files (H07_YYYY-MM-DD.m4a), runs the classic 4-stage pipeline.
    For multi-hive files (any other filename), automatically splits into per-hive
    transcripts and processes each hive independently.
    """
    # Resolve Obsidian vault: CLI arg > env var
    if obsidian_vault is None:
        obsidian_vault = cfg.OBSIDIAN_VAULT

    click.echo(f"🐝 BuzzBoard processing: {audio_file.name}\n")

    # ── Stage 1: Transcribe ─────────────────────────────────────────────
    click.echo("─" * 50)
    click.echo("Stage 1/?  Transcriber (Whisper)")
    click.echo("─" * 50)
    click.echo()

    if skip_transcribe:
        raw_path = audio_file
        is_multi = True  # assume multi-hive if skipping transcription
        click.echo(f"  ⏭️  Skipping — using existing artifact: {raw_path}")
    else:
        transcriber = TranscriberAgent(
            backend=backend, model=whisper_model, pipeline_dir=output_dir
        )
        try:
            raw_path, is_multi = transcriber.process(audio_file)
        except FileNotFoundError as e:
            click.echo(f"❌ Transcriber failed: {e}", err=True)
            raise SystemExit(1)

    # ── Branch: multi-hive or single-hive? ──────────────────────────────
    if is_multi:
        click.echo(f"\n{'─' * 50}")
        click.echo("Stage 2/?  HiveSplitter (LLM)")
        click.echo("─" * 50)
        click.echo()

        try:
            splitter = HiveSplitterAgent(
                ollama_model=ollama_model,
                ollama_host=ollama_host,
                pipeline_dir=output_dir,
            )
            hive_paths = splitter.process(raw_path)
        except RuntimeError as e:
            click.echo(f"❌ HiveSplitter failed: {e}", err=True)
            raise SystemExit(1)

        # Process each hive
        for i, hive_path in enumerate(hive_paths):
            click.echo(f"\n{'─' * 50}")
            click.echo(f"Hive {i+1}/{len(hive_paths)}")
            click.echo(f"{'─' * 50}")
            _run_editor_extractor_storage(hive_path, output_dir, ollama_model,
                                          ollama_host, obsidian_vault)
    else:
        _run_editor_extractor_storage(raw_path, output_dir, ollama_model,
                                      ollama_host, obsidian_vault)

    # ── Summary ─────────────────────────────────────────────────────────
    click.echo(f"\n{'═' * 50}")
    click.echo(f"✅ Pipeline complete")
    click.echo(f"{'═' * 50}")
    click.echo(f"  Raw transcript:  {raw_path}")
    click.echo()


@cli.command()
@click.option(
    "--obsidian-vault", default=None, type=click.Path(path_type=Path),
    help="Path to Obsidian vault for Storage agent"
)
@click.option(
    "--ollama-model", default=None, help="Ollama model"
)
@click.option(
    "--interval", default=5.0, help="Polling interval in seconds (for watch mode)"
)
@click.option("--once", is_flag=True, help="Process all pending files, then exit (default: watch forever)")
@click.option("--recent/--all", default=True, help="Only process recently added files (default: --recent). Use --all to process everything in inbox.")
def watch(
    obsidian_vault: Path | None,
    ollama_model: str | None,
    interval: float,
    once: bool,
    recent: bool,
):
    """Watch inbox/ and auto-process new voice memos.

    Without --once: runs forever, polling every N seconds.
    With --once: processes all pending files, reports results, exits.
    With --recent (default): only processes files added since last check.
    With --all: reprocesses everything in inbox/ (useful for recovery).
    """
    # Resolve from config if not specified
    if obsidian_vault is None:
        obsidian_vault = cfg.OBSIDIAN_VAULT
    if ollama_model is None:
        ollama_model = cfg.OLLAMA_MODEL

    orch = Orchestrator(
        inbox_dir=str(cfg.INBOX_DIR),
        obsidian_vault=obsidian_vault,
        ollama_model=ollama_model,
        pipeline_dir=str(cfg.PIPELINE_DIR),
    )

    if once:
        orch.run_once(recent_only=recent)
    else:
        orch.watch(poll_interval=interval, recent_only=recent)


@cli.command()
@click.option("--db", default=None, help="Path to Kanban database")
def board(db: str | None):
    """Show the Kanban board with all tasks and events."""
    if db is None:
        db = str(cfg.KANBAN_DB)
    board_obj = KanbanBoard(db)
    print(board_obj.print_board())

    # Show recent tasks with details
    tasks = board_obj.get_all_tasks()
    if tasks:
        print(f"\n{'─' * 70}")
        print(f"Recent tasks:")
        print(f"{'─' * 70}")
        for t in tasks[:10]:
            status_icon = {"done": "✅", "failed": "❌", "inbox": "📥"}.get(t["stage"], "🔄")
            print(f"  {status_icon} {t['id']:<20}  {t['stage']:<14}  "
                  f"created: {t['created_at'][:19]}  "
                  f"{'done: ' + t['completed_at'][:19] if t['completed_at'] else ''}")
            if t.get("error"):
                print(f"     ⚠️  {t['error'][:100]}")


@cli.command()
@click.argument("task_id")
@click.option("--db", default=None, help="Path to Kanban database")
def events(task_id: str, db: str | None):
    """Show the event log for a specific task."""
    if db is None:
        db = str(cfg.KANBAN_DB)
    board_obj = KanbanBoard(db)
    task = board_obj.get_task(task_id)
    if not task:
        click.echo(f"❌ Task not found: {task_id}")
        raise SystemExit(1)

    click.echo(f"Task: {task['id']}")
    click.echo(f"  Hive: {task['hive_id']}  |  File: {task['audio_file']}")
    click.echo(f"  Stage: {task['stage']}  |  Created: {task['created_at'][:19]}")
    if task.get("error"):
        click.echo(f"  Error: {task['error'][:200]}")
    click.echo()

    events_list = board_obj.get_events(task_id)
    if not events_list:
        click.echo("  No events logged.")
        return

    click.echo(f"{'Agent':<14} {'Action':<12} {'Duration':>8}  {'Time':<20}")
    click.echo("-" * 60)
    for ev in events_list:
        dur = f"{ev['duration_ms']:.0f}ms" if ev.get("duration_ms") else "—"
        click.echo(f"{ev['agent']:<14} {ev['action']:<12} {dur:>8}  {ev['created_at'][:19]}")


@cli.command()
@click.argument("hive_id")
@click.option(
    "--obsidian-vault", default=None, type=click.Path(path_type=Path),
    help="Path to Obsidian vault (default: $BUZZBOARD_OBSIDIAN_VAULT)"
)
@click.option(
    "--ollama-model", default=None, help="Ollama model for trend analysis"
)
@click.option(
    "--ollama-host", default=None, help="Ollama API host"
)
@click.option(
    "--output-dir", default="pipeline", type=click.Path(path_type=Path),
    help="Directory for pipeline artifacts"
)
def trends(
    hive_id: str,
    obsidian_vault: Path | None,
    ollama_model: str | None,
    ollama_host: str | None,
    output_dir: Path,
):
    """Analyze historical inspection trends for a hive.

    Reads all inspection records for HIVE_ID from your Obsidian vault
    (or a specified directory) and produces a trend report identifying
    patterns, risks, and recommendations.

    Example:
        buzzboard trends H07
        buzzboard trends H07 --obsidian-vault ~/Documents/Obsidian
    """
    # Resolve paths
    if obsidian_vault is None:
        obsidian_vault = cfg.OBSIDIAN_VAULT
    if ollama_model is None:
        ollama_model = cfg.OLLAMA_MODEL
    if ollama_host is None:
        ollama_host = cfg.OLLAMA_HOST

    # Find the hive directory
    if obsidian_vault:
        hive_dir = Path(obsidian_vault) / "Hives" / hive_id
    else:
        hive_dir = Path(f"pipeline/{hive_id}")

    if not hive_dir.exists():
        click.echo(f"❌ Hive directory not found: {hive_dir}")
        click.echo(f"   Make sure Obsidian vault is configured and "
                   f"inspections have been stored for {hive_id}.")
        raise SystemExit(1)

    click.echo(f"🐝 BuzzBoard Trend Analysis: {hive_id}\n")

    try:
        agent = TrendAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        output_path = agent.process(hive_dir)
        click.echo(f"\n✅ Trend report: {output_path}")

        # Print summary
        report = read_artifact(output_path, TrendReport)
        click.echo(f"\n{'─' * 50}")
        click.echo(f"📊 {hive_id} Trend Summary")
        click.echo(f"{'─' * 50}")
        click.echo(f"  Inspections: {report.inspections_analyzed}")
        click.echo(f"  Range: {report.date_range_first} → {report.date_range_last}")
        click.echo(f"  Severity: {report.overall_severity}")
        if report.summary:
            click.echo(f"\n  {report.summary}")
        if report.mite_trajectory:
            click.echo(f"\n  Mites: {report.mite_trajectory}")
        if report.recurring_issues:
            click.echo(f"\n  Recurring issues:")
            for issue in report.recurring_issues:
                click.echo(f"    ⚠️  {issue}")
        if report.recommendations:
            click.echo(f"\n  Recommendations:")
            for rec in report.recommendations:
                click.echo(f"    → {rec}")

    except FileNotFoundError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1)
    except RuntimeError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1)


@cli.command(name="split")
@click.argument("transcript_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--ollama-model", default=None, help="Ollama model for splitting"
)
@click.option(
    "--ollama-host", default=None, help="Ollama API host"
)
@click.option(
    "--output-dir", default="pipeline", type=click.Path(path_type=Path),
    help="Directory for pipeline artifacts"
)
def split_cmd(
    transcript_file: Path,
    ollama_model: str | None,
    ollama_host: str | None,
    output_dir: Path,
):
    """Split a multi-hive transcript into per-hive artifacts.

    Takes a RawTranscript JSON (from 'buzzboard transcribe') and uses
    Ollama to detect individual hive segments. Outputs one RawTranscript
    JSON artifact per hive found.

    Example:
        buzzboard transcribe inbox/recording.m4a
        buzzboard split pipeline/rawtranscript_abc123.json
    """
    if ollama_model is None:
        ollama_model = cfg.OLLAMA_MODEL
    if ollama_host is None:
        ollama_host = cfg.OLLAMA_HOST

    click.echo(f"🔀 BuzzBoard HiveSplitter\n")

    try:
        splitter = HiveSplitterAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        hive_paths = splitter.process(transcript_file)

        click.echo(f"\n✅ Split into {len(hive_paths)} hive(s):")
        for p in hive_paths:
            click.echo(f"   📄 {p}")

    except RuntimeError as e:
        click.echo(f"❌ HiveSplitter failed: {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1)


@cli.command()
def status():
    """Show BuzzBoard pipeline status."""
    click.echo("🐝 BuzzBoard Status")
    click.echo("=" * 40)
    click.echo("  Pipeline:  Transcriber ✅  |  Splitter ✅  |  Editor ✅  |  Extractor ✅  |  Storage ✅  |  Trend ✅")
    click.echo("  Phase 8 — multi-hive support + timestamp filtering.")
    click.echo()
    click.echo("  Quick start:")
    click.echo("    buzzboard process inbox/H07_2026-06-06.m4a     # single-hive")
    click.echo("    buzzboard process inbox/Neue\\ Aufnahme\\ 2.m4a  # multi-hive")
    click.echo("    buzzboard trends H07")
    click.echo("    buzzboard watch --once --recent")
    click.echo("    buzzboard board")
    click.echo("    buzzboard config")
    click.echo()


@cli.command(name="config")
def config_cmd():
    """Show current BuzzBoard configuration."""
    click.echo(cfg.print_config())
    click.echo()
    env_file = Path(".env")
    if env_file.exists():
        click.echo(f"  📄 .env file: {env_file.absolute()}")
    else:
        click.echo(f"  💡 Create a .env file to customize (see .env.example)")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8099, help="Port to listen on")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev mode)")
def dashboard(host: str, port: int, reload: bool):
    """Start the web dashboard (FastAPI + Uvicorn).

    Opens http://localhost:8099 — Kanban board with live updates.
    Press Ctrl+C to stop.
    """
    from .dashboard.server import run_server
    click.echo(f"🐝 BuzzBoard Dashboard → http://{host}:{port}")
    click.echo("   Press Ctrl+C to stop.\n")
    run_server(host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
