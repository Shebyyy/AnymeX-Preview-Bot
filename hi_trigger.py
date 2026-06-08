# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (catches all loopholes)
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
WEBHOOK_USERNAME       = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL     = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# ─────────────────────────────────────────────────────────────────────────────
# Hi detection patterns
# ─────────────────────────────────────────────────────────────────────────────

# Unicode lookalikes that map to "i" after normalization
_I_LOOKALIKES = re.compile(r"[iıіιᎥίϊΐíìîïīį]+", re.IGNORECASE)

# Pre-normalize: replace i-lookalikes that would get eaten by edge-junk stripping
_I_PRENORMALIZE = re.compile(r"[¡]")

# All junk chars to strip (markdown, zero-width, separators, diacritics)
_JUNK_PATTERN = re.compile(r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0\s.,\-_/\\:;!'\"\(\)\[\]{}\u0300-\u036f]")

# Same but spaces become word separators instead of being stripped
_FULL_JUNK = re.compile(r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0.,\-_/\\:;!'\"\(\)\[\]{}\u0300-\u036f]")

# Emojis and other non-letter clutter at the edges
_EDGE_JUNK = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)

# ─────────────────────────────────────────────────────────────────────────────
# Hi detector — catches "hi" as standalone or within a sentence
# ─────────────────────────────────────────────────────────────────────────────

def _is_hi_exact(text: str) -> bool:
    """Check if the entire message is just 'hi' (with any tricks)."""
    stripped = text.strip()
    stripped = _I_PRENORMALIZE.sub("i", stripped)  # ¡ → i before edge-junk eats it
    stripped = _EDGE_JUNK.sub("", stripped)
    decomposed = unicodedata.normalize("NFKD", stripped)
    cleaned = _JUNK_PATTERN.sub("", decomposed)
    cleaned = unicodedata.normalize("NFKC", cleaned)
    if len(cleaned) < 2 or len(cleaned) > 6:
        return False
    if cleaned[0].lower() != 'h':
        return False
    return bool(_I_LOOKALIKES.fullmatch(cleaned[1:]))


def _is_h_word(word: str) -> bool:
    """Check if a single-char word is 'h'."""
    w = unicodedata.normalize("NFKC", unicodedata.normalize("NFKD", word))
    return len(w) == 1 and w.lower() == 'h'


def _is_i_word(word: str) -> bool:
    """Check if a word is just i-like characters."""
    w = _EDGE_JUNK.sub("", word)
    w = unicodedata.normalize("NFKC", unicodedata.normalize("NFKD", w))
    w = _JUNK_PATTERN.sub("", w)
    if not w or len(w) > 5:
        return False
    return bool(_I_LOOKALIKES.fullmatch(w))


def _contains_hi(text: str) -> bool:
    """
    Returns True if the message contains 'hi' as a standalone word,
    catching every loophole:
      - Exact match: hi, Hi, HI
      - Discord formatting: *hi*, **hi**, ||hi||, `hi`, >hi
      - Zero-width / invisible chars: h​i, h‌i, h‍i
      - Separators: h i, h.i, h-i, h_i
      - Unicode lookalikes: hı, hі, hι
      - Extra i's: hii, hiii (up to 5)
      - Combining diacritics: hï, hî, hí
      - In a sentence: "oh hi", "just wanted to say hi"
      - Tricked in sentence: "oh h.i", "well h.i there"
    Does NOT trigger on: high, hiring, hint, history, hill, etc.
    """
    # Exact match first (most common case, fastest)
    if _is_hi_exact(text):
        return True

    # Normalize text for word-level scanning
    stripped = text.strip()
    stripped = _I_PRENORMALIZE.sub("i", stripped)  # ¡ → i before edge-junk eats it
    stripped = _EDGE_JUNK.sub("", stripped)
    decomposed = unicodedata.normalize("NFKD", stripped)
    normalized = _FULL_JUNK.sub(" ", decomposed)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = unicodedata.normalize("NFKC", normalized)

    words = normalized.split(" ")

    # Check each word individually
    for word in words:
        word = word.strip()
        if not word:
            continue
        if len(word) >= 2 and len(word) <= 6:
            if word[0].lower() == 'h' and _I_LOOKALIKES.fullmatch(word[1:]):
                return True

    # Check adjacent word pairs: 'h' 'i' → hi (catches "h i", "h.i" in sentences)
    for i in range(len(words) - 1):
        if _is_h_word(words[i]) and _is_i_word(words[i + 1]):
            return True

    return False


_bot = None

# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

async def _handle(message: discord.Message):
    if message.author.bot:
        return
    if not _contains_hi(message.content):
        return

    if message.author.id not in TARGET_USER_IDS:
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
