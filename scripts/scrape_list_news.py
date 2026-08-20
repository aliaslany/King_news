import json, re, html, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from parse_list import parse_items

CHANNEL = "dlmehr"
OUT = Path("news.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}
WINDOW = timedelta(hours=26)
MAX_PAGES = 12


def clean(node):
    return html.unescape(re.sub(r"\n{3,}", "\n\n", node.get_text("\n", strip=True))).strip() if node else ""


def looks_like_list(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    numbered = sum(bool(re.match(r"^(?:\d+|[۰-۹]+)[.)،:-]\s+", x)) for x in lines)
    bullets = sum(bool(re.match(r"^(?:[-•▪️🔹🔸])\s+", x)) for x in lines)
    links = len(re.findall(r"https?://\S+", text))
    return len(lines) >= 3 and (numbered >= 3 or (bullets + numbered >= 3 and links >= 2))


def parse_date(node):
    try:
        return datetime.fromisoformat(node.get("datetime").replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    result = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        post = wrap.select_one(".tgme_widget_message")
        node = post.select_one(".tgme_widget_message_text") if post else None
        text = clean(node)
        if not text or not looks_like_list(text):
            continue
        items = parse_items(text)
        if len(items) < 3:
            continue
        t = post.select_one("time[datetime]")
        dt = parse_date(t) if t else None
        a = post.select_one("a.tgme_widget_message_date")
        href = a.get("href") if a else ""
        m = re.search(r"/dlmehr/(\d+)", href)
        if not (dt and href and m):
            continue
        result.append({"id": int(m.group(1)), "date": dt.isoformat(), "url": urljoin("https://t.me/", href), "items": items})
    return result


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW
    found = []
    before = None
    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{CHANNEL}" + (f"?before={before}" if before else "")
        try:
            batch = fetch(url)
        except requests.RequestException as e:
            print("scrape error:", e)
            break
        if not batch:
            break
        found.extend(batch)
        before = min(x["id"] for x in batch)
        if min(datetime.fromisoformat(x["date"]) for x in batch) < cutoff:
            break
        time.sleep(1)

    recent = {x["id"]: x for x in found if datetime.fromisoformat(x["date"]) >= cutoff}
    old = {"updatedAt": "", "news": []}
    if OUT.exists():
        try: old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception: pass
    archive = {str(x.get("id")): x for x in old.get("news", []) if x.get("id")}
    for x in recent.values():
        archive[str(x["id"])] = {
            "id": x["id"], "date": x["date"],
            "title_fa": "سیگنال‌های امروز فناوری و آینده",
            "title_en": "Today’s Technology & Future Signals",
            "summary_fa": "مجموعه‌ای منتخب از عناوین فناوری، هوش مصنوعی و آینده.",
            "summary_en": "A curated collection of technology, AI and future-facing titles.",
            "category": "AI · TECHNOLOGY · FUTURE", "url": x["url"], "source": CHANNEL,
            "items": x["items"]
        }
    news = sorted(archive.values(), key=lambda x: x.get("date", ""), reverse=True)[:1000]
    OUT.write_text(json.dumps({"updatedAt": now.isoformat(), "news": news}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Found {len(recent)} qualifying list posts; archive={len(news)}")

if __name__ == "__main__": main()
