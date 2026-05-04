"""
BBB Introduce Yourself — post and pin guideline
Posts a formatted intro template to #introduce-yourself and pins it.
Idempotent: edits existing pinned message instead of posting duplicates.

Run:
    python setup_intro.py
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
log = logging.getLogger("intro")

# ---------- Configuration ----------

INTRO_CHANNEL_NAME = "introduce-yourself"
INTRO_MARKER = "bbb-intro-guide-v1"
EMBED_COLOR = 0xC9A876  # warm linen, matches the rules embed

INTRO_TITLE = "Start here — introduce yourself"

INTRO_DESCRIPTION = (
    "We pay attention to new arrivals. Drop a few lines so the rest of us "
    "can welcome you properly and find what we have in common."
)

# Each prompt is (label, hint). Designed to be inviting, not invasive —
# nothing about age, employer, salary, relationship status, or anything
# else someone might not want to broadcast.
PROMPTS = [
    (
        "📍 Where you're joining from",
        "City or country — wherever you call home right now.",
    ),
    (
        "📖 What you're reading",
        "Current book, recent favorite, or what's been on your nightstand.",
    ),
    (
        "✨ What brought you to BBB",
        "What you're hoping to get out of this — sharper thinking, better "
        "presentation, real conversations, a reading habit that sticks.",
    ),
    (
        "🎯 One thing you're working on",
        "Could be a skill, a project, a habit. Doesn't need to be big.",
    ),
    (
        "🎲 A fun fact about you",
        "Something small and human — a hidden talent, a strange hobby, "
        "the most unusual place you've been, a strong opinion about a snack. "
        "Whatever makes you, you.",
    ),
]

INTRO_OUTRO = (
    "Don't overthink it — a few sentences is plenty. The point is to be known, "
    "not to perform."
)


def build_embed() -> discord.Embed:
    embed = discord.Embed(
        title=INTRO_TITLE,
        description=INTRO_DESCRIPTION,
        color=EMBED_COLOR,
    )
    for name, value in PROMPTS:
        embed.add_field(name=name, value=value, inline=False)
    embed.add_field(name="\u200b", value=f"_{INTRO_OUTRO}_", inline=False)
    embed.set_footer(text=f"Books by the Beach · {INTRO_MARKER}")
    return embed


async def post_or_update_intro(guild: discord.Guild) -> None:
    channel = discord.utils.get(guild.text_channels, name=INTRO_CHANNEL_NAME)
    if not channel:
        log.error(f"Channel #{INTRO_CHANNEL_NAME} not found in {guild.name}")
        return

    embed = build_embed()

    pins = await channel.pins()
    existing = None
    for msg in pins:
        if (
            msg.author.id == guild.me.id
            and msg.embeds
            and msg.embeds[0].footer
            and INTRO_MARKER in (msg.embeds[0].footer.text or "")
        ):
            existing = msg
            break

    if existing:
        await existing.edit(embed=embed)
        log.info(f"Updated existing intro guide in #{INTRO_CHANNEL_NAME}")
    else:
        new_msg = await channel.send(embed=embed)
        try:
            await new_msg.pin(reason="Pin intro guide")
            log.info(f"Posted and pinned new intro guide in #{INTRO_CHANNEL_NAME}")
        except discord.Forbidden:
            log.error(
                "Posted intro but couldn't pin — bot needs Manage Messages "
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

        await post_or_update_intro(guild)
        await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
