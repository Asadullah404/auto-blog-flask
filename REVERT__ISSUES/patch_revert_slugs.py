#!/usr/bin/env python3
"""
patch_revert_slugs.py — Standalone WordPress Slug Revert Patch
Processes REVERT__ISSUES/Icssues.csv without AI or local DB dependency.
Connects directly to WordPress REST API using credentials from pipeline_config.json (or .env),
updates post slugs to match the exact competitor/source URL slugs,
and marks each row's status from 'Pending' to 'done'.
"""

import os
import sys
import re
import csv
import json
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit
import requests
from requests.auth import HTTPBasicAuth

# Force UTF-8 on Windows console
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

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent.resolve()


def load_credentials() -> dict:
    """
    Loads WordPress credentials from pipeline_config.json (primary)
    or falls back to .env in REVERT__ISSUES.
    """
    cfg_candidates = [
        REPO_ROOT / "pipeline_config.json",
        SCRIPT_DIR / "pipeline_config.json",
        Path("pipeline_config.json").resolve(),
    ]
    for p in cfg_candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("base_url") and data.get("username") and data.get("app_password"):
                    print(f"[*] Loaded credentials from: {p}")
                    return {
                        "base_url": data["base_url"].strip().rstrip("/"),
                        "username": data["username"].strip(),
                        "app_password": data["app_password"].strip(),
                        "seo_plugin": data.get("seo_plugin", "rankmath"),
                    }
            except Exception as e:
                print(f"[!] Warning reading {p}: {e}")

    # Fallback to .env in SCRIPT_DIR
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        print(f"[*] Loading credentials from fallback .env: {env_file}")
        creds = {}
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
        if creds.get("base_url") and creds.get("username") and creds.get("app_password"):
            return {
                "base_url": creds["base_url"].rstrip("/"),
                "username": creds["username"],
                "app_password": creds["app_password"],
                "seo_plugin": creds.get("seo_plugin", "rankmath"),
            }

    raise RuntimeError(
        "Could not find WordPress credentials in pipeline_config.json or REVERT__ISSUES/.env."
    )


def extract_competitor_slug(url: str) -> str:
    """
    Extracts the clean competitor slug from a source URL.
    E.g. 'https://fizzyflare.com/lunch-box-organization/' -> 'lunch-box-organization'
    """
    if not url:
        return ""
    try:
        parsed = urlsplit(str(url).strip())
        path = parsed.path.strip("/")
        if not path:
            return ""
        segments = [s for s in path.split("/") if s]
        if not segments:
            return ""
        last_seg = segments[-1]
        last_seg = re.sub(r"\.(html?|php|asp|aspx)$", "", last_seg, flags=re.IGNORECASE)
        slug = re.sub(r"[^\w\s-]", "", last_seg.lower())
        slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
        return slug
    except Exception:
        return ""


def extract_post_id(row: dict) -> str:
    """
    Extracts WordPress numeric post ID from row fields ('ACTUAL', 'tt', 'Published Link').
    """
    for field in ["ACTUAL", "tt", "Published Link", "tt2"]:
        val = str(row.get(field, "") or "")
        m = re.search(r"\?p=(\d+)", val)
        if m:
            return m.group(1)
        # Check if direct digit
        if val.strip().isdigit():
            return val.strip()
    return ""


def main():
    print("=" * 70)
    print("      REVERT ISSUES PATCH — WORDPRESS SLUG REVERSAL ENGINE")
    print("=" * 70)

    # 1. Load credentials
    creds = load_credentials()
    base_url = creds["base_url"]
    auth = HTTPBasicAuth(creds["username"], creds["app_password"])

    print(f"[*] Target WordPress Site: {base_url}")
    print(f"[*] Authenticating User:   {creds['username']}")
    print(f"[*] SEO Plugin Target:     {creds['seo_plugin']}")
    print("-" * 70)

    # 2. Verify connection
    try:
        r_me = requests.get(f"{base_url}/wp-json/wp/v2/users/me", auth=auth, timeout=20)
        if r_me.status_code == 401:
            print("[x] Error: 401 Unauthorized — verify username & application password.")
            sys.exit(1)
        elif r_me.status_code >= 400:
            print(f"[x] Error: HTTP {r_me.status_code} reaching WordPress REST API.")
            sys.exit(1)
        user_name = r_me.json().get("name", "Authorized User")
        print(f"[OK] Connection verified. Authenticated as: {user_name}\n")
    except Exception as e:
        print(f"[x] Error connecting to WordPress: {e}")
        sys.exit(1)

    # 3. Locate CSV
    csv_candidates = [
        SCRIPT_DIR / "Icssues.csv",
        REPO_ROOT / "REVERT__ISSUES" / "Icssues.csv",
        Path("Icssues.csv").resolve(),
    ]
    csv_path = None
    for p in csv_candidates:
        if p.exists():
            csv_path = p
            break

    if not csv_path:
        print("[x] Error: Icssues.csv not found.")
        sys.exit(1)

    print(f"[*] Loading CSV file: {csv_path}")

    # Read existing rows and fieldnames
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_rows = len(rows)
    print(f"[*] Found {total_rows} total rows in CSV.\n")

    updated_count = 0
    already_done_count = 0
    failed_count = 0

    def save_csv():
        with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    # 4. Process rows
    for idx, row in enumerate(rows, 1):
        row_id = row.get("ID", str(idx))
        source_url = row.get("Source URL", "").strip()
        status = row.get("Status", "").strip()
        post_id = extract_post_id(row)
        competitor_slug = extract_competitor_slug(source_url)

        prefix = f"[{idx:02d}/{total_rows:02d}] (ID: {row_id})"

        # Check if already done
        if status.lower() == "done":
            print(f"{prefix} [SKIP] Status is already 'done' -> {row.get('ACTUAL', source_url)}")
            already_done_count += 1
            continue

        if not post_id:
            print(f"{prefix} [FAIL] Could not determine post ID from row data.")
            failed_count += 1
            continue

        if not competitor_slug:
            print(f"{prefix} [FAIL] Could not extract competitor slug from: {source_url}")
            failed_count += 1
            continue

        # Fetch current post status
        api_post_url = f"{base_url}/wp-json/wp/v2/posts/{post_id}"
        try:
            get_resp = requests.get(api_post_url, auth=auth, timeout=30)
            if get_resp.status_code == 200:
                current_post = get_resp.json()
                current_slug = current_post.get("slug", "")

                if current_slug == competitor_slug:
                    print(f"{prefix} [OK] Post #{post_id} slug is already '{competitor_slug}'. Updating CSV...")
                    row["Status"] = "done"
                    row["Updated At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    row["ACTUAL"] = current_post.get("link", f"{base_url}/{competitor_slug}/")
                    save_csv()
                    updated_count += 1
                    continue
            elif get_resp.status_code == 404:
                print(f"{prefix} [FAIL] Post #{post_id} not found on WordPress (404).")
                failed_count += 1
                continue
        except Exception as e:
            print(f"{prefix} [WARN] Error fetching post #{post_id}: {e}")

        # Update slug via WordPress REST API
        try:
            payload = {"slug": competitor_slug}
            post_resp = requests.post(api_post_url, json=payload, auth=auth, timeout=30)

            if post_resp.status_code == 200:
                post_data = post_resp.json()
                returned_slug = post_data.get("slug", "")
                new_link = post_data.get("link", f"{base_url}/{competitor_slug}/")

                # Update row data
                row["Status"] = "done"
                row["Updated At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row["ACTUAL"] = new_link

                # Save immediately to prevent data loss on crash
                save_csv()

                print(
                    f"{prefix} [SUCCESS] Post #{post_id} slug updated to: '{returned_slug}'\n"
                    f"            -> Live Link: {new_link}"
                )
                updated_count += 1
            else:
                err_text = post_resp.text[:150]
                print(f"{prefix} [FAIL] HTTP {post_resp.status_code} updating post #{post_id}: {err_text}")
                failed_count += 1
        except Exception as e:
            print(f"{prefix} [ERROR] Exception updating post #{post_id}: {e}")
            failed_count += 1

        time.sleep(0.3)  # Brief polite delay between REST calls

    print("\n" + "=" * 70)
    print("                    PATCH EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Total Rows:            {total_rows}")
    print(f"Already Completed:     {already_done_count}")
    print(f"Successfully Updated:  {updated_count}")
    print(f"Failed / Unresolved:   {failed_count}")
    print(f"CSV Updated:           {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
