import requests
from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET

RSS_FEED_FILE = "pseudo_kinhtedothi.xml"
URL = "https://kinhtedothi.vn/chuyen-muc/khoa-hoc-cong-nghe"  # Ví dụ chuyên mục

def scrape_articles():
    response = requests.get(URL, timeout=10)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, 'html.parser')

    articles = soup.select('div.article-item')  # Cần chỉnh selector theo HTML thực tế

    items = []
    for article in articles[:10]:
        title_tag = article.select_one('h3 a')
        if not title_tag:
            continue

        title = title_tag.text.strip()
        link = title_tag['href']
        pubDate = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

        item = {
            'title': title,
            'link': link,
            'pubDate': pubDate,
            'description': title  # Có thể thêm mô tả nếu lấy được
        }
        items.append(item)
    
    return items

def build_rss(items):
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = "Kinh tế Đô thị (pseudo)"
    ET.SubElement(channel, 'link').text = URL
    ET.SubElement(channel, 'description').text = "Pseudo RSS feed from Kinh tế Đô thị"

    for item in items:
        item_elem = ET.SubElement(channel, 'item')
        for key, value in item.items():
            ET.SubElement(item_elem, key).text = value

    tree = ET.ElementTree(rss)
    tree.write(RSS_FEED_FILE, encoding='utf-8', xml_declaration=True)

if __name__ == "__main__":
    articles = scrape_articles()
    if articles:
        build_rss(articles)
        print(f"✅ RSS file created with {len(articles)} items.")
    else:
        print("⚠️ Không tìm được bài viết nào.")
