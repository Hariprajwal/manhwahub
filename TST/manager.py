import os
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

console = Console()

import re

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text).strip('-')
    return text

class ManhwaOrchestrator:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or os.getcwd())
        self.repo_dir = self.base_dir / "temp_repos"
        self.download_dir = self.base_dir / "downloads"
        self.download_dir.mkdir(exist_ok=True)

    def run_command_stream(self, cmd, cwd):
        """Yields output line by line for SSE."""
        try:
            full_cmd = [sys.executable] + cmd
            yield f"INFO: Executing {' '.join(cmd)}\n"
            
            # Setup environment for UTF-8 to prevent Windows UnicodeEncodeError
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            process = subprocess.Popen(
                full_cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )
            
            for line in process.stdout:
                yield line
                
            process.wait()
            if process.returncode == 0:
                yield "SUCCESS: Tool execution finished.\n"
                return True
            else:
                yield f"ERROR: Tool failed with code {process.returncode}\n"
                return False
        except Exception as e:
            yield f"CRITICAL: {str(e)}\n"
            return False

    def download_asura(self, title_slug):
        # Fallback to AIO for Asura as the specialized tool is menu-only
        yield "INFO: Transitioning to AIO for Asura source...\n"
        yield from self.download_aio(title_slug)

    def download_comick(self, title_slug):
        url = f"https://comick.io/comic/{title_slug}"
        # Comick downloader uses -o for output
        cmd = ["cli/main.py", "download", url, "-o", str(self.download_dir)]
        cwd = self.repo_dir / "comick_downloader"
        yield from self.run_command_stream(cmd, cwd)

    def download_aio(self, title_slug):
        # AIO uses [urls] as positional arguments and -o for output dir
        # Updated for 2026: Asura transitioned to asurascans.com and uses long hids
        if "solo-leveling" in title_slug:
            url = "https://asurascans.com/comics/solo-leveling-75e30c62"
        else:
            url = f"https://asurascans.com/comics/{title_slug}"
            
        cmd = ["aio-dl.py", "-o", str(self.download_dir), url]
        cwd = self.repo_dir / "AIO-Webtoon-Downloader"
        yield from self.run_command_stream(cmd, cwd)

    def download_manwa_engine(self, title_name):
        """Uses the high-powered 5-source NEW-MANWA.PY engine (v3.0)."""
        # Using -u for unbuffered output to ensure live logs in UI
        cmd = ["-u", "NEW-MANWA.PY", title_name, "--server", "--auto", "--output", str(self.download_dir)]
        cwd = self.base_dir
        return self.run_command_stream(cmd, cwd)

    def orchestrate_stream(self, title_input):
        title_slug = slugify(title_input)
        yield f"DEBUG: Slugified '{title_input}' to '{title_slug}'\n"
        
        strategies = [
            ("NEW_MANWA_PY (5-Source Fallback)", lambda t: self.download_manwa_engine(title_input)),
            ("Asura Specialized", lambda t: self.download_asura(title_slug)),
            ("Comick Specialized", lambda t: self.download_comick(title_slug)),
            ("AIO Webtoon Downloader", lambda t: self.download_aio(title_slug))
        ]

        yield f"START: Download Orchestration for '{title_input}'\n"

        for name, strategy_fn in strategies:
            yield f"STRATEGY: Attempting {name}...\n"
            success = False
            for line in strategy_fn(title_input):
                yield line
                if "SUCCESS:" in line:
                    success = True
            
            if success:
                yield f"COMPLETE: Download successful via {name}!\n"
                return
            else:
                yield f"RETRY: {name} failed. Moving to next strategy...\n"

        yield "FAIL: All strategies exhausted. No panels downloaded.\n"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[bold red]Usage: python manager.py <manhwa-slug>[/bold red]")
        sys.exit(1)
    
    slug = sys.argv[1]
    orchestrator = ManhwaOrchestrator()
    # Handle the generator for CLI output
    for line in orchestrator.orchestrate_stream(slug):
        console.print(line.strip())
