import os
import sys
# Update sys.path and import things
import importlib.util

spec = importlib.util.spec_from_file_location("new_manwa", "NEW-MANWA.PY")
new_manwa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_manwa)

from pathlib import Path

# Setup mock manga_info and chapter for weebrook
weebrook = new_manwa.WeebrookSource()
results = weebrook.search("solo")
if results:
    manga_info = results[0]
    print(f"Testing {manga_info['title']} on Weebrook:")
    chapters = weebrook.get_chapters(manga_info["url"])
    if chapters:
        ch = chapters[0]
        print(f"Found {len(chapters)} chapters. Testing first chapter {ch['num']}")
        manga_dir = Path("downloads") / new_manwa.safe_name(manga_info["title"])
        manga_dir.mkdir(parents=True, exist_ok=True)
        # we disable log spam for a bit
        new_manwa.download_chapter(manga_info, ch, manga_dir)
        print("Done downloading weebrook.")
    else:
        print("No weebrook chapters.")

# Let's try kunmanga with a common search
kun = new_manwa.KunMangaSource()
results = kun.search("magic")
if results:
    manga_info = results[0]
    print(f"\nTesting {manga_info['title']} on KunManga:")
    chapters = kun.get_chapters(manga_info["url"])
    if chapters:
        ch = chapters[0]
        print(f"Found {len(chapters)} chapters. Testing first chapter {ch['num']}")
        manga_dir = Path("downloads") / new_manwa.safe_name(manga_info["title"])
        manga_dir.mkdir(parents=True, exist_ok=True)
        new_manwa.download_chapter(manga_info, ch, manga_dir)
        print("Done downloading kunmanga.")
    else:
        print("No kunmanga chapters.")
