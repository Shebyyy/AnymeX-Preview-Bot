# ══════════════════════════════════════════════════════════════════════════════
# faq_trigger.py  —  !faqN prefix command + reply tagging
# ══════════════════════════════════════════════════════════════════════════════
# Usage:
#   !faq1          → sends FAQ #1 embed in the current channel
#   !faq12         → sends FAQ #12 embed in the current channel
#   (reply to a msg) !faq5  → sends FAQ #5 embed AND pings the replied-to user
#
# The FAQ data is loaded by bot.py from GitHub and passed in via setup().
# ══════════════════════════════════════════════════════════════════════════════

import re
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

FAQ_COLOR = 0x6A5ACD

# ─────────────────────────────────────────────────────────────────────────────
# State (populated by bot.py via setup)
# ─────────────────────────────────────────────────────────────────────────────

_faq_entries: dict[int, dict] = {}  # {1: {title, description}, 2: {...}, ...}
_bot = None


def get_faq_entries() -> dict[int, dict]:
    """Return the current FAQ map (used by bot.py for slash command autocomplete)."""
    return _faq_entries


def set_faq_entries(entries: dict[int, dict]) -> None:
    """Update the FAQ map (called by bot.py after loading from GitHub)."""
    global _faq_entries
    _faq_entries = entries


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

    faq_num = int(match.group(1))
    faq = _faq_entries.get(faq_num)

    if not faq:
        max_id = max(_faq_entries.keys(), default=0)
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


def setup(bot: discord.Client):
    global _bot
    _bot = bot

    @bot.listen("on_message")
    async def on_message_faq(message: discord.Message):
        await _handle(message)

    max_id = max(_faq_entries.keys(), default=0)
    print(f"✅ faq_trigger loaded — {len(_faq_entries)} entries (1–{max_id}), prefix: !faqN")
