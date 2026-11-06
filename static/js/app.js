/**
 * Auto Content Pipeline — UI PRO MAX Single Page App Controller
 * Ultra-clean reactive frontend handling real-time SSE logs, queue manipulation,
 * live preview galleries, and asynchronous pipeline controls.
 */

let sseEventSource = null;
let autoScrollLogs = true;

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initSidebarCollapse();
    initN8nCanvas();
    initSSE();
    loadDashboardStats();
    loadQueue();
    loadSettings();
    loadArticles();
    checkGflowStatus(false);
    initEventListeners();
});

// ── Universal Navigation (Desktop Sidebar & Mobile Bottom Nav) ─
function switchTab(target) {
    if (!target) return;
    const navItems = document.querySelectorAll(".nav-item");
    const mobileNavItems = document.querySelectorAll(".mobile-nav-item");
    const pages = document.querySelectorAll(".page-container");

    navItems.forEach(n => {
        n.classList.toggle("active", n.dataset.target === target);
    });
    mobileNavItems.forEach(n => {
        n.classList.toggle("active", n.dataset.target === target);
    });
    pages.forEach(p => {
        p.classList.toggle("active", p.id === `page-${target}`);
    });

    closeMobileSidebar();

    const targetPage = document.getElementById(`page-${target}`);
    if (targetPage) targetPage.scrollTop = 0;

    // Lazy load specific tab content
    if (target === "queue") loadQueue();
    if (target === "articles") loadArticles();
    if (target === "settings") loadSettings();
    if (target === "control-deck") {
        loadSettings();
        setTimeout(() => {
            renderN8nConnections();
        }, 80);
    }
}

function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const mobileNavItems = document.querySelectorAll(".mobile-nav-item");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            switchTab(item.dataset.target);
        });
    });

    mobileNavItems.forEach(item => {
        item.addEventListener("click", () => {
            switchTab(item.dataset.target);
        });
    });
}

// ── Server-Sent Events (SSE) Real-Time Logging ─────────────────
function initSSE() {
    if (sseEventSource) {
        sseEventSource.close();
    }

    sseEventSource = new EventSource("/api/logs/stream");

    sseEventSource.addEventListener("log", (e) => {
        try {
            const payload = JSON.parse(e.data);
            appendLogLine(payload);
        } catch (err) {
            console.error("Failed to parse log event:", err);
        }
    });

    sseEventSource.addEventListener("status", (e) => {
        try {
            const payload = JSON.parse(e.data);
            updateStatusUI(payload.data.state === "running");
            loadDashboardStats();
        } catch (err) {}
    });

    sseEventSource.addEventListener("active_task", (e) => {
        try {
            const payload = JSON.parse(e.data);
            const ticker = document.getElementById("active-task-ticker");
            if (ticker) {
                ticker.textContent = `Active: ${payload.data.url} (${payload.data.category || 'General'})`;
            }
        } catch (err) {}
    });

    sseEventSource.addEventListener("queue_updated", () => {
        loadDashboardStats();
        const queuePage = document.getElementById("page-queue");
        if (queuePage && queuePage.classList.contains("active")) {
            loadQueue();
        }
    });

    sseEventSource.addEventListener("gflow_terminal", (e) => {
        try {
            const payload = JSON.parse(e.data);
            appendGflowTermLine(payload.data.text, payload.data.type);
        } catch (err) {}
    });

    sseEventSource.addEventListener("gflow_status_change", (e) => {
        try {
            const payload = JSON.parse(e.data);
            if (payload.data.authenticated !== undefined) {
                updateGflowStatusBadges(payload.data.authenticated, payload.data.message);
            }
            if (payload.data.version) {
                updateGflowVersionBadge(payload.data.version);
            }
        } catch (err) {}
    });

    sseEventSource.onerror = () => {
        // Automatically reconnects
    };
}

function appendLogLine(item) {
    const termBody = document.getElementById("terminal-body");
    const recentActivity = document.getElementById("recent-activity-list");
    if (!termBody) return;

    const data = item.data || {};
    const level = data.level || "info";
    const msg = data.message || "";
    const ts = item.ts || new Date().toLocaleTimeString();

    const line = document.createElement("div");
    line.className = `log-line log-level-${level}`;
    line.innerHTML = `<span class="log-time">[${ts}]</span> [${level.toUpperCase()}] ${escapeHtml(msg)}`;

    termBody.appendChild(line);

    if (autoScrollLogs) {
        termBody.scrollTop = termBody.scrollHeight;
    }

    // Update compact recent activity on dashboard
    if (recentActivity) {
        const actLine = document.createElement("div");
        actLine.className = `log-line log-level-${level}`;
        actLine.style.fontSize = "0.78rem";
        actLine.innerHTML = `<span class="log-time">${ts}</span> ${escapeHtml(msg)}`;
        recentActivity.insertBefore(actLine, recentActivity.firstChild);
        if (recentActivity.children.length > 8) {
            recentActivity.removeChild(recentActivity.lastChild);
        }
    }
}

function updateStatusUI(isRunning) {
    const pill = document.getElementById("system-status-pill");
    const text = document.getElementById("system-status-text");
    const btnStart = document.getElementById("btn-start");
    const btnStop = document.getElementById("btn-stop");

    if (isRunning) {
        pill.className = "status-pill running";
        text.textContent = "RUNNING";
        if (btnStart) btnStart.style.display = "none";
        if (btnStop) btnStop.style.display = "inline-flex";
    } else {
        pill.className = "status-pill";
        text.textContent = "IDLE";
        if (btnStart) btnStart.style.display = "inline-flex";
        if (btnStop) btnStop.style.display = "none";
    }
}

// ── Dashboard Metrics & Previews ──────────────────────────────
async function loadDashboardStats() {
    try {
        const res = await fetch("/api/stats");
        const data = await res.json();

        document.getElementById("stat-total").textContent = data.total;
        document.getElementById("stat-pending").textContent = data.pending;
        document.getElementById("stat-done").textContent = data.done;
        document.getElementById("stat-failed").textContent = data.failed;
        document.getElementById("stat-published").textContent = data.published;

        // Progress Bar
        const percent = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
        const progFill = document.getElementById("progress-fill");
        const progText = document.getElementById("progress-text");
        if (progFill) progFill.style.width = `${percent}%`;
        if (progText) progText.textContent = `${percent}% Completed (${data.done}/${data.total})`;

        updateStatusUI(data.running);

        if (data.active_url) {
            document.getElementById("active-task-ticker").textContent = `Processing: ${data.active_url}`;
        } else if (!data.running) {
            document.getElementById("active-task-ticker").textContent = "Ready — system is waiting for tasks.";
        }

        // Live Feature & Pinterest Pin previews
        const featBox = document.getElementById("dashboard-feature-preview");
        if (featBox && data.latest_feature) {
            featBox.innerHTML = `<img src="${data.latest_feature}?t=${Date.now()}" alt="Feature Hero" />`;
        }
        const pinBox = document.getElementById("dashboard-pin-preview");
        if (pinBox && data.latest_pin) {
            pinBox.innerHTML = `<img src="${data.latest_pin}?t=${Date.now()}" alt="Pinterest Pin" /><span class="pin-badge">Pinterest 2:3</span>`;
        }
    } catch (e) {
        console.error("Error loading stats:", e);
    }
}

// ── Queue Management ──────────────────────────────────────────
async function loadQueue() {
    const search = document.getElementById("queue-search")?.value || "";
    const filter = document.getElementById("queue-filter")?.value || "all";
    const tbody = document.getElementById("queue-table-body");
    if (!tbody) return;

    try {
        const res = await fetch(`/api/queue?search=${encodeURIComponent(search)}&status=${encodeURIComponent(filter)}`);
        const rows = await res.json();

        if (rows.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-dim);">No URLs in queue. Click "Add URL" or upload a CSV to get started!</td></tr>`;
            return;
        }

        tbody.innerHTML = rows.map(r => `
            <tr>
                <td class="url-cell" title="${escapeHtml(r.url)}">
                    <div>${escapeHtml(r.url)}</div>
                    ${(r.status === 'done' && r.post_url) ? `
                        <div style="margin-top:5px;">
                            <a href="${escapeHtml(r.post_url)}" target="_blank" rel="noopener" style="display:inline-flex; align-items:center; gap:4px; font-size:0.75rem; color:#38bdf8; text-decoration:none; background:rgba(56,189,248,0.12); padding:2px 8px; border-radius:4px; border:1px solid rgba(56,189,248,0.3); font-weight:600;">
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                                Published Post ↗
                            </a>
                        </div>
                    ` : ''}
                </td>
                <td><span style="font-weight:600; color:#93c5fd;">${escapeHtml(r.category || 'General')}</span></td>
                <td>
                    <select class="status-select ${r.status}" onchange="changeItemStatus(${r.id}, this.value)">
                        <option value="pending" ${r.status === 'pending' ? 'selected' : ''}>Pending</option>
                        <option value="processing" ${r.status === 'processing' ? 'selected' : ''}>Processing</option>
                        <option value="done" ${r.status === 'done' ? 'selected' : ''}>Done</option>
                        <option value="failed" ${r.status === 'failed' ? 'selected' : ''}>Failed</option>
                    </select>
                </td>
                <td style="color:var(--text-dim); font-size:0.78rem;">${r.created_at || 'Just now'}</td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="deleteQueueItem(${r.id})" title="Delete URL">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                </td>
            </tr>
        `).join("");
    } catch (err) {
        console.error("Error loading queue:", err);
    }
}

async function changeItemStatus(id, newStatus) {
    try {
        await fetch(`/api/queue/${id}/status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus })
        });
        showToast(`Status updated to ${newStatus}`, "info");
        loadQueue();
        loadDashboardStats();
    } catch (e) {
        showToast("Failed to update status", "error");
    }
}

async function deleteQueueItem(id) {
    if (!confirm("Are you sure you want to remove this URL from the queue?")) return;
    try {
        await fetch(`/api/queue/${id}`, { method: "DELETE" });
        showToast("URL removed", "info");
        loadQueue();
        loadDashboardStats();
    } catch (e) {
        showToast("Failed to delete URL", "error");
    }
}

function exportQueueCsv() {
    const search = document.getElementById("queue-search")?.value || "";
    const filter = document.getElementById("queue-filter")?.value || "all";
    const exportUrl = `/api/queue/export?search=${encodeURIComponent(search)}&status=${encodeURIComponent(filter)}`;
    showToast("Exporting Queue CSV with live published links...", "info");
    const link = document.createElement("a");
    link.href = exportUrl;
    link.setAttribute("download", "");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ── Settings Management & Interactive Control Deck ─────────────
let currentSettingsCache = {};

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const cfg = await res.json();
        currentSettingsCache = { ...currentSettingsCache, ...cfg };

        // Populate form fields
        for (const [key, val] of Object.entries(cfg)) {
            const el = document.getElementById(`setting-${key}`);
            if (!el) continue;
            if (el.type === "checkbox") {
                el.checked = Boolean(val);
            } else {
                el.value = val;
            }
        }

        toggleEngineFields(cfg.text_engine, cfg.image_engine);
        syncControlDeckUI(cfg);
    } catch (e) {
        console.error("Error loading settings:", e);
    }
}

async function saveSettings(e) {
    if (e) e.preventDefault();
    const form = document.getElementById("settings-form");
    if (!form) return;

    const data = {};
    const inputs = form.querySelectorAll("input, select, textarea");
    inputs.forEach(input => {
        if (!input.name) return;
        if (input.type === "checkbox") {
            data[input.name] = input.checked;
        } else if (input.type === "number") {
            data[input.name] = Number(input.value);
        } else {
            data[input.name] = input.value;
        }
    });

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            showToast("Settings saved successfully!", "success");
            currentSettingsCache = { ...currentSettingsCache, ...data };
            syncControlDeckUI(currentSettingsCache);
        } else {
            showToast("Error saving settings", "error");
        }
    } catch (err) {
        showToast("Failed to connect to backend", "error");
    }
}

// ── Control Deck Master Operations ────────────────────────────
async function deckQuickSet(key, val) {
    try {
        const payload = {};
        payload[key] = val;

        const res = await fetch("/api/settings/quick-update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (data.success) {
            showToast(`Setting '${key}' updated to '${val}'`, "success");
            currentSettingsCache[key] = val;

            // Mirror change into standard form input if present
            const formEl = document.getElementById(`setting-${key}`);
            if (formEl) {
                if (formEl.type === "checkbox") {
                    formEl.checked = Boolean(val);
                } else {
                    formEl.value = val;
                }
            }

            // Sync visual chips, badges & diagram
            syncControlDeckUI(currentSettingsCache);
        } else {
            showToast(data.error || "Update failed", "error");
        }
    } catch (err) {
        showToast("Failed to connect to backend", "error");
        console.error("deckQuickSet error:", err);
    }
}

function deckToggleWpStatus() {
    const current = currentSettingsCache.status || "draft";
    const next = current === "publish" ? "draft" : "publish";
    deckQuickSet("status", next);
}

function deckToggleAutoPublish() {
    const current = Boolean(currentSettingsCache.auto_publish);
    const next = !current;
    deckQuickSet("auto_publish", next);
}

function syncControlDeckUI(cfg) {
    if (!cfg) return;

    // Update active highlight on all chips with data-field
    document.querySelectorAll(".deck-chip[data-field]").forEach(chip => {
        const field = chip.dataset.field;
        const val = chip.dataset.val;
        if (cfg[field] !== undefined) {
            if (String(cfg[field]) === String(val)) {
                chip.classList.add("active");
            } else {
                chip.classList.remove("active");
            }
        }
    });

    // Helper to safely update text across multiple badge elements
    const setBadgeText = (ids, text, extraClass = "") => {
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = text;
                if (extraClass) el.className = `${el.className.split(' ')[0]} ${extraClass}`;
            }
        });
    };

    // Post Layout Badge
    if (cfg.post_layout_order) {
        setBadgeText(["deck-badge-layout", "deck-badge-layout-node"], cfg.post_layout_order.toUpperCase().replace(/_/g, " "), "blue");
    }

    // Heading Overlay Mode & Master Toggle Badge
    if (cfg.heading_overlay_mode !== undefined || cfg.heading_text_overlay !== undefined) {
        let text = "CLEAN ART (OFF)";
        let extraClass = "teal";
        if (cfg.heading_text_overlay) {
            if (cfg.heading_overlay_mode === "all") {
                text = "ALL HEADINGS (ON)";
            } else {
                text = "FIRST ONLY (ON)";
            }
        }
        setBadgeText(["deck-badge-overlay", "deck-badge-overlay-node"], text, extraClass);
    }

    // Hero Count & Overlay Badge
    if (cfg.feature_image_count) {
        setBadgeText(["deck-badge-hero-count"], `${cfg.feature_image_count} HERO${cfg.feature_image_count > 1 ? 'ES' : ''}`);
    }

    // WordPress Publishing Status
    if (cfg.status) {
        const isPub = cfg.status === "publish";
        setBadgeText(["deck-badge-wp-status", "deck-badge-wp-status-node"], isPub ? "LIVE PUBLISH" : "DRAFT SAFE", isPub ? "green" : "amber");
        
        ["deck-val-wp-status", "deck-val-wp-status-node"].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = isPub ? "PUBLISH (Live to World)" : "DRAFT (Safe in WordPress)";
                el.style.color = isPub ? "var(--accent-green)" : "var(--accent-amber)";
            }
        });
    }

    // Auto-Publish
    if (cfg.auto_publish !== undefined) {
        const isAuto = Boolean(cfg.auto_publish);
        setBadgeText(["deck-badge-auto-pub"], isAuto ? "AUTO ON" : "MANUAL ONLY", isAuto ? "green" : "amber");

        ["deck-val-auto-pub", "deck-val-auto-pub-node"].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = isAuto ? "ON (Hands-Free Instant Post)" : "OFF (Hold in Queue)";
                el.style.color = isAuto ? "var(--accent-green)" : "var(--accent-amber)";
            }
        });
    }

    // Independent Resolutions
    if (cfg.feature_resolution) {
        setBadgeText(["deck-badge-feat-res", "deck-badge-feat-res-node"], cfg.feature_resolution.toUpperCase(), "indigo");
        ["deck-input-feat-res", "deck-input-feat-res-node"].forEach(id => {
            const input = document.getElementById(id);
            if (input && !['sd', 'hd', 'fhd', '2k'].includes(cfg.feature_resolution.toLowerCase())) {
                input.value = cfg.feature_resolution;
            }
        });
    }

    if (cfg.resolution) {
        setBadgeText(["deck-badge-sec-res"], cfg.resolution.toUpperCase());
        ["deck-input-sec-res"].forEach(id => {
            const input = document.getElementById(id);
            if (input && !['sd', 'hd', 'fhd', '2k'].includes(cfg.resolution.toLowerCase())) {
                input.value = cfg.resolution;
            }
        });
    }

    if (cfg.pin_resolution || cfg.pin_text_overlay !== undefined) {
        const res = cfg.pin_resolution || "1000x1500";
        const overlay = cfg.pin_text_overlay ? "OVERLAY ON" : "CLEAN";
        setBadgeText(["deck-badge-pin-res", "deck-badge-pin-res-node"], `${res} (${overlay})`, "rose");
        ["deck-input-pin-res"].forEach(id => {
            const input = document.getElementById(id);
            if (input && !['1000x1500', '735x1102', '1080x1920'].includes(cfg.pin_resolution)) {
                input.value = cfg.pin_resolution;
            }
        });
    }

    // AI Text Engine
    if (cfg.text_engine) {
        const text = cfg.text_engine === "agy" ? "ANTIGRAVITY CLI" : "GEMINI API";
        setBadgeText(["deck-badge-text-eng", "deck-badge-text-eng-node"], text, "purple");
    }

    // AI Visual Engine
    if (cfg.image_engine) {
        const labels = {
            gflow: "GOOGLE FLOW (gflow)",
            agy_fallback: "AGY + POLLINATIONS",
            pollinations: "POLLINATIONS",
            gemini_api: "GEMINI IMAGEN 3",
            my_server: "MY SERVER GPU",
            agy_only: "ANTIGRAVITY ONLY"
        };
        const text = labels[cfg.image_engine] || cfg.image_engine.toUpperCase();
        setBadgeText(["deck-badge-img-eng", "deck-badge-img-eng-node"], text, "pink");
    }

    // Format & Style
    if (cfg.article_format) {
        setBadgeText(["deck-badge-art-fmt"], cfg.article_format.toUpperCase().replace(/_/g, " "));
    }
    if (cfg.image_type) {
        setBadgeText(["deck-badge-img-style"], cfg.image_type.toUpperCase().replace(/_/g, " "));
    }

    // Render Dynamic Sequence Diagram in both bento view & n8n node
    renderDeckLayoutDiagram(cfg.post_layout_order || "standard", cfg.feature_image_count || 1);

    // Refresh n8n SVG connecting lines
    setTimeout(renderN8nConnections, 40);
}

function renderDeckLayoutDiagram(order, heroCount) {
    const containers = [
        document.getElementById("deck-layout-diagram"),
        document.getElementById("n8n-node-layout-diagram")
    ].filter(Boolean);

    if (containers.length === 0) return;

    let steps = [];
    const isDualHero = parseInt(heroCount, 10) === 2;

    switch (order) {
        case "dual_hero":
            steps = [
                { title: "Hero 1 (Featured)", type: "hero", meta: "Landscape 1.91:1" },
                { title: "Hero 2 (Context)", type: "hero", meta: "Landscape 1.91:1" },
                { title: "Intro Hook", type: "intro", meta: "Lead Paragraphs" },
                { title: "Section Image", type: "img", meta: "16:9 Photography" },
                { title: "H2 Heading", type: "h2", meta: "Section Title" },
                { title: "Body Paragraphs", type: "text", meta: "SEO Copy" },
                { title: "Wrap-up & FAQ", type: "concl", meta: "Closing Summary" }
            ];
            break;
        case "heading_first":
            steps = [
                { title: "Hero 1 (Featured)", type: "hero", meta: "Landscape 1.91:1" }
            ];
            if (isDualHero) {
                steps.push({ title: "Hero 2 (Lifestyle)", type: "hero", meta: "Secondary View" });
            }
            steps.push(
                { title: "Intro Hook", type: "intro", meta: "Lead Paragraphs" },
                { title: "H2 Heading", type: "h2", meta: "Section Title" },
                { title: "Section Image", type: "img", meta: "16:9 Photography" },
                { title: "Body Paragraphs", type: "text", meta: "SEO Copy" },
                { title: "Wrap-up & FAQ", type: "concl", meta: "Closing Summary" }
            );
            break;
        case "intro_first":
            steps = [
                { title: "Intro Hook", type: "intro", meta: "Direct Opening Text" },
                { title: "Hero 1 (Featured)", type: "hero", meta: "Landscape 1.91:1" }
            ];
            if (isDualHero) {
                steps.push({ title: "Hero 2 (Lifestyle)", type: "hero", meta: "Secondary View" });
            }
            steps.push(
                { title: "Section Image", type: "img", meta: "16:9 Photography" },
                { title: "H2 Heading", type: "h2", meta: "Section Title" },
                { title: "Body Paragraphs", type: "text", meta: "SEO Copy" },
                { title: "Wrap-up & FAQ", type: "concl", meta: "Closing Summary" }
            );
            break;
        case "dual_hero_split":
            steps = [
                { title: "Hero 1 (Featured)", type: "hero", meta: "Landscape 1.91:1" },
                { title: "Intro Hook", type: "intro", meta: "Opening Text" },
                { title: "Hero 2 (Split)", type: "hero", meta: "Secondary In-line" },
                { title: "Section Image", type: "img", meta: "16:9 Photography" },
                { title: "H2 Heading", type: "h2", meta: "Section Title" },
                { title: "Body Paragraphs", type: "text", meta: "SEO Copy" },
                { title: "Wrap-up & FAQ", type: "concl", meta: "Closing Summary" }
            ];
            break;
        case "standard":
        default:
            steps = [
                { title: "Hero 1 (Featured)", type: "hero", meta: "Landscape 1.91:1" }
            ];
            if (isDualHero) {
                steps.push({ title: "Hero 2 (Lifestyle)", type: "hero", meta: "Secondary View" });
            }
            steps.push(
                { title: "Intro Hook", type: "intro", meta: "Lead Paragraphs" },
                { title: "Section Image", type: "img", meta: "16:9 Photography" },
                { title: "H2 Heading", type: "h2", meta: "Section Title" },
                { title: "Body Paragraphs", type: "text", meta: "SEO Copy" },
                { title: "Wrap-up & FAQ", type: "concl", meta: "Closing Summary" }
            );
            break;
    }

    const html = steps.map((s, idx) => `
        <div class="layout-step-pill ${s.type}" title="${s.meta}">
            ${idx + 1}. ${s.title}
        </div>
        ${idx < steps.length - 1 ? '<span class="layout-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg></span>' : ''}
    `).join("");

    containers.forEach(c => { c.innerHTML = html; });
}

// ── Collapsible Left Sidebar Controller & Mobile Drawer ───────
function openMobileSidebar() {
    const sidebar = document.getElementById("app-sidebar") || document.querySelector(".sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (sidebar) sidebar.classList.add("mobile-open");
    if (backdrop) backdrop.classList.add("active");
    document.body.style.overflow = "hidden";
}

function closeMobileSidebar() {
    const sidebar = document.getElementById("app-sidebar") || document.querySelector(".sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (sidebar) sidebar.classList.remove("mobile-open");
    if (backdrop) backdrop.classList.remove("active");
    document.body.style.overflow = "";
}

function initSidebarCollapse() {
    const sidebar = document.getElementById("app-sidebar") || document.querySelector(".sidebar");
    const btnToggle = document.getElementById("btn-toggle-sidebar");
    const btnToggleTop = document.getElementById("btn-toggle-sidebar-top");
    const btnCloseMobile = document.getElementById("btn-close-sidebar-mobile");
    const backdrop = document.getElementById("sidebar-backdrop");

    // Restore saved collapse state on desktop
    if (window.innerWidth > 768) {
        const saved = localStorage.getItem("sidebar_collapsed");
        if (saved === "true" && sidebar) {
            sidebar.classList.add("collapsed");
        }
    }

    function toggleDesktop() {
        if (!sidebar) return;
        const collapsed = sidebar.classList.toggle("collapsed");
        localStorage.setItem("sidebar_collapsed", collapsed ? "true" : "false");

        setTimeout(() => {
            window.dispatchEvent(new Event("resize"));
            renderN8nConnections();
        }, 300);
    }

    btnToggle?.addEventListener("click", toggleDesktop);

    btnToggleTop?.addEventListener("click", () => {
        if (window.innerWidth <= 768) {
            if (sidebar?.classList.contains("mobile-open")) {
                closeMobileSidebar();
            } else {
                openMobileSidebar();
            }
        } else {
            toggleDesktop();
        }
    });

    btnCloseMobile?.addEventListener("click", closeMobileSidebar);
    backdrop?.addEventListener("click", closeMobileSidebar);

    window.addEventListener("resize", () => {
        if (window.innerWidth > 768) {
            closeMobileSidebar();
        }
    });
}

// ── N8N Workflow Studio Canvas Engine (Zoom & Pan) ────────────
let n8nZoomLevel = 0.82;
let n8nPanX = 50;
let n8nPanY = 40;
let isPanning = false;
let panStartX = 0;
let panStartY = 0;
let activeDragNode = null;
let dragNodeOffsetX = 0;
let dragNodeOffsetY = 0;

const N8N_CONNECTIONS = [
    { from: "n8n-node-queue", to: "n8n-node-extract", color: "#f59e0b" },
    { from: "n8n-node-extract", to: "n8n-node-text-ai", color: "#06b6d4" },
    { from: "n8n-node-text-ai", to: "n8n-node-layout", color: "#8b5cf6" },
    { from: "n8n-node-text-ai", to: "n8n-node-visual-ai", color: "#ec4899" },
    { from: "n8n-node-visual-ai", to: "n8n-node-hero-img", color: "#6366f1" },
    { from: "n8n-node-visual-ai", to: "n8n-node-heading-img", color: "#14b8a6" },
    { from: "n8n-node-visual-ai", to: "n8n-node-pin-img", color: "#f43f5e" },
    { from: "n8n-node-layout", to: "n8n-node-publisher", color: "#3b82f6" },
    { from: "n8n-node-hero-img", to: "n8n-node-publisher", color: "#6366f1" },
    { from: "n8n-node-heading-img", to: "n8n-node-publisher", color: "#14b8a6" },
    { from: "n8n-node-pin-img", to: "n8n-node-publisher", color: "#f43f5e" }
];

function initN8nCanvas() {
    const viewport = document.getElementById("deck-n8n-view");
    const stage = document.getElementById("n8n-canvas-stage");
    if (!viewport || !stage) return;

    applyCanvasTransform();
    setTimeout(renderN8nConnections, 50);

    // Canvas Mouse Pan (Drag background to pan view)
    viewport.addEventListener("mousedown", (e) => {
        // Only pan if clicking canvas background, not inside an interactive node or chip
        if (e.target.closest(".n8n-node") || e.target.closest("button") || e.target.closest("input")) {
            return;
        }
        isPanning = true;
        panStartX = e.clientX - n8nPanX;
        panStartY = e.clientY - n8nPanY;
        viewport.classList.add("is-panning");
    });

    window.addEventListener("mousemove", (e) => {
        if (isPanning) {
            n8nPanX = e.clientX - panStartX;
            n8nPanY = e.clientY - panStartY;
            applyCanvasTransform();
        } else if (activeDragNode) {
            const stageRect = stage.getBoundingClientRect();
            const newX = (e.clientX - stageRect.left) / n8nZoomLevel - dragNodeOffsetX;
            const newY = (e.clientY - stageRect.top) / n8nZoomLevel - dragNodeOffsetY;
            activeDragNode.style.left = `${Math.max(10, Math.round(newX))}px`;
            activeDragNode.style.top = `${Math.max(10, Math.round(newY))}px`;
            renderN8nConnections();
        }
    });

    window.addEventListener("mouseup", () => {
        if (isPanning) {
            isPanning = false;
            viewport.classList.remove("is-panning");
        }
        if (activeDragNode) {
            activeDragNode.classList.remove("is-dragging");
            activeDragNode = null;
        }
    });

    // Mouse Wheel Zoom centered on cursor
    viewport.addEventListener("wheel", (e) => {
        e.preventDefault();
        const rect = viewport.getBoundingClientRect();
        const cursorX = e.clientX - rect.left;
        const cursorY = e.clientY - rect.top;

        const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
        const newZoom = Math.min(2.0, Math.max(0.35, n8nZoomLevel * zoomFactor));

        n8nPanX = cursorX - (cursorX - n8nPanX) * (newZoom / n8nZoomLevel);
        n8nPanY = cursorY - (cursorY - n8nPanY) * (newZoom / n8nZoomLevel);
        n8nZoomLevel = newZoom;

        applyCanvasTransform();
    }, { passive: false });

    // Setup node header dragging
    document.querySelectorAll(".n8n-node-header").forEach(header => {
        header.addEventListener("mousedown", (e) => {
            const node = header.closest(".n8n-node");
            if (!node) return;
            activeDragNode = node;
            node.classList.add("is-dragging");

            const stageRect = stage.getBoundingClientRect();
            const mouseStageX = (e.clientX - stageRect.left) / n8nZoomLevel;
            const mouseStageY = (e.clientY - stageRect.top) / n8nZoomLevel;

            dragNodeOffsetX = mouseStageX - node.offsetLeft;
            dragNodeOffsetY = mouseStageY - node.offsetTop;
            e.stopPropagation();
        });
    });

    window.addEventListener("resize", () => {
        renderN8nConnections();
    });
}

function applyCanvasTransform() {
    const stage = document.getElementById("n8n-canvas-stage");
    const zoomText = document.getElementById("n8n-zoom-level");
    if (stage) {
        stage.style.transform = `translate(${Math.round(n8nPanX)}px, ${Math.round(n8nPanY)}px) scale(${n8nZoomLevel})`;
    }
    if (zoomText) {
        zoomText.textContent = `${Math.round(n8nZoomLevel * 100)}%`;
    }
}

function n8nZoom(delta) {
    const viewport = document.getElementById("deck-n8n-view");
    const rect = viewport ? viewport.getBoundingClientRect() : { width: 1000, height: 700 };
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    const newZoom = Math.min(2.0, Math.max(0.35, n8nZoomLevel + delta));
    n8nPanX = centerX - (centerX - n8nPanX) * (newZoom / n8nZoomLevel);
    n8nPanY = centerY - (centerY - n8nPanY) * (newZoom / n8nZoomLevel);
    n8nZoomLevel = newZoom;

    applyCanvasTransform();
}

function n8nResetZoom() {
    n8nZoomLevel = 0.85;
    n8nPanX = 50;
    n8nPanY = 40;
    applyCanvasTransform();
    renderN8nConnections();
}

function n8nFitView() {
    const nodes = document.querySelectorAll(".n8n-node");
    const viewport = document.getElementById("deck-n8n-view");
    if (!nodes.length || !viewport) return;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(n => {
        const left = n.offsetLeft;
        const top = n.offsetTop;
        const right = left + n.offsetWidth;
        const bottom = top + n.offsetHeight;
        if (left < minX) minX = left;
        if (top < minY) minY = top;
        if (right > maxX) maxX = right;
        if (bottom > maxY) maxY = bottom;
    });

    const vRect = viewport.getBoundingClientRect();
    const padding = 70;
    const width = maxX - minX + padding * 2;
    const height = maxY - minY + padding * 2;

    const scaleX = vRect.width / width;
    const scaleY = vRect.height / height;
    n8nZoomLevel = Math.min(1.2, Math.max(0.38, Math.min(scaleX, scaleY)));

    n8nPanX = (vRect.width - (maxX - minX) * n8nZoomLevel) / 2 - minX * n8nZoomLevel;
    n8nPanY = (vRect.height - (maxY - minY) * n8nZoomLevel) / 2 - minY * n8nZoomLevel;

    applyCanvasTransform();
    renderN8nConnections();
}

function switchControlDeckView(mode) {
    const n8nView = document.getElementById("deck-n8n-view");
    if (n8nView) n8nView.style.display = "block";
    setTimeout(renderN8nConnections, 60);
}

function renderN8nConnections() {
    const wiresGroup = document.getElementById("n8n-wires-group");
    if (!wiresGroup) return;

    let svgHtml = "";

    N8N_CONNECTIONS.forEach(conn => {
        const fromNode = document.getElementById(conn.from);
        const toNode = document.getElementById(conn.to);
        if (!fromNode || !toNode) return;

        const fromPort = fromNode.querySelector(".n8n-port-out");
        const toPort = toNode.querySelector(".n8n-port-in");

        const x1 = fromNode.offsetLeft + fromNode.offsetWidth + (fromPort ? 7 : 0);
        const y1 = fromNode.offsetTop + (fromPort ? fromPort.offsetTop : (fromNode.offsetHeight / 2));

        const x2 = toNode.offsetLeft - (toPort ? 7 : 0);
        const y2 = toNode.offsetTop + (toPort ? toPort.offsetTop : (toNode.offsetHeight / 2));

        const dx = Math.max(70, Math.abs(x2 - x1) * 0.5);
        const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

        // Glow Layer
        svgHtml += `<path class="n8n-wire-glow" d="${d}" stroke="${conn.color}" />`;
        // Solid Wire
        svgHtml += `<path class="n8n-wire" d="${d}" stroke="${conn.color}" />`;
        // Animated Pulse Flow
        svgHtml += `<path class="n8n-wire-pulse" d="${d}" />`;
    });

    wiresGroup.innerHTML = svgHtml;
}

function toggleEngineFields(textEngine, imgEngine) {
    const geminiKeyGroup = document.getElementById("group-gemini-key");
    const serverUrlGroup = document.getElementById("group-server-url");
    const pollinationsDelayGroup = document.getElementById("group-pollinations-delay");
    const gflowCard = document.getElementById("card-gflow-studio");

    if (geminiKeyGroup) {
        geminiKeyGroup.style.display = (textEngine === "gemini" || imgEngine === "gemini_api") ? "flex" : "none";
    }
    if (serverUrlGroup) {
        serverUrlGroup.style.display = (imgEngine === "my_server") ? "flex" : "none";
    }
    if (pollinationsDelayGroup) {
        pollinationsDelayGroup.style.display = (imgEngine === "pollinations" || imgEngine === "agy_fallback") ? "flex" : "none";
    }
    if (gflowCard) {
        if (imgEngine === "gflow") {
            gflowCard.style.border = "1px solid #3b82f6";
            gflowCard.style.boxShadow = "0 10px 25px -5px rgba(59,130,246,0.25)";
        } else {
            gflowCard.style.border = "1px solid var(--border-color)";
            gflowCard.style.boxShadow = "none";
        }
    }
}

// ── Articles Catalog ──────────────────────────────────────────
async function loadArticles() {
    const grid = document.getElementById("articles-grid");
    if (!grid) return;

    try {
        const res = await fetch("/api/articles");
        const articles = await res.json();

        if (articles.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding:60px 20px; color:var(--text-dim);">No articles generated yet. Run the pipeline on pending URLs to see articles here!</div>`;
            return;
        }

        grid.innerHTML = articles.map(a => `
            <div class="article-card">
                <div class="article-thumb">
                    ${a.thumbnail ? `<img src="${a.thumbnail}" alt="${escapeHtml(a.title)}" />` : `<div style="display:flex;height:100%;align-items:center;justify-content:center;color:var(--text-dim);">No Thumbnail</div>`}
                    ${a.pin_thumbnail ? `<span class="pin-badge">PIN READY</span>` : ''}
                </div>
                <div class="article-body">
                    <div class="article-category">${escapeHtml(a.category)}</div>
                    <div class="article-title">${escapeHtml(a.title)}</div>
                    <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">
                        ${a.sections_count} sections &bull; ${a.created_at || 'Recent'}
                    </div>
                    <div class="article-footer">
                        <button class="btn btn-sm btn-secondary" onclick="openPreviewModal('${a.hash}')">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                            Preview HTML
                        </button>
                        ${a.has_pin_text ? `
                            <a href="${a.pin_text_url}" target="_blank" class="btn btn-sm btn-secondary" title="View Pinterest Pin Title, Description, and Hashtags">
                                📌 Pin Text
                            </a>
                        ` : ''}
                        ${a.published && a.post_url ? `
                            <a href="${a.post_url}" target="_blank" class="btn btn-sm btn-primary">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                                View Post
                            </a>
                        ` : `
                            <span style="font-size:0.75rem; color:var(--accent-amber); font-weight:600;">Draft / Local</span>
                        `}
                    </div>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error loading articles:", e);
    }
}

function openPreviewModal(urlHash) {
    const modal = document.getElementById("preview-modal");
    const frame = document.getElementById("preview-iframe");
    if (!modal || !frame) return;

    frame.src = `/preview/${urlHash}`;
    modal.classList.add("active");
}

function closePreviewModal() {
    const modal = document.getElementById("preview-modal");
    const frame = document.getElementById("preview-iframe");
    if (frame) frame.src = "about:blank";
    if (modal) modal.classList.remove("active");
}

// ── Diagnostics & Action Buttons ──────────────────────────────
function initEventListeners() {
    // Pipeline Controls
    document.getElementById("btn-start")?.addEventListener("click", async () => {
        await fetch("/api/pipeline/start", { method: "POST" });
        showToast("Pipeline started!", "success");
        loadDashboardStats();
    });

    document.getElementById("btn-stop")?.addEventListener("click", async () => {
        await fetch("/api/pipeline/stop", { method: "POST" });
        showToast("Stopping pipeline...", "warning");
        loadDashboardStats();
    });

    document.getElementById("btn-resume")?.addEventListener("click", async () => {
        await fetch("/api/pipeline/resume", { method: "POST" });
        showToast("Bypassed quota countdown!", "info");
    });

    document.getElementById("btn-publish-all")?.addEventListener("click", async () => {
        if (!confirm("Publish all finished articles to WordPress now?")) return;
        await fetch("/api/publish-all", { method: "POST" });
        showToast("Batch publish job started!", "info");
    });

    // Test Connections
    document.getElementById("btn-test-wp")?.addEventListener("click", async () => {
        const btn = document.getElementById("btn-test-wp");
        btn.textContent = "Testing...";
        btn.disabled = true;
        try {
            const baseUrl = document.getElementById("setting-base_url")?.value?.trim() || "";
            const username = document.getElementById("setting-username")?.value?.trim() || "";
            const appPassword = document.getElementById("setting-app_password")?.value?.trim() || "";

            const payload = {};
            if (baseUrl) payload.base_url = baseUrl;
            if (username) payload.username = username;
            if (appPassword) payload.app_password = appPassword;

            const res = await fetch("/api/test-wp", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json().catch(() => ({ success: false, error: "Server returned invalid response" }));
            if (data.success) {
                showToast(`Connected as: ${data.user}`, "success");
            } else {
                showToast(`Failed: ${data.error || "Connection failed"}`, "error");
            }
        } catch (e) {
            showToast("Connection test failed: " + (e.message || e), "error");
        } finally {
            btn.textContent = "Test WordPress Connection";
            btn.disabled = false;
        }
    });

    document.getElementById("btn-test-ai")?.addEventListener("click", async () => {
        const textEngine = document.getElementById("setting-text_engine")?.value || "agy";
        const geminiKey = document.getElementById("setting-gemini_api_key")?.value || "";
        const btn = document.getElementById("btn-test-ai");
        btn.textContent = "Testing...";
        btn.disabled = true;
        try {
            const res = await fetch("/api/test-ai", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text_engine: textEngine, gemini_api_key: geminiKey })
            });
            const data = await res.json();
            if (data.success) {
                showToast(data.message, "success");
            } else {
                showToast(`AI Test Failed: ${data.error}`, "error");
            }
        } catch (e) {
            showToast("AI Test Failed", "error");
        } finally {
            btn.textContent = "Test AI Connection";
            btn.disabled = false;
        }
    });

    // Settings Engine Change Watchers
    document.getElementById("setting-text_engine")?.addEventListener("change", (e) => {
        const imgEngine = document.getElementById("setting-image_engine")?.value;
        toggleEngineFields(e.target.value, imgEngine);
    });

    document.getElementById("setting-image_engine")?.addEventListener("change", (e) => {
        const textEngine = document.getElementById("setting-text_engine")?.value;
        toggleEngineFields(textEngine, e.target.value);
    });

    // CSV File Upload
    document.getElementById("csv-file-input")?.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);

        showToast("Uploading CSV...", "info");
        try {
            const res = await fetch("/api/queue/upload-csv", { method: "POST", body: formData });
            const data = await res.json();
            if (data.success) {
                showToast(`Successfully imported ${data.imported} URLs!`, "success");
                loadQueue();
                loadDashboardStats();
            } else {
                showToast(data.error || "Failed to parse CSV", "error");
            }
        } catch (err) {
            showToast("Failed to upload CSV", "error");
        }
        e.target.value = "";
    });

    // Add single URL modal/form
    document.getElementById("form-add-url")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const url = document.getElementById("input-add-url").value;
        const cat = document.getElementById("input-add-category").value;

        try {
            const res = await fetch("/api/queue", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url, category: cat })
            });
            if (res.ok) {
                showToast("URL added to queue!", "success");
                document.getElementById("input-add-url").value = "";
                document.getElementById("input-add-category").value = "";
                closeAddUrlModal();
                loadQueue();
                loadDashboardStats();
            }
        } catch (err) {
            showToast("Error adding URL", "error");
        }
    });

    // Settings Form Submit
    document.getElementById("settings-form")?.addEventListener("submit", saveSettings);
}

// ── Modals & Toast Utility ────────────────────────────────────
function openAddUrlModal() {
    document.getElementById("add-url-modal")?.classList.add("active");
}

function closeAddUrlModal() {
    document.getElementById("add-url-modal")?.classList.remove("active");
}

function showToast(msg, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.style.cssText = "position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    const accentColors = {
        success: "#10b981",
        error: "#ef4444",
        warning: "#f59e0b",
        info: "#3b82f6"
    };
    const accent = accentColors[type] || accentColors.info;

    toast.style.cssText = `background:rgba(15, 23, 42, 0.94);color:#f8fafc;padding:10px 16px;border-radius:8px;font-size:0.8125rem;font-weight:600;box-shadow:0 10px 28px rgba(0,0,0,0.45);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.12);border-left:3px solid ${accent};display:flex;align-items:center;gap:10px;transition:all 0.22s cubic-bezier(0.16,1,0.3,1);transform:translateY(16px);opacity:0;pointer-events:auto;max-width:380px;`;
    toast.innerHTML = `<span style="width:7px;height:7px;border-radius:50%;background:${accent};flex-shrink:0;"></span><span>${escapeHtml(msg)}</span>`;

    container.appendChild(toast);
    requestAnimationFrame(() => {
        toast.style.transform = "translateY(0)";
        toast.style.opacity = "1";
    });

    setTimeout(() => {
        toast.style.transform = "translateY(16px)";
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 250);
    }, 3200);
}

function escapeHtml(text) {
    if (!text) return "";
    return text.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// ─────────────────────────────────────────────────────────────
// Google Flow (gflow) Interactive Web Terminal & Management
// ─────────────────────────────────────────────────────────────
let gflowCommandHistory = [];
let gflowHistoryIndex = -1;

async function checkGflowStatus(notify = false) {
    const settingsBadge = document.getElementById("gflow-settings-badge");
    const termBadge = document.getElementById("gflow-term-badge");

    try {
        if (settingsBadge) {
            settingsBadge.className = "badge badge-warning";
            settingsBadge.textContent = "Probing...";
        }
        if (termBadge) {
            termBadge.className = "badge badge-warning";
            termBadge.textContent = "Probing...";
        }

        const res = await fetch("/api/gflow/status");
        const data = await res.json();

        updateGflowStatusBadges(data.authenticated, data.auth_message);
        if (data.version) {
            updateGflowVersionBadge(data.version, data.update_available, data.latest_version);
        }

        if (notify) {
            if (data.authenticated) {
                showToast(`Google Flow authenticated (${data.auth_message})`, "success");
            } else {
                showToast(`Google Flow not signed in: ${data.auth_message}`, "warning");
            }
        }
    } catch (e) {
        console.error("Failed to check gflow status:", e);
        if (settingsBadge) {
            settingsBadge.className = "badge badge-danger";
            settingsBadge.textContent = "Offline";
        }
    }
}

function updateGflowStatusBadges(authenticated, message) {
    const settingsBadge = document.getElementById("gflow-settings-badge");
    const termBadge = document.getElementById("gflow-term-badge");

    const badgeClass = authenticated ? "badge badge-success" : "badge badge-danger";
    const badgeText = authenticated ? "✓ Authenticated" : "✗ Not Signed In";

    if (settingsBadge) {
        settingsBadge.className = badgeClass;
        settingsBadge.textContent = badgeText;
        settingsBadge.title = message || "";
    }
    if (termBadge) {
        termBadge.className = badgeClass;
        termBadge.textContent = badgeText;
        termBadge.title = message || "";
    }
}

function updateGflowVersionBadge(version, updateAvailable = false, latestVersion = null) {
    const termVersion = document.getElementById("gflow-term-version");
    if (!termVersion) return;
    if (updateAvailable && latestVersion) {
        termVersion.innerHTML = `v${version} <span style="color:#fbbf24; cursor:pointer;" onclick="triggerGflowUpdate()" title="Update available: v${latestVersion}">⬆️ v${latestVersion}</span>`;
    } else {
        termVersion.textContent = `v${version}`;
    }
}

function openGflowTerminalModal() {
    const modal = document.getElementById("gflow-terminal-modal");
    if (modal) {
        modal.classList.add("active");
        checkGflowStatus(false);
        setTimeout(() => {
            document.getElementById("gflow-term-input")?.focus();
        }, 120);
    }
}

function closeGflowTerminalModal() {
    const modal = document.getElementById("gflow-terminal-modal");
    if (modal) {
        modal.classList.remove("active");
    }
}

function clearGflowTerminal() {
    const body = document.getElementById("gflow-term-body");
    if (body) {
        body.innerHTML = `<span style="color:#64748b;">Terminal cleared. Ready for commands.</span>\n`;
    }
}

function appendGflowTermLine(text, type = "info") {
    const body = document.getElementById("gflow-term-body");
    if (!body) return;

    const time = new Date().toLocaleTimeString();
    const typeClass = {
        success: "term-line-success",
        error: "term-line-error",
        warning: "term-line-warning",
        cmd: "term-line-cmd",
        meta: "term-line-meta",
        info: "term-line-info"
    }[type] || "term-line-info";

    const div = document.createElement("div");
    div.className = typeClass;
    div.style.marginBottom = "3px";
    div.textContent = `[${time}] ${text}`;

    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
}

async function triggerGflowAuth() {
    openGflowTerminalModal();
    appendGflowTermLine("Initiating Google Flow authentication flow...", "meta");
    appendGflowTermLine("A Chrome browser window will now open. Please complete your Google account sign-in. Once signed in, the window will close on its own.", "warning");

    try {
        const res = await fetch("/api/gflow/auth-login", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Google Flow login browser opened. Follow prompt to sign in.", "info");
        } else {
            showToast(data.error || "Failed to launch login", "error");
        }
    } catch (e) {
        showToast("Error launching auth flow", "error");
    }
}

async function triggerGflowUpdate() {
    openGflowTerminalModal();
    appendGflowTermLine("Starting gflow CLI self-upgrade...", "meta");
    try {
        const res = await fetch("/api/gflow/update", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("gflow update initiated in background", "info");
        } else {
            showToast(data.error || "Update error", "error");
        }
    } catch (e) {
        showToast("Error initiating update", "error");
    }
}

async function launchNativeGflowTerminal() {
    try {
        const res = await fetch("/api/gflow/launch-external", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Native Windows terminal launched!", "success");
            appendGflowTermLine("Spawned native Windows Command Prompt with gflow environment prepped.", "info");
        } else {
            showToast(data.error || "Could not launch native terminal", "error");
        }
    } catch (e) {
        showToast("Failed to launch native terminal", "error");
    }
}

function handleGflowInputKey(e) {
    if (e.key === "Enter") {
        e.preventDefault();
        submitGflowTermInput();
    } else if (e.key === "ArrowUp") {
        if (gflowCommandHistory.length > 0 && gflowHistoryIndex < gflowCommandHistory.length - 1) {
            gflowHistoryIndex++;
            e.target.value = gflowCommandHistory[gflowCommandHistory.length - 1 - gflowHistoryIndex];
        }
    } else if (e.key === "ArrowDown") {
        if (gflowHistoryIndex > 0) {
            gflowHistoryIndex--;
            e.target.value = gflowCommandHistory[gflowCommandHistory.length - 1 - gflowHistoryIndex];
        } else if (gflowHistoryIndex === 0) {
            gflowHistoryIndex = -1;
            e.target.value = "";
        }
    }
}

function submitGflowTermInput() {
    const input = document.getElementById("gflow-term-input");
    if (!input) return;
    const cmd = input.value.trim();
    if (!cmd) return;

    gflowCommandHistory.push(cmd);
    gflowHistoryIndex = -1;
    input.value = "";

    runGflowCliCommand(cmd);
}

async function runGflowCliCommand(cmd) {
    appendGflowTermLine(`$ gflow ${cmd}`, "cmd");
    try {
        const res = await fetch("/api/gflow/terminal/exec", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        if (!data.success) {
            appendGflowTermLine(`Error: ${data.error}`, "error");
        }
    } catch (e) {
        appendGflowTermLine(`Network error executing command: ${e}`, "error");
    }
}



// ── Google Sheets Cloud Synchronization ─────────────────────────
async function syncQueueToGoogleSheets() {
    const btn = document.getElementById("btn-sync-sheets");
    const origHtml = btn ? btn.innerHTML : "Sync Sheets";
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="display:inline-block; width:12px; height:12px; border:2px solid #4ade80; border-top-color:transparent; border-radius:50%; animation:spin 0.6s linear infinite; margin-right:4px;"></span> Syncing...`;
    }

    try {
        showToast("Synchronizing queue with Google Sheets...", "info");
        const res = await fetch("/api/queue/sync-sheets", { method: "POST" });

        const contentType = res.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            if (res.status === 404) {
                showToast("Server restart needed: Close your terminal running run.bat and restart it to load Google Sheets sync.", "error");
            } else {
                showToast(`Server returned non-JSON error (HTTP ${res.status}). Please restart run.bat.`, "error");
            }
            return;
        }

        const data = await res.json();
        if (res.ok && data.success) {
            const sheetName = data.sheet_name ? ` (${data.sheet_name})` : "";
            showToast(`Synced to Google Sheets${sheetName}: ${data.updated} updated, ${data.added} added!`, "success");
        } else {
            showToast(data.error || "Failed to sync to Google Sheets", "error");
        }
    } catch (err) {
        showToast(`Sync error: ${err.message}`, "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

async function testGoogleSheetsConnection() {
    const webhookInput = document.getElementById("setting-google_sheet_webhook_url");
    const webhookUrl = webhookInput ? webhookInput.value.trim() : "";
    if (!webhookUrl) {
        showToast("Please enter a Google Apps Script Web App URL first", "error");
        return;
    }

    const btn = document.getElementById("btn-test-sheets");
    const origText = btn ? btn.textContent : "Test Connection";
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Testing...";
    }

    try {
        const res = await fetch("/api/test-google-sheets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ webhook_url: webhookUrl })
        });

        const contentType = res.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            if (res.status === 404) {
                showToast("Server restart needed: Close the terminal running run.bat and launch it again to activate the new Google Sheets endpoint.", "error");
            } else {
                showToast(`Server returned non-JSON error (HTTP ${res.status}). Please restart the server.`, "error");
            }
            return;
        }

        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || "Connected to Google Sheet successfully!", "success");
        } else {
            showToast(data.error || "Connection test failed", "error");
        }
    } catch (err) {
        showToast(`Connection test error: ${err.message}`, "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = origText;
        }
    }
}

let cachedAppsScriptCode = "";

async function openSheetScriptModal() {
    const modal = document.getElementById("modal-sheet-script");
    const codeBlock = document.getElementById("apps-script-code-block");
    if (!modal) return;

    modal.style.display = "flex";
    modal.classList.add("active");

    if (!cachedAppsScriptCode) {
        try {
            const res = await fetch("/api/google-sheets/script-code");
            const data = await res.json();
            cachedAppsScriptCode = data.code || "";
        } catch (e) {
            console.warn("Could not fetch fresh Apps Script code, using fallback:", e);
        }
    }

    if (codeBlock && cachedAppsScriptCode) {
        codeBlock.textContent = cachedAppsScriptCode;
    }
}

function closeSheetScriptModal() {
    const modal = document.getElementById("modal-sheet-script");
    if (!modal) return;
    modal.classList.remove("active");
    modal.style.display = "none";
}

// Global window bindings for inline HTML onclick handlers
window.openSheetScriptModal = openSheetScriptModal;
window.closeSheetScriptModal = closeSheetScriptModal;
window.copyAppsScriptCode = copyAppsScriptCode;
window.syncQueueToGoogleSheets = syncQueueToGoogleSheets;
window.testGoogleSheetsConnection = testGoogleSheetsConnection;

function copyAppsScriptCode() {
    const codeBlock = document.getElementById("apps-script-code-block");
    const text = codeBlock ? codeBlock.textContent : cachedAppsScriptCode;
    if (!text) return;

    navigator.clipboard.writeText(text).then(() => {
        const copyBtn = document.getElementById("btn-copy-script");
        if (copyBtn) {
            const orig = copyBtn.innerHTML;
            copyBtn.innerHTML = `✓ Copied!`;
            setTimeout(() => { copyBtn.innerHTML = orig; }, 2000);
        }
        showToast("Apps Script code copied to clipboard!", "success");
    }).catch(() => {
        showToast("Failed to copy automatically. Please select text manually.", "warning");
    });
}

async function shutdownServer() {
    if (!confirm("Are you sure you want to stop and shut down the Auto Blog server?\n\nThis will stop any active workers and cleanly exit the application.")) {
        return;
    }

    try {
        const btn = document.getElementById("btn-shutdown-server");
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<span class="btn-text">Shutting down...</span>`;
        }
        
        await fetch("/api/server/shutdown", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });

        // Display safe shutdown confirmation screen
        document.body.innerHTML = `
            <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; background:#0f172a; color:#f8fafc; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align:center; padding:24px;">
                <div style="font-size:3.5rem; margin-bottom:1.25rem;">🛑</div>
                <h1 style="font-size:2rem; font-weight:700; margin-bottom:0.75rem; color:#f87171;">Server Shut Down Safely</h1>
                <p style="font-size:1.05rem; color:#94a3b8; max-width:480px; margin-bottom:1.75rem; line-height:1.6;">
                    The Auto Content Pipeline background server has been stopped cleanly. All database states and active logs have been flushed.
                </p>
                <div style="padding:12px 24px; background:#1e293b; border-radius:10px; border:1px solid #334155; color:#cbd5e1; font-size:0.95rem;">
                    You can now safely close this browser window.
                </div>
            </div>
        `;
    } catch (err) {
        showToast("Server shutdown signal sent.", "info");
    }
}
window.shutdownServer = shutdownServer;
