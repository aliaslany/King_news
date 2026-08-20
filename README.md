# King News

A bilingual Persian/English daily news portal for posts from Merzad's Telegram channel.

## Architecture

```text
Telegram channel
      ↓
Daily GitHub Actions collector
      ↓
24-hour post extraction / normalization
      ↓
news.json
      ↓
GitHub Pages
      ↓
Dynamic bilingual news cards
```

The frontend is intentionally static so it can run on GitHub Pages. The collector runs once a day and writes normalized news items to `news.json`. The number of posts is not fixed: every run replaces/updates the dataset with whatever qualifying posts were found in the previous 24-hour window.

## News schema

Each card supports:

- `title_fa`
- `title_en`
- `summary_fa`
- `summary_en`
- `date`
- `category`
- `url`

The UI automatically falls back to the original title/summary when a translation is unavailable.

## Deployment

Enable GitHub Pages with the repository's deployment workflow once the collector workflow is added. No server is required for the frontend.
