#!/usr/bin/env python3
"""
run.py — One-Click Launcher for Auto Content Pipeline (Flask Edition)
Checks dependencies, initializes transparent IPv4 proxy, opens default browser,
and hosts the control panel on http://127.0.0.1:5000.
"""

import os
import sys
import time
import subprocess
import webbrowser
import threading
import importlib
from pathlib import Path

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

ROOT = Path(__file__).parent.resolve()
os.chdir(ROOT)

REQUIRED = {
    "flask": "flask",
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "newspaper": "newspaper4k",
    "jinja2": "Jinja2",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "nltk": "nltk",
}

import shutil

def ensure_external_tools():
    """
    Checks and auto-installs Google Antigravity CLI ('agy') and GFlow CLI ('gflow')
    if missing on the user's computer.
    """
    home = Path.home()
    
    # 1. Antigravity CLI (agy)
    agy_bin = shutil.which("agy")
    default_agy_path = home / "AppData" / "Local" / "agy" / "bin"
    if not agy_bin and (default_agy_path / "agy.exe").exists():
        agy_bin = str(default_agy_path / "agy.exe")
        os.environ["PATH"] = f"{default_agy_path};{os.environ.get('PATH', '')}"

    if not agy_bin:
        print("[*] Antigravity CLI ('agy') not found in PATH. Installing automatically via official installer...")
        try:
            ps_cmd = 'irm https://antigravity.google/cli/install.ps1 | iex'
            subprocess.run(["powershell", "-ExecutionPolicy", "ByPass", "-NoProfile", "-Command", ps_cmd], check=False)
            if (default_agy_path / "agy.exe").exists():
                os.environ["PATH"] = f"{default_agy_path};{os.environ.get('PATH', '')}"
                print("    [+] Antigravity CLI ('agy') installed successfully.")
            else:
                print("    [!] Antigravity CLI installation finished, please verify 'agy' in your PATH.")
        except Exception as e:
            print(f"    [!] Failed to auto-install Antigravity CLI: {e}")
    else:
        print("[+] Antigravity CLI ('agy') detected.")

    # 2. GFlow CLI (gflow)
    gflow_bin = shutil.which("gflow")
    default_gflow_path = home / ".local" / "bin"
    if not gflow_bin and (default_gflow_path / "gflow.exe").exists():
        gflow_bin = str(default_gflow_path / "gflow.exe")
        os.environ["PATH"] = f"{default_gflow_path};{os.environ.get('PATH', '')}"

    if not gflow_bin:
        print("[*] GFlow CLI ('gflow') not found. Installing automatically from PyPI...")
        try:
            installed = False
            if not getattr(sys, "frozen", False):
                try:
                    subprocess.run([sys.executable, "-m", "pip", "install", "gflow-cli", "-q"], check=True)
                    installed = True
                except Exception:
                    pass
            
            if not installed:
                ps_cmd = 'pip install gflow-cli; if ($LASTEXITCODE -ne 0) { uv tool install gflow-cli }'
                subprocess.run(["powershell", "-ExecutionPolicy", "ByPass", "-NoProfile", "-Command", ps_cmd], check=False)
            
            if (default_gflow_path / "gflow.exe").exists():
                os.environ["PATH"] = f"{default_gflow_path};{os.environ.get('PATH', '')}"
            print("    [+] GFlow CLI ('gflow') installed successfully.")
        except Exception as e:
            print(f"    [!] Failed to auto-install GFlow CLI: {e}")
    else:
        print("[+] GFlow CLI ('gflow') detected.")

def ensure_dependencies():
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"\n📦 Installing missing dependencies: {', '.join(missing)} ...\n")
        subprocess.run([sys.executable, "-m", "pip", "install", *missing, "-q"], check=True)
        print("✅ Dependencies ready.\n")

def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5000")

def main():
    print("=" * 65)
    print("🚀 AUTO CONTENT PIPELINE — FLASK CONTROL PANEL")
    print("=" * 65)
    if not getattr(sys, "frozen", False):
        ensure_dependencies()
    ensure_external_tools()

    import ipv4_guard
    port = ipv4_guard.start_ipv4_guard()
    if port:
        print(f"🔒 In-process IPv4 Loopback Guard active on 127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    from app import app
    print("🌐 Dashboard opening at http://127.0.0.1:5000")
    print("Press Ctrl+C in this terminal to shut down.")
    print("=" * 65)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

if __name__ == "__main__":
    main()
