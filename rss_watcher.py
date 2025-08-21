
# -*- coding: utf-8 -*-
"""
RSS Watcher - deduplicate by persistent state (no more resending old items)
----------------------------------------------------------------------------
- Reads feeds from an OPML file (xmlUrl entries) - local pseudo-feed XML also OK
- Loads keyword rules from a TXT file (one rule per line, supports AND/OR)
- Sends email instantly when NEW items match (no duplicates across workflow runs)
- Persists 'seen' IDs per feed to a JSON file so next runs won't resend

ENV (set via GitHub Actions env/secrets or local):
  STATE_FILE               default: .state/seen.json
  STATE_TTL_DAYS           default: 30
  STATE_MAX_IDS_PER_FEED   default: 2000
  STATE_INIT_IF_EMPTY      default: 0   # set to 1 for the very first run to record current items as seen without emailing

  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TO  (email settings)
  DRY_RUN                  default: 0   # set to 1 to skip sending email

Usage:
  python rss_watcher.py feeds.opml keywords.txt
"""
import os, re, json, time, html, sys, hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple

import feedparser
from bs4 import BeautifulSoup
import requests

# ---------- Email (SMTP) ----------
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(subject: str, html_body: str):
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '465'))
    user = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASS')
    from_addr = os.environ.get('SMTP_FROM', user)
    to_addrs = [x.strip() for x in os.environ.get('SMTP_TO', '').split(',') if x.strip()]

    if not (user and password and to_addrs):
        print("Warning: SMTP env not set - skipping email. (Need SMTP_USER/SMTP_PASS/SMTP_TO)")
        return

    msg = MIMEMultipart()
    msg['From'] = from_addr
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    if os.environ.get('DRY_RUN') == '1':
        print("DRY_RUN=1 -> not sending email. Subject:", subject)
        return

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(msg)
        print("Email sent to:", ', '.join(to_addrs))
    except smtplib.SMTPAuthenticationError as e:
        print("SMTPAuthenticationError:", e)
        print("-> Gmail users: enable 2FA and generate an App Password.")
        raise

# ---------- State persistence ----------

STATE_FILE = Path(os.environ.get("STATE_FILE", ".state/seen.json"))
STATE_TTL_DAYS = int(os.environ.get("STATE_TTL_DAYS", "30"))
STATE_MAX_IDS_PER_FEED = int(os.environ.get("STATE_MAX_IDS_PER_FEED", "2000"))
STATE_INIT_IF_EMPTY = os.environ.get("STATE_INIT_IF_EMPTY", "0") == "1"

def _now_ts() -> int:
    return int(time.time())

def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen": {}, "last_run": 0}

def save_state(state: Dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def prune_state(state: Dict):
    cutoff = _now_ts() - STATE_TTL_DAYS * 86400
    seen = state.get("seen", {})
    for feed_url, items in list(seen.items()):
        # remove too old
        new_items = {k: v for k, v in items.items() if v >= cutoff}
        # size cap
        if len(new_items) > STATE_MAX_IDS_PER_FEED:
            # keep newest N
            new_items = dict(sorted(new_items.items(), key=lambda kv: kv[1], reverse=True)[:STATE_MAX_IDS_PER_FEED])
        seen[feed_url] = new_items
    state["seen"] = seen

# ---------- Input parsing ----------

def parse_opml(opml_path: Path) -> List[str]:
    import xml.etree.ElementTree as ET
    urls = []
    try:
        tree = ET.parse(opml_path)
    except Exception as e:
        print("OPML parse error:", e)
        return urls
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

    for _ in walk(body):
        pass
    # de-dup while preserving order
    seen = set()
    out = []
    for u in urls:
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out

# ---------- Keyword logic ----------

def parse_rules(lines: List[str]) -> List[List[List[str]]]:
    """
    Very simple Boolean:
    - Each line = one rule (OR across lines).
    - Within a line, use 'AND' and 'OR' tokens (case-insensitive).
    - Tokens other than AND/OR are terms; whitespace-trimmed; quoted phrases supported.
    Parentheses are ignored; OR is treated left-to-right.
    Return: list of clauses, each is list of AND groups (list of terms).
    """
    rules = []
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        parts = re.findall(r'"[^"]+"|\S+', s, flags=re.UNICODE)
        clause = []
        group = []
        i = 0
        while i < len(parts):
            tok = parts[i]
            tok_up = tok.upper()
            if tok_up == "OR":
                if group:
                    clause.append(group)
                    group = []
            elif tok_up == "AND":
                pass
            else:
                term = tok.strip('"').lower()
                group.append(term)
            i += 1
        if group:
            clause.append(group)
        if clause:
            rules.append(clause)
    return rules

def text_matches_rules(text: str, rules) -> bool:
    if not rules:
        return True
    s = text.lower()
    for clause in rules:  # clause is OR of AND-groups
        for group in clause:
            if all(term in s for term in group):
                return True
    return False

# ---------- Feed processing ----------

def norm_id(entry) -> str:
    for key in ("id", "guid", "link"):
        if entry.get(key):
            return entry.get(key)
    combo = (entry.get("title", "") + "|" + entry.get("link", "") + "|" + str(entry.get("published", ""))).encode("utf-8", "ignore")
    return "h:" + hashlib.sha1(combo).hexdigest()

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
        from bs4 import BeautifulSoup
        clean = BeautifulSoup(desc, "lxml").get_text(" ", strip=True)
        if len(clean) > 500:
            clean = clean[:500] + "…"
        parts.append(f"<div>{html.escape(clean)}</div>")
    return "<br/>".join(parts)

def process(feeds: List[str], rules, state: Dict) -> tuple[int, str]:
    seen = state.setdefault("seen", {})
    now_ts = _now_ts()
    hits = []

    for f in feeds:
        try:
            d = feedparser.parse(f)
        except Exception as e:
            print("feedparser error:", f, e)
            continue
        if not d or not d.get("entries"):
            continue
        feed_seen = seen.setdefault(f, {})
        for e in d.entries:
            _id = norm_id(e)
            if _id in feed_seen:
                continue  # already sent before
            title = e.get("title") or ""
            desc  = e.get("summary") or e.get("description") or ""
            combined = f"{title}\n{desc}"
            if text_matches_rules(combined, rules):
                hits.append((f, e, _id))
                feed_seen[_id] = now_ts  # mark seen immediately

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
            html_parts.append("<li>" + entry_summary(e) + "</li>")
        html_parts.append("</ul>")
    html_parts.append("</div>")
    html_body = "\n".join(html_parts)
    return len(hits), html_body

def main():
    if len(sys.argv) < 3:
        print("Usage: python rss_watcher.py feeds.opml keywords.txt")
        sys.exit(2)
    feeds_opml = Path(sys.argv[1])
    keywords_txt = Path(sys.argv[2])

    feeds = parse_opml(feeds_opml)
    if not feeds:
        print("No feeds found in OPML.")
    lines = []
    if keywords_txt.exists():
        lines = [l.rstrip("\n") for l in keywords_txt.read_text(encoding="utf-8").splitlines()]
    rules = parse_rules(lines)

    state = load_state()
    first_time = (state.get("last_run", 0) == 0)
    if first_time and STATE_INIT_IF_EMPTY:
        print("First run with STATE_INIT_IF_EMPTY=1 -> initialize state without sending email.")
        for f in feeds:
            try:
                d = feedparser.parse(f)
                if not d or not d.get("entries"):
                    continue
                feed_seen = state.setdefault("seen", {}).setdefault(f, {})
                now_ts = _now_ts()
                for e in d.entries:
                    _id = norm_id(e)
                    feed_seen[_id] = now_ts
            except Exception:
                continue
        state["last_run"] = _now_ts()
        prune_state(state)
        save_state(state)
        print("State initialized. Next runs will only send new items.")
        sys.exit(0)

    count, html_body = process(feeds, rules, state)

    state["last_run"] = _now_ts()
    prune_state(state)
    save_state(state)

    if count > 0:
        subject = f"[RSS Watcher] {count} bài mới khớp bộ lọc"
        send_email(subject, html_body)
    else:
        print("No new matching items.")

if __name__ == "__main__":
    main()
