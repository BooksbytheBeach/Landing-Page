"""
BBB Community Rules — post and pin
Posts a formatted rules embed to #community-rules and pins it.
Idempotent: if the rules embed is already there, edits in place instead
of posting duplicates.

Run:
    python setup_rules.py
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
log = logging.getLogger("rules")

# ---------- Configuration ----------

RULES_CHANNEL_NAME = "community-rules"

# A unique marker we put in the embed footer so we can identify our own
# rules message when re-running, even if the content changes.
RULES_MARKER = "bbb-community-rules-v1"

# Warm linen / editorial accent — matches the BBB aesthetic from the brand brief.
EMBED_COLOR = 0xC9A876

RULES_TITLE = "Community Rules"

RULES_INTRO = (
    "BBB is a global English reading society for professionals. "
    "These rules keep the space sharp, warm, and worth showing up to."
)

# Each rule is (title, body). Rendered as separate embed fields for clean spacing.
RULES = [
    (
        "1. English only",
        "Every message, every channel. That's the practice. "
        "If something urgent needs Korean, DM Elaina directly.",
    ),
    (
        "2. Contribute, don't just consume",
        "Share what you're reading. Bring questions to discussions. "
        "The community is built by the people who show up.",
    ),
    (
        "3. No outside promotion",
        "Don't pitch your business, your event, your newsletter. "
        "Talk to Elaina if you think there's a real fit.",
    ),
    (
        "4. Disagree well",
        "Push back on ideas, never on people. Critical thinking is the point — "
        "defensiveness isn't.",
    ),
    (
        "5. Respect the room",
        "No harassment, slurs, hate, or bad-faith posting. "
        "One warning, then removal.",
    ),
]

RULES_OUTRO = "Questions about any of this — DM Elaina directly."


def build_embed() -> discord.Embed:
    embed = discord.Embed(
        title=RULES_TITLE,
        description=RULES_INTRO,
        color=EMBED_COLOR,
    )
    for name, value in RULES:
        embed.add_field(name=name, value=value, inline=False)
    embed.add_field(name="\u200b", value=f"_{RULES_OUTRO}_", inline=False)
    embed.set_footer(text=f"Books by the Beach · {RULES_MARKER}")
    return embed


async def post_or_update_rules(guild: discord.Guild) -> None:
    channel = discord.utils.get(guild.text_channels, name=RULES_CHANNEL_NAME)
    if not channel:
        log.error(f"Channel #{RULES_CHANNEL_NAME} not found in {guild.name}")
        return

    embed = build_embed()

    # Look through pinned messages for our marker. If found, edit it.
    # If not found, post a new one and pin it.
    pins = await channel.pins()
    existing = None
    for msg in pins:
        if (
            msg.author.id == guild.me.id
            and msg.embeds
            and msg.embeds[0].footer
            and RULES_MARKER in (msg.embeds[0].footer.text or "")
        ):
            existing = msg
            break

    if existing:
        await existing.edit(embed=embed)
        log.info(f"Updated existing rules message in #{RULES_CHANNEL_NAME}")
    else:
        # Optional: clean up the channel of older bot posts before posting fresh.
        # Skipping for safety — manual cleanup is fine for a one-time setup.
        new_msg = await channel.send(embed=embed)
        try:
            await new_msg.pin(reason="Pin community rules")
            log.info(f"Posted and pinned new rules message in #{RULES_CHANNEL_NAME}")
        except discord.Forbidden:
            log.error(
                "Posted rules but couldn't pin — bot needs Manage Messages permission "
                "in this channel. The message is there, just not pinned."
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

        await post_or_update_rules(guild)
        await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
