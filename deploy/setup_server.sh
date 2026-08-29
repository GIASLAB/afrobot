#!/usr/bin/env bash
# One-shot Afrobot install for a fresh Ubuntu VM (Oracle Always Free, or any VPS).
#
#   sudo bash setup_server.sh '<TELEGRAM_TOKEN>'
#
# Installs to /opt/afrobot, runs as an unprivileged user under systemd,
# restarts on crash, starts on boot.
set -euo pipefail

TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "usage: sudo bash setup_server.sh '<TELEGRAM_TOKEN>'" >&2
  exit 1
fi

APP_DIR=/opt/afrobot
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> installing python"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip

echo "==> creating service user"
id -u afrobot >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin afrobot

echo "==> copying app to $APP_DIR"
mkdir -p "$APP_DIR"
cp "$SRC_DIR"/news_bot.py "$SRC_DIR"/news_sources.py "$SRC_DIR"/article.py \
   "$SRC_DIR"/rescript.py "$SRC_DIR"/picker.py "$SRC_DIR"/virality.py \
   "$SRC_DIR"/requirements.txt "$APP_DIR"/

echo "==> installing dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> writing token to /etc/afrobot.env (root-only)"
printf 'TELEGRAM_TOKEN=%s\n' "$TOKEN" > /etc/afrobot.env
chmod 600 /etc/afrobot.env

chown -R afrobot:afrobot "$APP_DIR"

echo "==> installing systemd service"
cp "$SRC_DIR/deploy/afrobot.service" /etc/systemd/system/afrobot.service
systemctl daemon-reload
systemctl enable --now afrobot

sleep 5
systemctl --no-pager --lines=20 status afrobot || true

cat <<'DONE'

Afrobot is installed.

  systemctl status afrobot     # is it alive
  journalctl -u afrobot -f     # live log
  systemctl restart afrobot    # restart

IMPORTANT: stop the Windows copy before using this one.
Two pollers on one token cause telegram.error.Conflict:
  schtasks /end /tn Afrobot
  schtasks /change /tn Afrobot /disable
DONE
