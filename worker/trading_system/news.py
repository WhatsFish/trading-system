import datetime as dt
import email.utils
import html
import urllib.request
import xml.etree.ElementTree as ET


FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
}


def fetch_news(limit_per_feed: int = 20) -> list[dict]:
    items: list[dict] = []
    for source, url in FEEDS.items():
        request = urllib.request.Request(
            url, headers={"User-Agent": "trading-system/0.1"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            root = ET.parse(response).getroot()
        for item in root.findall(".//item")[:limit_per_feed]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            summary = item.findtext("description") or ""
            published = item.findtext("pubDate")
            parsed = email.utils.parsedate_to_datetime(published) if published else None
            items.append(
                {
                    "source": source,
                    "published_at": parsed or dt.datetime.now(dt.timezone.utc),
                    "title": html.unescape(title).strip(),
                    "url": link.strip(),
                    "summary": html.unescape(summary).strip()[:2000],
                }
            )
    return items


def save_news(connection, items: list[dict]) -> int:
    inserted = 0
    with connection.cursor() as cursor:
        for item in items:
            cursor.execute(
                """
                INSERT INTO news_item
                  (source, published_at, title, url, summary)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source, url) DO NOTHING
                """,
                (
                    item["source"],
                    item["published_at"],
                    item["title"],
                    item["url"],
                    item["summary"],
                ),
            )
            inserted += cursor.rowcount
    return inserted

