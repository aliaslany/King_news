import re

INVISIBLE = "\u200c\u200d\u200f\ufeff"
DIGITS = "0123456789۰۱۲۳۴۵۶۷۸۹"
MARKER = re.compile(
    rf"(?:^|[\n|])\s*[{INVISIBLE}]*([{DIGITS}]{{1,3}})\s*(?:\||[.)،:-])\s*\.?\s*",
    re.UNICODE,
)


def to_int(value):
    return int(value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))


def clean_title(value):
    value = value.replace("\u200f", "").replace("\u200e", "").replace("\u200c", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t|.-–—")


def parse_numbered_block(text):
    """Parse Merzad's actual bilingual format.

    Telegram's public HTML currently flattens the numbered lines into text
    such as `7 | . Apple Vision Pro ...`.  The Persian half and English half
    each run from 1..N.  We intentionally parse the complete text instead of
    requiring newline-separated `1.` lines.
    """
    text = text.replace("\r", "")
    matches = list(MARKER.finditer(text))
    if not matches:
        return []

    raw = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = clean_title(text[match.end():end])
        number = to_int(match.group(1))
        if len(title) >= 12 and len(title) <= 700:
            raw.append((number, title))

    # A bilingual roundup has a numbered Persian sequence followed by the
    # same numbered English sequence. Split at the second occurrence of 1.
    first_one = next((i for i, (n, _) in enumerate(raw) if n == 1), None)
    second_one = next((i for i, (n, _) in enumerate(raw[first_one + 1:], first_one + 1) if n == 1), None) if first_one is not None else None

    if first_one is not None and second_one is not None:
        fa = [(n, t) for n, t in raw[first_one:second_one] if n > 0]
        en = [(n, t) for n, t in raw[second_one:] if n > 0]
        fa_map = {n: t for n, t in fa}
        en_map = {n: t for n, t in en}
        nums = sorted(set(fa_map) & set(en_map))
        if len(nums) >= 3:
            return [
                {"title_fa": fa_map[n], "title_en": en_map[n], "title": fa_map[n], "url": None}
                for n in nums
            ]

    # Monolingual numbered roundup fallback.
    seen = set()
    result = []
    for n, title in raw:
        if n in seen:
            continue
        seen.add(n)
        result.append({"title": title, "url": None})
    return result


def parse_items(text):
    return parse_numbered_block(text)


def parse_fallback_title_url(text):
    # Kept for non-Merzad compatibility; numbered parsing is preferred.
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    result, pending = [], None
    for line in lines:
        urls = re.findall(r"https?://[^\s<>]+", line, re.I)
        if urls and pending:
            result.append({"title": pending, "url": urls[0]})
            pending = None
        elif not urls and len(line) >= 12:
            pending = f"{pending} {line}".strip() if pending else line
    return result
