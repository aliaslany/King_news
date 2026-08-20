import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

CHANNEL = os.getenv('TELEGRAM_CHANNEL', 'dlmehr')
API_ID = int(os.environ['TELEGRAM_API_ID'])
API_HASH = os.environ['TELEGRAM_API_HASH']
SESSION = os.environ['TELEGRAM_SESSION']
DATA = Path('news.json')

# The site is intentionally focused on technology, AI and future-facing material.
POSITIVE = [
    'هوش مصنوعی','هوش‌مصنوعی','فناوری','تکنولوژی','آینده','ربات','رباتیک','ماشین','مدل زبانی',
    'یادگیری ماشین','یادگیری عمیق','پردازنده','تراشه','کوانتوم','فضا','ماهواره','خودران','واقعیت مجازی',
    'واقعیت افزوده','AGI','AI','LLM','GPT','Claude','Gemini','OpenAI','Anthropic','Google DeepMind',
    'robot','robotics','artificial intelligence','machine learning','deep learning','quantum','space',
    'chip','semiconductor','autonomous','humanoid','agent','future','technology','tech'
]
NEGATIVE = ['تبلیغ','فروش ویژه','خرید کنید','قرعه‌کشی','تخفیف','استخدام فوری','promo','advertisement','giveaway']


def clean(text: str) -> str:
    text = text or ''
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def title_from(text: str) -> str:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        return 'بدون عنوان'
    first = re.sub(r'^[\W_]+', '', lines[0])
    return first[:180] or 'بدون عنوان'


def score(text: str) -> int:
    t = text.lower()
    return sum(2 if k.lower() in t else 0 for k in POSITIVE) - sum(4 if k.lower() in t else 0 for k in NEGATIVE)


def category(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ['هوش مصنوعی','هوش‌مصنوعی','ai','llm','gpt','claude','gemini','openai','anthropic']): return 'AI'
    if any(k in t for k in ['ربات','robot','robotics','humanoid']): return 'ROBOTICS'
    if any(k in t for k in ['فضا','ماهواره','space','rocket','mars','moon']): return 'SPACE'
    if any(k in t for k in ['کوانتوم','quantum','تراشه','chip','پردازنده','processor']): return 'DEEP TECH'
    return 'FUTURE TECH'


async def main():
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    await client.start()
    found = []
    async for m in client.iter_messages(CHANNEL, limit=300):
        if not m.date:
            continue
        dt = m.date if m.date.tzinfo else m.date.replace(tzinfo=timezone.utc)
        if dt < since:
            break
        text = clean(m.message or '')
        if not text or score(text) <= 0:
            continue
        found.append({
            'id': m.id,
            'title': title_from(text),
            'title_fa': title_from(text),
            'summary': text[:900],
            'summary_fa': text[:900],
            'date': dt.isoformat(),
            'category': category(text),
            'url': f'https://t.me/{CHANNEL}/{m.id}',
        })
    await client.disconnect()

    old = {'updatedAt': '', 'news': []}
    if DATA.exists():
        try:
            old = json.loads(DATA.read_text(encoding='utf-8'))
        except Exception:
            pass
    existing = {str(x.get('id')): x for x in old.get('news', [])}
    for item in found:
        existing[str(item['id'])] = item
    merged = list(existing.values())
    merged.sort(key=lambda x: x.get('date',''), reverse=True)
    # Keep a useful archive while preventing an endlessly growing JSON file.
    merged = merged[:1000]
    output = {'updatedAt': now.isoformat(), 'source': f'https://t.me/{CHANNEL}', 'news': merged}
    DATA.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Collected {len(found)} qualifying posts; archive contains {len(merged)} cards.')


if __name__ == '__main__':
    asyncio.run(main())
