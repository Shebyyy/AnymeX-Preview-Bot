# ══════════════════════════════════════════════════════════════════════════════
# source_trigger.py  —  Fully AI-powered guide link responder + manual commands
# ══════════════════════════════════════════════════════════════════════════════
#
# Uses AI (Pollinations, free, no key) to READ each message and decide which
# AnymeX guide link to send:
#
#   setup    → https://anymex-extensions.vercel.app/guide
#   download → https://anymex-extensions.vercel.app/download-guide
#   both     → send both links
#   none     → stay silent
#
# The AI reads the FULL message and classifies intent. Only a tiny junk filter
# runs before the AI (skip bots, pure links, code blocks) to avoid wasting calls.
#
# ── Manual commands (anyone can use, must be a reply) ──
#   !setup     → reply to the referenced message with the Setup Guide
#   !download  → reply to the referenced message with the Download Guide
#   !both      → reply to the referenced message with both guides
# The command message is auto-deleted to keep chat clean.
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import time
import asyncio
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

GUIDE_URL        = "https://anymex-extensions.vercel.app/guide"
DOWNLOAD_URL     = "https://anymex-extensions.vercel.app/download-guide"

# Only reply in this channel (set to None to reply everywhere)
ALLOWED_CHANNEL_ID = 1497202485469773947  # #support/help (new server)

# Cooldown per channel (seconds) — prevents spam
COOLDOWN_SECONDS = 30

# Roles that should NOT receive the guide link
EXCLUDED_ROLE_IDS = {
    1497202483519553634,  # Owner
    1497202483519553633,  # Admin
    1497202483519553632,  # Moderator
    1497202483519553631,  # Nub dev
}

# Users that should NOT receive the guide link
EXCLUDED_USER_IDS = {
    826730448688250890,   # bakabakaidiot
    1331083395614380090,  # devta.exe
}

# ── Manual commands config ──
# Anyone can use these by replying to a user's message.
# The command message is auto-deleted to keep chat clean.
MANUAL_PREFIX = "!"
# Map: command (lowercase, without prefix) → classification
MANUAL_COMMANDS = {
    "setup":    "setup",
    "download": "download",
    "both":     "both",
}

# ── Pollinations API (text — FREE, no key needed!) ──
POLLINATIONS_API_URL = "https://text.pollinations.ai/openai/chat/completions"
POLLINATIONS_MODEL   = "openai"  # GPT-OSS 20B reasoning model

# Browser User-Agent — Pollinations 403s without it now!
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ─────────────────────────────────────────────────────────────────────────────
# Minimal junk filter — only skips obvious non-messages so the AI doesn't waste
# calls on bots, pure links, code blocks, etc. The AI handles everything else.
# ─────────────────────────────────────────────────────────────────────────────

# Pre-filter limits
_MIN_LENGTH = 3
_MAX_WORDS  = 100  # generous — let the AI see longer help requests too

# ─────────────────────────────────────────────────────────────────────────────
# AI Prompt — tells the model exactly what each guide covers (and what they don't)
# ─────────────────────────────────────────────────────────────────────────────

AI_PROMPT = """You are a helpful assistant for the AnymeX anime/manga app community on Discord.

AnymeX has exactly TWO guides. Your job is to read a user's message and decide which guide link to send them.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📖 SETUP GUIDE  →  https://anymex-extensions.vercel.app/guide
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers:
- How to install the AnymeX app (Android, iOS, Windows, macOS, Linux)
- Windows prerequisites & Runtime Bridge Plugin
- How to add extension repositories (repos)
- How to browse and install extensions
- How to use an installed extension to watch/read anime & manga
Reply "setup" when someone is:
- Setting up AnymeX for the first time
- Trying to install the app or a plugin
- Adding repos or extension repositories
- Installing / browsing / finding extensions
- Saying extensions don't show up, can't install extensions
- Asking where to get sources/extensions
- Asking how to watch or read anime/manga in AnymeX (general use)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📥 DOWNLOAD GUIDE  →  https://anymex-extensions.vercel.app/download-guide
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers:
- How to DOWNLOAD anime & manga for offline use
- Download permissions (notifications, background run, unrestricted usage)
- Selecting a download folder
- Searching content, selecting a source/extension for download
- Selecting episodes or chapters
- Choosing download quality (1080p, 720p, 480p, 360p)
- Viewing the download queue and downloaded media
Reply "download" when someone is:
- Trying to download anime/manga episodes or chapters (offline)
- Having issues with downloads (pausing, stopping, failing, not starting)
- Asking about download permissions, background downloads, battery optimization
- Asking where downloads are saved / can't find downloaded files
- Asking about download quality or selecting episodes for download

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOT COVERED BY EITHER GUIDE (reply "none" for these)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
These topics are NOT in either guide, so reply "none":
- App UI / browsing experience (recommendations, categories, scrolling, infinite scroll, how content is displayed)
- Discovery / search results count / how many results show up
- App features / settings / account / profile questions
- General anime/manga recommendations (not about the AnymeX app itself)
- Comparisons with other apps (Mihon, Aniyomi, etc.) unless clearly asking how to set up AnymeX
- Bug reports about app behavior that aren't setup/download related
- Casual chat, greetings, thanks, opinions
- "source code" or "open source" mentions (not about AnymeX sources)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ONLY respond to messages asking for HELP or reporting a PROBLEM that a guide actually covers.
- When in doubt about whether a guide covers the topic, reply "none" — it's better to stay silent than send an irrelevant link.
- If the message is about BOTH setup AND downloading → reply "both".
- If it's clearly about one guide → reply "setup" or "download".
- If it's not asking for help, not about AnymeX, about a topic not covered above, or too vague to tell → reply "none".

Reply with ONLY ONE WORD: setup, download, both, or none."""


# ─────────────────────────────────────────────────────────────────────────────
# AI call (Pollinations — free, no key)
# ─────────────────────────────────────────────────────────────────────────────

async def _classify_message(text: str) -> str:
    """Ask the AI which guide to send. Returns 'setup', 'download', 'both', or 'none'."""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": POLLINATIONS_MODEL,
                "messages": [
                    {"role": "system", "content": AI_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 10,
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
                    print(f"[source_trigger] Pollinations HTTP {resp.status}: {body[:200]}")
                    return "none"

                data = await resp.json()
                reply = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                    .lower()
                )

                # Normalize — pick the first matching keyword
                for keyword in ("setup", "download", "both", "none"):
                    if keyword in reply:
                        print(f"[source_trigger] AI classified: {keyword!r} (raw: {reply!r})")
                        return keyword

                print(f"[source_trigger] AI reply not understood: {reply!r}")
                return "none"

    except asyncio.TimeoutError:
        print(f"[source_trigger] Pollinations timeout")
        return "none"
    except Exception as e:
        print(f"[source_trigger] Pollinations error: {e}")
        return "none"


# ─────────────────────────────────────────────────────────────────────────────
# Build the reply message for a given classification
# ─────────────────────────────────────────────────────────────────────────────

def _build_reply(classification: str) -> str | None:
    """Return the reply string, or None if we shouldn't reply."""
    if classification == "setup":
        return (
            f"📖 **Setup Guide**\n"
            f"Click this link to learn how to read/watch:\n"
            f"<{GUIDE_URL}>"
        )
    if classification == "download":
        return (
            f"📥 **Download Guide**\n"
            f"How to download anime & manga:\n"
            f"<{DOWNLOAD_URL}>"
        )
    if classification == "both":
        return (
            f"📖 **Guides** — these should help:\n"
            f"• **Setup** — Click this link to learn how to read/watch:\n"
            f"  <{GUIDE_URL}>\n"
            f"• **Download** — how to download anime & manga:\n"
            f"  <{DOWNLOAD_URL}>"
        )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Cooldown tracker
# ─────────────────────────────────────────────────────────────────────────────

_last_triggered: dict[int, float] = {}  # channel_id → timestamp


def _is_on_cooldown(channel_id: int) -> bool:
    now = time.time()
    last = _last_triggered.get(channel_id, 0)
    if now - last < COOLDOWN_SECONDS:
        return True
    _last_triggered[channel_id] = now
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

_bot = None


async def _handle(message: discord.Message):
    if message.author.bot:
        return

    # Skip excluded users
    if message.author.id in EXCLUDED_USER_IDS:
        return

    # Skip users with excluded roles (guild only)
    if hasattr(message.author, "roles"):
        if any(role.id in EXCLUDED_ROLE_IDS for role in message.author.roles):
            return

    # Only reply in the allowed channel
    if ALLOWED_CHANNEL_ID and message.channel.id != ALLOWED_CHANNEL_ID:
        return

    content = message.content
    if not content or len(content) < _MIN_LENGTH:
        return

    # Skip pure links (nothing to classify)
    if re.match(r'^https?://\S+$', content.strip()):
        return

    # Skip code blocks
    stripped = content.strip()
    if stripped.startswith('```') and stripped.endswith('```'):
        return

    # Skip very long messages (likely not a quick help request)
    if len(content.split()) > _MAX_WORDS:
        return

    # Ask the AI which guide to send (AI reads the FULL message)
    classification = await _classify_message(content)
    if classification == "none":
        return

    # Build the reply
    reply = _build_reply(classification)
    if not reply:
        return

    # Cooldown check (per channel)
    if _is_on_cooldown(message.channel.id):
        print(f"[source_trigger] On cooldown in #{message.channel}, skipping")
        return

    print(
        f"[source_trigger] Triggered by {message.author} in #{message.channel}: "
        f"classified as {classification!r}"
    )

    try:
        await message.reply(reply, mention_author=False)
        print(f"[source_trigger] Sent {classification} guide link ✅")
    except Exception as e:
        print(f"[source_trigger] Failed to reply: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Manual commands (!setup / !download / !both — must be a reply)
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_manual(message: discord.Message) -> bool:
    """Handle manual guide commands. Returns True if the message was a manual
    command (so the caller can skip the AI path).

    Usage: reply to a user's message with  !setup  /  !download  /  !both
    The command message is auto-deleted; the bot replies to the referenced
    message with the appropriate guide link.
    """
    if message.author.bot:
        return False

    content = message.content.strip()
    if not content:
        return False

    # Must start with the manual prefix
    if not content.startswith(MANUAL_PREFIX):
        return False

    # Strip prefix, take the first word, lowercase it
    rest = content[len(MANUAL_PREFIX):].strip()
    if not rest:
        return False
    first_word = rest.split()[0].lower()

    # Is it a known manual command?
    classification = MANUAL_COMMANDS.get(first_word)
    if classification is None:
        return False

    # ── It's a manual command — handle it ──
    print(f"[source_trigger] Manual !{first_word} by {message.author} in #{message.channel}")

    # Must be a reply to another message
    if message.reference is None or message.reference.message_id is None:
        try:
            await message.reply(
                f"ℹ️ Reply to a user's message with `!{first_word}` to send them the guide.",
                mention_author=False,
            )
        except Exception:
            pass
        # Still try to delete the command
        try:
            await message.delete()
        except Exception as e:
            print(f"[source_trigger] Failed to delete command (no-ref): {e}")
        return True

    # Fetch the referenced (original) message
    try:
        ref_message = await message.channel.fetch_message(message.reference.message_id)
    except Exception as e:
        print(f"[source_trigger] Failed to fetch referenced message: {e}")
        try:
            await message.delete()
        except Exception:
            pass
        return True

    if ref_message is None:
        try:
            await message.delete()
        except Exception:
            pass
        return True

    # Don't reply to bots (would be weird)
    if ref_message.author.bot:
        try:
            await message.delete()
        except Exception:
            pass
        return True

    # Build the reply
    reply = _build_reply(classification)
    if not reply:
        try:
            await message.delete()
        except Exception:
            pass
        return True

    # Delete the command message first (keep chat clean)
    try:
        await message.delete()
    except Exception as e:
        print(f"[source_trigger] Failed to delete command message: {e}")

    # Reply to the ORIGINAL user's message
    try:
        await ref_message.reply(reply, mention_author=False)
        print(
            f"[source_trigger] Manual !{first_word} → replied to "
            f"{ref_message.author} ✅"
        )
    except Exception as e:
        print(f"[source_trigger] Failed to reply manually: {e}")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

def setup(bot: discord.Client):
    global _bot
    _bot = bot

    @bot.listen("on_message")
    async def on_message_source(message: discord.Message):
        # Manual commands take priority — handle and short-circuit
        if await _handle_manual(message):
            return
        await _handle(message)

    cmds = ", ".join(f"{MANUAL_PREFIX}{c}" for c in MANUAL_COMMANDS)
    print(f"✅ source_trigger loaded — fully AI guide responder (Pollinations, free) + manual cmds: {cmds}")
