#!/usr/bin/env python3
href = a["href"].strip()
if is_candidate(href):
candidates.add(urllib.parse.urljoin(final, href))


# Lọc theo pattern
for c in candidates:
nurl = normalize(c)
# Lấy thêm text gợi ý từ anchor title/text nếu tồn tại
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


# Write OPML
head = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
<head>
<title>Category Feeds (VN)</title>
</head>
<body>
<outline text="VN Category Feeds" title="VN Category Feeds">
"""
body = []
for url, title in sorted(all_feeds.items(), key=lambda kv: kv[0]):
body.append(f' <outline type="rss" text="{html.escape(title)}" title="{html.escape(title)}" xmlUrl="{html.escape(url)}" />')


tail = """
</outline>
</body>
</opml>
"""
out_path.write_text(head + "\n".join(body) + tail, encoding="utf-8")
print(f"✅ Wrote {out_path} with {len(all_feeds)} feeds (category-only).")


if __name__ == "__main__":
main()