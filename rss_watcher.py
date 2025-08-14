import feedparser
import smtplib
from email.message import EmailMessage

KEYWORDS_FILE = 'keywords.txt'
SENT_FILE = 'sent_urls.txt'
RSS_FILE = 'feeds.opml'

def load_keywords():
    with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def load_sent():
    try:
        with open(SENT_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def save_sent(sent):
    with open(SENT_FILE, 'w', encoding='utf-8') as f:
        for url in sent:
            f.write(url + '\n')

def load_feeds():
    import xml.etree.ElementTree as ET
    tree = ET.parse(RSS_FILE)
    root = tree.getroot()
    return [outline.attrib['xmlUrl'] for outline in root.findall('.//outline') if 'xmlUrl' in outline.attrib]

def entry_matches(entry, keywords):
    title = entry.get('title', '').lower()
    summary = entry.get('summary', '').lower()
    content = title + ' ' + summary
    for rule in keywords:
        if ' AND ' in rule:
            terms = [t.lower() for t in rule.split(' AND ')]
            if all(term in content for term in terms):
                return True
        else:
            if rule.lower() in content:
                return True
    return False

def send_email(entries):
    msg = EmailMessage()
    msg['Subject'] = f"[RSS Alert] {len(entries)} tin tức liên quan"
    msg['From'] = 'your_email@example.com'
    msg['To'] = 'your_email@example.com'
    body = '\n\n'.join([f"{e['title']}\n{e['link']}" for e in entries])
    msg.set_content(body)
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login('your_email@example.com', 'your_app_password')
        smtp.send_message(msg)

def main():
    feeds = load_feeds()
    keywords = load_keywords()
    sent = load_sent()
    new_sent = set(sent)
    matched = []

    for url in feeds:
        d = feedparser.parse(url)
        for entry in d.entries:
            link = entry.get('link')
            if link and link not in sent and entry_matches(entry, keywords):
                matched.append(entry)
                new_sent.add(link)
    
    if matched:
        send_email(matched)
        print(f"[+] Sent {len(matched)} matched entries.")
    else:
        print("[-] No matched entries found.")

    save_sent(new_sent)

if __name__ == '__main__':
    main()