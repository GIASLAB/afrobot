"""Turn a fetched article into a script scaffold in Emmanuel's voice.

Deliberately extractive: every figure in the output is lifted from the source
article, never generated. Places where a human thesis is required are marked
so they cannot be mistaken for finished copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from article import Article

# Countries that carry the Pan-African sovereignty thread in the scripts.
AFRICAN_COUNTRIES = (
    "Zimbabwe", "Ghana", "Mali", "Burkina Faso", "Niger", "Nigeria", "Zambia",
    "South Africa", "Egypt", "Kenya", "Tanzania", "Uganda", "Senegal", "Guinea",
    "Ivory Coast", "Côte d'Ivoire", "Ethiopia", "Morocco", "Algeria", "Sudan",
    "DRC", "Congo", "Botswana", "Namibia", "Mozambique", "Angola", "Rwanda",
)

MONEY = re.compile(r"\$\s?\d[\d,.]*\s?(?:billion|million|trillion|bn|m)?", re.I)
PERCENT = re.compile(r"\d[\d,.]*\s?(?:%|percent)", re.I)
QUANTITY = re.compile(
    r"\d[\d,.]*\s?(?:kilograms?|kg|tonnes?|tons?|megawatts?|MW|barrels?|ounces?)", re.I
)
SENTENCE = re.compile(r"(?<=[.!?])\s+")

# Periods that end an abbreviation, not a sentence.
ABBREVIATIONS = (
    "U.S.", "U.K.", "U.N.", "E.U.", "U.A.E.", "D.R.C.",
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Gen.", "Gov.", "Sen.", "Rep.",
    "Inc.", "Ltd.", "Co.", "Corp.", "St.", "No.",
    "vs.", "etc.", "i.e.", "e.g.", "a.m.", "p.m.",
)
INITIAL = re.compile(r"\b([A-Z])\.(\s)")
DOT = "\x00"


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends without tripping over 'U.S.' or initials."""
    masked = text
    for abbreviation in ABBREVIATIONS:
        masked = masked.replace(abbreviation, abbreviation.replace(".", DOT))
    masked = INITIAL.sub(rf"\1{DOT}\2", masked)

    return [part.replace(DOT, ".").strip() for part in SENTENCE.split(masked)]

TAKE = "[YOUR TAKE]"

# Measured from Emmanuel's own 185-second Zimbabwe script (422 narration words).
WORDS_PER_MINUTE = 137
TARGET_SECONDS = 135  # 2:15
TARGET_WORDS = round(TARGET_SECONDS / 60 * WORDS_PER_MINUTE)
TAKE_WORDS = 35  # budget reserved for each [YOUR TAKE] once written


def count_words(text: str) -> int:
    """Spoken words only - bracketed directions are not read aloud."""
    spoken = re.sub(r"\[[^\]]*\]", "", text)
    return len(spoken.split())


def runtime_seconds(words: int) -> int:
    return round(words / WORDS_PER_MINUTE * 60)


def format_runtime(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def fill_to_budget(sentences: tuple[str, ...], budget: int) -> tuple[str, ...]:
    """Take whole sentences until the word budget is spent."""
    picked: list[str] = []
    used = 0

    for sentence in sentences:
        length = len(sentence.split())
        if used + length > budget:
            continue
        picked.append(sentence)
        used += length
        if used >= budget - 6:
            break

    return tuple(picked)


@dataclass(frozen=True)
class Facts:
    money: tuple[str, ...]
    percents: tuple[str, ...]
    quantities: tuple[str, ...]
    countries: tuple[str, ...]
    sentences: tuple[str, ...]

    @property
    def headline_number(self) -> str:
        """The largest figure in the piece, not merely the first one seen."""
        candidates = list(self.quantities) + list(self.money)
        if candidates:
            return max(candidates, key=magnitude)
        if self.percents:
            return max(self.percents, key=magnitude)
        return TAKE

    @property
    def has_strong_number(self) -> bool:
        """True when a figure is big enough to carry a hook on its own."""
        figure = self.headline_number
        if figure == TAKE:
            return False
        if "%" in figure or "percent" in figure.lower():
            return magnitude(figure) >= 10
        if figure.startswith("$"):
            return magnitude(figure) >= 1_000_000
        return magnitude(figure) >= 1_000


MULTIPLIERS = {
    "trillion": 1e12, "billion": 1e9, "bn": 1e9,
    "million": 1e6, "tonne": 1e3, "tonnes": 1e3, "ton": 1e3, "tons": 1e3,
}


def magnitude(figure: str) -> float:
    """Numeric size of a figure string, so '$4.61 billion' beats '$280'."""
    match = re.search(r"\d[\d,.]*", figure)
    if not match:
        return 0.0

    try:
        value = float(match.group().replace(",", ""))
    except ValueError:
        return 0.0

    lowered = figure.lower()
    for word, factor in MULTIPLIERS.items():
        if word in lowered:
            return value * factor
    return value


def rank_countries(text: str) -> tuple[str, ...]:
    """African countries ordered by how central they are to the piece."""
    counted: list[tuple[str, int, int]] = []

    for country in AFRICAN_COUNTRIES:
        # Word boundaries matter: "Niger" must not match inside "Nigeria".
        pattern = re.compile(rf"\b{re.escape(country)}\b", re.I)
        hits = pattern.findall(text)
        if hits:
            counted.append((country, len(hits), pattern.search(text).start()))

    counted.sort(key=lambda row: (-row[1], row[2]))
    return tuple(country for country, _, _ in counted)


def _unique(items) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return tuple(out)


def extract_facts(article: Article) -> Facts:
    """Pull the concrete, quotable material out of an article."""
    text = article.text
    sentences = _unique(
        s for s in split_sentences(text) if len(s) > 60 and s[:1].isupper()
    )

    return Facts(
        money=_unique(MONEY.findall(text)),
        percents=_unique(PERCENT.findall(text)),
        quantities=_unique(QUANTITY.findall(text)),
        countries=rank_countries(text),
        sentences=sentences,
    )


def _numbers_line(facts: Facts) -> str:
    found = list(facts.quantities) + list(facts.money) + list(facts.percents)
    return ", ".join(found[:6]) if found else "no hard figures in this piece"


def _sovereignty_close(facts: Facts) -> str:
    others = [c for c in facts.countries][1:4]
    if others:
        peers = ", ".join(others)
        return (
            f"{facts.countries[0]} joins {peers} in showing that African nations can "
            f"use their own resources to build genuine economic sovereignty.\n\n"
            f"The continent the world called resource-cursed is proving the curse was "
            f"never the resources - it was who controlled them."
        )
    return (
        "The continent the world called resource-cursed is proving the curse was "
        "never the resources - it was who controlled them."
    )


def _opener(country: str, facts: Facts) -> str:
    """Lead on a figure only when the article actually supplies a big one."""
    if facts.has_strong_number:
        return (
            f"{country} just posted {facts.headline_number}. "
            f"And it tells you everything about what's actually being built."
        )
    return (
        f"Something is shifting in {country}. "
        f"[YOUR TAKE - this piece has no headline figure, so open on the "
        f"stakes, not a number.]"
    )


def build_video_script(article: Article, facts: Facts) -> str:
    """Long-form timestamped format."""
    lead = facts.sentences[0] if facts.sentences else article.title
    body = facts.sentences[1:5]
    country = facts.countries[0] if facts.countries else TAKE

    parts = [
        f"SOURCE: {article.title}",
        f"{article.url}",
        f"FIGURES FOUND: {_numbers_line(facts)}",
        "",
        "=" * 60,
        "",
        "HOOK (0-10 seconds)",
        f"[Visual: {country}, {facts.headline_number}, supporting b-roll]",
        "",
        f"{lead}",
        "",
        f"[YOUR TAKE - one line on why this is bigger than it looks.]",
        "",
        "THE NUMBERS (10-45 seconds)",
        "[Visual: production/finance statistics, year-on-year comparison]",
        "",
    ]

    parts.extend(body[:2] or [TAKE])
    parts += [
        "",
        "This isn't a temporary spike. This is sustained momentum.",
        "",
        "WHY IT MATTERS (45-85 seconds)",
        "[Visual: currency, reserves, downstream industry]",
        "",
        "Here's why this matters beyond the headline figure.",
        "",
        f"[YOUR TAKE - connect this to currency, jobs, or industrial capacity.]",
        "",
    ]

    parts.extend(body[2:4] or [])
    parts += [
        "",
        "THE GLOBAL TIMING (85-120 seconds)",
        "[Visual: global prices, central bank demand]",
        "",
        f"[YOUR TAKE - what global condition makes this land now?]",
        "",
        "HISTORICAL CONTEXT (120-155 seconds)",
        "[Visual: archive footage, before/after]",
        "",
        "Let's put this in historical context.",
        "",
        f"[YOUR TAKE - where was {country} 10 or 20 years ago?]",
        "",
        "THE FINAL TRUTH (155-185 seconds)",
        "[Visual: continental map, sovereignty imagery]",
        "",
        _sovereignty_close(facts),
    ]

    return "\n".join(parts)


def build_social_script(article: Article, facts: Facts) -> str:
    """Short BUILD-UP / VALUE / PAYOFF / CTA format."""
    lead = facts.sentences[0] if facts.sentences else article.title
    country = facts.countries[0] if facts.countries else TAKE

    parts = [
        f"SOURCE: {article.title}",
        f"{article.url}",
        f"FIGURES FOUND: {_numbers_line(facts)}",
        "",
        "=" * 60,
        "",
        _opener(country, facts),
        "",
        "[BUILD-UP]",
        "",
        "Let me give you the context nobody's reporting.",
        "",
        f"{lead}",
        "",
        f"[YOUR TAKE - name the trap. What does this dependency actually cost them?]",
        "",
        "[VALUE]",
        "",
    ]

    parts.extend(facts.sentences[1:3] or [TAKE])
    parts += [
        "",
        "And here's what makes this even more significant.",
        "",
        f"[YOUR TAKE - link it to the wider continental shift.]",
        "",
        "[PAYOFF]",
        "",
        _sovereignty_close(facts),
        "",
        "[CTA]",
        "",
        'Comment "GOLD" and I\'ll send you access to my African Mineral Rush '
        "Masterclass - where I break down exactly how Africa's infrastructure "
        "revolution is creating one of the biggest wealth opportunities of our "
        "generation, and how everyday people can position themselves early.",
    ]

    return "\n".join(parts)


CTA = (
    'Comment "GOLD" and I\'ll send you access to my African Mineral Rush '
    "Masterclass - where I break down exactly how Africa's infrastructure "
    "revolution is creating one of the biggest wealth opportunities of our "
    "generation, and how everyday people can position themselves early."
)


def _title(country: str, facts: Facts, article: Article) -> str:
    """A punchy headline; leads on the figure only when there is a big one."""
    if facts.has_strong_number:
        figure = re.sub(
            r"\b(billion|million|trillion)\b",
            lambda m: m.group().capitalize(),
            facts.headline_number,
        )
        return f"{country} Just Posted {figure} - And It Tells You Everything"
    return article.title.split(" - ")[0].strip()


def build_simple_script(article: Article, facts: Facts) -> str:
    """TITLE / ARTICLE / CTA, budgeted to TARGET_SECONDS of narration."""
    country = facts.countries[0] if facts.countries else TAKE
    body: list[str] = []

    if facts.has_strong_number:
        opener = (
            f"{country} just posted {facts.headline_number}. "
            f"Let me give you the context nobody's reporting."
        )
    else:
        opener = "Let me give you the context nobody's reporting."
    body.append(opener)

    close = _sovereignty_close(facts)

    # Everything not drawn from the article is fixed cost; the rest is budget.
    fixed = count_words(opener) + count_words(close) + (TAKE_WORDS * 2)
    budget = max(TARGET_WORDS - fixed, 40)

    body.extend(fill_to_budget(facts.sentences, budget))
    body.append(f"[YOUR TAKE - why this matters beyond the headline figure.]")
    body.append(f"[YOUR TAKE - land the sovereignty point in your own words.]")
    body.append(close)

    narration = "\n\n".join(body)
    spoken = count_words(narration) + (TAKE_WORDS * 2)

    return "\n".join(
        [
            "TITLE",
            _title(country, facts, article),
            "",
            "ARTICLE",
            "",
            narration,
            "",
            "CTA",
            "",
            CTA,
            "",
            "-" * 40,
            f"RUNTIME: ~{format_runtime(runtime_seconds(spoken))} "
            f"({spoken} words at {WORDS_PER_MINUTE} wpm, incl. your two takes)",
            f"TARGET:  {format_runtime(TARGET_SECONDS)}",
            f"Source: {article.url}",
            f"Figures: {_numbers_line(facts)}",
        ]
    )


def rescript(article: Article, style: str = "simple") -> str:
    """Build a script scaffold. style is 'simple', 'social' or 'video'."""
    facts = extract_facts(article)
    if style == "video":
        return build_video_script(article, facts)
    if style == "social":
        return build_social_script(article, facts)
    return build_simple_script(article, facts)
