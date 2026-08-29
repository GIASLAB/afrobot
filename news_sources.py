"""Fetch, merge and filter Pan-African news headlines from RSS feeds.

Kept free of Telegram imports so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import calendar
import re
from dataclasses import dataclass
from time import time

import feedparser
import httpx

PRIMARY_SOURCE = "Business Insider Africa"

FEEDS = {
    PRIMARY_SOURCE: "https://africa.businessinsider.com/rss",
    "BI Leaders": "https://africa.businessinsider.com/local/leaders/rss",
    "BI Markets": "https://africa.businessinsider.com/local/markets/rss",
    "BI Careers": "https://africa.businessinsider.com/local/careers/rss",
    "BI Politics": "https://africa.businessinsider.com/politics/rss",
    "AllAfrica": "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf",
    "BBC Africa": "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
    "African Business": "https://african.business/feed",
}

REQUEST_TIMEOUT = 20
CACHE_SECONDS = 300
USER_AGENT = "Mozilla/5.0 (compatible; AfrocentricBot/1.0)"


@dataclass(frozen=True)
class Headline:
    title: str
    link: str
    source: str
    published: float  # epoch seconds; 0.0 when the feed omits a date
    summary: str = ""


_cache: tuple[float, tuple[Headline, ...]] = (0.0, ())


def _published_epoch(entry) -> float:
    """Best-effort publication time; 0.0 when the feed gives us nothing."""
    for key in ("published_parsed", "updated_parsed"):
        stamp = entry.get(key)
        if stamp:
            return float(calendar.timegm(stamp))
    return 0.0


def _clean_summary(entry) -> str:
    """Feed summaries arrive as HTML; flatten to plain text."""
    raw = entry.get("summary", "") or ""
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"\[[^\]]*\]", "", text)  # drop "[Bird Story Agency]" prefixes
    return " ".join(text.split())


def _parse(source: str, raw: bytes) -> tuple[Headline, ...]:
    parsed = feedparser.parse(raw)
    return tuple(
        Headline(
            title=" ".join(entry.title.split()),
            link=entry.get("link", ""),
            source=source,
            published=_published_epoch(entry),
            summary=_clean_summary(entry),
        )
        for entry in parsed.entries
        if entry.get("title")
    )


async def _fetch_one(client: httpx.AsyncClient, source: str, url: str) -> tuple[Headline, ...]:
    """One feed. A dead feed must never take the whole digest down."""
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return ()

    return _parse(source, response.content)


def _dedupe(headlines: tuple[Headline, ...]) -> tuple[Headline, ...]:
    seen: set[str] = set()
    unique: list[Headline] = []
    for headline in headlines:
        key = headline.title.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(headline)
    return tuple(unique)


async def fetch_headlines(force: bool = False) -> tuple[Headline, ...]:
    """All feeds merged, newest first. Cached for CACHE_SECONDS."""
    global _cache

    cached_at, cached = _cache
    if not force and cached and (time() - cached_at) < CACHE_SECONDS:
        return cached

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, source, url) for source, url in FEEDS.items())
        )

    merged = tuple(h for group in results for h in group)
    ordered = tuple(sorted(_dedupe(merged), key=_rank))

    if ordered:
        _cache = (time(), ordered)

    return ordered


def _rank(headline: Headline) -> tuple[int, float]:
    """Primary source leads; newest first within each tier."""
    tier = 0 if headline.source == PRIMARY_SOURCE else 1
    return (tier, -headline.published)


def filter_headlines(headlines: tuple[Headline, ...], keyword: str) -> tuple[Headline, ...]:
    """Case-insensitive substring match on the title."""
    needle = keyword.casefold().strip()
    if not needle:
        return headlines
    return tuple(h for h in headlines if needle in h.title.casefold())
