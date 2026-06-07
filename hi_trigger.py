# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply "Single yet?" when a specific user says "Hi"
# ══════════════════════════════════════════════════════════════════════════════

import re
import aiohttp
import discord

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? <:hmmm:1497190580344586422>"
WEBHOOK_USERNAME   = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

HI_PATTERN = re.compile(r"^[\*_~`]*hi[\*_~`]*$", re.IGNORECASE)

_bot = None

async def _handle(message: discord.Message):
    if message.author.bot:
        return
    if message.author.id not in TARGET_USER_IDS:
        return
    if not HI_PATTERN.match(message.content.strip()):
        return

    try:
        webhook = await _get_or_create_webhook(message.channel)
        if webhook:
            # Use raw HTTP to send webhook WITH message reply reference
            async with aiohttp.ClientSession() as session:
                payload = {
                    "content": REPLY_MESSAGE,
                    "username": WEBHOOK_USERNAME,
                    "avatar_url": WEBHOOK_AVATAR_URL,
                    "message_reference": {
                        "message_id": str(message.id),
                        "channel_id": str(message.channel.id),
                        "guild_id": str(message.guild.id),
                    },
                    "allowed_mentions": {
                        "replied_user": True
                    }
                }
                async with session.post(
                    f"{webhook.url}?wait=true",
                    json=payload
                ) as resp:
                    if resp.status not in (200, 204):
                        print(f"[hi_trigger] Webhook HTTP error: {resp.status}")
                        await message.reply(REPLY_MESSAGE, mention_author=False)
        else:
            await message.reply(REPLY_MESSAGE, mention_author=False)
    except Exception as e:
        print(f"[hi_trigger] Error: {e}")
        try:
            await message.reply(REPLY_MESSAGE, mention_author=False)
        except Exception as e2:
            print(f"[hi_trigger] Fallback failed: {e2}")


async def _get_or_create_webhook(channel: discord.TextChannel):
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.user and wh.user.id == _bot.user.id and wh.name == "HiTrigger":
                return wh
        return await channel.create_webhook(name="HiTrigger")
    except Exception as e:
        print(f"[hi_trigger] Webhook error: {e}")
        return None


def setup(bot: discord.Client):
    global _bot
    _bot = bot
    print("✅ hi_trigger loaded — watching for 'hi' from users", TARGET_USER_IDS)
