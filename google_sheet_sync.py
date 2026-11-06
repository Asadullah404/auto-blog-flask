#!/usr/bin/env python3
"""
google_sheet_sync.py — Google Sheets Integration via Google Apps Script Web App
Enables zero-friction, zero-cloud-console synchronization between queue_state.db
and Google Sheets with zero duplicate entries.
"""

import json
import re
import requests
from typing import Dict, Any, List, Tuple

# Ready-to-deploy Google Apps Script snippet for the user's sheet
APPS_SCRIPT_CODE = '''/**
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
'''


def extract_sheet_id(url: str) -> str:
    """
    Extracts the spreadsheet ID from a Google Sheet URL.
    E.g. 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit'
         -> '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms'
    """
    if not url:
        return ""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", str(url))
    return m.group(1) if m else ""


def test_connection(webhook_url: str) -> Tuple[bool, str]:
    """
    Tests connection to the Google Apps Script Web App endpoint.
    """
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return False, "Google Sheet Webhook URL is empty."

    if not webhook_url.startswith("https://script.google.com/"):
        return False, "Invalid Webhook URL. It must start with 'https://script.google.com/'"

    try:
        resp = requests.post(
            webhook_url,
            json={"action": "ping"},
            headers={"Content-Type": "application/json"},
            timeout=25,
            allow_redirects=True,
        )

        # Detect Google 401/403 or Sign-In Redirect (caused when 'Who has access' is not 'Anyone' or script unauthorized)
        if (
            resp.status_code in (401, 403)
            or "accounts.google.com" in resp.url
            or (resp.text and ("<!doctype" in resp.text.lower() or "<html" in resp.text.lower()))
        ):
            return False, (
                "Google Access Denied (Authorization or Deployment issue):\n"
                "1. Inside Apps Script editor, select 'testConnection' from the dropdown and click 'Run (play icon)'. Click 'Review permissions' -> 'Advanced' -> 'Allow' to grant one-time access.\n"
                "2. Click Deploy > Manage deployments > Edit > select Version: 'New version', verify 'Execute as: Me' and 'Who has access: Anyone', then click Deploy.\n"
                "3. If you clicked 'New deployment', copy the NEW Web App URL and paste it into Settings here."
            )

        if resp.status_code >= 400:
            return False, f"HTTP Error {resp.status_code}: {resp.text[:200]}"

        # Parse JSON
        try:
            data = resp.json()
            if data.get("success"):
                return True, data.get("message", "Connected successfully to Google Sheet!")
            return False, data.get("error", "Unknown error from Apps Script.")
        except Exception:
            return False, f"Unexpected response from Webhook: {resp.text[:200]}"

    except requests.Timeout:
        return False, "Connection timed out after 25s. Check the Google Sheet script deployment."
    except Exception as e:
        return False, f"Connection error: {e}"


def sync_queue_to_sheet(webhook_url: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sends queue rows to the Google Apps Script Web App.
    Matches the Export CSV format: ID, Source URL, Category, Status, Published Link, Created At, Updated At.
    """
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return {"success": False, "error": "Google Sheet Webhook URL is not configured in Settings."}

    if not rows:
        return {"success": True, "total": 0, "updated": 0, "added": 0, "message": "Queue is empty; nothing to sync."}

    payload = {
        "action": "sync",
        "rows": rows,
    }

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60,
            allow_redirects=True,
        )

        # Detect Google 401 or Sign-In Redirect
        if (
            resp.status_code == 401
            or "accounts.google.com" in resp.url
            or (resp.text and ("<!doctype" in resp.text.lower() or "<html" in resp.text.lower()))
        ):
            return {
                "success": False,
                "error": "Permission Error (Google Sign-In Required): In your Google Sheet, go to Extensions > Apps Script > Deploy > Manage deployments, click Edit (pencil icon), change 'Who has access' to 'Anyone', then click Deploy.",
            }

        if resp.status_code >= 400:
            return {"success": False, "error": f"HTTP {resp.status_code} from Webhook: {resp.text[:200]}"}

        try:
            data = resp.json()
            return data
        except Exception:
            return {"success": False, "error": f"Failed to parse Webhook JSON response: {resp.text[:200]}"}

    except requests.Timeout:
        return {"success": False, "error": "Google Sheets sync timed out after 60s."}
    except Exception as e:
        return {"success": False, "error": f"Sync request exception: {e}"}
