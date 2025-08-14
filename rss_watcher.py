
import feedparser
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os
import time
import hashlib

# ===== Cấu hình =====
OPML_FILE = "feeds.opml"
KEYWORDS_FILE = "keywords.txt"
SEEN_HASHES_FILE = "seen_hashes.txt"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
EMAIL_SENDER = "your_email@gmail.com"
EMAIL_PASSWORD = "your_password"  # Sử dụng App Password nếu dùng Gmail 2FA
EMAIL_RECEIVER = "receiver_email@gmail.com"

# ===== Hàm tiện ích =====
def load_keywords():
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    and_keywords = []
    or_keywords = []
    for line in lines:
        if " AND " in line:
            and_keywords.append([kw.strip().lower() for kw in line.split("AND")])
        else:
            or_keywords.append(line.lower())
    return and_keywords, or_keywords

def matches_keywords(text, and_keywords, or_keywords):
    text = text.lower()
    for group in and_keywords:
        if all(word in text for word in group):
            return True
    for word in or_keywords:
        if word in text:
            return True
    return False

def load_seen_hashes():
    if os.path.exists(SEEN_HASHES_FILE):
        with open(SEEN_HASHES_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()

def save_seen_hashes(hashes):
    with open(SEEN_HASHES_FILE, "w") as f:
        for h in hashes:
            f.write(h + "\n")

def hash_entry(entry):
    raw = entry.get("title", "") + entry.get("link", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

def parse_opml(opml_file):
    import xml.etree.ElementTree as ET
    tree = ET.parse(opml_file)
    root = tree.getroot()
    feeds = []
    for outline in root.iter("outline"):
        xml_url = outline.attrib.get("xmlUrl")
        if xml_url:
            feeds.append(xml_url)
    return feeds

# ===== Chạy chính =====
def main():
    print(f"⏰ Running at {datetime.now()}")
    feeds = parse_opml(OPML_FILE)
    and_keywords, or_keywords = load_keywords()
    seen_hashes = load_seen_hashes()
    new_hashes = set()
    matched_entries = []

    for feed_url in feeds:
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries:
            h = hash_entry(entry)
            if h in seen_hashes:
                continue
            content = (entry.get("title", "") + " " + entry.get("summary", ""))
            if matches_keywords(content, and_keywords, or_keywords):
                matched_entries.append(entry)
            new_hashes.add(h)

    if matched_entries:
        html = "<h3>📰 Có bài viết mới liên quan:</h3><ul>"
        for e in matched_entries:
            html += f"<li><a href='{e.link}'>{e.title}</a><br><small>{e.get('published', '')}</small></li>"
        html += "</ul>"
        send_email("🔔 Tin mới phù hợp bộ lọc từ khóa", html)
        print(f"✅ Đã gửi email với {len(matched_entries)} bài viết.")

    save_seen_hashes(seen_hashes.union(new_hashes))

if __name__ == "__main__":
    main()
