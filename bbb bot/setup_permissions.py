"""
BBB Server Setup — channel permissions
Configures who can see/send in each channel, based on roles.

Run once, or any time you want to re-sync permissions:
    python setup_permissions.py

Idempotent: safe to run multiple times. Reports what it changed.
Reads DISCORD_TOKEN and GUILD_ID from .env (same file as bot.py).
"""

import asyncio
import os
import logging
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
if not TOKEN or not GUILD_ID:
    raise SystemExit("Missing DISCORD_TOKEN or GUILD_ID in .env")
GUILD_ID = int(GUILD_ID)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("setup")

# ---------- Configuration ----------
# Edit this dict to change who can see what. Keys are channel names
# (must match Discord exactly). Values describe permission overrides.
#
# Three "actor" types you can use:
#   "@everyone"             — the default role (all members)
#   "BYOB members"          — your BYOB role
#   "Book Workshop Members" — your Workshop role
#   "Books by the beach DEMO"
#   "Admin"
#   "Bots"
#
# For each actor, set:
#   view: True / False / None  (None = inherit, no override)
#   send: True / False / None
#
# The "@everyone deny view, role allow view" pattern is the standard way
# to make a channel exclusive to specific roles.

PERMISSIONS = {
    # TOP — visible to everyone in the server
    "announcements": {
        "@everyone":               {"view": True,  "send": False},
        "Bots":                    {"view": True,  "send": True},
    },
    "community-rules": {
        "@everyone":               {"view": True,  "send": False},
        "Bots":                    {"view": True,  "send": True},
    },
    "lounge": {
        # Voice channel — "send" doesn't apply to voice the same way,
        # but view controls whether the channel is visible at all.
        "@everyone":               {"view": False},
        "BYOB members":            {"view": True},
        "Book Workshop Members":   {"view": True},
        "Bots":                    {"view": True},
    },

    # START HERE — visible to everyone, only admin/bot can send in welcome
    "welcome": {
        "@everyone":               {"view": True,  "send": False},
        "BYOB members":            {"view": True,  "send": False},
        "Book Workshop Members":   {"view": True,  "send": False},
        "Books by the beach DEMO": {"view": True,  "send": False},
        "Bots":                    {"view": True,  "send": True},
    },
    "introduce-yourself": {
        "@everyone":               {"view": True,  "send": True},
        "BYOB members":            {"view": True,  "send": True},
        "Book Workshop Members":   {"view": True,  "send": True},
        "Books by the beach DEMO": {"view": True,  "send": True},
        "Bots":                    {"view": True,  "send": True},
    },

    # COMMUNITY — members only, no @everyone
    "book-recommendations": {
        "@everyone":               {"view": False},
        "BYOB members":            {"view": True,  "send": True},
        "Book Workshop Members":   {"view": True,  "send": True},
        "Bots":                    {"view": True,  "send": True},
    },
    "daily-reading-challenge": {
        "@everyone":               {"view": False},
        "BYOB members":            {"view": True,  "send": True},
        "Book Workshop Members":   {"view": True,  "send": True},
        "Bots":                    {"view": True,  "send": True},
    },

    # PROGRAMS
    "byob-online": {
        "@everyone":               {"view": False},
        "BYOB members":            {"view": True,  "send": True},
        "Book Workshop Members":   {"view": True,  "send": True},
        "Bots":                    {"view": True,  "send": True},
    },
    "book-workshops": {
        # The exclusive one — only Workshop members see it (plus the bot).
        "@everyone":               {"view": False},
        "BYOB members":            {"view": False},
        "Book Workshop Members":   {"view": True,  "send": True},
        "Bots":                    {"view": True,  "send": True},
    },

    # EVENTS
    "upcoming-events": {
        "@everyone":               {"view": False},
        "BYOB members":            {"view": True,  "send": False},
        "Book Workshop Members":   {"view": True,  "send": False},
        "Books by the beach DEMO": {"view": True,  "send": False},
        "Bots":                    {"view": True,  "send": True},
    },
    "after-the-meetup": {
        "@everyone":               {"view": False},
        "BYOB members":            {"view": True,  "send": True},
        "Book Workshop Members":   {"view": True,  "send": True},
        "Bots":                    {"view": True,  "send": True},
    },

    # ADMIN — private. Only Admin role + Bots see it. Bot's mod log lives here.
    "admin": {
        "@everyone":               {"view": False},
        "BYOB members":            {"view": False},
        "Book Workshop Members":   {"view": False},
        "Books by the beach DEMO": {"view": False},
        "Bots":                    {"view": True,  "send": True},
    },
}


# ---------- Implementation ----------

def build_overwrite(spec: dict) -> discord.PermissionOverwrite:
    """Convert our simple dict spec into a Discord PermissionOverwrite."""
    overwrite = discord.PermissionOverwrite()
    if "view" in spec:
        overwrite.view_channel = spec["view"]
    if "send" in spec:
        overwrite.send_messages = spec["send"]
    return overwrite


async def apply_permissions(guild: discord.Guild) -> None:
    # Build a name -> role/member lookup, including @everyone
    actors: dict[str, discord.Role] = {"@everyone": guild.default_role}
    for role in guild.roles:
        actors[role.name] = role

    changes_made = 0
    skipped = 0

    for channel_name, perm_spec in PERMISSIONS.items():
        channel = discord.utils.get(guild.channels, name=channel_name)
        if not channel:
            log.warning(f"  Channel '{channel_name}' not found — skipping")
            skipped += 1
            continue

        log.info(f"Configuring #{channel_name}...")

        for actor_name, actor_spec in perm_spec.items():
            actor = actors.get(actor_name)
            if not actor:
                log.warning(f"  Role '{actor_name}' not found — skipping")
                continue

            new_overwrite = build_overwrite(actor_spec)
            current = channel.overwrites_for(actor)

            # Compare — only update if actually different. Saves rate-limit budget.
            if current.pair() == new_overwrite.pair():
                log.info(f"  {actor_name}: already correct")
            else:
                try:
                    await channel.set_permissions(
                        actor,
                        overwrite=new_overwrite,
                        reason="setup_permissions.py",
                    )
                    log.info(f"  {actor_name}: updated ({actor_spec})")
                    changes_made += 1
                except discord.Forbidden:
                    log.error(
                        f"  {actor_name}: PERMISSION DENIED. "
                        f"Bot needs Manage Channels and a role above the target role."
                    )

    log.info(f"\nDone. {changes_made} change(s) applied, {skipped} channel(s) skipped.")


async def main():
    intents = discord.Intents.default()
    intents.members = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info(f"Connected as {client.user}")
        guild = client.get_guild(GUILD_ID)
        if not guild:
            log.error(f"Bot is not in guild {GUILD_ID}")
            await client.close()
            return

        log.info(f"Configuring permissions for: {guild.name}\n")
        await apply_permissions(guild)
        await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
