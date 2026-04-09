import requests
from bs4 import BeautifulSoup

url = 'https://weebrook.com/toon/emperor-of-solo-play/chapter-01/'
text = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text
soup = BeautifulSoup(text, 'html.parser')
imgs = soup.find_all('img')
for i in imgs:
    src = i.get('src') or i.get('data-src') or i.get('data-lazy-src') or ''
    if 'logo' not in src and 'avatar' not in src:
        print(src)
