import requests
from bs4 import BeautifulSoup
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def test_kunmanga():
    print("Testing KunManga...")
    try:
        r = requests.get("https://kunmanga.com/?s=solo&post_type=wp-manga", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".c-tabs-item__content, .row.c-tabs-item__content")
        print("KunManga Search Items:", len(items))
        if items:
            title = items[0].select_one("h3 a, .post-title h3 a, h4 a")
            if title:
                print("Title:", title.text.strip())
                print("Link:", title["href"])
        
        # Test chapter
        if items and title:
            ch_r = requests.get(title["href"], headers=headers, timeout=10)
            ch_soup = BeautifulSoup(ch_r.text, "html.parser")
            chapters = ch_soup.select(".wp-manga-chapter a")
            print("KunManga Chapters:", len(chapters))
            if chapters:
                print("First chapter:", chapters[0]["href"])
                
                # Test pages
                pg_r = requests.get(chapters[0]["href"], headers=headers, timeout=10)
                pg_soup = BeautifulSoup(pg_r.text, "html.parser")
                imgs = pg_soup.select(".wp-manga-chapter-img")
                print("KunManga Pages:", len(imgs))
                if imgs:
                    print("First image:", imgs[0].get("src") or imgs[0].get("data-src"))
    except Exception as e:
        print("KunManga Error:", e)

def test_weebrook():
    print("Testing Weebrook...")
    try:
        r = requests.get("https://weebrook.com/?s=solo&post_type=wp-manga", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".c-tabs-item__content, .row.c-tabs-item__content")
        print("Weebrook Search Items:", len(items))
        if items:
            title = items[0].select_one("h3 a, .post-title h3 a, h4 a")
            if title:
                print("Title:", title.text.strip())
                print("Link:", title["href"])
        
        # Test chapter
        if items and title:
            ch_r = requests.get(title["href"], headers=headers, timeout=10)
            ch_soup = BeautifulSoup(ch_r.text, "html.parser")
            chapters = ch_soup.select(".wp-manga-chapter a")
            print("Weebrook Chapters:", len(chapters))
            if chapters:
                print("First chapter:", chapters[0]["href"])
                
                # Test pages
                # Sometimes chapters are loaded via ajax in mangabooth themes, 
                # but let's test normally first
                pg_r = requests.get(chapters[0]["href"], headers=headers, timeout=10)
                pg_soup = BeautifulSoup(pg_r.text, "html.parser")
                imgs = pg_soup.select(".wp-manga-chapter-img")
                print("Weebrook Pages:", len(imgs))
                if imgs:
                    print("First image:", imgs[0].get("src") or imgs[0].get("data-src"))
    except Exception as e:
        print("Weebrook Error:", e)

if __name__ == "__main__":
    test_kunmanga()
    test_weebrook()
