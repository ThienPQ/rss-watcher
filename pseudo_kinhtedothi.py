import requests
from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET

BASE_URL = "https://kinhtedothi.vn/kinh-te/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_articles():
    res = requests.get(BASE_URL, headers=HEADERS)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    
    items = []
    for article in soup.select("div.list__news--top a.news__title")[:10]:
        title = article.get_text(strip=True)
        link = article["href"]
        if not link.startswith("http"):
            link = "https://kinhtedothi.vn" + link
        items.append((title, link))
    return items

def build_rss(items):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Kinh tế & Đô thị - Kinh tế"
    ET.SubElement(channel, "link").text = BASE_URL
    ET.SubElement(channel, "description").text = "Tin mới từ chuyên mục Kinh tế"

    for title, link in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "description").text = title
        ET.SubElement(item, "pubDate").text = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')

    tree = ET.ElementTree(rss)
    tree.write("pseudo_kinhtedothi.xml", encoding="utf-8", xml_declaration=True)
    print("✅ Đã tạo file pseudo_kinhtedothi.xml")

if __name__ == "__main__":
    articles = fetch_articles()
    build_rss(articles)
