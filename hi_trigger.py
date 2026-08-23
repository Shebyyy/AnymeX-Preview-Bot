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

# Max message length to check (longer messages → ai_trigger handles)
AI_MAX_LENGTH = 50

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
    "openai",  # GPT-OSS 20B reasoning
]

# OpenRouter free models (needs OPENROUTER_API_KEY)
OPENROUTER_MODELS = [
    # Big smart text models
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    # Google
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    # Vision models (also handle text fine)
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    # Thinking/reasoning models
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    # GLM
    "z-ai/glm-5.2:free",
    # Dots
    "dots-studio/dots-3-note-preview:free",
    # Small / niche
    "liquid/lfm-2.5-2.6b:free",
    # Code models (still smart enough for this)
    "cohere/north-mini-code:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
]


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Simple regex fast path (instant, no API call)
# ─────────────────────────────────────────────────────────────────────────────

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
# Layer 2: Race ALL free AI models in parallel
# ─────────────────────────────────────────────────────────────────────────────

_AI_PROMPT = """You are a visual text pattern detector for a Discord bot.

Your job: determine if the given text is a creative/trick way of writing "hi" or a greeting.

People bypass "hi" detection using visual tricks. REASON about what the text LOOKS LIKE visually:
- ASCII art: "|-|" looks like H, so "|-| |" = Hi
- Pipe as i: "H|" = Hi, lone "|" = i
- Slash as i: "/" resembles i, "|-|/" = Hi
- Exclamation as i: "H!" = Hi
- L33tspeak: "1" = i, "H1" = Hi
- Unicode lookalikes, fullwidth, decorated, Zalgo, Braille, Morse, binary

YES examples: "|-| |", "H|", "H!", "H1", "|-|/", "🐀🇮"
NO examples: "high", "hiring", "hint", "this", "child", "hiiiiiiiiii" (6+ i's)

Reply only "yes" or "no"."""


_TRICK_CHARS = set("|!/-\\[]{}<>~`@#$%^&*()_+=:;'\"" + "1")


def _is_suspicious(text: str) -> bool:
    return any(c in _TRICK_CHARS for c in text.strip())


def _should_ask_ai(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > AI_MAX_LENGTH:
        return False
    if stripped.startswith("```"):
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
