# -*- coding: utf-8 -*-
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


if count>0:
subject = f"[RSS Watcher] {count} bài mới khớp bộ lọc"
send_email(subject, body)
else:
print("No new matching items.")


if __name__ == "__main__":
cli()