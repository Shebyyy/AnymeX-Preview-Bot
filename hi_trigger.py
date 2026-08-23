# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (Vision AI, no manual maps)
# ══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   Layer 1: Simple regex fast path (plain hi, Hi, HI, hii, etc.)
#   Layer 2: Vision AI — render text as MONOSPACE image → VLM literally sees tricks
#
# No manual Unicode maps. Covers:
#   - Plain hi, Hi, 𝐇𝐢, Ｈｉ (NFKC normalization)
#   - Visual tricks: H|, H!, H1, |-| |, |-|/
#   - Unicode lookalikes: Ƕi, Ħ|, Ні (vision model sees the shape)
#   - ASCII art, upside-down, reversed, Zalgo, invisible char combos
#   - Tricks hidden in longer sentences: "check this |-| | out"
#
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

# Max length to send full message to vision directly
VISION_DIRECT_MAX = 50
# Max length per segment when scanning longer messages
VISION_SEGMENT_MAX = 20

# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Simple regex fast path (instant, no API call)
# ─────────────────────────────────────────────────────────────────────────────
# NFKC normalization handles most Unicode equivalents (𝐇𝐢 → Hi, Ｈｉ → Hi, etc.)
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
# Layer 2: Render text as image → Vision AI
# ─────────────────────────────────────────────────────────────────────────────

_VISION_PROMPT = """Look at this image. Does the text in it visually look like the word "hi" or any greeting?

You are a visual pattern detector. Ignore Unicode values — only look at SHAPES.

Recognize these visual trick patterns:
- Pipe as i: "H|" looks like "Hi", lone "|" can be i
- Slash as i: "/" can resemble i, so "|-|/" looks like "Hi"
- Exclamation as i: "H!" looks like "Hi"
- ASCII art H: "|-|" looks like "H", so "|-| |" looks like "Hi"
- Any combination of vertical lines, dashes, slashes that form letter shapes resembling h+i
- L33tspeak: "H1" where 1 = i
- Upside-down, mirrored, or Zalgo-decorated text that still reads as "hi"
- Mixed scripts where characters visually resemble Latin h and i

Only say "yes" if it VISUALLY RESEMBLES "hi" or a greeting word.
If it looks like a normal English word (high, hiring, hint) or random symbols with no recognizable hi shape, say "no".

Reply only "yes" or "no"."""


# ── Monospace font (critical for ASCII art like |-| |) ──
_MONO_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "C:\\Windows\\Fonts\\consola.ttf",
    "C:\\Windows\\Fonts\\cour.ttf",
]

_font_cache = None


def _get_mono_font(size: int = 48):
    """Get cached monospace font."""
    global _font_cache
    if _font_cache is None:
        for path in _MONO_FONT_PATHS:
            try:
                _font_cache = ImageFont.truetype(path, size)
                break
            except (IOError, OSError):
                continue
        if _font_cache is None:
            _font_cache = ImageFont.load_default()
    return _font_cache


def _render_text_as_image(text: str) -> str | None:
    """Render text as a monospace PNG image, return base64."""
    try:
        font = _get_mono_font(48)

        lines = text.split("\n")
        max_line_len = max(len(line) for line in lines) if lines else 1

        # Monospace: all chars same width, approximate
        char_w, line_h, padding = 30, 60, 20
        img_w = max(max_line_len * char_w + padding * 2, 200)
        img_h = max(len(lines) * line_h + padding * 2, 100)

        img = Image.new("RGB", (img_w, img_h), "white")
        draw = ImageDraw.Draw(img)
        draw.text((padding, padding), text, fill="black", font=font)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[hi_trigger] Render failed: {e}")
        return None


# ── Segment extraction for longer messages ──
# Characters commonly used in visual tricks (non-letter, non-digit)
_TRICK_CHARS = set("|!/-\\[]{}<>~`@#$%^&*()_+=:;'\"" + "1")  # 1 = visual i


def _is_suspicious(text: str) -> bool:
    """Check if text contains characters commonly used in visual tricks."""
    return any(c in _TRICK_CHARS for c in text.strip())


def _extract_segments(text: str) -> list[str]:
    """Extract short suspicious segments from longer messages.

    For "check this |-| | out" → ["|-|", "|", "|-| |"]
    Only segments containing trick characters are returned to avoid
    wasting vision API calls on normal words.
    """
    words = text.split()
    segments = set()

    for i, w in enumerate(words):
        if not _is_suspicious(w):
            continue

        # Single word
        if len(w) <= VISION_SEGMENT_MAX:
            segments.add(w)

        # Pair with next word
        if i < len(words) - 1 and len(w) + 1 + len(words[i + 1]) <= VISION_SEGMENT_MAX:
            segments.add(w + " " + words[i + 1])

        # Pair with previous word
        if i > 0 and len(words[i - 1]) + 1 + len(w) <= VISION_SEGMENT_MAX:
            segments.add(words[i - 1] + " " + w)

        # Triple: prev + this + next
        if (i > 0 and i < len(words) - 1
                and len(words[i - 1]) + 1 + len(w) + 1 + len(words[i + 1]) <= VISION_SEGMENT_MAX):
            segments.add(words[i - 1] + " " + w + " " + words[i + 1])

    return list(segments)


def _should_try_vision(text: str) -> bool:
    """Pre-filter: only send messages that could be visual tricks to vision.

    Skips: URLs, code blocks, empty, too-long, and pure ASCII text without
    trick characters (normal words like 'high', 'hello' are handled by ai_trigger).
    Allows: text with special chars (H|, |-| |), non-ASCII (Ƕi, Ħi), etc.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > VISION_DIRECT_MAX:
        return False
    if stripped.startswith("```"):
        return False
    if re.match(r"^https?://\S+$", stripped):
        return False
    # Skip pure ASCII text with no trick characters
    # Normal greetings (hello, hey) and false positives (high, hiring) go to ai_trigger
    if stripped.isascii() and not _is_suspicious(stripped):
        return False
    return True


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


async def _trigger(message: discord.Message):
    """Fire the reply — shared by both layers."""
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
                    "content": f"<{message.author.id}> {REPLY_MESSAGE}",
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
    if len(stripped) <= VISION_DIRECT_MAX:
        # Short message: check the whole thing
        segments = [stripped]
    else:
        # Long message: extract suspicious short segments only
        segments = _extract_segments(text)

    # ── Check each segment ──
    for seg in segments:
        # Layer 1: Instant regex
        if _is_simple_hi(seg):
            await _trigger(message)
            return

        # Layer 2: Vision AI
        if _should_try_vision(seg) and await _ask_vision_hi(seg):
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

    vision_status = "Vision AI ✅" if OPENROUTER_API_KEY else "Vision AI ❌ (no OPENROUTER_API_KEY)"
    print(f"✅ hi_trigger loaded — regex + {vision_status} — watching users {TARGET_USER_IDS}")
