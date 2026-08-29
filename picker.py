"""Inline-button flow: list headlines -> tap one -> choose a script format.

Tap a number  -> the article is fetched and its figures extracted.
Tap a format  -> a script scaffold in Emmanuel's voice comes back.
"""

from __future__ import annotations

import asyncio
import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from article import Article, ArticleError, fetch_article
from news_sources import Headline
from rescript import extract_facts, rescript

PICK_PREFIX = "pick"
STYLE_PREFIX = "style"
CALLBACK_PREFIX = f"({PICK_PREFIX}|{STYLE_PREFIX})"
BUTTONS_PER_ROW = 5
TELEGRAM_LIMIT = 4000

logger = logging.getLogger("picker")


def build_keyboard(count: int) -> InlineKeyboardMarkup:
    """Numbered buttons, one per listed headline."""
    buttons = [
        InlineKeyboardButton(str(i + 1), callback_data=f"{PICK_PREFIX}:{i}")
        for i in range(count)
    ]
    rows = [
        buttons[i : i + BUTTONS_PER_ROW]
        for i in range(0, len(buttons), BUTTONS_PER_ROW)
    ]
    return InlineKeyboardMarkup(rows)


def _style_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Title / Article / CTA", callback_data=f"{STYLE_PREFIX}:simple"
                )
            ],
            [
                InlineKeyboardButton("Social", callback_data=f"{STYLE_PREFIX}:social"),
                InlineKeyboardButton("Video", callback_data=f"{STYLE_PREFIX}:video"),
            ],
        ]
    )


def remember(context: ContextTypes.DEFAULT_TYPE, headlines: tuple[Headline, ...]) -> None:
    """Stash the listed headlines so a later tap can resolve its index."""
    context.chat_data["listed"] = headlines


async def _send_long(message, text: str) -> None:
    """Telegram caps messages at ~4096 chars; split on paragraph breaks."""
    chunks: list[str] = []
    current = ""

    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > TELEGRAM_LIMIT:
            if current:
                chunks.append(current)
            current = block[:TELEGRAM_LIMIT]
        else:
            current = candidate

    if current:
        chunks.append(current)

    for chunk in chunks:
        await message.reply_text(chunk, disable_web_page_preview=True)


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A numbered button was tapped: fetch that article."""
    query = update.callback_query
    await query.answer()

    listed = context.chat_data.get("listed") or ()
    try:
        index = int(query.data.split(":", 1)[1])
        headline = listed[index]
    except (IndexError, ValueError):
        await query.message.reply_text("That list has expired. Send /news again.")
        return

    await query.message.reply_text(f"Pulling: {headline.title[:80]}…")

    try:
        article = await asyncio.to_thread(fetch_article, headline.link)
    except ArticleError as exc:
        await query.message.reply_text(str(exc))
        return

    context.chat_data["article"] = article
    facts = extract_facts(article)

    figures = ", ".join(
        (list(facts.quantities) + list(facts.money) + list(facts.percents))[:6]
    ) or "none found"

    await query.message.reply_text(
        f"<b>{html.escape(article.title)}</b>\n"
        f"<i>{html.escape(headline.source)} · {article.words} words</i>\n\n"
        f"Figures: {html.escape(figures)}\n"
        f"Focus: {html.escape(facts.countries[0] if facts.countries else 'unclear')}\n\n"
        f"Which format?",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=_style_keyboard(),
    )


async def on_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A format button was tapped: build the script."""
    query = update.callback_query
    await query.answer()

    article: Article | None = context.chat_data.get("article")
    if article is None:
        await query.message.reply_text("No article loaded. Send /news and pick one.")
        return

    style = query.data.split(":", 1)[1]
    script = rescript(article, style)
    await _send_long(query.message, script)
