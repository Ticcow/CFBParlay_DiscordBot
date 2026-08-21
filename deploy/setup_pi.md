# Raspberry Pi setup

Runs comfortably on a Raspberry Pi (a Pi 4 or 5 is plenty - even a Pi 3 or
Zero 2 W should be fine, this bot's footprint is tiny). Any other always-on
Linux box with Python 3.11+ works too; nothing here is Pi-specific except
that a Pi is a cheap, low-power way to keep this running 24/7 for free. It's
also safe to run alongside other things on a Pi that's already doing other
jobs - it gets its own virtualenv, its own systemd units, and its own `.env`,
with no dependency on anything else running there.

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git sqlite3
```

## 2. Get the bot code onto the Pi and set up a virtualenv

```bash
cd ~
git clone https://github.com/Ticcow/CFBParlay_DiscordBot.git degen-bot
cd degen-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Create a Discord bot application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it "Degen Bot" (or whatever you like).
2. In the **Bot** tab, click **Add Bot**. No privileged intents are needed - this bot is entirely slash-command driven, so leave **Message Content Intent**, **Presence Intent**, and **Server Members Intent** all off.
3. Still in the **Bot** tab, click **Reset Token** / **Copy** to get your bot token. Keep this secret - it goes in `.env` as `DISCORD_BOT_TOKEN`.
4. In **OAuth2 > URL Generator**, check the `bot` and `applications.commands` scopes, then under **Bot Permissions** check: `Send Messages`, `Embed Links`, `Read Message History`. `Embed Links` is required separately from `Send Messages` - without it, the panel and board embeds fail to post. If you're setting up the [auto-clean channel feature](../README.md#status-panel) also check `Manage Messages`. For `/flair` (team roles), also check `Manage Roles` - and after inviting the bot, drag its role above where you want team roles to sit in **Server Settings > Roles**, since a bot can only manage roles below its own highest role.
5. Copy the generated URL, open it in a browser, and invite the bot to your server.

## 4. Get free API keys

- **CollegeFootballData**: sign up at [collegefootballdata.com/key](https://collegefootballdata.com/key) for a free API key (1,000 calls/month, no credit card).
- **The Odds API**: sign up at [the-odds-api.com](https://the-odds-api.com/) for a free key (500 credits/month, no credit card).

## 5. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
DISCORD_BOT_TOKEN=<token from step 3>
CFBD_API_KEY=<key from step 4>
ODDS_API_KEY=<key from step 4>
DATABASE_PATH=degen_bot.db
ADMIN_LOG_CHANNEL_ID=<channel ID where the panel and job results/failures should post>
DEV_GUILD_ID=<your server's ID, for instant command sync>
```

To get a channel or server ID: enable Discord's Developer Mode (User Settings >
Advanced), then right-click the server or channel and **Copy ID**.

## 6. Run it manually first

```bash
source .venv/bin/activate
python -m bot.main
```

With `DEV_GUILD_ID` set, slash commands appear in that server within seconds.
Without it, commands sync globally, which can take up to an hour to show up
everywhere the first time. Test `/optin`, `/board`, `/parlay start`, and
`/admin sync-week`. Once you're happy, `Ctrl+C` and move on to running it as
a service.

## 7. Install as a systemd service (auto-start on boot)

`deploy/degen-bot.service` and `deploy/degen-bot-watchdog.service` assume the
bot lives at `/home/pi/degen-bot` and runs as user `pi` - the default on
most Raspberry Pi OS installs. **If your username or install path is
different, edit both files first** (find/replace `pi` and `/home/pi` with
your actual username and path).

```bash
sudo cp deploy/degen-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now degen-bot.service
sudo systemctl status degen-bot.service
journalctl -u degen-bot.service -f
```

## 8. Install the watchdog (recommended)

`Restart=always` handles crashes, but a fast crash loop can exhaust systemd's
`StartLimitBurst` and leave the unit stuck `failed` with no further auto-restart,
and nothing brings the bot back if it's ever stopped by mistake. This installs a
timer that checks every 5 minutes and restarts the bot if it's found stopped,
clearing any start-limit lockout first:

```bash
sudo cp deploy/degen-bot-watchdog.service /etc/systemd/system/
sudo cp deploy/degen-bot-watchdog.timer /etc/systemd/system/
sudo chmod +x deploy/watchdog_degen_bot.sh
sudo systemctl daemon-reload
sudo systemctl enable --now degen-bot-watchdog.timer
```

Confirm it works without waiting for a real outage:

```bash
sudo systemctl stop degen-bot.service
sudo systemctl start degen-bot-watchdog.service
sudo systemctl status degen-bot.service
```

## 9. Check resource headroom

```bash
free -h
df -h /
```

This bot's own footprint is small (well under 100MB installed, well under
100MB RAM), but if the box is already tight on disk from other things running
on it:

```bash
sudo journalctl --vacuum-time=7d
sudo apt clean
```

## 10. Keep it up to date

```bash
cd ~/degen-bot
git pull
sudo systemctl restart degen-bot.service
```

The bot posts what changed to your configured channel automatically the next
time it starts up on a new commit.
