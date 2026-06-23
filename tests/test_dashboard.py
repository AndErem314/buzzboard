"""
Tests for the dashboard (Phase 9: HTML/CSS/JS separation + Hermes redesign).

Validates:
  - Static assets exist and are non-empty
  - index.html references the right CSS/JS files (no inline styles/scripts)
  - server.py contains no inline HTML_TEMPLATE string (it must load from disk)
  - server.py mounts /static and serves the right routes
  - /api endpoints return the expected JSON shape
  - The stage list in JS mirrors the STAGES list in src/db/kanban.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Paths ──────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "dashboard" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
STYLE_CSS = STATIC_DIR / "style.css"
APP_JS = STATIC_DIR / "app.js"
SERVER_PY = REPO_ROOT / "src" / "dashboard" / "server.py"
KANBAN_PY = REPO_ROOT / "src" / "db" / "kanban.py"


# ── Static file presence ──────────────────────────────────────────────

class TestStaticFiles:
    """The dashboard ships its UI as separate static files."""

    def test_static_dir_exists(self):
        assert STATIC_DIR.is_dir(), f"Missing static dir: {STATIC_DIR}"

    def test_index_html_exists(self):
        assert INDEX_HTML.is_file(), f"Missing index.html: {INDEX_HTML}"

    def test_style_css_exists(self):
        assert STYLE_CSS.is_file(), f"Missing style.css: {STYLE_CSS}"

    def test_app_js_exists(self):
        assert APP_JS.is_file(), f"Missing app.js: {APP_JS}"

    def test_index_html_is_substantial(self):
        # A real dashboard skeleton, not a 5-line stub.
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert len(content) > 500, "index.html suspiciously short"

    def test_style_css_is_substantial(self):
        content = STYLE_CSS.read_text(encoding="utf-8")
        # Hermes-style design system is ~10-20 KB.
        assert len(content) > 5_000, "style.css suspiciously short"

    def test_app_js_is_substantial(self):
        content = APP_JS.read_text(encoding="utf-8")
        # Render + filter + drawer logic is several hundred lines.
        assert len(content) > 3_000, "app.js suspiciously short"


# ── index.html structure ──────────────────────────────────────────────

class TestIndexHtml:
    """index.html is a pure scaffold — links out to CSS/JS."""

    def test_references_local_css(self):
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert '/static/style.css' in content, (
            "index.html should load style.css from /static/"
        )

    def test_references_local_js(self):
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert '/static/app.js' in content, (
            "index.html should load app.js from /static/"
        )

    def test_no_inline_style_block(self):
        """No <style> blocks — all CSS lives in style.css."""
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert "<style" not in content.lower(), (
            "index.html should not contain inline <style> blocks"
        )

    def test_no_inline_script_block(self):
        """No <script>...</script> blocks — all JS lives in app.js."""
        content = INDEX_HTML.read_text(encoding="utf-8")
        # Allow the empty <script src=...> reference; forbid inline bodies.
        inline_script_pattern = re.compile(
            r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE
        )
        assert not inline_script_pattern.search(content), (
            "index.html should not contain inline <script> blocks"
        )

    def test_has_required_dom_anchors(self):
        """The JS controller relies on these element IDs."""
        content = INDEX_HTML.read_text(encoding="utf-8")
        for anchor in ("stats", "board", "search", "stage-filter",
                       "refresh-btn", "clear-btn", "countdown",
                       "footer-pulse", "drawer-shade"):
            assert f'id="{anchor}"' in content, (
                f"index.html missing required anchor id={anchor!r}"
            )


# ── server.py structure ───────────────────────────────────────────────

class TestServerModule:
    """server.py must not contain inline HTML templates."""

    def test_no_inline_html_template(self):
        content = SERVER_PY.read_text(encoding="utf-8")
        # The old code had a module-level HTML_TEMPLATE = \"\"\"...\"\"\" string.
        # New code reads from disk via INDEX_HTML.read_text().
        assert "HTML_TEMPLATE" not in content, (
            "server.py still contains an inline HTML_TEMPLATE; "
            "HTML must be loaded from static/index.html instead"
        )

    def test_loads_html_from_disk(self):
        content = SERVER_PY.read_text(encoding="utf-8")
        assert "INDEX_HTML.read_text" in content, (
            "server.py should load the dashboard HTML from disk"
        )

    def test_mounts_static_dir(self):
        content = SERVER_PY.read_text(encoding="utf-8")
        assert 'StaticFiles' in content, (
            "server.py should mount /static/ via StaticFiles"
        )
        assert '"/static"' in content or "mount(\"/static\"" in content, (
            "server.py should mount the /static URL prefix"
        )


# ── Stage list parity (JS ↔ Python) ──────────────────────────────────

class TestStageParity:
    """The JS column order must match the STAGES list in db/kanban.py."""

    def test_js_stages_match_python_stages(self):
        js_content = APP_JS.read_text(encoding="utf-8")
        py_content = KANBAN_PY.read_text(encoding="utf-8")

        # Extract Python STAGES list — should look like:
        #   STAGES = ["inbox", "transcribing", ...]
        py_match = re.search(r"STAGES\s*=\s*\[([^\]]+)\]", py_content)
        assert py_match, "Could not find STAGES list in db/kanban.py"
        py_stages = re.findall(r'"([^"]+)"', py_match.group(1))

        # Extract JS STAGES list — should look like:
        #   const STAGES = [ "inbox", "transcribing", ... ];
        js_match = re.search(r"const\s+STAGES\s*=\s*\[([^\]]+)\]", js_content)
        assert js_match, "Could not find STAGES list in static/app.js"
        js_stages = re.findall(r'"([^"]+)"', js_match.group(1))

        assert js_stages == py_stages, (
            f"JS STAGES {js_stages!r} does not match Python STAGES {py_stages!r}. "
            f"Update static/app.js to mirror src/db/kanban.py."
        )


# ── Server route smoke test ───────────────────────────────────────────
#
# We use FastAPI's TestClient (no network, no real port). The KanbanBoard
# module is opened against a temp SQLite file by monkeypatching the
# module-level `board` instance in server.py.

class TestRoutes:
    """End-to-end checks of the FastAPI app via TestClient."""

    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch):
        """Spin up the FastAPI app against a fresh empty Kanban DB."""
        from src.dashboard import server
        from src.db.kanban import KanbanBoard

        db_path = tmp_path / "test_kanban.db"
        # Replace the module-level `board` with one bound to tmp_path.
        server.board = KanbanBoard(str(db_path))

        # TestClient raises on startup errors so we catch them here.
        with TestClient(server.app) as c:
            yield c

    def test_root_serves_index_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        body = resp.text
        assert "BuzzBoard" in body, "Dashboard title missing from index.html"

    def test_static_css_served(self, client):
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        # CSS files served with the right content type by StaticFiles.
        assert "text/css" in resp.headers["content-type"]
        body = resp.text
        # Sanity: the Hermes-inspired design tokens are present.
        assert "--bb-bg" in body, "CSS missing design tokens (--bb-bg)"
        assert ".bb-column" in body, "CSS missing .bb-column rules"
        assert ".bb-dot" in body, "CSS missing .bb-dot rules"

    def test_static_js_served(self, client):
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        body = resp.text
        # Sanity: core controller functions are defined.
        assert "function loadBoard" in body
        assert "function renderBoard" in body
        assert "function openTaskDrawer" in body

    def test_api_board_empty(self, client):
        resp = client.get("/api/board")
        assert resp.status_code == 200
        data = resp.json()
        assert "stages" in data
        assert "stats" in data
        # All 7 stages present, even if empty.
        for stage in ("inbox", "transcribing", "editing",
                      "extracting", "storing", "done", "failed"):
            assert stage in data["stages"]

    def test_api_stats_empty(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tasks"] == 0
        assert data["total_events"] == 0

    def test_api_task_not_found(self, client):
        resp = client.get("/api/tasks/does-not-exist")
        assert resp.status_code == 404

    def test_api_task_with_events(self, client, tmp_path: Path):
        """A task with logged events should round-trip cleanly."""
        from src.dashboard import server

        server.board.create_task("H07_2026-06-06", "H07", "test.m4a")
        server.board.move_to("H07_2026-06-06", "transcribing")
        server.board.log_event(
            "H07_2026-06-06", "transcriber", "started", duration_ms=1500.0
        )

        resp = client.get("/api/tasks/H07_2026-06-06")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"]["id"] == "H07_2026-06-06"
        assert data["task"]["stage"] == "transcribing"
        assert len(data["events"]) == 1
        assert data["events"][0]["agent"] == "transcriber"

    def test_api_board_after_task_moves(self, client, tmp_path: Path):
        """Tasks should appear under their current stage column."""
        from src.dashboard import server

        server.board.create_task("H01", "H01", "a.m4a")
        server.board.create_task("H02", "H02", "b.m4a")
        server.board.move_to("H02", "done")

        resp = client.get("/api/board")
        data = resp.json()
        assert len(data["stages"]["inbox"]) == 1
        assert data["stages"]["inbox"][0]["id"] == "H01"
        assert len(data["stages"]["done"]) == 1
        assert data["stages"]["done"][0]["id"] == "H02"
