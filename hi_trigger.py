# ══════════════════════════════════════════════════════════════════════════════
# hi_trigger.py  —  Auto-reply when someone says "Hi" (AI-only, no manual maps)
# ══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   Layer 1: Simple regex fast path (plain hi, Hi, HI, hii, 𝐇𝐢, Ｈｉ)
#   Layer 2: Race ALL free AI models in parallel — first "yes" wins
#
# AI sources (all FREE):
#   - Pollinations: openai (GPT-OSS 20B) — no API key needed
#   - OpenRouter: 18 free models — uses OPENROUTER_API_KEY env var
#
# No manual Unicode/ASCII art maps. The AI reasons about visual patterns.
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import asyncio
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

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Max message length to check
AI_MAX_LENGTH = 2000

# ── OpenRouter ──
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Pollinations (no key needed) ──
POLLINATIONS_API_URL = "https://text.pollinations.ai/openai/chat/completions"

# ═══════════════════════════════════════════════════════════════════════════════
# ALL free models — every single one, fired in parallel
# ═══════════════════════════════════════════════════════════════════════════════

# Pollinations free models (no API key)
POLLINATIONS_MODELS = [
    "openai-fast",
    "openai",
]

# OpenRouter free models (needs OPENROUTER_API_KEY)
OPENROUTER_MODELS = [
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "z-ai/glm-5.2:free",
    "minimax/minimax-m3:free",
    "liquid/lfm-2.5-2.6b:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
    "cohere/north-mini-code:free",
]


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Universal Visual Geometry & Multi-Line ASCII Engine (<0.1ms)
# ─────────────────────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Normalize text and unwrap markdown codeblocks, spoilers, and formatting."""
    s = text.strip()
    changed = True
    while changed:
        old = s
        if s.startswith("```") and s.endswith("```") and len(s) >= 6:
            s = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", s)
            s = re.sub(r"\n?```$", "", s).strip()
        if s.startswith("`") and s.endswith("`") and len(s) >= 2:
            s = s[1:-1].strip()
        if s.startswith("||") and s.endswith("||") and len(s) >= 4:
            s = s[2:-2].strip()
        if "\n" not in s:
            if s.startswith("**") and s.endswith("**") and len(s) >= 4:
                s = s[2:-2].strip()
            if s.startswith("*") and s.endswith("*") and len(s) >= 2:
                s = s[1:-1].strip()
            if s.startswith("~~") and s.endswith("~~") and len(s) >= 4:
                s = s[2:-2].strip()
        changed = (s != old)

    # Unicode NFKC normalization
    return unicodedata.normalize("NFKC", s)


def _is_multiline_ascii_hi(text: str) -> bool:
    """Detects multi-line ASCII art drawings of H / Hi across multiple lines."""
    cleaned = _clean_text(text)
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    # Check if there are English words (3+ letters) that are NOT greeting words
    words = re.findall(r"[a-zA-Z]{3,}", cleaned)
    greeting_words = {"hey", "hello", "hola", "sup", "whatsup", "wassup", "greetings"}
    non_greeting_words = [w for w in words if w.lower() not in greeting_words and not all(c in "hHiI" for c in w)]
    if non_greeting_words:
        return False

    # Upright column character: |, I, l, 1, !, #, [, ], (, ), \, /, *, +, H, X, x, :, ;, o, O
    col_char = r"[\|Il1!#\[\]\(\)\\/XxHh\*\+\:\;oO]"
    bridge_char = r"[\-_–—=+*~.]"

    uprights_line = re.compile(rf"{col_char}+\s{{2,}}{col_char}+")
    bridge_line = re.compile(rf"{bridge_char}{{2,}}")

    has_bridge = any(bridge_line.search(l) for l in lines)
    has_uprights = sum(1 for l in lines if uprights_line.search(l)) >= 2

    return has_bridge and has_uprights


def _is_single_line_hi(text: str) -> bool:
    """Detects single-line visual tricks: I-Ii, }-{i, 1-1i, |-|, closures, lookalikes."""
    s = _clean_text(text)
    if "\n" in s:
        return False

    # Upright stroke / bracket character for building visual H
    upright = r"[\|Il1!\{\}\[\]\(\)\<\>\\\/]"

    # H element: standard H, Cyrillic/Greek, closures (}{, ][, )(, ><),
    # and any pair of uprights with a horizontal bridge (I-I, }-{, 1-1, |-|, [-], (-), <->, etc.)
    h_element = (
        r"(?:"
        r"[hH]"
        r"|[НнΗηɥ#卄♓𐌷⠓]"
        r"|(?:\}{"
        r"|\]\["
        r"|\)\("
        r"|\(\)"
        r"|><"
        rf"|{upright}[\s\-_–—=\~\*\+\.:\^v/]+{upright}"
        r"))"
    )

    sep = r"[\s\-_–—=\~\*\+\.:\^v,\'\"`\\/]*"

    # I element: i, I, 1, !, |, /, \, ;, lookalikes, emojis
    i_element = (
        r"(?:"
        r"[iI1!\|¡¦│┃\/\\;ℹⓘⒾ🄸🅘🇮𐌹⠊іІЇїιΙ]"
        r"|l(?![a-zA-Z])"
        r")"
    )

    trailing = r"(?:[\s!?.,~:;\-_+*^/\'\"`\(\)\[\]\{\}👋🤝😊✨\u200b-\u200f])*"

    hi_pattern = rf"^{h_element}{sep}{i_element}+(?:{sep}{i_element})*{trailing}$"
    if re.fullmatch(hi_pattern, s):
        return True

    greeting_pattern = (
        r"^(?:"
        r"h[e3][y]+"
        r"|h[e3]ll?[o0]+"
        r"|h[o0]la"
        r"|s[u|]p"
        r"|y[o0]+"
        r"|namaste"
        r"|wass?up"
        r"|whatsup"
        r"|wsp"
        r"|greetings"
        r")$"
    )
    clean_greeting = re.sub(r"[\s\-_–—=\~\*\+\.:\^v,\'\"`\\/]+", "", s).lower()
    if re.fullmatch(greeting_pattern, clean_greeting):
        return True

    return False


def _is_visual_greeting(text: str) -> bool:
    """Master Layer 1 check: handles single-line tricks and multi-line ASCII art."""
    return _is_single_line_hi(text) or _is_multiline_ascii_hi(text)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: Race ALL free AI models in parallel
# ─────────────────────────────────────────────────────────────────────────────

_AI_PROMPT = """You are an expert visual text pattern and ASCII art detector for a Discord bot.

Your job: determine if the given text is a creative, trick, or visual way of writing "hi" or a greeting.

IMPORTANT RULES for visual reasoning:
- People bypass filters using visual ASCII art and leetspeak.
- Two upright strokes with a crossbar represent "H": e.g., "1-1", "I-I", "}-{\", \"|-|\", \"]-[\", \"(-)\".
  DO NOT interpret \"1-1\" as math or subtraction! In this context, it is visual art for the letter H.
- A single upright, digit, or punctuation represents "i": e.g., "i", "1", "!", "|".
- Combinations like \"1-1i\", \"I-Ii\", \"}-{i\", \"|-|i\", \"1-11\", \"1-1!\" are visual art for \"Hi\".
- Multi-line ASCII art: Drawing "H" and "I" across multiple lines with spaces and pipes/dashes is "Hi".
- Greetings: hi, hey, hello, sup, yo, hola, namaste in any spelling, casing, leetspeak, or decoration.

YES examples: \"|-| |\", \"H|\", \"H!\", \"H1\", \"|-|/\", \"I-Ii\", \"}-{i\", \"1-1i\", \"🐀🇮\"
NO examples: \"high\", \"hiring\", \"hint\", \"this\", \"child\", \"1+1=2\", \"hiiiiiiiiii\" (6+ i's)

Reply only \"yes\" or \"no\"."""


_TRICK_CHARS = set("|!/-\\[]{}<>~`@#$%^&*()_+=:;'\"" + "1\n")


def _is_suspicious(text: str) -> bool:
    return any(c in _TRICK_CHARS for c in text.strip())


def _should_ask_ai(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > AI_MAX_LENGTH:
        return False
    if re.match(r"^https?://\S+$", stripped):
        return False
    if stripped.isascii() and not _is_suspicious(stripped):
        return False
    return True


def _extract_suspicious_words(text: str) -> list[str]:
    words = text.split()
    results = []
    for i, w in enumerate(words):
        if not _is_suspicious(w):
            continue
        if len(w) <= AI_MAX_LENGTH:
            results.append(w)
        if i < len(words) - 1:
            pair = w + " " + words[i + 1]
            if len(pair) <= AI_MAX_LENGTH:
                results.append(pair)
        if i > 0:
            pair = words[i - 1] + " " + w
            if len(pair) <= AI_MAX_LENGTH:
                results.append(pair)
    return results


# ── Per-model API call ──

async def _ask_openrouter_model(session: aiohttp.ClientSession, model: str, text: str) -> bool:
    """Ask one OpenRouter model. Returns True if "yes"."""
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _AI_PROMPT},
                {"role": "user", "content": text},
            ],
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
                print(f"  [hi] {model}: rate limited")
                return False
            if resp.status != 200:
                return False
            data = await resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()
            if reply.startswith("yes"):
                print(f"  [hi] ✅ {model}: YES → \"{text[:40]}\"")
                return True
            print(f"  [hi]    {model}: no → \"{text[:40]}\"")
            return False
    except asyncio.CancelledError:
        raise  # Don't swallow cancellation
    except Exception as e:
        print(f"  [hi]    {model}: error ({type(e).__name__})")
        return False


async def _ask_pollinations_model(session: aiohttp.ClientSession, model: str, text: str) -> bool:
    """Ask one Pollinations model. Returns True if "yes"."""
    try:
        payload = {
            "model": model,
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
                print(f"  [hi] pollinations/{model}: HTTP {resp.status}")
                return False
            data = await resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()
            if reply.startswith("yes"):
                print(f"  [hi] ✅ pollinations/{model}: YES → \"{text[:40]}\"")
                return True
            print(f"  [hi]    pollinations/{model}: no → \"{text[:40]}\"")
            return False
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"  [hi]    pollinations/{model}: error ({type(e).__name__})")
        return False


async def _race_all_models(text: str) -> bool:
    """Fire ALL free models in parallel. Return True on first YES.

    Uses asyncio.as_completed so we don't wait for slow models —
    as soon as any model says "yes", we return True immediately.
    """
    print(f"[hi_trigger] Racing all models for: \"{text[:50]}\"")

    tasks = []

    # Build all tasks
    async with aiohttp.ClientSession() as session:
        # Pollinations models (no API key)
        for model in POLLINATIONS_MODELS:
            tasks.append(asyncio.create_task(
                _ask_pollinations_model(session, model, text),
                name=f"pollinations/{model}",
            ))

        # OpenRouter models (needs API key)
        if OPENROUTER_API_KEY:
            for model in OPENROUTER_MODELS:
                tasks.append(asyncio.create_task(
                    _ask_openrouter_model(session, model, text),
                    name=f"openrouter/{model}",
                ))
        else:
            print("[hi_trigger] No OPENROUTER_API_KEY — skipping 18 OpenRouter models")

        if not tasks:
            print("[hi_trigger] No AI models available at all!")
            return False

        # Process results as they arrive — first YES wins
        try:
            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result:
                    # Cancel remaining tasks — we got our answer
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    # Wait for cancellations to finish (ignore errors)
                    await asyncio.gather(*tasks, return_exceptions=True)
                    return True
        except Exception:
            pass

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

_bot = None


async def _trigger(message: discord.Message):
    """Fire the reply — shared by both layers."""
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
                        print(f"[hi_trigger] Sent via webhook ✅")
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

    # ── Layer 1: Universal Visual Geometry & Multi-Line ASCII Engine (<0.1ms) ──
    # 1. Check whole message (handles multi-line ASCII art and single-line trick phrases)
    if _is_visual_greeting(stripped):
        await _trigger(message)
        return

    # 2. If multi-line, check individual lines (e.g. greeting on a single line of text)
    if "\n" in stripped:
        for line in stripped.splitlines():
            s_line = line.strip()
            if s_line and _is_visual_greeting(s_line):
                await _trigger(message)
                return

    # ── Build segments to check ──
    if len(stripped) <= AI_MAX_LENGTH:
        segments = [stripped]
    else:
        segments = _extract_suspicious_words(text)

    # ── Check each segment ──
    for seg in segments:
        # Layer 1 check on segment
        if _is_visual_greeting(seg):
            await _trigger(message)
            return

        # Layer 2: Race ALL AI models in parallel
        if _should_ask_ai(seg) and await _race_all_models(seg):
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

    total = len(POLLINATIONS_MODELS) + (len(OPENROUTER_MODELS) if OPENROUTER_API_KEY else 0)
    print(f"✅ hi_trigger loaded — regex + {total} AI models in parallel — watching {TARGET_USER_IDS}")
