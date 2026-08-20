# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (Vision AI, no manual maps)
# ══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   Layer 1: Simple regex fast path (plain hi, Hi, HI, hii, etc.)
#   Layer 2: Vision AI — render text as image → VLM literally sees visual tricks
#
# No manual Unicode maps. The VLM catches H|, H!, Ƕi, ASCII art, etc.
# ══════════════════════════════════════════════════════════════════════════════

import os
import io
import re
import base64
import unicodedata
import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? 🤔"
WEBHOOK_USERNAME   = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# ── OpenRouter Vision (free models, same API key ai_trigger uses) ──
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

VISION_MODELS = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
]

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Max message length to send to vision (short tricks only)
VISION_MAX_LEN = 30

# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Simple regex fast path (instant, no API call)
# ─────────────────────────────────────────────────────────────────────────────
# NFKC normalization handles most Unicode equivalents (𝐇𝐢 → Hi, Ｈｉ → Hi, etc.)
# Then strip junk and check for h + 1-5 i's.

_JUNK = re.compile(
    r"[\*_~`|>#\u200b\u200c\u200d\u200e\u200f\u00a0\s.,\-_/\\:;'\"\(\)\[\]\{\}\u0300-\u036f]+"
)


def _is_simple_hi(text: str) -> bool:
    """Fast path: catches plain hi, Hi, HI, hii, hiii, 𝐇𝐢, Ｈｉ, etc."""
    s = unicodedata.normalize("NFKC", text.strip())
    s = re.sub(r"^[^\w]+|[^\w]+$", "", s, flags=re.UNICODE)
    s = _JUNK.sub("", s).lower()
    return bool(re.fullmatch(r"hi{1,5}", s))


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: Render text as image → Vision AI
# ─────────────────────────────────────────────────────────────────────────────

_VISION_PROMPT = """Does this image visually look like the word "hi" or a greeting?

Look at the visual appearance of the characters — not their Unicode values.
Examples of visual tricks that should be caught:
- "H|" looks like "Hi" (pipe | resembles the letter i)
- "H!" looks like "Hi" (exclamation mark resembles i)
- "H1" looks like "Hi" (digit 1 resembles i)
- Any Unicode characters that visually resemble the letters h and i

Only say "yes" if the text visually resembles "hi" or a greeting word.
If it's random characters/symbols that don't look like any word, say "no".

Reply only "yes" or "no"."""


def _should_try_vision(text: str) -> bool:
    """Pre-filter: only short, non-empty messages go to vision."""
    stripped = text.strip()
    if not stripped or len(stripped) > VISION_MAX_LEN:
        return False
    if stripped.startswith("```"):
        return False
    if re.match(r"^https?://\S+$", stripped):
        return False
    return True


def _render_text_as_image(text: str) -> str | None:
    """Render text to a PNG image, return base64."""
    try:
        img = Image.new("RGB", (600, 100), "white")
        draw = ImageDraw.Draw(img)

        # Try system fonts, fall back to default
        font = None
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]:
            try:
                font = ImageFont.truetype(path, 48)
                break
            except (IOError, OSError):
                continue

        if font is None:
            font = ImageFont.load_default()

        draw.text((20, 20), text, fill="black", font=font)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[hi_trigger] Render failed: {e}")
        return None


async def _ask_vision_hi(text: str) -> bool:
    """Send rendered text image to Vision AI. Returns True if it looks like 'hi'."""
    if not OPENROUTER_API_KEY:
        print("[hi_trigger] No OPENROUTER_API_KEY — skipping vision check")
        return False

    b64_image = _render_text_as_image(text)
    if not b64_image:
        return False

    for model in VISION_MODELS:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _VISION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64_image}"
                                },
                            },
                        ],
                    }],
                    "max_tokens": 5,
                    "temperature": 0.1,
                }
                headers = {
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "User-Agent": BROWSER_UA,
                }
                async with session.post(
                    OPENROUTER_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        print(f"[hi_trigger] Vision {model}: rate limited, trying next...")
                        continue
                    if resp.status != 200:
                        body = await resp.text()
                        print(f"[hi_trigger] Vision {model} HTTP {resp.status}: {body[:200]}")
                        continue

                    data = await resp.json()
                    reply = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                        .lower()
                    )

                    if reply.startswith("yes"):
                        print(f"[hi_trigger] Vision {model}: detected hi in \"{text[:50]}\"")
                        return True
                    print(f"[hi_trigger] Vision {model}: not hi → {reply}")
                    return False

        except aiohttp.ClientTimeout:
            print(f"[hi_trigger] Vision {model}: timeout, trying next...")
            continue
        except Exception as e:
            print(f"[hi_trigger] Vision {model}: error {e}")
            continue

    print("[hi_trigger] All vision models failed")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

_bot = None


async def _handle(message: discord.Message):
    if message.author.bot:
        return
    if message.author.id not in TARGET_USER_IDS:
        return

    text = message.content

    # Layer 1: Instant regex check
    if not _is_simple_hi(text):
        # Layer 2: Vision AI for visual tricks
        if not _should_try_vision(text):
            return
        if not await _ask_vision_hi(text):
            return

    # Mark as caught so ai_trigger (Layer 3) skips this message
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

    vision_status = "Vision AI ✅" if OPENROUTER_API_KEY else "Vision AI ❌ (no OPENROUTER_API_KEY)"
    print(f"✅ hi_trigger loaded — regex + {vision_status} — watching users {TARGET_USER_IDS}")
