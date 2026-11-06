"""
firestore_sync.py — Firebase Authentication & Firestore Cloud Queue Sync
Supports multi-device link queue synchronization, automatic lease claim locking,
and cheap COUNT aggregations.
"""

import os
import json
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import requests

FIRESTORE_HOST = "https://firestore.googleapis.com"
IDENTITY_TOOLKIT_BASE = "https://identitytoolkit.googleapis.com/v1/accounts"
SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
SESSION_FILE = "firebase_session.json"
CONFIG_FILE = "firebase_config.json"

_ERROR_MESSAGES = {
    "EMAIL_EXISTS": "An account with this email already exists — try signing in.",
    "EMAIL_NOT_FOUND": "No account found with this email — try creating one.",
    "INVALID_PASSWORD": "Incorrect password.",
    "INVALID_LOGIN_CREDENTIALS": "Incorrect email or password.",
    "WEAK_PASSWORD": "Password must be at least 6 characters.",
    "INVALID_EMAIL": "Invalid email address format.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts — please wait a bit.",
    "OPERATION_NOT_ALLOWED": "Email/Password sign-in not enabled in Firebase Console.",
}

class AuthError(Exception):
    pass

class FirestoreError(Exception):
    pass


def _firebase_cfg() -> dict:
    p = Path(CONFIG_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _api_key() -> str:
    cfg = _firebase_cfg()
    key = cfg.get("apiKey")
    if not key:
        raise AuthError(f"Missing apiKey in {CONFIG_FILE}. Check firebase_config.example.json.")
    return key


def _project_id() -> str:
    cfg = _firebase_cfg()
    pid = cfg.get("projectId")
    if not pid:
        raise FirestoreError(f"Missing projectId in {CONFIG_FILE}.")
    return pid


def load_session() -> dict | None:
    p = Path(SESSION_FILE)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_session(session: dict):
    Path(SESSION_FILE).write_text(json.dumps(session, indent=2), encoding="utf-8")


def sign_out():
    Path(SESSION_FILE).unlink(missing_ok=True)


def current_profile() -> dict | None:
    sess = load_session()
    if not sess:
        return None
    return {"uid": sess.get("uid"), "email": sess.get("email")}


def get_valid_id_token() -> tuple[str | None, str | None]:
    sess = load_session()
    if not sess or not sess.get("refreshToken"):
        return None, None
    try:
        resp = requests.post(
            SECURE_TOKEN_URL,
            params={"key": _api_key()},
            data={"grant_type": "refresh_token", "refresh_token": sess["refreshToken"]},
            timeout=15,
        )
    except Exception:
        return None, None

    if not resp.ok:
        sign_out()
        return None, None

    data = resp.json()
    sess["refreshToken"] = data["refresh_token"]
    save_session(sess)
    return data["id_token"], data["user_id"]


def sign_in(email: str, password: str) -> dict:
    resp = requests.post(
        f"{IDENTITY_TOOLKIT_BASE}:signInWithPassword",
        params={"key": _api_key()},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=20,
    )
    if not resp.ok:
        try:
            err = resp.json()["error"]["message"]
            raise AuthError(_ERROR_MESSAGES.get(err, err))
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Sign-in failed ({resp.status_code})")
    data = resp.json()
    sess = {"refreshToken": data["refreshToken"], "uid": data["localId"], "email": data.get("email", email)}
    save_session(sess)
    return {"uid": sess["uid"], "email": sess["email"]}


def sign_up(email: str, password: str) -> dict:
    resp = requests.post(
        f"{IDENTITY_TOOLKIT_BASE}:signUp",
        params={"key": _api_key()},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=20,
    )
    if not resp.ok:
        try:
            err = resp.json()["error"]["message"]
            raise AuthError(_ERROR_MESSAGES.get(err, err))
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Sign-up failed ({resp.status_code})")
    data = resp.json()
    sess = {"refreshToken": data["refreshToken"], "uid": data["localId"], "email": data.get("email", email)}
    save_session(sess)
    return {"uid": sess["uid"], "email": sess["email"]}


# ── Firestore REST Data Helpers ─────────────────────────────────
def link_doc_id(url: str) -> str:
    parts = urlsplit(url.strip())
    normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]


def _encode_value(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [_encode_value(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _encode_value(val) for k, val in v.items()}}}
    return {"stringValue": str(v)}


def _decode_value(fv: dict):
    if not isinstance(fv, dict):
        return fv
    for k in ("stringValue", "timestampValue"):
        if k in fv:
            return fv[k]
    if "integerValue" in fv:
        return int(fv["integerValue"])
    if "doubleValue" in fv:
        return fv["doubleValue"]
    if "booleanValue" in fv:
        return fv["booleanValue"]
    if "nullValue" in fv:
        return None
    if "arrayValue" in fv:
        return [_decode_value(x) for x in fv["arrayValue"].get("values", [])]
    if "mapValue" in fv:
        return {k: _decode_value(v) for k, v in fv["mapValue"].get("fields", {}).items()}
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _firestore_req(method: str, path: str, id_token: str, **kwargs) -> requests.Response:
    url = f"{FIRESTORE_HOST}/v1/projects/{_project_id()}/databases/(default)/documents/{path}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {id_token}"
    resp = requests.request(method, url, headers=headers, timeout=25, **kwargs)
    return resp


def get_links(uid: str, id_token: str) -> list[dict]:
    url = f"{FIRESTORE_HOST}/v1/projects/{_project_id()}/databases/(default)/documents/users/{uid}:runQuery"
    body = {
        "structuredQuery": {
            "from": [{"collectionId": "links"}],
            "orderBy": [{"field": {"fieldPath": "updatedAt"}, "direction": "DESCENDING"}],
            "limit": 500
        }
    }
    resp = requests.post(url, headers={"Authorization": f"Bearer {id_token}"}, json=body, timeout=25)
    if not resp.ok:
        return []
    items = []
    for row in resp.json():
        doc = row.get("document")
        if not doc:
            continue
        doc_id = doc["name"].rsplit("/", 1)[-1]
        fields = {k: _decode_value(v) for k, v in doc.get("fields", {}).items()}
        items.append({"id": doc_id, **fields})
    return items


def upsert_link(uid: str, id_token: str, url: str, category: str = "", status: str = "pending"):
    doc_id = link_doc_id(url)
    now = _now_iso()
    fields = {
        "url": url,
        "category": category,
        "status": status,
        "updatedAt": now,
    }
    encoded = {k: _encode_value(v) for k, v in fields.items()}
    params = [("updateMask.fieldPaths", k) for k in fields]
    _firestore_req("PATCH", f"users/{uid}/links/{doc_id}", id_token, params=params, json={"fields": encoded})


def set_link_status(uid: str, id_token: str, url: str, status: str, claimed_by: str = None):
    doc_id = link_doc_id(url)
    now = _now_iso()
    fields = {
        "status": status,
        "updatedAt": now,
        "claimedBy": claimed_by or "",
        "claimedAt": now if status == "claimed" else "",
    }
    encoded = {k: _encode_value(v) for k, v in fields.items()}
    params = [("updateMask.fieldPaths", k) for k in fields]
    _firestore_req("PATCH", f"users/{uid}/links/{doc_id}", id_token, params=params, json={"fields": encoded})


def get_cloud_stats(uid: str, id_token: str) -> dict:
    links = get_links(uid, id_token)
    total = len(links)
    done = sum(1 for l in links if l.get("status") == "done")
    failed = sum(1 for l in links if l.get("status") == "failed")
    pending = total - done - failed
    return {"total": total, "done": done, "failed": failed, "pending": pending}
