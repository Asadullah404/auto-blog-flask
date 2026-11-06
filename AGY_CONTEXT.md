# AGY Context & Project Knowledge Base

> **Note for Future AGY Instances**:  
> Read this file first when prompted with *"see this file"* or when beginning a new session on this repository. This document contains the full architecture, configurations, completed tasks, troubleshooting guides, and exact implementation details of the **Auto Content Pipeline (Flask Edition)**.

---

## 1. Project Overview & Architecture

- **Project Name**: Auto Content Pipeline (Flask Edition)
- **Local Root Path**: `C:\Users\onlyg\Desktop\auto-blog-flask`
- **Application URL**: `http://127.0.0.1:5000`
- **Launcher**: `run.bat` $\to$ executes `run.py` $\to$ launches Flask `app.py` + transparent loopback guard (`ipv4_guard.py`).
- **Core Technology Stack**:
  - **Backend**: Python 3.14 / Flask (threaded, debug=False)
  - **Database**: SQLite3 (`queue_state.db` for global URL queue, `pipeline_output/<url_hash>/pipeline_state.db` for individual article workflows)
  - **Scraping**: `newspaper4k`, `beautifulsoup4`, `requests`
  - **Text Generation**: Antigravity CLI agent (`agy`) / Gemini API fallback
  - **Image Generation**: GFlow (`nano2`) headless image generator
  - **CMS Publishing**: WordPress REST API (`/wp-json/wp/v2/posts`) with Application Passwords and RankMath SEO integration
  - **External Cloud Sync**: Google Sheets via Google Apps Script Web App (Webhook gateway)

---

## 2. Live WordPress Configuration

- **Website URL**: `https://zivibloom.com`
- **Username / Email**: `muhammad.asadullah.suhail@gmail.com`
- **Application Password**: Stored in `pipeline_config.json` (`app_password`)
- **Default Post Status**: `draft` (with `auto_publish: true`)
- **SEO Plugin**: RankMath (`rankmath`)
- **Published URLs Pattern**: `https://zivibloom.com/<slug>/`

---

## 3. Major Features & Work Done

### A. Exact Competitor Slug Setting (`slug_mode`)
- **Requirement**: Allow user to choose between using the exact URL slug from the competitor source link vs generating a slug from the article headline.
- **Implemented Modes**:
  1. `"competitor"` (Default): Extracts slug directly from source URL path (e.g., `https://competitor.com/blog/red-roses-care/` $\to$ `red-roses-care`).
  2. `"title"`: Generates URL slug from the AI-generated headline.
- **Code Locations**:
  - `pipeline_config.json`: `"slug_mode": "competitor"`
  - `pipeline_engine.py`: `run_step_slug()` checks `cfg.get("slug_mode")`
  - `wordpress_publisher.py`: `publish_article()` respects `competitor` slug
  - `templates/index.html`: Added dropdown in Publishing Settings card
  - `static/js/app.js`: Settings load/save bindings

### B. Revert Issues Patch & Queue DB Alignment (43 Posts)
- **Requirement**: Revert 43 WordPress posts from `REVERT__ISSUES/Icssues.csv` so their WordPress post slugs match competitor slugs, mark them `done`, and align the active queue exclusively to these 43 posts.
- **Actions Taken**:
  1. `REVERT__ISSUES/patch_revert_slugs.py` executed: Updated all WordPress slugs via REST API.
  2. `queue_state.db` cleared of obsolete links and repopulated with exclusively the 43 items from `Icssues.csv` (IDs 1 to 43, status `done`, live post URLs verified).
  3. Pre-change queue backup stored at `BACKUP/queue_state_pre_user_request.db`.
  4. Per-article databases created in `pipeline_output/<url_hash>/pipeline_state.db` with populated `wp_published` tables.

### C. Google Sheets Cloud Sync (`Links_Sync`)
- **Requirement**: Add a **"Sync Sheets"** button in the Queue toolbar that exports/updates queue items into a Google Spreadsheet in the exact same 7-column schema as CSV export, with **zero duplicates**, specifically writing to a tab named **`Links_Sync`**.
- **Architecture**:
  - Flask backend makes a POST request to a Google Apps Script Web App deployed on the user's sheet.
  - Apps Script handles sheet operations atomically with `LockService` and `SpreadsheetApp`.
  - Target Tab: Looks for **`Links_Sync`** tab; if missing, automatically creates it (`insertSheet("Links_Sync")`).
  - Zero Duplicates: Uses **Column B (`Source URL`)** as the unique key. If URL exists, updates row in-place; if new, appends to bottom.

---

## 4. Google Sheets Integration Technical Details

### Target Spreadsheet Details
- **Google Sheet URL**: `https://docs.google.com/spreadsheets/d/1179NQXjHa6n2vCb0SAnsZW7HQ7oLM42tk4OfwKnyR4g/edit`
- **Owner Account**: `onlyarmor123isallowed@gmail.com`
- **Target Tab Name**: **`Links_Sync`**

### Data Schema (7 Columns, matching Export CSV)
| Column | Name | Description |
| :--- | :--- | :--- |
| **A** | `ID` | Queue ID (1, 2, 3...) |
| **B** | `Source URL` | Competitor source URL (Unique match key) |
| **C** | `Category` | Article category / niche (e.g. Flowers, General) |
| **D** | `Status` | `done`, `pending`, `processing`, `failed` |
| **E** | `Published Link` | Live WordPress post URL (`https://zivibloom.com/...`) |
| **F** | `Created At` | Timestamp when queued |
| **G** | `Updated At` | Timestamp when last processed |

---

## 5. Complete Google Apps Script Code (`Links_Sync`)

Deploy this script in the spreadsheet under **Extensions $\to$ Apps Script**:

```javascript
/**
 * Auto Content Pipeline — Google Sheets Sync Gateway (Tab: Links_Sync)
 * Paste this into Extensions > Apps Script in your Google Sheet, then Deploy as Web App.
 * IMPORTANT:
 * 1. Click "Run" on testConnection once to authorize access (Review permissions > Advanced > Allow).
 * 2. When deploying: set "Execute as: Me" and "Who has access: Anyone".
 */

// Finds or automatically creates the dedicated 'Links_Sync' tab
function getLinksSyncSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Links_Sync");
  if (!sheet) {
    sheet = ss.insertSheet("Links_Sync");
  }
  return sheet;
}

// Run this function ONCE inside the Apps Script editor to authorize access!
function testConnection() {
  var sheet = getLinksSyncSheet();
  Logger.log("SUCCESS! Connected to tab: " + sheet.getName() + " in " + SpreadsheetApp.getActiveSpreadsheet().getName());
}

function doGet(e) {
  try {
    var sheet = getLinksSyncSheet();
    return ContentService.createTextOutput(JSON.stringify({
      success: true,
      message: "Connected to tab '" + sheet.getName() + "' in " + SpreadsheetApp.getActiveSpreadsheet().getName() + ". Sync gateway is ready!"
    })).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      success: false,
      error: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    return ContentService.createTextOutput(JSON.stringify({
      success: false,
      error: "Sheet is busy with another sync request. Please try again."
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  try {
    var sheet = getLinksSyncSheet();
    var payload = JSON.parse(e.postData.contents);
    
    // 1. Healthcheck / Ping
    if (payload.action === "ping") {
      return ContentService.createTextOutput(JSON.stringify({
        success: true,
        message: "Connected to tab '" + sheet.getName() + "' in " + SpreadsheetApp.getActiveSpreadsheet().getName()
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    var rows = payload.rows || [];
    var headers = ["ID", "Source URL", "Category", "Status", "Published Link", "Created At", "Updated At"];
    var lastRow = sheet.getLastRow();
    
    // 2. Initialize Headers if sheet is blank
    if (lastRow === 0) {
      sheet.appendRow(headers);
      sheet.getRange(1, 1, 1, headers.length)
           .setFontWeight("bold")
           .setBackground("#1e293b")
           .setFontColor("#f8fafc");
      sheet.setFrozenRows(1);
      lastRow = 1;
    }
    
    // 3. Build Index of Existing URLs in Column B (Index 2 in sheet)
    var urlMap = {};
    if (lastRow > 1) {
      var existingUrls = sheet.getRange(2, 2, lastRow - 1, 1).getValues();
      for (var i = 0; i < existingUrls.length; i++) {
        var u = String(existingUrls[i][0] || "").trim();
        if (u) {
          urlMap[u] = i + 2; // 1-based row index in sheet
        }
      }
    }
    
    var updatedCount = 0;
    var addedCount = 0;
    var toAppend = [];
    
    // 4. Match & Synchronize
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j];
      var srcUrl = String(r.source_url || r.url || "").trim();
      if (!srcUrl) continue;
      
      var rowData = [
        r.id || "",
        srcUrl,
        r.category || "General",
        r.status || "pending",
        r.published_link || r.post_url || "N/A",
        r.created_at || "",
        r.updated_at || ""
      ];
      
      if (urlMap[srcUrl]) {
        // Update in-place to avoid duplicate rows
        var targetRow = urlMap[srcUrl];
        sheet.getRange(targetRow, 1, 1, rowData.length).setValues([rowData]);
        updatedCount++;
      } else {
        toAppend.push(rowData);
        urlMap[srcUrl] = lastRow + toAppend.length; // track to prevent duplicates within batch
        addedCount++;
      }
    }
    
    // 5. Append new rows in a single batch
    if (toAppend.length > 0) {
      var nextRow = sheet.getLastRow() + 1;
      sheet.getRange(nextRow, 1, toAppend.length, headers.length).setValues(toAppend);
    }
    
    return ContentService.createTextOutput(JSON.stringify({
      success: true,
      total: rows.length,
      updated: updatedCount,
      added: addedCount,
      tab_name: sheet.getName(),
      sheet_name: SpreadsheetApp.getActiveSpreadsheet().getName()
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      success: false,
      error: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
```

---

## 6. Critical Google Apps Script Deployment Rules & Troubleshooting

If you hit `403 Access Denied: You need access` or `Unexpected token '<'`, check these 3 rules:

1. **One-Time Script Authorization (Run Button)**:
   - Apps Script blocks all external web requests until the owner executes a function inside the editor.
   - **Fix**: In the editor toolbar, select `testConnection` (or `doGet`) and click **▶ Run**. When the popup appears, click **Review permissions** $\to$ choose account $\to$ **Advanced** $\to$ **Go to Untitled project (unsafe)** $\to$ **Allow**.
2. **Deployment Access Settings**:
   - Must be: **Execute as: Me (owner)** and **Who has access: Anyone**.
   - Note: Do NOT set "User accessing the web app" or "Anyone with Google Account".
3. **New Version Requirement**:
   - If using **Manage deployments**: You must change the **Version** dropdown to **New version** before clicking Deploy.
   - If using **New deployment**: Google generates a **new Web App URL** (`https://script.google.com/macros/s/.../exec`). You MUST copy and paste the new URL into **Settings** in the Auto Blog Flask dashboard and click **Save Settings**.
4. **Browser Cache**:
   - If UI throws a JSON syntax error, hard refresh the browser tab with `Ctrl + F5`.

---

## 7. Key Code Files & Directory Map

```text
auto-blog-flask/
├── AGY_CONTEXT.md              # THIS FILE: Master knowledge base for AGY
├── app.py                      # Flask server, API endpoints, SSE log broadcaster
├── google_sheet_sync.py        # Python sync engine & Apps Script code generator
├── pipeline_config.json        # Main configuration file (WordPress, models, settings)
├── pipeline_engine.py          # Multi-step content pipeline orchestrator
├── wordpress_publisher.py      # WordPress REST API publisher & RankMath handler
├── worker.py                   # Background pipeline queue worker
├── queue_state.db              # SQLite queue database (all 43 current URLs)
├── run.py / run.bat            # One-click launcher script
├── REVERT__ISSUES/             # Slugs revert patch scripts and tracking CSV
│   ├── Icssues.csv             # The 43 articles list
│   └── patch_revert_slugs.py   # Revert execution script
├── static/
│   ├── js/app.js               # Frontend JavaScript (Queue UI, Sync Sheets, modals)
│   └── css/style.css           # Styling
└── templates/
    └── index.html              # Dashboard UI & Google Sheets setup modal
```

---

## 8. Backend API Endpoints Reference

- **`POST /api/queue/sync-sheets`**: Reads all items from `queue_state.db` and pushes them to the configured Google Sheet Webhook URL.
- **`POST /api/test-google-sheets`**: Sends a ping action to the Webhook URL to verify connectivity and sheet name.
- **`GET /api/google-sheets/script-code`**: Returns the latest Apps Script snippet dynamically.
- **`GET /api/queue/export`**: Downloads queue as CSV (`url_queue_export_*.csv`).
- **`POST /api/queue`**: Add new URL to queue.
- **`POST /api/settings`**: Save configuration to `pipeline_config.json`.
- **`GET /api/status`**: Returns worker status (`idle` vs `running`), stats, and queue counts.

---

## 9. Quick Commands for Future Sessions

- **Run Web Dashboard**: `run.bat` or `python run.py` (opens `http://127.0.0.1:5000`)
- **Test Google Sheet Webhook via CLI**:
  ```bash
  python -c "import google_sheet_sync; print(google_sheet_sync.test_connection('<webhook_url>'))"
  ```
- **Inspect Queue Database**:
  ```bash
  python -c "import sqlite3; conn = sqlite3.connect('queue_state.db'); print(conn.execute('SELECT COUNT(*), status FROM queue GROUP BY status').fetchall())"
  ```
