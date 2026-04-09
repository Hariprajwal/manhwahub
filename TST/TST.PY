"""
omni_scraper.py
===============
Multi-site Manga/Manhwa Chapter Image Scraper
Supports: Lazy Load Attribute Scan (fast) + Headless Playwright fallback (slow but thorough)

Sites covered:
  1. Asura Scans        (asuracomic.net)
  2. Reaper Scans       (reaperscans.com)
  3. Flame Scans        (flamecomics.xyz)
  4. Luminous Scans     (luminousscans.com)
  5. MangaKakalot       (mangakakalot.com)
  6. MangaNato          (chapmanganato.to)
  7. MangaDex           (mangadex.org)  — uses their JSON API
  8. Webtoon            (webtoons.com)
  9. Void Scans         (void-scans.com)
 10. Manganato          (manganato.com)
 11. Zero Scans         (zeroscans.com)
 12. Bato.to            (bato.to)
 13. ComicK             (comick.io)      — uses their JSON API
 14. NightScans         (nightscans.net)
 15. IsekaiScan         (isekaiscan.com)

Usage:
    python omni_scraper.py <chapter_url>

Requirements:
    pip install requests beautifulsoup4 playwright
    playwright install chromium
"""

import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from functools import cached_property
from urllib.parse import urlparse, urljoin

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

# Common lazy-load attribute names used across Madara/custom themes
LAZY_ATTRS = [
    "data-src",
    "data-lazy-src",
    "data-srcset",
    "data-original",
    "orig-src",
    "data-url",
    "data-image",
    "data-cfsrc",          # Cloudflare lazy
    "data-lazyload",
    "data-hi-res-src",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://google.com",
}


# ─────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────

def get_soup(url: str, extra_headers: dict = None) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object."""
    print(f"[HTTP] Fetching: {url}")
    h = {**HEADERS, **(extra_headers or {})}
    resp = requests.get(url, headers=h, timeout=20)
    resp.raise_for_status()
    print(f"[HTTP] Status {resp.status_code} — {len(resp.content)} bytes")
    return BeautifulSoup(resp.text, "html.parser")


def extract_lazy_src(img_tag) -> str | None:
    """
    Strategy 1 — Attribute Scan.
    Tries all known lazy-load attributes before falling back to real src.
    Returns the first non-empty, non-placeholder URL found.
    """
    for attr in LAZY_ATTRS:
        val = img_tag.get(attr, "").strip()
        if val and not val.startswith("data:"):   # skip base64 placeholders
            # srcset may have "url 1x, url2 2x" — take first
            return val.split(",")[0].split(" ")[0]
    return img_tag.get("src", "").strip() or None


def filter_images(urls: list[str], min_width_hint: int = 200) -> list[str]:
    """
    Remove obvious junk: empty strings, base64 blobs, tiny icons.
    (We can't know real dimensions without downloading, so filter by URL patterns.)
    """
    bad_patterns = ["logo", "icon", "avatar", "banner", "ads", "spinner", "loading"]
    clean = []
    for u in urls:
        if not u:
            continue
        if u.startswith("data:"):
            continue
        if any(p in u.lower() for p in bad_patterns):
            continue
        clean.append(u)
    print(f"[FILTER] {len(urls)} raw → {len(clean)} after cleanup")
    return clean


def headless_scroll_and_rip(url: str, site_name: str) -> list[str]:
    """
    Strategy 2 — Headless Playwright Scroll.
    Use when simple HTTP fetch returns placeholder images.
    Scrolls to bottom, waits for network idle, then rips rendered src values.
    """
    print(f"[PLAYWRIGHT] Launching headless browser for {site_name}...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    images = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers=HEADERS)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        print("[PLAYWRIGHT] Scrolling page to trigger lazy load...")
        # Scroll in steps to trigger Intersection Observers
        page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    let total = document.body.scrollHeight;
                    let step = window.innerHeight;
                    let pos = 0;
                    const timer = setInterval(() => {
                        window.scrollTo(0, pos);
                        pos += step;
                        if (pos >= total) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 300);
                });
            }
        """)
        page.wait_for_load_state("networkidle", timeout=15000)
        print("[PLAYWRIGHT] Scroll done. Ripping image src values...")

        # Grab all rendered src attributes
        images = page.eval_on_selector_all(
            "img",
            "imgs => imgs.map(img => img.src).filter(s => s && !s.startsWith('data:'))"
        )
        browser.close()

    print(f"[PLAYWRIGHT] Found {len(images)} images")
    return images


# ─────────────────────────────────────────────
# LAZY CHAPTER CLASS (cached_property pattern)
# ─────────────────────────────────────────────

class ManhwaChapter:
    """
    Represents a single chapter.
    Uses @cached_property so panels are only fetched once,
    even if you call `chapter.panels` multiple times.
    """

    def __init__(self, url: str, site_name: str, scrape_fn):
        self.url = url
        self.site_name = site_name
        self._scrape_fn = scrape_fn  # function(url) -> list[str]

    @cached_property
    def panels(self) -> list[str]:
        print(f"[CHAPTER] Fetching panels for: {self.site_name}")
        result = self._scrape_fn(self.url)
        print(f"[CHAPTER] Total panels fetched: {len(result)}")
        return result

    def panels_lazy(self):
        """
        Generator method — yields one panel URL at a time.
        Useful if you want to start downloading before all URLs are scraped.
        """
        for url in self.panels:
            yield url


# ─────────────────────────────────────────────
# SITE SCRAPERS
# ─────────────────────────────────────────────

# --- 1. ASURA SCANS (asuracomic.net) ---
def scrape_asura(url: str) -> list[str]:
    """Asura uses Madara theme. Images in div.reading-content with data-src."""
    print("[ASURA] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://asuracomic.net/"})
    imgs = soup.select("div.reading-content img, div#readerarea img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 2. REAPER SCANS (reaperscans.com) ---
def scrape_reaper(url: str) -> list[str]:
    """Reaper uses a Next.js frontend. Images often in JSON props or standard img tags."""
    print("[REAPER] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://reaperscans.com/"})
    # Try standard reading container first
    imgs = soup.select("div.overflow-hidden img, main img")
    urls = [extract_lazy_src(i) for i in imgs]
    cleaned = filter_images([u for u in urls if u])
    if not cleaned:
        print("[REAPER] No static images found — falling back to Playwright...")
        cleaned = headless_scroll_and_rip(url, "Reaper Scans")
    return filter_images(cleaned)


# --- 3. FLAME SCANS / FLAME COMICS (flamecomics.xyz) ---
def scrape_flame(url: str) -> list[str]:
    """Flame uses Madara theme."""
    print("[FLAME] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://flamecomics.xyz/"})
    imgs = soup.select("div.reading-content img, div#readerarea img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 4. LUMINOUS SCANS (luminousscans.com) ---
def scrape_luminous(url: str) -> list[str]:
    """Luminous uses Madara theme."""
    print("[LUMINOUS] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://luminousscans.com/"})
    imgs = soup.select("div.reading-content img, div#readerarea img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 5. MANGAKAKALOT (mangakakalot.com) ---
def scrape_mangakakalot(url: str) -> list[str]:
    """MangaKakalot uses straightforward img tags inside div.container-chapter-reader."""
    print("[MANGAKAKALOT] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://mangakakalot.com/"})
    imgs = soup.select("div.container-chapter-reader img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 6. CHAPMANGANATO / MANGANATO (chapmanganato.to) ---
def scrape_manganato(url: str) -> list[str]:
    """MangaNato puts images in div.container-chapter-reader same as Kakalot."""
    print("[MANGANATO] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://chapmanganato.to/"})
    imgs = soup.select("div.container-chapter-reader img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 7. MANGADEX (mangadex.org) — JSON API ---
def scrape_mangadex(url: str) -> list[str]:
    """
    MangaDex has a proper REST API.
    Chapter URL format: https://mangadex.org/chapter/<chapter_id>
    We extract the chapter ID and call the /at-home/server endpoint.
    """
    print("[MANGADEX] Starting API scrape...")
    # Extract chapter UUID from URL
    match = re.search(r"chapter/([a-f0-9\-]{36})", url)
    if not match:
        print("[MANGADEX] ERROR: Could not extract chapter ID from URL")
        return []

    chapter_id = match.group(1)
    print(f"[MANGADEX] Chapter ID: {chapter_id}")

    api_url = f"https://api.mangadex.org/at-home/server/{chapter_id}"
    resp = requests.get(api_url, timeout=15)
    data = resp.json()

    base_url = data["baseUrl"]
    chapter_hash = data["chapter"]["hash"]
    filenames = data["chapter"]["data"]   # high quality

    urls = [f"{base_url}/data/{chapter_hash}/{f}" for f in filenames]
    print(f"[MANGADEX] Found {len(urls)} panels via API")
    return urls


# --- 8. WEBTOON (webtoons.com) ---
def scrape_webtoon(url: str) -> list[str]:
    """
    Webtoon needs a special Referer header. Images are in div#_imageList img.
    """
    print("[WEBTOON] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://www.webtoons.com/"})
    imgs = soup.select("div#_imageList img, div.viewer_lst img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 9. VOID SCANS (void-scans.com) ---
def scrape_void(url: str) -> list[str]:
    """Void Scans uses Madara-like theme."""
    print("[VOID SCANS] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://void-scans.com/"})
    imgs = soup.select("div.reading-content img, div#readerarea img, div.chapter-content img")
    urls = [extract_lazy_src(i) for i in imgs]
    cleaned = filter_images([u for u in urls if u])
    if not cleaned:
        print("[VOID SCANS] Falling back to Playwright...")
        cleaned = headless_scroll_and_rip(url, "Void Scans")
    return filter_images(cleaned)


# --- 10. ZERO SCANS (zeroscans.com) ---
def scrape_zero(url: str) -> list[str]:
    """Zero Scans is React-based — almost always needs Playwright."""
    print("[ZERO SCANS] This site is React-based, using Playwright...")
    imgs = headless_scroll_and_rip(url, "Zero Scans")
    return filter_images(imgs)


# --- 11. BATO.TO (bato.to) ---
def scrape_bato(url: str) -> list[str]:
    """
    Bato.to encodes image URLs in a JavaScript variable inside a <script> tag.
    We parse it with regex.
    """
    print("[BATO.TO] Starting scrape (script tag parsing)...")
    soup = get_soup(url, {"Referer": "https://bato.to/"})
    scripts = soup.find_all("script")

    for script in scripts:
        if script.string and "imgHttps" in script.string:
            # Regex to find the array of image URLs
            matches = re.findall(r'["\'](https://[^"\']+\.(?:jpg|jpeg|png|webp))["\']', script.string)
            if matches:
                print(f"[BATO.TO] Found {len(matches)} panel URLs in script")
                return filter_images(matches)

    # Fallback: try img tags
    print("[BATO.TO] Script parse failed, trying img tags...")
    imgs = soup.select("div.chapter-images img, div#viewer img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 12. COMICK (comick.io) — JSON API ---
def scrape_comick(url: str) -> list[str]:
    """
    ComicK has a public API.
    Chapter URL: https://comick.io/comic/<slug>/<chapter_hid>-chapter-N
    We extract hid and call /chapter/{hid} endpoint.
    """
    print("[COMICK] Starting API scrape...")
    # Extract chapter hid (alphanumeric slug before "-chapter")
    match = re.search(r"/([A-Za-z0-9]+)-chapter-", url)
    if not match:
        print("[COMICK] ERROR: Could not extract chapter HID")
        return []

    hid = match.group(1)
    print(f"[COMICK] Chapter HID: {hid}")

    api_url = f"https://api.comick.io/chapter/{hid}/get_images"
    resp = requests.get(api_url, headers=HEADERS, timeout=15)
    data = resp.json()

    urls = []
    for item in data:
        if "url" in item:
            urls.append(item["url"])
        elif "b2key" in item:
            urls.append(f"https://meo.comick.pictures/{item['b2key']}")

    print(f"[COMICK] Found {len(urls)} panels via API")
    return filter_images(urls)


# --- 13. NIGHT SCANS (nightscans.net) ---
def scrape_nightscans(url: str) -> list[str]:
    """Night Scans uses Madara theme."""
    print("[NIGHTSCANS] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://nightscans.net/"})
    imgs = soup.select("div.reading-content img, div#readerarea img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 14. ISEKAI SCAN (isekaiscan.com) ---
def scrape_isekaiscan(url: str) -> list[str]:
    """Isekai Scan uses Madara theme."""
    print("[ISEKAISCAN] Starting scrape...")
    soup = get_soup(url, {"Referer": "https://isekaiscan.com/"})
    imgs = soup.select("div.reading-content img, div#readerarea img")
    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# --- 15. MANGAS.IN / GENERIC MADARA FALLBACK ---
def scrape_madara_generic(url: str) -> list[str]:
    """
    Generic scraper for any WordPress Madara theme site.
    Works for: mangas.in, manga-scans.com, etc.
    Tries all common Madara selectors.
    """
    print("[MADARA-GENERIC] Starting scrape...")
    soup = get_soup(url)
    selectors = [
        "div.reading-content img",
        "div#readerarea img",
        "div.chapter-content img",
        "div.page-break img",
        "div.wp-manga-chapter-img img",
        "img.wp-manga-chapter-img",
    ]
    imgs = []
    for sel in selectors:
        found = soup.select(sel)
        if found:
            print(f"[MADARA-GENERIC] Matched selector: {sel} ({len(found)} imgs)")
            imgs = found
            break

    urls = [extract_lazy_src(i) for i in imgs]
    return filter_images([u for u in urls if u])


# ─────────────────────────────────────────────
# SITE ROUTER
# ─────────────────────────────────────────────

SITE_MAP = {
    "asuracomic.net":       scrape_asura,
    "reaperscans.com":      scrape_reaper,
    "flamecomics.xyz":      scrape_flame,
    "luminousscans.com":    scrape_luminous,
    "mangakakalot.com":     scrape_mangakakalot,
    "chapmanganato.to":     scrape_manganato,
    "manganato.com":        scrape_manganato,
    "mangadex.org":         scrape_mangadex,
    "webtoons.com":         scrape_webtoon,
    "void-scans.com":       scrape_void,
    "zeroscans.com":        scrape_zero,
    "bato.to":              scrape_bato,
    "comick.io":            scrape_comick,
    "nightscans.net":       scrape_nightscans,
    "isekaiscan.com":       scrape_isekaiscan,
}


def get_scraper(url: str):
    """
    Detects which site the URL belongs to and returns
    the appropriate scraper function.
    Falls back to generic Madara scraper if site is unknown.
    """
    domain = urlparse(url).netloc.replace("www.", "")
    print(f"[ROUTER] Detected domain: {domain}")

    for key, fn in SITE_MAP.items():
        if key in domain:
            print(f"[ROUTER] Matched site: {key}")
            return fn

    print(f"[ROUTER] Unknown site '{domain}' — using generic Madara scraper")
    return scrape_madara_generic


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def scrape_chapter(url: str) -> ManhwaChapter:
    """
    Main function.
    Returns a ManhwaChapter object with lazy-loaded panels.
    """
    scraper_fn = get_scraper(url)
    domain = urlparse(url).netloc
    chapter = ManhwaChapter(url=url, site_name=domain, scrape_fn=scraper_fn)
    return chapter


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python omni_scraper.py <chapter_url>")
        print("\nSupported sites:")
        for site in SITE_MAP:
            print(f"  - {site}")
        sys.exit(1)

    chapter_url = sys.argv[1]
    print(f"\n{'='*50}")
    print(f"omni_scraper.py — Starting")
    print(f"URL: {chapter_url}")
    print(f"{'='*50}\n")

    chapter = scrape_chapter(chapter_url)

    # Access panels — this triggers the scrape (lazy via @cached_property)
    panels = chapter.panels

    print(f"\n{'='*50}")
    print(f"Results: {len(panels)} panel(s) found")
    print(f"{'='*50}")

    # Print results or feed into your pipeline
    for i, panel_url in enumerate(chapter.panels_lazy(), start=1):
        print(f"  Panel {i:03d}: {panel_url}")