import feedparser
import smtplib
from email.message import EmailMessage
from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET
import os

# ========== CẤU HÌNH ==========
OPML_FILE = "Inoreader Feeds 20250813.xml"
KEYWORDS = ['AI', 'giá dầu', 'startup', 'Hòa Lạc']

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_PASS = os.getenv("EMAIL_PASS")

def extract_rss_urls(opml_path):
    tree = ET.parse(opml_path)
    root = tree.getroot()
    urls = []
    for outline in root.iter('outline'):
        url = outline.attrib.get('xmlUrl')
        if url:
            urls.append(url)
    return urls

def get_matching_articles(rss_urls, keywords):
    matches = []
    for url in rss_urls:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.title.lower()
            summary = BeautifulSoup(entry.get('summary', ''), "html.parser").text.lower()
            if any(kw.lower() in title or kw.lower() in summary for kw in keywords):
                matches.append(f"[{feed.feed.title}]\n{entry.title}\n{entry.link}\n")
    return matches

def send_email(matches):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = EmailMessage()
    msg['Subject'] = f'[RSS Watcher] Tin tức khớp từ khóa ({now})'
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg.set_content("\n\n".join(matches))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_PASS)
        smtp.send_message(msg)

if __name__ == "__main__":
    urls = extract_rss_urls(OPML_FILE)
    matches = get_matching_articles(urls, KEYWORDS)
    if matches:
        send_email(matches)
        print(f"Đã gửi {len(matches)} tin tức.")
    else:
        print("Không có tin nào phù hợp.")
