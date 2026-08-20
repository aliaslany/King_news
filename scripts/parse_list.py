import re


def is_list_line(line):
    return bool(re.match(r"^(?:\d+|[۰-۹]+)[.)،:-]\s+", line)) or bool(re.match(r"^(?:[-•▪️🔹🔸])\s+", line))


def parse_items(text):
    """Extract individual title entries from a Merzad-style list message."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    items = []
    current = None
    for line in lines:
        if is_list_line(line):
            if current:
                items.append(current)
            title = re.sub(r"^(?:\d+|[۰-۹]+)[.)،:-]\s+", "", line)
            title = re.sub(r"^(?:[-•▪️🔹🔸])\s+", "", title).strip()
            current = {"title": title, "url": None}
        elif current:
            m = re.search(r"https?://[^\s]+", line)
            if m:
                current["url"] = m.group(0).rstrip(".,،")
            elif len(line) < 280 and not re.match(r"^(?:https?://|🆔|@)", line):
                current["title"] += " " + line
    if current:
        items.append(current)
    return items
