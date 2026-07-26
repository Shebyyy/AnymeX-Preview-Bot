# ══════════════════════════════════════════════════════════════════════════════
# faq_trigger.py  —  !faqN prefix command + reply tagging
# ══════════════════════════════════════════════════════════════════════════════
# Usage:
#   !faq1          → sends FAQ #1 embed in the current channel
#   !faq12         → sends FAQ #12 embed in the current channel
#   (reply to a msg) !faq5  → sends FAQ #5 embed AND pings the replied-to user
#
# FAQ data is read live from bot.py's FAQ_MAP via a callback — no separate copy,
# no race condition.
# ══════════════════════════════════════════════════════════════════════════════

import re
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

FAQ_COLOR = 0x6A5ACD

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

_bot = None
_get_faq_fn = None  # set by setup() — returns the live FAQ_MAP dict


def _get_entries() -> dict[int, dict]:
    """Get the current FAQ entries dict (always fresh, no copy)."""
    if _get_faq_fn:
        return _get_faq_fn()
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Build embed
# ─────────────────────────────────────────────────────────────────────────────


def _build_faq_embed(faq_num: int, faq: dict) -> discord.Embed:
    """Build a Discord embed for a single FAQ entry."""
    embed = discord.Embed(
        title=f"❓ FAQ #{faq_num} — {faq['title']}",
        description=faq["description"],
        color=FAQ_COLOR,
    )
    embed.set_footer(text="AnymeX • Frequently Asked Questions")
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Core handler
# ─────────────────────────────────────────────────────────────────────────────

_FAQ_PREFIX_RE = re.compile(r"^!faq(\d+)$", re.IGNORECASE)


async def _handle(message: discord.Message):
    """Handle !faqN prefix commands."""
    if message.author.bot:
        return

    match = _FAQ_PREFIX_RE.match(message.content.strip())
    if not match:
        return

    entries = _get_entries()
    faq_num = int(match.group(1))
    faq = entries.get(faq_num)

    if not faq:
        max_id = max(entries.keys(), default=0)
        if max_id == 0:
            await message.channel.send(
                "⚠️ FAQ data hasn't loaded yet. Try again in a few seconds.",
                delete_after=8,
            )
        else:
            await message.channel.send(
                f"⚠️ FAQ **#{faq_num}** not found. Valid range: 1–{max_id}.",
                delete_after=8,
            )
        return

    embed = _build_faq_embed(faq_num, faq)

    if message.reference is not None:
        # Reply mode — ping the author of the original message
        try:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            await ref_msg.reply(embed=embed, mention_author=True)
        except discord.HTTPException:
            await message.channel.send(embed=embed)
    else:
        # Normal mode — just send the embed
        await message.channel.send(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────


def setup(bot: discord.Client, get_faq_fn=None):
    """
    Register the !faqN listener.

    Args:
        bot: The discord client.
        get_faq_fn: Callable that returns the live FAQ dict (bot.FAQ_MAP).
                   This avoids maintaining a separate copy and eliminates race conditions.
    """
    global _bot, _get_faq_fn
    _bot = bot
    if get_faq_fn:
        _get_faq_fn = get_faq_fn

    @bot.listen("on_message")
    async def on_message_faq(message: discord.Message):
        await _handle(message)

    print("✅ faq_trigger loaded — prefix: !faqN (reads live from FAQ_MAP)")
