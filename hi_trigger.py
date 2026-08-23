# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (AI-only, no manual maps)
# ══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   Layer 1: Simple regex fast path (plain hi, Hi, HI, hii, 𝐇𝐢, Ｈｉ)
#   Layer 2: Pollinations TEXT AI — understands visual tricks through reasoning
#
# No manual Unicode/ASCII art maps. The AI reasons about visual patterns.
# Covers: |-| |, H|, H!, H1, |-|/, Unicode tricks, Zalgo, l33tspeak, etc.
#
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
WEBHOOK_USERNAME   = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# ── Pollinations API (FREE, no key needed) ──
POLLINATIONS_API_URL = "https://text.pollinations.ai/openai/chat/completions"
POLLINATIONS_MODEL   = "openai"  # GPT-OSS — smart, free

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Max message length to check (longer messages → ai_trigger handles)
AI_MAX_LENGTH = 50

# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Simple regex fast path (instant, no API call)
# ─────────────────────────────────────────────────────────────────────────────
# NFKC normalization handles Unicode equivalents (𝐇𝐢 → Hi, Ｈｉ → Hi)
# Then strip junk and check for h + 1-5 i's.

_JUNK = re.compile(
    r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0\s.,\-_//\\:;'\"\(\)\[\]\{\}\u0300-\u036f]+"
)


def _is_simple_hi(text: str) -> bool:
    """Fast path: catches plain hi, Hi, HI, hii, hiii, 𝐇𝐢, Ｈｉ, etc."""
    s = unicodedata.normalize("NFKC", text.strip())
    s = re.sub(r"^[^\w]+|[^\w]+$", "", s, flags=re.UNICODE)
    s = _JUNK.sub("", s).lower()
    return bool(re.fullmatch(r"hi{1,5}", s))


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: Pollinations TEXT AI — visual trick detection
# ─────────────────────────────────────────────────────────────────────────────
# Instead of manual maps, the AI reasons about visual patterns.
# It knows |-| looks like H, | looks like i, 1 looks like i, etc.
# This generalizes to ANY visual trick, not just hardcoded patterns.

_AI_PROMPT = """You are a visual text pattern detector for a Discord bot.

Your job: determine if the given text is a creative/trick way of writing "hi" or a greeting.

People try to bypass simple "hi" detection using visual tricks. The AI should REASON about what the text LOOKS LIKE visually:

Common visual trick patterns:
- ASCII art letters: "|-|" looks like H (two vertical lines + horizontal dash), so "|-| |" = Hi
- Pipe as i: "H|" looks like Hi, lone "|" can represent i
- Slash as i: "/" can resemble the stem of i, so "|-|/" = Hi
- Exclamation as i: "H!" looks like Hi (the ! dot is like the i dot)
- L33tspeak substitutions: "1" looks like i, so "H1" = Hi
- Unicode lookalikes from other scripts (Cyrillic Н, Greek Η, etc.)
- Fullwidth: Ｈｉ
- Decorated: 𝐇𝐢, 𝓗𝓲, ℍ𝕚, etc.
- Zalgo/combining marks on top of h and i
- Upside-down or mirrored text
- Regional indicators: 🇭🇮
- Braille: ⠓⠊
- Morse/binary/encoded forms of "hi"

IMPORTANT DISTINCTIONS:
- "|-| |" → YES (H + | = Hi visually)
- "H|" → YES (H + | = Hi visually)
- "H!" → YES (H + ! = Hi visually)
- "H1" → YES (H + 1 = Hi in l33tspeak)
- "high" → NO (this is a normal English word meaning "tall", not a greeting)
- "hiring" → NO (normal word)
- "hint" → NO (normal word)
- "this" → NO (contains "hi" but is a different word)
- "child" → NO (contains "hi" but is a different word)
- "hiiiiiiiiii" (6+ i's) → NO (that's just spam, not a greeting)

Reply only "yes" or "no"."""


# Characters that suggest the text might be a visual trick (non-standard for greetings)
_TRICK_CHARS = set("|!/-\\[]{}<>~`@#$%^&*()_+=:;'\"" + "1")


def _is_suspicious(text: str) -> bool:
    """Quick check: does this text contain characters used in visual tricks?"""
    return any(c in _TRICK_CHARS for c in text.strip())


def _should_ask_ai(text: str) -> bool:
    """Pre-filter: only send suspicious or non-ASCII text to AI.

    Skips:
    - URLs, code blocks, empty, too long
    - Pure ASCII text without trick characters (normal words go to ai_trigger)
    Allows:
    - Text with special chars (H|, |-| |)
    - Non-ASCII Unicode (Ƕi, Ħi, 𝐇𝐢)
    """
    stripped = text.strip()
    if not stripped or len(stripped) > AI_MAX_LENGTH:
        return False
    if stripped.startswith("```"):
        return False
    if re.match(r"^https?://\S+$", stripped):
        return False
    # Pure ASCII without trick chars → let ai_trigger handle it
    if stripped.isascii() and not _is_suspicious(stripped):
        return False
    return True


def _extract_suspicious_words(text: str) -> list[str]:
    """From a longer message, extract words that look like visual tricks.

    For "check this |-| | out" → ["|-| |"]
    Only words with trick characters are returned.
    """
    words = text.split()
    results = []
    for i, w in enumerate(words):
        if not _is_suspicious(w):
            continue
        # Single word
        if len(w) <= AI_MAX_LENGTH:
            results.append(w)
        # Pair with adjacent word if short enough
        if i < len(words) - 1:
            pair = w + " " + words[i + 1]
            if len(pair) <= AI_MAX_LENGTH:
                results.append(pair)
        if i > 0:
            pair = words[i - 1] + " " + w
            if len(pair) <= AI_MAX_LENGTH:
                results.append(pair)
    return results


async def _ask_pollinations(text: str) -> bool:
    """Send text to Pollinations AI. Returns True if it's a visual "hi" trick."""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": POLLINATIONS_MODEL,
                "messages": [
                    {"role": "system", "content": _AI_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 5,
                "temperature": 0.1,
            }
            headers = {
                "Content-Type": "application/json",
                "User-Agent": BROWSER_UA,
            }
            async with session.post(
                POLLINATIONS_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[hi_trigger] Pollinations HTTP {resp.status}: {body[:200]}")
                    return False

                data = await resp.json()
                reply = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                    .lower()
                )

                if reply.startswith("yes"):
                    print(f"[hi_trigger] AI detected hi in \"{text[:50]}\" → {reply}")
                    return True
                print(f"[hi_trigger] AI: not hi \"{text[:50]}\" → {reply}")
                return False

    except aiohttp.ClientTimeout:
        print(f"[hi_trigger] Pollinations timeout: \"{text[:50]}\"")
        return False
    except Exception as e:
        print(f"[hi_trigger] Pollinations error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

_bot = None


async def _trigger(message: discord.Message):
    """Fire the reply — shared by both layers."""
    # Mark as caught so ai_trigger skips this message
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
                        return
                    body = await resp.text()
                    print(f"[hi_trigger] Webhook HTTP {resp.status}: {body[:200]} — falling back")
        await message.reply(REPLY_MESSAGE, mention_author=True)
        print(f"[hi_trigger] Replied via normal reply ✅")
    except Exception as e:
        print(f"[hi_trigger] Error: {e}")
        try:
            await message.reply(REPLY_MESSAGE, mention_author=True)
        except Exception as e2:
            print(f"[hi_trigger] Fallback also failed: {e2}")


async def _handle(message: discord.Message):
    if message.author.bot:
        return
    if message.author.id not in TARGET_USER_IDS:
        return

    text = message.content
    stripped = text.strip()
    if not stripped:
        return

    # ── Build segments to check ──
    if len(stripped) <= AI_MAX_LENGTH:
        segments = [stripped]
    else:
        segments = _extract_suspicious_words(text)

    # ── Check each segment ──
    for seg in segments:
        # Layer 1: Instant regex
        if _is_simple_hi(seg):
            await _trigger(message)
            return

        # Layer 2: Pollinations TEXT AI
        if _should_ask_ai(seg) and await _ask_pollinations(seg):
            await _trigger(message)
            return


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

    print(f"✅ hi_trigger loaded — regex + Pollinations AI — watching users {TARGET_USER_IDS}")
