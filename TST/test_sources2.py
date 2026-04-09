import requests
from bs4 import BeautifulSoup
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def test_weebrook():
    url = "https://weebrook.com/toon/emperor-of-solo-play/"
    r = requests.get(url, headers=headers, timeout=10)
    print("Weebrook Status:", r.status_code)
    
    # Check for manga ID
    soup = BeautifulSoup(r.text, "html.parser")
    manga_id_input = soup.select_one(".rating-post-id")
    manga_id = manga_id_input["value"] if manga_id_input else None
    print("Manga ID:", manga_id)
    
    # Try getting chapters via ajax if manga_id exists
    if manga_id:
        ajax_url = "https://weebrook.com/wp-admin/admin-ajax.php"
        data = {
            "action": "manga_get_chapters",
            "manga": manga_id
        }
        res = requests.post(ajax_url, data=data, headers=headers)
        ch_soup = BeautifulSoup(res.text, "html.parser")
        chapters = ch_soup.select(".wp-manga-chapter a")
        print("Ajax Chapters found:", len(chapters))
        if chapters:
            print("First chapter:", chapters[0]["href"])
            pg_r = requests.get(chapters[0]["href"], headers=headers)
            pg_soup = BeautifulSoup(pg_r.text, "html.parser")
            imgs = pg_soup.select(".wp-manga-chapter-img")
            print("Ajax Chapter Pages:", len(imgs))
            
def test_kunmanga():
    for ext in ["com", "net", "co"]:
        try:
            url = f"https://kunmanga.{ext}/?s=solo&post_type=wp-manga"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200 and "solo" in r.text.lower():
                print(f"KunManga domain works: kunmanga.{ext}")
                soup = BeautifulSoup(r.text, "html.parser")
                items = soup.select(".c-tabs-item__content, .row.c-tabs-item__content")
                print("Search items:", len(items))
                if items:
                    title = items[0].select_one("h3 a, .post-title h3 a, h4 a")
                    if title:
                        link = title["href"]
                        print("Test Manga Link:", link)
                        
                        r2 = requests.get(link, headers=headers)
                        soup2 = BeautifulSoup(r2.text, "html.parser")
                        manga_id_input = soup2.select_one(".rating-post-id")
                        manga_id = manga_id_input["value"] if manga_id_input else None
                        print("KunManga Manga ID:", manga_id)
                        
                        if manga_id:
                            ajax_url = f"https://kunmanga.{ext}/wp-admin/admin-ajax.php"
                            data = {"action": "manga_get_chapters", "manga": manga_id}
                            res = requests.post(ajax_url, data=data, headers=headers)
                            ch_soup = BeautifulSoup(res.text, "html.parser")
                            chapters = ch_soup.select(".wp-manga-chapter a")
                            print("KunManga Chapters via Ajax:", len(chapters))
                        
                break
        except Exception as e:
            print(f"KunManga {ext} Error:", e)

if __name__ == "__main__":
    test_weebrook()
    test_kunmanga()
