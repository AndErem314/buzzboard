"""
BuzzBoard CLI — the single entry point for the multi-agent pipeline.

Usage:
    buzzboard process inbox/H07_2026-06-06.m4a     # Run full pipeline
    buzzboard transcribe inbox/H07_2026-06-06.m4a   # Transcribe only
    buzzboard status                                 # Show pipeline status
"""

from __future__ import annotations

from pathlib import Path

import click

from .agents.transcriber import TranscriberAgent
from .agents.editor import EditorAgent
from .agents.extractor import ExtractorAgent


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
    """Transcribe a single voice memo to raw text."""
    agent = TranscriberAgent(
        backend=backend,
        model=model,
        pipeline_dir=output_dir,
    )
    try:
        output_path = agent.process(audio_file)
        click.echo(f"\n✅ Done: {output_path}")
    except ValueError as e:
        click.echo(f"❌ Filename error: {e}", err=True)
        raise SystemExit(1)
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
@click.option("--obsidian-vault", default=None, type=click.Path(path_type=Path),
              help="Path to Obsidian vault (for Phase 3 storage agent)")
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

    Pipeline:  Transcriber → Editor → Extractor → Storage (Phase 3)
    """
    click.echo(f"🐝 BuzzBoard processing: {audio_file.name}\n")

    # ── Stage 1: Transcribe ─────────────────────────────────────────────
    click.echo("─" * 50)
    click.echo("Stage 1/4:  Transcriber (Whisper)")
    click.echo("─" * 50)
    click.echo()

    if skip_transcribe:
        raw_path = audio_file  # user provided a RawTranscript JSON directly
        click.echo(f"  ⏭️  Skipping — using existing artifact: {raw_path}")
    else:
        transcriber = TranscriberAgent(
            backend=backend, model=whisper_model, pipeline_dir=output_dir
        )
        try:
            raw_path = transcriber.process(audio_file)
        except (ValueError, FileNotFoundError) as e:
            click.echo(f"❌ Transcriber failed: {e}", err=True)
            raise SystemExit(1)

    # ── Stage 2: Editor ─────────────────────────────────────────────────
    click.echo(f"\n{'─' * 50}")
    click.echo("Stage 2/4:  Editor (LLM)")
    click.echo("─" * 50)
    click.echo()

    try:
        editor = EditorAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        cleaned_path = editor.process(raw_path)
    except RuntimeError as e:
        click.echo(f"❌ Editor failed: {e}", err=True)
        raise SystemExit(1)

    # ── Stage 3: Extractor ──────────────────────────────────────────────
    click.echo(f"\n{'─' * 50}")
    click.echo("Stage 3/4:  Extractor (LLM)")
    click.echo("─" * 50)
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

    # ── Stage 4: Storage ────────────────────────────────────────────────
    click.echo(f"\n{'─' * 50}")
    click.echo("Stage 4/4:  Storage (Phase 3 — coming soon)")
    click.echo("─" * 50)
    click.echo()
    if obsidian_vault:
        click.echo(f"  ⏳ Would write StructuredRecord to: {obsidian_vault}/Hives/")
    else:
        click.echo(f"  ⏳ Would write StructuredRecord to Obsidian vault")
    click.echo(f"     Source: {record_path}")

    # ── Summary ─────────────────────────────────────────────────────────
    click.echo(f"\n{'═' * 50}")
    click.echo(f"✅ Pipeline complete (3/4 stages active)")
    click.echo(f"{'═' * 50}")
    click.echo(f"  Raw transcript:  {raw_path}")
    click.echo(f"  Cleaned note:    {cleaned_path}")
    click.echo(f"  Structured data: {record_path}")
    click.echo()


@cli.command()
def status():
    """Show BuzzBoard pipeline status."""
    click.echo("🐝 BuzzBoard Status")
    click.echo("=" * 40)
    click.echo("  Pipeline:  Transcriber ✅  |  Editor ✅  |  Extractor ✅  |  Storage ⏳")
    click.echo("  Phase 2 complete — full text pipeline working.")
    click.echo("  Phase 3 (Storage + Kanban) coming next.")
    click.echo()
    click.echo("  Inbox:  check inbox/ for pending voice memos")
    click.echo("  Pipeline artifacts:  pipeline/")
    click.echo()
    click.echo("  Quick test: buzzboard process inbox/H07_2026-06-06.m4a")


if __name__ == "__main__":
    cli()
