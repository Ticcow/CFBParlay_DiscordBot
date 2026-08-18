# Degen Bot

A free, self-hosted Discord bot for running a weekly fantasy-style college
football parlay competition with friends.
Everyone gets a fresh **$1,000 fake bankroll** each week, builds parlays
entirely by clicking through a Discord embed (no slash-command typing
required), and whoever ends the week with the highest balance wins.
It's for bragging rights, not real money - there's no payment integration,
and none is planned.

Built to run entirely on free tiers: [CollegeFootballData.com](https://collegefootballdata.com)
for schedules/scores/rankings, [The Odds API](https://the-odds-api.com) for
betting lines, and a Raspberry Pi (or any small always-on Linux box) for
hosting.
No credit card required anywhere in the stack.

## Features

- **Click-through parlay building** - `/parlay start` posts an interactive
  panel: pick a game from a Top 25-first list (or browse the full slate),
  pick a bet type with the actual lines shown up front, pick a side, repeat
  for 3-6 legs, then confirm a wager with quick preset buttons or a custom
  amount.
- **A persistent status panel** - one self-updating message showing who's
  opted in, everyone's bets (with live win/loss markers as individual games
  finish), and the weekly standings.
  It reposts itself so it always stays the newest message in the channel,
  and can optionally auto-clean everything else out of that channel too.
- **Real odds, cached and budget-aware** - spreads, moneylines, and totals
  pulled from The Odds API twice a week, well within its free 500-credit
  monthly budget.
- **Automatic grading** - games get graded leg-by-leg as they finish, not
  just once the whole week wraps up.
  Unwagered bankroll gets cleared before the weekly winner is decided, so
  sitting out can't win you the week.
- **Season-long leaderboards** - most weekly wins, and most money won,
  tracked across the whole season.
- **Fully automated weekly cycle** - syncs the schedule, pulls odds, locks
  parlays at kickoff, grades results, and settles the weekly winner on its
  own schedule.
  No manual intervention needed once it's running.
- **Patch notes on deploy** - posts what changed to your configured channel
  automatically whenever you push an update and restart it.

## Quickstart

See [`deploy/setup_pi.md`](deploy/setup_pi.md) for full setup instructions.
In short: clone this repo, get a free Discord bot token plus free CFBD and
Odds API keys, fill in `.env`, and run it (directly, or as a systemd service
for 24/7 uptime).

## Status panel

The persistent panel (configured via `ADMIN_LOG_CHANNEL_ID` in `.env`) is the
bot's main surface - it has Opt In / Start Parlay buttons built in, so people
can participate without typing any slash commands at all.
If you also grant the bot `Manage Messages` in that channel, it will keep
the channel clean by deleting anything else posted there after 5 minutes -
intended for a dedicated channel just for the bot, not one you also chat in.

## Tech stack

Python, [discord.py](https://discordpy.readthedocs.io/), SQLite, and
[APScheduler](https://apscheduler.readthedocs.io/) for the weekly job
schedule.
No ORM, no external database service, no paid infrastructure.

## Disclaimer

Not affiliated with the NCAA, CollegeFootballData.com, or The Odds API.
This is a fake-money game for friends, not a real-money gambling product.

## License

MIT - see [LICENSE](LICENSE).
