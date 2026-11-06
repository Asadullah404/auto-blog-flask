#!/usr/bin/env python3
"""
wordpress_publisher.py — Phase 6: WordPress REST API Publishing Engine
Handles media uploads, Gutenberg blocks, Pinterest Pin attachments,
Rank Math SEO meta, categories/tags, and idempotency.
"""

import os
import sys
import re
import json
import html
import time
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit
import requests
from requests.auth import HTTPBasicAuth

mimetypes.add_type("image/webp", ".webp")

class PublishError(Exception):
    pass

def _slugify(text, maxlen=80):
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:maxlen] or "post"

def _extract_slug_from_url(url: str, maxlen: int = 80) -> str:
    """
    Extracts the clean slug segment from a competitor / source URL.
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
        return slug[:maxlen]
    except Exception:
        return ""

def _esc_body(s):
    return html.escape(str(s or ""), quote=False)

def _esc_attr(s):
    return html.escape(str(s or ""), quote=True)

def _split_keywords(keywords, max_tags=12):
    if not keywords:
        return []
    parts = re.split(r"[,\n;|]", str(keywords))
    seen, out = set(), []
    for p in parts:
        t = p.strip()
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    return out[:max_tags]

def _format_inline_markdown(text: str) -> str:
    escaped = _esc_body(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped

def _image_block(media_id, url, alt):
    return (f'<!-- wp:image {{"id":{media_id},"sizeSlug":"large","linkDestination":"none"}} -->\n'
            f'<figure class="wp-block-image size-large">'
            f'<img src="{_esc_attr(url)}" alt="{_esc_attr(alt)}" class="wp-image-{media_id}"/>'
            f'</figure>\n<!-- /wp:image -->')

def _para_block(text):
    return f'<!-- wp:paragraph -->\n<p>{_format_inline_markdown(text)}</p>\n<!-- /wp:paragraph -->'

def _heading_block(text, level=2):
    return (f'<!-- wp:heading {{"level":{level}}} -->\n'
            f'<h{level}>{_format_inline_markdown(text)}</h{level}>\n<!-- /wp:heading -->')

def _list_block(items, ordered=False):
    tag = "ol" if ordered else "ul"
    attrs = '{"ordered":true}' if ordered else ''
    li_html = "\n".join(f"<li>{_format_inline_markdown(it.strip())}</li>" for it in items if str(it).strip())
    wp_comment = f'<!-- wp:list {attrs} -->' if attrs else '<!-- wp:list -->'
    return f'{wp_comment}\n<{tag}>\n{li_html}\n</{tag}>\n<!-- /wp:list -->'

def _render_paragraphs_to_gutenberg_blocks(paragraphs: list) -> list:
    if not paragraphs:
        return []
    if isinstance(paragraphs, str):
        paragraphs = [p.strip() for p in paragraphs.splitlines() if p.strip()] or [paragraphs]
    blocks = []
    list_items = []

    def flush_list():
        nonlocal list_items
        if list_items:
            blocks.append(_list_block(list_items))
            list_items = []

    for item in paragraphs:
        if not item:
            continue
        text = str(item).strip()
        if not text:
            continue

        if text.startswith("### ") or text.startswith("H3: ") or text.startswith("h3: "):
            flush_list()
            h_text = re.sub(r"^(###\s*|H3:\s*|h3:\s*)", "", text).strip()
            blocks.append(_heading_block(h_text, level=3))
        elif text.startswith("## ") and not text.startswith("### "):
            flush_list()
            h_text = text[3:].strip()
            blocks.append(_heading_block(h_text, level=3))
        elif text.startswith("- ") or text.startswith("* ") or text.startswith("• ") or re.match(r"^\d+\.\s+", text):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for line in lines:
                if line.startswith("- ") or line.startswith("* ") or line.startswith("• "):
                    list_items.append(line[2:].strip())
                elif re.match(r"^\d+\.\s+", line):
                    list_items.append(re.sub(r"^\d+\.\s+", "", line).strip())
                else:
                    flush_list()
                    blocks.append(_para_block(line))
        else:
            flush_list()
            if "\n-" in text or "\n*" in text or "\n•" in text:
                sub_lines = [l.strip() for l in text.splitlines() if l.strip()]
                for sline in sub_lines:
                    if sline.startswith("- ") or sline.startswith("* ") or sline.startswith("• "):
                        list_items.append(sline[2:].strip())
                    else:
                        flush_list()
                        blocks.append(_para_block(sline))
            else:
                blocks.append(_para_block(text))

    flush_list()
    return blocks

def _pin_block(url, alt, description):
    return (f'<!-- wp:html -->\n'
            f'<img src="{_esc_attr(url)}" alt="{_esc_attr(alt)}" '
            f'class="pinterest-pin-image" loading="lazy" '
            f'data-pin-description="{_esc_attr(description)}" '
            f'style="display:none">\n'
            f'<!-- /wp:html -->')

def _build_content(structured, section_media, layout_order="standard", feature_2_media=None):
    blocks = []
    intro = structured.get("intro")
    intro_items = [intro] if isinstance(intro, str) else list(intro) if intro else []
    intro_blocks = _render_paragraphs_to_gutenberg_blocks(intro_items) if intro_items else []

    feat2_block = None
    if feature_2_media:
        f2_id, f2_url, f2_alt = feature_2_media
        feat2_block = _image_block(f2_id, f2_url, f2_alt or "Secondary Feature")

    if layout_order == "intro_first":
        blocks.extend(intro_blocks)
        if feat2_block:
            blocks.append(feat2_block)
    elif layout_order == "dual_hero_split":
        blocks.extend(intro_blocks)
        if feat2_block:
            blocks.append(feat2_block)
    else:  # standard, dual_hero, heading_first
        # Order: Hero 1 (Featured) -> Hero 2 (Pinterest Pin Pasted) -> Intro -> Sections
        if feat2_block:
            blocks.append(feat2_block)
        blocks.extend(intro_blocks)

    for i, sec in enumerate(structured.get("sections", [])):
        heading = sec.get("heading", f"Section {i+1}")
        m = section_media.get(i) if isinstance(section_media, dict) else (section_media[i] if isinstance(section_media, (list, tuple)) and i < len(section_media) else None)
        img_block = _image_block(m[0], m[1], m[2] or heading) if m else None
        h_block = _heading_block(heading, level=2)
        sec_blocks = _render_paragraphs_to_gutenberg_blocks(sec.get("paragraphs", []))

        if layout_order == "heading_first":
            blocks.append(h_block)
            if img_block:
                blocks.append(img_block)
            blocks.extend(sec_blocks)
        else:  # standard / image first
            if img_block:
                blocks.append(img_block)
            blocks.append(h_block)
            blocks.extend(sec_blocks)

    concl = structured.get("conclusion")
    if isinstance(concl, dict) and concl.get("paragraphs"):
        blocks.append(_heading_block(concl.get("heading", "Conclusion"), level=2))
        concl_blocks = _render_paragraphs_to_gutenberg_blocks(concl.get("paragraphs", []))
        blocks.extend(concl_blocks)

    return "\n\n".join(blocks)



class WordPressPublisher:
    def __init__(self, config: dict = None, log_cb=None):
        config = config or {}
        base_url = config.get("base_url", "").strip().rstrip("/")
        if base_url:
            if not base_url.startswith(("http://", "https://")):
                base_url = "https://" + base_url
            elif base_url.startswith("http://") and not any(h in base_url.lower() for h in ("localhost", "127.0.0.1", "::1")):
                base_url = "https://" + base_url[len("http://"):]

        self.config = {
            "base_url": base_url,
            "username": config.get("username", "").strip(),
            "app_password": config.get("app_password", "").strip(),
            "status": config.get("status", "draft"),
            "seo_plugin": config.get("seo_plugin", "rankmath"),
            "slug_mode": config.get("slug_mode", "competitor"),
            "alt_from": config.get("alt_from", "heading"),
            "max_tags": config.get("max_tags", 12),
            "focus_keywords_max": config.get("focus_keywords_max", 5),
            "timeout": config.get("timeout", 60),
            "verify_ssl": config.get("verify_ssl", True),
            "retries": 3,
            "retry_wait": 4,
        }
        self.log_cb = log_cb or print

    def log(self, msg: str, level="info"):
        self.log_cb(f"[{level.upper()}] {msg}")

    def _auth(self):
        return HTTPBasicAuth(self.config["username"], self.config["app_password"])

    def _api(self, path):
        return f'{self.config["base_url"]}/wp-json/wp/v2/{path.lstrip("/")}'

    def _request(self, method, url, **kw):
        kw.setdefault("auth", self._auth())
        kw.setdefault("timeout", self.config["timeout"])
        kw.setdefault("verify", self.config["verify_ssl"])
        kw.setdefault("proxies", {"http": None, "https": None})
        last = None
        for attempt in range(1, self.config["retries"] + 1):
            try:
                r = requests.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{r.status_code} {r.text[:180]}")
                # Handle 301/302 redirects converting POST/PUT to GET
                if method.upper() in ("POST", "PUT", "PATCH", "DELETE") and r.history:
                    if r.request.method.upper() != method.upper():
                        target_url = r.url
                        r = requests.request(method, target_url, **kw)
                return r
            except Exception as e:
                last = e
                if attempt < self.config["retries"]:
                    time.sleep(self.config["retry_wait"])
        raise PublishError(f"{method} {url} failed: {last}")

    def check_connection(self) -> dict:
        if not self.config["base_url"] or not self.config["username"] or not self.config["app_password"]:
            raise PublishError("WordPress URL, Username, or Application Password is empty.")
        r = self._request("GET", self._api("users/me"))
        if r.status_code == 401:
            raise PublishError("401 Unauthorized — check Username & Application Password.")
        if r.status_code >= 400:
            raise PublishError(f"HTTP {r.status_code} connecting to REST API: {r.text[:160]}")
        # Detect canonical redirected URL if different
        if r.history or (r.url and r.url != self._api("users/me")):
            import urllib.parse
            parsed = urllib.parse.urlparse(r.url)
            if "/wp-json" in parsed.path:
                base_prefix = parsed.path.split("/wp-json")[0]
                detected_base = f"{parsed.scheme}://{parsed.netloc}{base_prefix}".rstrip("/")
                if detected_base and detected_base != self.config["base_url"]:
                    self.log(f"Detected canonical WordPress base URL: {detected_base}")
                    self.config["base_url"] = detected_base
        user_info = r.json()
        if isinstance(user_info, list) and user_info:
            user_info = user_info[0]
        return {
            "name": user_info.get("name", "WordPress User") if isinstance(user_info, dict) else "WordPress User",
            "id": user_info.get("id") if isinstance(user_info, dict) else None,
            "url": self.config["base_url"]
        }

    def _wp_db_init(self, db):
        db.execute("""CREATE TABLE IF NOT EXISTS wp_published
                      (url TEXT PRIMARY KEY, post_id INTEGER, post_url TEXT,
                       ts TEXT DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS wp_media
                      (local_path TEXT PRIMARY KEY, media_id INTEGER, source_url TEXT,
                       ts TEXT DEFAULT CURRENT_TIMESTAMP)""")
        db.commit()

    def _already_published(self, db, url):
        row = db.execute("SELECT post_id, post_url FROM wp_published WHERE url=?", (url,)).fetchone()
        return (row[0], row[1]) if row else None

    def _mark_published(self, db, url, post_id, post_url):
        db.execute("INSERT OR REPLACE INTO wp_published (url, post_id, post_url) VALUES (?,?,?)",
                   (url, post_id, post_url))
        db.commit()

    def _media_cached(self, db, local_path):
        row = db.execute("SELECT media_id, source_url FROM wp_media WHERE local_path=?", (str(local_path),)).fetchone()
        return (row[0], row[1]) if row else None

    def _media_save(self, db, local_path, media_id, source_url):
        db.execute("INSERT OR REPLACE INTO wp_media (local_path, media_id, source_url) VALUES (?,?,?)",
                   (str(local_path), media_id, source_url))
        db.commit()

    def _upload_media(self, db, img_path: Path, alt_text: str, title: str = None, post_id: int = None):
        img_path = Path(img_path)
        cached = self._media_cached(db, img_path)
        if cached:
            self.log(f"Media already cached on WP: {img_path.name} (id {cached[0]})")
            return cached

        ctype = mimetypes.guess_type(str(img_path))[0] or "image/jpeg"
        data = img_path.read_bytes()
        headers = {
            "Content-Disposition": f'attachment; filename="{img_path.name}"',
            "Content-Type": ctype,
        }
        r = self._request("POST", self._api("media"), headers=headers, data=data)
        if r.status_code >= 400:
            raise PublishError(f"Media upload failed for {img_path.name}: {r.status_code} {r.text[:180]}")
        obj = r.json()
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and "id" in obj[0]:
                obj = obj[0]
            else:
                raise PublishError(f"Media upload returned unexpected list structure for {img_path.name}: {str(obj)[:200]}")
        elif not isinstance(obj, dict):
            raise PublishError(f"Media upload returned unexpected response type {type(obj).__name__} for {img_path.name}")

        media_id = obj.get("id")
        if not media_id:
            raise PublishError(f"Media upload succeeded but returned no 'id' for {img_path.name}: {str(obj)[:200]}")

        upd_payload = {"alt_text": alt_text or "", "title": title or alt_text or img_path.stem}
        if post_id:
            upd_payload["post"] = post_id
        upd = self._request("POST", self._api(f"media/{media_id}"), json=upd_payload)
        upd_obj = upd.json() if upd.status_code < 400 else obj
        if isinstance(upd_obj, list) and upd_obj and isinstance(upd_obj[0], dict):
            upd_obj = upd_obj[0]
        source_url = (upd_obj if isinstance(upd_obj, dict) else obj).get("source_url", "")

        self._media_save(db, img_path, media_id, source_url)
        self.log(f"Uploaded media {img_path.name} -> ID {media_id}", "success")
        return media_id, source_url

    def _get_or_create_term(self, name: str, kind: str):
        name = (name or "").strip()
        if not name:
            return None
        r = self._request("GET", self._api(kind), params={"search": name, "per_page": 100})
        if r.status_code < 400:
            items = r.json()
            if isinstance(items, list):
                for term in items:
                    if isinstance(term, dict) and html.unescape(term.get("name", "")).strip().lower() == name.lower():
                        return term.get("id")
        c = self._request("POST", self._api(kind), json={"name": name})
        if c.status_code < 400:
            c_obj = c.json()
            if isinstance(c_obj, list) and c_obj and isinstance(c_obj[0], dict):
                c_obj = c_obj[0]
            if isinstance(c_obj, dict) and "id" in c_obj:
                return c_obj["id"]

        r2 = self._request("GET", self._api(kind), params={"per_page": 100})
        if r2.status_code < 400:
            items2 = r2.json()
            if isinstance(items2, list):
                for term in items2:
                    if isinstance(term, dict) and html.unescape(term.get("name", "")).strip().lower() == name.lower():
                        return term.get("id")
        return None

    def _rankmath_meta(self, structured: dict) -> dict:
        meta = {}
        title = structured.get("title")
        desc = structured.get("meta_description")
        kws = _split_keywords(structured.get("keywords", ""), self.config["focus_keywords_max"])
        focus = ", ".join(kws)
        if title:
            meta["rank_math_title"] = title
        if desc:
            meta["rank_math_description"] = desc
        if focus:
            meta["rank_math_focus_keyword"] = focus
        return meta

    def publish_article(self, structured: dict, rendered: dict, out_dir: Path, url: str, db):
        self._wp_db_init(db)
        out_dir = Path(out_dir)
        already = self._already_published(db, url)
        existing_post_id = already[0] if already else None
        existing_post_url = already[1] if already else None

        # Check if already published AND all media is already uploaded
        if existing_post_id:
            feat_cand = None
            if rendered.get("feature"):
                p = Path(rendered["feature"])
                feat_cand = p if p.is_absolute() else out_dir / p
                if not feat_cand.exists():
                    feat_cand = out_dir / "rendered" / p.name

            has_pending_images = False
            if feat_cand and feat_cand.exists() and not self._media_cached(db, feat_cand):
                has_pending_images = True

            sec_paths = rendered.get("sections", [])
            for raw_path in sec_paths:
                if not raw_path:
                    continue
                sp = Path(raw_path)
                scand = sp if sp.is_absolute() else out_dir / sp
                if not scand.exists():
                    scand = out_dir / "rendered" / sp.name
                if scand.exists() and not self._media_cached(db, scand):
                    has_pending_images = True
                    break

            if not has_pending_images and feat_cand and feat_cand.exists() and self._media_cached(db, feat_cand):
                self.log(f"Already fully published to WP with images (Post ID {existing_post_id}): {existing_post_url}", "info")
                return existing_post_id, existing_post_url
            elif existing_post_id:
                self.log(f"WP Post #{existing_post_id} exists but missing uploaded images. Proceeding to upload visuals and update post...", "info")

        conn = self.check_connection()
        self.log(f"Connected to WordPress as {conn['name']}", "info")

        out_dir = Path(out_dir)
        title = structured.get("title", "Untitled Article")
        meta = structured.get("meta_description", "")

        # 1. Feature image
        feat_path = None
        if rendered.get("feature"):
            p = Path(rendered["feature"])
            feat_path = p if p.is_absolute() else out_dir / p
            if not feat_path.exists():
                feat_path = out_dir / "rendered" / p.name

        featured_id = None
        if feat_path and feat_path.exists():
            featured_id, _ = self._upload_media(db, feat_path, alt_text=title, title=title)
        else:
            self.log("No feature image found for post.", "warning")

        # 1b. Feature image 2 (Dual Hero mode)
        feature_2_media = None
        if rendered.get("feature_2"):
            p2 = Path(rendered["feature_2"])
            feat2_path = p2 if p2.is_absolute() else out_dir / p2
            if not feat2_path.exists():
                feat2_path = out_dir / "rendered" / p2.name
            if feat2_path and feat2_path.exists():
                pin_alt = structured.get("pin_alt_text") or f"{title} — Pinterest Pin Visual Guide"
                f2_id, f2_url = self._upload_media(db, feat2_path, alt_text=pin_alt, title=f"{title} (Pinterest Pin)")
                feature_2_media = (f2_id, f2_url, pin_alt)

        # 2. Section images
        section_media = {}
        sec_paths = rendered.get("sections", [])
        for i, sec in enumerate(structured.get("sections", [])):
            raw_path = sec_paths[i] if i < len(sec_paths) else None
            if not raw_path:
                continue
            p = Path(raw_path)
            cand = p if p.is_absolute() else out_dir / p
            if not cand.exists():
                cand = out_dir / "rendered" / p.name
            if not cand.exists():
                continue
            alt = sec.get("heading", title) if self.config["alt_from"] == "heading" else title
            mid, murl = self._upload_media(db, cand, alt_text=alt, title=alt)
            section_media[i] = (mid, murl, alt)

        # 3. Category & Tags
        cat_id = self._get_or_create_term(structured.get("category", "Article"), "categories")
        tag_ids = []
        for kw in _split_keywords(structured.get("keywords", ""), self.config["max_tags"]):
            tid = self._get_or_create_term(kw, "tags")
            if tid:
                tag_ids.append(tid)

        # 4. Gutenberg body with Granular Layout Sequencing
        layout_order = self.config.get("post_layout_order", "standard")
        content = _build_content(structured, section_media, layout_order=layout_order, feature_2_media=feature_2_media)


        # 5. Create or Update post
        slug_mode = self.config.get("slug_mode", "competitor")
        if slug_mode == "competitor" and url:
            source_slug = _extract_slug_from_url(url)
            post_slug = source_slug or _slugify(title)
        else:
            post_slug = _slugify(title)

        payload = {
            "title": title,
            "slug": post_slug,
            "status": self.config["status"],
            "content": content,
            "excerpt": meta,
        }
        if cat_id:
            payload["categories"] = [cat_id]
        if tag_ids:
            payload["tags"] = tag_ids

        # Rank Math SEO
        rm_meta = {}
        if self.config["seo_plugin"] == "rankmath":
            rm_meta = self._rankmath_meta(structured)
            if rm_meta:
                payload["meta"] = rm_meta

        post_id = None
        post_url = ""

        # Update existing post if ID exists
        if existing_post_id:
            r = self._request("POST", self._api(f"posts/{existing_post_id}"), json=payload)
            if r.status_code < 400:
                post = r.json()
                if isinstance(post, dict):
                    post_id = post.get("id") or existing_post_id
                    post_url = post.get("link", existing_post_url)
                else:
                    post_id = existing_post_id
                    post_url = existing_post_url
                self.log(f"Updated existing WP Post #{post_id} with newly generated visuals", "success")
            else:
                self.log(f"Update of existing Post #{existing_post_id} returned {r.status_code}. Falling back to creating new post...", "warning")

        # Create new post if not updating or if update failed
        if not post_id:
            r = self._request("POST", self._api("posts"), json=payload)
            if r.status_code >= 400:
                raise PublishError(f"Post creation failed: {r.status_code} {r.text[:200]}")
            post = r.json()
            if isinstance(post, list):
                if post and isinstance(post[0], dict) and "id" in post[0]:
                    post = post[0]
                else:
                    raise PublishError(f"Post creation returned unexpected list: {str(post)[:200]}")
            elif not isinstance(post, dict):
                raise PublishError(f"Post creation returned unexpected response type {type(post).__name__}: {str(post)[:200]}")

            post_id = post.get("id")
            if not post_id:
                raise PublishError(f"Post creation succeeded but returned no 'id': {str(post)[:200]}")
            post_url = post.get("link", "")

        # 6. Set featured media in follow-up step (fixes Hostinger 500 error)
        if featured_id:
            self._request("POST", self._api(f"posts/{post_id}"), json={"featured_media": featured_id})
            self.log(f"Linked featured image ID {featured_id} to post {post_id}", "success")

        # 7. Pinterest Pin Image
        pin_path = None
        if rendered.get("pin"):
            p = Path(rendered["pin"])
            pin_path = p if p.is_absolute() else out_dir / p
            if not pin_path.exists():
                pin_path = out_dir / "rendered" / p.name

        if pin_path and pin_path.exists():
            pin_id, pin_url = self._upload_media(db, pin_path, alt_text=title, title=title, post_id=post_id)
            pin_html = _pin_block(pin_url, title, meta or title)
            self._request("POST", self._api(f"posts/{post_id}"), json={"content": content + "\n\n" + pin_html})
            self.log(f"Attached Pinterest Pin media {pin_id} to post body", "success")

        # Self-test Rank Math
        if rm_meta:
            saved = post.get("meta") or {}
            if not saved.get("rank_math_description"):
                self.log("Rank Math meta not saved. Ensure rank-math-rest-meta.php is in wp-content/mu-plugins/", "warning")
            else:
                self.log("Rank Math SEO meta successfully saved.", "success")

        self._mark_published(db, url, post_id, post_url)
        self.log(f"PUBLISHED -> {post_url}", "success")
        return post_id, post_url
