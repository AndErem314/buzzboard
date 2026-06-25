# BuzzBoard — Quality Streak Log

Daily pipeline health check: test suite, agent availability, filesystem integrity.

| Run ID | Date | Tests | Agents | Streak | Changes | Score |
|------|------|--------|--------|--------|---------|----------|
| (baseline) | — | — | — | 0 | Initial setup | — |

---

## Scoring

| Dimension | Weight | What it checks |
|-----------|--------|----------------|
| Tests | 50 | pytest pass rate (61 tests) |
| Pipeline | 30 | Filesystem directories, recent activity |
| Agents | 20 | All 6 agents importable |

Pass threshold: ≥70%

## Quick Reference

- **Eval harness:** `python scripts/streak_eval.py`
- **Cron:** Daily 04:00 Berlin (`0 4 * * *`)
- **Dependencies:** pytest, Whisper, Ollama (llama3.1:8b)
