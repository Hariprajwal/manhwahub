import requests
from bs4 import BeautifulSoup
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def test_weebrook():
    url = "https://weebrook.com/toon/emperor-of-solo-play/"
    r = requests.get(url, headers=headers, timeout=10)
    
    soup = BeautifulSoup(r.text, "html.parser")
    # check if chapters are directly in html
    chapters = soup.select("li.wp-manga-chapter a, div.wp-manga-chapter a, div.chapter-link a, li a[href*='chapter']")
    print("Normal HTML Chapters:", len(chapters))
    if chapters:
        print("Sample:", chapters[0]["href"])
        
    # Check for another ajax endpoint
    ajax_script = soup.select_one("script[id='manga_info-js-extra']")
    if ajax_script:
        print("Ajax Script:", ajax_script.text.strip())

    # Try manga-info ajax? There's an endpoint `admin-ajax.php?action=manga_get_chapters` with POST.
    # sometimes it needs 'manga': <id>
    
test_weebrook()
