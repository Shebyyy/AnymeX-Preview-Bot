# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply "Single yet?" when a specific user says "Hi"
# ══════════════════════════════════════════════════════════════════════════════

import re
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? <:hmmm:1497190580344586422>"
WEBHOOK_USERNAME   = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# Matches "hi" with any Discord formatting, any case
HI_PATTERN = re.compile(r"^[\*_~`]*hi[\*_~`]*$", re.IGNORECASE)

_bot = None

# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

async def _handle(message: discord.Message):
    if message.author.bot:
        return
    if message.author.id not in TARGET_USER_IDS:
        return
    if not HI_PATTERN.match(message.content.strip()):
        return

    print(f"[hi_trigger] Triggered by {message.author} in #{message.channel}")

    try:
        webhook = await _get_or_create_webhook(message.channel)
        if webhook:
            async with aiohttp.ClientSession() as session:
                # Step 1: Send webhook with custom profile + mention tag
                payload = {
                    "content": f"<@{message.author.id}> {REPLY_MESSAGE}",
                    "username": WEBHOOK_USERNAME,
                    "avatar_url": WEBHOOK_AVATAR_URL,
                    "allowed_mentions": {"parse": ["users"]},
                    "wait": True,
                }
                async with session.post(
                    webhook.url + "?wait=true",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 204):
                        data = await resp.json()
                        webhook_msg_id = data.get("id")
                        if webhook_msg_id:
                            # Step 2: Try to edit the message to add message_reference (reply)
                            edit_url = f"{webhook.url}/messages/{webhook_msg_id}"
                            edit_payload = {
                                "message_reference": {
                                    "message_id": str(message.id),
                                    "channel_id": str(message.channel.id),
                                }
                            }
                            if message.guild:
                                edit_payload["message_reference"]["guild_id"] = str(message.guild.id)
                            async with session.patch(
                                edit_url,
                                json=edit_payload,
                                headers={"Content-Type": "application/json"},
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as edit_resp:
                                if edit_resp.status in (200, 204):
                                    print(f"[hi_trigger] Replied via webhook + reply edit ✅")
                                else:
                                    body = await edit_resp.text()
                                    print(f"[hi_trigger] Webhook sent with profile + mention (edit reply failed {edit_resp.status}: {body[:100]})")
                        else:
                            print(f"[hi_trigger] Webhook sent with profile + mention ✅")
                    else:
                        body = await resp.text()
                        print(f"[hi_trigger] Webhook HTTP {resp.status}: {body[:200]} — falling back")
                        await message.reply(REPLY_MESSAGE, mention_author=True)
        else:
            await message.reply(REPLY_MESSAGE, mention_author=True)
            print(f"[hi_trigger] Replied via normal reply ✅")
    except Exception as e:
        print(f"[hi_trigger] Error: {e}")
        try:
            await message.reply(REPLY_MESSAGE, mention_author=True)
        except Exception as e2:
            print(f"[hi_trigger] Fallback also failed: {e2}")


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

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

def setup(bot: discord.Client):
    global _bot
    _bot = bot

    @bot.listen("on_message")
    async def on_message_hi(message: discord.Message):
        await _handle(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_hi(before: discord.Message, after: discord.Message):
        await _handle(after)

    print("✅ hi_trigger loaded — watching for 'hi' from users", TARGET_USER_IDS)
