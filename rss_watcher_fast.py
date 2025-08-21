# -*- coding: utf-8 -*-
"""
rss_watcher_fast.py — tải song song + cache ETag/Last-Modified, chỉ gửi bài MỚI khớp bộ lọc.
Usage:
  python rss_watcher_fast.py feeds.opml keywords.txt
Env:
  MAX_CONCURRENCY=20  REQ_TIMEOUT=25  MAX_ENTRY_AGE_DAYS=7
  STATE_FILE=.state/seen.json  CACHE_FILE=.state/cache.json
  SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM/SMTP_TO
"""
import os, re, json, html, sys, hashlib, asyncio, time
from pathlib import Path
from typing import List, Dict, Tuple

import aiohttp
import feedparser
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "20"))
REQ_TIMEOUT = int(os.environ.get("REQ_TIMEOUT", "25"))
MAX_ENTRY_AGE_DAYS = int(os.environ.get("MAX_ENTRY_AGE_DAYS", "7"))

STATE_FILE = Path(os.environ.get("STATE_FILE", ".state/seen.json"))
CACHE_FILE = Path(os.environ.get("CACHE_FILE", ".state/cache.json"))

def _now_ts() -> int:
    return int(time.time())

def load_json(p: Path, fallback):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return fallback

def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def parse_opml(opml_path: Path) -> List[str]:
    import xml.etree.ElementTree as ET
    urls = []
    tree = ET.parse(opml_path)
    root = tree.getroot()
    body = root.find("body")
    if body is None:
        return urls
    def walk(e):
        for c in e:
            if c.tag.lower().endswith("outline"):
                xml = c.attrib.get("xmlUrl") or c.attrib.get("xmlurl") or ""
                if xml:
                    urls.append(xml.strip())
                if list(c):
                    yield from walk(c)
    for _ in walk(body):  # consume generator
        pass
    out, seen = [], set()
    for u in urls:
        if u and u not in seen:
            out.append(u); seen.add(u)
    return out

def parse_rules(lines: List[str]):
    rules = []
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        parts = re.findall(r'"[^"]+"|\S+', s, flags=re.UNICODE)
        clause, group = [], []
        for tok in parts:
            up = tok.upper()
            if up == "OR":
                if group:
                    clause.append(group); group = []
            elif up == "AND":
                pass
            else:
                group.append(tok.strip('"').lower())
        if group:
            clause.append(group)
        if clause:
            rules.append(clause)
    return rules

def text_matches(text: str, rules) -> bool:
    if not rules:
        return True
    s = text.lower()
    for clause in rules:
        for group in clause:
            if all(term in s for term in group):
                return True
    return False

def norm_id(entry) -> str:
    for k in ("id", "guid", "link"):
        if entry.get(k):
            return entry.get(k)
    combo = (entry.get("title","") + "|" + entry.get("link","") + "|" + str(entry.get("published",""))).encode("utf-8","ignore")
    return "h:"+hashlib.sha1(combo).hexdigest()

def entry_summary(entry) -> str:
    parts = []
    if entry.get("title"):
        parts.append(f"<b>{html.escape(entry.title)}</b>")
    if entry.get("published"):
        parts.append(f"<i>{html.escape(entry.published)}</i>")
    if entry.get("link"):
        parts.append(f'<div><a href="{html.escape(entry.link)}">{html.escape(entry.link)}</a></div>')
    desc = entry.get("summary") or entry.get("description") or ""
    if desc:
        clean = BeautifulSoup(desc, "lxml").get_text(" ", strip=True)
        if len(clean) > 500:
            clean = clean[:500] + "…"
        parts.append(f"<div>{html.escape(clean)}</div>")
    return "<br/>".join(parts)

def send_email(subject: str, html_body: str):
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '465'))
    user = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASS')
    from_addr = os.environ.get('SMTP_FROM', user)
    to_addrs = [x.strip() for x in os.environ.get('SMTP_TO', '').split(',') if x.strip()]
    if not (user and password and to_addrs):
        print("SMTP not set; skip email."); return
    msg = MIMEMultipart(); msg['From']=from_addr; msg['To']=', '.join(to_addrs); msg['Subject']=subject
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    if os.environ.get('DRY_RUN')=='1':
        print("DRY_RUN=1 -> not sending email. Subject:", subject); return
    try:
        if port==465:
            with smtplib.SMTP_SSL(host, port) as s: s.login(user,password); s.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as s: s.ehlo(); s.starttls(); s.login(user,password); s.send_message(msg)
        print("Email sent to:", ', '.join(to_addrs))
    except smtplib.SMTPAuthenticationError as e:
        print("SMTPAuthenticationError:", e); raise

async def fetch_feed(session: aiohttp.ClientSession, url: str, cache: Dict) -> Tuple[str, bytes, Dict]:
    headers = {"User-Agent":"Mozilla/5.0 RSS-Watcher/fast"}
    meta = cache.get(url, {})
    if (et := meta.get("etag")):
        headers["If-None-Match"] = et
    if (lm := meta.get("last_modified")):
        headers["If-Modified-Since"] = lm
    try:
        async with session.get(url, headers=headers, timeout=REQ_TIMEOUT, allow_redirects=True) as resp:
            if resp.status == 304:
                return url, b"", meta
            content = await resp.read()
            new_meta = {
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "fetched_at": _now_ts(),
                "status": resp.status
            }
            return str(resp.url), content, new_meta
    except Exception as e:
        return url, b"", {"error": str(e), "fetched_at": _now_ts()}

async def main_async(feeds: List[str], rules, state: Dict, cache: Dict):
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        async def run(u):
            async with sem:
                return await fetch_feed(session, u, cache)
        results = await asyncio.gather(*[run(u) for u in feeds])

    seen = state.setdefault("seen", {})
    hits = []
    cutoff_ts = _now_ts() - MAX_ENTRY_AGE_DAYS*86400

    for (final_url, content, meta), orig in zip(results, feeds):
        cache[orig] = {**cache.get(orig, {}), **meta}
        if not content:
            # 304 hoặc lỗi: bỏ qua
            continue
        d = feedparser.parse(content)
        if not d or not d.get("entries"):
            continue
        feed_seen = seen.setdefault(orig, {})
        for e in d.entries:
            _id = norm_id(e)
            if _id in feed_seen:
                continue
            if e.get("published_parsed"):
                import time as _t
                ts = int(_t.mktime(e.published_parsed))
                if ts < cutoff_ts:
                    continue
            title = e.get("title") or ""
            desc  = e.get("summary") or e.get("description") or ""
            if text_matches(f"{title}\n{desc}", rules):
                hits.append((orig, e, _id))
                feed_seen[_id] = _now_ts()

    if not hits:
        return 0, ""

    from collections import defaultdict
    groups = defaultdict(list)
    for f, e, _ in hits:
        groups[f].append(e)

    html_parts = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px">']
    html_parts.append(f"<h2>RSS Watcher — {len(hits)} bài mới khớp bộ lọc</h2>")
    for f, entries in groups.items():
        html_parts.append(f'<h3 style="margin-top:16px">{html.escape(f)}</h3><ul>')
        for e in entries:
            html_parts.append("<li>"+entry_summary(e)+"</li>")
        html_parts.append("</ul>")
    html_parts.append("</div>")
    return len(hits), "\n".join(html_parts)

def cli():
    if len(sys.argv) < 3:
        print("Usage: python rss_watcher_fast.py feeds.opml keywords.txt")
        sys.exit(2)
    opml = Path(sys.argv[1])
    kw = Path(sys.argv[2])
    feeds = parse_opml(opml)
    lines = kw.read_text(encoding="utf-8").splitlines() if kw.exists() else []
    rules = parse_rules(lines)

    state = load_json(STATE_FILE, {"seen":{}, "last_run":0})
    cache = load_json(CACHE_FILE, {})

    count, body = asyncio.run(main_async(feeds, rules, state, cache))

    state["last_run"] = _now_ts()
    save_json(STATE_FILE, state)
    save_json(CACHE_FILE, cache)

    if count > 0:
        subject = f"[RSS Watcher] {count} bài mới khớp bộ lọc"
        send_email(subject, body)
    else:
        print("No new matching items.")

if __name__ == "__main__":
    cli()
