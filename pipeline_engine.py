#!/usr/bin/env python3
"""
pipeline_engine.py — Enterprise Autonomous Content Pipeline Engine
Handles Phases 1–6: Extract, Transform, Generate Images, Render, Compile, Publish.
Supports Antigravity CLI and direct Gemini API Key for text & images.
Features Granular Post Layout Orchestration, Dual Hero Images, and Independent Resolutions.
"""

import os
import sys
import re
import csv
import json
import time
import math
import queue
import hashlib
import sqlite3
import requests
import threading
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageStat
from jinja2 import Template
from bs4 import BeautifulSoup

import wordpress_publisher
import ipv4_guard
import gflow_bridge

# Initialize IPv4 loopback guard
ipv4_guard.start_ipv4_guard()

if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).parent.resolve()
else:
    ROOT_DIR = Path(__file__).parent.resolve()

OUTPUT_DIR = ROOT_DIR / "pipeline_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = ROOT_DIR / "pipeline_config.json"
QUEUE_DB_FILE = ROOT_DIR / "queue_state.db"

# ─────────────────────────────────────────────────────────────
# DEFAULT CONFIGURATION
# ─────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    # AI Engine Settings
    "text_engine": "agy",             # "agy" or "gemini"
    "gemini_api_key": "",             # Google AI Studio Gemini API Key
    "gemini_model": "gemini-2.5-flash",
    "image_engine": "agy_fallback",   # "agy_fallback", "gemini_api", "pollinations", "my_server", "agy_only", "gflow"
    "server_url": "",                 # Custom Colab / ngrok GPU URL
    "pollinations_delay": 180,        # Cooldown seconds between Pollinations calls
    "quota_wait_hours": 6,            # Quota sleep duration
    "gflow_model": "nano2",           # "nano2", "nano-pro", "image4", "nano2-lite"
    "gflow_profile": "",             # Custom profile name (blank for default)
    "gflow_headless": True,          # Headless / off-screen generation
    "gflow_auto_update": True,       # Auto-check and upgrade gflow CLI before runs

    # WordPress Publishing
    "base_url": "",
    "username": "",
    "app_password": "",
    "status": "draft",                # "draft" or "publish"
    "auto_publish": True,             # Publish immediately after generating
    "seo_plugin": "rankmath",         # "rankmath" or "none"
    "slug_mode": "competitor",        # "competitor" (exact source URL slug) or "title" (from post title)
    "alt_from": "heading",            # "heading" or "title"

    # Image Formats & Independent Resolutions
    "image_format": "webp",           # "webp" or "jpeg"
    "image_quality": 88,
    "resolution": "hd",               # Heading/Section image resolution: "sd", "hd", "fhd", "2k", or "WxH"
    "feature_resolution": "hd",       # Feature Hero image resolution (independent)
    "pin_resolution": "1000x1500",    # Pinterest pin resolution (independent)
    "prompt_include_dimensions": True, # Include breadth, height, and aspect ratio in image prompt
    
    # Granular Layout & Post Architecture Settings
    "post_layout_order": "standard",  # "standard", "dual_hero", "heading_first", "intro_first", "dual_hero_split"
    "feature_image_count": 1,         # 1 = Single Hero, 2 = Dual Feature Hero Images
    "feature_text_overlay": False,    # Overlay post title on Hero 1 image (False = clean art)
    "feature_2_text_overlay": False,  # Overlay post title on Hero 2 image (False = clean art)
    "heading_text_overlay": False,    # Overlay text on section images (False = 100% clean art)
    "heading_overlay_mode": "first_only", # When heading_text_overlay is True: "first_only" or "all"
    "pin_text_overlay": False,        # Overlay text on Pinterest Pin image (False = clean art)
    "pinterest_pin": True,            # Generate vertical Pinterest Pin image

    # Style & Master Prompts
    "image_type": "photo",            # "photo", "cinematic", "vector", "3d_render", "vintage", "studio", "watercolor", "custom"
    "image_type_custom": "",
    "master_image_prompt": "",        # Universal prompt addition
    "feature_image_master_prompt": "",
    "heading_image_master_prompt": "",
    "pin_image_master_prompt": "",
    "pin_image_type": "inherit",
    "master_text_prompt": "",         # Editorial tone / persona directive
    "article_format": "paragraphs",   # "paragraphs", "point_wise", "subheadings", "hybrid"

    # Batching & Performance
    "batch_size": 4,
    "img_inter_delay": 5,
    "img_min_stddev": 4.0,            # Reject blank/flat images
    "img_max_retries": 3,
    "agy_model": "gemini-3.8-flash-low", # Ultra-fast CLI model: gemini-3.8-flash-low, gemini-3.8-flash-medium
    "agy_effort": "low",              # Reasoning effort for agy CLI: "low", "medium", "high"
    "agy_timeout": 480,               # LLM call timeout seconds (adaptive 480s)
    "agy_img_timeout": 120,
    "sync_mode": "local",             # "local" or "firestore"
    "google_sheet_url": "",           # Google Sheet document URL
    "google_sheet_webhook_url": "",   # Google Apps Script Web App URL
}

RESOLUTION_PRESETS = {
    "sd": 854,
    "hd": 1200,
    "fhd": 1920,
    "2k": 2560,
}

_CUSTOM_RES_RE = re.compile(r"^(\d{2,5})\s*[xX]\s*(\d{2,5})$")

def resolve_dimensions(res_str: str, aspect: float) -> tuple[int, int]:
    m = _CUSTOM_RES_RE.match(str(res_str).strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    width = RESOLUTION_PRESETS.get(str(res_str).lower().strip(), 1200)
    return width, round(width * aspect)


# ─────────────────────────────────────────────────────────────
# DATABASE & QUEUE MANAGEMENT
# ─────────────────────────────────────────────────────────────
def get_queue_db():
    conn = sqlite3.connect(QUEUE_DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            category TEXT,
            status TEXT DEFAULT 'pending',
            post_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE queue ADD COLUMN post_url TEXT")
    except Exception:
        pass
    conn.commit()
    return conn

def init_article_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT,
        phase TEXT,
        status TEXT,
        data TEXT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS transform_batches (
        url TEXT,
        batch_idx INTEGER,
        sections_json TEXT,
        PRIMARY KEY (url, batch_idx)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS images_done (
        url TEXT,
        img_key TEXT PRIMARY KEY,
        dest_path TEXT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS render_done (
        url TEXT,
        sec_key TEXT PRIMARY KEY,
        out_path TEXT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────────────
# LOGGING & SERVER-SENT EVENTS BUS
# ─────────────────────────────────────────────────────────────
class EventBus:
    def __init__(self):
        self.subscribers = []
        self.lock = threading.Lock()
        self.recent_logs = []
        self.max_recent = 400

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.subscribers.append(q)
            for item in self.recent_logs[-100:]:
                try:
                    q.put_nowait(item)
                except Exception:
                    pass
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def emit(self, event_type: str, data: dict):
        item = {
            "type": event_type,
            "data": data,
            "ts": datetime.now().strftime("%H:%M:%S")
        }
        with self.lock:
            self.recent_logs.append(item)
            if len(self.recent_logs) > self.max_recent:
                self.recent_logs.pop(0)
            for q in list(self.subscribers):
                try:
                    q.put_nowait(item)
                except Exception:
                    pass

    def log(self, text: str, level: str = "info"):
        self.emit("log", {"message": text, "level": level})

BUS = EventBus()


# ─────────────────────────────────────────────────────────────
# HTML TEMPLATE (DYNAMIC POST SEQUENCE AWARE)
# ─────────────────────────────────────────────────────────────
STANDALONE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ data.title }}</title>
<meta name="description" content="{{ data.meta_description }}">
<meta name="keywords" content="{{ data.keywords }}">
<meta property="og:title" content="{{ data.title }}">
<meta property="og:description" content="{{ data.meta_description }}">
<meta property="og:image" content="{{ feature_img }}">
<meta property="og:type" content="article">
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#f8fafc;color:#0f172a;font-family:'Merriweather',serif;line-height:1.85;font-size:1.08rem}
.hero{position:relative;width:100%;max-height:600px;overflow:hidden;background:#0f172a}
.hero img{display:block;width:100%;height:auto;object-fit:cover;opacity:.88}
.hero-content{position:absolute;inset:0;background:linear-gradient(to top,rgba(15,23,42,.92) 0%,rgba(15,23,42,.2) 65%,transparent 100%);display:flex;align-items:flex-end;padding:50px 32px}
.hero-inner{max-width:900px;margin:0 auto;width:100%}
.hero-badge{display:inline-block;padding:5px 14px;background:#3b82f6;color:#fff;border-radius:9999px;font-family:'Plus Jakarta Sans',sans-serif;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:16px}
.hero h1{font-family:'Plus Jakarta Sans',sans-serif;font-size:clamp(2rem,4vw,3.2rem);line-height:1.2;font-weight:800;color:#fff}
.dual-hero-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:24px 0}
@media(max-width:768px){.dual-hero-grid{grid-template-columns:1fr;}}
.dual-hero-item{border-radius:14px;overflow:hidden;box-shadow:0 10px 25px -5px rgba(0,0,0,.15)}
.dual-hero-item img{width:100%;height:auto;display:block}
main{max-width:880px;margin:0 auto;padding:60px 24px 100px;background:#fff;border-radius:0 0 24px 24px;box-shadow:0 10px 40px -10px rgba(0,0,0,.05)}
.intro{font-size:1.22rem;line-height:1.9;color:#334155;border-left:4px solid #3b82f6;padding-left:22px;margin-bottom:50px;font-style:italic}
.sec{margin-bottom:60px}
.sec h2{font-family:'Plus Jakarta Sans',sans-serif;font-size:1.85rem;font-weight:700;color:#0f172a;margin-bottom:20px;line-height:1.3}
.img-wrap{border-radius:14px;overflow:hidden;box-shadow:0 12px 30px -5px rgba(0,0,0,.12);margin-bottom:24px}
.img-wrap img{display:block;width:100%;height:auto}
.sec p{margin-bottom:18px;color:#334155}
.sec h3{font-family:'Plus Jakarta Sans',sans-serif;font-size:1.35rem;font-weight:600;color:#1e293b;margin:28px 0 12px}
.article-list{margin:18px 0 22px 28px}
.article-list li{margin-bottom:10px;color:#334155}
.conclusion{background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);color:#fff;border-radius:20px;padding:45px 38px;margin-top:60px}
.conclusion h2{font-family:'Plus Jakarta Sans',sans-serif;font-size:1.9rem;margin-bottom:18px;color:#fff}
.conclusion p{color:#cbd5e1;margin-bottom:14px}
.conclusion p:last-child{margin-bottom:0}
</style>
</head>
<body>
{% if layout_order == 'intro_first' %}
<main style="margin-top:40px; border-radius:24px 24px 0 0;">
    <div class="intro">{{ data.intro }}</div>
</main>
{% endif %}

<div class="hero">
    <img src="{{ feature_img }}" alt="{{ data.title }}">
    <div class="hero-content">
        <div class="hero-inner">
            <span class="hero-badge">{{ data.category or 'Feature' }}</span>
            <h1>{{ data.title }}</h1>
        </div>
    </div>
</div>

<main>
    {% if layout_order == 'intro_first' %}
    <div class="intro">{{ data.intro }}</div>
    {% endif %}

    {% if feature_2_img %}
    <div class="dual-hero-item pinterest-hero-wrap" style="max-width:560px; margin:0 auto 40px; text-align:center;">
        <img src="{{ feature_2_img }}" alt="Pinterest Pin Visual Guide" style="border-radius:16px; box-shadow:0 12px 35px -5px rgba(0,0,0,0.18); width:100%; height:auto;">
    </div>
    {% endif %}

    {% if layout_order != 'intro_first' %}
    <div class="intro">{{ data.intro }}</div>
    {% endif %}

    {% for sec in data.sections %}
    <div class="sec">
        {% if layout_order == 'heading_first' %}
            <h2>{{ sec.heading }}</h2>
            {% if sec.img %}
            <div class="img-wrap">
                <img src="{{ sec.img }}" alt="{{ sec.heading }}">
            </div>
            {% endif %}
        {% else %}
            {% if sec.img %}
            <div class="img-wrap">
                <img src="{{ sec.img }}" alt="{{ sec.heading }}">
            </div>
            {% endif %}
            <h2>{{ sec.heading }}</h2>
        {% endif %}

        <div class="sec-body">
            {% for para in sec.paragraphs %}
                {% if para.startswith('### ') %}
                    <h3>{{ para[4:] }}</h3>
                {% elif para.startswith('- ') or para.startswith('* ') %}
                    <ul class="article-list"><li>{{ para[2:] }}</li></ul>
                {% else %}
                    <p>{{ para }}</p>
                {% endif %}
            {% endfor %}
        </div>
    </div>
    {% endfor %}

    {% if data.conclusion %}
    <div class="conclusion">
        <h2>{{ data.conclusion.heading or 'Conclusion' }}</h2>
        {% for para in data.conclusion.paragraphs %}
            <p>{{ para }}</p>
        {% endfor %}
    </div>
    {% endif %}
</main>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────
# PIPELINE WORKER ORCHESTRATOR
# ─────────────────────────────────────────────────────────────
class ContentPipelineWorker:
    def __init__(self):
        self.running = False
        self.stop_requested = False
        self.resume_event = threading.Event()
        self.thread = None
        self.active_url = None
        self.config = self.load_config()

    def load_config(self) -> dict:
        cfg = dict(DEFAULT_CONFIG)
        if CONFIG_FILE.exists():
            try:
                loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                cfg.update(loaded)
            except Exception as e:
                BUS.log(f"Error loading {CONFIG_FILE.name}: {e}", "warning")
        return cfg

    def save_config(self, new_cfg: dict):
        if "base_url" in new_cfg and isinstance(new_cfg["base_url"], str):
            b = new_cfg["base_url"].strip()
            if b.startswith("http://") and not any(h in b.lower() for h in ("localhost", "127.0.0.1", "::1")):
                new_cfg["base_url"] = "https://" + b[len("http://"):]
        self.config.update(new_cfg)
        CONFIG_FILE.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        BUS.log("Pipeline configuration updated.", "success")

    def start(self):
        if self.running:
            return
        self.running = True
        self.stop_requested = False
        self.resume_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="PipelineWorker")
        self.thread.start()
        BUS.emit("status", {"state": "running"})
        BUS.log("Pipeline engine started.", "success")

    def stop(self):
        if not self.running:
            return
        self.stop_requested = True
        self.resume_event.set()
        BUS.log("Pipeline stop requested — finishing current operation...", "warning")

    def resume_quota(self):
        BUS.log("Manual resume triggered — bypassing quota countdown.", "info")
        self.resume_event.set()

    def _run_loop(self):
        BUS.log("Worker loop active. Monitoring queue...", "info")
        # Auto-recover any orphaned tasks left in 'processing' back to 'pending'
        try:
            rec_conn = get_queue_db()
            recovered = rec_conn.execute("UPDATE queue SET status='pending', updated_at=CURRENT_TIMESTAMP WHERE status='processing'").rowcount
            rec_conn.commit()
            rec_conn.close()
            if recovered > 0:
                BUS.log(f"Auto-recovered {recovered} interrupted 'processing' task(s) back to 'pending'.", "info")
        except Exception as e:
            BUS.log(f"Queue recovery notice: {e}", "warning")

        while not self.stop_requested:
            self.config = self.load_config()
            url_item = self._fetch_next_pending()
            if not url_item:
                BUS.log("Queue complete — no pending URLs found. Pausing worker.", "info")
                break

            url = (url_item.get("url") or "").strip()
            category = url_item.get("category", "")

            # Guard against invalid URLs (e.g. headers or non-HTTP inputs)
            if not url.startswith(("http://", "https://")):
                BUS.log(f"Invalid URL '{url}' detected in queue (must start with http:// or https://). Marking failed.", "warning")
                self._set_status(url, "failed")
                continue

            self.active_url = url
            self._set_status(url, "processing")
            BUS.emit("active_task", {"url": url, "category": category})
            BUS.log(f"Processing URL: {url}", "info")

            try:
                self._process_single_url(url, category)
                self._set_status(url, "done")
                BUS.log(f"Successfully finished URL: {url}", "success")
            except Exception as e:
                BUS.log(f"Error processing {url}: {e}", "error")
                self._set_status(url, "failed")

            self.active_url = None
            time.sleep(2)

        self.running = False
        self.stop_requested = False
        BUS.emit("status", {"state": "idle"})
        BUS.log("Pipeline worker is now idle.", "info")

    def _fetch_next_pending(self):
        conn = get_queue_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, category FROM queue WHERE status='pending' ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"id": row[0], "url": row[1], "category": row[2]}
        return None

    def _set_status(self, url: str, status: str, post_url: str = None):
        conn = get_queue_db()
        if post_url:
            conn.execute("UPDATE queue SET status=?, post_url=?, updated_at=CURRENT_TIMESTAMP WHERE url=?", (status, post_url, url))
        else:
            conn.execute("UPDATE queue SET status=?, updated_at=CURRENT_TIMESTAMP WHERE url=?", (status, url))
        conn.commit()
        conn.close()
        BUS.emit("queue_updated", {"url": url, "status": status, "post_url": post_url})

    # ─────────────────────────────────────────────────────────
    # CORE 6-PHASE EXECUTION
    # ─────────────────────────────────────────────────────────
    def _process_single_url(self, url: str, category_override: str = ""):
        url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        article_dir = OUTPUT_DIR / url_hash
        article_dir.mkdir(parents=True, exist_ok=True)
        img_dir = article_dir / "images"
        render_dir = article_dir / "rendered"
        img_dir.mkdir(exist_ok=True)
        render_dir.mkdir(exist_ok=True)

        # Pre-check: If this article was already fully completed & published to WordPress with visuals, skip duplicate runs
        db_file = article_dir / "pipeline_state.db"
        if db_file.exists():
            try:
                chk_conn = sqlite3.connect(db_file)
                has_pub_tbl = chk_conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='wp_published'").fetchone()[0]
                pub_row = chk_conn.execute("SELECT post_id, post_url FROM wp_published WHERE url=?", (url,)).fetchone() if has_pub_tbl else None
                has_media_tbl = chk_conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='wp_media'").fetchone()[0]
                media_count = chk_conn.execute("SELECT count(*) FROM wp_media").fetchone()[0] if has_media_tbl else 0
                chk_conn.close()

                feat_rendered = list(render_dir.glob("feature_rendered.*"))
                sec_rendered = list(render_dir.glob("sec_*_rendered.*"))

                if pub_row and feat_rendered and sec_rendered and media_count > 0:
                    BUS.log(f"Article already fully published with visuals to WordPress (Post #{pub_row[0]}: {pub_row[1]}). Skipping re-generation.", "success")
                    self._set_status(url, "done", post_url=pub_row[1])
                    return
                elif pub_row:
                    BUS.log(f"Article has prior WordPress draft record (Post #{pub_row[0]}), but rendered visuals or media are incomplete (Rendered: {len(feat_rendered) + len(sec_rendered)}, Media: {media_count}). Proceeding with visual generation & WordPress post update.", "info")
            except Exception as e:
                BUS.log(f"Pre-check notice: {e}", "warning")

        db = init_article_db(article_dir / "pipeline_state.db")

        # ── Phase 1: Extract ──
        BUS.log("[Phase 1/6] Extracting article content...", "info")
        extracted = self._phase_extract(url, db)

        # ── Phase 2: Transform (SEO + GEO + AEO Rewrite) ──
        BUS.log("[Phase 2/6] Rewriting content for SEO, GEO & AEO...", "info")
        structured = self._phase_transform(extracted, url, db, category_override)

        # ── Phase 3: AI Image Generation ──
        if self.config.get("image_engine") == "gflow":
            BUS.log("[gflow] Pre-flight check: Auto-update and Session Verification...", "info")
            if self.config.get("gflow_auto_update", True):
                try:
                    up_info = gflow_bridge.check_update()
                    if up_info.get("update_available"):
                        BUS.log(f"[gflow] New version available ({up_info.get('installed')} -> {up_info.get('latest')}). Running auto-update...", "info")
                        ok, up_msg = gflow_bridge.run_update(log_cb=BUS.log)
                        if ok:
                            BUS.log(f"[gflow] Auto-update completed: {up_msg}", "success")
                        else:
                            BUS.log(f"[gflow] Auto-update notice: {up_msg}", "warning")
                    else:
                        BUS.log(f"[gflow] CLI up-to-date (v{up_info.get('installed', 'verified')}).", "info")
                except Exception as e:
                    BUS.log(f"[gflow] Update check notice: {e}", "warning")

            # Non-blocking session check: warn but proceed to generation attempts
            is_auth, auth_msg = gflow_bridge.check_auth(self.config.get("gflow_profile", ""))
            if is_auth:
                BUS.log(f"[gflow] Session Verification: {auth_msg}", "success")
            else:
                BUS.log(f"[gflow] Session probe notice: {auth_msg}. Proceeding with persistent profile cookies...", "warning")

        BUS.log("[Phase 3/6] Generating photorealistic visuals...", "info")
        raw_images = self._phase_images(structured, url, db, img_dir)

        # ── Phase 4: Graphics Compositing & Typography ──
        BUS.log("[Phase 4/6] Rendering graphics & typography...", "info")
        rendered = self._phase_render(structured, raw_images, render_dir, url, db)

        # ── Pinterest Pin Text & Copy Generation ──
        if self.config.get("pinterest_pin", True):
            self._save_pinterest_pin_text(structured, url, article_dir, raw_images, rendered)

        # ── Phase 5: Compile Standalone HTML ──
        BUS.log("[Phase 5/6] Compiling responsive HTML...", "info")
        html_path = self._phase_compile(structured, rendered, article_dir)

        # ── Phase 6: Publish to WordPress ──
        if self.config.get("auto_publish", True):
            BUS.log("[Phase 6/6] Auto-publishing to WordPress...", "info")
            publisher = wordpress_publisher.WordPressPublisher(self.config, log_cb=BUS.log)
            res = publisher.publish_article(structured, rendered, article_dir, url, db)
            post_url = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else ""
            if post_url:
                self._set_status(url, "done", post_url=post_url)
                if self.config.get("pinterest_pin", True):
                    self._save_pinterest_pin_text(structured, url, article_dir, raw_images, rendered, post_url=post_url)
        else:
            BUS.log("Auto-publish is disabled. Skipping WordPress publish.", "info")

        db.close()

    # ─────────────────────────────────────────────────────────
    # PHASE 1: EXTRACT
    # ─────────────────────────────────────────────────────────
    def _phase_extract(self, url: str, db) -> dict:
        row = db.execute("SELECT data FROM runs WHERE url=? AND phase='extract' AND status='done'", (url,)).fetchone()
        if row:
            cached_data = json.loads(row[0])
            if "headings" in cached_data and cached_data.get("headings"):
                BUS.log(f"Extracted content cached ({len(cached_data.get('headings', []))} headings).", "info")
                return cached_data

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=25)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        h1 = soup.find("h1")
        if h1 and h1.get_text():
            title = h1.get_text().strip()

        # Remove ads, navigation, scripts, footers, forms, comments, headers
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form"]):
            tag.decompose()

        # Remove known widget / related / comment / author / sharing containers
        widget_selectors = [
            "section.ff-related", "div.ff-related", "[id*='ff-related']",
            ".related-posts", "#related-posts", ".relatedposts", "#relatedposts",
            ".yarpp-related", ".jp-relatedposts", ".crp_related",
            ".wp-block-latest-posts", ".wp-block-jetpack-related-posts",
            ".sharedaddy", ".post-share", ".social-share",
            "#comments", "#respond", ".comments-area", ".comment-respond",
            ".author-box", ".post-author", ".about-author"
        ]
        for sel in widget_selectors:
            for el in soup.select(sel):
                if el.name not in ["html", "body", "main"]:
                    el.decompose()

        # Terminal / cutoff patterns: once these headings appear, the main article has ended
        cutoff_patterns = [
            r"more ideas",
            r"you (?:might|may) (?:also )?like",
            r"related (?:posts?|articles?|stories|content)",
            r"recommended (?:reading|posts?|articles?|for you)",
            r"what to read next",
            r"read next",
            r"other posts (?:you might|you may)?",
            r"recent posts",
            r"leave a (?:reply|comment)",
            r"^comments?$"
        ]

        skip_patterns = [
            r"leave a reply", r"comment", r"related post", r"save it for later",
            r"about the author", r"hi,?\s*i['’]?m", r"meet\s+(?:the\s+)?author",
            r"share this", r"subscribe", r"newsletter", r"disclosure", r"affiliate",
            r"you (?:may|might) (?:also )?like", r"pin it", r"recent posts",
            r"more ideas"
        ]

        structured_body = []
        headings_list = []

        # Find main content container to avoid sidebars (supports CSS selectors)
        main_container = soup.select_one(".entry-content, .post-content, #content, article, main") or soup.body or soup

        for elem in main_container.find_all(["h2", "h3", "h4", "p", "li"]):
            txt = elem.get_text().strip()
            if not txt:
                continue

            if elem.name in ("h2", "h3", "h4"):
                lower_t = txt.lower()
                # Stop extraction immediately if terminal / related posts heading is reached
                if any(re.search(pat, lower_t) for pat in cutoff_patterns):
                    BUS.log(f"[Extract] Reached end-of-article cutoff heading: '{txt}'. Stopping further section extraction.", "info")
                    break

                if any(re.search(pat, lower_t) for pat in skip_patterns):
                    continue
                clean_heading = re.sub(r'[\r\n\t]+', ' ', txt).strip()
                if len(clean_heading) > 2:
                    structured_body.append(f"\n## {clean_heading}")
                    headings_list.append(clean_heading)
            elif elem.name == "li":
                if len(txt) > 15:
                    structured_body.append(f"- {txt}")
            elif elem.name == "p":
                if len(txt) > 25:
                    structured_body.append(txt)

        text_body = "\n\n".join(structured_body)

        extracted = {
            "title": title or "Untitled Article",
            "body": text_body[:25000],
            "headings": headings_list,
            "headings_count": len(headings_list),
            "url": url,
        }

        db.execute("INSERT OR REPLACE INTO runs (url, phase, status, data) VALUES (?, 'extract', 'done', ?)",
                   (url, json.dumps(extracted)))
        db.commit()
        BUS.log(f"Extracted article '{extracted['title']}' with {len(headings_list)} distinct headings.", "info")
        return extracted

    # ─────────────────────────────────────────────────────────
    # PHASE 2: TRANSFORM (SEO + GEO + AEO)
    # ─────────────────────────────────────────────────────────
    def _load_skills_prompt(self) -> str:
        skills = []
        for name in ("seo_skill.md", "geo_skill.md", "aeo_skill.md"):
            p = ROOT_DIR / "Skills" / name
            if p.exists():
                skills.append(p.read_text(encoding="utf-8"))
        return "\n\n".join(skills)

    def _call_llm(self, prompt: str, timeout: int = None) -> str:
        engine = self.config.get("text_engine", "agy")
        gemini_key = self.config.get("gemini_api_key", "").strip()

        # Direct Gemini API Key
        if engine == "gemini" and gemini_key:
            model = self.config.get("gemini_model", "gemini-2.5-flash")
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192}
            }
            req_timeout = timeout or int(self.config.get("agy_timeout", 480))
            resp = requests.post(endpoint, json=payload, timeout=req_timeout)
            if not resp.ok:
                raise RuntimeError(f"Gemini API returned error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                return candidates[0]["content"]["parts"][0]["text"]
            raise RuntimeError("Gemini returned empty candidate response.")

        # Default: Google Antigravity CLI ('agy') — Extra-ordinary Fall-proof Engine
        import subprocess
        timeout_sec = timeout or int(self.config.get("agy_timeout", 480))
        effort = str(self.config.get("agy_effort", "low")).lower().strip() or "low"
        agy_model = str(self.config.get("agy_model", "gemini-3.8-flash-low")).strip() or "gemini-3.8-flash-low"

        # Isolate environment: bypass any local loopback proxy env vars for agy
        clean_env = dict(os.environ)
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            clean_env.pop(key, None)

        max_retries = 4
        last_err = ""
        current_prompt = prompt
        current_effort = effort

        # Safety guard for Windows CLI command length: streamline input if prompt exceeds 24k chars
        if len(current_prompt) > 24000:
            if "SOURCE ARTICLE TO REWRITE:" in current_prompt:
                p_head, p_body = current_prompt.split("SOURCE ARTICLE TO REWRITE:", 1)
                current_prompt = p_head + "SOURCE ARTICLE TO REWRITE:\n" + p_body[:10000]
            elif "SOURCE ARTICLE REFERENCE:" in current_prompt:
                p_head, p_body = current_prompt.split("SOURCE ARTICLE REFERENCE:", 1)
                current_prompt = p_head + "SOURCE ARTICLE REFERENCE:\n" + p_body[:10000]

        for attempt in range(1, max_retries + 1):
            if self.stop_requested:
                raise RuntimeError("Pipeline worker stopped by user request.")

            # Text prompt plan changes on successive retries
            if attempt == 2:
                # Plan change 1: Enforce lowest effort and standard flags
                current_effort = "low"
            elif attempt == 3 and len(current_prompt) > 8000:
                # Plan change 2: Streamline source content length to avoid timeouts/congestion
                BUS.log("[Antigravity] Attempt 3 plan change: Streamlining source prompt content for rapid completion...", "info")
                if "SOURCE ARTICLE TO REWRITE:" in current_prompt:
                    p_head, p_body = current_prompt.split("SOURCE ARTICLE TO REWRITE:", 1)
                    current_prompt = p_head + "SOURCE ARTICLE TO REWRITE:\n" + p_body[:7500]
                elif "SOURCE ARTICLE REFERENCE:" in current_prompt:
                    p_head, p_body = current_prompt.split("SOURCE ARTICLE REFERENCE:", 1)
                    current_prompt = p_head + "SOURCE ARTICLE REFERENCE:\n" + p_body[:7500]

            cmd = [
                "agy",
                "--model", agy_model,
                "--effort", current_effort,
                "--print-timeout", f"{timeout_sec}s",
                "--dangerously-skip-permissions",
                "--disable-slash-commands",
                "-p", current_prompt
            ]

            try:
                BUS.log(f"Calling Antigravity CLI (model={agy_model}, effort={current_effort}, timeout={timeout_sec}s, attempt {attempt}/{max_retries})...", "info")
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    encoding="utf-8",
                    errors="replace",
                    env=clean_env,
                    cwd=str(ROOT_DIR)
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout

                err_msg = (proc.stderr or proc.stdout).strip()
                last_err = f"code {proc.returncode}: {err_msg[:300]}"
                BUS.log(f"Antigravity CLI attempt {attempt} failed ({last_err})", "warning")

                # Detect Quota / Rate Limit exhaustion: enter standby sleep instead of aborting backend
                is_quota = any(kw in err_msg.lower() for kw in [
                    "quota", "rate limit", "resource_exhausted", "429", "exhausted",
                    "too many requests", "try again in", "limit reached", "rate_limit"
                ])
                if is_quota:
                    wait_hours = float(self.config.get("quota_wait_hours", 6))
                    wait_sec = int(wait_hours * 3600)
                    BUS.log(f"[Antigravity] Quota/Rate limit detected: {err_msg[:120]}. Entering standby for {wait_hours}h. (Click 'Resume' in UI anytime to retry immediately).", "warning")
                    BUS.emit("status", {"state": "quota_wait", "message": f"Antigravity quota wait ({wait_hours}h)"})
                    self.resume_event.clear()
                    resumed = self.resume_event.wait(timeout=wait_sec)
                    if resumed:
                        BUS.log("[Antigravity] Manual resume triggered! Retrying prompt immediately...", "info")
                    else:
                        BUS.log(f"[Antigravity] Standby period ({wait_hours}h) completed. Resuming prompt...", "info")
                    BUS.emit("status", {"state": "running"})
                    continue

            except subprocess.TimeoutExpired:
                last_err = f"Timed out after {timeout_sec}s"
                BUS.log(f"Antigravity CLI attempt {attempt} timed out after {timeout_sec}s", "warning")
            except Exception as e:
                last_err = str(e)
                BUS.log(f"Antigravity CLI attempt {attempt} error: {e}", "warning")

            if attempt < max_retries:
                time.sleep(attempt * 4)

        raise RuntimeError(f"Antigravity CLI failed after {max_retries} attempts with prompt plan adjustments: {last_err}")

    def _clean_json(self, raw: str) -> dict:
        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean.strip(), flags=re.MULTILINE)
        clean = clean.strip()

        # Tier 1: Direct JSON parse
        try:
            return json.loads(clean)
        except Exception:
            pass

        # Tier 2: Extract balanced outer { ... }
        start = clean.find("{")
        end = clean.rfind("}")
        candidate = clean[start:end+1] if (start != -1 and end != -1 and end > start) else clean

        # Fix trailing commas
        candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except Exception:
            pass

        # Tier 3: Fix unescaped control chars / literal newlines in strings
        def fix_newlines(match):
            return match.group(0).replace("\n", "\\n").replace("\r", "")

        repaired = re.sub(r'"([^"\\]*(\\.[^"\\]*)*)"', fix_newlines, candidate)
        repaired = re.sub(r",\s*([\]}])", r"\1", repaired)
        try:
            return json.loads(repaired)
        except Exception:
            pass

        # Tier 4: Fallback to AST literal_eval if single-quoted Python dict
        try:
            import ast
            py_obj = ast.literal_eval(repaired)
            if isinstance(py_obj, dict):
                return py_obj
        except Exception:
            pass

        # Tier 5: Regex search for any inner JSON block
        m = re.search(r"(\{.*\})", clean, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        raise ValueError(f"Could not parse valid JSON from LLM response (preview: {clean[:200]})")

    def _phase_transform(self, extracted: dict, url: str, db, category_override: str = "") -> dict:
        row = db.execute("SELECT data FROM runs WHERE url=? AND phase='transform' AND status='done'", (url,)).fetchone()
        if row:
            BUS.log("Transform rewrite cached in local SQLite.", "info")
            return json.loads(row[0])

        skills_prompt = self._load_skills_prompt()
        format_style = self.config.get("article_format", "paragraphs")
        master_text = self.config.get("master_text_prompt", "")

        format_instruction = {
            "paragraphs": "Write in standard narrative format with 2-4 comprehensive paragraphs per section.",
            "point_wise": "Write with a concise section intro followed by 4-6 scannable bullet points ('- **Key Takeaway**: Details').",
            "subheadings": "Structure each section with 2-3 H3 subheadings ('### Subheading Title') followed by concise explanations.",
            "hybrid": "Provide explanatory paragraphs followed by an actionable key takeaways bullet list."
        }.get(format_style, "Write standard comprehensive paragraphs.")

        headings = extracted.get("headings", [])
        batch_size = max(2, int(self.config.get("batch_size", 4)))

        # ── BRANCH A: BATCHED TRANSFORM FOR EXTENSIVE ARTICLES (> 5 HEADINGS) ──
        # Guarantees zero Antigravity/Gemini timeouts by generating outline first,
        # then processing manageable section batches with SQLite checkpoints.
        if len(headings) > 5:
            BUS.log(f"[Transform] Article has {len(headings)} headings. Initiating resilient batched transformation (chunk size {batch_size})...", "info")

            # 1. Blueprint Generation (Article title, SEO metadata, hooks, pin data, and conclusion)
            blueprint_prompt = f"""
{skills_prompt}

INSTRUCTIONS:
You are an elite editorial SEO and GEO (Generative Engine Optimization) writer.
Format requirement: {format_instruction}
Master tone directive: {master_text or 'Authoritative, engaging, factual, conversational.'}

Generate the overall article metadata, high-CTR headline, intro hook, image visual prompts, Pinterest pin kit, and conclusion for this article.
DO NOT generate the individual body sections array yet (they are generated in dedicated batches).

CRITICAL: Return strictly valid JSON with no markdown code blocks or preamble:
{{
  "title": "Compelling SEO Title within 60 characters",
  "meta_description": "145-155 character search meta description with focus keyword",
  "keywords": "primary keyword, secondary keyword 1, secondary keyword 2",
  "category": "{category_override or 'Technology'}",
  "intro": "Engaging 2-3 sentence introduction with inverted pyramid answer directly stated.",
  "feature_image_prompt": "Photorealistic 40-word visual description, cinematic natural lighting, 8k, no text",
  "feature_2_image_prompt": "Secondary wide-angle lifestyle / contextual action photo, complementing hero, 8k, no text",
  "pin_image_prompt": "Vertical 9:16 Pinterest visual graphic prompt, clean aesthetic, high aesthetic value",
  "pin_title": "Catchy, high-CTR Pinterest Pin Title under 100 characters with primary keyword",
  "pin_description": "Engaging 200-400 character Pinterest description with benefit hook, call to action, and 4-6 hashtags",
  "pin_alt_text": "Descriptive accessibility text for Pinterest pin graphic under 150 characters",
  "pin_boards": ["Primary Board", "Secondary Board", "Inspiration Board"],
  "conclusion": {{
    "heading": "Key Takeaways & Final Thoughts",
    "paragraphs": ["Concluding summary and forward-looking recommendation."]
  }}
}}

SOURCE ARTICLE:
Title: {extracted['title']}
Content Sample:
{extracted['body'][:8000]}
"""
            raw_bp = self._call_llm(blueprint_prompt, timeout=240)
            structured = self._clean_json(raw_bp)
            if category_override:
                structured["category"] = category_override

            # 2. Sequential Batched Section Generation with SQLite Checkpoints
            batches = [headings[i:i + batch_size] for i in range(0, len(headings), batch_size)]
            total_batches = len(batches)
            all_sections = []

            for b_idx, batch_headings in enumerate(batches):
                # Check SQLite cache first
                row = db.execute("SELECT sections_json FROM transform_batches WHERE url=? AND batch_idx=?", (url, b_idx)).fetchone()
                if row and row[0]:
                    try:
                        cached_secs = json.loads(row[0])
                        if isinstance(cached_secs, list) and len(cached_secs) == len(batch_headings):
                            all_sections.extend(cached_secs)
                            BUS.log(f"[Transform] Batch {b_idx + 1}/{total_batches} ({len(batch_headings)} sections) loaded from checkpoint.", "info")
                            continue
                    except Exception:
                        pass

                start_num = (b_idx * batch_size) + 1
                formatted_batch = "\n".join([f"  {start_num + j}. {h}" for j, h in enumerate(batch_headings)])

                batch_prompt = f"""
{skills_prompt}

INSTRUCTIONS:
You are an elite editorial SEO writer drafting specific sections for the article: "{structured.get('title', extracted['title'])}".
Format requirement: {format_instruction}
Master tone: {master_text or 'Authoritative, engaging, factual, conversational.'}

CRITICAL: Generate EXACTLY {len(batch_headings)} sections corresponding 1-to-1 in sequential order with these specific headings:
{formatted_batch}

Do NOT generate or include sections for related posts, recommended reading, other articles, author bios, or site comments. Focus ONLY on the primary article topic.

Each section MUST have:
1. "heading": enhanced heading retaining original subject + SEO keyword.
2. "paragraphs": comprehensive text matching format requirement.
3. "image_prompt": vivid photorealistic scene description for this section, 35mm lens, natural lighting, no text.
4. "image_alt": concise image alt text under 125 chars.

CRITICAL: Return strictly valid JSON containing ONLY the "sections" array:
{{
  "sections": [
    {{
      "heading": "H2 Heading with Long-Tail Keyword",
      "paragraphs": ["First paragraph...", "Second paragraph..."],
      "image_prompt": "Vivid photorealistic scene, 35mm lens, natural lighting, no text",
      "image_alt": "Alt text under 125 chars"
    }}
  ]
}}

SOURCE ARTICLE REFERENCE:
{extracted['body'][:12000]}
"""
                BUS.log(f"[Transform] Generating sections batch {b_idx + 1}/{total_batches} ({len(batch_headings)} headings)...", "info")
                raw_batch = self._call_llm(batch_prompt, timeout=240)
                batch_data = self._clean_json(raw_batch)
                batch_secs = batch_data.get("sections", [])
                if not isinstance(batch_secs, list) or not batch_secs:
                    if isinstance(batch_data, list):
                        batch_secs = batch_data
                    else:
                        raise ValueError(f"Batch {b_idx + 1} did not return valid 'sections' list.")

                # Checkpoint into SQLite
                db.execute("INSERT OR REPLACE INTO transform_batches (url, batch_idx, sections_json) VALUES (?, ?, ?)",
                           (url, b_idx, json.dumps(batch_secs)))
                db.commit()
                all_sections.extend(batch_secs)
                BUS.log(f"[Transform] Checkpointed batch {b_idx + 1}/{total_batches} ({len(batch_secs)} sections saved).", "success")

            structured["sections"] = all_sections
            db.execute("INSERT INTO runs (url, phase, status, data) VALUES (?, 'transform', 'done', ?)",
                       (url, json.dumps(structured)))
            db.commit()
            BUS.log(f"[Transform] Fully assembled article with all {len(all_sections)} sections.", "success")
            return structured

        # ── BRANCH B: STANDARD SINGLE PASS FOR SHORT ARTICLES (<= 5 HEADINGS) ──
        if headings:
            formatted_headings = "\n".join([f"  {idx+1}. {h}" for idx, h in enumerate(headings)])
            parity_directive = f"""CRITICAL 1:1 HEADING PARITY MANDATE:
The scraped source article contains EXACTLY {len(headings)} specific headings/tips:
{formatted_headings}

YOU MUST MAINTAIN STRICT 1-TO-1 CORRESPONDENCE WITH THESE {len(headings)} HEADINGS:
1. Create EXACTLY {len(headings)} items in your "sections" array — one distinct section for every single heading listed above.
2. DO NOT combine, merge, group, or omit any headings into broader topics.
3. Keep the exact logical sequence of the original points.
4. Each section heading must correspond directly to one of the original points above, enhanced with an SEO long-tail keyword.
5. Strictly exclude any "Related Posts", "More ideas you might like", or other external articles — focus exclusively on the core topic."""
        else:
            parity_directive = """CRITICAL 1:1 HEADING PRESERVATION:
Identify every single numbered item, tip, or heading in the source content.
Create a distinct section in "sections" for every item without combining them into fewer sections.
Strictly exclude any "Related Posts", "More ideas you might like", or other external articles."""

        prompt = f"""
{skills_prompt}

INSTRUCTIONS:
You are an elite editorial SEO and GEO (Generative Engine Optimization) writer.
Format requirement: {format_instruction}
Master tone directive: {master_text or 'Authoritative, engaging, factual, conversational.'}

{parity_directive}

CRITICAL: Return strictly valid JSON with no markdown code blocks or preamble:
{{
  "title": "Compelling SEO Title within 60 characters",
  "meta_description": "145-155 character search meta description with focus keyword",
  "keywords": "primary keyword, secondary keyword 1, secondary keyword 2",
  "category": "{category_override or 'Technology'}",
  "intro": "Engaging 2-3 sentence introduction with inverted pyramid answer directly stated.",
  "feature_image_prompt": "Photorealistic 40-word visual description, cinematic natural lighting, 8k, no text",
  "feature_2_image_prompt": "Secondary wide-angle lifestyle / contextual action photo, complementing hero, 8k, no text",
  "pin_image_prompt": "Vertical 9:16 Pinterest visual graphic prompt, clean aesthetic, high aesthetic value",
  "pin_title": "Catchy, high-CTR Pinterest Pin Title under 100 characters with primary keyword",
  "pin_description": "Engaging 200-400 character Pinterest description with benefit hook, call to action, and 4-6 hashtags",
  "pin_alt_text": "Descriptive accessibility text for Pinterest pin graphic under 150 characters",
  "pin_boards": ["Primary Board", "Secondary Board", "Inspiration Board"],
  "sections": [
    {{
      "heading": "H2 Heading with Long-Tail Keyword",
      "paragraphs": ["First paragraph...", "Second paragraph..."],
      "image_prompt": "Vivid photorealistic scene for this section, 35mm lens, natural lighting, no text",
      "image_alt": "Alt text under 125 chars"
    }}
  ],
  "conclusion": {{
    "heading": "Key Takeaways & Final Thoughts",
    "paragraphs": ["Concluding summary and forward-looking recommendation."]
  }}
}}

SOURCE ARTICLE TO REWRITE:
Title: {extracted['title']}
Content:
{extracted['body'][:16000]}
"""
        adaptive_timeout = max(480, len(headings) * 45)
        raw_res = self._call_llm(prompt, timeout=adaptive_timeout)
        structured = self._clean_json(raw_res)

        if category_override:
            structured["category"] = category_override

        db.execute("INSERT INTO runs (url, phase, status, data) VALUES (?, 'transform', 'done', ?)",
                   (url, json.dumps(structured)))
        db.commit()
        return structured

    # ─────────────────────────────────────────────────────────
    # PHASE 3: AI IMAGE GENERATION (DUAL HERO AWARE)
    # ─────────────────────────────────────────────────────────
    def _is_blank_image(self, img: Image.Image) -> bool:
        stat = ImageStat.Stat(img.convert("L"))
        return stat.stddev[0] < self.config.get("img_min_stddev", 4.0)

    def _generate_pollinations(self, prompt: str, dest: Path, w: int, h: int) -> bool:
        delay = self.config.get("pollinations_delay", 180)
        time.sleep(min(delay, 5))
        enc_prompt = requests.utils.quote(prompt[:300])
        url = f"https://image.pollinations.ai/prompt/{enc_prompt}?width={w}&height={h}&nologo=true&model=flux"
        resp = requests.get(url, timeout=90)
        if resp.status_code == 200 and len(resp.content) > 5000:
            dest.write_bytes(resp.content)
            with Image.open(dest) as img:
                if not self._is_blank_image(img):
                    return True
        return False

    def _generate_gemini_imagen(self, prompt: str, dest: Path) -> bool:
        key = self.config.get("gemini_api_key", "").strip()
        if not key:
            return False
        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={key}"
        payload = {
            "instances": [{"prompt": prompt[:400]}],
            "parameters": {"sampleCount": 1, "aspectRatio": "16:9"}
        }
        resp = requests.post(url, json=payload, timeout=90)
        if resp.ok:
            data = resp.json()
            predictions = data.get("predictions", [])
            if predictions and "bytesBase64Encoded" in predictions[0]:
                import base64
                img_data = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                dest.write_bytes(img_data)
                return True
        return False

    def _generate_myserver(self, prompt: str, dest: Path, w: int, h: int) -> bool:
        srv_url = self.config.get("server_url", "").strip()
        if not srv_url:
            return False
        payload = {
            "prompt": prompt,
            "width": w,
            "height": h,
            "steps": 25,
            "guidance_scale": 6.5
        }
        headers = {"ngrok-skip-browser-warning": "true"}
        resp = requests.post(srv_url, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 5000:
            dest.write_bytes(resp.content)
            return True
        return False

    def _generate_agy(self, prompt: str, dest: Path) -> bool:
        import subprocess
        cmd = ["agy", "--effort", "low", "--disable-slash-commands", "-p", f"Generate a photorealistic 8k image: {prompt}"]
        clean_env = dict(os.environ)
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            clean_env.pop(key, None)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.config.get("agy_img_timeout", 120), env=clean_env)
        return False

    def _streamline_prompt_for_gflow(self, full_prompt: str, context: dict = None) -> str:
        ctx = context or {}
        buzzwords = [
            r"ultra-high resolution", r"photorealistic", r"8k", r"35mm lens", r"depth of field",
            r"octane render", r"sharp focus", r"dramatic lighting", r"hyperrealistic",
            r"studio quality", r"cinematic lighting", r"cinematic natural lighting",
            r"architectural digest style", r"no text", r", ,", r",,"
        ]
        cleaned = full_prompt
        for bw in buzzwords:
            cleaned = re.sub(bw, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
        if len(cleaned) > 280:
            cleaned = cleaned[:280].rsplit(" ", 1)[0]
        return cleaned

    def _generate_gflow_with_plan_changes(
        self,
        full_prompt: str,
        dest: Path,
        aspect: str,
        model: str,
        profile: str,
        headless: bool,
        timeout: int,
        label: str,
        context: dict = None
    ) -> Path:
        """
        Executes Google Flow image generation with multi-stage prompt plan changes.
        STRICT POLICY: Never falls back to Pollinations AI. If all plan variations fail, raises descriptive error.
        """
        ctx = context or {}
        streamlined = self._streamline_prompt_for_gflow(full_prompt, ctx)
        alt_model = "nano-pro" if model == "nano2" else "nano2"
        subject_core = ctx.get("title") or ctx.get("heading") or label

        plans = [
            ("Plan 1: Primary Model & Configured Prompt", full_prompt, model, 0),
            ("Plan 2: Streamlined Visual Prompt (Modifiers Stripped)", streamlined, model, 2),
            ("Plan 3: Model Shift to " + alt_model, streamlined, alt_model, 3),
            ("Plan 4: Minimalist Core Directive", f"A clean, vivid high quality photograph of {subject_core}, natural daylight", model, 5),
        ]

        for plan_name, prompt_variant, model_variant, delay_sec in plans:
            if self.stop_requested:
                raise RuntimeError("Pipeline stopped by user request.")

            if delay_sec > 0:
                time.sleep(delay_sec)

            BUS.log(f"[gflow] Executing {plan_name} for {label} (model: {model_variant})...", "info")
            success = gflow_bridge.generate_image(
                prompt=prompt_variant,
                dest_path=dest,
                aspect=aspect,
                model=model_variant,
                profile=profile,
                headless=headless,
                timeout=timeout,
                log_cb=BUS.log
            )
            if success and dest.exists() and dest.stat().st_size > 1000:
                BUS.log(f"[gflow] Visual generation verified via {plan_name}: {dest.name}", "success")
                return dest
            else:
                BUS.log(f"[gflow] {plan_name} did not yield a verified image. Initiating plan change...", "warning")

        # All 4 plans exhausted — DO NOT fall back to Pollinations
        BUS.log(f"[gflow] ERROR: All 4 prompt plan variations failed for {label}. Per policy, Pollinations AI fallback is strictly DISABLED.", "error")
        raise RuntimeError(f"Google Flow failed to generate verified visual for {label} after 4 plan variations. (Pollinations fallback disabled per policy)")

    def _generate_image_router(self, prompt: str, dest: Path, w: int, h: int, label: str, context: dict = None) -> Path:
        engine = self.config.get("image_engine", "agy_fallback")
        ctx = context or {}

        lbl = (label or "").strip().lower()
        is_pin = (lbl == "pinterest pin") or (lbl == "pin") or ("pinterest" in lbl)
        is_hero = ("hero" in lbl) or ("feature" in lbl)
        is_section = ("section" in lbl) or ("sec" in lbl)

        if is_pin:
            pin_type = self.config.get("pin_image_type", "inherit")
            style = self.config.get("image_type", "photo") if pin_type == "inherit" else pin_type
        else:
            style = self.config.get("image_type", "photo")

        style_prompt = f", {style} style, photorealistic, cinematic lighting, ultra-high resolution"

        dim_prompt = ""
        if self.config.get("prompt_include_dimensions", True):
            if is_pin:
                ratio_str = "2:3 (vertical pin)" if abs((w / h) - (2 / 3)) < 0.05 else ("9:16 (vertical pin)" if abs((w / h) - (9 / 16)) < 0.1 else f"{w}:{h}")
                dim_prompt = f", {w}x{h} dimensions, {ratio_str} vertical aspect ratio, tall vertical framing, portrait composition"
            elif h > w:
                dim_prompt = f", {w}x{h} dimensions, vertical portrait framing, tall composition"
            elif w > h:
                ratio_str = "16:9" if abs((w / h) - (16 / 9)) < 0.08 else ("1.91:1" if abs((w / h) - 1.91) < 0.1 else f"{w}:{h}")
                dim_prompt = f", {w}x{h} dimensions, {ratio_str} wide aspect ratio, horizontal landscape orientation, wide angle framing"
            else:
                dim_prompt = f", {w}x{h} dimensions, 1:1 square aspect ratio"

        pin_master = self.config.get("pin_image_master_prompt", "").strip()
        hero_master = self.config.get("feature_image_master_prompt", "").strip()
        sec_master = self.config.get("heading_image_master_prompt", "").strip()
        universal_master = self.config.get("master_image_prompt", "").strip()

        if is_pin and pin_master:
            if "{{" in pin_master:
                vis_subject = prompt or ctx.get("pin_image_prompt") or ctx.get("title", "")
                headline = ctx.get("pin_title") or ctx.get("title") or "Editorial Guide"
                topic = ctx.get("title") or ctx.get("category") or "Guide"
                supp_text = (ctx.get("meta_description") or f"{ctx.get('category', 'Travel')} Checklist & Tips")[:80]
                
                full_prompt = pin_master
                full_prompt = full_prompt.replace("{{VISUAL_SUBJECT}}", vis_subject)
                full_prompt = full_prompt.replace("{{TOPIC}}", topic)
                full_prompt = full_prompt.replace("{{HEADLINE}}", headline)
                full_prompt = full_prompt.replace("{{SUPPORTING_TEXT}}", supp_text)
                full_prompt = full_prompt.replace("{{CATEGORY}}", ctx.get("category", ""))
                full_prompt = full_prompt.replace("{{TITLE}}", ctx.get("title", ""))
            else:
                full_prompt = f"{prompt}, {pin_master}{style_prompt}{dim_prompt}"
        elif is_hero and hero_master:
            full_prompt = f"{prompt}, {hero_master}{style_prompt}{dim_prompt}"
        elif is_section and sec_master:
            full_prompt = f"{prompt}, {sec_master}{style_prompt}{dim_prompt}"
        else:
            full_prompt = f"{prompt}{style_prompt}{dim_prompt}"

        if universal_master and universal_master not in full_prompt:
            full_prompt += f", {universal_master}"

        BUS.log(f"Generating image ({label} @ {w}x{h}): {full_prompt[:70]}...", "info")

        # Specific handler for Google Flow: Multi-plan retry with NO Pollinations fallback
        if engine == "gflow":
            aspect = "9:16" if h > w else "16:9"
            model = self.config.get("gflow_model", "nano2")
            profile = self.config.get("gflow_profile", "")
            headless = bool(self.config.get("gflow_headless", True))
            timeout = int(self.config.get("agy_img_timeout", 180))
            return self._generate_gflow_with_plan_changes(
                full_prompt=full_prompt,
                dest=dest,
                aspect=aspect,
                model=model,
                profile=profile,
                headless=headless,
                timeout=timeout,
                label=label,
                context=ctx
            )

        success = False
        if engine == "gemini_api":
            success = self._generate_gemini_imagen(full_prompt, dest)
        elif engine == "my_server":
            success = self._generate_myserver(full_prompt, dest, w, h)
        elif engine == "pollinations":
            success = self._generate_pollinations(full_prompt, dest, w, h)
        else: # agy_fallback or agy_only
            success = self._generate_agy(full_prompt, dest)
            if not success and engine == "agy_fallback":
                BUS.log("Antigravity Imagen unavailable — falling back to Pollinations AI...", "info")
                success = self._generate_pollinations(full_prompt, dest, w, h)

        if not success:
            if engine in ("pollinations", "agy_fallback"):
                BUS.log(f"Attempting final Pollinations AI fallback for {label}...", "info")
                success = self._generate_pollinations(full_prompt, dest, w, h)

        if not success:
            raise RuntimeError(f"Failed to produce verified image for {label}")

        BUS.log(f"Image verified & saved: {dest.name}", "success")
        return dest

    def _phase_images(self, structured: dict, url: str, db, img_dir: Path) -> dict:
        w_hero, h_hero = resolve_dimensions(self.config.get("feature_resolution", "hd"), 0.525)
        w_sec, h_sec = resolve_dimensions(self.config.get("resolution", "hd"), 9 / 16)
        w_pin, h_pin = resolve_dimensions(self.config.get("pin_resolution", "1000x1500"), 1.5)

        ext = self.config.get("image_format", "webp")
        results = {"feature": None, "feature_2": None, "sections": [], "pin": None}

        # 1. Feature Hero Image 1 (Regular Hero)
        feat_path = img_dir / f"feature.{ext}"
        if not feat_path.exists():
            prompt = structured.get("feature_image_prompt", structured.get("title", ""))
            self._generate_image_router(prompt, feat_path, w_hero, h_hero, "Hero 1", context=structured)
        results["feature"] = str(feat_path)

        # 2. Section Images (1:1 with scraped sections)
        for i, sec in enumerate(structured.get("sections", [])):
            sec_path = img_dir / f"sec_{i:02d}.{ext}"
            if not sec_path.exists():
                prompt = sec.get("image_prompt", sec.get("heading", ""))
                self._generate_image_router(prompt, sec_path, w_sec, h_sec, f"Section {i+1}", context=structured)
            results["sections"].append(str(sec_path))

        # 3. Pinterest Pin Image
        if self.config.get("pinterest_pin", True) or int(self.config.get("feature_image_count", 1)) == 2:
            pin_path = img_dir / f"pin.{ext}"
            if not pin_path.exists():
                pin_prompt = structured.get("pin_image_prompt", structured.get("title", ""))
                self._generate_image_router(pin_prompt, pin_path, w_pin, h_pin, "Pinterest Pin", context=structured)
            results["pin"] = str(pin_path)

        # 1b. Feature Hero Image 2 (2 Heroes Mode: Hero 2 is the Pinterest Pin image pasted)
        if int(self.config.get("feature_image_count", 1)) == 2:
            results["feature_2"] = results["pin"]

        return results

    # ─────────────────────────────────────────────────────────
    # PHASE 4: EDITORIAL GRAPHICS & FANCY TYPOGRAPHY RENDERING
    # ─────────────────────────────────────────────────────────
    def _get_font(self, size: int, bold: bool = True):
        font_names = (
            ['segoeuib.ttf', 'arialbd.ttf', 'trebucbd.ttf', 'calibrib.ttf']
            if bold else
            ['segoeui.ttf', 'arial.ttf', 'calibri.ttf']
        )
        for name in font_names:
            p = Path("C:/Windows/Fonts") / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def _wrap_text(self, text: str, font, max_width: int, draw: ImageDraw.Draw) -> list[str]:
        words = text.split()
        if not words:
            return []
        lines = []
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []
        if current_line:
            lines.append(" ".join(current_line))
        return lines

    def _render_fancy_image_overlay(
        self,
        src: Path,
        dest: Path,
        heading: str,
        out_w: int,
        out_h: int,
        category: str = "",
        badge_text: str = "",
        layout: str = "landscape",
        step_index: int = None
    ):
        with Image.open(src) as raw_img:
            img = raw_img.convert("RGBA").resize((out_w, out_h), Image.Resampling.LANCZOS)

            # If no heading text, save clean image directly (100% clean art)
            if not heading or not heading.strip():
                fmt = "WEBP" if self.config.get("image_format", "webp") == "webp" else "JPEG"
                img.convert("RGB").save(dest, fmt, quality=self.config.get("image_quality", 88))
                return

            heading = heading.strip()
            is_pin = (layout == "vertical")
            is_tall = (out_h > out_w)

            # 1. Non-linear curved scrim overlay for maximum photo contrast
            scrim = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
            draw_scrim = ImageDraw.Draw(scrim)
            scrim_ratio = 0.60 if is_tall else 0.52
            scrim_h = int(out_h * scrim_ratio)
            for y in range(scrim_h):
                progress = y / scrim_h
                alpha = int(230 * (progress ** 1.5))
                draw_scrim.line(
                    [(0, out_h - scrim_h + y), (out_w, out_h - scrim_h + y)],
                    fill=(10, 15, 26, alpha)
                )
            img = Image.alpha_composite(img, scrim)

            draw = ImageDraw.Draw(img)
            pad_x = int(out_w * 0.07) if is_tall else int(out_w * 0.055)
            pad_y = int(out_h * 0.07)
            max_txt_w = out_w - (pad_x * 2)

            # 2. Pill Badge
            b_text = badge_text
            if not b_text:
                if is_pin:
                    b_text = f"★ {category.upper()} ★" if category else "★ PIN GUIDE ★"
                elif step_index:
                    b_text = f"TIP {step_index:02d}"
                elif category:
                    b_text = category.upper()
                else:
                    b_text = "FEATURE"

            badge_font_size = int(out_h * 0.024) if is_tall else int(out_h * 0.032)
            badge_font = self._get_font(max(badge_font_size, 14), bold=True)
            b_box = draw.textbbox((0, 0), b_text, font=badge_font)
            bw = (b_box[2] - b_box[0]) + 28
            bh = (b_box[3] - b_box[1]) + 14

            # 3. Dynamic Headline Sizing and Auto-Wrapping
            base_font_ratio = 0.046 if is_tall else 0.065
            font_size = int(out_h * base_font_ratio)
            title_font = self._get_font(font_size, bold=True)
            lines = self._wrap_text(heading, title_font, max_txt_w, draw)
            max_lines = 4 if is_tall else 3
            if len(lines) > max_lines:
                font_size = int(font_size * 0.85)
                title_font = self._get_font(font_size, bold=True)
                lines = self._wrap_text(heading, title_font, max_txt_w, draw)

            line_height = int(font_size * 1.28)
            total_title_h = len(lines) * line_height

            gap = 14
            extra_pin_h = 35 if is_pin else 0
            total_block_h = bh + gap + total_title_h + extra_pin_h
            cur_y = out_h - pad_y - total_block_h

            # Draw Pill Badge
            badge_overlay = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
            b_draw = ImageDraw.Draw(badge_overlay)
            badge_color = (6, 182, 212, 240) if is_pin else (245, 158, 11, 240)
            badge_text_color = (255, 255, 255, 255) if is_pin else (15, 23, 42, 255)
            b_draw.rounded_rectangle([pad_x, cur_y, pad_x + bw, cur_y + bh], radius=bh // 2, fill=badge_color)
            img = Image.alpha_composite(img, badge_overlay)

            draw = ImageDraw.Draw(img)
            draw.text((pad_x + 14, cur_y + 7), b_text, font=badge_font, fill=badge_text_color)
            cur_y += bh + gap

            # Draw Headline Lines with Soft Multi-Offset Drop Shadow
            for line in lines:
                for ox, oy in [(-2, 2), (2, 2), (0, 3), (2, 0)]:
                    draw.text((pad_x + ox, cur_y + oy), line, font=title_font, fill=(0, 0, 0, 190))
                draw.text((pad_x, cur_y), line, font=title_font, fill=(255, 255, 255, 255))
                cur_y += line_height

            # For actual Pinterest pins only: add accent divider & subtle branding watermark
            if is_pin:
                cur_y += 10
                accent_bar_w = min(120, max_txt_w)
                draw.line([(pad_x, cur_y), (pad_x + accent_bar_w, cur_y)], fill=(6, 182, 212, 255), width=3)
                cur_y += 12
                brand_font = self._get_font(max(int(out_h * 0.018), 13), bold=False)
                draw.text((pad_x, cur_y), "Tap to read full guide  •  Save for later", font=brand_font, fill=(203, 213, 225, 220))

            fmt = "WEBP" if self.config.get("image_format", "webp") == "webp" else "JPEG"
            img.convert("RGB").save(dest, fmt, quality=self.config.get("image_quality", 88))

    def _phase_render(self, structured: dict, raw_images: dict, render_dir: Path, url: str, db) -> dict:
        w_hero, h_hero = resolve_dimensions(self.config.get("feature_resolution", "hd"), 0.525)
        w_sec, h_sec = resolve_dimensions(self.config.get("resolution", "hd"), 9 / 16)
        w_pin, h_pin = resolve_dimensions(self.config.get("pin_resolution", "1000x1500"), 1.5)

        ext = self.config.get("image_format", "webp")
        rendered = {"feature": None, "feature_2": None, "sections": [], "pin": None}
        cat = structured.get("category", "")

        # 1. Hero 1 (Individual Toggle: feature_text_overlay)
        hero_src = Path(raw_images["feature"])
        hero_dest = render_dir / f"feature_rendered.{ext}"
        hero_text = (structured.get("title") or "") if self.config.get("feature_text_overlay", False) else ""
        self._render_fancy_image_overlay(hero_src, hero_dest, hero_text, w_hero, h_hero, category=cat, layout="landscape")
        rendered["feature"] = str(hero_dest)

        # 2. Hero 2 (Individual Toggle: feature_2_text_overlay)
        if raw_images.get("feature_2"):
            hero2_src = Path(raw_images["feature_2"])
            hero2_dest = render_dir / f"feature_2_rendered.{ext}"
            hero2_text = (structured.get("title") or "") if self.config.get("feature_2_text_overlay", False) else ""
            self._render_fancy_image_overlay(hero2_src, hero2_dest, hero2_text, w_hero, h_hero, category=cat, layout="landscape")
            rendered["feature_2"] = str(hero2_dest)

        # 3. Section Headings (Individual Toggle: heading_text_overlay)
        # If heading_text_overlay is False -> 100% CLEAN ART ACROSS ALL SECTIONS
        # If heading_text_overlay is True -> check heading_overlay_mode ("all" or "first_only")
        heading_text_overlay = bool(self.config.get("heading_text_overlay", False))
        overlay_mode = self.config.get("heading_overlay_mode", "first_only")

        for i, s_path in enumerate(raw_images["sections"]):
            sec_src = Path(s_path)
            sec_dest = render_dir / f"sec_{i:02d}_rendered.{ext}"

            should_have_text = False
            if heading_text_overlay:
                if overlay_mode == "all":
                    should_have_text = True
                elif overlay_mode == "first_only":
                    should_have_text = (i == 0)

            heading_to_draw = structured["sections"][i].get("heading", "") if should_have_text else ""
            badge = f"TIP {i+1:02d}" if (i > 0 or "tip" in heading_to_draw.lower()) else (cat or "STEP")
            self._render_fancy_image_overlay(
                sec_src, sec_dest, heading_to_draw, w_sec, h_sec,
                category=cat, badge_text=badge, layout="landscape", step_index=i+1
            )
            rendered["sections"].append(str(sec_dest))

        # 4. Pinterest Pin (Individual Toggle: pin_text_overlay)
        if raw_images.get("pin"):
            pin_src = Path(raw_images["pin"])
            pin_dest = render_dir / f"pin_rendered.{ext}"
            pin_text = (structured.get("pin_title") or structured.get("title") or "") if self.config.get("pin_text_overlay", False) else ""
            self._render_fancy_image_overlay(pin_src, pin_dest, pin_text, w_pin, h_pin, category=cat, layout="vertical")
            rendered["pin"] = str(pin_dest)

        # 2. Hero 2 (When 2 heroes selected: Hero 2 is the Pinterest Pin image pasted)
        if int(self.config.get("feature_image_count", 1)) == 2:
            rendered["feature_2"] = rendered["pin"]

        return rendered

    def _save_pinterest_pin_text(
        self,
        structured: dict,
        url: str,
        article_dir: Path,
        raw_images: dict = None,
        rendered: dict = None,
        post_url: str = ""
    ) -> Path:
        """
        Generates and saves a complete, copy-paste-ready Pinterest Pin text file
        ('pinterest_pin.txt' and 'pinterest pin.txt') in the article output folder.
        Includes Title, Description, Destination Link, Alt Text, Recommended Boards,
        SEO Keywords, Hashtags, AI Image Prompt, and on-disk file paths.
        """
        title = (structured.get("pin_title") or structured.get("title") or "Untitled Pin").strip()
        title = re.sub(r'["\r\n]+', ' ', title).strip()[:100]

        category = (structured.get("category") or "General").strip()

        # Parse keywords
        raw_keywords = structured.get("keywords", "")
        if isinstance(raw_keywords, list):
            kws = [str(k).strip() for k in raw_keywords if str(k).strip()]
        else:
            kws = [k.strip() for k in str(raw_keywords).split(",") if k.strip()]

        # Generate hashtags
        tag_list = []
        for kw in kws[:8]:
            clean_tag = re.sub(r"[^a-zA-Z0-9]", "", kw.title())
            if clean_tag and len(clean_tag) > 2:
                tag_list.append(f"#{clean_tag}")
        cat_tag = f"#{re.sub(r'[^a-zA-Z0-9]', '', category.title())}"
        if cat_tag not in tag_list:
            tag_list.append(cat_tag)
        hashtags_str = " ".join(dict.fromkeys(tag_list))

        # Description
        raw_desc = structured.get("pin_description") or ""
        if raw_desc and len(raw_desc.strip()) > 30:
            desc = raw_desc.strip()
            if "#" not in desc and hashtags_str:
                desc = f"{desc}\n\n{hashtags_str}"
        else:
            base_desc = (structured.get("meta_description") or structured.get("intro") or "").strip()
            cta = "📌 Save this pin to your boards and tap the link to read the full guide!"
            desc = f"{base_desc}\n\n{cta}\n\n{hashtags_str}".strip()

        dest_url = (post_url or url).strip()

        alt_text = (structured.get("pin_alt_text") or f"{title} — Complete visual guide, actionable tips, and ideas for {category}.").strip()
        alt_text = re.sub(r'["\r\n]+', ' ', alt_text)[:450]

        # Recommended boards
        raw_boards = structured.get("pin_boards")
        if isinstance(raw_boards, list) and raw_boards:
            boards = [str(b).strip() for b in raw_boards if str(b).strip()]
        else:
            boards = [f"{category} Tips & Hacks", f"Best {category} Ideas", f"{category} Essentials", f"{category} Guide"]

        pin_prompt = (structured.get("pin_image_prompt") or structured.get("feature_image_prompt") or "").strip()

        # Image paths
        ext = self.config.get("image_format", "webp")
        rendered_pin = article_dir / "rendered" / f"pin_rendered.{ext}"
        raw_pin = article_dir / "images" / f"pin.{ext}"

        rendered_rel = f"rendered/{rendered_pin.name}" if rendered_pin.exists() else "Not yet generated"
        raw_rel = f"images/{raw_pin.name}" if raw_pin.exists() else "Not yet generated"

        boards_str = "\n".join([f"  • {b}" for b in boards])
        keywords_str = ", ".join(kws) if kws else "N/A"

        text_content = f"""================================================================================
                    PINTEREST PIN SPECIFICATIONS & PUBLISHING COPY
================================================================================

📌 PIN TITLE (Ideal: 40-70 chars | Max: 100 chars)
--------------------------------------------------------------------------------
{title}

📝 PIN DESCRIPTION (Hook + Core Value + Call to Action + Hashtags)
--------------------------------------------------------------------------------
{desc}

🔗 DESTINATION LINK (Article / Post URL)
--------------------------------------------------------------------------------
{dest_url}

🖼️ PIN IMAGE ALT TEXT (Accessibility & Pinterest Search SEO)
--------------------------------------------------------------------------------
{alt_text}

📁 RECOMMENDED PINTEREST BOARDS
--------------------------------------------------------------------------------
{boards_str}

🏷️ TARGET SEARCH KEYWORDS (Pinterest SEO)
--------------------------------------------------------------------------------
{keywords_str}

#️⃣ HASHTAGS (Ready to Copy & Paste)
--------------------------------------------------------------------------------
{hashtags_str}

🎨 PIN VISUAL CREATIVE PROMPT (9:16 Vertical Composition)
--------------------------------------------------------------------------------
{pin_prompt}

📂 LOCAL IMAGE FILES ON DISK
--------------------------------------------------------------------------------
- Rendered Pin Graphic: {rendered_rel} ({rendered_pin if rendered_pin.exists() else 'N/A'})
- Raw AI Generated Pin: {raw_rel} ({raw_pin if raw_pin.exists() else 'N/A'})
- Article Folder:       {article_dir.resolve()}

================================================================================
Generated automatically by Auto Content Pipeline — Pinterest Studio
================================================================================
"""
        article_dir.mkdir(parents=True, exist_ok=True)
        p1 = article_dir / "pinterest_pin.txt"
        p2 = article_dir / "pinterest pin.txt"
        p1.write_text(text_content, encoding="utf-8")
        p2.write_text(text_content, encoding="utf-8")
        BUS.log(f"Generated Pinterest Pin text file: {p1.name}", "success")
        return p1

    # ─────────────────────────────────────────────────────────
    # PHASE 5: COMPILE (STANDALONE HTML)
    # ─────────────────────────────────────────────────────────
    def _phase_compile(self, structured: dict, rendered: dict, article_dir: Path) -> Path:
        out_html = article_dir / "final_output.html"

        doc_data = dict(structured)
        for i, sec in enumerate(doc_data.get("sections", [])):
            if i < len(rendered["sections"]):
                sec["img"] = f"rendered/{Path(rendered['sections'][i]).name}"

        feat_rel = f"rendered/{Path(rendered['feature']).name}" if rendered.get("feature") else ""
        feat2_rel = f"rendered/{Path(rendered['feature_2']).name}" if rendered.get("feature_2") else ""

        layout_order = self.config.get("post_layout_order", "standard")

        tmpl = Template(STANDALONE_HTML_TEMPLATE)
        rendered_content = tmpl.render(
            data=doc_data,
            feature_img=feat_rel,
            feature_2_img=feat2_rel,
            layout_order=layout_order
        )
        out_html.write_text(rendered_content, encoding="utf-8")
        BUS.log(f"Standalone HTML generated: {out_html.name}", "success")
        return out_html


WORKER = ContentPipelineWorker()
