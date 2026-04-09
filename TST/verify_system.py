import os
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()

def verify_setup():
    console.print("[bold blue]Starting Manhwa Hub System Verification...[/bold blue]\n")
    
    # 1. Check Directories
    dirs_to_check = ["temp_repos", "downloads"]
    repos_to_check = [
        "asuracomic_downloader", "comick_downloader", "AIO-Webtoon-Downloader",
        "mihon", "hakuneko", "manhwa-downloader", "seanime", "Kotatsu", "yokai", "comic-downloader"
    ]
    
    table = Table(title="System Integrity Check")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    
    # Check main folders
    for d in dirs_to_check:
        status = "[PASS]" if Path(d).exists() else "[FAIL]"
        table.add_row(f"Folder: {d}", status)
        
    # Check repos
    repo_base = Path("temp_repos")
    for r in repos_to_check:
        status = "[PASS]" if (repo_base / r).exists() else "[FAIL]"
        table.add_row(f"Repo: {r}", status)
        
    # Check core scripts
    scripts = ["manager.py", "server.py", ".env", "requirements.txt"]
    for s in scripts:
        status = "[PASS]" if Path(s).exists() else "[FAIL]"
        table.add_row(f"Script: {s}", status)
        
    console.print(table)

    # 2. Check Environment
    console.print("\n[bold yellow]Environment Check:[/bold yellow]")
    try:
        import openai
        import fastapi
        import uvicorn
        console.print("[PASS] Core Python dependencies verified.")
    except ImportError as e:
        console.print(f"[FAIL] Missing dependency: {e}")
        console.print("[dim]Run 'pip install -r requirements.txt' to fix.[/dim]")

    console.print("\n[bold green]Verification Complete![/bold green]")
    console.print("You can now run 'python server.py' to start the hub.")

if __name__ == "__main__":
    verify_setup()
