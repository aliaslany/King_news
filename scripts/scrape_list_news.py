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
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) if value else None
    except ValueError:
        return None


def external_anchors(post):
    out = []
    seen = set()
    for a in post.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = clean(a)
        if href.startswith("//"):
            href = "https:" + href
        if not re.match(r"^https?://", href, re.I) or not title:
            continue
        # Ignore Telegram's own message metadata and social boilerplate.
        if href.startswith("https://t.me/") and len(title) < 12:
            continue
        if title.casefold() in {"telegram", "instagram", "twitter", "youtube", "x"}:
            continue
        key = (re.sub(r"\s+", " ", title).strip().casefold(), href)
        if key not in seen:
            seen.add(key)
            out.append({"title": re.sub(r"\s+", " ", title).strip(), "url": href})
    return out


def extract_items(post, text):
    # Most robust path: inspect the raw Telegram post DOM, not only text.
    anchors = external_anchors(post)
    if len(anchors) >= 3:
        return anchors

    items = parse_items(text)
    if len(items) >= 3:
        return items

    fallback = parse_fallback_title_url(text)
    if len(fallback) >= 3:
        return fallback

    return []


def roundup_score(post, text, items):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    score = 0
    if len(lines) >= 6:
        score += 2
    if len(lines) >= 10:
        score += 2
    if len(items) >= 3:
        score += 5
    if len(items) >= 5:
        score += 2
    if len(external_anchors(post)) >= 5:
        score += 3
    numbered = sum(bool(re.match(r"^\s*(?:\d+|[۰-۹]+)\s*[.)،:-]\s+", x)) for x in lines)
    bullets = sum(bool(re.match(r"^\s*[-–—•▪️🔹🔸▫️◾️]", x)) for x in lines)
    score += min(numbered, 5)
    score += min(bullets, 3)
    return score


def parse_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    posts = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
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
            "post": post,
        })
    return posts, min((p["id"] for p in posts), default=None)


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW
    matches = {}
    before = None
    pages_scanned = posts_scanned = 0

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

        for p in posts:
            if not p["date"] or p["date"] < cutoff:
                continue
            items = extract_items(p["post"], p["text"])
            score = roundup_score(p["post"], p["text"], items)
            # Channel-specific principle: we only need genuine multi-story roundups.
            # Use the content structure rather than requiring a specific numbering style.
            accepted = len(items) >= 3 and score >= 7
            if accepted:
                matches[p["id"]] = {
                    "id": p["id"],
                    "date": p["date"].isoformat(),
                    "url": p["url"],
                    "items": items[:80],
                }
                print(f"ACCEPTED post {p['id']}: {len(items)} stories, score={score}")

        if oldest_id is None or oldest_id <= 1:
            break
        dates = [p["date"] for p in posts if p["date"]]
        if dates and min(dates) < cutoff:
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
    OUT.write_text(json.dumps({"updatedAt": now.isoformat(), "news": news}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scanned {pages_scanned} Telegram pages / {posts_scanned} posts; found {len(matches)} qualifying list posts; archive={len(news)}")


if __name__ == "__main__":
    main()
