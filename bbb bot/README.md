# BBB Discord Bot

Phase 1 — skeleton. Proves the bot can connect, respond to slash commands,
and observe events. Run locally on your laptop while developing.

## What this phase does

- Connects to Discord using your bot token
- Responds to `/ping` (shows latency) and `/hello` (greets you)
- Logs every message and every member join to your terminal
- Nothing else yet — moderation, roles, Notion all come in later phases

## Setup (one time, ~5 minutes)

### 1. Install Python dependencies

Open a terminal in this folder and run:

```bash
pip install -r requirements.txt
```

If you get a "permission denied" or "externally-managed environment" error,
use a virtual environment instead:

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Create your `.env` file

Copy `.env.example` to `.env` and fill in two values:

**DISCORD_TOKEN** — from the Discord Developer Portal:
- Go to your application → Bot (left sidebar)
- Click "Reset Token" and copy the new token (you can only see it once)
- Paste into `.env`

**GUILD_ID** — your server's ID, so slash commands appear instantly:
- In Discord, go to Settings → Advanced → enable Developer Mode
- Right-click your server name in the server list → Copy Server ID
- Paste into `.env`

### 3. Verify intents are on in the Developer Portal

Go to your application → Bot page, scroll down to "Privileged Gateway Intents",
and make sure these are toggled ON:

- ✅ Server Members Intent
- ✅ Message Content Intent
- (Presence Intent — optional, fine to leave off)

Save changes. If these are off, the bot will start but events won't fire.

## Run the bot

```bash
python bot.py
```

You should see output like:

```
2026-04-28 ... [INFO] bbb: Slash commands synced to guild 12345...
2026-04-28 ... [INFO] bbb: Logged in as BBB#1234 (id: ...)
2026-04-28 ... [INFO] bbb: Connected to 1 guild(s):
2026-04-28 ... [INFO] bbb:   - Books by the Beach (id: ..., members: 5)
2026-04-28 ... [INFO] bbb: Bot is ready. Try /ping or /hello in your server.
```

The bot's status in your member list will switch from offline to online.

## Test it

In any channel in your server, type `/` — the slash command menu should appear.
You should see `/ping` and `/hello`. Try both.

You should also see your messages appearing in the terminal as you type them
in any channel the bot can read.

## Stop the bot

Press `Ctrl+C` in the terminal. The bot goes offline.

## What's next

Phase 2: deploy to Railway so the bot stays online 24/7.
Phase 3: roles + welcome flow (BYOB Member auto-assign, /elevate to Workshop).
Phase 4: moderation (English-only reminder, anti-raid, mod log).
Phase 5: Notion integration (scheduled posts, events, time zones).

## Troubleshooting

**"Missing DISCORD_TOKEN in .env file"** — `.env` doesn't exist or doesn't
have the token. Make sure the file is named exactly `.env` (no extension).

**Slash commands don't appear** — make sure `GUILD_ID` is set in `.env`.
Without it, commands take up to an hour to propagate. With it, they appear
within seconds. You may also need to fully quit and reopen Discord once.

**"PrivilegedIntentsRequired" error** — the intents in step 3 above aren't
enabled in the Developer Portal. Toggle them on and save.

**Bot stays offline** — token is wrong, or you copied it with extra spaces.
Reset the token in the portal and paste fresh into `.env`.
