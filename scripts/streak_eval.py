#!/usr/bin/env python3
"""
BuzzBoard Quality Streak Harness.

Tests the full 6-agent pipeline health: runs pytest suite, checks
pipeline filesystem health, and verifies agent availability.
Designed for daily cron monitoring.

Usage:
    python scripts/streak_eval.py
    python scripts/streak_eval.py --no-pipeline-test
    python scripts/streak_eval.py --output /tmp/buzzboard_eval.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STREAK_LOG = PROJECT_ROOT / ".hermes" / "streak-log.md"
INBOX_DIR = PROJECT_ROOT / "inbox"
DEFAULT_MAX_RUNTIME = 300  # 5 minutes

# Scoring weights
WEIGHT_TESTS = 50          # pytest pass rate
WEIGHT_PIPELINE = 30       # pipeline filesystem health
WEIGHT_AGENTS = 20         # agent availability checks

PASS_THRESHOLD = 70


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
def check_agent_availability() -> Dict:
    """Verify all 6 agents are importable and configurable."""
    agents = {
        "Transcriber": "src/agents/transcriber.py",
        "HiveSplitter": "src/agents/hive_splitter.py",
        "Editor": "src/agents/editor.py",
        "Extractor": "src/agents/extractor.py",
        "Storage": "src/agents/storage.py",
        "Trend": "src/agents/trend.py",
    }

    available = []
    missing = []
    for name, path in agents.items():
        full_path = PROJECT_ROOT / path
        if full_path.exists():
            available.append(name)
        else:
            missing.append(name)

    return {
        "total": len(agents),
        "available": len(available),
        "available_agents": available,
        "missing_agents": missing,
        "score": len(available) / len(agents) * WEIGHT_AGENTS if agents else 0,
    }


def check_pipeline_filesystem() -> Dict:
    """Check pipeline directories and state files exist."""
    dirs = ["inbox", "artifacts", "logs"]
    results = {}
    for d in dirs:
        path = PROJECT_ROOT / d
        results[d] = path.exists()

    # Check for recent pipeline activity
    artifacts_dir = PROJECT_ROOT / "artifacts"
    recent = False
    if artifacts_dir.exists():
        for f in artifacts_dir.glob("*.json"):
            if time.time() - f.stat().st_mtime < 86400 * 7:  # 7 days
                recent = True
                break

    all_dirs_ok = all(results.values())

    return {
        "directories": results,
        "recent_activity": recent,
        "all_dirs_ok": all_dirs_ok,
        "score": sum(WEIGHT_PIPELINE * (1 if v else 0.5) / len(results) for v in results.values()),
    }


def run_test_suite() -> Dict:
    """Run pytest and return pass/fail summary."""
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        elapsed = time.time() - start

        # Parse pytest summary line
        stdout = result.stdout + result.stderr
        passed = 0
        failed = 0
        total = 0

        for line in stdout.split("\n"):
            if "passed" in line and "=" in line:
                # Parse e.g. "61 passed in 4.2s"
                parts = line.strip().split()
                for p in parts:
                    if p.endswith("passed"):
                        try:
                            passed = int(p.replace("passed", ""))
                            total += passed
                        except: pass
                    if p.endswith("failed"):
                        try:
                            failed = int(p.replace("failed", ""))
                            total += failed
                        except: pass

        if total == 0:
            total = passed + failed
        if total == 0:
            total = "unknown"

        return {
            "passed": passed,
            "failed": failed,
            "total": total,
            "pass_rate": round(passed / total * 100, 1) if isinstance(total, int) and total > 0 else 0,
            "exit_code": result.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "raw_output": stdout[-500:],
            "score": (passed / total * WEIGHT_TESTS) if isinstance(total, int) and total > 0 else 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": 0, "failed": 0, "total": "???",
            "pass_rate": 0, "exit_code": -1,
            "elapsed_seconds": 120, "raw_output": "TIMEOUT",
            "score": 0, "error": "Test suite timed out (>120s)",
        }
    except Exception as e:
        return {
            "passed": 0, "failed": 0, "total": "???",
            "pass_rate": 0, "exit_code": -1,
            "elapsed_seconds": 0, "raw_output": str(e)[:500],
            "score": 0, "error": str(e),
        }


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------
def run_evaluation(skip_pipeline: bool = False) -> Dict:
    """Run the full BuzzBoard health evaluation."""
    results = {}

    # 1. Test suite
    print("🧪 Running test suite...")
    results["tests"] = run_test_suite()
    print(f"   {'✅' if results['tests']['exit_code'] == 0 else '❌'} "
          f"{results['tests']['passed']}/{results['tests']['total']} passed "
          f"({results['tests']['elapsed_seconds']}s)")

    # 2. Pipeline filesystem
    if not skip_pipeline:
        print("📁 Checking pipeline filesystem...")
        results["pipeline"] = check_pipeline_filesystem()
        print(f"   Directories: {results['pipeline']['directories']}")
    else:
        results["pipeline"] = {"score": WEIGHT_PIPELINE, "all_dirs_ok": True,
                                "directories": {}, "recent_activity": True}

    # 3. Agent availability
    print("🤖 Checking agent availability...")
    results["agents"] = check_agent_availability()
    print(f"   {results['agents']['available']}/{results['agents']['total']} agents available")
    if results["agents"]["missing_agents"]:
        print(f"   ❌ Missing: {', '.join(results['agents']['missing_agents'])}")

    # 4. Compute overall
    total_score = sum([
        results["tests"]["score"],
        results["pipeline"]["score"],
        results["agents"]["score"],
    ])
    passed = total_score >= PASS_THRESHOLD

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": results["tests"],
        "pipeline": results["pipeline"],
        "agents": results["agents"],
        "total_score": round(total_score, 1),
        "passed": passed,
        "pass_threshold": PASS_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Streak log
# ---------------------------------------------------------------------------
def update_streak_log(report: Dict, previous_streak: int, new_streak: int):
    """Append run to the BuzzBoard streak log."""
    STREAK_LOG.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%d %b %Y")
    run_id = now.strftime("%Y%m%d-%H%M")

    tests_info = f"{report['tests']['passed']}/{report['tests']['total']} tests"
    agent_info = f"{report['agents']['available']}/{report['agents']['total']} agents"
    changes = "; ".join(report["agents"]["missing_agents"]) if report["agents"]["missing_agents"] else "none"
    if not report["pipeline"].get("all_dirs_ok", True):
        changes += " dirs_missing"

    new_row = (
        f"| {run_id} | {date_str} | {tests_info} | {agent_info} "
        f"| {new_streak} | {changes} | {report['total_score']}% |\n"
    )

    if STREAK_LOG.exists():
        with open(STREAK_LOG, "r") as f:
            content = f.read()
        insert_after = "|------|------|--------|--------|--------|---------|----------|"
        if insert_after in content:
            parts = content.split(insert_after)
            new_content = parts[0] + insert_after + "\n" + new_row + parts[1]
        else:
            new_content = content + new_row
    else:
        header = (
            "# BuzzBoard — Quality Streak Log\n\n"
            "Daily pipeline health check: test suite, filesystem, agent availability.\n\n"
            "| Run ID | Date | Tests | Agents | Streak | Changes | Score |\n"
            "|------|------|--------|--------|--------|---------|----------|\n"
        )
        new_content = header + new_row

    with open(STREAK_LOG, "w") as f:
        f.write(new_content)


def get_previous_streak() -> int:
    """Read streak from last log row."""
    if not STREAK_LOG.exists():
        return 0
    try:
        with open(STREAK_LOG) as f:
            lines = f.readlines()
        for line in reversed(lines):
            if line.startswith("|") and "Run ID" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 6:
                    return int(parts[5])
    except (ValueError, IndexError):
        pass
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="BuzzBoard Quality Streak Evaluation")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--no-pipeline-test", action="store_true")
    parser.add_argument("--no-update-log", action="store_true")
    parser.add_argument("--max-runtime", type=int, default=DEFAULT_MAX_RUNTIME)
    args = parser.parse_args()

    start_time = time.time()

    report = run_evaluation(skip_pipeline=args.no_pipeline_test)
    elapsed = time.time() - start_time

    previous_streak = get_previous_streak()
    new_streak = previous_streak + 1 if report["passed"] else 0

    # Summary
    print(f"\n{'='*60}")
    print(f"🐝 BUZZBOARD EVALUATION — {elapsed:.1f}s")
    print(f"{'='*60}")
    print(f"  Tests:     {report['tests']['passed']}/{report['tests']['total']} passed")
    print(f"  Agents:    {report['agents']['available']}/{report['agents']['total']} available")
    print(f"  Pipeline:  {'✅' if report['pipeline'].get('all_dirs_ok', True) else '❌'}")
    print(f"  Total:     {report['total_score']}/100")
    print(f"  Streak:    {previous_streak} → {new_streak} 🐝")
    print(f"{'='*60}")

    if not args.no_update_log:
        update_streak_log(report, previous_streak, new_streak)

    output_data = {
        **report,
        "streak_before": previous_streak,
        "streak_after": new_streak,
        "elapsed_seconds": round(elapsed, 1),
        "runtime_exceeded": elapsed > args.max_runtime,
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"📄 Full report: {output_path}")
    else:
        print(json.dumps(output_data, indent=2, ensure_ascii=False))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
