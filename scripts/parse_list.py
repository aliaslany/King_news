import re
from urllib.parse import urlparse

NUMBER = r"(?:\d{1,3}|[۰-۹]{1,3})"
PREFIX_RE = re.compile(rf"^\s*(?:{NUMBER}\s*[.)،:-]|[-•▪️🔹🔸▪︎▫︎])\s*", re.UNICODE)
URL_RE = re.compile(r"https?://[^\s<>]+", re.I)

# Common separators used by curated Persian technology/news roundups.
SEPARATOR_RE = re.compile(r"\s*(?:\n|\r\n|[|｜])\s*")


def normalize(line):
    return re.sub(r"\s+", " ", line).strip(" \t•▪️🔹🔸")


def is_noise(line):
    s = normalize(line)
    if not s:
        return True
    if URL_RE.fullmatch(s):
        return True
    if re.match(r"^(?:https?://|t\.me/|@\w+|🆔)", s, re.I):
        return True
    return False


def is_list_line(line):
    return bool(PREFIX_RE.match(line))


def parse_items(text):
    """Extract story titles from Merzad-style curated roundup posts.

    The collector deliberately supports several layouts: numbered entries,
    bullet entries, and title lines followed by a URL. A post is accepted by
    the scraper only after enough story candidates have been found.
    """
    raw = [normalize(x) for x in text.replace("\r", "").split("\n")]
    lines = [x for x in raw if x]
    items = []
    current = None

    def flush():
        nonlocal current
        if current and current.get("title") and len(current["title"]) >= 8:
            items.append(current)
        current = None

    for line in lines:
        if is_list_line(line):
            flush()
            title = PREFIX_RE.sub("", line).strip()
            urls = URL_RE.findall(title)
            title = URL_RE.sub("", title).strip(" -–—:|")
            current = {"title": title, "url": urls[0] if urls else None}
            continue

        urls = URL_RE.findall(line)
        if current:
            if urls:
                current["url"] = current.get("url") or urls[0]
                continuation = URL_RE.sub("", line).strip(" -–—:|")
                if continuation and len(continuation) < 240:
                    current["title"] += " " + continuation
            elif not is_noise(line) and len(line) <= 260:
                current["title"] += " " + line
        elif not is_noise(line):
            # Some roundups don't number the first/title lines. Keep a
            # candidate so the fallback detector can use title+URL pairs.
            current = {"title": line, "url": None}

    flush()

    # Remove obvious header/footer candidates and duplicates.
    seen = set()
    result = []
    for item in items:
        title = normalize(item["title"])
        key = title.casefold()
        if key in seen or len(title) < 8:
            continue
        seen.add(key)
        result.append({"title": title, "url": item.get("url")})
    return result


def parse_fallback_title_url(text):
    """Fallback for posts where each story is simply a title followed by a URL."""
    lines = [normalize(x) for x in text.replace("\r", "").split("\n") if normalize(x)]
    result = []
    pending = None
    for line in lines:
        urls = URL_RE.findall(line)
        if urls:
            if pending:
                result.append({"title": pending, "url": urls[0]})
                pending = None
            continue
        if not is_noise(line) and len(line) >= 10 and len(line) <= 240:
            if pending:
                # A long consecutive title is more likely continuation text.
                pending += " " + line
            else:
                pending = line
    return result
