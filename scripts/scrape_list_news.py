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
    "Accept-Language": "fa,en;q=0.9",
}
WINDOW = timedelta(hours=26)
MAX_PAGES = 20
# The two posts supplied by the project owner are also used as bootstrap fixtures.
# This makes the first deployment deterministic even if Telegram's channel pager
# changes the amount of history exposed on /s/dlmehr.
BOOTSTRAP_IDS = (4837, 4838)


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
    if not node:
        return []
    result, seen = [], set()
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
        low = title.casefold()
        if len(title) < 8 or low in {"telegram", "instagram", "twitter", "x", "youtube"}:
            continue
        key = re.sub(r"\s+", " ", title).strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({"title": re.sub(r"\s+", " ", title).strip(), "url": href})
    return result


def extract_items(node, text):
    linked = extract_linked_items(node)
    if len(linked) >= 3:
        return linked
    items = parse_items(text)
    if len(items) >= 3:
        return items
    fallback = parse_fallback_title_url(text)
    if len(fallback) >= 3:
        return fallback
    return []


def is_list_candidate(text, node=None):
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    numbered = sum(bool(re.match(r"^(?:\d+|[۰-۹]+)\s*[.)،:-]\s+", x)) for x in lines)
    bullets = sum(bool(re.match(r"^(?:[-–—•▪️🔹🔸▫️◾️])\s+", x)) for x in lines)
    linked_count = len(extract_linked_items(node)) if node else 0
    literal_links = len(re.findall(r"https?://[^\s]+", text or ""))
    return numbered >= 3 or bullets >= 3 or linked_count >= 3 or literal_links >= 3


def parse_document(soup, expected_id=None):
    posts = []
    wraps = soup.select(".tgme_widget_message_wrap")
    if not wraps:
        # Direct message pages can expose the message without the wrapper list.
        node = soup.select_one(".tgme_widget_message")
        wraps = [node] if node else []

    for wrap in wraps:
        post = wrap.select_one(".tgme_widget_message") if hasattr(wrap, "select_one") else None
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
            # Direct pages sometimes contain the canonical URL in the HTML.
            match = re.search(r"(?:t\.me|telegram\.me)/dlmehr/(\d+)", str(post))
        if not match:
            continue
        post_id = int(match.group(1))
        if expected_id is not None and post_id != expected_id:
            continue
        text_node = post.select_one(".tgme_widget_message_text")
        text = clean(text_node)
        posts.append({
            "id": post_id,
            "date": dt,
            "url": urljoin("https://t.me/", href) if href else f"https://t.me/{CHANNEL}/{post_id}",
            "text": text,
            "node": text_node,
        })
    return posts


def fetch_posts(url, expected_id=None):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return parse_document(soup, expected_id)


def parse_page(url):
    posts = fetch_posts(url)
    oldest_id = min((p["id"] for p in posts), default=None)
    return posts, oldest_id


def process_post(post, cutoff, force=False):
    dt = post["date"]
    if not force and (not dt or dt < cutoff):
        return None
    items = extract_items(post["node"], post["text"])
    if len(items) < 3:
        print(f"  rejected post {post['id']}: extracted={len(items)}, anchors={len(extract_linked_items(post['node']))}, text_len={len(post['text'])}")
        return None
    print(f"  ACCEPTED post {post['id']}: {len(items)} stories")
    return {
        "id": post["id"],
        "date": dt.isoformat() if dt else datetime.now(timezone.utc).isoformat(),
        "url": post["url"],
        "items": items,
    }


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW
    matches = {}
    pages_scanned = posts_scanned = 0

    # First, validate the exact posts supplied by the owner. These are deliberately
    # processed even if they are outside today's rolling window so the initial site
    # has real content and the parser can be verified against known examples.
    for post_id in BOOTSTRAP_IDS:
        try:
            posts = fetch_posts(f"https://t.me/{CHANNEL}/{post_id}", expected_id=post_id)
            if not posts:
                print(f"  bootstrap {post_id}: Telegram direct page returned no matching post")
                continue
            result = process_post(posts[0], cutoff, force=True)
            if result:
                matches[result["id"]] = result
        except requests.RequestException as exc:
            print(f"  bootstrap {post_id}: fetch failed: {exc}")

    # Then collect the normal rolling 26-hour window.
    before = None
    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{CHANNEL}" + (f"?before={before}" if before else "")
        try:
            posts, oldest_id = parse_page(url)
        except requests.RequestException as exc:
            raise SystemExit(f"Telegram public web fetch failed: {exc}")
        pages_scanned += 1
        posts_scanned += len(posts)
        if not posts:
            break
        for post in posts:
            result = process_post(post, cutoff)
            if result:
                matches[result["id"]] = result
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
            "id": x["id"], "date": x["date"],
            "title_fa": "سیگنال‌های فناوری و آینده",
            "title_en": "Technology & Future Signals",
            "summary_fa": "مجموعه‌ای منتخب از عناوین فناوری، هوش مصنوعی و آینده.",
            "summary_en": "A curated collection of technology, AI and future-facing titles.",
            "category": "AI · TECHNOLOGY · FUTURE", "url": x["url"],
            "source": CHANNEL, "items": x["items"],
        }

    news = sorted(archive.values(), key=lambda x: x.get("date", ""), reverse=True)[:1000]
    OUT.write_text(json.dumps({"updatedAt": now.isoformat(), "news": news}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scanned {pages_scanned} Telegram pages / {posts_scanned} posts; found {len(matches)} qualifying list posts; archive={len(news)}")


if __name__ == "__main__":
    main()
