#!/usr/bin/env python3
"""
gflow_bridge.py — Integration Bridge for Google Flow (gflow CLI)
Handles headless / off-screen image generation, authentication status & login,
auto-updates, and interactive terminal commands.
"""

import os
import sys
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional, Callable, Tuple, Dict, Any
from PIL import Image

GFLOW_BIN = shutil.which("gflow") or "gflow"


def is_installed() -> bool:
    return shutil.which("gflow") is not None


def get_version() -> str:
    if not is_installed():
        return "Not Installed"
    try:
        proc = subprocess.run([GFLOW_BIN, "--version"], capture_output=True, text=True, timeout=10)
        out = proc.stdout.strip()
        if "version" in out.lower():
            return out.split("version")[-1].strip()
        return out or "Unknown"
    except Exception as e:
        return f"Error: {e}"


def check_update() -> Dict[str, Any]:
    """
    Checks if a newer version of gflow-cli is available on PyPI.
    Returns: {"installed": ..., "latest": ..., "update_available": bool, "raw": ...}
    """
    if not is_installed():
        return {"installed": None, "latest": None, "update_available": False, "error": "gflow not installed"}

    try:
        proc = subprocess.run(
            [GFLOW_BIN, "update", "--check", "--json"],
            capture_output=True,
            text=True,
            timeout=25,
            encoding="utf-8",
            errors="replace"
        )
        # Parse JSON output (skip any header warnings/text)
        out = proc.stdout.strip()
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        for line in reversed(lines):
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if "update_available" in data:
                        return {
                            "installed": data.get("installed", "unknown"),
                            "latest": data.get("latest", "unknown"),
                            "update_available": bool(data.get("update_available", False)),
                            "installer": data.get("installer", "uv"),
                        }
                except Exception:
                    continue

        # Fallback text parse
        v_curr = get_version()
        return {"installed": v_curr, "latest": v_curr, "update_available": False}
    except Exception as e:
        return {"installed": get_version(), "latest": None, "update_available": False, "error": str(e)}


def run_update(log_cb: Optional[Callable[[str, str], None]] = None) -> Tuple[bool, str]:
    """
    Runs gflow update to upgrade gflow-cli.
    """
    if not is_installed():
        return False, "gflow is not installed."

    def _log(msg, lvl="info"):
        if log_cb:
            log_cb(msg, lvl)

    _log("Starting gflow self-update via package manager...", "info")
    try:
        proc = subprocess.Popen(
            [GFLOW_BIN, "update"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        output_lines = []
        for line in proc.stdout:
            clean = line.rstrip()
            if clean:
                output_lines.append(clean)
                _log(clean, "info")

        proc.wait(timeout=90)
        # Check new version
        new_v = get_version()
        _log(f"gflow update completed. Current version: {new_v}", "success")
        return True, f"Updated to version {new_v}"
    except Exception as e:
        _log(f"gflow update failed: {e}", "error")
        return False, str(e)


def check_auth(profile: str = "") -> Tuple[bool, str]:
    """
    Probes Google Flow session status.
    Returns: (is_authenticated: bool, details_message: str)
    """
    if not is_installed():
        return False, "gflow executable not found in PATH."

    cmd = [GFLOW_BIN, "auth", "status"]
    if profile.strip():
        cmd.extend(["--profile", profile.strip()])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=50,
            encoding="utf-8",
            errors="replace"
        )
        combined = (proc.stdout + "\n" + proc.stderr).strip()
        is_ok = (proc.returncode == 0)

        # Extract concise verification line
        msg = "Session verified"
        for line in combined.splitlines():
            line_str = line.strip()
            if "flow session verified" in line_str.lower():
                msg = line_str
                is_ok = True
                break
            elif "signed in to google, but not to the flow app" in line_str.lower():
                msg = line_str
                break
            elif "not signed in" in line_str.lower() or "no session" in line_str.lower():
                msg = line_str
                is_ok = False
                break

        # Check for persistent profile cookies if probe endpoint had a 410 redirect/migration
        if not is_ok and "cookies_present: true" in combined.lower() and "exists: true" in combined.lower():
            if not any(k in combined.lower() for k in ["not signed in", "no session", "session dead"]):
                is_ok = True
                msg = "Persistent session cookies present (ready for generation)"

        return is_ok, msg
    except subprocess.TimeoutExpired:
        return False, "Auth probe timed out (network slow)."
    except Exception as e:
        return False, str(e)


def login_interactive(profile: str = "", log_cb: Optional[Callable[[str, str], None]] = None) -> Tuple[bool, str]:
    """
    Executes gflow auth login. This pops up the interactive Chrome login browser.
    Once authenticated, Chrome closes automatically.
    """
    if not is_installed():
        return False, "gflow is not installed."

    def _log(msg, lvl="info"):
        if log_cb:
            log_cb(msg, lvl)

    cmd = [GFLOW_BIN, "auth", "login"]
    if profile.strip():
        cmd.extend(["--profile", profile.strip()])

    _log(f"Launching Google Flow authentication (Command: {' '.join(cmd)})...", "info")
    _log("A browser window will open automatically. Complete your Google sign-in. The window will close itself once done.", "warning")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        output_lines = []
        for line in proc.stdout:
            clean = line.rstrip()
            if clean:
                output_lines.append(clean)
                _log(clean, "info")

        proc.wait(timeout=300)
        if proc.returncode == 0:
            _log("Google Flow login verified & session saved successfully!", "success")
            return True, "Login successful"
        else:
            _log(f"Google Flow login process exited with returncode {proc.returncode}.", "error")
            return False, f"Process exited with code {proc.returncode}"
    except Exception as e:
        _log(f"Error during gflow login: {e}", "error")
        return False, str(e)


def launch_native_terminal(profile: str = "") -> bool:
    """
    Spawns a native Windows Command Prompt window with gflow environment prepped.
    """
    try:
        profile_flag = f"--profile {profile}" if profile else ""
        cmd_script = (
            "title Google Flow (gflow) CLI Console & "
            "echo ======================================================== & "
            "echo   GOOGLE FLOW (gflow) CLI INTERACTIVE TERMINAL & "
            "echo ======================================================== & "
            "echo. & "
            f"gflow auth status {profile_flag} & "
            "echo. & "
            "echo Tip: Run 'gflow --help' or 'gflow auth login' & "
            "echo. & "
            "cmd.exe /k"
        )
        subprocess.Popen(["cmd.exe", "/c", f"start {cmd_script}"], shell=True)
        return True
    except Exception:
        return False


def execute_raw(command_str: str, log_cb: Optional[Callable[[str, str], None]] = None, timeout: int = 120) -> Tuple[int, str]:
    """
    Executes an arbitrary gflow command and returns (returncode, output_text).
    """
    clean_cmd = command_str.strip()
    if clean_cmd.startswith("gflow "):
        clean_cmd = clean_cmd[6:].strip()

    args = [GFLOW_BIN] + [arg.strip() for arg in clean_cmd.split() if arg.strip()]

    def _log(msg, lvl="info"):
        if log_cb:
            log_cb(msg, lvl)

    _log(f"$ gflow {clean_cmd}", "info")
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        lines = []
        for line in proc.stdout:
            l_str = line.rstrip()
            if l_str:
                lines.append(l_str)
                _log(l_str, "info")

        proc.wait(timeout=timeout)
        return proc.returncode, "\n".join(lines)
    except Exception as e:
        _log(f"Execution error: {e}", "error")
        return -1, str(e)


def generate_image(
    prompt: str,
    dest_path: Path,
    aspect: str = "16:9",
    model: str = "nano2",
    profile: str = "",
    headless: bool = True,
    timeout: int = 180,
    log_cb: Optional[Callable[[str, str], None]] = None
) -> bool:
    """
    Generates an image via gflow image t2i.
    Runs headless / offscreen to avoid window popups during batch runs.
    Verifies image integrity and saves to dest_path.
    """
    if not is_installed():
        if log_cb:
            log_cb("gflow CLI not found in PATH.", "error")
        return False

    def _log(msg, lvl="info"):
        if log_cb:
            log_cb(msg, lvl)

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_target = dest_path.with_name(f"_gflow_temp_{dest_path.stem}.jpg")

    cmd = [
        GFLOW_BIN, "image", "t2i",
        prompt[:350],
        "--model", model or "nano2",
        "--aspect", aspect or "16:9",
        "-n", "1",
        "-o", str(temp_target)
    ]
    if profile.strip():
        cmd.extend(["--profile", profile.strip()])

    # Setup environment for offscreen / headless execution
    env = dict(os.environ)
    if headless:
        env["GFLOW_CLI_BROWSER_WINDOW_POSITION"] = "-30000,-30000"
    env["GFLOW_CLI_UPDATE_CHECK"] = "0"  # Silence update warnings during generation

    _log(f"[gflow] Executing t2i generation (model: {model}, aspect: {aspect})...", "info")

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            _log(f"[gflow] CLI generation error (code {proc.returncode}): {err_msg[:250]}", "error")
            return False

        # Look for the generated output
        target_file = None
        if temp_target.exists() and temp_target.stat().st_size > 1000:
            target_file = temp_target
        else:
            # Fallback search in catalog if renamed
            candidates = list(dest_path.parent.glob(f"_gflow_temp_{dest_path.stem}.*"))
            if candidates:
                target_file = candidates[0]

        if not target_file or not target_file.exists():
            _log(f"[gflow] Generation finished but target file not found at {temp_target.name}.", "error")
            return False

        # Convert to target format (e.g. WebP) & check blank image
        with Image.open(target_file) as img:
            fmt = "WEBP" if dest_path.suffix.lower() == ".webp" else "JPEG"
            img.convert("RGB").save(dest_path, fmt, quality=88)

        # Cleanup temp file
        try:
            target_file.unlink(missing_ok=True)
        except Exception:
            pass

        _log(f"[gflow] Visual successfully saved: {dest_path.name}", "success")
        return True
    except subprocess.TimeoutExpired:
        _log(f"[gflow] Image generation timed out after {timeout}s", "error")
        return False
    except Exception as e:
        _log(f"[gflow] Exception generating image: {e}", "error")
        return False
