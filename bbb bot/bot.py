"""
BBB Discord Bot — Phase 3
The real working bot. Autonomous welcome, patient English detection,
anti-raid, admin overview commands, member tracking via SQLite.

Run locally:
    pip install -r requirements.txt
    python bot.py
"""

import os
import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv
from langdetect import detect, DetectorFactory, LangDetectException

# Make langdetect deterministic — same input always gives same result.
DetectorFactory.seed = 0

# ---------- Setup ----------

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN in .env file.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("bbb")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# ---------- Configuration ----------
# All channel/role names live here. If you rename in Discord, update here.

ADMIN_CHANNEL_NAME = "admin"
INTRO_CHANNEL_NAME = "introduce-yourself"
WELCOME_CHANNEL_NAME = "welcome"

BYOB_ROLE_NAME = "BYOB members"
WORKSHOP_ROLE_NAME = "Book Workshop Members"
ADMIN_ROLE_NAME = "Admin"

# Channels where English-only enforcement applies. Excludes admin and welcome
# (where the bot itself posts long-form English, which would otherwise echo).
ENGLISH_ENFORCED_CHANNELS = {
    "introduce-yourself",
    "book-recommendations",
    "daily-reading-challenge",
    "byob-online",
    "book-workshops",
    "upcoming-events",
    "after-the-meetup",
    "lounge",
}

# English detection tuning — patient, not pedantic.
MIN_LENGTH_FOR_DETECTION = 15      # Skip short messages; detection unreliable below this.
NON_ENGLISH_TRIGGER_COUNT = 3      # How many non-English messages in window before triggering.
NON_ENGLISH_WINDOW_MINUTES = 5     # Time window for the trigger count.
COOLDOWN_HOURS = 1                 # After 3rd trigger in 24h, bot goes silent on that user for this long.

# Anti-raid: if more than this many members join in this window, alert admins.
RAID_THRESHOLD_JOINS = 5
RAID_THRESHOLD_SECONDS = 30

# Quiet member detection.
QUIET_MIN_DAYS_IN_SERVER = 30      # Don't flag fresh joiners.
QUIET_MAX_MESSAGES = 5             # 5 or fewer total messages = quiet.

# ---------- Storage ----------
# SQLite for member message counts, warnings, and last-seen timestamps.
# One file, no setup, survives restarts. Located next to bot.py.

DB_PATH = Path(__file__).parent / "bbb.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS member_stats (
            user_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            joined_at TEXT,
            message_count INTEGER DEFAULT 0,
            last_message_at TEXT
        );
        CREATE TABLE IF NOT EXISTS english_warnings (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            warned_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_warnings_user ON english_warnings(user_id, warned_at);
    """)
    conn.commit()
    conn.close()


def db():
    """Open a fresh connection. SQLite is fast enough that we don't need pooling."""
    return sqlite3.connect(DB_PATH)


# ---------- In-memory state ----------
# Things that don't need to survive restart — just track within a session.

# Per-user rolling deque of recent non-English message timestamps.
non_english_recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
# Users currently in cooldown (bot won't react to them until this time).
cooldowns: dict[int, datetime] = {}
# Recent join timestamps for raid detection.
recent_joins: deque = deque(maxlen=20)


# ---------- Welcome copy ----------
# Placeholder draft in BBB's voice. Elaina will rewrite when ready.

WELCOME_DM = """**Welcome to Books by the Beach.**

You're here to think sharper and speak clearer through reading. That's what we do.

Two things before you settle in:

**1. We run in English** — everywhere, all the time. If something urgent needs Korean, DM me directly.

**2. Introduce yourself in `#introduce-yourself`.** Where you're joining from, what you're reading, what brought you here.

See you in the conversation.

— Elaina"""

PUBLIC_PING = "📖 {mention} just joined BBB. Welcome."


# ---------- Bot class ----------

class BBBBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Slash commands synced to guild {guild_id}")
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally")


bot = BBBBot()


# ---------- Helpers ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime) -> str:
    return dt.isoformat()


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


async def admin_log(guild: discord.Guild, content: str = None, embed: discord.Embed = None):
    """Post to #admin. Used by every autonomous action so admins see what the bot did."""
    channel = discord.utils.get(guild.text_channels, name=ADMIN_CHANNEL_NAME)
    if not channel:
        log.warning(f"#{ADMIN_CHANNEL_NAME} not found — skipping admin log")
        return
    try:
        await channel.send(content=content, embed=embed)
    except discord.Forbidden:
        log.error(f"Bot lacks permission to post in #{ADMIN_CHANNEL_NAME}")


def is_english(text: str) -> bool:
    """
    True if message is probably English or too short/ambiguous to judge.
    False only when we're confident it's another language.
    Errs on the side of letting things through.
    """
    # Strip URLs, mentions, emojis, code — these aren't natural language.
    cleaned = text
    for token in ("http://", "https://"):
        if token in cleaned:
            # Crude but effective: chop messages with URLs at the URL.
            cleaned = cleaned.split(token)[0]
    cleaned = cleaned.strip()

    if len(cleaned) < MIN_LENGTH_FOR_DETECTION:
        return True  # Too short to judge — assume fine.

    try:
        lang = detect(cleaned)
        return lang == "en"
    except LangDetectException:
        return True  # Detection failed — assume fine.


# ---------- Welcome flow ----------

async def run_welcome(member: discord.Member) -> None:
    log.info(f"Welcoming {member} in {member.guild.name}")

    # Track them in the DB
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO member_stats (user_id, guild_id, joined_at, message_count) "
            "VALUES (?, ?, ?, COALESCE((SELECT message_count FROM member_stats WHERE user_id = ?), 0))",
            (member.id, member.guild.id, isoformat(utcnow()), member.id),
        )
        conn.commit()

    # 1. DM
    dm_succeeded = False
    try:
        await member.send(WELCOME_DM)
        dm_succeeded = True
    except discord.Forbidden:
        log.warning(f"  Could not DM {member} (DMs disabled)")
    except Exception as e:
        log.error(f"  Unexpected DM error: {e}")

    # 2. Public ping (or fallback to full welcome if DM failed)
    intro_channel = discord.utils.get(member.guild.text_channels, name=INTRO_CHANNEL_NAME)
    if intro_channel:
        try:
            if dm_succeeded:
                await intro_channel.send(PUBLIC_PING.format(mention=member.mention))
            else:
                await intro_channel.send(f"{member.mention}\n\n{WELCOME_DM}")
        except discord.Forbidden:
            log.error(f"  Cannot post in #{INTRO_CHANNEL_NAME}")

    # 3. Auto-assign BYOB role
    byob_role = discord.utils.get(member.guild.roles, name=BYOB_ROLE_NAME)
    if byob_role:
        try:
            await member.add_roles(byob_role, reason="Auto-assigned on join")
        except discord.Forbidden:
            log.error(f"  Cannot assign {BYOB_ROLE_NAME} — check role hierarchy")

    # 4. Log to admin
    await admin_log(
        member.guild,
        embed=discord.Embed(
            title="Member joined",
            description=f"{member.mention} ({member})\nDM: {'sent' if dm_succeeded else 'failed (DMs off)'}\nRole: BYOB members assigned",
            color=0x77BB77,
            timestamp=utcnow(),
        ),
    )


# ---------- Anti-raid ----------

async def check_raid(member: discord.Member):
    now = utcnow()
    recent_joins.append(now)

    # Count joins in the threshold window
    window_start = now - timedelta(seconds=RAID_THRESHOLD_SECONDS)
    recent_count = sum(1 for ts in recent_joins if ts >= window_start)

    if recent_count >= RAID_THRESHOLD_JOINS:
        await admin_log(
            member.guild,
            content=f"⚠️ **POSSIBLE RAID:** {recent_count} members joined in the last {RAID_THRESHOLD_SECONDS}s.",
        )
        log.warning(f"Raid threshold tripped: {recent_count} joins in {RAID_THRESHOLD_SECONDS}s")


# ---------- English detection (patient) ----------

async def check_english(message: discord.Message):
    if message.channel.name not in ENGLISH_ENFORCED_CHANNELS:
        return
    if message.author.bot:
        return
    # Check cooldown
    cooldown_until = cooldowns.get(message.author.id)
    if cooldown_until and utcnow() < cooldown_until:
        return

    if is_english(message.content):
        return

    # Track this non-English message
    user_recent = non_english_recent[message.author.id]
    user_recent.append(utcnow())

    # How many non-English messages from this user in the window?
    window_start = utcnow() - timedelta(minutes=NON_ENGLISH_WINDOW_MINUTES)
    in_window = sum(1 for ts in user_recent if ts >= window_start)

    if in_window < NON_ENGLISH_TRIGGER_COUNT:
        return  # Patient. Just one or two slips, no reaction.

    # Trigger fired — escalate based on prior warnings in last 24h
    with db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM english_warnings WHERE user_id = ? AND warned_at >= ?",
            (message.author.id, isoformat(utcnow() - timedelta(hours=24))),
        )
        prior_warnings = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO english_warnings (user_id, guild_id, warned_at) VALUES (?, ?, ?)",
            (message.author.id, message.guild.id, isoformat(utcnow())),
        )
        conn.commit()

    # Clear their rolling window so we don't re-trigger immediately on the next message
    user_recent.clear()

    if prior_warnings == 0:
        # First trigger: gentle public reminder
        try:
            await message.channel.send(
                f"Hey {message.author.mention} — looks like the conversation's drifting out of English. "
                f"BBB runs in English so everyone can join in. Pick it back up when you can."
            )
        except discord.Forbidden:
            pass
        await admin_log(
            message.guild,
            embed=discord.Embed(
                title="English reminder issued (1st)",
                description=f"{message.author.mention} in {message.channel.mention}",
                color=0xCCAA66,
                timestamp=utcnow(),
            ),
        )

    elif prior_warnings == 1:
        # Second trigger: firmer reminder
        try:
            await message.channel.send(
                f"{message.author.mention} — second nudge today. English is the practice here. "
                f"If you need to talk in another language, take it to DMs."
            )
        except discord.Forbidden:
            pass
        await admin_log(
            message.guild,
            embed=discord.Embed(
                title="English reminder issued (2nd)",
                description=f"{message.author.mention} in {message.channel.mention}\nFirmer tone used.",
                color=0xCC7744,
                timestamp=utcnow(),
            ),
        )

    else:
        # Third+ trigger: cooldown silently, escalate to admin
        cooldowns[message.author.id] = utcnow() + timedelta(hours=COOLDOWN_HOURS)
        await admin_log(
            message.guild,
            embed=discord.Embed(
                title="⚠️ English reminders ignored",
                description=(
                    f"{message.author.mention} in {message.channel.mention}\n"
                    f"3rd+ trigger in 24h. Bot is silent on this user for {COOLDOWN_HOURS}h. "
                    f"Suggest reviewing manually."
                ),
                color=0xCC4444,
                timestamp=utcnow(),
            ),
        )


# ---------- Events ----------

@bot.event
async def on_ready():
    init_db()
    log.info(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        log.info(f"  - {guild.name} ({guild.member_count} members)")
    log.info("Bot is ready.")


@bot.event
async def on_member_join(member: discord.Member):
    log.info(f"Member joined: {member}")
    await check_raid(member)
    await run_welcome(member)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return
    if not message.guild:
        return  # DM, ignore

    # Track stats
    with db() as conn:
        conn.execute(
            "INSERT INTO member_stats (user_id, guild_id, joined_at, message_count, last_message_at) "
            "VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "  message_count = message_count + 1, last_message_at = excluded.last_message_at",
            (message.author.id, message.guild.id, isoformat(utcnow()), isoformat(utcnow())),
        )
        conn.commit()

    # English check
    await check_english(message)


# ---------- Permission helper for admin commands ----------

def is_admin_check():
    """Decorator factory: only Admin role or guild admins can run."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if admin_role and admin_role in interaction.user.roles:
            return True
        await interaction.response.send_message(
            "This command is for admins only.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


# ---------- Slash commands ----------

@bot.tree.command(name="ping", description="Check the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Pong. Latency: {round(bot.latency * 1000)}ms", ephemeral=True
    )


@bot.tree.command(name="rules", description="Show the community rules.")
async def rules(interaction: discord.Interaction):
    rules_channel = discord.utils.get(interaction.guild.text_channels, name="community-rules")
    if rules_channel:
        await interaction.response.send_message(
            f"Rules are pinned in {rules_channel.mention}.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "Rules channel not found.", ephemeral=True
        )


@bot.tree.command(name="elevate", description="Promote a member to Workshop tier.")
@app_commands.describe(member="The member to elevate.")
@is_admin_check()
async def elevate(interaction: discord.Interaction, member: discord.Member):
    workshop_role = discord.utils.get(interaction.guild.roles, name=WORKSHOP_ROLE_NAME)
    if not workshop_role:
        await interaction.response.send_message(
            f"Role '{WORKSHOP_ROLE_NAME}' doesn't exist.", ephemeral=True
        )
        return
    if workshop_role in member.roles:
        await interaction.response.send_message(
            f"{member.mention} is already in {WORKSHOP_ROLE_NAME}.", ephemeral=True
        )
        return
    try:
        await member.add_roles(workshop_role, reason=f"Elevated by {interaction.user}")
        await interaction.response.send_message(
            f"✓ {member.mention} elevated to **{WORKSHOP_ROLE_NAME}**.", ephemeral=True
        )
        await admin_log(
            interaction.guild,
            embed=discord.Embed(
                title="Member elevated",
                description=f"{member.mention} → {WORKSHOP_ROLE_NAME}\nBy: {interaction.user.mention}",
                color=0x77BB77,
                timestamp=utcnow(),
            ),
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I can't assign that role — check role hierarchy.", ephemeral=True
        )


@bot.tree.command(name="demote", description="Remove Workshop tier from a member.")
@app_commands.describe(member="The member to demote.")
@is_admin_check()
async def demote(interaction: discord.Interaction, member: discord.Member):
    workshop_role = discord.utils.get(interaction.guild.roles, name=WORKSHOP_ROLE_NAME)
    if not workshop_role or workshop_role not in member.roles:
        await interaction.response.send_message(
            f"{member.mention} doesn't have the Workshop role.", ephemeral=True
        )
        return
    try:
        await member.remove_roles(workshop_role, reason=f"Demoted by {interaction.user}")
        await interaction.response.send_message(
            f"✓ {member.mention} removed from {WORKSHOP_ROLE_NAME}.", ephemeral=True
        )
        await admin_log(
            interaction.guild,
            embed=discord.Embed(
                title="Member demoted",
                description=f"{member.mention} removed from {WORKSHOP_ROLE_NAME}\nBy: {interaction.user.mention}",
                color=0xCC7744,
                timestamp=utcnow(),
            ),
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I can't remove that role — check role hierarchy.", ephemeral=True
        )


@bot.tree.command(name="member-info", description="Show details about a member.")
@app_commands.describe(member="The member to inspect.")
@is_admin_check()
async def member_info(interaction: discord.Interaction, member: discord.Member):
    with db() as conn:
        cur = conn.execute(
            "SELECT joined_at, message_count, last_message_at FROM member_stats WHERE user_id = ?",
            (member.id,),
        )
        row = cur.fetchone()
        cur = conn.execute(
            "SELECT COUNT(*) FROM english_warnings WHERE user_id = ?",
            (member.id,),
        )
        warning_count = cur.fetchone()[0]

    joined_iso = row[0] if row else None
    msg_count = row[1] if row else 0
    last_msg_iso = row[2] if row else None

    joined_dt = parse_iso(joined_iso) or member.joined_at
    last_msg_dt = parse_iso(last_msg_iso)

    days_in_server = (utcnow() - joined_dt).days if joined_dt else "?"
    last_msg_str = (
        f"<t:{int(last_msg_dt.timestamp())}:R>" if last_msg_dt else "never"
    )

    roles = [r.name for r in member.roles if r.name != "@everyone"]

    embed = discord.Embed(
        title=f"Member info: {member.display_name}",
        color=0xC9A876,
        timestamp=utcnow(),
    )
    embed.add_field(name="User", value=f"{member.mention}\n`{member}`", inline=False)
    embed.add_field(name="Joined", value=f"{days_in_server} days ago", inline=True)
    embed.add_field(name="Messages", value=str(msg_count), inline=True)
    embed.add_field(name="Last message", value=last_msg_str, inline=True)
    embed.add_field(name="Roles", value=", ".join(roles) or "none", inline=False)
    embed.add_field(name="English warnings (all-time)", value=str(warning_count), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="quiet-members", description="Show members who watch but don't post.")
@is_admin_check()
async def quiet_members(interaction: discord.Interaction):
    """Members who joined >30 days ago and have <=5 messages total."""
    cutoff = isoformat(utcnow() - timedelta(days=QUIET_MIN_DAYS_IN_SERVER))
    with db() as conn:
        cur = conn.execute(
            "SELECT user_id, joined_at, message_count, last_message_at FROM member_stats "
            "WHERE guild_id = ? AND joined_at <= ? AND message_count <= ? "
            "ORDER BY joined_at ASC",
            (interaction.guild.id, cutoff, QUIET_MAX_MESSAGES),
        )
        rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No quiet members. Either everyone's posting or no one's been here long enough yet.",
            ephemeral=True,
        )
        return

    # Build a list, oldest-quiet first
    lines = []
    for user_id, joined_at, msg_count, last_msg_at in rows[:25]:  # cap at 25 for embed length
        member = interaction.guild.get_member(user_id)
        if not member:
            continue  # left the server
        joined_dt = parse_iso(joined_at)
        days = (utcnow() - joined_dt).days if joined_dt else "?"
        last_msg_dt = parse_iso(last_msg_at)
        last_str = f"<t:{int(last_msg_dt.timestamp())}:R>" if last_msg_dt else "never posted"
        lines.append(f"• {member.mention} — {days}d in server, {msg_count} msgs, last: {last_str}")

    embed = discord.Embed(
        title="Quiet members",
        description=(
            f"Members in for {QUIET_MIN_DAYS_IN_SERVER}+ days with ≤{QUIET_MAX_MESSAGES} messages.\n"
            f"Sorted by longest-watching first.\n\n" + "\n".join(lines)
        ),
        color=0xC9A876,
        timestamp=utcnow(),
    )
    if len(rows) > 25:
        embed.set_footer(text=f"Showing 25 of {len(rows)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="server-overview", description="Snapshot of community health.")
@is_admin_check()
async def server_overview(interaction: discord.Interaction):
    guild = interaction.guild
    # Defer because some lookups can be slow on large servers
    await interaction.response.defer(ephemeral=True)

    total = guild.member_count
    bots_count = sum(1 for m in guild.members if m.bot)
    humans = total - bots_count

    byob_role = discord.utils.get(guild.roles, name=BYOB_ROLE_NAME)
    workshop_role = discord.utils.get(guild.roles, name=WORKSHOP_ROLE_NAME)
    demo_role = discord.utils.get(guild.roles, name="Books by the beach DEMO")

    byob_count = len(byob_role.members) if byob_role else 0
    workshop_count = len(workshop_role.members) if workshop_role else 0
    demo_count = len(demo_role.members) if demo_role else 0

    # Recent joins (last 7 days) from DB
    seven_days_ago = isoformat(utcnow() - timedelta(days=7))
    with db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM member_stats WHERE guild_id = ? AND joined_at >= ?",
            (guild.id, seven_days_ago),
        )
        recent_joins_count = cur.fetchone()[0]

        cur = conn.execute(
            "SELECT COUNT(*) FROM english_warnings WHERE guild_id = ? AND warned_at >= ?",
            (guild.id, seven_days_ago),
        )
        recent_warnings = cur.fetchone()[0]

        # Quiet members
        thirty_days_ago = isoformat(utcnow() - timedelta(days=QUIET_MIN_DAYS_IN_SERVER))
        cur = conn.execute(
            "SELECT COUNT(*) FROM member_stats "
            "WHERE guild_id = ? AND joined_at <= ? AND message_count <= ?",
            (guild.id, thirty_days_ago, QUIET_MAX_MESSAGES),
        )
        quiet_count = cur.fetchone()[0]

        # Total messages tracked
        cur = conn.execute(
            "SELECT SUM(message_count) FROM member_stats WHERE guild_id = ?",
            (guild.id,),
        )
        total_msgs = cur.fetchone()[0] or 0

    embed = discord.Embed(
        title="📊 BBB Server Overview",
        color=0xC9A876,
        timestamp=utcnow(),
    )
    embed.add_field(name="Members", value=f"**{humans}** humans · {bots_count} bots", inline=False)
    embed.add_field(name="BYOB", value=str(byob_count), inline=True)
    embed.add_field(name="Workshop", value=str(workshop_count), inline=True)
    embed.add_field(name="DEMO", value=str(demo_count), inline=True)
    embed.add_field(name="Joined (7d)", value=str(recent_joins_count), inline=True)
    embed.add_field(name="Quiet members", value=str(quiet_count), inline=True)
    embed.add_field(name="English nudges (7d)", value=str(recent_warnings), inline=True)
    embed.add_field(name="Total messages tracked", value=str(total_msgs), inline=False)
    embed.set_footer(text="Use /quiet-members for details · /recent-activity for the timeline")

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="recent-activity", description="Last 7 days of joins and mod actions.")
@is_admin_check()
async def recent_activity(interaction: discord.Interaction):
    seven_days_ago_iso = isoformat(utcnow() - timedelta(days=7))
    with db() as conn:
        cur = conn.execute(
            "SELECT user_id, joined_at FROM member_stats "
            "WHERE guild_id = ? AND joined_at >= ? ORDER BY joined_at DESC LIMIT 20",
            (interaction.guild.id, seven_days_ago_iso),
        )
        joins = cur.fetchall()
        cur = conn.execute(
            "SELECT user_id, warned_at FROM english_warnings "
            "WHERE guild_id = ? AND warned_at >= ? ORDER BY warned_at DESC LIMIT 20",
            (interaction.guild.id, seven_days_ago_iso),
        )
        warnings = cur.fetchall()

    embed = discord.Embed(
        title="Recent activity (last 7 days)",
        color=0xC9A876,
        timestamp=utcnow(),
    )
    if joins:
        join_lines = []
        for uid, joined_at in joins[:10]:
            m = interaction.guild.get_member(uid)
            mention = m.mention if m else f"`{uid}` (left)"
            dt = parse_iso(joined_at)
            ts = f"<t:{int(dt.timestamp())}:R>" if dt else "?"
            join_lines.append(f"• {mention} {ts}")
        embed.add_field(name=f"Joins ({len(joins)})", value="\n".join(join_lines), inline=False)
    else:
        embed.add_field(name="Joins", value="none", inline=False)

    if warnings:
        warn_lines = []
        for uid, warned_at in warnings[:10]:
            m = interaction.guild.get_member(uid)
            mention = m.mention if m else f"`{uid}` (left)"
            dt = parse_iso(warned_at)
            ts = f"<t:{int(dt.timestamp())}:R>" if dt else "?"
            warn_lines.append(f"• {mention} {ts}")
        embed.add_field(name=f"English nudges ({len(warnings)})", value="\n".join(warn_lines), inline=False)
    else:
        embed.add_field(name="English nudges", value="none", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="server-check", description="Audit server config for problems.")
@is_admin_check()
async def server_check(interaction: discord.Interaction):
    guild = interaction.guild
    issues = []
    ok = []

    # Check expected channels exist
    expected_channels = [
        "welcome", "introduce-yourself", "community-rules", "announcements",
        "book-recommendations", "daily-reading-challenge",
        "byob-online", "book-workshops",
        "upcoming-events", "after-the-meetup",
        "lounge", ADMIN_CHANNEL_NAME,
    ]
    for ch_name in expected_channels:
        if discord.utils.get(guild.channels, name=ch_name):
            ok.append(f"#{ch_name}")
        else:
            issues.append(f"❌ Missing channel: `{ch_name}`")

    # Check expected roles exist
    expected_roles = [BYOB_ROLE_NAME, WORKSHOP_ROLE_NAME, ADMIN_ROLE_NAME]
    for role_name in expected_roles:
        if discord.utils.get(guild.roles, name=role_name):
            ok.append(f"@{role_name}")
        else:
            issues.append(f"❌ Missing role: `{role_name}`")

    # Check bot's role hierarchy
    bot_top_role = guild.me.top_role
    byob_role = discord.utils.get(guild.roles, name=BYOB_ROLE_NAME)
    workshop_role = discord.utils.get(guild.roles, name=WORKSHOP_ROLE_NAME)
    if byob_role and bot_top_role <= byob_role:
        issues.append(f"⚠️ Bot's role is not above `{BYOB_ROLE_NAME}` — can't assign it.")
    if workshop_role and bot_top_role <= workshop_role:
        issues.append(f"⚠️ Bot's role is not above `{WORKSHOP_ROLE_NAME}` — can't assign it.")

    # Check bot can post in admin channel
    admin_ch = discord.utils.get(guild.text_channels, name=ADMIN_CHANNEL_NAME)
    if admin_ch:
        perms = admin_ch.permissions_for(guild.me)
        if not perms.send_messages:
            issues.append(f"⚠️ Bot can't send in #{ADMIN_CHANNEL_NAME}")

    embed = discord.Embed(
        title="Server config audit",
        color=0xCC4444 if issues else 0x77BB77,
        timestamp=utcnow(),
    )
    if issues:
        embed.add_field(name=f"Issues ({len(issues)})", value="\n".join(issues), inline=False)
    else:
        embed.add_field(name="Status", value="✓ Everything looks right.", inline=False)
    embed.add_field(name=f"Verified ({len(ok)})", value=", ".join(ok) or "none", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="test-welcome", description="Run welcome flow on yourself for testing.")
@is_admin_check()
async def test_welcome(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Running welcome flow. Check DMs and #introduce-yourself.", ephemeral=True
    )
    await run_welcome(interaction.user)


# ---------- Run ----------

if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
