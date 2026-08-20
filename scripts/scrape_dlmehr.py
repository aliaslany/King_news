import json, re, html, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CHANNEL = "dlmehr"
OUT = Path("news.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}
# Telegram's public web preview exposes channel history without an API account.
# We crawl backwards from the newest public post and stop once posts are older than the window.
WINDOW = timedelta(hours=26)  # small overlap protects against scheduling delays
MAX_PAGES = 12


def clean_text(node):
    if not node:
        return ""
    text = node.get_text("\n", strip=True)
    return html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()


def is_list_post(text):
    """Keep the characteristic Merzad posts that contain lists of titles.

    We intentionally reject ordinary prose/news posts. A list post normally has
    several numbered/bulleted title lines and often Telegram links to individual items.
    """
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 3:
        return False
    numbered = sum(bool(re.match(r"^(?:\d+|[۰-۹]+)[.)、:-]\s+", x)) for x in lines)
    bullets = sum(bool(re.match(r"^(?:[-•▪️🔹🔸])\s+", x)) for x in lines)
    links = len(re.findall(r"https?://t\.me/[^\s]+", text))
    # Lists of titles usually contain either multiple numbered entries or several links.
    return numbered >= 3 or (links >= 3 and (numbered + bullets) >= 2)


def parse_date(s):
    if not s:
        return None
    # Telegram web normally renders ISO datetime in the time element.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_page(page_url):
    r = requests.get(page_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        post = wrap.select_one(".tgme_widget_message")
        if not post:
            continue
        text_node = post.select_one(".tgme_widget_message_text")
        text = clean_text(text_node)
        if not text or not is_list_post(text):
            continue
        time_node = post.select_one("time[datetime]")
        dt = parse_date(time_node.get("datetime") if time_node else None)
        link = post.select_one("a.tgme_widget_message_date")
        href = link.get("href") if link else ""
        if not href:
            continue
        post_url = urljoin("https://t.me/", href)
        m = re.search(r"/dlmehr/(\d+)", post_url)
        post_id = int(m.group(1)) if m else None
        if not post_id:
            continue
        posts.append({"id": post_id, "date": dt, "text": text, "url": post_url})
    return posts


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW
    all_posts = []
    before = None
    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{CHANNEL}" + (f"?before={before}" if before else "")
        try:
            batch = parse_page(url)
        except requests.RequestException as exc:
            print(f"Fetch failed: {url}: {exc}")
            break
        if not batch:
            break
        all_posts.extend(batch)
        oldest = min((p["date"] for p in batch if p["date"]), default=None)
        before = min(p["id"] for p in batch)
        if oldest and oldest < cutoff:
            break
        time.sleep(1)

    # Deduplicate and retain only recent list posts.
    unique = {p["id"]: p for p in all_posts if p["date"] and p["date"] >= cutoff}
    posts = sorted(unique.values(), key=lambda p: p["date"], reverse=True)

    # Preserve the existing archive while replacing today's collected set.
    old = {"updatedAt": "", "news": []}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    archive = {str(x.get("id")): x for x in old.get("news", []) if x.get("id")}

    for p in posts:
        # Each qualifying Telegram post becomes ONE card. The original list is kept intact.
        archive[str(p["id"])] = {
            "id": p["id"],
            "date": p["date"].isoformat(),
            "title_fa": "فهرست روزانه فناوری و آینده",
            "title_en": "Daily Technology & Future List",
            "summary_fa": p["text"],
            "summary_en": p["text"],
            "category": "AI · TECHNOLOGY · FUTURE",
            "url": p["url"],
            "source": CHANNEL,
        }

    # Keep a reasonable archive. The frontend can show today's cards while history remains available.
    items = sorted(archive.values(), key=lambda x: x.get("date", ""), reverse=True)[:1000]
    OUT.write_text(json.dumps({"updatedAt": now.isoformat(), "news": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Collected {len(posts)} list posts from the last ~24h; archive={len(items)}")


if __name__ == "__main__":
    main()
