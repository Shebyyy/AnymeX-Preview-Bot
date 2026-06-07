# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply "Single yet?" when a specific user says "Hi"
# ══════════════════════════════════════════════════════════════════════════════
#
# Uses the same setup(bot) pattern as moderation.py to avoid circular imports.
#
# In bot.py — add these lines inside the `main()` function (after moderation setup):
#
#     import hi_trigger
#     hi_trigger.setup(bot)
#
# ══════════════════════════════════════════════════════════════════════════════

import re
import asyncio
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

# The user who triggers the reply
TARGET_USER_ID = 1331083395614380090

# The message to reply with
REPLY_MESSAGE = "Single yet? <:hmmm:1497190580344586422>"

# Fake profile — will look like this person sent the message (no BOT tag)
WEBHOOK_USERNAME    = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL  = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# Regex — matches "hi" in any case, with or without Discord formatting (* _ ~ `)
HI_PATTERN = re.compile(r"^[\*_~`]*hi[\*_~`]*$", re.IGNORECASE)

# ─────────────────────────────────────────────────────────────────────────────
# Module-level bot reference — populated by setup()
# ─────────────────────────────────────────────────────────────────────────────

_bot = None

# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

async def _handle(message: discord.Message):
    """Check the message and reply via webhook if it matches."""

    # Ignore bots & wrong user
    if message.author.bot:
        return
    if message.author.id != TARGET_USER_ID:
        return

    # Check if message matches "hi" pattern
    if not HI_PATTERN.match(message.content.strip()):
        return

    # Get or create a webhook for this channel
    webhook = await _get_or_create_webhook(message.channel)
    if webhook is None:
        # Fallback: reply normally if webhook creation fails
        await message.reply(REPLY_MESSAGE)
        return

    # Send as fake profile, replying to the message
    async with aiohttp.ClientSession() as session:
        payload = {
            "content": REPLY_MESSAGE,
            "username": WEBHOOK_USERNAME,
            "avatar_url": WEBHOOK_AVATAR_URL,
            "allowed_mentions": {"replied_user": True},
        }

        # Discord webhook reply (thread_id not needed for normal channels)
        url = f"{webhook.url}?wait=true"

        # Use message_reference to make it a reply
        payload["message_reference"] = {"message_id": str(message.id)}

        try:
            wh = discord.Webhook.from_url(webhook.url, session=session)
            await wh.send(
                content=REPLY_MESSAGE,
                username=WEBHOOK_USERNAME,
                avatar_url=WEBHOOK_AVATAR_URL,
                wait=True,
            )
        except Exception:
            # Fallback to normal reply
            await message.reply(REPLY_MESSAGE)


async def _get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook | None:
    """Fetch existing bot webhook in the channel, or create one."""
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.user and wh.user.id == _bot.user.id and wh.name == "HiTrigger":
                return wh
        # Create a new one
        return await channel.create_webhook(name="HiTrigger")
    except (discord.Forbidden, discord.HTTPException):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Event listeners
# ─────────────────────────────────────────────────────────────────────────────

def setup(bot: discord.Client):
    """Call this from bot.py main() to register the hi trigger."""
    global _bot
    _bot = bot

    @bot.listen("on_message")
    async def on_message_hi(message: discord.Message):
        await _handle(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_hi(before: discord.Message, after: discord.Message):
        # Treat edited messages the same as new ones
        await _handle(after)

    print("✅ hi_trigger loaded — watching for 'hi' from user", TARGET_USER_ID)
