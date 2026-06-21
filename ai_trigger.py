# ══════════════════════════════════════════════════════════════════════════════
# ai_trigger.py  —  AI-powered greeting detector (Layer 2)
# ══════════════════════════════════════════════════════════════════════════════
#
# This runs AFTER hi_trigger.py (Layer 1). If the pattern-based detector
# didn't catch the message, this sends it to AI to check intent.
#
# Catches: "hey", "hello", "sup", "yo", "hola", "namaste", emoji greetings,
#          creative spellings, slang, and any greeting that isn't "hi"
# Does NOT trigger on: normal conversation, questions, statements
#
# Uses Groq API (free, ~0.1-0.3s response time)
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TARGET_USER_IDS    = {1331083395614380090, 1400504783097561098}
REPLY_MESSAGE      = "Single yet? <:hmmm:1497190580344586422>"
WEBHOOK_USERNAME   = "𝕾𝖍𝖊𝖇𝖞 D. ツ"
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/avatars/612532963938271232/cf5d3f43c29516523531f21b09d4a743.png?size=1024"

# Groq API config
GROQ_API_KEY  = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.1-8b-instant"  # Fast + free tier friendly

# Pre-check filters (avoid wasting API calls)
MAX_WORDS     = 6      # Greetings are short — skip long messages
MIN_LENGTH    = 1      # Skip empty messages
MAX_LENGTH    = 40     # Skip very long messages

# Track recently caught message IDs to avoid double-firing with hi_trigger
_caught_by_hi: set[int] = set()

# System prompt for the AI
SYSTEM_PROMPT = """You are a greeting detector. Your ONLY job is to determine if the user's message is a greeting or saying hi.

A greeting includes:
- Direct greetings: hi, hey, hello, sup, yo, howdy, heya, hiya, yo, yoo
- Other languages: hola, bonjour, namaste, ciao, konnichiwa, salaam, salut, aloha, privyet, merhaba, jambo, olá, hallo, hei, hej, czesc, ahoy
- Slang/informal: wassup, what's up, whats good, how's it going, watcha, yooo, heyyyy
- Emoji-based greetings: 👋, 🙏, 🤝, 🫡 (when used as a standalone greeting)
- Creative/trick greetings: any misspelling, l33tspeak, or deliberate trick to say hi (h1, h3y, h3llo, h3llo0, y0, h3y, etc.)
- Single letter or symbol combos that represent hi

NOT a greeting:
- Normal conversation, questions, statements
- Words that happen to start with h (high, hiring, hint, history, help, here, how, have)
- Partial words or abbreviations that aren't greetings
- Code, URLs, or technical content

Reply ONLY one word: "yes" or "no" """

# ─────────────────────────────────────────────────────────────────────────────
# Quick pre-filter (skip obviously not-greetings without API call)
# ─────────────────────────────────────────────────────────────────────────────

# Common words that are definitely NOT greetings — skip AI call entirely
_DEF_NOT_GREETING = re.compile(
    r'^(?:'
    r'the|and|but|for|not|you|all|can|had|her|was|one|our|out|day|get|has|him|his|how|its|'
    r'may|new|now|old|see|way|who|did|let|say|she|too|use|ok|yes|no|yeah|nah|bruh|bro|'
    r'dude|man|like|just|know|think|feel|want|need|going|doing|making|saying|try|wait|'
    r'stop|look|come|give|tell|work|call|good|bad|cool|nice|great|fine|right|sure|well|'
    r'still|again|also|back|here|there|where|when|what|which|why|will|would|should|could|'
    r'thanks|thank|sorry|please|maybe|really|very|much|more|most|some|any|every|never|'
    r'always|already|before|after|since|because|though|through|between|about|above|below|'
    r'lol|lmao|wtf|omg|brb|afk|smh|ngl|fr|tbh|imo|idk|icymi|fyi|aka|rn|btw|atp'
    r')(?:\s|$)',
    re.IGNORECASE
)


def _should_check_ai(text: str) -> bool:
    """Quick filter — return True if message MIGHT be a greeting."""
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) < MIN_LENGTH or len(stripped) > MAX_LENGTH:
        return False
    if len(stripped.split()) > MAX_WORDS:
        return False
    # Skip code blocks
    if stripped.startswith('```') or stripped.startswith('`'):
        return False
    # Skip URLs
    if 'http://' in stripped or 'https://' in stripped:
        return False
    # Skip messages that are clearly not greetings
    if _DEF_NOT_GREETING.match(stripped):
        return False
    # Must have at least one letter or emoji
    if not re.search(r'[\w\u2600-\u27BF\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0]', stripped):
        return False
    return True


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
                timeout=aiohttp.ClientTimeout(total=3),  # Fast timeout
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[ai_trigger] Groq HTTP {resp.status}: {body[:200]}")
                    return False

                data = await resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()

                if reply.startswith("yes"):
                    print(f"[ai_trigger] AI detected greeting: \"{text}\" → {reply}")
                    return True
                return False

    except aiohttp.ClientTimeout:
        print(f"[ai_trigger] Groq timeout for: \"{text}\"")
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

    # Quick pre-filter
    if not _should_check_ai(message.content):
        return

    # Ask AI
    is_greeting = await _ask_ai(message.content)

    if not is_greeting:
        return

    print(f"[ai_trigger] Triggered by {message.author} in #{message.channel}")

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
                        print(f"[ai_trigger] Sent via webhook with profile + mention ✅")
                    else:
                        body = await resp.text()
                        print(f"[ai_trigger] Webhook HTTP {resp.status}: {body[:200]} — falling back")
                        await message.reply(REPLY_MESSAGE, mention_author=True)
        else:
            await message.reply(REPLY_MESSAGE, mention_author=True)
            print(f"[ai_trigger] Replied via normal reply ✅")
    except Exception as e:
        print(f"[ai_trigger] Error: {e}")
        try:
            await message.reply(REPLY_MESSAGE, mention_author=True)
        except Exception as e2:
            print(f"[ai_trigger] Fallback also failed: {e2}")


async def _get_or_create_webhook(channel: discord.TextChannel):
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.user and wh.user.id == _bot.user.id and wh.name == "AiTrigger":
                return wh
        return await channel.create_webhook(name="AiTrigger")
    except Exception as e:
        print(f"[ai_trigger] Webhook error: {e}")
        return None


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
