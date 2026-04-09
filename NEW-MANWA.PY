#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║         MANHWA DOWNLOADER v3.0               ║
║  Sources: MangaDex → ComicK → MangaNato      ║
║           → MangaFire → Bato.to              ║
║  FIX: Downloads ALL chapters by default      ║
╚══════════════════════════════════════════════╝

Usage:
  python manhwa_dl.py                          # Interactive mode
  python manhwa_dl.py "Solo Leveling"          # Search directly
  python manhwa_dl.py "Solo Leveling" --all    # Download all chapters
  python manhwa_dl.py "Solo Leveling" --ch 1 5 # Download chapters 1 to 5
  python manhwa_dl.py "Solo Leveling" --auto   # Auto-pick first result, all chapters
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
from urllib.parse import quote, urljoin, urlparse

# Force UTF-8 on Windows environments to prevent charmap UnicodeEncodeError on Japanese/Chinese aliases
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# ─── AUTO INSTALL MISSING PACKAGES ───────────────────────────────────────────

def install_if_missing(package, import_name=None):
    import_name = import_name or package
    try:
        __import__(import_name)
    except ImportError:
        print(f"  ↓ Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])
        print(f"  ✓ {package} installed")

print("\n[*] Checking dependencies...")
install_if_missing("requests")
install_if_missing("beautifulsoup4", "bs4")

import requests
from bs4 import BeautifulSoup

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://google.com",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

OUTPUT_DIR = Path("downloads")
if not OUTPUT_DIR.exists():
    OUTPUT_DIR.mkdir(parents=True)

# ─── UTILS ───────────────────────────────────────────────────────────────────

def normalize_title(text: str) -> str:
    """Normalize title for comparison: lowercase, no special chars, no extra whitespace."""
    if not text: return ""
    text = text.lower()
    text = re.sub(r"['’\"!@#$%^&*()_+\-=\[\]{};':\",.<>/?|]", "", text)
    return " ".join(text.split())

def generate_variations(title: str) -> list:
    """Generate title variations for more robust search."""
    base = title.strip()
    variations = [base]
    
    # Common manhwa title patterns
    if "omniscient reader" in base.lower() and "viewpoint" not in base.lower():
        variations.append(f"{base}'s Viewpoint")
        variations.append(f"{base} Viewpoint")
    
    # Generic variants
    lower = base.lower()
    if lower.endswith(" manhwa") or lower.endswith(" manga"):
        variations.append(base.rsplit(" ", 1)[0])
    
    return list(dict.fromkeys(variations)) # Unique only

def is_manhwa(title: str) -> bool:
    """Filter out non-manhwa results (novels, books, etc)."""
    t = title.lower()
    skip_keywords = ["(novel)", " novel", "book version", "light novel", "special edition", "promo"]
    if any(k in t for k in skip_keywords):
        return False
    return True

def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name).strip().replace(' ', '_')

def download_image(url: str, save_path: Path, referer: str = "", retries: int = 4) -> bool:
    # Anti-bot delay between page requests
    time.sleep(random.uniform(1.5, 3.5))
    
    headers = {**HEADERS}
    if referer:
        headers["Referer"] = referer

    for attempt in range(1, retries + 1):
        try:
            resp = SESSION.get(url, headers=headers, timeout=25, stream=True)
            resp.raise_for_status()
            # Validate it's actually an image
            ct = resp.headers.get("Content-Type", "")
            if "html" in ct:
                raise ValueError(f"Got HTML instead of image (likely rate-limited)")
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=16384):
                    f.write(chunk)
            # Sanity check: image should be at least 1KB
            if save_path.stat().st_size < 1024:
                save_path.unlink(missing_ok=True)
                raise ValueError(f"File too small ({save_path.stat().st_size if save_path.exists() else 0}B) — likely error page")
            return True
        except Exception as e:
            if attempt < retries:
                wait = 2.0 * attempt
                print(f"\n    ⚠ Retry {attempt}/{retries} (wait {wait:.0f}s): {e}")
                time.sleep(wait)
            else:
                print(f"\n    ✗ Failed: {save_path.name} — {e}")
    return False

def progress_bar(current: int, total: int, prefix: str = "", width: int = 35):
    if total == 0:
        return
    if "--server" in sys.argv:
        # Avoid \r spam in streaming orchestrator logs
        if current == total:
            print(f"  {prefix} [███████████████████████████████████] 100% ({current}/{total})")
            sys.stdout.flush()
        return
        
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total)
    print(f"\r  {prefix} [{bar}] {pct}% ({current}/{total})", end="", flush=True)
    if current == total:
        print()

def ask_user(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Cancelled.")
        sys.exit(0)

# ─── SOURCE 1: MANGADEX (PRIMARY) ────────────────────────────────────────────

class MangaDexSource:
    """Official MangaDex REST API — most reliable."""
    BASE   = "https://api.mangadex.org"

    def search(self, title: str) -> list:
        print(f"\n[MangaDex] Searching: '{title}'...")
        try:
            params = {
                "title": title,
                "limit": 10,
                "contentRating[]": ["safe", "suggestive", "erotica"],
                "includes[]": ["cover_art"],
                "order[relevance]": "desc",
            }
            r = SESSION.get(f"{self.BASE}/manga", params=params, timeout=15)
            r.raise_for_status()
            results = []
            for item in r.json().get("data", []):
                mid   = item["id"]
                attrs = item["attributes"]
                titles = attrs.get("title", {})
                name   = titles.get("en") or next(iter(titles.values()), "Unknown")
                
                # Extract unofficial/alternate titles for discovery
                aliases = []
                for alt_dict in attrs.get("altTitles", []):
                    aliases.extend(alt_dict.values())
                
                results.append({
                    "id": mid, 
                    "title": name, 
                    "status": attrs.get("status","?"), 
                    "source": "mangadex",
                    "aliases": list(set(aliases)) # Deduplicate
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaDex] Search failed: {e}")
            return []

    def get_chapters(self, manga_id: str, lang: str = "en") -> list:
        print(f"[MangaDex] Fetching full chapter list...")
        chapters = []
        offset = 0
        limit  = 100
        while True:
            try:
                params = {
                    "manga": manga_id,
                    "translatedLanguage[]": [lang],
                    "limit": limit,
                    "offset": offset,
                    "order[chapter]": "asc",
                    "contentRating[]": ["safe", "suggestive", "erotica"],
                    "includes[]": ["scanlation_group"],
                }
                r = SESSION.get(f"{self.BASE}/chapter", params=params, timeout=15)
                r.raise_for_status()
                data  = r.json()
                batch = data.get("data", [])
                if not batch:
                    break
                for ch in batch:
                    attrs  = ch["attributes"]
                    ch_num = attrs.get("chapter") or "0"
                    chapters.append({
                        "id"   : ch["id"],
                        "num"  : ch_num,
                        "title": attrs.get("title") or f"Chapter {ch_num}",
                        "pages": attrs.get("pages", 0),
                    })
                offset += limit
                if offset >= data.get("total", 0):
                    break
                time.sleep(0.3)
            except Exception as e:
                print(f"  [MangaDex] Chapter fetch error at offset {offset}: {e}")
                break
        # Deduplicate by chapter number (keep first encountered)
        seen = set()
        unique = []
        for ch in chapters:
            if ch["num"] not in seen:
                seen.add(ch["num"])
                unique.append(ch)
        print(f"  Found {len(unique)} unique chapters (lang={lang})")
        return unique

    def get_page_urls(self, chapter_id: str) -> list:
        try:
            r = SESSION.get(f"{self.BASE}/at-home/server/{chapter_id}", timeout=15)
            r.raise_for_status()
            data     = r.json()
            base_url = data["baseUrl"]
            ch_hash  = data["chapter"]["hash"]
            pages    = data["chapter"]["data"]
            return [f"{base_url}/data/{ch_hash}/{p}" for p in pages]
        except Exception as e:
            print(f"  [MangaDex] Page URL error: {e}")
            return []

# ─── SOURCE 2: COMICK (FALLBACK 1) ───────────────────────────────────────────

class ComicKSource:
    """ComicK API — great for manhwa specifically. DNS fix: uses comick.io fallback."""
    BASES = ["https://api.comick.fun", "https://api.comick.io"]

    def _get(self, path, **kwargs):
        """Try each base URL until one works."""
        last_err = None
        for base in self.BASES:
            try:
                r = SESSION.get(f"{base}{path}", **kwargs)
                r.raise_for_status()
                return r
            except Exception as e:
                last_err = e
        raise last_err

    def search(self, title: str) -> list:
        print(f"\n[ComicK] Searching: '{title}'...")
        try:
            params = {"q": title, "limit": 10, "type": "comic"}
            r = self._get("/v1.0/search", params=params, timeout=15)
            results = []
            for item in r.json():
                results.append({
                    "id"    : item.get("hid", ""),
                    "slug"  : item.get("slug", ""),
                    "title" : item.get("title", "Unknown"),
                    "status": str(item.get("status", "?")),
                    "source": "comick",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [ComicK] Search failed: {e}")
            return []

    def get_chapters(self, hid: str, lang: str = "en") -> list:
        print(f"[ComicK] Fetching full chapter list...")
        chapters = []
        page = 1
        while True:
            try:
                params = {"lang": lang, "page": page, "limit": 100, "ordering": "asc"}
                r = self._get(f"/comic/{hid}/chapters", params=params, timeout=15)
                batch = r.json().get("chapters", [])
                if not batch:
                    break
                for ch in batch:
                    ch_num = str(ch.get("chap") or "0")
                    chapters.append({
                        "id"   : ch["hid"],
                        "num"  : ch_num,
                        "title": ch.get("title") or f"Chapter {ch_num}",
                        "pages": ch.get("page_count", 0),
                    })
                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  [ComicK] Chapter page {page} error: {e}")
                break
        print(f"  Found {len(chapters)} chapters")
        return chapters

    def get_page_urls(self, chapter_hid: str) -> list:
        try:
            r = self._get(f"/chapter/{chapter_hid}", timeout=15)
            imgs = r.json().get("chapter", {}).get("md_images", [])
            base = "https://meo.comick.pictures/"
            return [f"{base}{img['b2key']}" for img in imgs if img.get("b2key")]
        except Exception as e:
            print(f"  [ComicK] Page URL error: {e}")
            return []

# ─── SOURCE 3: MANGANATO (FALLBACK 2) ────────────────────────────────────────

class MangaNatoSource:
    """MangaNato scraper — large catalogue."""
    SEARCH = "https://manganato.com/search/story/"

    def search(self, title: str) -> list:
        print(f"\n[MangaNato] Searching: '{title}'...")
        try:
            slug = quote(title.lower().replace(" ", "_"))
            r = SESSION.get(f"{self.SEARCH}{slug}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.search-story-item")[:8]:
                a = item.select_one("a.item-title") or item.select_one("h3 a")
                if not a:
                    continue
                href = a.get("href", "")
                results.append({
                    "id"    : href.rstrip("/").split("/")[-1],
                    "url"   : href,
                    "title" : a.get_text(strip=True),
                    "status": "?",
                    "source": "manganato",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaNato] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaNato] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("li.a-h")
            chapters = []
            for row in reversed(rows):
                a = row.select_one("a.chapter-name")
                if not a:
                    continue
                href = a.get("href", "")
                text = a.get_text(strip=True)
                m = re.search(r"chapter[\s_-]*([\d.]+)", text, re.I)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaNato] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            headers = {**HEADERS, "Referer": "https://manganato.com"}
            r = SESSION.get(chapter_url, headers=headers, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div.container-chapter-reader img")
            return [img.get("src", "") for img in imgs if img.get("src")]
        except Exception as e:
            print(f"  [MangaNato] Page URL error: {e}")
            return []

# ─── SOURCE 4: MANGAFIRE (FALLBACK 3) ── FIXED 403 ──────────────────────────

class MangaFireSource:
    """MangaFire — fixed 403 with proper Referer header."""
    BASE   = "https://mangafire.to"
    SEARCH = "https://mangafire.to/filter"
    HDRS   = {**HEADERS, "Referer": "https://mangafire.to/", "User-Agent": "Mozilla/5.0"}

    def search(self, title: str) -> list:
        print(f"\n[MangaFire] Searching: '{title}'...")
        try:
            params = {"keyword": title, "type[]": "manhwa"}
            r = SESSION.get(self.SEARCH, headers=self.HDRS, params=params, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.unit .inner")[:8]:
                a = item.select_one("a")
                if not a:
                    continue
                href  = self.BASE + a.get("href", "")
                name  = (item.select_one(".title") or item.select_one("h3") or a).get_text(strip=True)
                mid   = a.get("href","").rstrip("/").split("/")[-1]
                results.append({"id": mid, "url": href, "title": name, "status": "?", "source": "mangafire"})
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaFire] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaFire] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, headers=self.HDRS, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for li in reversed(soup.select("ul#en-chapters li, ul.chapter-list li")):
                a = li.select_one("a")
                if not a:
                    continue
                href  = self.BASE + a.get("href","") if a.get("href","").startswith("/") else a.get("href","")
                text  = a.get_text(strip=True)
                m     = re.search(r"[\d.]+", text)
                ch_num = m.group(0) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaFire] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers=self.HDRS, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div.viewer img, div#chapter-images img, .chapter-container img")
            return [img.get("data-src") or img.get("src") or "" for img in imgs if img.get("data-src") or img.get("src")]
        except Exception as e:
            print(f"  [MangaFire] Page URL error: {e}")
            return []

# ─── SOURCE 5: BATO.TO (FALLBACK 4) ── FIXED TIMEOUT ─────────────────────────

class BatoSource:
    """Bato.to — fixed timeout (30s) + retry logic."""
    BASE   = "https://bato.to"
    SEARCH = "https://bato.to/search"

    def _get(self, url, **kwargs):
        kwargs.setdefault("timeout", 30)
        for i in range(3):
            try:
                r = SESSION.get(url, **kwargs)
                r.raise_for_status()
                return r
            except Exception as e:
                if i < 2:
                    time.sleep(2)
                else:
                    raise e

    def search(self, title: str) -> list:
        print(f"\n[Bato.to] Searching: '{title}'...")
        try:
            r = self._get(self.SEARCH, params={"word": title, "lang": "en"})
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.item-row, article.item")[:8]:
                a = item.select_one("a.item-title, h3 a, .title a")
                if not a:
                    continue
                href  = self.BASE + a.get("href","") if a.get("href","").startswith("/") else a.get("href","")
                name  = a.get_text(strip=True)
                mid   = a.get("href","").rstrip("/").split("/")[-1]
                results.append({"id": mid, "url": href, "title": name, "status": "?", "source": "bato"})
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [Bato.to] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[Bato.to] Fetching chapter list...")
        try:
            r = self._get(manga_url)
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("a[href*='/chapter/'], .chapter-list a")):
                href  = self.BASE + a.get("href","") if a.get("href","").startswith("/") else a.get("href","")
                text  = a.get_text(strip=True)
                m     = re.search(r"[\d.]+", text)
                ch_num = m.group(0) if m else "0"
                if href not in [c["url"] for c in chapters]:
                    chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [Bato.to] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = self._get(chapter_url, headers={**HEADERS, "Referer": self.BASE})
            soup = BeautifulSoup(r.text, "html.parser")
            script = soup.find("script", string=re.compile(r"imgSrcs|images|pageUrls"))
            if script:
                m = re.findall(r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', script.string or "")
                if m:
                    return m
            imgs = soup.select("div#viewer img, .page-img img, img.page")
            return [img.get("src","") for img in imgs if img.get("src","").startswith("http")]
        except Exception as e:
            print(f"  [Bato.to] Page URL error: {e}")
            return []

# ─── SOURCE 6: MANGASEE ───────────────────────────────────────────────────────

class MangaSeeSource:
    """MangaSee123 — large catalogue, good quality scans."""
    BASE   = "https://mangasee123.com"
    SEARCH_API = "https://mangasee123.com/_search.php"

    def search(self, title: str) -> list:
        print(f"\n[MangaSee] Searching: '{title}'...")
        try:
            # Load the full directory (MangaSee search is client-side usually)
            r = SESSION.get(self.SEARCH_API, timeout=20)
            r.raise_for_status()
            all_manga = r.json()
            
            variations = generate_variations(title)
            results = []
            
            for item in all_manga:
                name = item.get("s", "")
                slug = item.get("i", "")
                
                # Check for any variation match
                match = False
                for v in variations:
                    if normalize_title(v) in normalize_title(name):
                        match = True
                        break
                
                if match and is_manhwa(name):
                    results.append({
                        "id"    : slug,
                        "url"   : f"{self.BASE}/manga/{slug}",
                        "title" : name,
                        "status": "?",
                        "source": "mangasee",
                    })
                
                if len(results) >= 8:
                    break
                    
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaSee] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaSee] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            # MangaSee embeds chapter data in a JSON script
            for script in soup.find_all("script"):
                txt = script.string or ""
                if "vm.Chapters" in txt:
                    m = re.search(r"vm\.Chapters\s*=\s*(\[.*?\]);?", txt, re.DOTALL)
                    if m:
                        import json
                        ch_data = json.loads(m.group(1))
                        slug = manga_url.rstrip("/").split("/")[-1]
                        for ch in reversed(ch_data):
                            ch_num_raw = ch.get("Chapter", "0")
                            # MangaSee encodes chapter number strangely (e.g., "100010")
                            ch_num = str(int(ch_num_raw[1:-1])) if len(ch_num_raw) > 2 else "0"
                            url = f"{self.BASE}/read-online/{slug}-chapter-{ch_num}-page-1.html"
                            chapters.append({"id": url, "url": url, "num": ch_num, "title": f"Chapter {ch_num}", "pages": 0})
                        break
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaSee] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for script in soup.find_all("script"):
                txt = script.string or ""
                if "vm.CurChapter" in txt:
                    import json
                    dir_m = re.search(r'vm\.CurPathName\s*=\s*"([^"]+)"', txt)
                    ch_m  = re.search(r'vm\.CurChapter\s*=\s*(\{.*?\});', txt)
                    if dir_m and ch_m:
                        cdn  = dir_m.group(1)
                        ch   = json.loads(ch_m.group(1))
                        slug = chapter_url.split("/")[-1].split("-chapter-")[0]
                        ch_num = ch.get("Chapter", "")
                        pages = int(ch.get("Page", 0))
                        num_str = str(int(ch_num[1:-1])).zfill(4) if len(ch_num) > 2 else "0000"
                        return [f"https://{cdn}/manga/{slug}/{num_str}-{str(p).zfill(3)}.png" for p in range(1, pages + 1)]
            return []
        except Exception as e:
            print(f"  [MangaSee] Page URL error: {e}")
            return []

# ─── SOURCE 7: MANGAKAKALOT (FALLBACK 6) ─────────────────────────────────────

class MangaKakalotSource:
    """MangaKakalot — big catalogue, similar to MangaNato."""
    BASE   = "https://mangakakalot.com"
    SEARCH = "https://mangakakalot.com/search/story/"

    def search(self, title: str) -> list:
        print(f"\n[MangaKakalot] Searching: '{title}'...")
        try:
            slug = quote(title.lower().replace(" ", "_"))
            r = SESSION.get(f"{self.SEARCH}{slug}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.story_item, div.search-story-item")[:8]:
                a = item.select_one("h3 a, a.story_name, a.item-title")
                if not a:
                    continue
                href = a.get("href", "")
                results.append({
                    "id"    : href.rstrip("/").split("/")[-1],
                    "url"   : href,
                    "title" : a.get_text(strip=True),
                    "status": "?",
                    "source": "mangakakalot",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaKakalot] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaKakalot] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for row in reversed(soup.select("div.chapter-list div.row")):
                a = row.select_one("span a")
                if not a:
                    continue
                href = a.get("href", "")
                text = a.get_text(strip=True)
                m = re.search(r"chapter[\s_-]*([\d.]+)", text, re.I)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaKakalot] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            return [img.get("src", "") for img in soup.select("div.container-chapter-reader img") if img.get("src")]
        except Exception as e:
            print(f"  [MangaKakalot] Page URL error: {e}")
            return []

# ─── SOURCE 8: MANGANELO (FALLBACK 7) ────────────────────────────────────────

class MangaNeloSource:
    """MangaNelo — mirror of MangaNato/MangaKakalot network."""
    SEARCH = "https://manganelo.com/search/story/"
    BASE   = "https://manganelo.com"

    def search(self, title: str) -> list:
        print(f"\n[MangaNelo] Searching: '{title}'...")
        try:
            slug = quote(title.lower().replace(" ", "_"))
            r = SESSION.get(f"{self.SEARCH}{slug}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.search-story-item")[:8]:
                a = item.select_one("a.item-title") or item.select_one("h3 a")
                if not a:
                    continue
                href = a.get("href", "")
                results.append({
                    "id"    : href.rstrip("/").split("/")[-1],
                    "url"   : href,
                    "title" : a.get_text(strip=True),
                    "status": "?",
                    "source": "manganelo",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaNelo] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaNelo] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for row in reversed(soup.select("li.a-h")):
                a = row.select_one("a.chapter-name")
                if not a:
                    continue
                href = a.get("href", "")
                text = a.get_text(strip=True)
                m = re.search(r"chapter[\s_-]*([\d.]+)", text, re.I)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaNelo] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            return [img.get("src", "") for img in soup.select("div.container-chapter-reader img") if img.get("src")]
        except Exception as e:
            print(f"  [MangaNelo] Page URL error: {e}")
            return []

# ─── SOURCE 9: ASURA SCANS (FALLBACK 8) ───────────────────────────────────────

class AsuraScansSource:
    """Asura Scans — premium scanlation for manhwa."""
    BASE   = "https://asurascans.com"
    SEARCH = "https://asurascans.com/?s="

    def search(self, title: str) -> list:
        print(f"\n[AsuraScans] Searching: '{title}'...")
        try:
            r = SESSION.get(f"{self.SEARCH}{quote(title)}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.bsx, div.bs")[:8]:
                a = item.select_one("a")
                if not a:
                    continue
                href = a.get("href", "")
                name = (item.select_one(".tt") or a).get_text(strip=True)
                results.append({
                    "id"    : href.rstrip("/").split("/")[-1],
                    "url"   : href,
                    "title" : name,
                    "status": "?",
                    "source": "asura",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [AsuraScans] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[AsuraScans] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("div.eplister li a")):
                href = a.get("href", "")
                num_el = a.select_one(".chapternum")
                text = num_el.get_text(strip=True) if num_el else a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [AsuraScans] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div#readerarea img, div.rdminimal img")
            return [img.get("src", "") or img.get("data-src", "") for img in imgs if img.get("src") or img.get("data-src")]
        except Exception as e:
            print(f"  [AsuraScans] Page URL error: {e}")
            return []

# ─── SOURCE 10: REAPER SCANS (FALLBACK 9) ─────────────────────────────────────

class ReaperScansSource:
    """Reaper Scans — popular scanlation group."""
    BASE   = "https://reaperscans.com"
    SEARCH = "https://reaperscans.com/?s="

    def search(self, title: str) -> list:
        print(f"\n[ReaperScans] Searching: '{title}'...")
        try:
            r = SESSION.get(f"{self.SEARCH}{quote(title)}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.bsx, div.bs, article")[:8]:
                a = item.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href", "")
                name = (item.select_one(".tt, h3, h2") or a).get_text(strip=True)
                results.append({
                    "id": href.rstrip("/").split("/")[-1], "url": href,
                    "title": name, "status": "?", "source": "reaper",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [ReaperScans] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[ReaperScans] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("div.eplister li a")):
                href = a.get("href", "")
                text = (a.select_one(".chapternum") or a).get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [ReaperScans] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div#readerarea img, div.rdminimal img")
            return [img.get("src") or img.get("data-src") for img in imgs if img.get("src") or img.get("data-src")]
        except Exception as e:
            print(f"  [ReaperScans] Page URL error: {e}")
            return []

# ─── SOURCE 11: FLAME SCANS (FALLBACK 10) ─────────────────────────────────────

class FlameScansSource:
    """Flame Scans — another popular manhwa scanlation."""
    BASE   = "https://flamescans.org"
    SEARCH = "https://flamescans.org/?s="

    def search(self, title: str) -> list:
        print(f"\n[FlameScans] Searching: '{title}'...")
        try:
            r = SESSION.get(f"{self.SEARCH}{quote(title)}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.bsx, div.bs, article")[:8]:
                a = item.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href", "")
                name = (item.select_one(".tt, h3, h2") or a).get_text(strip=True)
                results.append({
                    "id": href.rstrip("/").split("/")[-1], "url": href,
                    "title": name, "status": "?", "source": "flame",
                })
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [FlameScans] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[FlameScans] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("div.eplister li a")):
                href = a.get("href", "")
                text = (a.select_one(".chapternum") or a).get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [FlameScans] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div#readerarea img, div.rdminimal img")
            return [img.get("src") or img.get("data-src") for img in imgs if img.get("src") or img.get("data-src")]
        except Exception as e:
            print(f"  [FlameScans] Page URL error: {e}")
            return []

# ─── ALL SOURCES REGISTRY ─────────────────────────────────────────────────────

ALL_SOURCES = {
    # Tier 1: APIs (most stable)
    "mangadex"   : MangaDexSource(),
    "comick"     : ComicKSource(),
    # Tier 2: Scrapers with large catalogues
    "manganato"  : MangaNatoSource(),
    "manganelo"  : MangaNeloSource(),
    "mangakakalot": MangaKakalotSource(),
    "mangasee"   : MangaSeeSource(),
    "mangafire"  : MangaFireSource(),
    "bato"       : BatoSource(),
    # Tier 3: Premium scanlation sites
    "asura"       : AsuraScansSource(),
    "reaper"      : ReaperScansSource(),
    "flame"       : FlameScansSource(),
}

# ─── EASY-SCRAPE SOURCES (Tier 4) ────────────────────────────────────────────

def _wp_reader_source(name: str, base: str, source_key: str):
    """
    Factory for WordPress-theme sites (bsx/bs selectors, #readerarea images).
    Used by: Zero Scans, Luminous, Void Scans etc.
    """
    class WPScanSource:
        BASE   = base
        SEARCH = base + "/?s="
        KEY    = source_key

        def search(self, title: str) -> list:
            print(f"\n[{name}] Searching: '{title}'...")
            try:
                r = SESSION.get(f"{self.SEARCH}{quote(title)}", timeout=5)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                results = []
                for item in soup.select("div.bsx, div.bs, article")[:8]:
                    a = item.select_one("a[href]")
                    if not a:
                        continue
                    href = a.get("href", "")
                    n = (item.select_one(".tt, h3, h2") or a).get_text(strip=True)
                    results.append({"id": href.rstrip("/").split("/")[-1], "url": href,
                                     "title": n, "status": "?", "source": self.KEY})
                print(f"  Found {len(results)} results")
                return results
            except Exception as e:
                print(f"  [{name}] Search failed: {e}")
                return []

        def get_chapters(self, manga_url: str) -> list:
            print(f"[{name}] Fetching chapter list...")
            try:
                r = SESSION.get(manga_url, timeout=5)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                chapters = []
                for a in reversed(soup.select("div.eplister li a")):
                    href = a.get("href", "")
                    text = (a.select_one(".chapternum") or a).get_text(strip=True)
                    m = re.search(r"([\d.]+)", text)
                    ch_num = m.group(1) if m else "0"
                    chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
                print(f"  Found {len(chapters)} chapters")
                return chapters
            except Exception as e:
                print(f"  [{name}] Chapter fetch error: {e}")
                return []

        def get_page_urls(self, chapter_url: str) -> list:
            try:
                r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=5)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                imgs = soup.select("div#readerarea img, div.rdminimal img")
                return [img.get("src") or img.get("data-src") for img in imgs
                        if img.get("src") or img.get("data-src")]
            except Exception as e:
                print(f"  [{name}] Page URL error: {e}")
                return []

    WPScanSource.__name__ = f"{name}Source"
    return WPScanSource()

def _madara_source(name: str, base: str, source_key: str):
    """
    Factory for Madara-theme sites (post_type=wp-manga).
    Used by: Coffee Manga, Hari Manga, Kun Manga, Toonily, 1st Kiss etc.
    """
    class MadaraScanSource:
        BASE   = base
        SEARCH = base + "/?s="
        KEY    = source_key

        def search(self, title: str) -> list:
            print(f"\n[{name}] Searching: '{title}'...")
            try:
                params = {"s": title, "post_type": "wp-manga"}
                r = SESSION.get(f"{self.BASE}/", params=params, timeout=5)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                results = []
                for item in soup.select(".c-tabs-item__content, .row.c-tabs-item__content")[:8]:
                    a = item.select_one(".post-title a, h3 a")
                    if not a:
                        continue
                    href = a.get("href", "")
                    n = a.get_text(strip=True)
                    results.append({"id": href.rstrip("/").split("/")[-1], "url": href,
                                     "title": n, "status": "?", "source": self.KEY})
                print(f"  Found {len(results)} results")
                return results
            except Exception as e:
                print(f"  [{name}] Search failed: {e}")
                return []

        def get_chapters(self, manga_url: str) -> list:
            print(f"[{name}] Fetching chapter list...")
            try:
                # Madara sometimes needs a POST request to get chapters
                r = SESSION.post(f"{manga_url.rstrip('/')}/ajax/chapters/", timeout=5)
                if r.status_code != 200 or not r.text.strip():
                    r = SESSION.get(manga_url, timeout=5)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                chapters = []
                for a in reversed(soup.select("li.wp-manga-chapter a")):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    m = re.search(r"([\d.]+)", text)
                    ch_num = m.group(1) if m else "0"
                    chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
                print(f"  Found {len(chapters)} chapters")
                return chapters
            except Exception as e:
                print(f"  [{name}] Chapter fetch error: {e}")
                return []

        def get_page_urls(self, chapter_url: str) -> list:
            try:
                r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=5)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                imgs = soup.select(".reading-content img, .page-break img")
                return [img.get("data-src") or img.get("src") for img in imgs
                        if img.get("data-src") or img.get("src")]
            except Exception as e:
                print(f"  [{name}] Page URL error: {e}")
                return []

    MadaraScanSource.__name__ = f"{name}Source"
    return MadaraScanSource()


class MangaParkSource:
    """MangaPark — simple HTML, easy scrape."""
    BASE   = "https://mangapark.net"
    SEARCH = "https://mangapark.net/search"

    def search(self, title: str) -> list:
        print(f"\n[MangaPark] Searching: '{title}'...")
        try:
            r = SESSION.get(self.SEARCH, params={"q": title}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.item, div.comic-item, article")[:8]:
                a = item.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                n = (item.select_one("h3, h2, .title") or a).get_text(strip=True)
                results.append({"id": href.rstrip("/").split("/")[-1], "url": href,
                                 "title": n, "status": "?", "source": "mangapark"})
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaPark] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaPark] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("a[href*='/chapter'], a[href*='-chapter-']")):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                if href not in [c["url"] for c in chapters]:
                    chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaPark] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div.viewer img, div.chapter-images img, img.page-img")
            return [img.get("src") or img.get("data-src") for img in imgs
                    if img.get("src") or img.get("data-src")]
        except Exception as e:
            print(f"  [MangaPark] Page URL error: {e}")
            return []


class MangaBatSource:
    """MangaBat — simple HTML, same network as MangaNato."""
    BASE   = "https://m.mangabat.com"
    SEARCH = "https://m.mangabat.com/search/manga/"

    def search(self, title: str) -> list:
        print(f"\n[MangaBat] Searching: '{title}'...")
        try:
            slug = quote(title.lower().replace(" ", "_"))
            r = SESSION.get(f"{self.SEARCH}{slug}", timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.list-story-item, div.search-story-item")[:8]:
                a = item.select_one("a")
                if not a:
                    continue
                href = a.get("href", "")
                n = (item.select_one(".item-img") or a).get("title", a.get_text(strip=True))
                results.append({"id": href.rstrip("/").split("/")[-1], "url": href,
                                 "title": n, "status": "?", "source": "mangabat"})
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaBat] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaBat] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("li a.chapter-name, a.chapter")):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                m = re.search(r"chapter[\s_-]*([\d.]+)", text, re.I)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaBat] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            return [img.get("src", "") for img in soup.select("div.container-chapter-reader img") if img.get("src")]
        except Exception as e:
            print(f"  [MangaBat] Page URL error: {e}")
            return []


class MangaBuddySource:
    """MangaBuddy — clean HTML, easy scrape."""
    BASE   = "https://mangabuddy.com"
    SEARCH = "https://mangabuddy.com/search"

    def search(self, title: str) -> list:
        print(f"\n[MangaBuddy] Searching: '{title}'...")
        try:
            r = SESSION.get(self.SEARCH, params={"q": title}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.book-item, div.comic-item")[:8]:
                a = item.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                n = (item.select_one(".title, h3") or a).get_text(strip=True)
                results.append({"id": href.rstrip("/").split("/")[-1], "url": href,
                                 "title": n, "status": "?", "source": "mangabuddy"})
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaBuddy] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaBuddy] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("ul.chapter-list a, div.chapter-list a")):
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE + href
                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                if href not in [c["url"] for c in chapters]:
                    chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaBuddy] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            imgs = soup.select("div.chapter-images img, div#chapter-images img")
            return [img.get("data-src") or img.get("src") for img in imgs
                    if img.get("data-src") or img.get("src")]
        except Exception as e:
            print(f"  [MangaBuddy] Page URL error: {e}")
            return []


class MangaPillSource:
    """MangaPill — very clean, easy scrape."""
    BASE   = "https://mangapill.com"
    SEARCH = "https://mangapill.com/search"

    def search(self, title: str) -> list:
        print(f"\n[MangaPill] Searching: '{title}'...")
        try:
            r = SESSION.get(self.SEARCH, params={"q": title, "type": "", "status": ""}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select("div.manga-item, div.col")[:8]:
                a = item.select_one("a[href]")
                if not a:
                    continue
                href = self.BASE + a.get("href", "") if a.get("href","").startswith("/") else a.get("href","")
                n = (item.select_one(".manga-title, h3") or a).get_text(strip=True)
                results.append({"id": href.rstrip("/").split("/")[-1], "url": href,
                                 "title": n, "status": "?", "source": "mangapill"})
            print(f"  Found {len(results)} results")
            return results
        except Exception as e:
            print(f"  [MangaPill] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        print(f"[MangaPill] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = []
            for a in reversed(soup.select("div#chapters a, div.chapters a")):
                href = self.BASE + a.get("href","") if a.get("href","").startswith("/") else a.get("href","")
                text = a.get_text(strip=True)
                m = re.search(r"([\d.]+)", text)
                ch_num = m.group(1) if m else "0"
                chapters.append({"id": href, "url": href, "num": ch_num, "title": text, "pages": 0})
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaPill] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        try:
            r = SESSION.get(chapter_url, headers={**HEADERS, "Referer": self.BASE}, timeout=5)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            return [img.get("data-src") or img.get("src") for img in soup.select("div.flex img, div.chapter-images img")
                    if img.get("data-src") or img.get("src")]
        except Exception as e:
            print(f"  [MangaPill] Page URL error: {e}")
            return []


# ─── ALL SOURCES REGISTRY (26 total) ──────────────────────────────────────────
# TIER 1 = Gold (APIs, always reliable)
# TIER 2 = Silver (HTML scrapers, large catalogues)
# TIER 3 = Bronze (Scanlation sites / WP streams, premium content)
# TIER 4 = Iron (Easy-scrape backup sites, fast-fail 5s)
# TIER 5 = Lead (Madara backup / obscure sites)

ALL_SOURCES = {
    # ── TIER 1: Gold ──────────────────────────────────────────────────────────
    "mangadex"    : MangaDexSource(),
    "comick"      : ComicKSource(),
    # ── TIER 2: Silver ────────────────────────────────────────────────────────
    "manganato"   : MangaNatoSource(),
    "manganelo"   : MangaNeloSource(),
    "mangakakalot": MangaKakalotSource(),
    "mangasee"    : MangaSeeSource(),
    "mangafire"   : MangaFireSource(),
    "bato"        : BatoSource(),
    # ── TIER 3: Bronze (Scanlations - Mangastream WP) ─────────────────────────
    "asura"       : AsuraScansSource(),
    "reaper"      : ReaperScansSource(),
    "flame"       : FlameScansSource(),
    "zeroscans"   : _wp_reader_source("ZeroScans",    "https://zeroscans.com",    "zeroscans"),
    "luminous"    : _wp_reader_source("LuminousScans","https://luminousscans.com","luminous"),
    "void"        : _wp_reader_source("VoidScans",    "https://void-scans.com",   "void"),
    "rawkuma"     : _wp_reader_source("Rawkuma",      "https://rawkuma.com",      "rawkuma"),
    # ── TIER 4: Iron (Simple HTML Scrapes) ────────────────────────────────────
    "mangapark"   : MangaParkSource(),
    "mangabat"    : MangaBatSource(),
    "mangabuddy"  : MangaBuddySource(),
    "mangapill"   : MangaPillSource(),
    # ── TIER 5: Lead (Madara WP Backups) ──────────────────────────────────────
    "coffee"      : _madara_source("CoffeeManga", "https://coffeemanga.com",  "coffee"),
    "kun"         : _madara_source("KunManga",    "https://kunmanga.com",     "kun"),
    "toonily"     : _madara_source("Toonily",     "https://toonily.com",      "toonily"),
    "manhwatop"   : _madara_source("ManhwaTop",   "https://manhwatop.com",    "manhwatop"),
    "1stkiss"     : _madara_source("1stKiss",     "https://1stkissmanga.me",  "1stkiss"),
    # ── TIER 6: Lead (Fallback Bato) ──────────────────────────────────────────
    "bato"        : BatoSource(),
}


# ─── DOWNLOAD ENGINE ──────────────────────────────────────────────────────────

def download_chapter(manga_info: dict, chapter: dict, manga_dir: Path) -> bool:
    """Download all pages of one chapter."""
    ch_num  = chapter["num"]
    ch_name = safe_name(f"Chapter_{str(ch_num).zfill(4)}")
    ch_dir  = manga_dir / ch_name

    if ch_dir.exists() and any(ch_dir.iterdir()):
        # Count existing images
        existing = list(ch_dir.glob("*.jpg")) + list(ch_dir.glob("*.png")) + list(ch_dir.glob("*.webp"))
        if len(existing) > 0:
            print(f"  ✓ {ch_name} already downloaded ({len(existing)} pages), skipping.")
            return True

    ch_dir.mkdir(parents=True, exist_ok=True)

    src_name = manga_info.get("source")
    source   = ALL_SOURCES.get(src_name)
    ch_id    = chapter.get("url") or chapter["id"]

    referer_map = {
        "mangadex" : "https://mangadex.org",
        "comick"   : "https://comick.fun",
        "manganato": "https://manganato.com",
        "mangafire": "https://mangafire.to",
        "bato"     : "https://bato.to",
    }
    referer = referer_map.get(src_name, "")

    if src_name == "mangadex":
        urls = source.get_page_urls(chapter["id"])
    else:
        urls = source.get_page_urls(ch_id)

    if not urls:
        print(f"  ✗ No pages found for {ch_name}")
        shutil.rmtree(ch_dir, ignore_errors=True)
        return False

    print(f"\n  ⬇  {ch_name} — {chapter.get('title','')}  ({len(urls)} pages)")

    success = 0
    for i, url in enumerate(urls, 1):
        ext  = url.split("?")[0].rsplit(".", 1)[-1].lower()
        ext  = ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"
        path = ch_dir / f"{str(i).zfill(4)}.{ext}"
        progress_bar(i - 1, len(urls), prefix=f"  Page {i:>3}/{len(urls)}")
        ok = download_image(url, path, referer=referer)
        if ok:
            success += 1
        time.sleep(0.2)

    progress_bar(len(urls), len(urls), prefix=f"  {'Done':<12}")

    if success == 0:
        shutil.rmtree(ch_dir, ignore_errors=True)
        print(f"  ✗ All pages failed for {ch_name}")
        return False

    print(f"  ✔ {success}/{len(urls)} pages saved → {ch_dir}")
    return True

# ─── MAIN FLOW ────────────────────────────────────────────────────────────────

def pick_from_list(items: list, label: str) -> dict | None:
    if not items:
        return None
    print(f"\n{'─'*55}")
    for i, item in enumerate(items, 1):
        status = item.get('status', '?')
        source = item.get('source', '')
        print(f"  {i:>2}. {item['title'][:40]:<40} [{status}] ({source})")
    print(f"{'─'*55}")
    choice = ask_user(f"Pick a {label} (1-{len(items)}, or 0 to skip): ")
    if not choice.isdigit() or choice == "0":
        return None
    idx = int(choice) - 1
    return items[idx] if 0 <= idx < len(items) else None

def filter_chapters(chapters: list, ch_from=None, ch_to=None) -> list:
    if ch_from is None and ch_to is None:
        return chapters
    result = []
    for ch in chapters:
        try:
            n = float(ch["num"])
            if ch_from is not None and n < ch_from:
                continue
            if ch_to is not None and n > ch_to:
                continue
            result.append(ch)
        except ValueError:
            pass
    return result

def run(title: str = None, download_all: bool = False, ch_range: tuple = None, auto: bool = False):
    print("\n" + "═"*55)
    print("  MANHWA DOWNLOADER v3.0 — 5-Source Fallback")
    print("  Sources: MangaDex, ComicK, MangaNato, MangaFire, Bato.to")
    print("═"*55)

    if not title:
        title = ask_user("\nEnter manhwa title to search: ")
    if not title:
        print("No title entered.")
        return

    # Search all sources with intelligence loop
    all_results = []
    
    # Handle Master Keyword Array (Title|Alt1|Alt2)
    if "|" in title:
        variations = [t.strip() for t in title.split("|") if t.strip()]
        main_title = variations[0]
        print(f"[*] Using AI Master List: {variations}")
    else:
        variations = generate_variations(title)
        main_title = title
        print(f"[*] Search variations: {variations}")

    for src_name, src_obj in ALL_SOURCES.items():
        try:
            # Try variations for each source
            src_results = []
            for v in variations:
                res = src_obj.search(v)
                # Filter results (skip novels/books)
                filtered = [r for r in res if is_manhwa(r['title'])]
                src_results.extend(filtered)
                if src_results: # If we found something for this source, move on
                    break
            
            # Deduplicate by url/id
            unique_src = []
            seen = set()
            for r in src_results:
                key = r.get('url') or r.get('id')
                if key not in seen:
                    unique_src.append(r)
                    seen.add(key)
            
            all_results.extend(unique_src)
        except Exception as e:
            print(f"  [{src_name}] Error: {e}")
            sys.stdout.flush()

    if not all_results:
        print("\n✗ No results found from any source even with title variations.")
        return

    # Prioritize exact matches or smart sorting
    all_results.sort(key=lambda x: (normalize_title(main_title) != normalize_title(x['title']), x['source']))

    print(f"\n✔ Found {len(all_results)} total result(s) across all sources.")

    # Pick manga
    if auto:
        manga = all_results[0]
        print(f"\n[AUTO] Selected: {manga['title']} [{manga['source']}]")
    else:
        manga = pick_from_list(all_results, "manga")
        if not manga:
            print("Nothing selected.")
            return

    print(f"\n✔ Selected: \"{manga['title']}\" from {manga['source']}")

    # Get chapters
    src_name = manga["source"]
    source   = ALL_SOURCES[src_name]

    if src_name == "mangadex":
        chapters = source.get_chapters(manga["id"])
    elif src_name == "comick":
        chapters = source.get_chapters(manga["id"])
    else:
        chapters = source.get_chapters(manga.get("url", manga.get("id", "")))

    if not chapters:
        print("✗ No chapters found. Try selecting a different source result.")
        return

    print(f"\n{'─'*55}")
    print(f"  Total chapters available : {len(chapters)}")
    print(f"  Range                    : Ch.{chapters[0]['num']} → Ch.{chapters[-1]['num']}")
    print(f"{'─'*55}")
    for ch in chapters[:6]:
        print(f"    Ch.{ch['num']:>6}  {ch['title'][:45]}")
    if len(chapters) > 6:
        print(f"    ... {len(chapters) - 6} more chapters ...")

    # Determine what to download
    if download_all or auto:
        # ── FIX: Download ALL chapters, not just 5 ──
        to_download = chapters
        print(f"\n[*] Downloading ALL {len(to_download)} chapters.")
    elif ch_range:
        ch_from, ch_to = ch_range
        to_download = filter_chapters(chapters, ch_from, ch_to)
        print(f"\n[*] Ch.{ch_from} → Ch.{ch_to} = {len(to_download)} chapters")
    else:
        print(f"\n  A = All {len(chapters)} chapters")
        print(f"  R = Range (e.g. 1 to 50)")
        print(f"  S = Single chapter")
        choice = ask_user("  Choice (A/R/S): ").upper()

        if choice == "A":
            to_download = chapters
        elif choice == "R":
            c1 = ask_user("  From chapter: ")
            c2 = ask_user("  To chapter  : ")
            try:
                to_download = filter_chapters(chapters, float(c1), float(c2))
            except ValueError:
                print("Invalid range.")
                return
        elif choice == "S":
            c1 = ask_user("  Chapter number: ")
            try:
                to_download = filter_chapters(chapters, float(c1), float(c1))
            except ValueError:
                print("Invalid chapter number.")
                return
        else:
            print("Invalid choice.")
            return

    if not to_download:
        print("✗ No chapters match that selection.")
        return

    manga_dir = OUTPUT_DIR / safe_name(manga["title"])
    manga_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[*] Output folder : {manga_dir.resolve()}")
    print(f"[*] Chapters      : {len(to_download)}")
    print(f"[*] Starting download...\n")

    success_count = 0
    fail_count    = 0

    for idx, ch in enumerate(to_download, 1):
        print(f"\n[{idx}/{len(to_download)}] Ch.{ch['num']} — {ch.get('title','')}")
        ok = download_chapter(manga, ch, manga_dir)
        if ok:
            success_count += 1
        else:
            fail_count += 1
        time.sleep(0.5)

    print(f"\n{'═'*55}")
    print(f"  ✔  Downloaded : {success_count} chapter(s)")
    if fail_count:
        print(f"  ✗  Failed     : {fail_count} chapter(s)")
    print(f"  📁 Saved to   : {manga_dir.resolve()}")
    print(f"{'═'*55}\n")

    if success_count > 0:
        print(f"SUCCESS: {success_count} chapters saved to {manga_dir.resolve()}")

# ─── SERVER MODE (for FastAPI integration) ────────────────────────────────────

def server_mode(title: str, all_chapters: bool = True, ch_range: tuple = None):
    """
    Called from server.py — streams output, downloads ALL chapters.
    """
    def log(msg):
        print(msg)
        sys.stdout.flush()

    log(f"INFO: [ORCHESTRATOR] Starting download: {title}")
    
    # Handle Master Keyword Array (Title|Alt1|Alt2)
    if "|" in title:
        variations = [t.strip() for t in title.split("|") if t.strip()]
        main_title = variations[0]
        log(f"INFO: [ORCHESTRATOR] Using AI Master List: {variations}")
    else:
        variations = generate_variations(title)
        main_title = title
        log(f"INFO: [ORCHESTRATOR] Searching variants: {variations}")

    all_results = []
    for src_name, src_obj in ALL_SOURCES.items():
        try:
            src_results = []
            for v in variations:
                res = src_obj.search(v)
                filtered = [r for r in res if is_manhwa(r['title'])]
                src_results.extend(filtered)
                if src_results: break
            
            seen = set()
            for r in src_results:
                key = r.get('url') or r.get('id')
                if key not in seen:
                    log(f"INFO: [{src_name.upper()}] Found valid result: {r['title']}")
                    all_results.append(r)
                    seen.add(key)
        except Exception as e:
            log(f"ERROR: [{src_name.upper()}] Search error: {e}")

    if not all_results:
        log(f"FAIL: No results found for '{title}' even with title variations.")
        sys.exit(1)

    # Auto-pick logic with deeper validation (check chapters)
    manga = None
    # Sort for best match first
    all_results.sort(key=lambda x: (normalize_title(main_title) != normalize_title(x['title']), x['source']))
    
    for candidate in all_results[:3]: # Check top 3 results
        log(f"INFO: Validating candidate: {candidate['title']} [{candidate['source']}]")
        src_obj = ALL_SOURCES[candidate['source']]
        try:
            url_or_id = candidate.get('url') or candidate['id']
            chaps = src_obj.get_chapters(url_or_id)
            if chaps and len(chaps) > 0:
                log(f"INFO: Selection confirmed! {len(chaps)} chapters found.")
                manga = candidate
                break
            else:
                log(f"WARN: Candidate {candidate['title']} has 0 chapters. Skipping...")
        except:
            continue

    if not manga:
        manga = all_results[0] # Fallback
        log(f"WARN: Selection unvalidated. Falling back to highest relevance: {manga['title']}")
    log(f"INFO: [ORCHESTRATOR] Selected: {manga['title']} [{manga['source']}]")

    src_name = manga["source"]
    source   = ALL_SOURCES[src_name]

    if src_name in ("mangadex", "comick"):
        chapters = source.get_chapters(manga["id"])
    else:
        chapters = source.get_chapters(manga.get("url", manga.get("id", "")))

    if not chapters:
        log(f"FAIL: No chapters found for '{manga['title']}'")
        sys.exit(1)

    if ch_range:
        to_download = filter_chapters(chapters, ch_range[0], ch_range[1])
    else:
        to_download = chapters

    log(f"INFO: [ORCHESTRATOR] {len(to_download)} chapters to download")

    manga_dir = OUTPUT_DIR / safe_name(manga["title"])
    manga_dir.mkdir(parents=True, exist_ok=True)

    ok_count = 0
    for idx, ch in enumerate(to_download, 1):
        log(f"DOWNLOAD: Chapter {ch['num']} ({idx}/{len(to_download)})")
        ok = download_chapter(manga, ch, manga_dir)
        if ok:
            ok_count += 1
        time.sleep(0.5)

    log(f"COMPLETE: {ok_count}/{len(to_download)} chapters saved to {manga_dir.resolve()}")
    if ok_count == 0:
        log("FAIL: Downloader yielded 0 complete chapters.")
        sys.exit(1)

# ─── CLI ENTRY POINT ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manhwa Downloader v3.0 — 5 Sources",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("title",   nargs="?", help="Manhwa title")
    parser.add_argument("--all",   action="store_true", help="Download all chapters")
    parser.add_argument("--ch",    nargs=2, metavar=("FROM", "TO"), help="Chapter range")
    parser.add_argument("--output",help="Output directory")
    parser.add_argument("--auto",  action="store_true", help="Auto-pick first result, download everything")
    parser.add_argument("--server",action="store_true", help="Server/dashboard mode (streamed output)")

    args = parser.parse_args()

    if args.output:
        OUTPUT_DIR = Path(args.output)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ch_range = None
    if args.ch:
        try:
            ch_range = (float(args.ch[0]), float(args.ch[1]))
        except ValueError:
            print("ERROR: --ch requires two numbers, e.g. --ch 1 50")
            sys.exit(1)

    try:
        if args.server and args.title:
            server_mode(args.title, all_chapters=args.all, ch_range=ch_range)
        else:
            run(
                title=args.title,
                download_all=args.all or args.auto,
                ch_range=ch_range,
                auto=args.auto,
            )
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted.")
        sys.exit(0)