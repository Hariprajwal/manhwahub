#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║         MANHWA DOWNLOADER v2.0               ║
║  Sources: MangaDex → ComicK → MangaNato      ║
║  Single file. Multiple fallbacks. Just works.║
╚══════════════════════════════════════════════╝

Usage:
  python manhwa_dl.py                          # Interactive mode
  python manhwa_dl.py "Solo Leveling"          # Search directly
  python manhwa_dl.py "Solo Leveling" --all    # Download all chapters
  python manhwa_dl.py "Solo Leveling" --ch 1 5 # Download chapters 1 to 5

Requirements (auto-installs if missing):
  pip install requests beautifulsoup4
"""

import sys
import os
import re
import time
import json
import shutil
import argparse
import subprocess
from pathlib import Path
from urllib.parse import quote, urljoin

# ─── AUTO INSTALL MISSING PACKAGES ───────────────────────────────────────────

def install_if_missing(package, import_name=None):
    """Install a package if it's not already installed."""
    import_name = import_name or package
    try:
        __import__(import_name)
        print(f"  ✓ {package}")
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://mangadex.org",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

OUTPUT_DIR = Path("manhwa_downloads")

# ─── UTILS ───────────────────────────────────────────────────────────────────

def safe_name(name: str) -> str:
    """Convert title to a safe folder/file name."""
    return re.sub(r'[<>:"/\\|?*]', '', name).strip().replace(' ', '_')

def download_image(url: str, save_path: Path, referer: str = "", retries: int = 3) -> bool:
    """Download a single image with retry logic."""
    headers = {**HEADERS}
    if referer:
        headers["Referer"] = referer

    for attempt in range(1, retries + 1):
        try:
            resp = SESSION.get(url, headers=headers, timeout=20, stream=True)
            resp.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            if attempt < retries:
                print(f"    ⚠ Retry {attempt}/{retries} for {save_path.name}...")
                time.sleep(1.5 * attempt)
            else:
                print(f"    ✗ Failed: {save_path.name} → {e}")
    return False

def progress_bar(current: int, total: int, prefix: str = "", width: int = 35):
    """Simple inline progress bar."""
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total)
    print(f"\r  {prefix} [{bar}] {pct}% ({current}/{total})", end="", flush=True)
    if current == total:
        print()  # newline at end

def ask_user(prompt: str) -> str:
    """Simple input wrapper."""
    try:
        return input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Cancelled.")
        sys.exit(0)

# ─── SOURCE 1: MANGADEX (PRIMARY) ────────────────────────────────────────────

class MangaDexSource:
    """
    Uses MangaDex's official REST API.
    Docs: https://api.mangadex.org
    Most reliable - no scraping, proper JSON API.
    """
    BASE   = "https://api.mangadex.org"
    IMGCDN = "https://uploads.mangadex.org"

    def search(self, title: str) -> list:
        """Search for manhwa/manga by title. Returns list of (id, title, status)."""
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
            data = r.json().get("data", [])

            results = []
            for item in data:
                mid   = item["id"]
                attrs = item["attributes"]
                # Get English title or fall back to first available
                titles = attrs.get("title", {})
                name   = titles.get("en") or next(iter(titles.values()), "Unknown")
                status = attrs.get("status", "?")
                results.append({"id": mid, "title": name, "status": status, "source": "mangadex"})
            return results
        except Exception as e:
            print(f"  [MangaDex] Search failed: {e}")
            return []

    def get_chapters(self, manga_id: str, lang: str = "en") -> list:
        """Get all chapters for a manga. Returns list sorted by chapter number."""
        print(f"[MangaDex] Fetching chapter list...")
        chapters = []
        offset   = 0
        limit    = 100

        while True:
            try:
                params = {
                    "manga": manga_id,
                    "translatedLanguage[]": [lang],
                    "limit": limit,
                    "offset": offset,
                    "order[chapter]": "asc",
                    "contentRating[]": ["safe", "suggestive", "erotica"],
                }
                r = SESSION.get(f"{self.BASE}/chapter", params=params, timeout=15)
                r.raise_for_status()
                data  = r.json()
                batch = data.get("data", [])
                if not batch:
                    break

                for ch in batch:
                    attrs = ch["attributes"]
                    ch_num = attrs.get("chapter") or "0"
                    title  = attrs.get("title") or f"Chapter {ch_num}"
                    chapters.append({
                        "id"    : ch["id"],
                        "num"   : ch_num,
                        "title" : title,
                        "pages" : attrs.get("pages", 0),
                    })

                offset += limit
                total   = data.get("total", 0)
                if offset >= total:
                    break
            except Exception as e:
                print(f"  [MangaDex] Chapter fetch error: {e}")
                break

        print(f"  Found {len(chapters)} chapters (lang={lang})")
        return chapters

    def get_page_urls(self, chapter_id: str) -> list:
        """Get all image URLs for a chapter."""
        try:
            r = SESSION.get(f"{self.BASE}/at-home/server/{chapter_id}", timeout=15)
            r.raise_for_status()
            data     = r.json()
            base_url = data["baseUrl"]
            ch_hash  = data["chapter"]["hash"]
            pages    = data["chapter"]["data"]  # high quality
            return [f"{base_url}/data/{ch_hash}/{p}" for p in pages]
        except Exception as e:
            print(f"  [MangaDex] Page URL error: {e}")
            return []

# ─── SOURCE 2: COMICK (FALLBACK 1) ───────────────────────────────────────────

class ComicKSource:
    """
    Uses ComicK's unofficial but stable JSON API.
    Good for manhwa specifically (Korean webtoons).
    """
    BASE = "https://api.comick.fun"

    def search(self, title: str) -> list:
        """Search ComicK."""
        print(f"\n[ComicK] Searching: '{title}'...")
        try:
            params = {"q": title, "limit": 10, "type": "comic"}
            r = SESSION.get(f"{self.BASE}/v1.0/search", params=params, timeout=15)
            r.raise_for_status()
            items = r.json()

            results = []
            for item in items:
                slug   = item.get("slug", "")
                hid    = item.get("hid", "")
                name   = item.get("title", "Unknown")
                status = str(item.get("status", "?"))
                results.append({
                    "id"    : hid,
                    "slug"  : slug,
                    "title" : name,
                    "status": status,
                    "source": "comick",
                })
            return results
        except Exception as e:
            print(f"  [ComicK] Search failed: {e}")
            return []

    def get_chapters(self, hid: str, lang: str = "en") -> list:
        """Get all chapters from ComicK."""
        print(f"[ComicK] Fetching chapter list...")
        chapters = []
        page     = 1

        while True:
            try:
                params = {"lang": lang, "page": page, "limit": 100, "ordering": "asc"}
                r = SESSION.get(f"{self.BASE}/comic/{hid}/chapters", params=params, timeout=15)
                r.raise_for_status()
                data  = r.json()
                batch = data.get("chapters", [])
                if not batch:
                    break

                for ch in batch:
                    ch_num = str(ch.get("chap") or "0")
                    title  = ch.get("title") or f"Chapter {ch_num}"
                    chapters.append({
                        "id"   : ch["hid"],
                        "num"  : ch_num,
                        "title": title,
                        "pages": ch.get("page_count", 0),
                    })
                page += 1
            except Exception as e:
                print(f"  [ComicK] Chapter page error: {e}")
                break

        print(f"  Found {len(chapters)} chapters")
        return chapters

    def get_page_urls(self, chapter_hid: str) -> list:
        """Get page image URLs from ComicK."""
        try:
            r = SESSION.get(f"{self.BASE}/chapter/{chapter_hid}", timeout=15)
            r.raise_for_status()
            data  = r.json()
            imgs  = data.get("chapter", {}).get("md_images", [])
            # ComicK uses b2 CDN
            base  = "https://meo.comick.pictures/"
            return [f"{base}{img['b2key']}" for img in imgs if img.get("b2key")]
        except Exception as e:
            print(f"  [ComicK] Page URL error: {e}")
            return []

# ─── SOURCE 3: MANGANATO (FALLBACK 2) ────────────────────────────────────────

class MangaNatoSource:
    """
    Scrapes MangaNato (also known as MangaKakalot).
    Pure HTML scraping — last resort fallback.
    """
    BASE     = "https://manganato.com"
    SEARCH   = "https://manganato.com/search/story/"

    def search(self, title: str) -> list:
        """Search MangaNato via scraping."""
        print(f"\n[MangaNato] Searching: '{title}'...")
        try:
            slug = quote(title.lower().replace(" ", "_"))
            url  = f"{self.SEARCH}{slug}"
            r    = SESSION.get(url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("div.search-story-item")

            results = []
            for item in items[:8]:
                a    = item.select_one("a.item-title") or item.select_one("h3 a")
                if not a:
                    continue
                name = a.get_text(strip=True)
                href = a.get("href", "")
                # Extract manga ID from URL
                mid  = href.rstrip("/").split("/")[-1]
                results.append({
                    "id"    : mid,
                    "url"   : href,
                    "title" : name,
                    "status": "?",
                    "source": "manganato",
                })
            return results
        except Exception as e:
            print(f"  [MangaNato] Search failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> list:
        """Scrape chapter list from MangaNato."""
        print(f"[MangaNato] Fetching chapter list...")
        try:
            r = SESSION.get(manga_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("li.a-h")  # chapter rows

            chapters = []
            for row in reversed(rows):  # reverse = ascending order
                a      = row.select_one("a.chapter-name")
                if not a:
                    continue
                href   = a.get("href", "")
                text   = a.get_text(strip=True)
                # Extract chapter number from text like "Chapter 10.5"
                m      = re.search(r"chapter[\s_-]*([\d.]+)", text, re.I)
                ch_num = m.group(1) if m else "0"
                chapters.append({
                    "id"   : href,   # URL is the ID for MangaNato
                    "url"  : href,
                    "num"  : ch_num,
                    "title": text,
                    "pages": 0,
                })
            print(f"  Found {len(chapters)} chapters")
            return chapters
        except Exception as e:
            print(f"  [MangaNato] Chapter fetch error: {e}")
            return []

    def get_page_urls(self, chapter_url: str) -> list:
        """Scrape image URLs from a MangaNato chapter page."""
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

# ─── DOWNLOAD ENGINE ──────────────────────────────────────────────────────────

def download_chapter(source, manga_info: dict, chapter: dict, manga_dir: Path) -> bool:
    """Download all pages of one chapter."""
    ch_num  = chapter["num"]
    ch_name = safe_name(f"Chapter_{str(ch_num).zfill(4)}")
    ch_dir  = manga_dir / ch_name

    if ch_dir.exists() and any(ch_dir.iterdir()):
        print(f"  ✓ {ch_name} already exists, skipping.")
        return True

    ch_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n  ⬇  {ch_name} — {chapter.get('title', '')}")

    # Get page URLs based on source type
    src_name = manga_info.get("source")
    ch_id    = chapter["id"]

    if src_name == "mangadex":
        urls = source.get_page_urls(ch_id)
        referer = "https://mangadex.org"
    elif src_name == "comick":
        urls = source.get_page_urls(ch_id)
        referer = "https://comick.fun"
    elif src_name == "manganato":
        urls = source.get_page_urls(chapter.get("url", ch_id))
        referer = "https://manganato.com"
    else:
        urls = []
        referer = ""

    if not urls:
        print(f"  ✗ No pages found for {ch_name}")
        shutil.rmtree(ch_dir, ignore_errors=True)
        return False

    success = 0
    for i, url in enumerate(urls, 1):
        ext  = url.split(".")[-1].split("?")[0] or "jpg"
        ext  = ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"
        name = f"{str(i).zfill(4)}.{ext}"
        path = ch_dir / name
        progress_bar(i - 1, len(urls), prefix=f"  Page {i}/{len(urls)}")
        ok = download_image(url, path, referer=referer)
        if ok:
            success += 1
        time.sleep(0.15)  # be polite, avoid rate limiting

    progress_bar(len(urls), len(urls), prefix=f"  Done        ")

    if success == 0:
        shutil.rmtree(ch_dir, ignore_errors=True)
        return False

    print(f"  ✔ {success}/{len(urls)} pages saved → {ch_dir}")
    return True

# ─── MAIN FLOW ────────────────────────────────────────────────────────────────

def pick_from_list(items: list, label: str) -> dict | None:
    """Let user pick one item from a numbered list."""
    if not items:
        return None
    print(f"\n{'─'*50}")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item['title']}  [{item.get('status','?')}]  ({item.get('source','')})")
    print(f"{'─'*50}")
    choice = ask_user(f"Pick a {label} (1-{len(items)}, or 0 to skip): ")
    if choice == "0" or not choice.isdigit():
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(items):
        return items[idx]
    return None

def filter_chapters(chapters: list, ch_from: float = None, ch_to: float = None) -> list:
    """Filter chapters by number range."""
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

def run(title: str = None, download_all: bool = False, ch_range: tuple = None):
    """Main orchestrator."""
    print("\n" + "═"*52)
    print("  🗒  MANHWA DOWNLOADER — 3-Source Fallback Mode")
    print("═"*52)

    # Initialize all 3 sources
    md_src  = MangaDexSource()
    ck_src  = ComicKSource()
    mn_src  = MangaNatoSource()

    # ── STEP 1: Get search title ───────────────────────────────────────────
    if not title:
        title = ask_user("\nEnter manhwa title to search: ")
    if not title:
        print("No title entered. Exiting.")
        return

    # ── STEP 2: Search all sources ─────────────────────────────────────────
    all_results = []

    md_results = md_src.search(title)
    if md_results:
        all_results.extend(md_results)

    ck_results = ck_src.search(title)
    if ck_results:
        all_results.extend(ck_results)

    mn_results = mn_src.search(title)
    if mn_results:
        all_results.extend(mn_results)

    if not all_results:
        print("\n✗ No results found from any source. Try a different title.")
        return

    print(f"\n✔ Found {len(all_results)} result(s) across all sources.")

    # ── STEP 3: User picks manga ───────────────────────────────────────────
    manga = pick_from_list(all_results, "manga")
    if not manga:
        print("Nothing selected.")
        return

    print(f"\n✔ Selected: {manga['title']} [{manga['source']}]")

    # ── STEP 4: Get chapters from correct source ───────────────────────────
    src_name = manga["source"]
    chapters = []

    if src_name == "mangadex":
        chapters = md_src.get_chapters(manga["id"])
        active_src = md_src
    elif src_name == "comick":
        chapters = ck_src.get_chapters(manga["id"])
        active_src = ck_src
    elif src_name == "manganato":
        chapters = mn_src.get_chapters(manga.get("url", ""))
        active_src = mn_src

    if not chapters:
        print("✗ No chapters found. Try a different source.")
        return

    # ── STEP 5: Show chapter list ──────────────────────────────────────────
    print(f"\n{'─'*52}")
    print(f"  Chapters available: {len(chapters)}")
    print(f"  Range: Ch.{chapters[0]['num']} → Ch.{chapters[-1]['num']}")
    print(f"{'─'*52}")

    # Show first few and last few chapters
    preview = chapters[:5] + (chapters[-3:] if len(chapters) > 5 else [])
    for ch in chapters[:8]:
        print(f"    Ch.{ch['num']:>6}  {ch['title'][:40]}")
    if len(chapters) > 8:
        print(f"    ... {len(chapters) - 8} more chapters ...")

    # ── STEP 6: Decide which chapters to download ──────────────────────────
    if download_all:
        to_download = chapters
        print(f"\n[*] Will download ALL {len(to_download)} chapters.")
    elif ch_range:
        ch_from, ch_to = ch_range
        to_download = filter_chapters(chapters, ch_from, ch_to)
        print(f"\n[*] Will download Ch.{ch_from} → Ch.{ch_to} ({len(to_download)} chapters)")
    else:
        print(f"\n  Options:")
        print(f"  A = Download ALL chapters")
        print(f"  R = Download a RANGE of chapters")
        print(f"  S = Download SINGLE chapter")
        choice = ask_user("  Your choice (A/R/S): ").upper()

        if choice == "A":
            to_download = chapters
        elif choice == "R":
            c1 = ask_user(f"  Start chapter (e.g. 1): ")
            c2 = ask_user(f"  End chapter (e.g. 50): ")
            to_download = filter_chapters(chapters, float(c1), float(c2))
        elif choice == "S":
            c1 = ask_user(f"  Chapter number: ")
            to_download = filter_chapters(chapters, float(c1), float(c1))
        else:
            print("Invalid choice.")
            return

    if not to_download:
        print("✗ No chapters match that range.")
        return

    # ── STEP 7: Download ───────────────────────────────────────────────────
    manga_dir = OUTPUT_DIR / safe_name(manga["title"])
    manga_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[*] Saving to: {manga_dir.resolve()}")
    print(f"[*] Starting download of {len(to_download)} chapter(s)...\n")

    success_count = 0
    fail_count    = 0

    for idx, ch in enumerate(to_download, 1):
        print(f"\n[{idx}/{len(to_download)}] Ch.{ch['num']} — {ch['title']}")
        ok = download_chapter(active_src, manga, ch, manga_dir)
        if ok:
            success_count += 1
        else:
            fail_count += 1
        time.sleep(0.5)  # brief pause between chapters

    # ── STEP 8: Summary ────────────────────────────────────────────────────
    print(f"\n{'═'*52}")
    print(f"  ✔ Downloaded : {success_count} chapter(s)")
    if fail_count:
        print(f"  ✗ Failed     : {fail_count} chapter(s)")
    print(f"  📁 Saved to  : {manga_dir.resolve()}")
    print(f"{'═'*52}\n")


# ─── CLI ENTRY POINT ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manhwa Downloader — MangaDex + ComicK + MangaNato",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("title",  nargs="?", help="Manhwa title to search")
    parser.add_argument("--all",  action="store_true", help="Download all chapters")
    parser.add_argument("--ch",   nargs=2, metavar=("FROM", "TO"), help="Chapter range")
    parser.add_argument("--output", help="Custom output directory")
    parser.add_argument("--auto", action="store_true", help="Auto-pick first search result")

    args = parser.parse_args()

    if args.output:
        OUTPUT_DIR = Path(args.output)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ch_range = None
    if args.ch:
        ch_range = (float(args.ch[0]), float(args.ch[1]))

    try:
        if args.auto and args.title:
            # DASHBOARD INTEGRATION MODE
            print(f"[*] DASHBOARD-MODE: Searching for '{args.title}'...")
            md_src, ck_src, mn_src = MangaDexSource(), ComicKSource(), MangaNatoSource()
            
            # Aggregate search results
            all_res = md_src.search(args.title) + ck_src.search(args.title) + mn_src.search(args.title)
            if not all_res:
                print("✗ No results found across any source.")
                sys.exit(1)
            
            manga = all_res[0] # Pick the first/best match
            print(f"✔ Auto-selected: {manga['title']} from {manga['source']}")
            
            # Fetch chapters
            if manga["source"] == "mangadex":
                chapters = md_src.get_chapters(manga["id"])
                active_src = md_src
            elif manga["source"] == "comick":
                chapters = ck_src.get_chapters(manga["id"])
                active_src = ck_src
            else:
                chapters = mn_src.get_chapters(manga.get("url", ""))
                active_src = mn_src
            
            # Determine range
            to_download = filter_chapters(chapters, ch_range[0] if ch_range else None, ch_range[1] if ch_range else None) if ch_range else chapters
            if not args.all and not ch_range:
                to_download = chapters[:100] # Default to first 5 for preview in auto mode
                print("[*] Downloading first 5 chapters for preview...")
            
            manga_dir = OUTPUT_DIR / safe_name(manga["title"])
            manga_dir.mkdir(parents=True, exist_ok=True)
            
            for idx, ch in enumerate(to_download, 1):
                print(f"\n[{idx}/{len(to_download)}] Ch.{ch['num']} — {ch['title']}")
                download_chapter(active_src, manga, ch, manga_dir)
            
            print(f"SUCCESS: Operation finished. Panels saved to {manga_dir.resolve()}")
        else:
            # Standard Interactive Mode
            run(title=args.title, download_all=args.all, ch_range=ch_range)
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted. Exiting.")
        sys.exit(0)