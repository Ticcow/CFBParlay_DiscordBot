# Raspberry Pi setup

Deploying to an existing Pi that already runs BirdNET-Pi and a separate Discord
music bot - this bot gets its own venv, its own systemd units, and its own `.env`,
with no dependency on anything already running.

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git sqlite3
```

(`sqlite3` and `python3` are almost certainly already present from the other bot -
this is just to be safe.)

## 2. Get the bot code onto the Pi and set up a virtualenv

```bash
cd /home/lpsteiner
git clone git@github.com:Ticcow/CFBParlay_DiscordBot.git degen-bot
cd degen-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Create a Discord bot application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it "Degen Bot" (or whatever you like).
2. In the **Bot** tab, click **Add Bot**. No privileged intents are needed - this bot is entirely slash-command driven, so leave **Message Content Intent**, **Presence Intent**, and **Server Members Intent** all off.
3. Still in the **Bot** tab, click **Reset Token** / **Copy** to get your bot token. Keep this secret - it goes in `.env` as `DISCORD_BOT_TOKEN`.
4. In **OAuth2 > URL Generator**, check the `bot` and `applications.commands` scopes, then under **Bot Permissions** check: `Send Messages`, `Embed Links`, `Read Message History`. `Embed Links` is required separately from `Send Messages` - without it, board/leaderboard embeds fail to post.
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
ADMIN_LOG_CHANNEL_ID=<channel ID where job results/failures should post>
DEV_GUILD_ID=<your server's ID, for instant command sync during testing>
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
`/admin sync-week`.

## 7. Install as a systemd service (auto-start on boot)

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
sudo cp deploy/watchdog_degen_bot.sh deploy/degen-bot-watchdog.service /etc/systemd/system/ 2>/dev/null || true
sudo cp deploy/degen-bot-watchdog.service /etc/systemd/system/
sudo cp deploy/degen-bot-watchdog.timer /etc/systemd/system/
sudo chmod +x /home/lpsteiner/degen-bot/deploy/watchdog_degen_bot.sh
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

Disk space on this Pi is tight (BirdNET-Pi's audio/log retention is the usual
culprit, not this bot). If `df -h /` shows less than ~500M free, run:

```bash
sudo journalctl --vacuum-time=7d
sudo apt clean
```

before doing anything else that installs packages.
