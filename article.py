"""Fetch the full text of a news article from its URL.

No Telegram or model imports - testable on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = 25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)
MIN_PARAGRAPH_CHARS = 40
STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "figure")


@dataclass(frozen=True)
class Article:
    title: str
    text: str
    url: str

    @property
    def words(self) -> int:
        return len(self.text.split())


class ArticleError(Exception):
    """Raised when an article cannot be fetched or has no usable body."""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in ("h1", "title"):
        node = soup.find(selector)
        if node and node.get_text(strip=True):
            return _clean(node.get_text())
    return "Untitled"


def _extract_body(soup: BeautifulSoup) -> str:
    """Prefer <article>; otherwise take the densest block of paragraphs."""
    container = soup.find("article") or soup.find("main") or soup

    paragraphs = [
        _clean(p.get_text())
        for p in container.find_all("p")
        if len(_clean(p.get_text())) >= MIN_PARAGRAPH_CHARS
    ]

    return "\n\n".join(paragraphs)


def fetch_article(url: str) -> Article:
    """Download one article and pull out its headline and body text."""
    try:
        response = httpx.get(
            url,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ArticleError(f"Could not fetch the article: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(list(STRIP_TAGS)):
        tag.decompose()

    body = _extract_body(soup)
    if not body:
        raise ArticleError("No article text found at that URL.")

    return Article(title=_extract_title(soup), text=body, url=url)
