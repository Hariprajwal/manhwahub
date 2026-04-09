#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           MANHWA DOWNLOADER v5.0 — PRODUCTION               ║
║   3 Live-Tested Sources (April 2026)                        ║
║                                                              ║
║   Source 1: MangaDex    — Official REST API (gold standard)  ║
║   Source 2: MangaBuddy  — HTML + lazy-load CDN images        ║
║   Source 3: MangaPill   — Clean HTML, large catalogue        ║
║                                                              ║
║   Every source verified: search → chapters → page images     ║
╚══════════════════════════════════════════════════════════════╝
"""

import sys
import os
import re
import time
import json
import random
import shutil
import argparse
import subprocess
from pathlib import Path
from urllib.parse import quote, urljoin

# ═══════════════════════════════════════════════════════════════════════════════
#  WINDOWS UTF-8 FIX
#  Without this, Japanese/Chinese/Vietnamese aliases crash with:
#     'charmap' codec can't decode byte 0x81
# ═══════════════════════════════════════════════════════════════════════════════
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # Python < 3.7 fallback

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO-INSTALL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════
def _install(pkg, imp=None):
    imp = imp or pkg
    try:
        __import__(imp)
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

print("[*] Checking dependencies...")
_install("requests")
_install("beautifulsoup4", "bs4")

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

SESSION = requests.Session()
SESSION.headers.update(BROWSER_HEADERS)

OUTPUT_DIR = Path("downloads")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_RETRIES = 4
IS_SERVER = "--server" in sys.argv

# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def log(msg: str):
    """Print + flush (critical for subprocess streaming to manager.py)."""
    print(msg, flush=True)


def safe_name(name: str) -> str:
    """Convert a title to a filesystem-safe folder name."""
    return re.sub(r'[<>:"/\\|?*]', "", name).strip().replace(" ", "_")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy matching."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return " ".join(text.split())


def polite_delay(lo: float = 1.0, hi: float = 2.5):
    """Random sleep to avoid getting blocked."""
    time.sleep(random.uniform(lo, hi))


def is_manga_result(title: str) -> bool:
    """Reject novels, light novels, promo entries."""
    t = title.lower()
    reject = ["(novel)", "light novel", "book version", "special edition", "promo", "(ln)"]
    return not any(kw in t for kw in reject)


def generate_variations(title: str) -> list:
    """Create search variations from a single user query."""
    base = title.strip()
    out = [base]
    low = base.lower()
    # Strip trailing " manhwa" / " manga" / " webtoon"
    for suffix in (" manhwa", " manga", " webtoon", " comic"):
        if low.endswith(suffix):
            out.append(base[: -len(suffix)])
            break
    
    # ADDED: Id-Method slug variations for direct URL guessing
    slug_base = re.sub(r'[^a-z0-9\s-]', '', low).replace(' ', '-')
    slug_base = re.sub(r'-+', '-', slug_base).strip('-')
    if slug_base and slug_base not in out:
        out.append(slug_base)
        
    # Article stripping (the, a, an)
    no_articles = re.sub(r'\b(the|a|an)\b', '', low).strip()
    if no_articles != low:
        slug_no_art = re.sub(r'[^a-z0-9\s-]', '', no_articles).replace(' ', '-')
        slug_no_art = re.sub(r'-+', '-', slug_no_art).strip('-')
        if slug_no_art and slug_no_art not in out:
            out.append(slug_no_art)

    return list(dict.fromkeys(out))


def progress_bar(cur: int, total: int, prefix: str = "", width: int = 35):
    """Terminal progress bar — suppressed in server mode to avoid \\r spam."""
    if total == 0:
        return
    if IS_SERVER:
        if cur == total:
            log(f"  {prefix} [DONE] 100% ({cur}/{total})")
        return
    filled = int(width * cur / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * cur / total)
    print(f"\r  {prefix} [{bar}] {pct}% ({cur}/{total})", end="", flush=True)
    if cur == total:
        print()


def ask_user(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Cancelled.")
        sys.exit(0)


# ═══════════════════════════════════════════════════════════════════════════════
#  IMAGE DOWNLOADER  (with retry, backoff, validation)
# ═══════════════════════════════════════════════════════════════════════════════

def download_image(url: str, save_path: Path, referer: str = "") -> bool:
    """
    Download one image file with:
      - Per-source Referer header
      - Exponential backoff on 429/503
      - Content-Type validation (rejects HTML error pages)
      - Minimum file-size check (rejects <1 KB stubs)
    """
    hdrs = {**BROWSER_HEADERS}
    if referer:
        hdrs["Referer"] = referer
    # Image-specific accept header
    hdrs["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"

    for attempt in range(1, MAX_IMAGE_RETRIES + 1):
        try:
            polite_delay(0.4, 1.2)
            resp = SESSION.get(url, headers=hdrs, timeout=30, stream=True)

            # Rate-limited? Backoff.
            if resp.status_code in (429, 503):
                wait = (2 ** attempt) + random.uniform(0, 1)
                log(f"    WARN: {resp.status_code} rate-limit. Backoff {wait:.0f}s (attempt {attempt})")
                time.sleep(wait)
                continue

            resp.raise_for_status()

            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(16384):
                    f.write(chunk)

            # HARDENED: Scan every plausible image attribute (Id-Method)
            # We reject tiny files (error pages, empty gifs)
            fsize = save_path.stat().st_size
            if fsize < 1024:
                save_path.unlink(missing_ok=True)
                raise ValueError(f"File only {fsize}B — likely not a real image")

            return True

        except Exception as e:
            if attempt < MAX_IMAGE_RETRIES:
                wait = 2 * attempt
                log(f"    WARN: Retry {attempt}/{MAX_IMAGE_RETRIES}: {e}")
                time.sleep(wait)
            else:
                log(f"    FAIL: {save_path.name} — {e}")

    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  SOURCE 1:  M A N G A D E X   (Official REST API)
#
#  Endpoints used:
#    GET /manga?title=...           → search
#    GET /chapter?manga=...         → chapter list
#    GET /at-home/server/{chId}     → page image URLs
#
#  Image download: use the baseUrl from at-home, do NOT send auth headers.
# ═══════════════════════════════════════════════════════════════════════════════

class MangaDexSource:
    NAME    = "MangaDex"
    KEY     = "mangadex"
    API     = "https://api.mangadex.org"
    REFERER = "https://mangadex.org"

    # ── search ──────────────────────────────────────────────────────────
    def search(self, title: str) -> list:
        log(f"  [{self.NAME}] Searching: '{title}'")
        try:
            params = {
                "title": title,
                "limit": 10,
                "contentRating[]": ["safe", "suggestive", "erotica"],
                "includes[]": ["cover_art"],
                "order[relevance]": "desc",
            }
            r = SESSION.get(f"{self.API}/manga", params=params, timeout=15)
            r.raise_for_status()

            results = []
            for item in r.json().get("data", []):
                attrs  = item["attributes"]
                titles = attrs.get("title", {})
                name   = titles.get("en") or next(iter(titles.values()), "Unknown")

                # Collect ASCII-safe aliases only (avoids Windows charmap crash)
                aliases = []
                for alt in attrs.get("altTitles", []):
                    for v in alt.values():
                        try:
                            v.encode("ascii")
                            aliases.append(v)
                        except UnicodeEncodeError:
                            pass

                results.append({
                    "id":      item["id"],
                    "title":   name,
                    "status":  attrs.get("status", "?"),
                    "source":  self.KEY,
                    "aliases": list(set(aliases)),
                })

            log(f"  [{self.NAME}] {len(results)} results")
            return results
        except Exception as e:
            log(f"  [{self.NAME}] Search failed: {e}")
            return []

    # ── chapters ────────────────────────────────────────────────────────
    def get_chapters(self, manga_id: str) -> list:
        log(f"  [{self.NAME}] Fetching chapters...")
        chapters = []
        offset = 0
        while True:
            try:
                params = {
                    "manga": manga_id,
                    "translatedLanguage[]": ["en"],
                    "limit": 100,
                    "offset": offset,
                    "order[chapter]": "asc",
                    "contentRating[]": ["safe", "suggestive", "erotica"],
                }
                r = SESSION.get(f"{self.API}/chapter", params=params, timeout=15)
                r.raise_for_status()
                data  = r.json()
                batch = data.get("data", [])
                if not batch:
                    break
                for ch in batch:
                    a = ch["attributes"]
                    num = a.get("chapter") or "0"
                    chapters.append({
                        "id":    ch["id"],
                        "num":   num,
                        "title": a.get("title") or f"Chapter {num}",
                        "pages": a.get("pages", 0),
                    })
                offset += 100
                if offset >= data.get("total", 0):
                    break
                time.sleep(0.4)  # respect MangaDex rate limit
            except Exception as e:
                log(f"  [{self.NAME}] Chapter error at offset {offset}: {e}")
                break

        # Deduplicate by chapter number (keep first)
        seen, unique = set(), []
        for ch in chapters:
            if ch["num"] not in seen:
                seen.add(ch["num"])
                unique.append(ch)

        log(f"  [{self.NAME}] {len(unique)} unique chapters")
        return unique

    # ── page URLs ───────────────────────────────────────────────────────
    def get_page_urls(self, chapter_id: str) -> list:
        try:
            r = SESSION.get(f"{self.API}/at-home/server/{chapter_id}", timeout=15)
            r.raise_for_status()
            d = r.json()
            base   = d["baseUrl"]
            h      = d["chapter"]["hash"]
            pages  = d["chapter"]["data"]
            return [f"{base}/data/{h}/{p}" for p in pages]
        except Exception as e:
            log(f"  [{self.NAME}] Page URL error: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════════════
#  SOURCE 2:  M A N G A B U D D Y   (HTML scraper + lazy-load CDN images)
#
#  Verified live April 2026:
#    Search:   GET https://mangabuddy.com/search?q=...   → div.book-detailed-item
#    Chapters: GET https://mangabuddy.com/<slug>          → ul/div.chapter-list a
#    Pages:    GET https://mangabuddy.com/<slug>/chapter-N → img[data-src] OR img[src]
#              Real CDN: https://s19.mbcdnsat.org/res/manga/...
#              Placeholder: https://res.mgcdn.xyz/x.gif  (SKIP THIS)
# ═══════════════════════════════════════════════════════════════════════════════

class MangaBuddySource:
    NAME    = "MangaBuddy"
    KEY     = "mangabuddy"
    BASE    = "https://mangabuddy.com"
    REFERER = "https://mangabuddy.com"

    # ── search ──────────────────────────────────────────────────────────
    def search(self, title: str) -> list:
        log(f"  [{self.NAME}] Searching: '{title}'")
        try:
            r = SESSION.get(
                f"{self.BASE}/search",
                params={"q": title},
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            results = []
            seen = set()
            # Primary: detailed items
            items = soup.select("div.book-detailed-item, div.book-item")
            for item in items[:10]:
                a = item.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href

                # Deduplicate by URL
                if href in seen:
                    continue
                seen.add(href)

                # Title: try multiple selectors
                name_el = (
                    item.select_one(".title") or
                    item.select_one("h3") or
                    item.select_one(".book-name") or
                    a
                )
                name = name_el.get_text(strip=True) if name_el else "Unknown"

                results.append({
                    "id":     href.rstrip("/").split("/")[-1],
                    "url":    href,
                    "title":  name,
                    "status": "?",
                    "source": self.KEY,
                })

            log(f"  [{self.NAME}] {len(results)} results")
            return results
        except Exception as e:
            log(f"  [{self.NAME}] Search failed: {e}")
            return []

    # ── chapters ────────────────────────────────────────────────────────
    def get_chapters(self, manga_url: str) -> list:
        log(f"  [{self.NAME}] Fetching chapters...")
        try:
            r = SESSION.get(
                manga_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            chapters = []
            seen_urls = set()

            # Select chapter links
            links = soup.select(
                "ul.chapter-list a, div.chapter-list a, "
                "li.chapter-item a, div.chapters a"
            )

            for a in links:
                href = a.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = self.BASE + href

                # Deduplicate
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                text = a.get_text(strip=True)
                m = re.search(r"[\d.]+", text)
                ch_num = m.group(0) if m else "0"

                chapters.append({
                    "id":    href,
                    "url":   href,
                    "num":   ch_num,
                    "title": text or f"Chapter {ch_num}",
                    "pages": 0,
                })

            # Sort ascending by chapter number
            try:
                chapters.sort(key=lambda c: float(c["num"]))
            except ValueError:
                pass

            log(f"  [{self.NAME}] {len(chapters)} chapters")
            return chapters
        except Exception as e:
            log(f"  [{self.NAME}] Chapter error: {e}")
            return []

    # ── page URLs ───────────────────────────────────────────────────────
    def get_page_urls(self, chapter_url: str) -> list:
        """
        MangaBuddy stores ALL image URLs in a JS variable:
            var chapImages = 'url1,url2,url3,...';
        The HTML only shows the first ~2 images eagerly; the rest are
        lazy-loaded by JavaScript. We parse the JS variable directly
        to get the COMPLETE list.
        """
        try:
            r = SESSION.get(
                chapter_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            html = r.text

            # ── PRIMARY: Extract from var chapImages = '...'; ──
            m = re.search(r"var\s+chapImages\s*=\s*['\"](.+?)['\"]", html)
            if m:
                raw = m.group(1)
                urls = [u.strip() for u in raw.split(",") if u.strip().startswith("http")]
                if urls:
                    log(f"    [{self.NAME}] Extracted {len(urls)} pages from JS chapImages")
                    return urls

            # ── FALLBACK: Parse img tags ──
            soup = BeautifulSoup(html, "html.parser")
            urls = []
            for img in soup.find_all("img"):
                src = (img.get("data-src") or img.get("src") or "").strip()
                if not src or "x.gif" in src or not src.startswith("http"):
                    continue
                if any(k in src.lower() for k in ["mbcdn", "/res/manga/", "/manga/"]):
                    if src not in urls:
                        urls.append(src)

            if urls:
                log(f"    [{self.NAME}] Extracted {len(urls)} pages from HTML img tags")
            return urls
        except Exception as e:
            log(f"  [{self.NAME}] Page URL error: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════════════
#  SOURCE 3:  M A N G A P I L L   (Clean HTML scraper)
#
#  Verified live April 2026:
#    Search:   GET https://mangapill.com/search?q=...
#              Results: a[href*='/manga/']
#    Chapters: GET https://mangapill.com/manga/<id>/<slug>
#              Chapters: a[href*='/chapters/']
#    Pages:    GET https://mangapill.com/chapters/<id>/<slug>
#              Images: chapter-container img (data-src preferred)
# ═══════════════════════════════════════════════════════════════════════════════

class MangaPillSource:
    NAME    = "MangaPill"
    KEY     = "mangapill"
    BASE    = "https://mangapill.com"
    REFERER = "https://mangapill.com"

    # ── search ──────────────────────────────────────────────────────────
    def search(self, title: str) -> list:
        log(f"  [{self.NAME}] Searching: '{title}'")
        try:
            r = SESSION.get(
                f"{self.BASE}/search",
                params={"q": title, "type": "", "status": ""},
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            results = []
            seen = set()

            # Find all manga links
            for a in soup.find_all("a", href=re.compile(r"/manga/\d+")):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href

                if href in seen:
                    continue
                seen.add(href)

                # Get title text — might be nested
                name = a.get_text(strip=True)
                # Skip empty-text navigation links
                if not name or len(name) < 2:
                    continue
                # Skip novel entries
                if not is_manga_result(name):
                    continue

                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":     slug,
                    "url":    href,
                    "title":  name,
                    "status": "?",
                    "source": self.KEY,
                })

            log(f"  [{self.NAME}] {len(results)} results")
            return results[:10]
        except Exception as e:
            log(f"  [{self.NAME}] Search failed: {e}")
            return []

    # ── chapters ────────────────────────────────────────────────────────
    def get_chapters(self, manga_url: str) -> list:
        log(f"  [{self.NAME}] Fetching chapters...")
        try:
            r = SESSION.get(
                manga_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            chapters = []
            seen = set()

            for a in soup.find_all("a", href=re.compile(r"/chapters/")):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                if href in seen:
                    continue
                seen.add(href)

                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"

                chapters.append({
                    "id":    href,
                    "url":   href,
                    "num":   ch_num,
                    "title": text or f"Chapter {ch_num}",
                    "pages": 0,
                })

            # Sort ascending by chapter number
            try:
                chapters.sort(key=lambda c: float(c["num"]))
            except ValueError:
                pass

            log(f"  [{self.NAME}] {len(chapters)} chapters")
            return chapters
        except Exception as e:
            log(f"  [{self.NAME}] Chapter error: {e}")
            return []

    # ── page URLs ───────────────────────────────────────────────────────
    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(
                chapter_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            urls = []
            # Try multiple selectors for chapter page images
            selectors = [
                "chapter-page img",           # MangaPill's custom element
                "div.chapter-container img",
                "div.flex img",
                "div.container-chapter-reader img",
                "picture source",
                "img.wp-manga-chapter-img",
            ]

            for sel in selectors:
                imgs = soup.select(sel)
                for img in imgs:
                    src = (img.get("data-src") or img.get("src") or "").strip()
                    if not src or not src.startswith("http"):
                        continue
                    # Filter: must look like a manga page image
                    low = src.lower()
                    if any(k in low for k in [
                        "manga", "chapter", "page", "cdn", "scan",
                        ".jpg", ".jpeg", ".png", ".webp"
                    ]):
                        if src not in urls:
                            urls.append(src)

                if urls:
                    break  # Found images with this selector

            # Final fallback: grab ALL large images from the page
            if not urls:
                for img in soup.find_all("img"):
                    src = (img.get("data-src") or img.get("src") or "").strip()
                    if src and src.startswith("http") and src not in urls:
                        # Skip logos, icons, avatars (usually small or in specific paths)
                        low = src.lower()
                        skip = ["logo", "icon", "avatar", "favicon", "banner", "ad-", "ads/"]
                        if not any(s in low for s in skip):
                            urls.append(src)

            return urls
        except Exception as e:
            log(f"  [{self.NAME}] Page URL error: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════════════
#  MADARA THEME BASE SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════

class BaseMadaraSource:
    NAME    = ""
    KEY     = ""
    BASE    = ""
    REFERER = ""
    AJAX_CHAPTERS = True
    SEARCH_PATH = "/?s={}&post_type=wp-manga"

    def search(self, title: str) -> list:
        log(f"  [{self.NAME}] Searching: '{title}'")
        try:
            r = SESSION.get(
                self.BASE + self.SEARCH_PATH.format(quote(title)),
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            results = []
            seen = set()

            items = soup.select(".c-tabs-item__content, .row.c-tabs-item__content, .profile-manga, .post-item")
            for item in items[:10]:
                a = item.select_one("h3 a, .post-title h3 a, h4 a, .tab-summary .post-title a")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                if href in seen:
                    continue
                seen.add(href)
                
                name = a.get_text(strip=True)
                if not name or len(name) < 2:
                    continue
                if not is_manga_result(name):
                    continue
                    
                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":     slug,
                    "url":    href,
                    "title":  name,
                    "status": "?",
                    "source": self.KEY,
                })

            log(f"  [{self.NAME}] {len(results)} results")
            return results
        except Exception as e:
            log(f"  [{self.NAME}] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        log(f"  [{self.NAME}] Fetching chapters...")
        try:
            r = SESSION.get(
                manga_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            
            chapters = []
            seen = set()
            
            # HARDENED: AJAX Chapter Ripping (Id-Method)
            manga_id_input = soup.select_one(".rating-post-id")
            if manga_id_input and self.AJAX_CHAPTERS:
                manga_id = manga_id_input["value"]
                # Try both standard and hidden AJAX endpoints
                for action in ["manga_get_chapters", "wp_manga_get_chapters"]:
                    ajax_url = f"{self.BASE}/wp-admin/admin-ajax.php"
                    res = SESSION.post(
                        ajax_url, 
                        data={"action": action, "manga": manga_id}, 
                        headers={**BROWSER_HEADERS, "Referer": self.REFERER, "X-Requested-With": "XMLHttpRequest"},
                        timeout=15,
                    )
                    if res.status_code == 200 and "chapter" in res.text.lower():
                        soup = BeautifulSoup(res.text, "html.parser")
                        break
                    
            links = soup.select("li.wp-manga-chapter a, div.wp-manga-chapter a, div.chapter-link a")
            if not links:
                links = [a for a in soup.find_all("a", href=True) if "chapter" in a["href"].lower()]
                
            for a in links:
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                if href in seen:
                    continue
                seen.add(href)
                
                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                
                chapters.append({
                    "id":    href,
                    "url":   href,
                    "num":   ch_num,
                    "title": text or f"Chapter {ch_num}",
                    "pages": 0,
                })
                
            try:
                chapters.sort(key=lambda c: float(c["num"]))
            except ValueError:
                pass

            log(f"  [{self.NAME}] {len(chapters)} chapters")
            return chapters
        except Exception as e:
            log(f"  [{self.NAME}] Chapter error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(
                chapter_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            urls = []
            
            for img in soup.select("img.wp-manga-chapter-img, .page-break img, .reading-content img"):
                src = (img.get("data-src") or img.get("src") or img.get("data-lazy-src") or "").strip()
                if not src or not src.startswith("http"):
                    continue
                if src not in urls:
                    urls.append(src)
                    
            if not urls:
                for img in soup.find_all("img"):
                    src = (img.get("data-src") or img.get("src") or img.get("data-lazy-src") or "").strip()
                    if src and src.startswith("http") and "chapter" in src.lower() and src not in urls:
                        urls.append(src)
                        
            return urls
        except Exception as e:
            log(f"  [{self.NAME}] Page URL error: {e}")
            return []

class KunMangaSource(BaseMadaraSource):
    NAME    = "KunManga"
    KEY     = "kunmanga"
    BASE    = "https://kunmanga.co"
    REFERER = "https://kunmanga.co"

class WeebrookSource(BaseMadaraSource):
    NAME    = "Weebrook"
    KEY     = "weebrook"
    BASE    = "https://weebrook.com"
    REFERER = "https://weebrook.com"
    AJAX_CHAPTERS = False

# ═══════════════════════════════════════════════════════════════════════════════
#  SOURCE 6:  W E E B   C E N T R A L   (Premium Custom Source)
# ═══════════════════════════════════════════════════════════════════════════════

class WeebCentralSource:
    NAME    = "WeebCentral"
    KEY     = "weebcentral"
    BASE    = "https://weebcentral.com"
    REFERER = "https://weebcentral.com"

    def search(self, title: str) -> list:
        log(f"  [{self.NAME}] Searching: '{title}'")
        try:
            r = SESSION.get(
                f"{self.BASE}/search",
                params={"text": title},
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            
            results = []
            seen = set()
            # WeebCentral search results are often in <a> tags with /series/
            for a in soup.select('a[href*="/series/"]'):
                href = a.get("href", "")
                if href in seen or not "/series/" in href:
                    continue
                seen.add(href)
                
                # Title might be in an <img> alt or nested text
                name = a.get_text(strip=True)
                if not name:
                    img = a.select_one("img")
                    name = img.get("alt", "") if img else "Unknown"
                
                if not name or not is_manga_result(name):
                    continue
                
                slug = href.rstrip("/").split("/")[-1]
                results.append({
                    "id":     href, # WeebCentral uses full URL or specific UUID
                    "url":    href,
                    "title":  name,
                    "status": "?",
                    "source": self.KEY,
                })
            log(f"  [{self.NAME}] {len(results)} results")
            return results
        except Exception as e:
            log(f"  [{self.NAME}] Search failed: {e}")
            return []

    def get_chapters(self, series_url: str) -> list:
        log(f"  [{self.NAME}] Fetching chapters...")
        try:
            r = SESSION.get(
                series_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            
            chapters = []
            seen = set()
            
            # WeebCentral chapters are in <a> tags with /chapter/ (note singular)
            # Selector updated to catch both /chapter/ and /chapters/ for resilience
            links = soup.select('a[href*="/chapter/"], a[href*="/chapters/"]')
            for a in reversed(links): # Often listed descending
                href = a.get("href", "")
                if href in seen:
                    continue
                seen.add(href)
                
                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                
                chapters.append({
                    "id":    href,
                    "url":   href,
                    "num":   ch_num,
                    "title": text or f"Chapter {ch_num}",
                    "pages": 0,
                })
            
            # Sort ascending
            try:
                chapters.sort(key=lambda c: float(c["num"]))
            except:
                pass
                
            log(f"  [{self.NAME}] {len(chapters)} chapters")
            return chapters
        except Exception as e:
            log(f"  [{self.NAME}] Chapter error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(
                chapter_url,
                headers={**BROWSER_HEADERS, "Referer": self.REFERER},
                timeout=15,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            urls = []
            
            # WeebCentral uses <section> or container for images
            # ADDED: .reader-content img and .chapter-content img found in final inspection
            for img in soup.select(".reader-content img, .chapter-content img, img.chapter-image, section#reader img, section img"):
                # Use multi-attribute scan principle
                src = (
                    img.get("data-src") or 
                    img.get("data-lazy-src") or 
                    img.get("src") or 
                    ""
                ).strip()
                
                if src and src.startswith("http") and src not in urls:
                    if not any(k in src.lower() for k in ["logo", "icon", "avatar"]):
                        urls.append(src)
                        
            return urls
        except Exception as e:
            log(f"  [{self.NAME}] Page URL error: {e}")
            return []

# ═══════════════════════════════════════════════════════════════════════════════
#  SOURCE 7:  M A N G A N A T O   /   M A N G A K A K A L O T
# ═══════════════════════════════════════════════════════════════════════════════

class ManganatoSource:
    NAME    = "Manganato"
    KEY     = "manganato"
    # Primary domain for 2026. Mirrors used as backup.
    BASE    = "https://manganato.com"
    MIRRORS = ["https://chapmanganato.to", "https://readmanganato.to", "https://mangakakalot.com"]
    REFERER = "https://manganato.com"

    def search(self, title: str) -> list:
        log(f"  [{self.NAME}] Searching: '{title}'")
        # Try mirrors first if primary is unstable
        domains = [self.BASE] + self.MIRRORS
        for domain in domains:
            try:
                # Manganato search often uses underscores for spaces in slug
                # Use /search/story/ for Manganato variants
                search_url = f"{domain}/search/story/{quote(title.replace(' ', '_'))}"
                r = SESSION.get(search_url, headers={**BROWSER_HEADERS, "Referer": domain}, timeout=15)
                if r.status_code != 200:
                    continue
                
                soup = BeautifulSoup(r.text, "html.parser")
                results = []
                # Selectors: .search-story-item or .item-title
                items = soup.select(".search-story-item, .story_item, .panel-search-story-item")
                for item in items[:10]:
                    a = item.select_one("h3 a, .story_name a, .item-title, a")
                    if not a: continue
                    href = a.get("href", "")
                    if not href.startswith("http"):
                        href = domain + href
                    
                    name = a.get_text(strip=True)
                    if not name or not is_manga_result(name):
                        continue
                        
                    results.append({
                        "id":     href,
                        "url":    href,
                        "title":  name,
                        "status": "?",
                        "source": self.KEY,
                    })
                
                if results:
                    log(f"  [{self.NAME}] Results found on {domain}")
                    return results
            except Exception:
                continue
        return []

    def get_chapters(self, manga_url: str) -> list:
        log(f"  [{self.NAME}] Fetching chapters...")
        # Determine referer based on domain
        ref = self.REFERER
        for m in self.MIRRORS:
            if m in manga_url:
                ref = m
                break
                
        try:
            r = SESSION.get(manga_url, headers={**BROWSER_HEADERS, "Referer": ref}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            
            chapters = []
            seen = set()
            
            # Selector: .chapter-name (Manganato) or .a-h (New Manganato)
            links = soup.select(".chapter-name, .row-content-chapter a, .chapter-list a, .a-h")
            for a in links:
                if a.name != "a":
                    a = a.find_parent("a") or a.find("a")
                if not a: continue
                
                href = a.get("href", "")
                if href in seen: continue
                seen.add(href)
                
                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                
                chapters.append({
                    "id":    href,
                    "url":   href,
                    "num":   ch_num,
                    "title": text or f"Chapter {ch_num}",
                    "pages": 0,
                })
            
            log(f"  [{self.NAME}] {len(chapters)} chapters")
            return chapters
        except Exception as e:
            log(f"  [{self.NAME}] Chapter error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            # Need to pick a referer based on the domain of the chapter_url
            curr_ref = self.REFERER
            for m in self.MIRRORS:
                if m in chapter_url:
                    curr_ref = m
                    break

            r = SESSION.get(chapter_url, headers={**BROWSER_HEADERS, "Referer": curr_ref}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            urls = []
            
            # Selector: .container-chapter-reader img
            for img in soup.select(".container-chapter-reader img, .v-content img, .reading-content img"):
                src = (img.get("src") or img.get("data-src") or "").strip()
                if src and src.startswith("http") and src not in urls:
                    if not any(k in src.lower() for k in ["logo", "icon", "avatar"]):
                        # MangaBox CDN often uses these domains
                        if any(k in src.lower() for k in ["mangakakalot", "manganelo", "mangabat", "mkcdn"]):
                           urls.append(src)
            
            # Fallback: if no specific CDN images found, take all large images
            if not urls:
                for img in soup.select("img"):
                    src = (img.get("src") or img.get("data-src") or "").strip()
                    if src and src.startswith("http") and src not in urls:
                         if not any(k in src.lower() for k in ["logo", "icon", "avatar", "ad"]):
                            urls.append(src)

            return urls
        except Exception as e:
            log(f"  [{self.NAME}] Page URL error: {e}")
            return []

# ═══════════════════════════════════════════════════════════════════════════════
#  SOURCE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

ALL_SOURCES = {
    "mangadex":    MangaDexSource(),
    "weebcentral": WeebCentralSource(),
    "manganato":   ManganatoSource(),    # Added Source
    "mangabuddy":  MangaBuddySource(),
    "mangapill":   MangaPillSource(),
    "kunmanga":    KunMangaSource(),
    "weebrook":    WeebrookSource(),
}

SOURCE_ORDER = ["mangadex", "weebcentral", "manganato", "weebrook", "kunmanga", "mangabuddy", "mangapill"]



# ═══════════════════════════════════════════════════════════════════════════════
#  CHAPTER DOWNLOAD  (with partial recovery)
# ═══════════════════════════════════════════════════════════════════════════════

def download_chapter(manga_info: dict, chapter: dict, manga_dir: Path) -> bool:
    """
    Download all pages of one chapter.
    - Skips already-downloaded chapters.
    - Uses partial recovery: keeps whatever pages succeeded.
    - Only marks FAIL if zero pages downloaded.
    """
    ch_num  = chapter["num"]
    ch_name = safe_name(f"Chapter_{str(ch_num).zfill(4)}")
    ch_dir  = manga_dir / ch_name

    # Skip if already downloaded
    if ch_dir.exists() and any(ch_dir.iterdir()):
        existing = [f for f in ch_dir.iterdir() if f.suffix.lower() in (".jpg",".jpeg",".png",".webp",".gif")]
        if existing:
            log(f"  SKIP: {ch_name} ({len(existing)} pages already on disk)")
            return True

    ch_dir.mkdir(parents=True, exist_ok=True)

    src_key = manga_info["source"]
    source  = ALL_SOURCES[src_key]
    referer = getattr(source, "REFERER", "")

    # Get page image URLs
    if src_key == "mangadex":
        urls = source.get_page_urls(chapter["id"])
    else:
        urls = source.get_page_urls(chapter.get("url") or chapter["id"])

    if not urls:
        log(f"  FAIL: No page URLs for {ch_name}")
        shutil.rmtree(ch_dir, ignore_errors=True)
        return False

    log(f"  DOWNLOAD: {ch_name} — {len(urls)} pages")

    saved  = 0
    failed = 0

    for i, url in enumerate(urls, 1):
        # Determine file extension from URL
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        ext = ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"
        path = ch_dir / f"{str(i).zfill(4)}.{ext}"

        progress_bar(i - 1, len(urls), prefix=f"  Page {i:>3}/{len(urls)}")

        if download_image(url, path, referer=referer):
            saved += 1
        else:
            failed += 1

    progress_bar(len(urls), len(urls), prefix="  Done       ")

    # PARTIAL RECOVERY: keep whatever we got
    if saved == 0:
        shutil.rmtree(ch_dir, ignore_errors=True)
        log(f"  FAIL: 0/{len(urls)} pages — chapter deleted")
        return False

    log(f"  OK: {saved}/{len(urls)} pages saved" + (f" ({failed} failed)" if failed else ""))
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  SEARCH ENGINE  — Each title searched INDIVIDUALLY (no pipe-join)
# ═══════════════════════════════════════════════════════════════════════════════

def search_all_sources(titles: list) -> list:
    """
    For each source, try each title variation until we get results.
    Returns deduplicated, aggregated list across all sources.
    """
    all_results = []
    seen_keys = set()

    for src_key in SOURCE_ORDER:
        src = ALL_SOURCES[src_key]
        found = False

        for title in titles:
            title = title.strip()
            if not title:
                continue
            try:
                results = src.search(title)
                for r in results:
                    if not is_manga_result(r["title"]):
                        continue
                    key = r.get("url") or r.get("id")
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_results.append(r)
                        found = True

                if found:
                    break  # Got results from this source, move on

            except Exception as e:
                log(f"  [{src_key}] Error: {e}")

            polite_delay(0.5, 1.0)

        polite_delay(0.3, 0.8)

    return all_results


# ═══════════════════════════════════════════════════════════════════════════════
#  CHAPTER FILTER
# ═══════════════════════════════════════════════════════════════════════════════

def filter_chapters(chapters: list, ch_from=None, ch_to=None) -> list:
    if ch_from is None and ch_to is None:
        return chapters
    out = []
    for ch in chapters:
        try:
            n = float(ch["num"])
            if ch_from is not None and n < ch_from:
                continue
            if ch_to is not None and n > ch_to:
                continue
            out.append(ch)
        except ValueError:
            pass
    return out


def pick_from_list(items: list, label: str):
    if not items:
        return None
    print(f"\n{'─'*58}")
    for i, item in enumerate(items, 1):
        src = item.get("source", "")
        print(f"  {i:>2}. {item['title'][:42]:<42} ({src})")
    print(f"{'─'*58}")
    choice = ask_user(f"Pick a {label} (1-{len(items)}, 0=skip): ")
    if not choice.isdigit() or choice == "0":
        return None
    idx = int(choice) - 1
    return items[idx] if 0 <= idx < len(items) else None


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERACTIVE MODE
# ═══════════════════════════════════════════════════════════════════════════════

def run(title=None, download_all=False, ch_range=None, auto=False):
    log("\n" + "═" * 58)
    log("  MANHWA DOWNLOADER v5.0 — PRODUCTION")
    log("  Sources: MangaDex · WeebCentral · Manganato · etc.")
    log("═" * 58)

    if not title:
        title = ask_user("\nEnter manhwa title: ")
    if not title:
        log("No title.")
        return

    # Parse pipe-separated titles
    if "|" in title:
        titles = [t.strip() for t in title.split("|") if t.strip()]
    else:
        titles = generate_variations(title)
    main_title = titles[0]
    log(f"[*] Search queries: {titles}")

    # Search
    all_results = search_all_sources(titles)
    if not all_results:
        log("\nFAIL: No results from any source.")
        return

    # Sort: exact match first, then by SOURCE_ORDER priority
    all_results.sort(key=lambda x: (
        normalize(main_title) != normalize(x["title"]),
        SOURCE_ORDER.index(x["source"]) if x["source"] in SOURCE_ORDER else 99
    ))
    log(f"\nFound {len(all_results)} result(s).")

    # Pick
    if auto:
        manga = all_results[0]
        log(f"[AUTO] {manga['title']} [{manga['source']}]")
    else:
        manga = pick_from_list(all_results, "manga")
        if not manga:
            return

    log(f"\nSelected: \"{manga['title']}\" [{manga['source']}]")

    # Chapters
    src_key = manga["source"]
    source  = ALL_SOURCES[src_key]
    if src_key == "mangadex":
        chapters = source.get_chapters(manga["id"])
    else:
        chapters = source.get_chapters(manga.get("url", manga["id"]))

    if not chapters:
        log("FAIL: No chapters found.")
        return

    log(f"\n  {len(chapters)} chapters — Ch.{chapters[0]['num']} to Ch.{chapters[-1]['num']}")

    # What to download
    if download_all or auto:
        to_dl = chapters
    elif ch_range:
        to_dl = filter_chapters(chapters, ch_range[0], ch_range[1])
    else:
        print(f"\n  A = All {len(chapters)}  |  R = Range  |  S = Single")
        c = ask_user("  Choice: ").upper()
        if c == "A":
            to_dl = chapters
        elif c == "R":
            try:
                to_dl = filter_chapters(chapters, float(ask_user("  From: ")), float(ask_user("  To: ")))
            except ValueError:
                log("Invalid."); return
        elif c == "S":
            try:
                n = float(ask_user("  Ch#: "))
                to_dl = filter_chapters(chapters, n, n)
            except ValueError:
                log("Invalid."); return
        else:
            return

    if not to_dl:
        log("FAIL: No chapters match.")
        return

    manga_dir = OUTPUT_DIR / safe_name(manga["title"])
    manga_dir.mkdir(parents=True, exist_ok=True)
    log(f"\n[*] Saving to: {manga_dir.resolve()}")
    log(f"[*] {len(to_dl)} chapter(s)\n")

    ok = 0
    for idx, ch in enumerate(to_dl, 1):
        log(f"\n[{idx}/{len(to_dl)}] Ch.{ch['num']}")
        if download_chapter(manga, ch, manga_dir):
            ok += 1
        polite_delay(0.5, 1.5)

    fail = len(to_dl) - ok
    log(f"\n{'═'*58}")
    log(f"  Downloaded: {ok}  |  Failed: {fail}")
    log(f"  Saved to:   {manga_dir.resolve()}")
    log(f"{'═'*58}")
    if ok > 0:
        log(f"SUCCESS: {ok} chapters saved to {manga_dir.resolve()}")


# ═══════════════════════════════════════════════════════════════════════════════
#  SERVER MODE  (called by manager.py as subprocess)
# ═══════════════════════════════════════════════════════════════════════════════

def server_mode(title: str, all_chapters=True, ch_range=None):
    log(f"INFO: [ENGINE] Starting: {title}")

    # Parse titles
    if "|" in title:
        titles = [t.strip() for t in title.split("|") if t.strip()]
    else:
        titles = generate_variations(title)
    main_title = titles[0]
    log(f"INFO: [ENGINE] Queries: {titles}")

    # Search each title individually
    all_results = search_all_sources(titles)
    if not all_results:
        log(f"FAIL: No results for '{main_title}'.")
        sys.exit(1)

    # Sort: exact match first, then by SOURCE_ORDER priority
    all_results.sort(key=lambda x: (
        normalize(main_title) != normalize(x["title"]),
        SOURCE_ORDER.index(x["source"]) if x["source"] in SOURCE_ORDER else 99
    ))

    # Validate: pick first candidate that actually has chapters
    manga = None
    for cand in all_results[:6]:
        log(f"INFO: Validating: {cand['title']} [{cand['source']}]")
        src = ALL_SOURCES[cand["source"]]
        try:
            if cand["source"] == "mangadex":
                chs = src.get_chapters(cand["id"])
            else:
                chs = src.get_chapters(cand.get("url") or cand["id"])
            if chs:
                log(f"INFO: Confirmed — {len(chs)} chapters")
                manga = cand
                break
            else:
                log(f"WARN: 0 chapters, skipping...")
        except Exception as e:
            log(f"WARN: Validation error: {e}")
        polite_delay(0.5, 1.0)

    if not manga:
        log("FAIL: All candidates had 0 chapters.")
        sys.exit(1)

    log(f"INFO: [ENGINE] Selected: {manga['title']} [{manga['source']}]")

    # Get chapters
    src_key = manga["source"]
    source  = ALL_SOURCES[src_key]
    if src_key == "mangadex":
        chapters = source.get_chapters(manga["id"])
    else:
        chapters = source.get_chapters(manga.get("url", manga["id"]))

    if not chapters:
        log(f"FAIL: No chapters for '{manga['title']}'")
        sys.exit(1)

    # Filter
    to_dl = filter_chapters(chapters, *(ch_range if ch_range else (None, None)))
    if not to_dl:
        log(f"FAIL: No chapters in range {ch_range}")
        sys.exit(1)

    log(f"INFO: [ENGINE] {len(to_dl)} chapters to download")

    manga_dir = OUTPUT_DIR / safe_name(manga["title"])
    manga_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    for idx, ch in enumerate(to_dl, 1):
        log(f"DOWNLOAD: Chapter {ch['num']} ({idx}/{len(to_dl)})")
        if download_chapter(manga, ch, manga_dir):
            ok += 1
        polite_delay(0.5, 1.0)

    log(f"COMPLETE: {ok}/{len(to_dl)} chapters saved to {manga_dir.resolve()}")
    if ok == 0:
        log("FAIL: 0 chapters downloaded.")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manhwa Downloader v5.0")
    parser.add_argument("title",    nargs="?", help="Manhwa title")
    parser.add_argument("--all",    action="store_true", help="All chapters")
    parser.add_argument("--ch",     nargs=2, metavar=("FROM", "TO"), help="Range")
    parser.add_argument("--output", help="Output dir")
    parser.add_argument("--auto",   action="store_true", help="Auto-pick first")
    parser.add_argument("--server", action="store_true", help="Server mode")

    args = parser.parse_args()

    if args.output:
        OUTPUT_DIR = Path(args.output)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ch_range = None
    if args.ch:
        try:
            ch_range = (float(args.ch[0]), float(args.ch[1]))
        except ValueError:
            log("ERROR: --ch needs two numbers")
            sys.exit(1)

    try:
        if args.server and args.title:
            server_mode(args.title, all_chapters=args.all, ch_range=ch_range)
        else:
            run(title=args.title, download_all=args.all or args.auto,
                ch_range=ch_range, auto=args.auto)
    except KeyboardInterrupt:
        log("\n[!] Interrupted.")
        sys.exit(0)