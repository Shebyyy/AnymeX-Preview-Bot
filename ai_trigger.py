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
#   1. Pollinations — text greeting detection (GPT-OSS 20B, smart, free, no key)
#   2. OpenRouter — vision greeting detection (free models that SEE images!)
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
REPLY_MESSAGE      = "Single yet? 🤔"

# ── Pollinations API (text — FREE, no key needed!) ──
POLLINATIONS_API_URL = "https://text.pollinations.ai/openai/chat/completions"
POLLINATIONS_MODEL   = "openai"  # GPT-OSS 20B reasoning model

# ── OpenRouter API (vision — needs OPENROUTER_API_KEY) ──
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL  = "https://openrouter.ai/api/v1/chat/completions"

# Free vision models on OpenRouter (ordered by preference)
OPENROUTER_VISION_MODELS = [
    "nvidia/nemotron-nano-12b-v2-vl:free",     # Best free vision — detected greeting image!
    "google/gemma-4-26b-a4b-it:free",            # Google vision model
    "google/gemma-4-31b-it:free",                # Google vision model (bigger)
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # Multi-modal
]

# Pre-check filters
MAX_WORDS     = 30
MIN_LENGTH    = 1
MAX_LENGTH    = 2000
MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4MB max

# Browser User-Agent — Pollinations 403s without it now!
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Track recently caught message IDs to avoid double-firing with hi_trigger
_caught_by_hi: set[int] = set()

# ─────────────────────────────────────────────────────────────────────────────
# Visual Unicode trick decoder
# ─────────────────────────────────────────────────────────────────────────────
# Maps emoji/symbols that visually look like letters → their letter equivalents
# So "♓🇮" (Pisces + flag-I) becomes "hi" for the AI to recognize

VISUAL_MAP = {
    # Zodiac signs that look like letters
    '♓': 'h', '♈': 'r', '♉': 't', '♊': 'i', '♋': 'c', '♌': 'l',
    '♍': 'm', '♎': 'l', '♏': 'm', '♐': 's', '♑': 'c', '♒': 'a',
    # Regional indicators (flag letters A-Z)
    '🇦': 'a', '🇧': 'b', '🇨': 'c', '🇩': 'd', '🇪': 'e', '🇫': 'f',
    '🇬': 'g', '🇭': 'h', '🇮': 'i', '🇯': 'j', '🇰': 'k', '🇱': 'l',
    '🇲': 'm', '🇳': 'n', '🇴': 'o', '🇵': 'p', '🇶': 'q', '🇷': 'r',
    '🇸': 's', '🇹': 't', '🇺': 'u', '🇻': 'v', '🇼': 'w', '🇽': 'x',
    '🇾': 'y', '🇿': 'z',
    # Info symbols
    'ℹ': 'i', 'ℋ': 'h', 'ℌ': 'h', 'Ⓗ': 'h', 'Ⓘ': 'i', 'ⓗ': 'h', 'ⓘ': 'i',
    # Braille alphabet
    '⠁': 'a', '⠃': 'b', '⠉': 'c', '⠙': 'd', '⠑': 'e', '⠋': 'f',
    '⠛': 'g', '⠓': 'h', '⠊': 'i', '⠚': 'j', '⠅': 'k', '⠇': 'l',
    '⠍': 'm', '⠝': 'n', '⠕': 'o', '⠏': 'p', '⠟': 'q', '⠗': 'r',
    '⠎': 's', '⠞': 't', '⠥': 'u', '⠧': 'v', '⠺': 'w', '⠭': 'x',
    '⠽': 'y', '⠵': 'z',
    # Math style / superscript letters
    '𝐡': 'h', '𝐢': 'i', '𝐇': 'h', '𝐈': 'i', 'ʰ': 'h', 'ⁱ': 'i',
    'ᵉ': 'e', 'ʸ': 'y', 'ᵒ': 'o', 'ᵃ': 'a',
    # Runic / ancient scripts that look like latin
    '𐌷': 'h', '𐌹': 'i',
    # Circled letters
    'ⓞ': 'o', 'ⓔ': 'e', 'ⓨ': 'y', 'ⓐ': 'a',
    # Common greeting emojis (not letters but signal greetings)
    '👋': ' wave ',
}

def _decode_visual(text: str) -> str:
    """Decode visual Unicode tricks to readable letters.
    So '♓🇮' (Pisces + flag-I) becomes 'hi'.
    """
    result = []
    for ch in text:
        if ch in VISUAL_MAP:
            result.append(VISUAL_MAP[ch])
        else:
            result.append(ch)
    return ''.join(result)

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

A greeting in visual form: someone waving, a hand wave, text saying hi/hello/hey in any language or script, a waving emoji, waving hand, any visual way of saying hello or greeting someone.

Be generous — if there's any text, wave, or greeting gesture visible, say yes.

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
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": BROWSER_UA},
            ) as resp:
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
# Pollinations AI call (text — free, no key, smart model)
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_pollinations(text: str) -> bool:
    """Send text to Pollinations AI (GPT-OSS 20B). Returns True if greeting.

    Also sends a decoded version of visual Unicode tricks so the AI can
    recognize things like '♓🇮' (Pisces + flag-I) = 'hi'.
    """
    # Decode visual Unicode tricks to readable letters
    decoded = _decode_visual(text)
    # If decoding changed the text, include both versions for the AI
    if decoded.strip() != text.strip() and decoded.strip():
        user_content = f"{text}\n[decoded: {decoded}]"
    else:
        user_content = text

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": POLLINATIONS_MODEL,
                "messages": [
                    {"role": "system", "content": TEXT_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": 3,
                "temperature": 0.1,
            }
            # Browser UA required — Pollinations 403s without it now
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
# OpenRouter Vision AI call (can SEE images — needs OPENROUTER_API_KEY)
# ─────────────────────────────────────────────────────────────────────────────

async def _ask_openrouter_vision(text: str, image_data: list[tuple[str, str]]) -> bool:
    """Send text + images to OpenRouter Vision. Returns True if it's a greeting.

    Tries multiple free vision models in order until one works.
    image_data: list of (base64_data, mime_type) tuples
    """
    if not OPENROUTER_API_KEY:
        return False

    # Build OpenAI-compatible vision message content
    content = [{"type": "text", "text": VISION_PROMPT}]

    if text:
        content.append({"type": "text", "text": f"Message text: {text}"})

    for b64_data, mime_type in image_data:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{b64_data}"
            }
        })

    # Try each free vision model until one works
    for model in OPENROUTER_VISION_MODELS:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 5,
                    "temperature": 0.1,
                }
                headers = {
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://anymex-bot.render.com",
                    "X-Title": "AnymeX-Preview-Bot",
                    "User-Agent": BROWSER_UA,
                }
                async with session.post(
                    OPENROUTER_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        # Rate limited — try next model
                        print(f"[ai_trigger] OpenRouter {model}: rate limited, trying next...")
                        continue

                    if resp.status != 200:
                        body = await resp.text()
                        print(f"[ai_trigger] OpenRouter {model} HTTP {resp.status}: {body[:200]}")
                        continue

                    data = await resp.json()
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()

                    if reply.startswith("yes"):
                        print(f"[ai_trigger] OpenRouter {model}: greeting detected \"{text[:80]}\" → {reply}")
                        return True

                    print(f"[ai_trigger] OpenRouter {model}: not a greeting → {reply}")
                    return False  # Model responded, just said no

        except aiohttp.ClientTimeout:
            print(f"[ai_trigger] OpenRouter {model}: timeout, trying next...")
            continue
        except Exception as e:
            print(f"[ai_trigger] OpenRouter {model}: error {e}, trying next...")
            continue

    print(f"[ai_trigger] All OpenRouter vision models failed")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Main AI check — picks the right model based on content
# ─────────────────────────────────────────────────────────────────────────────

async def _check_greeting(message: discord.Message) -> bool:
    """Check if a message is a greeting using AI.

    Strategy:
    1. Has images/GIFs/stickers + OpenRouter key? → OpenRouter Vision (can SEE them)
    2. Has images but no key? → Pollinations with text description only
    3. Text only → Pollinations (smart, free, no key)
    """
    ai_text = _build_ai_text(message)
    has_attachments = bool(message.attachments)
    has_stickers = bool(message.stickers)
    has_visual = has_attachments or has_stickers

    # ── Has images/GIFs/stickers + OpenRouter key → try OpenRouter Vision ──
    if has_visual and OPENROUTER_API_KEY:
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
            result = await _ask_openrouter_vision(ai_text, image_data)
            if result:
                return True
            # Vision said no — fall through to text check as backup

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

    modes = [f"Pollinations ({POLLINATIONS_MODEL}) — text"]
    if OPENROUTER_API_KEY:
        models_str = ", ".join(m.split("/")[-1] for m in OPENROUTER_VISION_MODELS[:2])
        modes.append(f"OpenRouter vision ({models_str})")
    else:
        modes.append("⚠️ No OPENROUTER_API_KEY — image detection limited to filenames only")

    @bot.listen("on_message")
    async def on_message_ai(message: discord.Message):
        await _handle(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_ai(before: discord.Message, after: discord.Message):
        await _handle(after)

    print(f"✅ ai_trigger loaded — {', '.join(modes)} — watching users {TARGET_USER_IDS}")
