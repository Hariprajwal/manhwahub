import requests

url = "https://weebrook.com/toon/emperor-of-solo-play/"
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
with open("test.html", "w", encoding="utf-8") as f:
    f.write(r.text)
print("Saved to test.html")
