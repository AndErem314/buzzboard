/*
 * BuzzBoard Dashboard — Kanban UI controller.
 *
 * Vanilla JS, no build step. Loaded as a plain <script> from
 * static/index.html. Talks to the FastAPI backend at /api/*.
 *
 * Responsibilities:
 *   - Poll /api/board every N seconds and re-render the columns
 *   - Render stage columns with colored dot indicators + counts
 *   - Filter by hive (search) + active stage checkboxes
 *   - Open a side drawer with full task + event log on card click
 *   - Show live countdown + last-updated pulse in the footer
 */

(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────────

  // Column order matches STAGES in src/db/kanban.py — single source of
  // truth stays in Python; this is a presentation-only mirror.
  const STAGES = [
    "inbox",
    "transcribing",
    "editing",
    "extracting",
    "storing",
    "done",
    "failed",
  ];

  const STAGE_META = {
    inbox:        { label: "Inbox",        icon: "📥", help: "Voice memos waiting to enter the pipeline" },
    transcribing: { label: "Transcribing", icon: "🎙️", help: "Whisper converting audio to text" },
    editing:      { label: "Editing",      icon: "✏️",  help: "LLM cleaning and structuring the transcript" },
    extracting:   { label: "Extracting",   icon: "🔍", help: "LLM pulling out structured inspection fields" },
    storing:      { label: "Storing",      icon: "📁", help: "Writing the note to Obsidian" },
    done:         { label: "Done",         icon: "✅", help: "Pipeline complete — note lives in your vault" },
    failed:       { label: "Failed",       icon: "❌", help: "Pipeline hit an error — click for details" },
  };

  const REFRESH_SECONDS = 10;

  // ── DOM refs (populated on DOMContentLoaded) ──────────────────────

  const $ = (id) => document.getElementById(id);

  let els = {};

  // ── State ──────────────────────────────────────────────────────────

  const state = {
    board: null,            // last fetched board payload
    stats: null,            // last fetched stats
    countdown: REFRESH_SECONDS,
    countdownTimer: null,
    refreshTimer: null,
    filters: {
      search: "",
      stage: "all",        // 'all' | stage name
    },
    activeTaskId: null,
  };

  // ── Utilities ──────────────────────────────────────────────────────

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    // Strip the ISO timestamp down to HH:MM:SS for compactness.
    // Tasks created today show just time; older ones prepend the date.
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    const time = `${hh}:${mm}:${ss}`;
    if (sameDay) return time;
    return d.toISOString().slice(0, 10) + " " + time;
  }

  function fmtDuration(ms) {
    if (!ms || ms <= 0) return "—";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  // ── API ────────────────────────────────────────────────────────────

  async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) {
      let body = "";
      try { body = await resp.text(); } catch (_e) { /* ignore */ }
      throw new Error(`${resp.status}: ${body || resp.statusText}`);
    }
    return resp.json();
  }

  async function loadBoard() {
    const boardData = await fetchJSON("/api/board");
    state.board = boardData;
    state.stats = boardData.stats;
    renderAll();
  }

  // ── Render: stats ──────────────────────────────────────────────────

  function renderStats() {
    if (!state.stats) return;
    const s = state.stats;
    const avg = s.avg_duration_seconds
      ? `${s.avg_duration_seconds}s`
      : "—";
    els.stats.innerHTML = `
      <div class="bb-stats-item">
        <div class="bb-stats-value">${escapeHtml(s.total_tasks)}</div>
        <div class="bb-stats-label">Total Tasks</div>
      </div>
      <div class="bb-stats-item">
        <div class="bb-stats-value">${escapeHtml(s.total_events)}</div>
        <div class="bb-stats-label">Events Logged</div>
      </div>
      <div class="bb-stats-item">
        <div class="bb-stats-value">${escapeHtml(avg)}</div>
        <div class="bb-stats-label">Avg Duration</div>
      </div>
    `;
  }

  // ── Render: board ──────────────────────────────────────────────────

  function applyFilters(tasks) {
    const q = state.filters.search.trim().toLowerCase();
    return tasks.filter((t) => {
      if (state.filters.stage !== "all" && t.stage !== state.filters.stage) return false;
      if (!q) return true;
      // Match against id, hive_id, audio_file, error
      const haystack = [
        t.id, t.hive_id, t.audio_file, t.error || "",
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }

  function renderBoard() {
    if (!state.board) return;
    const stages = state.board.stages || {};
    const allTasks = [];
    for (const stage of STAGES) {
      const tasks = stages[stage] || [];
      for (const t of tasks) allTasks.push(t);
    }
    const filtered = applyFilters(allTasks);

    // Group filtered tasks by stage
    const grouped = {};
    for (const s of STAGES) grouped[s] = [];
    for (const t of filtered) {
      if (grouped[t.stage]) grouped[t.stage].push(t);
    }

    els.board.innerHTML = STAGES.map((stage) => {
      const meta = STAGE_META[stage] || { label: stage, help: "" };
      const tasks = grouped[stage] || [];
      const totalCount = (stages[stage] || []).length;
      const filteredCount = tasks.length;
      const countText = state.filters.search || state.filters.stage !== "all"
        ? `${filteredCount}/${totalCount}`
        : `${totalCount}`;
      const cardsHtml = tasks.length === 0
        ? `<div class="bb-empty">— no tasks —</div>`
        : tasks.map(renderCard).join("");
      return `
        <section class="bb-column" data-stage="${escapeHtml(stage)}">
          <header class="bb-column-head">
            <span class="bb-dot bb-dot-${escapeHtml(stage)}"></span>
            <span class="bb-column-label">${escapeHtml(meta.icon)} ${escapeHtml(meta.label)}</span>
            <span class="bb-column-count">${escapeHtml(countText)}</span>
          </header>
          <div class="bb-column-sub">${escapeHtml(meta.help)}</div>
          <div class="bb-column-body">${cardsHtml}</div>
        </section>
      `;
    }).join("");

    // Re-attach card click handlers (innerHTML wipes them).
    els.board.querySelectorAll(".bb-card").forEach((card) => {
      card.addEventListener("click", () => {
        const id = card.getAttribute("data-task-id");
        if (id) openTaskDrawer(id);
      });
    });
  }

  function renderCard(task) {
    let cls = "bb-card";
    let pulse = "";
    if (task.stage === "failed") cls += " bb-card-failed";
    else if (task.stage === "done") cls += " bb-card-done";
    else if (task.stage !== "inbox") {
      cls += " bb-card-active";
      pulse = " bb-card-pulse";
    }

    const updated = task.updated_at || task.created_at;
    const errorLine = task.error
      ? `<div class="bb-card-error">⚠ ${escapeHtml(task.error.slice(0, 80))}</div>`
      : "";

    return `
      <div class="${cls}${pulse}" data-task-id="${escapeHtml(task.id)}">
        <div class="bb-card-row">
          <span class="bb-card-id">${escapeHtml(task.id)}</span>
          <span class="bb-card-meta">
            <span>${escapeHtml(task.hive_id)}</span>
            <span class="bb-card-time">${escapeHtml(fmtTime(updated))}</span>
          </span>
        </div>
        ${errorLine}
      </div>
    `;
  }

  // ── Render: stage filter (populated from STAGES) ───────────────────

  function renderStageFilter() {
    const opts = ['<option value="all">All stages</option>'].concat(
      STAGES.map((s) =>
        `<option value="${escapeHtml(s)}">${escapeHtml(STAGE_META[s]?.label || s)}</option>`
      )
    );
    els.stageFilter.innerHTML = opts.join("");
  }

  // ── Render: everything ──────────────────────────────────────────────

  function renderAll() {
    renderStats();
    renderBoard();
    updateFooterPulse(true);
  }

  // ── Footer / pulse indicator ───────────────────────────────────────

  function updateFooterPulse(fresh) {
    const dot = els.footerPulse;
    if (fresh) dot.classList.remove("bb-footer-pulse-stale");
    else dot.classList.add("bb-footer-pulse-stale");
  }

  function tickCountdown() {
    state.countdown--;
    if (state.countdown <= 0) {
      state.countdown = REFRESH_SECONDS;
      loadBoard().catch((err) => {
        // Network blip — keep countdown moving, mark stale.
        console.error("Refresh failed:", err);
        updateFooterPulse(false);
      });
    }
    els.countdown.textContent = `${state.countdown}s`;
  }

  // ── Drawer (task detail) ────────────────────────────────────────────
  //
  // The drawer is built into the `#drawer-shade` container, which is
  // hidden by default. We write the drawer markup into the shade's
  // innerHTML and remove the `hidden` attribute to show it.

  async function openTaskDrawer(taskId) {
    state.activeTaskId = taskId;
    let payload;
    try {
      payload = await fetchJSON(`/api/tasks/${encodeURIComponent(taskId)}`);
    } catch (err) {
      console.error("Failed to load task:", err);
      return;
    }
    const t = payload.task;
    const events = payload.events || [];
    const meta = STAGE_META[t.stage] || { label: t.stage };

    els.drawerShade.innerHTML = `
      <aside class="bb-drawer">
        <header class="bb-drawer-head">
          <div class="bb-drawer-title">
            <span class="bb-dot bb-dot-${escapeHtml(t.stage)}"></span>
            <span class="bb-card-id">${escapeHtml(t.id)}</span>
            <span style="font-weight:500;color:var(--bb-fg-muted);">— ${escapeHtml(meta.label || t.stage)}</span>
          </div>
          <button class="bb-drawer-close" type="button" aria-label="Close">×</button>
        </header>
        <div class="bb-drawer-body">
          <div class="bb-meta-card">
            <div class="bb-meta-row">
              <span class="bb-meta-label">Hive</span>
              <span class="bb-meta-value">${escapeHtml(t.hive_id)}</span>
            </div>
            <div class="bb-meta-row">
              <span class="bb-meta-label">Audio file</span>
              <span class="bb-meta-value">${escapeHtml(t.audio_file)}</span>
            </div>
            <div class="bb-meta-row">
              <span class="bb-meta-label">Created</span>
              <span class="bb-meta-value">${escapeHtml(fmtTime(t.created_at))}</span>
            </div>
            <div class="bb-meta-row">
              <span class="bb-meta-label">Updated</span>
              <span class="bb-meta-value">${escapeHtml(fmtTime(t.updated_at))}</span>
            </div>
            ${t.completed_at ? `
            <div class="bb-meta-row">
              <span class="bb-meta-label">Completed</span>
              <span class="bb-meta-value">${escapeHtml(fmtTime(t.completed_at))}</span>
            </div>` : ""}
            ${t.error ? `
            <div class="bb-meta-row">
              <span class="bb-meta-label">Error</span>
              <span class="bb-meta-value" style="color:var(--bb-dot-failed);">⚠ ${escapeHtml(t.error.slice(0, 400))}</span>
            </div>` : ""}
          </div>

          <div>
            <div class="bb-section-title">Event log (${events.length})</div>
            ${events.length === 0
              ? `<div class="bb-events-empty">No events logged yet.</div>`
              : `
              <table class="bb-events">
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Action</th>
                    <th>Duration</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  ${events.map((e) => `
                    <tr>
                      <td class="bb-events-agent">${escapeHtml(e.agent)}</td>
                      <td>${escapeHtml(e.action)}</td>
                      <td>${escapeHtml(fmtDuration(e.duration_ms))}</td>
                      <td class="bb-events-time">${escapeHtml(fmtTime(e.created_at))}</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            `}
          </div>
        </div>
      </aside>
    `;

    // Wire close handlers against the freshly injected markup.
    const drawer = els.drawerShade.querySelector(".bb-drawer");
    drawer.querySelector(".bb-drawer-close").addEventListener("click", closeTaskDrawer);
    els.drawerShade.addEventListener("click", shadeClickHandler);
    document.addEventListener("keydown", escCloseDrawer);

    els.drawerShade.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function shadeClickHandler(e) {
    // Close when the user clicks the shade backdrop (not the drawer itself).
    if (e.target === els.drawerShade) closeTaskDrawer();
  }

  function escCloseDrawer(e) {
    if (e.key === "Escape") closeTaskDrawer();
  }

  function closeTaskDrawer() {
    els.drawerShade.hidden = true;
    els.drawerShade.innerHTML = "";
    els.drawerShade.removeEventListener("click", shadeClickHandler);
    document.removeEventListener("keydown", escCloseDrawer);
    document.body.style.overflow = "";
    state.activeTaskId = null;
  }

  // ── Event wiring ───────────────────────────────────────────────────

  function wireEvents() {
    // Search filter (debounced via timeout reset)
    let searchTimer = null;
    els.search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const value = els.search.value;
      searchTimer = setTimeout(() => {
        state.filters.search = value;
        renderBoard();
      }, 150);
    });

    // Stage filter
    els.stageFilter.addEventListener("change", () => {
      state.filters.stage = els.stageFilter.value;
      renderBoard();
    });

    // Manual refresh
    els.refreshBtn.addEventListener("click", () => {
      state.countdown = REFRESH_SECONDS;
      loadBoard().catch((err) => console.error("Refresh failed:", err));
    });

    // Clear filters
    els.clearBtn.addEventListener("click", () => {
      els.search.value = "";
      els.stageFilter.value = "all";
      state.filters = { search: "", stage: "all" };
      renderBoard();
    });
  }

  // ── Bootstrap ──────────────────────────────────────────────────────

  function init() {
    els = {
      stats:        $("stats"),
      board:        $("board"),
      search:       $("search"),
      stageFilter:  $("stage-filter"),
      refreshBtn:   $("refresh-btn"),
      clearBtn:     $("clear-btn"),
      countdown:    $("countdown"),
      footerPulse:  $("footer-pulse"),
      drawerShade:  $("drawer-shade"),
    };

    renderStageFilter();
    wireEvents();

    // First paint, then schedule refresh.
    loadBoard().catch((err) => {
      console.error("Initial load failed:", err);
      els.board.innerHTML = `<div class="bb-empty">⚠ Failed to load: ${escapeHtml(err.message)}</div>`;
      updateFooterPulse(false);
    });

    state.countdownTimer = setInterval(tickCountdown, 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();