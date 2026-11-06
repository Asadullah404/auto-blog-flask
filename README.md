# Auto Content Pipeline — Flask Web Edition (UI PRO MAX)

An enterprise-grade, web-based automated content generation and publishing engine. It extracts articles from source URLs, transforms them using modular **SEO, GEO (Generative Engine Optimization), and AEO (Answer Engine Optimization)** copywriting instructions via **Google Antigravity (`agy` CLI)** or direct **Google Gemini API**, produces high-resolution AI visuals (Google Imagen, direct Gemini API, Pollinations AI, or custom Colab GPU), crafts dedicated **Pinterest Pin** graphics, renders graphics with custom typography, and publishes directly to **WordPress** as native Gutenberg blocks with Rank Math SEO fields.

---

## 🚀 Key Highlights & New Capabilities

1. **Modern Flask Web Control Panel ("UI PRO MAX")**:
   - Ultra-clean dark aesthetic with glassmorphism, responsive grid cards, and intuitive navigation.
   - Built with modern Tailwind-inspired CSS and high-density Inter & Plus Jakarta Sans typography.

2. **Interactive NDN Master Control Deck**:
   - Notion / Matrix-style command center showing all pipeline levers in extreme detail.
   - Click any box, card, or chip to switch settings on the fly with immediate persistence — no need to navigate to the settings page!
   - Instant live visual badge feedback and one-click toggles for WordPress Live/Draft publishing and Auto-Publish.

3. **Granular Post Layout & Sequence Architect**:
   - Choose the exact Gutenberg block and HTML structural flow:
     - `Standard`: Hero → Intro → Section Img → H2 → Paras
     - `Dual Hero`: Hero 1 → Hero 2 → Intro → Section Img → H2 → Paras
     - `Heading First`: Hero → Intro → H2 → Section Img → Paras
     - `Intro First`: Intro Hook → Hero → Section Img → H2 → Paras
     - `Split Dual Hero`: Hero 1 → Intro Hook → Hero 2 → Section Img → H2 → Paras
   - **Interactive Live Diagram**: Displays the step-by-step block sequence dynamically in real time.
   - **Selective Heading Text Overlay**: Set to `1st Heading Only` (clean rest), `All Heading Images`, or `Pure Art (No Text)`.
   - **Dual Hero Images**: Generate 1 landscape hero or 2 complementary landscape heroes (context + lifestyle).

4. **Independent Image Resolution Engine**:
   - **Feature Hero Resolution**: Preset (`sd`, `hd`, `fhd`, `2k`) or exact custom `WIDTHxHEIGHT` (1.91:1 aspect ratio).
   - **Heading / Section Resolution**: Preset (`sd`, `hd`, `fhd`, `2k`) or exact custom `WIDTHxHEIGHT` (16:9 aspect ratio).
   - **Pinterest Pin Resolution**: Vertical (`1000x1500`, `735x1102`, `1080x1920`, or custom).

5. **Dual AI Text & Rewrite Engine**:
   - **Google Antigravity (`agy` CLI)**: 100% free using your Google Antigravity quota.
   - **Direct Google Gemini API Key**: Choose between `gemini-2.5-flash` or `gemini-2.5-pro` with zero CLI dependency.

6. **Multi-Engine Visual Generator**:
   - **Antigravity Imagen (with Fallback)**: Google Imagen primary, Pollinations AI fallback.
   - **Gemini / Imagen 3 API**: Direct API Key generation.
   - **Pollinations AI Only**: Zero-credential generation with configurable anti-spam cooldown (`pollinations_delay`).
   - **Custom GPU Server**: Remote Stable Diffusion / FLUX Colab endpoint via ngrok.
   - **Anti-Grey / Anti-Blank Guarantee**: Rejects flat/grey frames via pixel standard deviation checks (`img_min_stddev`).

7. **Pinterest Pin Studio**:
   - Dedicated 2:3 vertical graphic generation (e.g. `1000x1500`).
   - Live Pinterest Pin preview alongside the feature hero image.
   - Automatically embeds hidden Pinterest pin markup in WordPress post bodies for browser extension pinning.

8. **Live Real-Time SSE Log Streaming**:
   - Uses Server-Sent Events (`/api/logs/stream`) to pipe terminal-grade console logs directly into the web UI in real time with syntax coloring and auto-scroll.

9. **Interactive Queue Management**:
   - Add single URLs or upload bulk CSV files via drag & drop.
   - Real-time search and category filtering.
   - **Instant Status Dropdown**: Change any link's status from `Done` or `Failed` back to `Pending` with 1 click to re-queue it!

10. **WordPress Publishing & Rank Math SEO**:
   - Uploads media with alt tags.
   - Assembles clean Gutenberg blocks (`wp:paragraph`, `wp:heading`, `wp:list`, `wp:image`).
   - Automatically injects Rank Math SEO title, meta description, and focus keywords via companion `rank-math-rest-meta.php`.
   - Hostinger AI theme 500 error bypass (separate featured media linkage).

11. **Transparent IPv4 Loopback Proxy (`ipv4_guard.py`)**:
   - Runs an in-process proxy on `127.0.0.1` that forces all Google Cloud connections over IPv4, completely eliminating ISP IPv6 route drops and TLS handshake resets.

---

## 🏃 Quick Start (One-Click)

1. Double-click **`run.bat`** (or run `python run.py` in your terminal).
2. The launcher will automatically check dependencies, start the background IPv4 proxy, and open the web dashboard in your browser:
   ```
   http://127.0.0.1:5000
   ```
3. In the **Settings** tab:
   - Configure your WordPress connection (`Site URL`, `Username`, `Application Password`).
   - Choose your Text LLM (`Antigravity CLI` or `Gemini API Key`).
   - Choose your Image Engine mode.
   - Click **Save Settings**.
4. In the **URL Queue** tab, click **Add URL** (or upload your `Links.csv`).
5. Click **▶ Start Pipeline** in the top navigation bar to begin automated 24/7 processing!

---

## 📁 File Structure

```
auto-blog-flask/
├── app.py                     # Flask web app, REST API & SSE streaming server
├── pipeline_engine.py         # Autonomous 6-phase content pipeline engine
├── wordpress_publisher.py     # WordPress REST API publisher & Gutenberg block builder
├── firestore_sync.py          # Firebase Auth & Cloud Firestore sync client
├── ipv4_guard.py              # Transparent local IPv4 loopback proxy
├── rank-math-rest-meta.php    # WordPress must-use plugin for Rank Math REST meta
├── requirements.txt           # Python package requirements
├── run.py                     # Dependency checker & browser launcher
├── run.bat                    # One-click Windows runner
├── Skills/                    # Prompt skills
│   ├── seo_skill.md           # SEO + GEO copywriting instructions
│   ├── geo_skill.md           # Generative Engine Optimization rules
│   └── aeo_skill.md           # Answer Engine Optimization rules
├── static/
│   ├── css/
│   │   └── style.css          # UI PRO MAX stylesheet (Dark theme, glassmorphism)
│   └── js/
│       └── app.js             # Reactive frontend SPA controller
└── templates/
    └── index.html             # Single-page dashboard template
```
