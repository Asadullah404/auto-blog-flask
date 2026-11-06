#!/usr/bin/env python3
"""
app.py — Enterprise Flask Web Control Panel & REST API
Clean, high-performance web dashboard for the Auto Content Pipeline.
Provides real-time SSE log streaming, queue management, live previews, and settings.
"""

import os
import sys

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import csv
import json
import time
import glob
import sqlite3
import hashlib
import threading
import requests
import subprocess
from datetime import datetime
from io import StringIO
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_from_directory, send_file

from pipeline_engine import (
    WORKER, BUS, get_queue_db, OUTPUT_DIR, CONFIG_FILE, DEFAULT_CONFIG
)
import wordpress_publisher
import firestore_sync
import gflow_bridge
import google_sheet_sync

if getattr(sys, "frozen", False):
    bundle_dir = getattr(sys, "_MEIPASS", Path(sys.executable).parent.resolve())
    template_folder = str(Path(bundle_dir) / "templates")
    static_folder = str(Path(bundle_dir) / "static")
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)
app.config["SECRET_KEY"] = "auto-content-pipeline-enterprise-2026"
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB max upload
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ─────────────────────────────────────────────────────────────
# PAGE ROUTES
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─────────────────────────────────────────────────────────────
# SSE REAL-TIME LOG & EVENT STREAM
# ─────────────────────────────────────────────────────────────
@app.route("/api/logs/stream")
def sse_logs():
    def event_stream():
        q = BUS.subscribe()
        try:
            while True:
                try:
                    item = q.get(timeout=25)
                    yield f"event: {item['type']}\ndata: {json.dumps(item)}\n\n"
                except Exception:
                    # Keep-alive heartbeat ping
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            BUS.unsubscribe(q)

    return Response(event_stream(), mimetype="text/event-stream")

# ─────────────────────────────────────────────────────────────
# STATS & DASHBOARD API
# ─────────────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    conn = get_queue_db()
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM queue GROUP BY status")
    counts = dict(c.fetchall())
    conn.close()

    total = sum(counts.values())
    pending = counts.get("pending", 0)
    processing = counts.get("processing", 0)
    done = counts.get("done", 0)
    failed = counts.get("failed", 0)

    # Count published articles
    published_count = 0
    latest_feature = None
    latest_pin = None

    for db_path in OUTPUT_DIR.glob("*/pipeline_state.db"):
        try:
            art_conn = sqlite3.connect(db_path)
            row = art_conn.execute("SELECT COUNT(*) FROM wp_published").fetchone()
            if row and row[0] > 0:
                published_count += 1
            art_conn.close()
        except Exception:
            pass

    # Find most recently modified rendered images
    rendered_images = list(OUTPUT_DIR.glob("*/rendered/feature_rendered.*"))
    if rendered_images:
        latest_feature_file = max(rendered_images, key=lambda p: p.stat().st_mtime)
        rel_feat = latest_feature_file.relative_to(OUTPUT_DIR)
        latest_feature = f"/media/{rel_feat.as_posix()}"

    pin_images = list(OUTPUT_DIR.glob("*/rendered/pin_rendered.*"))
    if pin_images:
        latest_pin_file = max(pin_images, key=lambda p: p.stat().st_mtime)
        rel_pin = latest_pin_file.relative_to(OUTPUT_DIR)
        latest_pin = f"/media/{rel_pin.as_posix()}"

    return jsonify({
        "total": total,
        "pending": pending + processing,
        "done": done,
        "failed": failed,
        "published": published_count,
        "running": WORKER.running,
        "active_url": WORKER.active_url,
        "latest_feature": latest_feature,
        "latest_pin": latest_pin,
    })

# ─────────────────────────────────────────────────────────────
# QUEUE MANAGEMENT API
# ─────────────────────────────────────────────────────────────
@app.route("/api/queue", methods=["GET"])
def api_get_queue():
    search = request.args.get("search", "").strip().lower()
    filter_status = request.args.get("status", "").strip().lower()

    conn = get_queue_db()
    c = conn.cursor()

    query = "SELECT id, url, category, status, post_url, created_at, updated_at FROM queue WHERE 1=1"
    params = []

    if search:
        query += " AND (url LIKE ? OR category LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if filter_status and filter_status != "all":
        query += " AND status = ?"
        params.append(filter_status)

    query += " ORDER BY id DESC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "url": r[1],
            "category": r[2] or "",
            "status": r[3],
            "post_url": r[4] or "",
            "created_at": r[5],
            "updated_at": r[6],
        })
    return jsonify(items)

@app.route("/api/queue/export", methods=["GET"])
def api_export_queue():
    search = request.args.get("search", "").strip().lower()
    filter_status = request.args.get("status", "").strip().lower()

    conn = get_queue_db()
    c = conn.cursor()

    query = "SELECT id, url, category, status, post_url, created_at, updated_at FROM queue WHERE 1=1"
    params = []

    if search:
        query += " AND (url LIKE ? OR category LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if filter_status and filter_status != "all":
        query += " AND status = ?"
        params.append(filter_status)

    query += " ORDER BY id ASC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Source URL", "Category", "Status", "Published Link", "Created At", "Updated At"])

    for r in rows:
        qid, url, cat, status, post_url, created_at, updated_at = r
        link_val = (post_url or "").strip()

        # If status is done, ensure published link is provided
        if not link_val and status.lower() == "done":
            try:
                url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
                art_db = OUTPUT_DIR / url_hash / "pipeline_state.db"
                if art_db.exists():
                    art_conn = sqlite3.connect(art_db)
                    pub_row = art_conn.execute("SELECT post_url FROM wp_published WHERE url=?", (url,)).fetchone()
                    art_conn.close()
                    if pub_row and pub_row[0]:
                        link_val = pub_row[0]
            except Exception:
                pass

        if not link_val:
            link_val = "N/A" if status.lower() != "done" else ""

        writer.writerow([qid, url, cat or "General", status, link_val, created_at or "", updated_at or ""])

    output.seek(0)
    filename = f"url_queue_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.route("/api/queue/sync-sheets", methods=["POST"])
def api_sync_google_sheets():
    import importlib
    importlib.reload(google_sheet_sync)
    cfg = WORKER.load_config()
    webhook_url = (cfg.get("google_sheet_webhook_url") or "").strip()
    if not webhook_url:
        return jsonify({
            "success": False,
            "error": "Google Sheet Webhook URL is not configured. Please set it in Settings."
        }), 400

    conn = get_queue_db()
    c = conn.cursor()
    c.execute("SELECT id, url, category, status, post_url, created_at, updated_at FROM queue ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()

    formatted_rows = []
    for r in rows:
        qid, url, cat, status, post_url, created_at, updated_at = r
        link_val = (post_url or "").strip()
        if not link_val and status.lower() == "done":
            try:
                url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
                art_db = OUTPUT_DIR / url_hash / "pipeline_state.db"
                if art_db.exists():
                    art_conn = sqlite3.connect(art_db)
                    pub_row = art_conn.execute("SELECT post_url FROM wp_published WHERE url=?", (url,)).fetchone()
                    art_conn.close()
                    if pub_row and pub_row[0]:
                        link_val = pub_row[0]
            except Exception:
                pass
        if not link_val:
            link_val = "N/A" if status.lower() != "done" else ""

        formatted_rows.append({
            "id": qid,
            "source_url": url,
            "category": cat or "General",
            "status": status,
            "published_link": link_val,
            "created_at": created_at or "",
            "updated_at": updated_at or ""
        })

    BUS.log(f"Starting Google Sheets sync for {len(formatted_rows)} queue items...", "info")
    res = google_sheet_sync.sync_queue_to_sheet(webhook_url, formatted_rows)

    if res.get("success"):
        sheet_info = f" ({res.get('sheet_name')})" if res.get("sheet_name") else ""
        msg = f"Synced to Google Sheets{sheet_info}! Updated: {res.get('updated', 0)}, Added: {res.get('added', 0)}"
        BUS.log(msg, "success")
        return jsonify(res)
    else:
        err = res.get("error", "Failed to sync to Google Sheets.")
        BUS.log(f"Google Sheets sync failed: {err}", "error")
        return jsonify(res), 500

@app.route("/api/test-google-sheets", methods=["POST"])
def api_test_google_sheets():
    import importlib
    importlib.reload(google_sheet_sync)
    data = request.get_json(silent=True) or {}
    webhook_url = (data.get("webhook_url") or "").strip()
    if not webhook_url:
        cfg = WORKER.load_config()
        webhook_url = (cfg.get("google_sheet_webhook_url") or "").strip()

    if not webhook_url:
        return jsonify({"success": False, "error": "Webhook URL cannot be empty."}), 400

    ok, msg = google_sheet_sync.test_connection(webhook_url)
    if ok:
        BUS.log(f"Google Sheets connection verified: {msg}", "success")
        return jsonify({"success": True, "message": msg})
    else:
        BUS.log(f"Google Sheets connection test failed: {msg}", "error")
        return jsonify({"success": False, "error": msg}), 400

@app.route("/api/server/shutdown", methods=["POST"])
def api_server_shutdown():
    """Gracefully stops the worker, flushes logs/DB, and terminates the server process."""
    BUS.log("Server shutdown requested from dashboard. Terminating process...", "warning")
    try:
        if WORKER.is_running:
            WORKER.stop()
    except Exception as e:
        BUS.log(f"Worker stop error: {e}", "warning")

    def delayed_exit():
        time.sleep(1.2)
        BUS.log("Process exiting cleanly. Goodbye!", "info")
        os._exit(0)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return jsonify({"success": True, "message": "Server is shutting down..."})

@app.route("/api/google-sheets/script-code", methods=["GET"])
def api_google_sheets_script():
    import importlib
    importlib.reload(google_sheet_sync)
    return jsonify({"code": google_sheet_sync.APPS_SCRIPT_CODE})

@app.route("/api/queue", methods=["POST"])
def api_add_queue():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    category = (data.get("category") or "").strip()
    status = (data.get("status") or "pending").strip().lower()

    if not url:
        return jsonify({"error": "URL cannot be empty"}), 400

    conn = get_queue_db()
    try:
        conn.execute("INSERT OR REPLACE INTO queue (url, category, status, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                     (url, category, status))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
    conn.close()

    BUS.log(f"Added URL to queue: {url}", "info")
    return jsonify({"success": True, "message": "Link queued successfully"})

@app.route("/api/queue/upload-csv", methods=["POST"])
def api_upload_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".csv") and not f.filename.endswith(".txt"):
        return jsonify({"error": "File must be a .csv or .txt file"}), 400

    content = f.read().decode("utf-8", errors="replace")
    reader = csv.reader(StringIO(content))
    conn = get_queue_db()
    count = 0

    for row in reader:
        if not row:
            continue
        first = row[0].strip()
        if not first or first.startswith("#") or first.lower() in ("url", "link", "links", "website", "source url"):
            continue
        url = first
        category = row[1].strip() if len(row) > 1 else ""
        status = row[2].strip().lower() if len(row) > 2 else "pending"
        if status not in ("done", "failed"):
            status = "pending"

        conn.execute("INSERT OR REPLACE INTO queue (url, category, status, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                     (url, category, status))
        count += 1

    conn.commit()
    conn.close()
    BUS.log(f"Imported {count} URLs from CSV upload.", "success")
    return jsonify({"success": True, "imported": count})

@app.route("/api/queue/<int:item_id>/status", methods=["POST"])
def api_update_item_status(item_id):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "pending")
    conn = get_queue_db()
    conn.execute("UPDATE queue SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, item_id))
    conn.commit()
    conn.close()
    BUS.log(f"Updated item #{item_id} status to '{new_status}'", "info")
    return jsonify({"success": True})

@app.route("/api/queue/<int:item_id>", methods=["DELETE"])
def api_delete_item(item_id):
    conn = get_queue_db()
    conn.execute("DELETE FROM queue WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/queue/clear-done", methods=["POST"])
def api_clear_done():
    conn = get_queue_db()
    conn.execute("DELETE FROM queue WHERE status='done'")
    conn.commit()
    conn.close()
    BUS.log("Cleared all completed links from queue.", "info")
    return jsonify({"success": True})

@app.route("/api/queue/reset-failed", methods=["POST"])
def api_reset_failed():
    conn = get_queue_db()
    conn.execute("UPDATE queue SET status='pending', updated_at=CURRENT_TIMESTAMP WHERE status='failed'")
    conn.commit()
    conn.close()
    BUS.log("Re-queued all failed links back to pending.", "info")
    return jsonify({"success": True})

# ─────────────────────────────────────────────────────────────
# PIPELINE CONTROL API
# ─────────────────────────────────────────────────────────────
@app.route("/api/pipeline/start", methods=["POST"])
def api_pipeline_start():
    WORKER.start()
    return jsonify({"success": True, "running": True})

@app.route("/api/pipeline/stop", methods=["POST"])
def api_pipeline_stop():
    WORKER.stop()
    return jsonify({"success": True, "running": False})

@app.route("/api/pipeline/resume", methods=["POST"])
def api_pipeline_resume():
    WORKER.resume_quota()
    return jsonify({"success": True})

@app.route("/api/publish-all", methods=["POST"])
def api_publish_all():
    cfg = WORKER.load_config()
    publisher = wordpress_publisher.WordPressPublisher(cfg, log_cb=BUS.log)

    def run_publish_job():
        count = 0
        BUS.log("Starting batch WordPress publication of all finished articles...", "info")
        for db_path in OUTPUT_DIR.glob("*/pipeline_state.db"):
            out_dir = db_path.parent
            art_conn = sqlite3.connect(db_path)
            try:
                row = art_conn.execute("SELECT url, data FROM runs WHERE phase='transform' AND status='done' ORDER BY id DESC").fetchone()
                if not row:
                    continue
                url, data = row[0], json.loads(row[1])

                # Check rendered files - only publish if rendered visuals genuinely exist on disk
                feat_cand = next(out_dir.glob("rendered/feature_rendered.*"), None)
                sec_cands = list(out_dir.glob("rendered/sec_*_rendered.*"))
                if not feat_cand or not sec_cands:
                    continue

                rendered = {
                    "feature": str(feat_cand),
                    "feature_2": str(next(out_dir.glob("rendered/feature_2_rendered.*"), "")),
                    "sections": [str(p) for p in sorted(sec_cands)],
                    "pin": str(next(out_dir.glob("rendered/pin_rendered.*"), ""))
                }
                res = publisher.publish_article(data, rendered, out_dir, url, art_conn)
                post_url = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else ""
                if post_url:
                    WORKER._save_pinterest_pin_text(data, url, out_dir, rendered=rendered, post_url=post_url)
                    WORKER._set_status(url, "done", post_url=post_url)
                count += 1
            except Exception as e:
                BUS.log(f"Publish error on {out_dir.name}: {e}", "error")
            finally:
                art_conn.close()
        BUS.log(f"Batch publish finished! Total published: {count}", "success")

    threading.Thread(target=run_publish_job, daemon=True).start()
    return jsonify({"success": True, "message": "Batch publication initiated in background."})

# ─────────────────────────────────────────────────────────────
# SETTINGS & DIAGNOSTICS API
# ─────────────────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(WORKER.load_config())

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    new_data = request.get_json(silent=True) or {}
    WORKER.save_config(new_data)
    return jsonify({"success": True, "settings": WORKER.config})

@app.route("/api/settings/quick-update", methods=["POST"])
def api_quick_update_setting():
    data = request.get_json(silent=True) or {}
    updates = {}
    if "key" in data and "value" in data:
        updates[data["key"]] = data["value"]
    elif "key" in data and len(data) == 1:
        return jsonify({"error": "Missing setting value"}), 400
    else:
        updates = data

    if not updates:
        return jsonify({"error": "Missing setting key or updates"}), 400

    WORKER.save_config(updates)
    for k, v in updates.items():
        BUS.emit("settings_updated", {"key": k, "value": v, "settings": WORKER.config})
        BUS.log(f"Quick updated setting: {k} = {v}", "info")
    return jsonify({"success": True, "updates": updates, "settings": WORKER.config})


@app.route("/api/test-wp", methods=["POST"])
def api_test_wp():
    data = request.get_json(silent=True) or {}
    cfg = WORKER.load_config()
    if isinstance(data, dict):
        for k in ["base_url", "username", "app_password"]:
            if data.get(k):
                cfg[k] = data[k]
    pub = wordpress_publisher.WordPressPublisher(cfg, log_cb=BUS.log)
    try:
        res = pub.check_connection()
        BUS.log(f"WordPress connection verified! Authenticated as: {res['name']}", "success")
        return jsonify({"success": True, "user": res["name"], "url": res["url"]})
    except Exception as e:
        BUS.log(f"WordPress connection test failed: {e}", "error")
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/test-ai", methods=["POST"])
def api_test_ai():
    data = request.get_json(silent=True) or {}
    engine = data.get("text_engine", "agy")
    gemini_key = data.get("gemini_api_key", "").strip()

    if engine == "gemini":
        if not gemini_key:
            return jsonify({"success": False, "error": "Gemini API key is required"}), 400
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            resp = requests.post(url, json={"contents": [{"parts": [{"text": "Reply with 'OK'"}]}]}, timeout=15)
            if resp.ok:
                BUS.log("Gemini API Key verified and active!", "success")
                return jsonify({"success": True, "message": "Gemini API is ready!"})
            return jsonify({"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:150]}"}), 400
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        # Test Antigravity CLI
        try:
            r = subprocess.run(["agy", "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                BUS.log(f"Antigravity CLI verified: {r.stdout.strip()}", "success")
                return jsonify({"success": True, "message": f"Antigravity CLI found: {r.stdout.strip()}"})
            return jsonify({"success": False, "error": "agy command returned an error"}), 400
        except FileNotFoundError:
            return jsonify({"success": False, "error": "'agy' command not found in system PATH"}), 400
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# GOOGLE FLOW (gflow) API & TERMINAL ENDPOINTS
# ─────────────────────────────────────────────────────────────
@app.route("/api/gflow/status", methods=["GET"])
def api_gflow_status():
    installed = gflow_bridge.is_installed()
    version = gflow_bridge.get_version() if installed else None
    cfg = WORKER.load_config()
    profile = cfg.get("gflow_profile", "")

    authenticated = False
    auth_msg = "Not checked"
    if installed:
        authenticated, auth_msg = gflow_bridge.check_auth(profile)

    update_info = {}
    if installed:
        try:
            update_info = gflow_bridge.check_update()
        except Exception:
            pass

    return jsonify({
        "installed": installed,
        "version": version,
        "authenticated": authenticated,
        "auth_message": auth_msg,
        "update_available": update_info.get("update_available", False),
        "latest_version": update_info.get("latest"),
        "profile": profile or "default"
    })

@app.route("/api/gflow/auth-login", methods=["POST"])
def api_gflow_auth_login():
    if not gflow_bridge.is_installed():
        return jsonify({"success": False, "error": "gflow CLI is not installed"}), 400

    cfg = WORKER.load_config()
    profile = cfg.get("gflow_profile", "")

    def run_auth_task():
        BUS.emit("gflow_terminal", {"text": ">>> Starting Google Flow interactive authentication...", "type": "meta"})
        BUS.emit("gflow_terminal", {"text": ">>> A browser window will open. Complete your Google sign-in. The window will close itself once done.", "type": "warning"})

        def stream_log(msg, lvl="info"):
            BUS.emit("gflow_terminal", {"text": msg, "type": lvl})
            BUS.log(f"[gflow auth] {msg}", lvl)

        ok, msg = gflow_bridge.login_interactive(profile=profile, log_cb=stream_log)
        if ok:
            BUS.emit("gflow_terminal", {"text": ">>> SUCCESS: Google Flow session verified and ready!", "type": "success"})
            BUS.emit("gflow_status_change", {"authenticated": True, "message": "Flow authenticated successfully"})
            BUS.log("Google Flow authenticated successfully!", "success")
        else:
            BUS.emit("gflow_terminal", {"text": f">>> WARNING: Auth finished with status: {msg}", "type": "error"})
            BUS.emit("gflow_status_change", {"authenticated": False, "message": msg})

    threading.Thread(target=run_auth_task, daemon=True).start()
    return jsonify({"success": True, "message": "Google Flow auth login launched. Follow the browser window."})

@app.route("/api/gflow/update", methods=["POST"])
def api_gflow_update():
    if not gflow_bridge.is_installed():
        return jsonify({"success": False, "error": "gflow CLI is not installed"}), 400

    def run_update_task():
        BUS.emit("gflow_terminal", {"text": ">>> Running gflow update via package manager...", "type": "meta"})

        def stream_log(msg, lvl="info"):
            BUS.emit("gflow_terminal", {"text": msg, "type": lvl})
            BUS.log(f"[gflow update] {msg}", lvl)

        ok, msg = gflow_bridge.run_update(log_cb=stream_log)
        if ok:
            new_v = gflow_bridge.get_version()
            BUS.emit("gflow_terminal", {"text": f">>> Update finished. Active version: {new_v}", "type": "success"})
            BUS.emit("gflow_status_change", {"version": new_v, "update_available": False})
        else:
            BUS.emit("gflow_terminal", {"text": f">>> Update notice: {msg}", "type": "warning"})

    threading.Thread(target=run_update_task, daemon=True).start()
    return jsonify({"success": True, "message": "gflow update job initiated."})

@app.route("/api/gflow/launch-external", methods=["POST"])
def api_gflow_launch_external():
    cfg = WORKER.load_config()
    profile = cfg.get("gflow_profile", "")
    ok = gflow_bridge.launch_native_terminal(profile=profile)
    if ok:
        BUS.log("Launched native Google Flow terminal window.", "info")
        return jsonify({"success": True, "message": "Native terminal window opened."})
    return jsonify({"success": False, "error": "Failed to launch native terminal window."}), 500

@app.route("/api/gflow/terminal/exec", methods=["POST"])
def api_gflow_terminal_exec():
    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "Command cannot be empty"}), 400

    def run_exec_task():
        BUS.emit("gflow_terminal", {"text": f"$ gflow {command}", "type": "cmd"})

        def stream_log(msg, lvl="info"):
            BUS.emit("gflow_terminal", {"text": msg, "type": lvl})

        code, out = gflow_bridge.execute_raw(command, log_cb=stream_log, timeout=120)
        status_type = "success" if code == 0 else "error"
        BUS.emit("gflow_terminal", {"text": f">>> [Process exited with code {code}]", "type": status_type})

    threading.Thread(target=run_exec_task, daemon=True).start()
    return jsonify({"success": True, "command": command})


# ─────────────────────────────────────────────────────────────
# ARTICLES CATALOG & MEDIA API
# ─────────────────────────────────────────────────────────────
@app.route("/api/articles")
def api_get_articles():
    articles = []
    for db_path in OUTPUT_DIR.glob("*/pipeline_state.db"):
        art_dir = db_path.parent
        conn = sqlite3.connect(db_path)
        try:
            t_row = conn.execute("SELECT url, data, ts FROM runs WHERE phase='transform' AND status='done' ORDER BY id DESC LIMIT 1").fetchone()
            if not t_row:
                continue
            url, s_data, ts = t_row[0], json.loads(t_row[1]), t_row[2]

            wp_row = conn.execute("SELECT post_id, post_url, ts FROM wp_published WHERE url=?", (url,)).fetchone()
            is_published = bool(wp_row)
            post_url = wp_row[1] if wp_row else None

            feat_img = next(art_dir.glob("rendered/feature_rendered.*"), None)
            pin_img = next(art_dir.glob("rendered/pin_rendered.*"), None)

            feat_thumb = f"/media/{feat_img.relative_to(OUTPUT_DIR).as_posix()}" if feat_img else None
            pin_thumb = f"/media/{pin_img.relative_to(OUTPUT_DIR).as_posix()}" if pin_img else None

            pin_txt_file = art_dir / "pinterest_pin.txt"
            if not pin_txt_file.exists():
                pin_txt_file = art_dir / "pinterest pin.txt"
            has_pin_text = pin_txt_file.exists()
            pin_text_url = f"/media/{pin_txt_file.relative_to(OUTPUT_DIR).as_posix()}" if has_pin_text else None

            articles.append({
                "hash": art_dir.name,
                "title": s_data.get("title", "Untitled Article"),
                "category": s_data.get("category", "General"),
                "meta_description": s_data.get("meta_description", ""),
                "url": url,
                "sections_count": len(s_data.get("sections", [])),
                "created_at": ts,
                "published": is_published,
                "post_url": post_url,
                "preview_url": f"/preview/{art_dir.name}",
                "thumbnail": feat_thumb,
                "pin_thumbnail": pin_thumb,
                "has_pin_text": has_pin_text,
                "pin_text_url": pin_text_url,
            })
        except Exception:
            pass
        finally:
            conn.close()

    articles.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify(articles)

@app.route("/preview/<url_hash>")
def preview_article(url_hash):
    html_file = OUTPUT_DIR / url_hash / "final_output.html"
    if html_file.exists():
        return send_file(html_file)
    return "Article preview not found.", 404

@app.route("/media/<path:subpath>")
def serve_media(subpath):
    return send_from_directory(OUTPUT_DIR, subpath)

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 65)
    print(">> AUTO CONTENT PIPELINE FLASK CONTROL PANEL")
    print("=" * 65)
    print("  * Web UI:      http://127.0.0.1:5000")
    print("  * Log Stream:  http://127.0.0.1:5000/api/logs/stream")
    print("=" * 65)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
