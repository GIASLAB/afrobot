"""Score headlines on how likely they are to travel, for this channel.

Tuned to Emmanuel's niche: African resource sovereignty, hard economic
numbers, great-power manoeuvring. Scores are transparent - every point
comes with a reason, so the ranking can be argued with and retuned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from time import time

from news_sources import Headline

# --- signal tables --------------------------------------------------------

SUPERLATIVES = (
    "largest", "biggest", "first", "record", "historic", "unprecedented",
    "highest", "fastest", "worst", "best", "top", "most", "never before",
)

POWER_MOVES = (
    "takes back", "seizes", "seized", "nationalis", "nationaliz", "expels",
    "expelled", "bans", "banned", "rejects", "rejected", "defies", "defied",
    "cancels", "cancelled", "terminates", "withdraws", "exits", "quits",
    "suspends", "blocks", "halts", "scraps", "revokes", "takeover",
)

SOVEREIGNTY = (
    "sovereignty", "independence", "control", "ownership", "owns", "reclaim",
    "self-reliance", "local content", "domestic", "indigenous", "repatriat",
)

COMMODITIES = (
    "gold", "uranium", "lithium", "cobalt", "oil", "gas", "diamond", "copper",
    "mineral", "mining", "bullion", "reserves", "platinum", "bauxite", "iron ore",
)

GREAT_POWERS = (
    "u.s.", "us", "america", "china", "chinese", "russia", "france", "french",
    "eu", "european union", "imf", "world bank", "brics", "uk", "washington",
)

CORE_COUNTRIES = (
    "zimbabwe", "ghana", "mali", "burkina faso", "niger", "zambia", "nigeria",
    "south africa", "senegal", "guinea", "drc", "congo", "tanzania", "kenya",
    "egypt", "ethiopia", "sahel",
)

CURRENCY = (
    "currency", "inflation", "cedi", "naira", "rand", "zig", "kwacha",
    "devalu", "exchange rate", "forex", "debt", "imf loan",
)

# Things that carry a shot: you can actually film or B-roll them.
VIDEO_VISUAL = (
    "mine", "mining", "bullion", "gold bar", "refinery", "smelter", "port",
    "railway", "power plant", "dam", "factory", "pipeline", "airport",
    "airline", "construction", "megaproject", "vault", "reserves", "banknote",
    "convoy", "troops", "protest", "border", "cargo", "shipment", "drill",
)

# A named human face to build the video around.
PROTAGONIST = (
    "president", "billionaire", "ceo", "founder", "minister", "tycoon",
    "mogul", "richest", "chief executive", "governor", "general", "leader",
)

DAMPENERS = (
    "football", "soccer", "afcon", "premier league", "celebrity", "singer",
    "actor", "movie", "album", "fashion week", "beauty pageant", "wedding",
)

MONEY = re.compile(r"\$\s?\d[\d,.]*\s?(?:billion|million|trillion|bn)?", re.I)
PERCENT = re.compile(r"(\d[\d,.]*)\s?(?:%|percent)", re.I)
LISTICLE = re.compile(r"^\d{1,2}\s", re.I)

# --- weights --------------------------------------------------------------

W_BIG_MONEY = 25
W_MID_MONEY = 15
W_ANY_MONEY = 6
W_BIG_PERCENT = 16
W_ANY_PERCENT = 8
W_SUPERLATIVE = 18
W_POWER_MOVE = 22
W_SOVEREIGNTY = 18
W_COMMODITY = 14
W_GREAT_POWER = 12
W_CORE_COUNTRY = 10
W_CURRENCY = 12
W_LISTICLE = 12
W_FRESH_6H = 10
W_FRESH_24H = 5
W_WEEK_OLD = -12
W_STALE = -30
W_PRIMARY_SOURCE = 8
W_VIDEO_VISUAL = 16
W_PROTAGONIST = 12
W_DAMPENER = -25

PRIMARY_SOURCE = "Business Insider Africa"
# Every Business Insider Africa section counts as the primary source.
PRIMARY_SOURCES = (PRIMARY_SOURCE, "BI Leaders", "BI Markets",
                   "BI Careers", "BI Politics")


@dataclass(frozen=True)
class Score:
    total: int
    reasons: tuple[str, ...]

    @property
    def band(self) -> str:
        if self.total >= 70:
            return "HOT"
        if self.total >= 45:
            return "warm"
        return "cool"


def _money_points(text: str) -> tuple[int, str | None]:
    figures = MONEY.findall(text)
    if not figures:
        return 0, None

    lowered = " ".join(figures).lower()
    if "billion" in lowered or "trillion" in lowered or "bn" in lowered:
        return W_BIG_MONEY, "big money figure"
    if "million" in lowered:
        return W_MID_MONEY, "money figure"
    return W_ANY_MONEY, "small money figure"


def _percent_points(text: str) -> tuple[int, str | None]:
    values = [float(v.replace(",", "")) for v in PERCENT.findall(text) if v]
    if not values:
        return 0, None
    if max(values) >= 20:
        return W_BIG_PERCENT, "large percentage swing"
    return W_ANY_PERCENT, "percentage figure"


def _matches(text: str, table) -> bool:
    """Word-start matching, so 'us' cannot fire inside 'various'.

    No trailing boundary, so stems like 'nationalis' still catch
    'nationalising' and 'nationalisation'.
    """
    return any(re.search(rf"\b{re.escape(word)}", text) for word in table)


def _keyword_points(text: str, table, weight: int, label: str) -> tuple[int, str | None]:
    if _matches(text, table):
        return weight, label
    return 0, None


def score_headline(headline: Headline) -> Score:
    """Total virality points plus the reasons behind them."""
    text = f"{headline.title} {headline.summary}".lower()
    title = headline.title.lower()

    checks = [
        _money_points(text),
        _percent_points(text),
        _keyword_points(text, SUPERLATIVES, W_SUPERLATIVE, "superlative claim"),
        _keyword_points(text, POWER_MOVES, W_POWER_MOVE, "power move"),
        _keyword_points(text, SOVEREIGNTY, W_SOVEREIGNTY, "sovereignty angle"),
        _keyword_points(text, COMMODITIES, W_COMMODITY, "resource story"),
        _keyword_points(text, GREAT_POWERS, W_GREAT_POWER, "great-power actor"),
        _keyword_points(text, CORE_COUNTRIES, W_CORE_COUNTRY, "core country"),
        _keyword_points(text, CURRENCY, W_CURRENCY, "currency/debt angle"),
        _keyword_points(text, VIDEO_VISUAL, W_VIDEO_VISUAL, "filmable subject"),
        _keyword_points(text, PROTAGONIST, W_PROTAGONIST, "human protagonist"),
        _keyword_points(text, DAMPENERS, W_DAMPENER, "off-niche topic"),
    ]

    total = 0
    reasons: list[str] = []
    for points, label in checks:
        if points and label:
            total += points
            reasons.append(label)

    if LISTICLE.match(title):
        total += W_LISTICLE
        reasons.append("listicle format")

    if headline.source in PRIMARY_SOURCES:
        total += W_PRIMARY_SOURCE
        reasons.append("primary source")

    age_hours = (time() - headline.published) / 3600 if headline.published else 999
    if age_hours <= 6:
        total += W_FRESH_6H
        reasons.append("very fresh")
    elif age_hours <= 24:
        total += W_FRESH_24H
        reasons.append("fresh")
    elif age_hours > 24 * 14:
        total += W_STALE
        reasons.append("stale (2+ weeks)")
    elif age_hours > 24 * 7:
        total += W_WEEK_OLD
        reasons.append("over a week old")

    return Score(total=max(total, 0), reasons=tuple(reasons))


def rank_by_virality(
    headlines: tuple[Headline, ...],
) -> tuple[tuple[Headline, Score], ...]:
    """Highest scoring first; newest breaks ties."""
    scored = [(h, score_headline(h)) for h in headlines]
    scored.sort(key=lambda pair: (-pair[1].total, -pair[0].published))
    return tuple(scored)
