# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (catches ALL loopholes)
# ══════════════════════════════════════════════════════════════════════════════
#
# Unicode loophole coverage:
#   H lookalikes: ǶĦⱧꞕɦНнΗηℋℌℍⒽⓗＨｈᴴₕ𝐇𝐡𝐻𝑯𝒉𝒽𝓗𝓱𝔥𝕙𝕳𝖍𝖧𝗁𝗛𝗵𝘏𝘩𝙃𝙝𝙷𝚑🄷
#   I lookalikes: ıіΙιίϊΐɪɨᵻȷǀ|ӏᴵℐℑⅈⒾⓗＩｉ𝐈𝐢𝐼𝑰𝒊𝒾𝓘𝓲𝔦𝕀𝕚𝕴𝖎𝖨𝗂𝗜𝗶𝘐𝘪𝙄𝙞𝙸𝚒🄸
#   Also catches: h| h/ hl h1 h! h¡ h; h: (visual tricks for "i")
#   h! → Hi (exclamation mark = vertical line + dot, looks like i)
#   h1 → Hi (digit one = vertical line, looks like i)
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
REPLY_MESSAGE      = "Single yet? 🤔"
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
    "\u2c75": "H",  # Ⱶ  LATIN CAPITAL LETTER HALF H
    "\u2c76": "h",  # ⱶ  LATIN SMALL LETTER HALF H
    "\ua7aa": "H",  # Ɦ  LATIN CAPITAL LETTER H WITH HOOK
    # Cyrillic letters that look identical to H/h
    "\u041d": "H",  # Н  CYRILLIC CAPITAL LETTER EN
    "\u043d": "h",  # н  CYRILLIC SMALL LETTER EN
    "\u04a2": "H",  # Ң  CYRILLIC CAPITAL LETTER EN WITH DESCENDER
    "\u04a3": "h",  # ң  CYRILLIC SMALL LETTER EN WITH DESCENDER
    "\u04c9": "H",  # Ӊ  CYRILLIC CAPITAL LETTER EN WITH TAIL
    "\u04ca": "h",  # ӊ  CYRILLIC SMALL LETTER EN WITH TAIL
    "\u0528": "H",  # Ԩ  CYRILLIC CAPITAL LETTER EN WITH LEFT HOOK
    "\u0529": "h",  # ԩ  CYRILLIC SMALL LETTER EN WITH LEFT HOOK
    # Cyrillic Che variants (look like h with tail/hook)
    "\u04b6": "H",  # Ҷ  CYRILLIC CAPITAL LETTER CHE WITH DESCENDER
    "\u04b7": "h",  # ҷ  CYRILLIC SMALL LETTER CHE WITH DESCENDER
    "\u04b8": "H",  # Ҹ  CYRILLIC CAPITAL LETTER CHE WITH VERTICAL STROKE
    "\u04b9": "h",  # ҹ  CYRILLIC SMALL LETTER CHE WITH VERTICAL STROKE
    "\u04cb": "H",  # Ӌ  CYRILLIC CAPITAL LETTER KHAKASSIAN CHE
    "\u04cc": "h",  # ӌ  CYRILLIC SMALL LETTER KHAKASSIAN CHE
    # Deseret H (obscure script, looks like H/h)
    "\U00010410": "H",  # 𐐐  DESERET CAPITAL LETTER H
    "\U00010438": "h",  # 𐐸  DESERET SMALL LETTER H
    # Greek letters that look like H/h
    "\u0397": "H",  # Η  GREEK CAPITAL LETTER ETA
    "\u03b7": "h",  # η  GREEK SMALL LETTER ETA (looks like n/h)
    # Armenian letters that look like H/h
    "\u053b": "H",  # Ի  ARMENIAN CAPITAL LETTER INI
    "\u056b": "h",  # ի  ARMENIAN SMALL LETTER INI
    # Regional indicator 🇭 → H
    "\U0001f1ed": "H",
    # Small capital H
    "\u029c": "H",  # ʜ  LATIN LETTER SMALL CAPITAL H
    "\u02b0": "h",  # ʰ  MODIFIER LETTER SMALL H
    "\u02b1": "h",  # ʱ  MODIFIER LETTER SMALL H WITH HOOK
    "\u1da3": "h",  # ᶣ  MODIFIER LETTER SMALL TURNED H
    "\u1d78": "H",  # ᵸ  MODIFIER LETTER CYRILLIC EN
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
    # ── Obscure script H letters (visual H lookalikes) ──
    "\U00010337": "H",  # 𐌷  GOTHIC LETTER HAGL
    "\u16ba": "H",  # ᚺ  RUNIC LETTER HAGLAZ
    "\u16bc": "H",  # ᚼ  RUNIC LETTER LONG-BRANCH-HAGALL
    "\u16bd": "h",  # ᚽ  RUNIC LETTER SHORT-TWIG-HAGALL
    "\u310f": "H",  # ㄏ  BOPOMOFO LETTER H
    "\u31b7": "h",  # ㆷ  BOPOMOFO FINAL LETTER H
    "\U0001029b": "H",  # 𐊛  LYCIAN LETTER H
    "\U0001036c": "H",  # 𐍬  OLD PERMIC LETTER HA
    "\u2c90": "H",  # Ⲑ  COPTIC CAPITAL LETTER THETHE
    "\u2c91": "h",  # ⲑ  COPTIC SMALL LETTER THETHE
    "\u071a": "h",  # ܚ  SYRIAC LETTER HETH
    "\u2c10": "H",  # Ⱀ  GLAGOLITIC CAPITAL LETTER NASHI
    "\u2c40": "h",  # ⱀ  GLAGOLITIC SMALL LETTER NASHI
    "\U00010847": "H",  # 𐡇  IMPERIAL ARAMAIC LETTER HETH
    "\U0001088a": "H",  # 𐢊  NABATAEAN LETTER HETH
    "\U0001bc00": "H",  # 𛰀  DUPLOYAN LETTER H
    # ── Modifier H letters (NFKC→already-mapped chars, bypass prenormalize!) ──
    "\ua7f8": "H",  # ꟸ  MODIFIER LETTER CAPITAL H WITH STROKE
    "\U00010795": "h",  # 𐞕  MODIFIER LETTER SMALL H WITH STROKE
    "\U00010796": "H",  # 𐞖  MODIFIER LETTER SMALL CAPITAL H
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
    "\u04cf": "i",  # ӏ  CYRILLIC SMALL LETTER PALOCHKA
    # Latin Iota / I with stroke (look like I/i)
    "\u0196": "I",  # Ɩ  LATIN CAPITAL LETTER IOTA
    "\u0269": "i",  # ɩ  LATIN SMALL LETTER IOTA
    "\u0197": "I",  # Ɨ  LATIN CAPITAL LETTER I WITH STROKE
    "\ua7ae": "I",  # Ɪ  LATIN CAPITAL LETTER I WITH SERIF
    "\u019a": "i",  # ƚ  LATIN SMALL LETTER L WITH BAR (looks like i)
    # Deseret I (obscure script, looks like I/i)
    "\U00010414": "I",  # 𐐔  DESERET CAPITAL LETTER I
    "\U0001043c": "i",  # 𐐼  DESERET SMALL LETTER I
    # ── Latin epigraphic / obscure Latin ──
    "\ua7fe": "I",  # ꟾ  LATIN EPIGRAPHIC LETTER I LONGA
    "\u1d96": "i",  # ᶖ  LATIN SMALL LETTER I WITH RETROFLEX HOOK
    # ── CJK / Korean vertical lines (look like i) ──
    "\u3127": "i",  # ㄧ  BOPOMOFO LETTER I
    "\u3163": "i",  # ㅣ  HANGUL LETTER I
    "\uffdc": "i",  # ￜ  HALFWIDTH HANGUL LETTER I
    # ── Japanese i (commonly used as i substitute on Discord) ──
    "\u3043": "i",  # ぃ  HIRAGANA LETTER SMALL I
    "\u3044": "i",  # い  HIRAGANA LETTER I
    "\u30a3": "i",  # ィ  KATAKANA LETTER SMALL I
    "\u30a4": "i",  # イ  KATAKANA LETTER I
    "\uff68": "i",  # ｨ  HALFWIDTH KATAKANA LETTER SMALL I
    "\uff72": "i",  # ｲ  HALFWIDTH KATAKANA LETTER I
    # ── Cherokee I ──
    "\u13a2": "I",  # Ꭲ  CHEROKEE LETTER I
    "\uab72": "i",  # ꭲ  CHEROKEE SMALL LETTER I
    # ── Obscure script I letters (visual I lookalikes) ──
    "\U00010286": "I",  # 𐊆  LYCIAN LETTER I
    "\U00010309": "I",  # 𐌉  OLD ITALIC LETTER I
    "\U000102b9": "I",  # 𐊹  CARIAN LETTER I
    "\U0001039b": "I",  # 𐎛  UGARITIC LETTER I
    "\U00010498": "I",  # 𐒘  OSMANYA LETTER I
    "\U000104bb": "I",  # 𐒻  OSAGE CAPITAL LETTER I
    "\U000104e3": "i",  # 𐓣  OSAGE SMALL LETTER I
    "\U00010c90": "I",  # 𐲐  OLD HUNGARIAN CAPITAL LETTER I
    "\U00010cd0": "i",  # 𐳐  OLD HUNGARIAN SMALL LETTER I
    "\U0001057e": "I",  # 𐕾  VITHKUQI CAPITAL LETTER I
    "\U000105a5": "i",  # 𐖥  VITHKUQI SMALL LETTER I
    "\U0001050d": "I",  # 𐔍  ELBASAN LETTER I
    "\u07cc": "I",  # ߌ  NKO LETTER I
    "\U00010b0c": "I",  # 𐬌  AVESTAN LETTER I
    "\U00016e4b": "I",  # 𖹋  MEDEFAIDRIN CAPITAL LETTER I
    "\U00016e6b": "i",  # 𖹫  MEDEFAIDRIN SMALL LETTER I
    "\U0001e90b": "I",  # 𞤋  ADLAM CAPITAL LETTER I
    "\U0001e92d": "i",  # 𞤭  ADLAM SMALL LETTER I
    "\ua4f2": "i",  # ꓲ  LISU LETTER I
    "\U0001bc46": "i",  # 𛱆  DUPLOYAN LETTER I
    "\u2c0b": "I",  # Ⰻ  GLAGOLITIC CAPITAL LETTER I
    "\u2c3b": "i",  # ⰻ  GLAGOLITIC SMALL LETTER I
    "\U00010359": "I",  # 𐍙  OLD PERMIC LETTER I
    "\u1822": "i",  # ᠢ  MONGOLIAN LETTER I
    "\ua6a9": "i",  # ꚩ  BAMUM LETTER I
    # ── Modifier I letters (NFKC→already-mapped chars, bypass prenormalize!) ──
    "\u1da4": "i",  # ᶤ  MODIFIER LETTER SMALL I WITH STROKE
    "\u1da6": "i",  # ᶦ  MODIFIER LETTER SMALL CAPITAL I
    "\u1da7": "i",  # ᶧ  MODIFIER LETTER SMALL CAPITAL I WITH STROKE
    # Visual i tricks: common punctuation/number lookalikes
    "!": "i",   # !  EXCLAMATION MARK (vertical line + dot = looks like i)
    "1": "i",   # 1  DIGIT ONE (vertical line = looks like i/l)
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

    # Mark as caught so ai_trigger (Layer 2) skips this message
    try:
        import ai_trigger
        ai_trigger.mark_caught_by_hi(message.id)
    except ImportError:
        pass

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
