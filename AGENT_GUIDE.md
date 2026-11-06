# 📖 AGENT_GUIDE.md — Master Architecture & Operations Manual

> **NOTICE FOR AI AGENTS:** Read this document first when entering or modifying the `auto-blog-flask` repository. It provides the end-to-end architectural blueprints, system rules, strict fallback policies, database schemas, and critical execution guidelines.

---

## 1. System Overview

**`auto-blog-flask`** ("UI PRO MAX") is an autonomous content generation, visual design, and WordPress publishing pipeline powered by Flask, Google Antigravity (`agy` CLI), Google Flow (`gflow` CLI), and optional Google Gemini API.

### Core End-to-End Pipeline Workflow:
```
[Source URL] ──► [Phase 1: Extract] ──► [Phase 2: Transform] ──► [Phase 3: AI Images]
                      (BS4/LXML)             (agy / Gemini)           (gflow t2i)
                                                                           │
[WordPress Post] ◄── [Phase 6: Publish] ◄── [Phase 5: Compile] ◄── [Phase 4: Render]
 (Gutenberg/RankMath)    (REST API)            (Jinja2 HTML)          (PIL Typography)
```

1. **Phase 1: Extract:** Scrapes target articles, strips ads/sidebars, deconstructs related-post and recommendation widgets (e.g. `section.ff-related`, `.yarpp-related`, `More ideas you might like`), and extracts clean structural headings without trailing external articles.
2. **Phase 2: Transform:** Feeds source text + copywriting skills (`Skills/*.md`) into Antigravity CLI or Gemini API, enforcing 1:1 heading parity and outputting strictly structured JSON.
3. **Phase 3: AI Image Generation:** Generates landscape hero/section visuals and vertical 2:3 Pinterest Pin graphics via Google Flow (`gflow`).
4. **Phase 4: Graphics & Canvas Compositing:** Uses PIL to composite gradient contrast scrims, category badges, drop-shadow headlines, and Pinterest branding.
5. **Phase 5: Compile:** Assembles responsive standalone HTML previews.
6. **Phase 6: WordPress Publishing:** Uploads media, constructs native Gutenberg blocks, embeds hidden Pinterest pins, and saves Rank Math SEO metadata.

---

## 2. File-by-File Repository Map

```
auto-blog-flask/
├── AGENT_GUIDE.md               # THIS MASTER MANUAL (Read first)
├── app.py                       # Flask server, REST API & real-time SSE log streamer
├── pipeline_engine.py           # 6-phase autonomous worker & image routing orchestrator
├── wordpress_publisher.py       # WordPress REST API publisher & Gutenberg block builder
├── gflow_bridge.py              # Google Flow CLI (gflow) driver, auth prober & process runner
├── ipv4_guard.py                # In-process loopback proxy (127.0.0.1) forcing pure IPv4
├── firestore_sync.py            # Firebase Auth & Cloud Firestore sync client (optional)
├── run.py                       # Launcher: checks dependencies, boots proxy, opens browser
├── run.bat                      # Windows one-click batch launcher
├── fix_ipv4_and_network.bat     # Windows admin network optimizer (RFC 6724 IPv4 priority)
├── pipeline_config.json         # Master settings file (AI engines, WP credentials, layout)
├── queue_state.db               # Primary SQLite database for URL queue management
├── requirements.txt             # Python dependencies
├── rank-math-rest-meta.php      # WordPress MU-plugin exposing Rank Math fields to REST API
├── Skills/                      # Modular prompt instructions
│   ├── seo_skill.md             # SEO copywriting v3.0 rules
│   ├── geo_skill.md             # Generative Engine Optimization rules (AI Overviews)
│   └── aeo_skill.md             # Answer Engine Optimization rules (Featured Snippets)
├── static/                      # Frontend static assets
│   ├── css/style.css            # Dark glassmorphism UI styling (UI PRO MAX)
│   └── js/app.js                # Reactive SPA controller & n8n-style visual deck
├── templates/
│   └── index.html               # Single-page dashboard template (7 tabbed views)
└── pipeline_output/             # Output directory partitioned by URL SHA1 hashes (12 chars)
    └── <url_sha1_hash>/
        ├── images/              # Raw AI-generated visuals (feature, sec_XX, pin)
        ├── rendered/            # Composited graphics with overlays and typography
        ├── pipeline_state.db    # Per-article SQLite database (runs, media, WP status)
        ├── pinterest_pin.txt    # Copy-paste publishing sheet for Pinterest Studio
        └── final_output.html    # Standalone compiled responsive HTML preview
```

---

## 3. Strict Architectural Rules & Hard Policies

### 🛡️ Policy A: "Never Exit Backend" — Antigravity Fall-Proofing
The Python/Flask backend and worker thread must **NEVER crash, abort, or terminate unexpectedly**.
1. **Quota & Rate Limit Standby:**
   - In `pipeline_engine.py`, `_call_llm()` monitors `agy` output for quota signals: `quota`, `rate limit`, `resource_exhausted`, `429`, `too many requests`.
   - When detected, it **does not mark the URL as failed** and **does not abort the process**. It logs a notice, updates UI status to `quota_wait`, and enters a standby sleep (`quota_wait_hours`, default 6h).
   - If the user clicks **Resume** in the UI (`BUS.resume_quota()`) or the timer expires, it wakes up and retries the prompt automatically.
2. **Resilient Batched Transform & Adaptive Timeout (Zero-Timeout Guarantee):**
   - For articles with > 5 headings (e.g. 15-32 headings), the engine automatically switches to **Batched Transformation**:
     * Step 1: Rapid Article Blueprint generation (~10-15s) for headline, SEO metadata, Pinterest pin data, and conclusion.
     * Step 2: Sequential section batches (chunk size 4) executed with individual timeouts (240s) and immediate checkpointing into 	ransform_batches SQLite table. Interrupted tasks resume from the last saved batch.
     * Step 3: Fast assembly of all batch sections into the final structured article.
   - Default gy_timeout is extended to 480s, passing --model gemini-3.8-flash-low and matching --print-timeout.
3. **Text Prompt Plan Changes on Retry:**
   - **Plan 1:** Standard editorial prompt with configured reasoning effort.
   - **Plan 2 (Effort Adjustment):** Enforces `--effort low` and strips local proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`) so `agy` talks directly to Google APIs.
   - **Plan 3 (Source Streamlining):** If the scraped article is too large, it trims the source text to 7,500 characters to prevent token overflow and timeouts.
4. **5-Tier Robust JSON Repair (_clean_json):
   - Strips markdown fences (````json ... ````).
   - Extracts balanced outer `{` and `}`.
   - Removes trailing commas before `}` and `]`.
   - Fixes literal unescaped newlines inside string values.
   - Falls back to Python AST `literal_eval` for single-quoted structures.
5. **Worker Resilience:**
   - **Zombie Task Recovery:** On worker start, any links left in `processing` status (from an earlier crash or restart) are automatically restored to `pending`.
   - **Duplicate Work Prevention:** Before running, `_process_single_url()` checks if the URL is already recorded in `wp_published`. If found, it marks the queue row `done` immediately.
   - **Input Validation:** Non-HTTP strings (e.g. accidental CSV headers like `"link"`) are safely skipped.

---

### 🎨 Policy B: Google Flow (`gflow`) Strict "No-Pollinations" Policy
When `image_engine` is set to `"gflow"`:
1. **POLLINATIONS AI IS STRICTLY FORBIDDEN:**
   - Under no circumstances may `_generate_image_router()` fall back to Pollinations AI when `gflow` is active.
2. **Multi-Stage Plan Changes for Visuals (`_generate_gflow_with_plan_changes`):**
   If `gflow` fails on the initial attempt, it must execute progressive plan changes:
   - **Plan 1 (Primary Model & Configured Prompt):** Runs the full prompt with the configured model (e.g. `nano2`).
   - **Plan 2 (Streamlined Visual Prompt):** Uses `_streamline_prompt_for_gflow()` to remove technical camera specifications and clutter buzzwords (`cinematic lighting, ultra-high resolution, photorealistic, 8k, 35mm lens, octane render, depth of field`) that trigger Flow safety filters or parser stalls. Adds a 2-second anti-bot jitter.
   - **Plan 3 (Model Shift):** Switches model alias (e.g. shifts `nano2` to `nano-pro`, or `nano-pro` to `nano2`) with a 3-second jitter.
   - **Plan 4 (Minimalist Essential Subject Directive):** Generates a concise, high-contrast declarative prompt (`"A clean, vivid high quality photograph of {subject}, natural daylight"`) with a 5-second cooldown.
   - **Policy Failure:** If all 4 plans fail, raise a descriptive error without touching Pollinations AI.
3. **Session Cookie Preservation:**
   - `gflow_bridge.py` uses persistent browser cookies located at:
     `%LOCALAPPDATA%\ffroliva\gflow-cli\profile_muhammad-asadullah-oficial`
   - Even if Google's legacy status probe endpoint returns status 410, `check_auth()` recognizes persistent profile cookies and allows generation to run off-screen.

---

## 4. WordPress & Publishing Details

* **Authentication:** Uses WordPress Application Passwords via HTTP Basic Auth.
* **REST API Endpoint:** `<base_url>/wp-json/wp/v2/posts` and `<base_url>/wp-json/wp/v2/media`.
* **Gutenberg Comments:**
  - Paragraphs: `<!-- wp:paragraph --><p>...</p><!-- /wp:paragraph -->`
  - Headings: `<!-- wp:heading {"level":2} --><h2>...</h2><!-- /wp:heading -->`
  - Images: `<!-- wp:image {"id":123,"sizeSlug":"large"} --><figure>...</figure><!-- /wp:image -->`
  - Lists: `<!-- wp:list --><ul><li>...</li></ul><!-- /wp:list -->`
* **Hostinger AI Theme Workaround:**
  - In `wordpress_publisher.py`, creating a post with `featured_media` directly in the payload causes HTTP 500 errors on some Hostinger installations.
  - The publisher creates the post *first*, then attaches the featured media in a secondary `POST /wp-json/wp/v2/posts/{id}` call.
* **Rank Math SEO Integration:**
  - Companion plugin `rank-math-rest-meta.php` must exist in `wp-content/mu-plugins/`.
  - Exposes `rank_math_title`, `rank_math_description`, and `rank_math_focus_keyword` to the REST API.
* **Pinterest Pin Embed:**
  - Generates a hidden image in the post HTML:
    `<img src="..." alt="..." class="pinterest-pin-image" loading="lazy" data-pin-description="..." style="display:none">`
  - Allows Pinterest browser extensions to discover the dedicated 2:3 vertical graphic without cluttering the main post body.

---

## 5. Database Schemas

### Master Queue Database: `queue_state.db`
```sql
CREATE TABLE queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    category TEXT,
    status TEXT DEFAULT 'pending', -- 'pending', 'processing', 'done', 'failed'
    post_url TEXT,                 -- Live published WordPress link (when done)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Queue Export Feature
* **Endpoint:** `GET /api/queue/export?search=...&status=...`
* **Output:** Downloadable CSV file with columns: `ID`, `Source URL`, `Category`, `Status`, `Published Link`, `Created At`, `Updated At`.
* **Behavior:** When an article is `done`, the exact live published WordPress post URL is exported. If pending or failed, exports `N/A`.
* **UI Integration:** The URL Queue toolbar features an **Export CSV** button that dynamically respects active search queries and status filters. Live links are also directly clickable in the UI queue table.

### Per-Article State Database: `pipeline_output/<sha1_hash>/pipeline_state.db`
* `runs`: Stores phase execution status (`extract`, `transform`) and serialized JSON data payloads.
* `wp_published`: Tracks WordPress publishing idempotency (`url`, `post_id`, `post_url`, `ts`).
* `wp_media`: Caches uploaded image paths and remote media IDs to prevent duplicate uploads.
* `images_done` & `render_done`: Progress trackers for raw and composited graphics.

---

## 6. Networking & The IPv4 Guard (`ipv4_guard.py`)

* Many residential and commercial ISPs experience packet drop, TLS handshake resets, and routing degradation over IPv6 when contacting Google APIs.
* `ipv4_guard.py` creates an in-process loopback proxy on `127.0.0.1:<dynamic_port>` using `socket.AF_INET`.
* Automatically sets `HTTP_PROXY`, `HTTPS_PROXY`, and configures `GODEBUG=netdns=cgo` to prevent upstream DNS leaks.
* Antigravity CLI (`agy`) runs with a sanitized environment (`clean_env` without proxy variables) to ensure direct internal communication.

---

## 7. Operational Instructions (How to Run & Control)

### Starting the Server:
Double-click `run.bat` or run from terminal:
```powershell
python run.py
```
* Dashboard URL: `http://127.0.0.1:5000`
* Real-time SSE Log Stream: `http://127.0.0.1:5000/api/logs/stream`

### Quick Commands for Future Agents:
```powershell
# Check Python environment & dependencies
python -m py_compile app.py pipeline_engine.py wordpress_publisher.py gflow_bridge.py

# Verify Antigravity CLI
agy --version
agy --effort low --disable-slash-commands -p "Reply with PING"

# Check Google Flow CLI & Authentication
gflow --version
python -c "import gflow_bridge; print(gflow_bridge.check_auth())"

# Inspect active queue status breakdown
python -c "import sqlite3; c=sqlite3.connect('queue_state.db'); print(c.execute('SELECT status, count(*) FROM queue GROUP BY status').fetchall())"
```

---
*Created for autonomous AI agent onboarding. Keep this document updated whenever altering core pipeline architecture.*
