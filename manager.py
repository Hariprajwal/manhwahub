import os
import sys
import re
import time
import random
import subprocess
import requests
from pathlib import Path
from rich.console import Console

console = Console()

# ─── HEADERS ────────────────────────────────────────────────────────────────
# This is the #1 fix. Without these, every manhwa site blocks you immediately.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ─── RETRY CONFIG ───────────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0   # seconds — doubles each attempt
RETRY_JITTER = 0.5         # random ± jitter to avoid thundering herd
STRATEGY_DELAY = (2.0, 4.0)  # random sleep between strategy attempts


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def retry_sleep(attempt: int):
    """Exponential backoff with jitter."""
    delay = RETRY_BACKOFF_BASE ** attempt + random.uniform(-RETRY_JITTER, RETRY_JITTER)
    delay = max(0.5, delay)
    return delay


class ManhwaOrchestrator:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or os.getcwd())
        self.repo_dir = self.base_dir / "temp_repos"
        self.download_dir = self.base_dir / "downloads"
        self.download_dir.mkdir(exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # CORE: run a subprocess and stream its output line by line.
    # BUG FIX: The old version used "return True/False" inside a generator,
    # which Python silently ignores. We now track success via a mutable list
    # so the caller can check it after iteration finishes.
    # ─────────────────────────────────────────────────────────────────────────
    def run_command_stream(self, cmd, cwd, success_flag: list):
        """
        Yields output lines. Writes True/False into success_flag[0] when done.
        Usage:
            flag = [False]
            for line in self.run_command_stream(cmd, cwd, flag):
                yield line
            if flag[0]: ...
        """
        try:
            full_cmd = [sys.executable] + cmd
            yield f"INFO: Executing: {' '.join(str(c) for c in cmd)}\n"

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                full_cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                encoding="utf-8",
                errors="ignore"
            )

            for line in process.stdout:
                yield line

            process.wait()

            if process.returncode == 0:
                yield "SUCCESS: Tool execution finished.\n"
                success_flag[0] = True
            else:
                yield f"ERROR: Tool exited with code {process.returncode}\n"
                success_flag[0] = False

        except FileNotFoundError:
            yield f"ERROR: Script not found at {cwd / cmd[0]}\n"
            success_flag[0] = False
        except Exception as e:
            yield f"CRITICAL: {str(e)}\n"
            success_flag[0] = False

    # ─────────────────────────────────────────────────────────────────────────
    # STRATEGY: NEW-MANWA.PY multi-source engine
    # ─────────────────────────────────────────────────────────────────────────
    def download_manwa_engine(self, title_list, ch_range=None):
        title_query = "|".join(title_list) if isinstance(title_list, list) else title_list
        cmd = ["-u", "NEW-MANWA.PY", title_query, "--server", "--auto",
               "--output", str(self.download_dir)]
        if ch_range:
            cmd.extend(["--ch", str(ch_range[0]), str(ch_range[1])])

        flag = [False]
        yield from self.run_command_stream(cmd, self.base_dir, flag)
        # Expose result so orchestrator can read it
        self._last_flag = flag[0]

    # Removed fake URL heuristic scrapers. NEW-MANWA.PY handles exhaustive multi-source properly.

    # ─────────────────────────────────────────────────────────────────────────
    # DIRECT IMAGE DOWNLOADER (used as a last-resort fallback)
    # Fetches images directly with proper headers + per-image retry.
    # Skips files already on disk (deduplication).
    # ─────────────────────────────────────────────────────────────────────────
    def download_images_direct(self, image_urls: list, folder: Path):
        """
        Downloads a list of image URLs into `folder` with:
          - Proper browser headers
          - Per-image retry (up to MAX_RETRIES)
          - Skip if file already exists (deduplication)
        Yields log lines.
        """
        folder.mkdir(parents=True, exist_ok=True)
        saved = 0
        skipped = 0
        failed = 0

        session = requests.Session()
        session.headers.update(HEADERS)

        for i, url in enumerate(image_urls):
            ext = url.split("?")[0].rsplit(".", 1)[-1]
            ext = ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"
            filename = folder / f"{i+1:04d}.{ext}"

            # Deduplication: skip if already downloaded
            if filename.exists() and filename.stat().st_size > 1024:
                yield f"SKIP: {filename.name} already exists.\n"
                skipped += 1
                continue

            success = False
            for attempt in range(MAX_RETRIES):
                try:
                    resp = session.get(url, timeout=20, stream=True)
                    if resp.status_code == 200:
                        with open(filename, "wb") as f:
                            for chunk in resp.iter_content(8192):
                                f.write(chunk)
                        yield f"SAVED: {filename.name}\n"
                        saved += 1
                        success = True

                        # Polite delay between images
                        time.sleep(random.uniform(0.3, 0.8))
                        break

                    elif resp.status_code in (429, 503):
                        wait = retry_sleep(attempt)
                        yield f"WARN: Rate limited ({resp.status_code}). Waiting {wait:.1f}s...\n"
                        time.sleep(wait)

                    else:
                        yield f"WARN: HTTP {resp.status_code} for {url}\n"
                        time.sleep(retry_sleep(attempt))

                except requests.exceptions.RequestException as e:
                    wait = retry_sleep(attempt)
                    yield f"WARN: Request error ({e}). Retry {attempt+1}/{MAX_RETRIES} in {wait:.1f}s...\n"
                    time.sleep(wait)

            if not success:
                yield f"ERROR: Failed to download image {i+1} after {MAX_RETRIES} attempts.\n"
                failed += 1

        self._last_flag = saved > 0
        yield f"INFO: Direct download complete — {saved} saved, {skipped} skipped, {failed} failed.\n"

    # ─────────────────────────────────────────────────────────────────────────
    # ORCHESTRATOR
    # BUG FIX: success is now read from self._last_flag (set by each strategy),
    # NOT from grep-ing the text stream for the word "SUCCESS:".
    # Also adds a polite random delay between strategy attempts.
    # ─────────────────────────────────────────────────────────────────────────
    def orchestrate_stream(self, title_input, ch_range=None):
        if isinstance(title_input, list):
            main_title = title_input[0]
            master_list = title_input
        else:
            main_title = title_input
            master_list = [title_input]

        title_slug = slugify(main_title)
        yield f"DEBUG: Slugified '{main_title}' → '{title_slug}'\n"

        strategies = [
            ("5-Source Engine (NEW-MANWA.PY)",
             lambda: self.download_manwa_engine(master_list, ch_range=ch_range)),
        ]

        yield f"START: Orchestration for '{main_title}' | Range: {ch_range}\n"

        results = []
        overall_success = False
        self._last_flag = False

        for idx, (name, strategy_fn) in enumerate(strategies):
            if idx > 0:
                # Polite delay between attempts — prevents IP bans from burst traffic
                wait = random.uniform(*STRATEGY_DELAY)
                yield f"INFO: Waiting {wait:.1f}s before next strategy...\n"
                time.sleep(wait)

            yield f"STRATEGY: [{idx+1}/{len(strategies)}] Attempting {name}...\n"
            self._last_flag = False

            try:
                for line in strategy_fn():
                    yield line
            except Exception as e:
                yield f"ERROR: Strategy '{name}' threw an exception: {e}\n"
                self._last_flag = False

            # Read actual success from flag, not from text parsing
            if self._last_flag:
                results.append((name, "SUCCESS"))
                overall_success = True
                yield f"COMPLETE: '{name}' succeeded!\n"
                break
            else:
                results.append((name, "FAILED"))
                yield f"RETRY: '{name}' failed. Trying next strategy...\n"

        if not overall_success:
            yield "FAIL: All strategies exhausted. No panels downloaded.\n"

        yield "\n========================================\n"
        yield "DOWNLOAD PIPELINE SUMMARY:\n"
        for name, status in results:
            icon = "✓" if status == "SUCCESS" else "✗"
            yield f"  [{icon}] {name}: {status}\n"
        tried = len(results)
        for name, _ in strategies[tried:]:
            yield f"  [-] {name}: SKIPPED\n"
        yield "========================================\n"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[bold red]Usage: python manager.py <manhwa-title>[/bold red]")
        sys.exit(1)

    slug = sys.argv[1]
    orchestrator = ManhwaOrchestrator()
    for line in orchestrator.orchestrate_stream(slug):
        console.print(line.strip())