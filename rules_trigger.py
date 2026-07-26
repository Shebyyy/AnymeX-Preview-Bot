# ══════════════════════════════════════════════════════════════════════════════
# rules_trigger.py  —  !ruleN prefix command + reply tagging
# ══════════════════════════════════════════════════════════════════════════════
# Usage:
#   !rule1          → sends Rule #1 embed in the current channel
#   !rule10         → sends Rule #10 embed in the current channel
#   (reply to a msg) !rule3  → sends Rule #3 embed AND pings the replied-to user
#
# Rules data is read live from bot.py's RULES_MAP via a callback — no separate copy,
# no race condition.
# ══════════════════════════════════════════════════════════════════════════════

import re
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

RULES_COLOR = 0x01CBE6

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

_bot = None
_get_rules_fn = None  # set by setup() — returns the live RULES_MAP dict


def _get_entries() -> dict[int, dict]:
    """Get the current rules entries dict (always fresh, no copy)."""
    if _get_rules_fn:
        return _get_rules_fn()
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Build embed
# ─────────────────────────────────────────────────────────────────────────────


def _build_rule_embed(rule_num: int, rule: dict) -> discord.Embed:
    """Build a Discord embed for a single rule entry."""
    embed = discord.Embed(
        title=f"Rule #{rule_num} — {rule['title']}",
        description=rule["description"],
        color=RULES_COLOR,
    )
    embed.set_footer(text="AnymeX • Server Rules")
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Core handler
# ─────────────────────────────────────────────────────────────────────────────

_RULE_PREFIX_RE = re.compile(r"^!(?:rule|r)(\d+)$", re.IGNORECASE)


async def _handle(message: discord.Message):
    """Handle !ruleN prefix commands."""
    if message.author.bot:
        return

    match = _RULE_PREFIX_RE.match(message.content.strip())
    if not match:
        return

    entries = _get_entries()
    rule_num = int(match.group(1))
    rule = entries.get(rule_num)

    if not rule:
        max_id = max(entries.keys(), default=0)
        if max_id == 0:
            await message.channel.send(
                "⚠️ Rules data hasn't loaded yet. Try again in a few seconds.",
                delete_after=8,
            )
        else:
            await message.channel.send(
                f"⚠️ Rule **#{rule_num}** not found. Valid range: 1–{max_id}.",
                delete_after=8,
            )
        return

    embed = _build_rule_embed(rule_num, rule)

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


def setup(bot: discord.Client, get_rules_fn=None):
    """
    Register the !ruleN listener.

    Args:
        bot: The discord client.
        get_rules_fn: Callable that returns the live rules dict (bot.RULES_MAP).
    """
    global _bot, _get_rules_fn
    _bot = bot
    if get_rules_fn:
        _get_rules_fn = get_rules_fn

    @bot.listen("on_message")
    async def on_message_rules(message: discord.Message):
        await _handle(message)

    print("✅ rules_trigger loaded — prefix: !ruleN (reads live from RULES_MAP)")
