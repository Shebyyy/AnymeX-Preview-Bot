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
#   - GIFs / images that show greetings (waving, hi text, etc.) ← VISION!
#   - Any creative/trick way of saying hi
#
# Dual AI:
#   - Groq (text-only) — fastest, for messages without attachments
#   - Google Gemini Flash (vision) — can SEE images/GIFs/stickers
#
# Both are FREE. Groq: 14,400 req/day. Gemini: 1,500 req/day.
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import base64
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? <:hmmm:1497190580344586422>"
# AI trigger uses plain reply (bot's own profile) — no webhook/custom tag

# ── Groq API (text-only, fast) ──
GROQ_API_KEY  = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.1-8b-instant"

# ── Google Gemini API (vision — can see images/GIFs) ──
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GEMINI_MODEL  = "gemini-2.0-flash"  # Free, fast, supports images

# Pre-check filters
MAX_WORDS     = 30
MIN_LENGTH    = 1
MAX_LENGTH    = 2000
MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB max for Gemini

# Track recently caught message IDs to avoid double-firing with hi_trigger
_caught_by_hi: set[int] = set()

# ─────────────────────────────────────────────────────────────────────────────
# AI Prompt — clear rules, no ambiguity
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Determine whether the message's primary intent is to greet someone.

Reply "yes" ONLY if the message itself is a greeting, in ANY language, script, encoding, or visual form.

Examples that ARE greetings:
- Any language: hi, hello, hey, hola, bonjour, ciao, namaste, salaam, assalamu alaikum, konnichiwa, annyeong, ni hao, etc.
- Informal greetings: sup, yo, wassup, morning, good morning, good evening, etc.
- Emoji or visual greetings: 👋 🙋 🤝 🙏
- Unicode/obfuscated forms: ⓗⓘ, 𐌷𐌹, 🇭🇮, ♓ℹ, ⠓⠊, zero-width characters, homoglyphs, combining marks.
- Encoded forms: Morse, Binary, Hex, Base64, ROT13, Braille.
- ASCII art, stickers, GIFs, images, or any creative way intended as a greeting.

Reply "no" if:
- The message only mentions greetings (e.g. "the word hi").
- It is a question or discussion about greetings.
- "hi" appears inside another unrelated word.
- The primary intent is not greeting someone.

Output ONLY:
yes
or
no
"""

# Separate prompt for vision (image analysis)
VISION_PROMPT = """Determine whether this image/GIF/sticker's primary purpose is greeting someone.

Reply "yes" if it visually represents a greeting in any language or form (text, waving, bowing, handshake, greeting sticker, etc.).

Reply "no" otherwise.

Output ONLY:
yes
or
no
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pre-filter — relaxed, let AI decide
# ─────────────────────────────────────────────────────────────────────────────

def _should_check_ai(text: str, message: discord.Message = None) -> bool:
    """Very relaxed filter — let AI decide. We only check 2 target users."""
    stripped = text.strip()

    # Always check stickers and attachments
    if message and message.stickers:
        return True
    if message and message.attachments:
        return True

    # Empty text
    if not stripped:
        if message and (message.stickers or message.attachments):
            return True
        return False

    if len(stripped) < MIN_LENGTH or len(stripped) > MAX_LENGTH:
        return False
    if len(stripped.split()) > MAX_WORDS:
        return False
    if stripped.startswith('```') and stripped.endswith('```'):
        return False
    if re.match(r'^https?://\S+$', stripped):
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Build text context for AI (stickers, attachment descriptions)
# ─────────────────────────────────────────────────────────────────────────────

def _build_ai_text(message: discord.Message) -> str:
    """Build text for AI. Stickers/attachments described by name."""
    parts = []

    if message.content.strip():
        parts.append(message.content.strip())

    for sticker in message.stickers:
        info = f"[sticker: {sticker.name}"
        if sticker.description:
            info += f" - {sticker.description}"
        info += "]"
        parts.append(info)

    for att in message.attachments:
        info = f"[attachment: {att.filename}"
        if att.content_type:
            info += f" ({att.content_type})"
        if att.filename.lower().endswith('.gif') or (att.content_type and 'gif' in att.content_type.lower()):
            info += " - GIF"
        info += "]"
        parts.append(info)

    return " | ".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────────────────────
# Download attachment as base64
# ─────────────────────────────────────────────────────────────────────────────

async def _download_as_base64(url: str, max_size: int = MAX_IMAGE_SIZE) -> tuple[str, str] | None:
    """Download an image from URL and return (base64_data, mime_type) or None."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                # Check size before downloading
                content_length = resp.headers.get('Content-Length')
                if content_length and int(content_length) > max_size:
                    return None

                data = await resp.read()
                if len(data) > max_size:
                    return None

                mime_type = resp.headers.get('Content-Type', 'image/png')
                b64 = base64.b64encode(data).decode('utf-8')
                return (b64, mime_type)
    except Exception as e:
        print(f"[ai_trigger] Download failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Groq AI call (text-only)
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_groq(text: str) -> bool:
    """Send text to Groq AI. Returns True if it's a greeting."""
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
                "max_tokens": 3,
                "temperature": 0.1,
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
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[ai_trigger] Groq HTTP {resp.status}: {body[:200]}")
                    return False

                data = await resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()

                if reply.startswith("yes"):
                    print(f"[ai_trigger] Groq: greeting detected \"{text[:80]}\" → {reply}")
                    return True
                return False

    except aiohttp.ClientTimeout:
        print(f"[ai_trigger] Groq timeout: \"{text[:50]}\"")
        return False
    except Exception as e:
        print(f"[ai_trigger] Groq error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Google Gemini AI call (vision — can SEE images)
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_gemini_vision(text: str, image_data: list[tuple[str, str]] = None) -> bool:
    """Send text + optional images to Gemini. Returns True if it's a greeting.
    
    image_data: list of (base64_data, mime_type) tuples
    """
    if not GEMINI_API_KEY:
        # No Gemini key — fall back to text-only analysis
        return False

    try:
        # Build content parts
        parts = []

        # System instruction
        parts.append({"text": VISION_PROMPT if image_data else SYSTEM_PROMPT})

        # User text
        if text:
            parts.append({"text": text})

        # Images
        if image_data:
            for b64_data, mime_type in image_data:
                parts.append({
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": b64_data
                    }
                })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "maxOutputTokens": 3,
                "temperature": 0.1,
                "topP": 1,
            }
        }

        url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[ai_trigger] Gemini HTTP {resp.status}: {body[:200]}")
                    return False

                data = await resp.json()
                # Gemini response format
                candidates = data.get("candidates", [])
                if not candidates:
                    return False

                reply = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip().lower()

                if reply.startswith("yes"):
                    src = "vision" if image_data else "text"
                    print(f"[ai_trigger] Gemini ({src}): greeting detected \"{text[:80]}\" → {reply}")
                    return True
                return False

    except aiohttp.ClientTimeout:
        print(f"[ai_trigger] Gemini timeout: \"{text[:50]}\"")
        return False
    except Exception as e:
        print(f"[ai_trigger] Gemini error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main AI check — picks the right model based on content
# ─────────────────────────────────────────────────────────────────────────────

async def _check_greeting(message: discord.Message) -> bool:
    """Check if a message is a greeting using AI.
    
    Strategy:
    - If message has image/GIF attachments → use Gemini (can SEE them)
    - If message has sticker image → try Gemini with sticker image
    - If text-only → use Groq (fastest)
    - If no vision API available → fall back to text description only
    """
    ai_text = _build_ai_text(message)
    has_attachments = bool(message.attachments)
    has_stickers = bool(message.stickers)

    # ── Has image/GIF attachments → use Gemini Vision ──
    if has_attachments and GEMINI_API_KEY:
        image_data = []
        for att in message.attachments:
            # Only process image-like attachments
            is_image = False
            if att.content_type and any(t in att.content_type.lower() for t in ['image', 'gif']):
                is_image = True
            if att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                is_image = True

            if is_image:
                result = await _download_as_base64(att.url)
                if result:
                    image_data.append(result)

        if image_data:
            # Send to Gemini with actual images!
            return await _ask_gemini_vision(ai_text, image_data)

    # ── Has stickers → try Gemini with sticker image ──
    if has_stickers and GEMINI_API_KEY:
        image_data = []
        for sticker in message.stickers:
            # Discord stickers have a URL we can download
            sticker_url = None
            if sticker.url:
                sticker_url = sticker.url
            # Try different format URLs
            if not sticker_url and sticker.id:
                sticker_url = f"https://cdn.discordapp.com/stickers/{sticker.id}.png"

            if sticker_url:
                result = await _download_as_base64(sticker_url)
                if result:
                    image_data.append(result)

        if image_data:
            return await _ask_gemini_vision(ai_text, image_data)

    # ── Text-only or no vision API → use Groq (fastest) ──
    if GROQ_API_KEY:
        result = await _ask_groq(ai_text)
        # If Groq says no but message has attachments/stickers,
        # try Gemini with text description as fallback
        if not result and (has_attachments or has_stickers) and GEMINI_API_KEY:
            return await _ask_gemini_vision(ai_text)
        return result

    # ── Only Gemini available → use it for text too ──
    if GEMINI_API_KEY:
        return await _ask_gemini_vision(ai_text)

    # No API keys set
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
        _caught_by_hi.discard(message.id)
        return

    # Pre-filter
    ai_text = _build_ai_text(message)
    if not _should_check_ai(ai_text, message):
        return

    # Ask AI (picks right model automatically)
    is_greeting = await _check_greeting(message)

    if not is_greeting:
        return

    print(f"[ai_trigger] Triggered by {message.author} in #{message.channel}")

    # AI trigger uses plain reply — bot's own profile
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

    has_ai = bool(GROQ_API_KEY or GEMINI_API_KEY)
    if not has_ai:
        print("⚠️ ai_trigger NOT loaded — set GROQ_API_KEY and/or GEMINI_API_KEY")
        return

    @bot.listen("on_message")
    async def on_message_ai(message: discord.Message):
        await _handle(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_ai(before: discord.Message, after: discord.Message):
        await _handle(after)

    modes = []
    if GROQ_API_KEY:
        modes.append(f"Groq text ({GROQ_MODEL})")
    if GEMINI_API_KEY:
        modes.append(f"Gemini vision ({GEMINI_MODEL})")
    print(f"✅ ai_trigger loaded — {', '.join(modes)} — watching users {TARGET_USER_IDS}")
