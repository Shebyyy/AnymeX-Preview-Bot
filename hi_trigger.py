# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply "Single yet?" when a specific user says "Hi"
# ══════════════════════════════════════════════════════════════════════════════

import re
import unicodedata
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? <:hmmm:1497190580344586422>"
WEBHOOK_USERNAME   = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# Unicode lookalikes that map to "i" after normalization
_I_LOOKALIKES = re.compile(r"[iıіιᎥίϊΐί]+", re.IGNORECASE)

# Discord markdown characters + zero-width chars + visual separators + combining diacritics
_JUNK_PATTERN = re.compile(r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0\s.,\-_/\\:;!'\"\(\)\[\]{}\u0300-\u036f]")

# Emojis and other non-letter clutter at the edges
_EDGE_JUNK = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)

# ─────────────────────────────────────────────────────────────────────────────
# Normalizer — strips ALL tricks and checks if the message is essentially "hi"
# ─────────────────────────────────────────────────────────────────────────────

def _is_hi(text: str) -> bool:
    """
    Returns True if the message is 'hi' regardless of:
      - Case: hi, Hi, HI, hI
      - Discord formatting: *hi*, **hi**, _hi_, ||hi||, `hi`, >hi, >>>hi
      - Zero-width / invisible chars: h​i, h‌i, h‍i
      - Separators: h i, h.i, h-i, h_i, h/i
      - Unicode lookalikes: hı, hі (Cyrillic), hι (Greek)
      - Extra i's: hii, hiii, hiiii (up to 5 i's)
      - Combining diacritics: hï, hî, hí
      - Emojis around it: 👋hi, hi 🖤
    """
    # Strip leading/trailing whitespace
    stripped = text.strip()

    # Remove leading/trailing non-word chars (emojis, symbols, punctuation)
    stripped = _EDGE_JUNK.sub("", stripped)

    # Decompose first: ï → i + combining diaeresis, so the diacritic becomes strippable
    decomposed = unicodedata.normalize("NFKD", stripped)

    # Remove ALL junk characters (markdown, spaces, zero-width, separators, diacritics)
    cleaned = _JUNK_PATTERN.sub("", decomposed)

    # Normalize remaining unicode lookalikes (ı→i, і→i, ι→i, etc.)
    cleaned = unicodedata.normalize("NFKC", cleaned)

    # Now check: must start with 'h' followed by 1-5 i-like characters
    if len(cleaned) < 2 or len(cleaned) > 6:
        return False

    if cleaned[0].lower() != 'h':
        return False

    # All remaining chars must be i-like
    return bool(_I_LOOKALIKES.fullmatch(cleaned[1:]))

_bot = None

# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

async def _handle(message: discord.Message):
    if message.author.bot:
        return
    if message.author.id not in TARGET_USER_IDS:
        return
    if not _is_hi(message.content):
        return

    print(f"[hi_trigger] Triggered by {message.author} in #{message.channel}")

    try:
        webhook = await _get_or_create_webhook(message.channel)
        if webhook:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "content": f"<@{message.author.id}> {REPLY_MESSAGE}",
                    "username": WEBHOOK_USERNAME,
                    "avatar_url": WEBHOOK_AVATAR_URL,
                    "allowed_mentions": {"parse": ["users"]},
                }
                async with session.post(
                    webhook.url + "?wait=true",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 204):
                        print(f"[hi_trigger] Sent via webhook with profile + mention ✅")
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
