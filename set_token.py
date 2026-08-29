"""Validate a BotFather token and save it to token.txt.

Usage:
    python set_token.py                 # prompts for the token
    python set_token.py 12345:AAE...    # or pass it directly
"""

import re
import sys
from pathlib import Path

import httpx

TOKEN_FILE = Path(__file__).with_name("token.txt")
API = "https://api.telegram.org"


def clean(raw: str) -> str:
    """Strip quotes, spaces and any line breaks a paste may have introduced."""
    return re.sub(r"\s+", "", raw.strip().strip("'\""))


def check(token: str) -> dict | None:
    """Ask Telegram who this token belongs to. None if it is rejected."""
    try:
        response = httpx.get(f"{API}/bot{token}/getMe", timeout=20)
    except httpx.HTTPError as exc:
        raise SystemExit(f"Could not reach Telegram: {exc}")

    if response.status_code == 200 and response.json().get("ok"):
        return response.json()["result"]

    return None


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else input("Paste your BotFather token: ")
    token = clean(raw)

    if not token:
        raise SystemExit("No token given.")

    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise SystemExit(
            f"That does not look like a token.\n"
            f"Expected digits, a colon, then letters/numbers - got: {token[:20]}..."
        )

    bot = check(token)
    if bot is None:
        raise SystemExit(
            "Telegram rejected that token (401).\n"
            "Get a fresh one: message @BotFather, send /mybots, pick your bot,\n"
            "then API Token -> Revoke current token."
        )

    TOKEN_FILE.write_text(token, encoding="utf-8")
    print(f"Token valid - saved to {TOKEN_FILE}")
    print(f"Bot: @{bot['username']}  ({bot['first_name']})")
    print("\nNow run:  python simple_bot.py")


if __name__ == "__main__":
    main()
