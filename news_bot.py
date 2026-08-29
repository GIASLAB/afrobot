"""@AfrocentricBot - Pan-African news digest with tap-to-pick articles.

Run:  python news_bot.py
Stop: Ctrl+C
"""

import asyncio
import html
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import time

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from news_sources import FEEDS, Headline, fetch_headlines, filter_headlines
from picker import PICK_PREFIX, STYLE_PREFIX, build_keyboard, on_pick, on_style, remember
from virality import Score, rank_by_virality

Ranked = tuple[tuple[Headline, Score], ...]

TOKEN_FILE = Path(__file__).with_name("token.txt")
DEFAULT_COUNT = 10
MAX_COUNT = 15
BRIEF_COUNT = 10
SUMMARY_CHARS = 180
MESSAGE_LIMIT = 3600  # Telegram caps at 4096; leave room for header and footer
REFRESH_SECONDS = 240  # under CACHE_SECONDS (300) so the pool is never stale
SELF_PING_SECONDS = 600  # under the 15 min idle window free hosts spin down at

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("newsbot")


def read_token() -> str:
    """Env var first (cloud), token.txt second (local).

    token.txt is gitignored and never ships; a deployed host sets TELEGRAM_TOKEN.
    """
    env_token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if env_token:
        return env_token

    if not TOKEN_FILE.is_file():
        raise SystemExit(
            f"No TELEGRAM_TOKEN set and no {TOKEN_FILE}. Run: python set_token.py"
        )
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(f"{TOKEN_FILE} is empty. Run: python set_token.py")
    return token


def ago(published: float) -> str:
    """Short relative age, e.g. '3h'. Empty when the feed gave no date."""
    if not published:
        return ""

    minutes = int((time() - published) / 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 60 * 24:
        return f"{minutes // 60}h"
    return f"{minutes // (60 * 24)}d"


def digest_blocks(ranked: Ranked) -> list[str]:
    """One block per story: compact numbered line plus its score."""
    blocks = []

    for index, (headline, score) in enumerate(ranked, start=1):
        title = html.escape(headline.title)
        source = html.escape(headline.source)
        age = ago(headline.published)
        stamp = f" · {age}" if age else ""

        star = " ⭐" if index == 1 else ""

        if headline.link:
            line = f'{index}.{star} <a href="{html.escape(headline.link)}">{title}</a>'
        else:
            line = f"{index}.{star} {title}"

        blocks.append(f"{line}\n    <i>{score.band} {score.total} · {source}{stamp}</i>")

    return blocks


def brief_blocks(ranked: Ranked) -> list[str]:
    """One block per story: headline, the feed's summary, then the score."""
    blocks = []

    for index, (headline, score) in enumerate(ranked, start=1):
        title = html.escape(headline.title)
        source = html.escape(headline.source)
        age = ago(headline.published)
        stamp = f" · {age}" if age else ""
        parts = []

        star = " ⭐" if index == 1 else ""

        if headline.link:
            parts.append(
                f'{index}.{star} <a href="{html.escape(headline.link)}">{title}</a>'
            )
        else:
            parts.append(f"{index}.{star} <b>{title}</b>")

        if headline.summary:
            text = headline.summary[:SUMMARY_CHARS].rstrip()
            if len(headline.summary) > SUMMARY_CHARS:
                text += "…"
            parts.append(html.escape(text))

        parts.append(f"<i>{score.band} {score.total} · {source}{stamp}</i>")
        blocks.append("\n".join(parts))

    return blocks


async def send_list(update: Update, heading: str, blocks: list[str], keyboard) -> None:
    """Send a list across as many messages as Telegram's limit requires.

    The keyboard rides on the final message so the numbers stay tappable.
    """
    footer = (
        "<i>⭐ = most likely to go viral as video. "
        "Tap a number to pull that article.</i>"
    )
    messages: list[str] = []
    current = f"<b>{html.escape(heading)}</b>"

    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) > MESSAGE_LIMIT:
            messages.append(current)
            current = block
        else:
            current = candidate

    messages.append(f"{current}\n\n{footer}")

    for position, text in enumerate(messages, start=1):
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=keyboard if position == len(messages) else None,
        )


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Afrobot here - Pan-African news digest.\n\n"
        "/news - latest headlines\n"
        "/brief - same 10 stories, with summaries\n"
        "/news gold - only stories matching a word\n"
        "/sources - where I pull from\n\n"
        "Tap the number under any list to pull that full article."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/news - top headlines across all sources\n"
        "/news <word> - filter, e.g. /news zambia, /news gold\n"
        "/news <word> 15 - ask for more (max 15)\n"
        "/brief - same 10 stories, with summaries\n"
        "/sources - list the feeds\n\n"
        "Tap a number under any list and I'll pull the full article.\n"
        "You can also just send me a word to search."
    )


async def sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    listed = "\n".join(f"· {name}" for name in FEEDS)
    await update.message.reply_text(f"Pulling from:\n{listed}")


def split_args(args: list[str]) -> tuple[str, int]:
    """Trailing number becomes the count; the rest is the keyword."""
    if args and args[-1].isdigit():
        return " ".join(args[:-1]), min(int(args[-1]), MAX_COUNT)
    return " ".join(args), DEFAULT_COUNT


async def _select(
    update: Update, keyword: str, count: int
) -> tuple[Ranked, str] | None:
    """Fetch, filter, rank by viral potential, and top up a thin result.

    Replies and returns None when there is nothing at all to show.
    """
    headlines = await fetch_headlines()

    if not headlines:
        await update.message.reply_text(
            "Could not reach any news source right now. Try again shortly."
        )
        return None

    if not keyword:
        return rank_by_virality(headlines)[:count], "top stories"

    matches = filter_headlines(headlines, keyword)
    if not matches:
        await update.message.reply_text(
            f'Nothing on "{keyword}" in the last {len(headlines)} headlines.\n'
            f"Try a broader word, or /news for everything."
        )
        return None

    ranked = rank_by_virality(matches)[:count]
    label = f'"{keyword}"'

    # A narrow keyword should still fill the list rather than return two rows.
    if len(ranked) < count:
        already = {headline for headline, _ in ranked}
        extra = tuple(
            pair for pair in rank_by_virality(headlines) if pair[0] not in already
        )
        ranked = ranked + extra[: count - len(ranked)]
        label = f'"{keyword}" + top stories'

    return ranked, label


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyword, count = split_args(context.args or [])
    selected = await _select(update, keyword, count)
    if selected is None:
        return

    ranked, label = selected
    shown = ranked[:count]
    remember(context, tuple(headline for headline, _ in shown))

    await send_list(
        update,
        f"Africa news · {label}",
        digest_blocks(shown),
        build_keyboard(len(shown)),
    )


async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyword, _ = split_args(context.args or [])
    selected = await _select(update, keyword, BRIEF_COUNT)
    if selected is None:
        return

    ranked, label = selected
    shown = ranked[:BRIEF_COUNT]
    remember(context, tuple(headline for headline, _ in shown))

    await send_list(
        update,
        f"Africa brief · {label}",
        brief_blocks(shown),
        build_keyboard(len(shown)),
    )


GREETINGS = (
    "hello", "hi", "hey", "yo", "hiya", "howdy", "sup", "hola",
    "good morning", "good afternoon", "good evening", "morning", "evening",
)


def is_greeting(text: str) -> bool:
    """True when the message is just a greeting, not a search term."""
    cleaned = re.sub(r"[^\w\s]", "", text).strip().casefold()
    if not cleaned:
        return False
    if cleaned in GREETINGS:
        return True

    # "hello there", "hi bot" - a greeting opener on a short message.
    words = cleaned.split()
    return len(words) <= 3 and words[0] in GREETINGS


IDENTITY_QUESTIONS = (
    "who are you", "who r u", "who are u", "whos this", "who is this",
    "what are you", "what r u", "what do you do", "what can you do",
    "introduce yourself", "your name", "who made you", "who created you",
)

IDENTITY_REPLY = (
    "I'm a bot you created to pull articles, rescript and send them to you! 🫡"
)


def is_identity_question(text: str) -> bool:
    """True when the message is asking what the bot is."""
    cleaned = re.sub(r"[^\w\s]", "", text).strip().casefold()
    return any(phrase in cleaned for phrase in IDENTITY_QUESTIONS)


STAR_QUESTIONS = (
    "star", "stars", "asterisk", "what is the", "whats the", "what does the",
)

STAR_REPLY = "It's content that's likely to go viral as video."


def is_star_question(text: str) -> bool:
    """True when asking what the star means - both words must be present."""
    cleaned = re.sub(r"[^\w\s]", "", text).strip().casefold()
    if "star" not in cleaned.split() and "stars" not in cleaned.split():
        return False
    return any(
        word in cleaned for word in ("what", "why", "meaning", "means", "for")
    )


async def search_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet, introduce, or treat the message as a search."""
    text = update.message.text.strip()

    if is_greeting(text):
        await update.message.reply_text("Hello Wallace😊!")
        return

    if is_identity_question(text):
        await update.message.reply_text(IDENTITY_REPLY)
        return

    if is_star_question(text):
        await update.message.reply_text(STAR_REPLY)
        return

    context.args = text.split()
    await news(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Handler failed", exc_info=context.error)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"afrobot alive")

    def log_message(self, *args) -> None:
        """Silence per-request stderr spam from the pinger."""


def start_health_server() -> None:
    """Serve $PORT so free web-service hosts keep us running.

    Render's free tier has no background workers, only web services, and it
    spins a service down after 15 minutes with no inbound traffic. Serving a
    port makes the bot a valid web service and gives an external pinger
    something to hit. No PORT set (local, or a real worker host) = no server.
    """
    port = int(os.environ.get("PORT", "0"))
    if not port:
        return

    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on :%d", port)


async def refresh_loop() -> None:
    """Pull every feed on a timer so the pool is fresh before anyone asks.

    Runs under CACHE_SECONDS, so a /news never waits on the network and never
    serves an expired cache. One bad cycle must not kill the loop.
    """
    while True:
        try:
            headlines = await fetch_headlines(force=True)
            logger.info("Feed refresh: %d headlines", len(headlines))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Feed refresh failed; retrying next cycle")
        await asyncio.sleep(REFRESH_SECONDS)


async def self_ping_loop() -> None:
    """Keep a free web-service instance from being spun down.

    Render stops a free service after 15 minutes with no inbound request, and
    a polling bot generates none - all its traffic is outbound. Requesting our
    own public URL is inbound traffic and resets that timer. RENDER_EXTERNAL_URL
    is set by the platform, so this is a no-op anywhere else.
    """
    url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not url:
        return

    logger.info("Self-ping every %ds -> %s", SELF_PING_SECONDS, url)
    while True:
        await asyncio.sleep(SELF_PING_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
            logger.info("Self-ping %s", response.status_code)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Self-ping failed: %s", error)


async def post_init(app) -> None:
    """Start refreshing in the background. Must not block startup."""
    app.bot_data["refresher"] = asyncio.create_task(refresh_loop())
    app.bot_data["pinger"] = asyncio.create_task(self_ping_loop())


async def post_shutdown(app) -> None:
    for name in ("refresher", "pinger"):
        task = app.bot_data.get(name)
        if task is not None:
            task.cancel()


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(read_token())
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("sources", sources))
    app.add_handler(CallbackQueryHandler(on_pick, pattern=f"^{PICK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(on_style, pattern=f"^{STYLE_PREFIX}:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_text))
    app.add_error_handler(on_error)

    start_health_server()

    logger.info("Afrobot starting. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
