# Daily Telegram collector setup

The collector uses Telethon because the public Telegram web preview is not a reliable history API. Telethon provides access to channel message history and supports portable `StringSession` credentials. See the official Telethon documentation for StringSession details.

## 1. Create Telegram API credentials

Create `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from Telegram's developer tools.

## 2. Create a StringSession

Run locally:

```bash
pip install 'telethon>=1.44,<2'
python -c "from telethon.sync import TelegramClient; from telethon.sessions import StringSession; import os; c=TelegramClient(StringSession(), int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH']); c.start(); print(c.session.save()); c.disconnect()"
```

Set the two environment variables first. The printed StringSession is sensitive: never commit it to the repository. Telethon explicitly documents StringSession as a portable session representation and warns that session credentials must be protected.

## 3. Add GitHub Actions secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION`

The workflow already reads these secrets.

## 4. Daily behavior

`.github/workflows/daily-news.yml` runs once per day and can also be started manually with **Run workflow**.

The collector:

1. Reads the previous 24 hours from `@dlmehr`.
2. Accepts a variable number of posts.
3. Filters toward AI, technology, science, robotics, space, chips, quantum and future-facing material.
4. Rejects obvious advertising/promotional posts.
5. Creates one JSON record per qualifying Telegram message.
6. Merges records into the archive without duplicating message IDs.
7. Keeps up to 1,000 cards.
8. Commits `news.json`, which automatically triggers the GitHub Pages deployment.

The collector intentionally does **not** treat the site as a breaking-news service. The editorial model is a daily technology/future intelligence digest.
