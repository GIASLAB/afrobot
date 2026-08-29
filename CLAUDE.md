# Afrobot — @AfrocentricBot

Telegram bot for Emmanuel (Wallace). Pulls Pan-African business news, ranks it
by how likely it is to go viral **as video**, and turns a chosen article into a
script scaffold in his voice.

## Run it

```
python news_bot.py          # or double-click run.cmd
```

Only ONE instance can run at a time — Telegram allows a single poller per token.
A second instance causes `telegram.error.Conflict`. Same error if anything else
calls `getUpdates` on this token while the bot is live. This matters most when
the cloud copy is live: running it locally at the same time breaks both.

## Always-on (local)

A Scheduled Task named `Afrobot` starts the bot at logon, hidden, and restarts
it if it dies:

`afrobot_hidden.vbs` (hides the window) -> `afrobot_service.cmd` (restart loop,
15s backoff, rotates `afrobot.log` past 5 MB) -> `python news_bot.py`.

```
schtasks /query /tn Afrobot           # is it registered
schtasks /run   /tn Afrobot           # start now
schtasks /end   /tn Afrobot           # stop the task
tail afrobot.log                      # what it is doing
```

**The local setup dies with the machine.** This laptop uses Modern Standby and
sleeps aggressively — during standby the process is suspended, so nothing
answers until it wakes. Telegram holds updates for 24h, so messages are late,
never lost. The only real fix is the cloud deploy below.

## Deploy (cloud)

Needs an always-on container host — **not** serverless. `picker.remember`
stashes the listed headlines in `context.chat_data`, which is in-process
memory, so a stateless function would lose the tap-to-pick flow between taps.

- Token comes from `TELEGRAM_TOKEN`; `token.txt` is the local fallback only
- `Dockerfile` for any container host, `Procfile` for nixpacks hosts
- It is a **worker**, not a web service. No port, no health check endpoint
- Set `TELEGRAM_TOKEN` as a secret in the host dashboard. Never commit it

### Free VM route (Oracle Always Free / any Ubuntu VPS)

```
sudo bash deploy/setup_server.sh '<token>'
```

Installs to `/opt/afrobot`, runs as the unprivileged `afrobot` user under
systemd with `Restart=always`, token in root-only `/etc/afrobot.env`.

```
systemctl status afrobot
journalctl -u afrobot -f
```

Only free-forever host left in 2026: Oracle Always Free (2 ARM OCPU / 12 GB,
halved from 4/24 in June 2026). Koyeb, Fly and Railway all dropped their free
compute tiers. Render and HF Spaces sleep on inactivity, which is the exact
problem the move is meant to solve.

**Stop the Windows task before the cloud copy goes live** — two pollers on one
token is a guaranteed `Conflict`:
`schtasks /end /tn Afrobot && schtasks /change /tn Afrobot /disable`

## Flow

`/news` → 10 headlines ranked by viral score, ⭐ on #1 → tap a number → article
is fetched and parsed → tap a format → script scaffold comes back.

## Files

| File | Does |
|---|---|
| `news_bot.py` | Handlers, commands, list formatting, message splitting |
| `news_sources.py` | RSS feeds, fetch/merge/dedupe/cache, `Headline` |
| `virality.py` | Viral scoring + ranking. All weights are constants at the top |
| `article.py` | Fetches one article URL, extracts headline + body text |
| `rescript.py` | Builds the three script formats, runtime budgeting |
| `picker.py` | Inline buttons: number picker + format picker |
| `set_token.py` | Validates a BotFather token, writes `token.txt` |
| `token.txt` | The live token. Gitignored. Never commit or paste it |
| `bot.py`, `simple_bot.py` | Early throwaway starters. Not used; `bot.py` holds a dead token |
| `afrobot_service.cmd` | Restart loop + log rotation for the Scheduled Task |
| `afrobot_hidden.vbs` | Launches the loop with no console window |
| `Dockerfile`, `Procfile` | Cloud deploy |

## Common tuning knobs

- Feeds: `FEEDS` in `news_sources.py`
- Viral weights: `W_*` constants in `virality.py`; signal word lists above them
- Script length: `TARGET_SECONDS` in `rescript.py` (currently 135 = 2:15).
  `WORDS_PER_MINUTE = 137` was **measured** from Emmanuel's own 185-second
  Zimbabwe script (422 narration words) — don't replace it with a guess
- Article counts: `DEFAULT_COUNT`, `MAX_COUNT`, `BRIEF_COUNT` in `news_bot.py`
- Background refresh: `REFRESH_SECONDS` in `news_bot.py` (240). Keep it under
  `CACHE_SECONDS` (300) in `news_sources.py` or the pool goes stale between pulls
- CTA text and voice phrases: `rescript.py`

## Rules learned the hard way

1. **Never call `getUpdates` to test whether the bot is alive.** It steals the
   polling connection and throws `Conflict` in the bot's log. Check liveness by
   reading the log and the process list. `getMe` and `setMyCommands` are safe.
2. **Word-boundary match every keyword table.** `"Niger"` matched inside
   `"Nigeria"`; `"us"` matched inside `"various"`. Both shipped wrong output.
   Use `\b` prefixes (no trailing boundary, so stems like `nationalis` still work).
3. **The rescripter must never invent a figure.** Every number in a script is
   lifted from the source article. Emmanuel publishes hard economic stats;
   a hallucinated number is a credibility risk. `[YOUR TAKE - ...]` marks where
   a human argument is required — those are directions, not narration, and
   `count_words` excludes anything in brackets.
4. **Telegram caps messages at 4096 chars.** Lists split via `send_list`, with
   the keyboard on the final message. Scripts split via `_send_long`.
5. Restarts can take a few minutes while Telegram releases the old poller.
6. `requirements.txt` must list `feedparser` and `beautifulsoup4` explicitly.
   They are not pulled in by `python-telegram-bot`; only `httpx` is. A clean
   deploy without them dies on `import feedparser`.
7. `refresh_loop` swallows every non-cancel exception on purpose. One dead
   cycle must never end the loop and silently stop refreshing.

## Voice reference

Two formats. Long-form timestamped (`HOOK 0-10s` … `THE FINAL TRUTH`, with
`[Visual: ...]` directions) and short social (`[BUILD-UP] [VALUE] [PAYOFF] [CTA]`).
Markers: hard specific numbers; a long sentence then a short hammer
("Sixty percent."); anaphora ("You cannot industrialize. You cannot manufacture.");
pivots — "Let me give you the context nobody's reporting", "Here's why this
matters beyond…", "Let's put this in historical context"; and a closing
sovereignty reframe linking the story to Ghana / Mali / Burkina Faso / Zimbabwe.
