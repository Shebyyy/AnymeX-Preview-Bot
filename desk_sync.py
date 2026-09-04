# ══════════════════════════════════════════════════════════════════════════════
# desk_sync.py  —  Bidirectional Sync with AnymeX Bug & Suggestion Desk
# ══════════════════════════════════════════════════════════════════════════════
# Automatically forwards messages, edits, deletions, and forum tag changes
# from Discord forum threads to the AnymeX Desk web application.
#
# Environment variables (all optional — fallbacks to hardcoded values):
#   DESK_SYNC_URL           — Full URL or domain of Desk:
#                             e.g. "https://anymex-desk.asheby.workers.dev"
#   DESK_SYNC_SECRET        — Optional shared secret matching discord_sync_secret in Desk config
#   DESK_GUILD_ID           — Server (Guild) ID to monitor (defaults to Contributor Guild)
#   DESK_FORUM_CHANNEL_IDS  — Comma-separated Forum Channel IDs to monitor
# ══════════════════════════════════════════════════════════════════════════════

import os
import asyncio
import aiohttp
import discord
from discord import app_commands

# ─────────────────────────────────────────────────────────────────────────────
# Hardcoded Defaults (with Environment Variable Overrides)
# ─────────────────────────────────────────────────────────────────────────────

# Default Contributor Guild ID
DEFAULT_GUILD_ID = 1545003117018357850

# Default Forum Channel IDs: Bugs, Suggestions, Extension Issues
DEFAULT_FORUM_CHANNEL_IDS: set[int] = {
    1545003724961751096,  # Bugs forum channel
    1545003626823417906,  # Suggestions forum channel
    1545003859380805702,  # Extension issues forum channel
}

# Default site URL
DEFAULT_SYNC_URL = "https://anymex-desk.asheby.workers.dev"

# Parse Server (Guild) ID
_RAW_GUILD_ID = os.environ.get("DESK_GUILD_ID", "").strip()
DESK_GUILD_ID: int = int(_RAW_GUILD_ID) if _RAW_GUILD_ID.isdigit() else DEFAULT_GUILD_ID

# Parse Forum Channel IDs
_RAW_FORUM_IDS = os.environ.get("DESK_FORUM_CHANNEL_IDS", "").strip()
if _RAW_FORUM_IDS:
    parsed_ids = {int(x.strip()) for x in _RAW_FORUM_IDS.split(",") if x.strip().isdigit()}
    DESK_FORUM_CHANNEL_IDS: set[int] = parsed_ids if parsed_ids else DEFAULT_FORUM_CHANNEL_IDS
else:
    DESK_FORUM_CHANNEL_IDS: set[int] = DEFAULT_FORUM_CHANNEL_IDS

# Parse Sync Endpoint URL
_RAW_URL = os.environ.get("DESK_SYNC_URL", "").strip().rstrip("/")
if not _RAW_URL:
    _RAW_URL = DEFAULT_SYNC_URL

if not _RAW_URL.endswith("/api/discord/sync"):
    DESK_SYNC_ENDPOINT = f"{_RAW_URL}/api/discord/sync"
else:
    DESK_SYNC_ENDPOINT = _RAW_URL

# Default shared sync secret
DEFAULT_SYNC_SECRET = "anymex_sync_8f4a9b2c6e1d3075e82f419c8a74e5bd"

# Parse Sync Secret (defaults to DEFAULT_SYNC_SECRET)
_RAW_SECRET = os.environ.get("DESK_SYNC_SECRET", "").strip()
DESK_SYNC_SECRET: str = _RAW_SECRET if _RAW_SECRET else DEFAULT_SYNC_SECRET

_bot: discord.Client | None = None


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if DESK_SYNC_SECRET:
        headers["Authorization"] = f"Bearer {DESK_SYNC_SECRET}"
    return headers


async def _send_event(payload: dict) -> bool:
    """Send an event payload to the Desk inbound sync API."""
    if not DESK_SYNC_ENDPOINT:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DESK_SYNC_ENDPOINT,
                json=payload,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True
                elif resp.status == 404:
                    # Thread not registered in Desk — completely normal
                    return False
                else:
                    text = await resp.text()
                    print(f"[desk_sync] API HTTP {resp.status}: {text[:160]}")
                    return False
    except asyncio.TimeoutError:
        print("[desk_sync] API request timed out (10s)")
        return False
    except Exception as err:
        print(f"[desk_sync] Connection error: {err}")
        return False


async def ping_desk_api() -> tuple[bool, str]:
    """Test connectivity to Desk API via GET request."""
    if not DESK_SYNC_ENDPOINT:
        return False, "DESK_SYNC_URL is not configured."

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                DESK_SYNC_ENDPOINT,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        count = data.get("syncedThreads", 0)
                        return True, f"Connected successfully! Synced threads on site: {count}"
                    except Exception:
                        return True, "Connected successfully (HTTP 200 OK)."
                elif resp.status == 401:
                    return False, "HTTP 401 Unauthorized — check DESK_SYNC_SECRET."
                else:
                    text = await resp.text()
                    return False, f"HTTP {resp.status}: {text[:100]}"
    except Exception as e:
        return False, f"Failed to connect: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Setup and Event Handlers
# ─────────────────────────────────────────────────────────────────────────────

def setup(bot: commands.Bot | discord.Client):
    """Register Discord event listeners and slash command for AnymeX Desk sync."""
    global _bot
    _bot = bot

    # ── 1. MESSAGE CREATE (New comment from Discord) ──────────────────────────
    @bot.listen("on_message")
    async def on_message_desk(message: discord.Message):
        # Must be in the configured server (Guild)
        if not message.guild or message.guild.id != DESK_GUILD_ID:
            return

        # Must be a forum thread
        if not isinstance(message.channel, discord.Thread):
            return

        # Must belong to one of the Desk forum channels
        if message.channel.parent_id not in DESK_FORUM_CHANNEL_IDS:
            return

        # Skip bots, webhooks, and our own messages to avoid echo loops
        if message.author.bot or message.webhook_id is not None:
            return

        # Skip thread starter messages (type 21 is thread starter card created by forum)
        if getattr(message.type, "value", None) == 21:
            return

        attachments_payload = []
        for att in message.attachments:
            attachments_payload.append({
                "url": att.url,
                "filename": att.filename,
                "content_type": att.content_type or "application/octet-stream",
            })

        reply_to_id = None
        if message.reference and message.reference.message_id:
            reply_to_id = str(message.reference.message_id)

        author_avatar = message.author.avatar.key if message.author.avatar else None

        payload = {
            "event": "MESSAGE_CREATE",
            "threadId": str(message.channel.id),
            "messageId": str(message.id),
            "content": message.content or "",
            "author": {
                "id": str(message.author.id),
                "username": message.author.display_name or message.author.name,
                "avatar": author_avatar,
                "bot": False,
            },
            "replyToMessageId": reply_to_id,
            "attachments": attachments_payload,
        }

        asyncio.create_task(_send_event(payload))

    # ── 2. MESSAGE UPDATE (Comment edit from Discord) ─────────────────────────
    @bot.listen("on_message_edit")
    async def on_message_edit_desk(before: discord.Message, after: discord.Message):
        # Must be in the configured server (Guild)
        if not after.guild or after.guild.id != DESK_GUILD_ID:
            return

        if not isinstance(after.channel, discord.Thread):
            return

        if after.channel.parent_id not in DESK_FORUM_CHANNEL_IDS:
            return

        if after.author.bot or after.webhook_id is not None:
            return

        # Discord fires on_message_edit when embeds are generated without content change
        if before.content == after.content:
            return

        payload = {
            "event": "MESSAGE_UPDATE",
            "threadId": str(after.channel.id),
            "messageId": str(after.id),
            "content": after.content or "",
        }

        asyncio.create_task(_send_event(payload))

    # ── 3. MESSAGE DELETE (Comment delete from Discord) ───────────────────────
    @bot.listen("on_message_delete")
    async def on_message_delete_desk(message: discord.Message):
        # Must be in the configured server (Guild)
        if not message.guild or message.guild.id != DESK_GUILD_ID:
            return

        if not isinstance(message.channel, discord.Thread):
            return

        if message.channel.parent_id not in DESK_FORUM_CHANNEL_IDS:
            return

        payload = {
            "event": "MESSAGE_DELETE",
            "threadId": str(message.channel.id),
            "messageId": str(message.id),
        }

        asyncio.create_task(_send_event(payload))

    # ── 4. THREAD UPDATE (Tag changes / Status updates from Discord) ───────────
    @bot.listen("on_thread_update")
    async def on_thread_update_desk(before: discord.Thread, after: discord.Thread):
        # Must be in the configured server (Guild)
        if not after.guild or after.guild.id != DESK_GUILD_ID:
            return

        if after.parent_id not in DESK_FORUM_CHANNEL_IDS:
            return

        before_tags = set(before.applied_tags) if hasattr(before, "applied_tags") else set()
        after_tags = set(after.applied_tags) if hasattr(after, "applied_tags") else set()

        # Only trigger if tags or archived/locked status changed
        if (
            before_tags != after_tags
            or before.archived != after.archived
            or before.locked != after.locked
        ):
            tag_names = [t.name for t in after_tags]
            payload = {
                "event": "THREAD_UPDATE",
                "threadId": str(after.id),
                "tagNames": tag_names,
            }
            asyncio.create_task(_send_event(payload))

    # ── 5. Status check slash command ─────────────────────────────────────────
    if hasattr(bot, "tree"):
        @bot.tree.command(name="desk_status", description="Check bidirectional sync status with AnymeX Desk")
        async def desk_status(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            ok, msg = await ping_desk_api()

            embed = discord.Embed(
                title="📡 AnymeX Desk Sync Status",
                color=0x57F287 if ok else 0xED4245,
            )
            embed.add_field(
                name="Endpoint",
                value=f"`{DESK_SYNC_ENDPOINT}`",
                inline=False,
            )
            embed.add_field(
                name="Server ID",
                value=f"`{DESK_GUILD_ID}`",
                inline=True,
            )
            embed.add_field(
                name="Auth Secret",
                value="Configured (hidden)" if DESK_SYNC_SECRET else "*None*",
                inline=True,
            )
            embed.add_field(
                name="Monitored Forum Channels",
                value=", ".join(f"`{i}`" for i in sorted(DESK_FORUM_CHANNEL_IDS)),
                inline=False,
            )
            embed.add_field(name="Connection Test", value=msg, inline=False)
            embed.set_footer(text="AnymeX Desk • Bidirectional Synchronization")

            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── 6. Startup check in background ────────────────────────────────────────
    async def _on_startup_check():
        await bot.wait_until_ready()
        ok, detail = await ping_desk_api()
        if ok:
            print(f"✅ desk_sync: Connected to AnymeX Desk ({detail})")
        else:
            print(f"⚠️ desk_sync: Could not reach AnymeX Desk: {detail}")

    asyncio.create_task(_on_startup_check())
    print(f"✅ desk_sync loaded — monitoring server {DESK_GUILD_ID} (channels: {sorted(DESK_FORUM_CHANNEL_IDS)})")
