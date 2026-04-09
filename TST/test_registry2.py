import sys
sys.path.append("TST")
import test_manwa

# Test Weebrook directly
weebrook = test_manwa.WeebrookSource()
results = weebrook.search("solo")
print("Weebrook Search Results:", len(results))
for r in results:
    print(r["title"], "-", r["url"])
    chaps = weebrook.get_chapters(r["url"])
    print("  Chapters:", len(chaps))
    if chaps:
        urls = weebrook.get_page_urls(chaps[0]["url"])
        print("    Pages in chapter 1:", len(urls))
    break

# Test Kunmanga directly
kun = test_manwa.KunMangaSource()
results = kun.search("solo")
print("\nKunManga Search Results:", len(results))
for r in results:
    print(r["title"], "-", r["url"])
    chaps = kun.get_chapters(r["url"])
    print("  Chapters:", len(chaps))
    if chaps:
        urls = kun.get_page_urls(chaps[0]["url"])
        print("    Pages in chapter 1:", len(urls))
    break
