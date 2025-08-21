#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, sys, time, html, urllib.parse
from pathlib import Path
import requests
from bs4 import BeautifulSoup

IN_FILE  = Path("rss_indices.txt")
OUT_FILE = Path("feeds.opml")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RSS-Crawler/1.0 (+https://example.local)"
TIMEOUT = 20

RSS_HINT_PATTERNS = [
    re.compile(r"\.rss($|\?)", re.I),
    re.compile(r"/rss($|[/?#])", re.I),
    re.compile(r"/rss\.htm[l]?$", re.I),
]

def looks_like_rss(url: str) -> bool:
    u = url.strip()
    if not u: return False
    return any(p.search(u) for p in RSS_HINT_PATTERNS)

def absolutize(base, href):
    return urllib.parse.urljoin(base, href)

def fetch(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text, r.url

def extract_feeds_from_page(html_text, base_url):
    soup = BeautifulSoup(html_text, "lxml")
    feeds = set()

    # 1) <a href=...> có chứa /rss hoặc .rss
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if looks_like_rss(href):
            feeds.add(absolutize(base_url, href))

    # 2) <link rel="alternate" type="application/rss+xml"> (nếu có)
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel", [])).lower()
        t   = (link.get("type") or "").lower()
        if "alternate" in rel and ("rss" in t or "xml" in t):
            feeds.add(absolutize(base_url, link["href"]))

    # 3) fallback: nếu chính URL kết thúc bằng /rss(.html|.htm), coi là feed
    if looks_like_rss(base_url):
        feeds.add(base_url)

    return feeds

def tidy_title_from_url(u: str) -> str:
    p = urllib.parse.urlparse(u)
    host = p.hostname or ""
    path = (p.path or "/").rstrip("/")
    if not path: path = "/"
    return f"{host}{path}"

def write_opml(feed_urls):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    head = f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head>
    <title>VN News Feeds (Auto-built)</title>
    <dateCreated>{now}</dateCreated>
  </head>
  <body>
    <outline text="Vietnam News" title="Vietnam News">
"""
    body = []
    for url in sorted(feed_urls):
        title = html.escape(tidy_title_from_url(url))
        href  = html.escape(url)
        body.append(f'      <outline type="rss" text="{title}" title="{title}" xmlUrl="{href}" />')
    tail = """
    </outline>
  </body>
</opml>
"""
    OUT_FILE.write_text(head + "\n".join(body) + tail, encoding="utf-8")

def main():
    if not IN_FILE.exists():
        print(f"⚠️ Không thấy {IN_FILE}. Hãy tạo file này trước.")
        sys.exit(1)

    seeds = [l.strip() for l in IN_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
    all_feeds = set()
    for url in seeds:
        try:
            html_text, final_url = fetch(url)
        except Exception as e:
            print(f"❌ Lỗi tải {url}: {e}")
            continue

        # Thử trích ngay từ trang seed
        feeds = extract_feeds_from_page(html_text, final_url)
        all_feeds |= feeds

        # Nếu seed là trang chủ, thử các biến thể phổ biến
        if not feeds:
            for suffix in ("/rss", "/rss.htm", "/rss.html"):
                probe = urllib.parse.urljoin(final_url.rstrip("/") + "/", suffix.lstrip("/"))
                try:
                    txt, fin = fetch(probe)
                    feeds2   = extract_feeds_from_page(txt, fin)
                    if feeds2:
                        print(f"[+] Found RSS index via {probe} -> {len(feeds2)} feeds")
                        all_feeds |= feeds2
                        break
                except Exception:
                    pass

        print(f"[i] {url} -> +{len(feeds)} feed(s) (tổng hiện tại: {len(all_feeds)})")

    if not all_feeds:
        print("⚠️ Không phát hiện feed nào. Kiểm tra lại seeds / mạng / chặn bot.")
        sys.exit(2)

    write_opml(all_feeds)
    print(f"✅ Đã viết {OUT_FILE} với {len(all_feeds)} feed.")
    print("• Import OPML này vào Inoreader hoặc dùng trực tiếp trong workflow gửi mail của bạn.")

if __name__ == "__main__":
    main()
