import json, re, html, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from parse_list import parse_items, parse_fallback_title_url

CHANNEL = "dlmehr"
OUT = Path("news.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept-Language": "fa,en;q=0.8",
}
WINDOW = timedelta(hours=26)
MAX_PAGES = 20


def clean(node):
    if not node:
        return ""
    return html.unescape(re.sub(r"\n{3,}", "\n\n", node.get_text("\n", strip=True))).strip()


def parse_date(node):
    if not node:
        return None
    value = node.get("datetime")
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def extract_linked_items(node):
    """Extract story titles directly from Telegram's rendered anchor HTML.

    This is important because Telegram's public preview often renders a
    roundup as clickable title anchors. Their hrefs disappear when the text
    is converted with get_text(), so looking only for literal http:// URLs
    incorrectly classified those posts as ordinary prose.
    """
    if not node:
        return []

    result = []
    seen = set()
    for a in node.select("a[href]"):
        title = clean(a)
        href = a.get("href", "").strip()
        if not title or not href:
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin("https://t.me/", href)
        if not href.startswith(("http://", "https://")):
            continue

        # Ignore Telegram/channel metadata and social boilerplate.
        low = title.casefold()
        if len(title) < 8 or low in {"telegram", "instagram", "twitter", "x", "youtube"}:
            continue
        if href.startswith("https://t.me/") and len(title) < 12:
            continue

        key = re.sub(r"\s+", " ", title).strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({"title": re.sub(r"\s+", " ", title).strip(), "url": href})

    return result


def extract_items(node, text):
    # 1. Prefer actual hyperlinks in Telegram's HTML.
    linked = extract_linked_items(node)
    if len(linked) >= 3:
        return linked

    # 2. Support numbered/bulleted visible text lists.
    items = parse_items(text)
    if len(items) >= 3:
        return items

    # 3. Support title-on-one-line + URL-on-next-line roundups.
    fallback = parse_fallback_title_url(text)
    if len(fallback) >= 3:
        return fallback

    return []


def is_list_candidate(text, node=None):
    if not text:
        return False
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 3:
        return False

    numbered = sum(bool(re.match(r"^(?:\d+|[۰-۹]+)\s*[.)،:-]\s+", x)) for x in lines)
    bullets = sum(bool(re.match(r"^(?:[-–—•▪️🔹🔸▫️◾️])\s+", x)) for x in lines)
    linked_count = len(extract_linked_items(node)) if node else 0
    literal_links = len(re.findall(r"https?://[^\s]+", text))

    return numbered >= 3 or bullets >= 3 or linked_count >= 3 or literal_links >= 3


def parse_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    wraps = soup.select(".tgme_widget_message_wrap")
    posts = []

    for wrap in wraps:
        post = wrap.select_one(".tgme_widget_message")
        if not post:
            continue

        date_node = post.select_one("time[datetime]")
        dt = parse_date(date_node)
        link_node = post.select_one("a.tgme_widget_message_date")
        href = link_node.get("href", "") if link_node else ""
        match = re.search(r"/dlmehr/(\d+)(?:$|[?#])", href)
        if not match:
            match = re.search(r"data-post=[\"']dlmehr/(\d+)", str(post))
        if not match:
            continue

        post_id = int(match.group(1))
        text_node = post.select_one(".tgme_widget_message_text")
        text = clean(text_node)
        posts.append({
            "id": post_id,
            "date": dt,
            "url": urljoin("https://t.me/", href) if href else f"https://t.me/{CHANNEL}/{post_id}",
            "text": text,
            "node": text_node,
        })

    oldest_id = min((p["id"] for p in posts), default=None)
    return posts, oldest_id


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW
    matches = {}
    before = None
    pages_scanned = 0
    posts_scanned = 0

    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{CHANNEL}" + (f"?before={before}" if before else "")
        try:
            posts, oldest_id = parse_page(url)
        except requests.RequestException as exc:
            raise SystemExit(f"Telegram public web fetch failed: {exc}")

        pages_scanned += 1
        posts_scanned += len(posts)
        if not posts:
            print(f"No Telegram posts found on {url}; stopping.")
            break

        for post in posts:
            dt = post["date"]
            if not dt or dt < cutoff:
                continue

            if not is_list_candidate(post["text"], post["node"]):
                continue

            items = extract_items(post["node"], post["text"])
            if len(items) < 3:
                continue

            matches[post["id"]] = {
                "id": post["id"],
                "date": dt.isoformat(),
                "url": post["url"],
                "items": items,
            }
            print(f"  accepted post {post['id']}: {len(items)} stories")

        if oldest_id is None or oldest_id <= 1:
            break
        oldest_dates = [p["date"] for p in posts if p["date"]]
        if oldest_dates and min(oldest_dates) < cutoff:
            break
        if before == oldest_id:
            break
        before = oldest_id
        time.sleep(1)

    old = {"updatedAt": "", "news": []}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    archive = {str(x.get("id")): x for x in old.get("news", []) if x.get("id")}

    for x in matches.values():
        archive[str(x["id"])] = {
            "id": x["id"],
            "date": x["date"],
            "title_fa": "سیگنال‌های امروز فناوری و آینده",
            "title_en": "Today’s Technology & Future Signals",
            "summary_fa": "مجموعه‌ای منتخب از عناوین فناوری، هوش مصنوعی و آینده.",
            "summary_en": "A curated collection of technology, AI and future-facing titles.",
            "category": "AI · TECHNOLOGY · FUTURE",
            "url": x["url"],
            "source": CHANNEL,
            "items": x["items"],
        }

    news = sorted(archive.values(), key=lambda x: x.get("date", ""), reverse=True)[:1000]
    OUT.write_text(
        json.dumps({"updatedAt": now.isoformat(), "news": news}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"Scanned {pages_scanned} Telegram pages / {posts_scanned} posts; "
        f"found {len(matches)} qualifying list posts; archive={len(news)}"
    )


if __name__ == "__main__":
    main()
