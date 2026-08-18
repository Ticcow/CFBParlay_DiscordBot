#!/bin/bash
# Independent backstop on top of degen-bot.service's Restart=always: a
# crash loop can exhaust systemd's StartLimitBurst and leave the unit
# "failed" with no further auto-restart, and Restart= never covers an
# explicit `systemctl stop` (accidental or otherwise). Run periodically via
# degen-bot-watchdog.timer to catch and recover from either case.
set -euo pipefail

SERVICE=degen-bot.service

if systemctl is-active --quiet "$SERVICE"; then
    exit 0
fi

echo "$SERVICE is not active - resetting any start-limit lockout and restarting it"
systemctl reset-failed "$SERVICE" || true
systemctl start "$SERVICE"
