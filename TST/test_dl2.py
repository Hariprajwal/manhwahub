import sys
from pathlib import Path
sys.path.append("TST")
import test_manwa

new_manwa = test_manwa

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
        new_manwa.download_chapter(manga_info, ch, manga_dir)
        print("Done downloading weebrook.")
    else:
        print("No weebrook chapters.")
else:
    print("No weebrook results")

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
else:
    print("No kunmanga results")
