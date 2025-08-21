#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_category_opml.py — Quét CHỈ các RSS CHUYÊN MỤC theo bộ pattern, xuất OPML gọn.
Usage:
  python build_category_opml.py --sites sites.txt --patterns category_patterns.txt --out feeds.opml

Heuristics:
  - Lấy <link rel="alternate" type="application/rss+xml"> và <a href> có chứa rss/feed/xml
  - Giữ lại feed nếu URL hoặc text/tiêu đề chứa 1 trong các pattern (không phân biệt hoa thường, bỏ dấu)
Deps: requests, beautifulsoup4, lxml, unidecode
"""
from pathlib import Path
import argparse
import html
import urllib.parse

import requests
from bs4 import BeautifulSoup

try:
    from unidecode import unidecode
except Exception:  # fallback nếu chưa có unidecode
    def unidecode(s: str) -> str:
        return s

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Category-RSS-Builder/1.0"
TIMEOUT = 25


def fetch(url: str) -> tuple[str, str]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url


def normalize(s: str) -> str:
    s = (s or "")
    s = unidecode(s)
    return s.lower()


def load_lines(p: Path) -> list[str]:
    return [
        l.strip()
        for l in p.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]


def is_candidate(href: str) -> bool:
    u = (href or "").lower()
    return ("rss" in u) or ("/feed" in u) or u.endswith(".xml")


def title_from_url(u: str) -> str:
    p = urllib.parse.urlparse(u)
    host = p.hostname or ""
    path = (p.path or "/").strip("/")
    return host if not path else f"{host}/{path}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", required=True)
    ap.add_argument("--patterns", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sites_path = Path(args.sites)
    pats_path = Path(args.patterns)
    out_path = Path(args.out)

    seeds = load_lines(sites_path)
    patterns_norm = [normalize(x) for x in load_lines(pats_path)]

    all_feeds: dict[str, str] = {}

    for url in seeds:
        try:
            html_text, final = fetch(url)
        except Exception as e:
            print(f"❌ {url}: {e}")
            continue

        soup = BeautifulSoup(html_text, "lxml")
        candidates: set[str] = set()

        # 1) <link rel="alternate" ...>
        for link in soup.find_all("link", href=True):
            rel = " ".join(link.get("rel", [])).lower()
            typ = (link.get("type") or "").lower()
            if ("alternate" in rel) and (("rss" in typ) or ("xml" in typ)):
                candidates.add(urllib.parse.urljoin(final, link["href"]))

        # 2) <a href=...> chứa rss/feed/xml
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if is_candidate(href):
                candidates.add(urllib.parse.urljoin(final, href))

        # 3) Lọc theo pattern (URL hoặc text anchor)
        for c in candidates:
            nurl = normalize(c)

            # lấy text/title tương ứng nếu có
            text = ""
            for a in soup.find_all("a", href=True):
                if urllib.parse.urljoin(final, a["href"].strip()) == c:
                    text = (a.get("title") or a.get_text(" ", strip=True) or "")
                    break
            ntext = normalize(text)

            keep = False
            for pat in patterns_norm:
                if pat in nurl or (ntext and pat in ntext):
                    keep = True
                    break
            if not keep:
                continue

            if c not in all_feeds:
                all_feeds[c] = title_from_url(c)

    # 4) Ghi OPML
    head = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head>
    <title>Category Feeds (VN)</title>
  </head>
  <body>
    <outline text="VN Category Feeds" title="VN Category Feeds">
"""
    body_lines = []
    for url, title in sorted(all_feeds.items(), key=lambda kv: kv[0]):
        body_lines.append(
            f'      <outline type="rss" text="{html.escape(title)}" title="{html.escape(title)}" xmlUrl="{html.escape(url)}" />'
        )

    tail = """
    </outline>
  </body>
</opml>
"""
    out_path.write_text(head + "\n".join(body_lines) + tail, encoding="utf-8")
    print(f"✅ Wrote {out_path} with {len(all_feeds)} feeds (category-only).")


if __name__ == "__main__":
    main()
