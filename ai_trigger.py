# ══════════════════════════════════════════════════════════════════════════════
# ai_trigger.py  —  AI-powered greeting detector (Layer 2)
# ══════════════════════════════════════════════════════════════════════════════
#
# This runs AFTER hi_trigger.py (Layer 1). If the pattern-based detector
# didn't catch the message, this sends it to AI to check intent.
#
# Catches EVERYTHING hi_trigger misses:
#   - Other greetings: hey, hello, sup, yo, hola, namaste, etc.
#   - Unicode tricks: ♓ℹ, ⠓⠊, 🇭🇮, ⓗⓘ, 𐌷𐌹, 𝐡𝐢, ʰⁱ
#   - ASCII art of "hi" or greetings
#   - Encoded: Morse (.... ..), Binary, Braille, Base64, ROT13
#   - L33tspeak: h1, h3y, h3llo, y0
#   - Emoji-only greetings: 👋, 🙏, 🤝
#   - Stickers that are greetings
#   - GIFs / attachments that look like greetings
#   - Any creative/trick way of saying hi
#
# Uses Groq API (free, ~0.1-0.3s response time)
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import unicodedata
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? <:hmmm:1497190580344586422>"
# AI trigger uses plain reply (bot's own profile) — no webhook/custom tag

# Groq API config
GROQ_API_KEY  = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.1-8b-instant"  # Fast + free tier friendly

# Pre-check filters (very relaxed — we only check 2 target users anyway)
MAX_WORDS     = 30     # Allow ASCII art / encoded messages (was 6)
MIN_LENGTH    = 1      # Skip empty messages
MAX_LENGTH    = 2000   # Allow ASCII art (was 40)

# Track recently caught message IDs to avoid double-firing with hi_trigger
_caught_by_hi: set[int] = set()

# ─────────────────────────────────────────────────────────────────────────────
# AI Prompt — knows about ALL encoding tricks
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an extremely thorough greeting detector. Your job is to catch ANY form of greeting or saying "hi", no matter how creative or encoded.

A greeting includes ALL of these:

1. DIRECT GREETINGS: hi, hey, hello, sup, yo, howdy, heya, hiya, yoo, heyyyy
2. OTHER LANGUAGES: hola, bonjour, namaste, ciao, konnichiwa, salaam, salut, aloha, privyet, merhaba, jambo, olá, hallo, hei, hej, czesc, ahoy, annyeong, ni hao
3. SLANG: wassup, what's up, whats good, how's it going, watcha, yooo, heyyyy, wagwan, yerr
4. EMOJI GREETINGS: 👋, 🙏, 🤝, 🫡, 🖐️, ✋ (when used as standalone greeting)
5. L33TSPEAK / CREATIVE: h1, h3y, h3llo, y0, h1h1, any deliberate trick spelling

6. UNICODE TRICKS (visual lookalikes for "hi"):
   - Regional indicators: 🇭🇮
   - Circled: ⓗⓘ
   - Fullwidth: ｈｉ
   - Superscript: ʰⁱ
   - Subscript: ₕᵢ
   - Small caps: ʜɪ
   - Gothic: 𐌷𐌹
   - Mathematical: 𝐡𝐢, 𝘩𝘪, 𝕙𝕚, 𝚑𝚒
   - Braille: ⠓⠊
   - Any Unicode characters that visually spell "hi" (♓ℹ, etc.)

7. ENCODED "hi":
   - Morse code: .... ..
   - Binary: 01101000 01101001
   - ASCII/decimal: 104 105
   - Hex: 68 69
   - Base64: aGk=
   - ROT13: uv
   - Any number code that represents hi

8. ASCII ART that spells "hi" or a greeting word
9. STICKER names that are greetings
10. REVERSED: ih (when used as a trick for hi)
11. ANY combination of symbols, numbers, letters, emoji that represents a greeting

NOT a greeting:
- Normal conversation, questions, statements (longer messages with real content)
- "its", "it's", "it is" — these are pronouns, not greetings
- Short reactions, filler words, expressions (ohhk, ok, okay, lol, wtf, damn, bruh, etc.)
- Swearing or frustrated messages
- Words that happen to start with h (high, hiring, hint, history, help, here, how, have)
- Real words in sentences (not tricks)
- Code blocks with actual code
- URLs or links

Be thorough but precise. When in doubt, say no. Only say yes if you're confident it's a greeting.

Reply ONLY one word: "yes" or "no" """


# ─────────────────────────────────────────────────────────────────────────────
# Quick pre-filter (very relaxed — only skip OBVIOUSLY not-greetings)
# ─────────────────────────────────────────────────────────────────────────────

# Only skip messages that are 100% definitely not greetings
# We removed the aggressive _DEF_NOT_GREETING list because the AI is smart enough
# and we only check 2 target users (very low API usage)

def _should_check_ai(text: str, message: discord.Message = None) -> bool:
    """Very relaxed filter — return True if message COULD be a greeting.
    
    Since we only check 2 target users, we can afford to send almost
    everything to AI. We only skip obviously-not-greeting messages.
    """
    stripped = text.strip()

    # ── Always check ──
    # Stickers (might be greeting stickers)
    if message and message.stickers:
        return True

    # Attachments (GIFs, images — might be waving GIF etc.)
    if message and message.attachments:
        return True

    # Empty text
    if not stripped:
        # But if there are stickers/attachments with no text, still check
        if message and (message.stickers or message.attachments):
            return True
        return False

    # Length check (very generous)
    if len(stripped) < MIN_LENGTH:
        return False
    if len(stripped) > MAX_LENGTH:
        return False

    # Word count (allow more for encoded messages / ASCII art)
    if len(stripped.split()) > MAX_WORDS:
        return False

    # Skip code blocks (actual code, not tricks)
    if stripped.startswith('```') and stripped.endswith('```'):
        return False

    # Skip URLs only
    if re.match(r'^https?://\S+$', stripped):
        return False

    # ── Let everything else through to AI ──
    # The AI is smart — let it decide. We only have 2 target users,
    # so even sending all their messages would be <100 calls/day.
    # Groq free tier allows 14,400/day. No worries.
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Build the text to send to AI (includes stickers, attachments context)
# ─────────────────────────────────────────────────────────────────────────────

def _build_ai_text(message: discord.Message) -> str:
    """Build the text representation to send to AI, including stickers/attachments."""
    parts = []

    # Main text content
    if message.content.strip():
        parts.append(message.content.strip())

    # Stickers — include name and description
    for sticker in message.stickers:
        sticker_info = f"[sticker: {sticker.name}"
        if sticker.description:
            sticker_info += f" - {sticker.description}"
        sticker_info += "]"
        parts.append(sticker_info)

    # Attachments — describe what they are
    for att in message.attachments:
        att_info = f"[attachment: {att.filename}"
        if att.content_type:
            att_info += f" ({att.content_type})"
        # Flag GIFs specifically — they're commonly used as greetings
        if att.filename.lower().endswith('.gif'):
            att_info += " - this is a GIF"
        if att.content_type and 'gif' in att.content_type.lower():
            att_info += " - this is a GIF"
        att_info += "]"
        parts.append(att_info)

    return " | ".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────────────────────
# Groq AI call
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_ai(text: str) -> bool:
    """Send message to Groq AI and return True if it's a greeting."""
    if not GROQ_API_KEY:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 3,        # We only need "yes" or "no"
                "temperature": 0.1,      # Low temp = more consistent
                "top_p": 1,
            }
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            async with session.post(
                GROQ_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),  # Slightly longer for ASCII art
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[ai_trigger] Groq HTTP {resp.status}: {body[:200]}")
                    return False

                data = await resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()

                if reply.startswith("yes"):
                    print(f"[ai_trigger] AI detected greeting: \"{text[:100]}\" → {reply}")
                    return True
                return False

    except aiohttp.ClientTimeout:
        print(f"[ai_trigger] Groq timeout for: \"{text[:50]}\"")
        return False
    except Exception as e:
        print(f"[ai_trigger] Groq error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

_bot = None


async def _handle(message: discord.Message):
    if message.author.bot:
        return

    # Only check target users
    if message.author.id not in TARGET_USER_IDS:
        return

    # Skip if hi_trigger already caught this message
    if message.id in _caught_by_hi:
        _caught_by_hi.discard(message.id)  # Clean up
        return

    # Build the full text (content + stickers + attachments)
    ai_text = _build_ai_text(message)

    # Very relaxed pre-filter
    if not _should_check_ai(ai_text, message):
        return

    # Ask AI
    is_greeting = await _ask_ai(ai_text)

    if not is_greeting:
        return

    print(f"[ai_trigger] Triggered by {message.author} in #{message.channel}")

    # AI trigger uses plain reply — bot's own profile, no custom webhook
    try:
        await message.reply(REPLY_MESSAGE, mention_author=True)
        print(f"[ai_trigger] Replied via normal reply ✅")
    except Exception as e:
        print(f"[ai_trigger] Reply failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Public API for hi_trigger to mark messages as caught
# ─────────────────────────────────────────────────────────────────────────────

def mark_caught_by_hi(message_id: int):
    """Called by hi_trigger when it catches a message, so ai_trigger skips it."""
    _caught_by_hi.add(message_id)


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

def setup(bot: discord.Client):
    global _bot
    _bot = bot

    if not GROQ_API_KEY:
        print("⚠️ ai_trigger NOT loaded — GROQ_API_KEY environment variable is not set")
        return

    @bot.listen("on_message")
    async def on_message_ai(message: discord.Message):
        await _handle(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_ai(before: discord.Message, after: discord.Message):
        await _handle(after)

    print(f"✅ ai_trigger loaded — AI greeting detector watching users {TARGET_USER_IDS}")
