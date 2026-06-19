# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (catches ALL loopholes)
# ══════════════════════════════════════════════════════════════════════════════
#
# Unicode loophole coverage:
#   H lookalikes: ǶĦⱧꞕɦНнΗηℋℌℍⒽⓗＨｈᴴₕ𝐇𝐡𝐻𝑯𝒉𝒽𝓗𝓱𝔥𝕙𝕳𝖍𝖧𝗁𝗛𝗵𝘏𝘩𝙃𝙝𝙷𝚑🄷
#   I lookalikes: ıіΙιίϊΐɪɨᵻȷǀ|ӏᴵℐℑⅈⒾⓗＩｉ𝐈𝐢𝐼𝑰𝒊𝒾𝓘𝓲𝔦𝕀𝕚𝕴𝖎𝖨𝗂𝗜𝗶𝘐𝘪𝙄𝙞𝙸𝚒🄸
#   Also catches: h| h/ hl h1 h! h¡ (visual tricks for "i")
#   Does NOT trigger on: high, hiring, hint, history, hill, etc.
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
# Unicode pre-normalization maps
# ─────────────────────────────────────────────────────────────────────────────
# These are characters that VISUALLY look like H/h or I/i but do NOT
# NFKD-decompose to the base letter. We must replace them before processing.

# Build a single replacement function for all H-lookalikes → "H"
_H_MAP = str.maketrans({
    # H variants that don't NFKD-decompose to H
    "\u01f6": "H",  # Ƕ  LATIN CAPITAL LETTER HWAIR (H WITH HOOK)
    "\u0126": "H",  # Ħ  LATIN CAPITAL LETTER H WITH STROKE
    "\u0127": "h",  # ħ  LATIN SMALL LETTER H WITH STROKE
    "\u2c67": "H",  # Ⱨ  LATIN CAPITAL LETTER H WITH DESCENDER
    "\u2c68": "h",  # ⱨ  LATIN SMALL LETTER H WITH DESCENDER
    "\ua795": "h",  # ꞕ  LATIN SMALL LETTER H WITH PALATAL HOOK
    "\u0266": "h",  # ɦ  LATIN SMALL LETTER H WITH HOOK
    "\ua7ed": "h",  # ꟭  LATIN SMALL LETTER H WITH PALATAL HOOK (alt)
    # Cyrillic letters that look identical to H/h
    "\u041d": "H",  # Н  CYRILLIC CAPITAL LETTER EN
    "\u043d": "h",  # н  CYRILLIC SMALL LETTER EN
    # Greek letters that look like H/h
    "\u0397": "H",  # Η  GREEK CAPITAL LETTER ETA
    "\u03b7": "h",  # η  GREEK SMALL LETTER ETA (looks like n/h)
    # Regional indicator 🇭 → H
    "\U0001f1ed": "H",
    # Small capital H
    "\u029c": "H",  # ʜ  LATIN LETTER SMALL CAPITAL H
    # Mathematical / fancy H variants that NFKC-normalize to H already,
    # but we pre-normalize for safety in case NFKD doesn't catch them
    "\u210b": "H",  # ℋ  SCRIPT CAPITAL H
    "\u210c": "H",  # ℌ  BLACK-LETTER CAPITAL H
    "\u210d": "H",  # ℍ  DOUBLE-STRUCK CAPITAL H
    "\u210e": "h",  # ℎ  PLANCK CONSTANT
    "\u24bd": "H",  # Ⓗ  CIRCLED LATIN CAPITAL LETTER H
    "\u24d7": "h",  # ⓗ  CIRCLED LATIN SMALL LETTER H
    "\uff28": "H",  # Ｈ  FULLWIDTH LATIN CAPITAL LETTER H
    "\uff48": "h",  # ｈ  FULLWIDTH LATIN SMALL LETTER H
    "\u1d34": "H",  # ᴴ  MODIFIER LETTER CAPITAL H
    "\u2095": "h",  # ₕ  LATIN SUBSCRIPT SMALL LETTER H
    "\U0001f137": "H", # 🄷  SQUARED LATIN CAPITAL LETTER H
})

# I-lookalikes → "i"
_I_MAP = str.maketrans({
    # I variants that don't NFKD-decompose to I
    "\u0131": "i",  # ı  LATIN SMALL LETTER DOTLESS I
    "\u0456": "i",  # і  CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0406": "I",  # І  CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0399": "I",  # Ι  GREEK CAPITAL LETTER IOTA
    "\u03b9": "i",  # ι  GREEK SMALL LETTER IOTA
    "\u03af": "i",  # ί  GREEK SMALL LETTER IOTA WITH TONOS
    "\u03ca": "i",  # ϊ  GREEK SMALL LETTER IOTA WITH DIALYTIKA
    "\u0390": "i",  # ΐ  GREEK SMALL LETTER IOTA WITH DIALYTIKA AND TONOS
    "\u026a": "i",  # ɪ  LATIN LETTER SMALL CAPITAL I
    "\u0268": "i",  # ɨ  LATIN SMALL LETTER I WITH STROKE
    "\u1d7b": "i",  # ᵻ  LATIN SMALL CAPITAL LETTER I WITH STROKE
    "\u0237": "i",  # ȷ  LATIN SMALL LETTER DOTLESS J (looks like i)
    # Cyrillic palochka (looks like I/l/i)
    "\u04c0": "I",  # Ӏ  CYRILLIC LETTER PALOCHKA
    # Visual i tricks: pipe, dental click, divides
    "\u01c0": "i",  # ǀ  LATIN LETTER DENTAL CLICK (looks like l/i)
    "\u2223": "i",  # ∣  DIVIDES (looks like l/i)
    "\uff5c": "i",  # ｜ FULLWIDTH VERTICAL LINE
    # Regional indicator 🇮 → i
    "\U0001f1ee": "i",
    # Inverted exclamation (looks like i)
    "\u00a1": "i",  # ¡
    # Mathematical / fancy I variants
    "\u2110": "I",  # ℐ  SCRIPT CAPITAL I
    "\u2111": "I",  # ℑ  BLACK-LETTER CAPITAL I
    "\u2139": "i",  # ℹ  INFORMATION SOURCE
    "\u2148": "i",  # ⅈ  DOUBLE-STRUCK ITALIC SMALL I
    "\u2160": "I",  # Ⅰ  ROMAN NUMERAL ONE
    "\u2170": "i",  # ⅰ  SMALL ROMAN NUMERAL ONE
    "\u24be": "I",  # Ⓘ  CIRCLED LATIN CAPITAL LETTER I
    "\u24d8": "i",  # ⓘ  CIRCLED LATIN SMALL LETTER I
    "\uff29": "I",  # Ｉ  FULLWIDTH LATIN CAPITAL LETTER I
    "\uff49": "i",  # ｉ  FULLWIDTH LATIN SMALL LETTER I
    "\u1d35": "I",  # ᴵ  MODIFIER LETTER CAPITAL I
    "\u1d62": "i",  # ᵢ  LATIN SUBSCRIPT SMALL LETTER I
    "\u2071": "i",  # ⁱ  SUPERSCRIPT LATIN SMALL LETTER I
    "\U0001f138": "I", # 🄸  SQUARED LATIN CAPITAL LETTER I
})

# ─────────────────────────────────────────────────────────────────────────────
# Combined pre-normalization: apply both maps at once
# ─────────────────────────────────────────────────────────────────────────────

def _prenormalize(text: str) -> str:
    """Replace ALL known H/I lookalikes with their base letters."""
    return text.translate(_H_MAP).translate(_I_MAP)

# ─────────────────────────────────────────────────────────────────────────────
# Hi detection patterns
# ─────────────────────────────────────────────────────────────────────────────

# After pre-normalization + NFKD + junk stripping, the i part should match this
_I_PATTERN = re.compile(r"[i]+", re.IGNORECASE)

# All junk chars to strip (markdown, zero-width, separators, diacritics)
_JUNK_PATTERN = re.compile(
    r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0\s.,\-_/\\:;!'\"\(\)\[\]{}\u0300-\u036f]"
)

# Same but spaces become word separators instead of being stripped
_FULL_JUNK = re.compile(
    r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0.,\-_/\\:;!'\"\(\)\[\]{}\u0300-\u036f]"
)

# Emojis and other non-letter clutter at the edges
_EDGE_JUNK = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)

# ─────────────────────────────────────────────────────────────────────────────
# Core normalizer — used by both exact and word-level checks
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_hi(text: str) -> str:
    """
    Full normalization pipeline:
      1. Pre-normalize Unicode lookalikes (Ƕ→H, ı→i, ɪ→i, etc.)
      2. Strip edge junk (emojis at edges)
      3. NFKD decompose (separates base letters from combining marks)
      4. Strip combining diacritics + junk
      5. NFKC recompose
    """
    s = _prenormalize(text.strip())
    s = _EDGE_JUNK.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = _JUNK_PATTERN.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    return s


def _normalize_for_words(text: str) -> str:
    """
    Normalization for word-level scanning (keeps spaces as word separators).
    """
    s = _prenormalize(text.strip())
    s = _EDGE_JUNK.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = _FULL_JUNK.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = unicodedata.normalize("NFKC", s)
    return s

# ─────────────────────────────────────────────────────────────────────────────
# Hi detector — catches "hi" as standalone or within a sentence
# ─────────────────────────────────────────────────────────────────────────────

def _is_hi_exact(text: str) -> bool:
    """Check if the entire message is just 'hi' (with any tricks)."""
    cleaned = _normalize_hi(text)
    if len(cleaned) < 2 or len(cleaned) > 6:
        return False
    if cleaned[0].lower() != 'h':
        return False
    return bool(_I_PATTERN.fullmatch(cleaned[1:]))


def _is_h_word(word: str) -> bool:
    """Check if a single-char word is 'h' (after full normalization)."""
    w = _normalize_hi(word)
    return len(w) == 1 and w.lower() == 'h'


def _is_i_word(word: str) -> bool:
    """Check if a word is just i-like characters (after full normalization)."""
    w = _prenormalize(word)
    w = _EDGE_JUNK.sub("", w)
    w = unicodedata.normalize("NFKC", unicodedata.normalize("NFKD", w))
    w = _JUNK_PATTERN.sub("", w)
    if not w or len(w) > 5:
        return False
    return bool(_I_PATTERN.fullmatch(w))


def _contains_hi(text: str) -> bool:
    """
    Returns True if the message contains 'hi' as a standalone word,
    catching every loophole:
      - Exact match: hi, Hi, HI
      - Discord formatting: *hi*, **hi**, ||hi||, `hi`, >hi
      - Zero-width / invisible chars: h​i, h‌i, h‍i
      - Separators: h i, h.i, h-i, h_i
      - Unicode H lookalikes: Ƕi, Ħi, Ⱨi, ꞕi, ɦi, Нi, Ηi
      - Unicode I lookalikes: hı, hі, hι, hɪ, hɨ, hᵻ, hȷ, hǀ
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
    normalized = _normalize_for_words(text)
    words = normalized.split(" ")

    # Check each word individually
    for word in words:
        word = word.strip()
        if not word:
            continue
        if len(word) >= 2 and len(word) <= 6:
            if word[0].lower() == 'h' and _I_PATTERN.fullmatch(word[1:]):
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
