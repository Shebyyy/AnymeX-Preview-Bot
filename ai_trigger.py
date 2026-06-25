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
#   - GIFs / images that show greetings (waving, hi text, etc.)
#   - Any creative/trick way of saying hi
#
# AI stack (all FREE, works on render.com):
#   1. Pollinations — primary, free, no key needed (GPT-OSS 20B, smart!)
#   2. Groq Vision — sees actual images/GIFs/stickers (needs GROQ_API_KEY)
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

# ── Pollinations API (primary — FREE, no key needed!) ──
POLLINATIONS_API_URL = "https://text.pollinations.ai/openai/chat/completions"
POLLINATIONS_MODEL   = "openai"  # GPT-OSS 20B reasoning model

# ── Groq API (vision — needs GROQ_API_KEY) ──
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL       = "https://api.groq.com/openai/v1/chat/completions"
GROQ_VISION_MODEL  = "llama-3.2-11b-vision-preview"

# Pre-check filters
MAX_WORDS     = 30
MIN_LENGTH    = 1
MAX_LENGTH    = 2000
MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB max

# Track recently caught message IDs to avoid double-firing with hi_trigger
_caught_by_hi: set[int] = set()

# ─────────────────────────────────────────────────────────────────────────────
# AI Prompts
# ─────────────────────────────────────────────────────────────────────────────

TEXT_PROMPT = """Is this message a greeting?

A greeting is any message whose MAIN PURPOSE is to say hello, acknowledge someone, or start a conversation. Examples: hi, hey, hello, yo, sup, what's up, howdy, hola, namaste, ciao, konnichiwa, salaam, annyeong, bonjour, aloha, greetings, wassup, etc.

Also count as greeting: emoji-only greetings (👋), Unicode tricks (♓ℹ ⠓⠊ 𐌷𐌹), l33tspeak (h1 y0), encoded text (Morse, binary, Base64, ROT13), ASCII art, reversed text, any creative/trick way to say hello.

If the message has an attachment: only say yes if the filename clearly indicates a greeting (like wave.gif, hello.png, hi_sticker). Generic filenames like image.png do NOT count as a greeting just because they exist.

NOT a greeting: normal sentences, questions, statements, comments. "It's unchanged tho?" is NOT a greeting.

Reply only "yes" or "no"."""

VISION_PROMPT = """Does this image/GIF show a greeting?

A greeting in visual form: someone waving, a hand wave, text saying hi/hello in any language, a waving emoji, any visual way of saying hello.

Reply only "yes" or "no"."""


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
# Pollinations AI call (primary — free, no key, smart model)
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_pollinations(text: str) -> bool:
    """Send text to Pollinations AI (GPT-OSS 20B). Returns True if greeting."""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": POLLINATIONS_MODEL,
                "messages": [
                    {"role": "system", "content": TEXT_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 3,
                "temperature": 0.1,
            }
            headers = {"Content-Type": "application/json"}
            async with session.post(
                POLLINATIONS_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[ai_trigger] Pollinations HTTP {resp.status}: {body[:200]}")
                    return False

                data = await resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()

                if reply.startswith("yes"):
                    print(f"[ai_trigger] Pollinations: greeting detected \"{text[:80]}\" → {reply}")
                    return True
                return False

    except aiohttp.ClientTimeout:
        print(f"[ai_trigger] Pollinations timeout: \"{text[:50]}\"")
        return False
    except Exception as e:
        print(f"[ai_trigger] Pollinations error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Groq Vision AI call (can SEE images — needs GROQ_API_KEY)
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_groq_vision(text: str, image_data: list[tuple[str, str]]) -> bool:
    """Send text + images to Groq Vision. Returns True if it's a greeting.

    image_data: list of (base64_data, mime_type) tuples
    """
    if not GROQ_API_KEY:
        return False

    try:
        # Build OpenAI-compatible vision message content
        content = [{"type": "text", "text": VISION_PROMPT}]

        if text:
            content.append({"type": "text", "text": f"Message: {text}"})

        for b64_data, mime_type in image_data:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{b64_data}"
                }
            })

        async with aiohttp.ClientSession() as session:
            payload = {
                "model": GROQ_VISION_MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 3,
                "temperature": 0.1,
            }
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            async with session.post(
                GROQ_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[ai_trigger] Groq vision HTTP {resp.status}: {body[:300]}")
                    return False

                data = await resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()

                if reply.startswith("yes"):
                    print(f"[ai_trigger] Groq vision: greeting detected \"{text[:80]}\" → {reply}")
                    return True
                return False

    except aiohttp.ClientTimeout:
        print(f"[ai_trigger] Groq vision timeout: \"{text[:50]}\"")
        return False
    except Exception as e:
        print(f"[ai_trigger] Groq vision error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main AI check — picks the right model based on content
# ─────────────────────────────────────────────────────────────────────────────

async def _check_greeting(message: discord.Message) -> bool:
    """Check if a message is a greeting using AI.

    Strategy:
    1. Has images/GIFs/stickers + Groq key? → Groq Vision (can SEE them)
    2. Everything else → Pollinations (smart, free, no key)
    """
    ai_text = _build_ai_text(message)
    has_attachments = bool(message.attachments)
    has_stickers = bool(message.stickers)
    has_visual = has_attachments or has_stickers

    # ── Has images/GIFs/stickers + Groq key → try Groq Vision ──
    if has_visual and GROQ_API_KEY:
        image_data = []

        # Download image attachments
        for att in message.attachments:
            is_image = False
            if att.content_type and any(t in att.content_type.lower() for t in ['image', 'gif']):
                is_image = True
            if att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                is_image = True

            if is_image:
                result = await _download_as_base64(att.url)
                if result:
                    image_data.append(result)

        # Download sticker images
        for sticker in message.stickers:
            sticker_url = sticker.url if sticker.url else None
            if not sticker_url and sticker.id:
                sticker_url = f"https://cdn.discordapp.com/stickers/{sticker.id}.png"

            if sticker_url:
                result = await _download_as_base64(sticker_url)
                if result:
                    image_data.append(result)

        if image_data:
            result = await _ask_groq_vision(ai_text, image_data)
            if result:
                return True
            # If Groq vision said no, still try Pollinations with text description
            # (maybe the vision model missed something the text model catches)

    # ── Everything → Pollinations ──
    return await _ask_pollinations(ai_text)


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

    modes = [f"Pollinations ({POLLINATIONS_MODEL}) — primary"]
    if GROQ_API_KEY:
        modes.append(f"Groq vision ({GROQ_VISION_MODEL})")
    else:
        modes.append("⚠️ No GROQ_API_KEY — image detection limited to filenames only")

    @bot.listen("on_message")
    async def on_message_ai(message: discord.Message):
        await _handle(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_ai(before: discord.Message, after: discord.Message):
        await _handle(after)

    print(f"✅ ai_trigger loaded — {', '.join(modes)} — watching users {TARGET_USER_IDS}")
