"""
BBB Welcome / Server Guide — post and pin
Posts a navigation hub embed in #welcome that orients new members to
the server: where to introduce yourself, where to find each program,
where to track events.

Idempotent: edits existing pinned message instead of duplicating.

Run:
    python setup_welcome.py
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
log = logging.getLogger("welcome")

# ---------- Configuration ----------

WELCOME_CHANNEL_NAME = "welcome"
WELCOME_MARKER = "bbb-welcome-guide-v1"
EMBED_COLOR = 0xC9A876  # warm linen — consistent across rules / intro / welcome

WELCOME_TITLE = "Welcome to Books by the Beach"

WELCOME_DESCRIPTION = (
    "A global English reading society for professionals who want to "
    "think sharper and speak clearer through real conversations about real ideas.\n\n"
    "Here's how the server is laid out so you can find what matters."
)

# Each section maps to a category in the channel sidebar. Channels are
# referenced as #channel-name — Discord auto-links these once the embed posts.
SECTIONS = [
    (
        "🌊 Start Here",
        "**#community-rules** — how we operate. Read this first.\n"
        "**#introduce-yourself** — drop a few lines about yourself so the rest of us can welcome you properly.",
    ),
    (
        "📚 Community",
        "**#book-recommendations** — share what's worth reading. Ask for picks when you need one.\n"
        "**#daily-reading-challenge** — daily prompts to keep the habit alive.\n"
        "**#lounge** (voice) — open voice room. Drop in when others are around.",
    ),
    (
        "🎯 Programs",
        "**#byob-online** — Bring Your Own Book reading nights. Read alongside others, surface ideas, build the habit.\n\n"
        "**#book-workshops** — guided deep-dive sessions on a single book. Smaller group, more structure, more depth. "
        "_Access is limited to Workshop members._",
    ),
    (
        "📅 Events",
        "**#announcements** — official updates from Elaina.\n"
        "**#upcoming-events** — what's on the calendar. Real Talk, BYOB nights, workshops, partnerships.\n"
        "**#after-the-meetup** — debrief and reflections after sessions.",
    ),
    (
        "🌐 One ground rule",
        "Everything here happens in English. That's the practice.",
    ),
]

WELCOME_OUTRO = "Questions about anything — workshops, rules, where to start — don't hesitate to DM Elaina."


def build_embed() -> discord.Embed:
    embed = discord.Embed(
        title=WELCOME_TITLE,
        description=WELCOME_DESCRIPTION,
        color=EMBED_COLOR,
    )
    for name, value in SECTIONS:
        embed.add_field(name=name, value=value, inline=False)
    embed.add_field(name="\u200b", value=f"_{WELCOME_OUTRO}_", inline=False)
    embed.set_footer(text=f"Books by the Beach · {WELCOME_MARKER}")
    return embed


async def post_or_update_welcome(guild: discord.Guild) -> None:
    channel = discord.utils.get(guild.text_channels, name=WELCOME_CHANNEL_NAME)
    if not channel:
        log.error(f"Channel #{WELCOME_CHANNEL_NAME} not found in {guild.name}")
        return

    embed = build_embed()

    pins = await channel.pins()
    existing = None
    for msg in pins:
        if (
            msg.author.id == guild.me.id
            and msg.embeds
            and msg.embeds[0].footer
            and WELCOME_MARKER in (msg.embeds[0].footer.text or "")
        ):
            existing = msg
            break

    if existing:
        await existing.edit(embed=embed)
        log.info(f"Updated existing welcome guide in #{WELCOME_CHANNEL_NAME}")
    else:
        new_msg = await channel.send(embed=embed)
        try:
            await new_msg.pin(reason="Pin welcome guide")
            log.info(f"Posted and pinned new welcome guide in #{WELCOME_CHANNEL_NAME}")
        except discord.Forbidden:
            log.error(
                "Posted welcome but couldn't pin — bot needs Manage Messages "
                "permission in this channel."
            )


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

        await post_or_update_welcome(guild)
        await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
