# -*- coding: utf-8 -*-
"""
pseudo_kinhtedothi.py — Selenium pseudo RSS builder (v6: no user-data-dir + Firefox fallback)

- KHÔNG dùng --user-data-dir (tránh xung đột profile)
- Nếu Chrome không mở được session → fallback sang Firefox headless
- Cuộn trang + thử click “Xem thêm / Tải thêm / Load more / Trang sau”
- Lấy link *.html trực tiếp từ DOM (ít phụ thuộc CSS class)
- Ghi debug_links.txt & debug_page.html khi rỗng
- Xuất RSS XML: pseudo_kinhtedothi.xml

Cài đặt:
  pip install selenium webdriver-manager beautifulsoup4 lxml
  (khuyến nghị) pip install undetected-chromedriver

ENV (Windows CMD: `set KEY=VALUE`):
  KINHTEDOTHI_URL       (mặc định: https://kinhtedothi.vn/doanh-nghiep/khoi-nghiep)
  KINHTEDOTHI_OUT       (mặc định: pseudo_kinhtedothi.xml)
  KINHTEDOTHI_MAX       (mặc định: 40)
  KINHTEDOTHI_HEADLESS  (1|0; mặc định: 1 — chạy ẩn)
  KINHTEDOTHI_FOCUS     (substring cần có trong link; vd: khoi-nghiep)
  KINHTEDOTHI_USE_UC    (1|0; mặc định: 1 — dùng undetected-chromedriver nếu có)
"""

import os, re, time, html
from datetime import datetime, timezone
from typing import List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except Exception:
    HAS_UC = False

URL        = os.environ.get("KINHTEDOTHI_URL", "https://kinhtedothi.vn/doanh-nghiep/khoi-nghiep")
OUT_FILE   = os.environ.get("KINHTEDOTHI_OUT", "pseudo_kinhtedothi.xml")
MAX_ITEMS  = int(os.environ.get("KINHTEDOTHI_MAX", "40"))
HEADLESS   = os.environ.get("KINHTEDOTHI_HEADLESS", "1") != "0"
FOCUS_SUB  = (os.environ.get("KINHTEDOTHI_FOCUS") or "").strip().lower()
USE_UC     = os.environ.get("KINHTEDOTHI_USE_UC", "1") == "1"

def _apply_chrome_common(opts):
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,4000")
    opts.add_argument("--lang=vi-VN,vi")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/127.0.0.0 Safari/537.36")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

def _apply_firefox_common(opts):
    if HEADLESS:
        opts.add_argument("-headless")
    # user-agent mặc định của Firefox là đủ
    # có thể thêm prefs nếu bị chặn

def make_chrome():
    # 1) undetected-chromedriver nếu có và được bật
    if USE_UC and HAS_UC:
        print("[i] Driver: undetected-chromedriver (no user-data-dir)")
        options = uc.ChromeOptions()
        _apply_chrome_common(options)
        options.add_argument("--disable-blink-features=AutomationControlled")
        driver = uc.Chrome(options=options)
        return driver

    # 2) Chrome chuẩn (webdriver-manager) — KHÔNG set user-data-dir
    print("[i] Driver: selenium-standard (Chrome, no user-data-dir)")
    from selenium.webdriver import ChromeOptions
    options = ChromeOptions()
    _apply_chrome_common(options)
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
    except Exception:
        pass
    return driver

def make_firefox():
    print("[i] Driver: selenium-standard (Firefox fallback)")
    from selenium.webdriver import FirefoxOptions
    options = FirefoxOptions()
    _apply_firefox_common(options)
    service = FxService(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)
    return driver

def click_cookie_banner(driver):
    texts = ["Chấp nhận", "Đồng ý", "Tôi đồng ý", "Chấp nhận tất cả", "Accept", "Got it"]
    for t in texts:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, f"//button[contains(., '{t}')]"))
            )
            btn.click()
            time.sleep(0.4)
            break
        except Exception:
            continue

def smart_load(driver, rounds=22, pause=1.0):
    last_count = 0
    last_height = 0
    for _ in range(rounds):
        # click “Xem thêm/Tải thêm/Load more/Trang sau/>>”
        try:
            btns = driver.find_elements(
                By.XPATH,
                "//button[contains(., 'Xem thêm') or contains(., 'Tải thêm') or contains(., 'Load more')]"
                " | //a[contains(., 'Xem thêm') or contains(., 'Tải thêm') or contains(., 'Trang sau') or contains(., '>>')]"
            )
            for b in btns:
                try:
                    if b.is_enabled() and b.is_displayed():
                        b.click()
                        time.sleep(pause)
                except Exception:
                    continue
        except Exception:
            pass

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)

        try:
            new_height = driver.execute_script("return document.body.scrollHeight")
            links_count = driver.execute_script("return document.querySelectorAll('a[href$=\".html\"]').length")
        except Exception:
            new_height, links_count = 0, 0

        if new_height == last_height and links_count == last_count:
            break
        last_height = new_height
        last_count  = links_count

def collect_links_js(driver, focus: str, max_items: int) -> List[Tuple[str, str]]:
    raw = driver.execute_script("""
      return Array.from(document.querySelectorAll('a[href$=".html"]')).map(a => {
        return [a.href, (a.title || a.textContent || '').trim()];
      });
    """)
    seen, out = set(), []
    domain = "https://kinhtedothi.vn"
    for href, text in raw:
        if not href.startswith(domain):
            continue
        href_l = href.lower()
        if focus and focus not in href_l:
            # nếu lọc quá chặt, vẫn chấp nhận link dạng ...12345.html
            if not re.search(r"\\d+\\.html$", href_l):
                continue
        if href in seen:
            continue
        seen.add(href)
        if not text:
            text = href.rsplit("/", 1)[-1].replace("-", " ").strip()
        text = re.sub(r"\\s+", " ", text)
        out.append((href, text))
        if len(out) >= max_items:
            break
    return out

def build_rss(items: List[Tuple[str,str]], channel_link: str) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '<channel>',
        f'<title>Kinh tế & Đô thị — Pseudo feed</title>',
        f'<link>{html.escape(channel_link)}</link>',
        '<description>Feed giả lập trích từ chuyên mục Kinh tế & Đô thị</description>',
        f'<pubDate>{now}</pubDate>',
    ]
    for href, title in items:
        parts += [
            "<item>",
            f"<title>{html.escape(title or 'Bài viết')}</title>",
            f"<link>{html.escape(href)}</link>",
            f"<pubDate>{now}</pubDate>",
            "</item>"
        ]
    parts += ["</channel></rss>"]
    return "\n".join(parts)

def main():
    print(f"[i] URL: {URL}")
    print(f"[i] Headless: {HEADLESS} | Focus: {FOCUS_SUB or '(none)'}")
    driver = None
    tried_firefox = False
    try:
        # Try Chrome first
        try:
            driver = make_chrome()
        except Exception as e1:
            print("[!] Chrome init failed → fallback Firefox. Lý do:", e1)
            tried_firefox = True
            driver = make_firefox()

        driver.get(URL)
        WebDriverWait(driver, 25).until(lambda d: d.execute_script("return document.readyState") == "complete")
        click_cookie_banner(driver)

        try:
            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href$='.html']")))
        except Exception:
            pass

        smart_load(driver, rounds=22, pause=1.0)
        links = collect_links_js(driver, FOCUS_SUB, MAX_ITEMS)

        # ghi debug
        with open("debug_links.txt", "w", encoding="utf-8") as f:
            for href, title in links:
                f.write(f"{title} | {href}\n")

        if not links:
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("❗ Không lấy được bài nào. Kiểm tra debug_page.html & debug_links.txt.")
            print("Gợi ý: set KINHTEDOTHI_HEADLESS=0, xoá KINHTEDOTHI_FOCUS, tăng rounds; hoặc thử Firefox/Chrome ngược lại.")
            return

        xml = build_rss(links, URL)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.write(xml)

        print(f"✅ Lấy {len(links)} bài. Ghi -> {OUT_FILE}")
        for i, (href, title) in enumerate(links[:5], 1):
            print(f"  {i}. {title}\n     {href}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

if __name__ == "__main__":
    main()
