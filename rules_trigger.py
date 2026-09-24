# ══════════════════════════════════════════════════════════════════════════════
# rules_trigger.py  —  !ruleN prefix command + reply tagging
# ══════════════════════════════════════════════════════════════════════════════
# Usage:
#   !rule1          → sends Rule #1 embed in the current channel
#   !rule10         → sends Rule #10 embed in the current channel
#   (reply to a msg) !rule3  → sends Rule #3 embed AND pings the replied-to user
#   (reply to a msg) !rule4  → sends Rule #4 embed, pings user AND times them out for 12 hours
#
# Rules data is read live from bot.py's RULES_MAP via a callback — no separate copy,
# no race condition.
# ══════════════════════════════════════════════════════════════════════════════

import re
import asyncio
from datetime import timedelta
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

RULES_COLOR = 0x01CBE6
TIMEOUT_RULE_NUM = 4
TIMEOUT_DURATION = timedelta(hours=12)

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

_bot = None
_get_rules_fn = None  # set by setup() — returns the live RULES_MAP dict
_send_log_fn = None   # set by setup() — optional log sender callback


def _get_entries() -> dict[int, dict]:
    """Get the current rules entries dict (always fresh, no copy)."""
    if _get_rules_fn:
        return _get_rules_fn()
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Build embed
# ─────────────────────────────────────────────────────────────────────────────


def _build_rule_embed(
    rule_num: int,
    rule: dict,
    timed_out_member: discord.Member | None = None,
) -> discord.Embed:
    """Build a Discord embed for a single rule entry."""
    embed = discord.Embed(
        title=f"📜 Rule #{rule_num} — {rule['title']}",
        description=rule["description"],
        color=RULES_COLOR,
    )
    if timed_out_member:
        embed.add_field(
            name="⏱️ Member Timed Out",
            value=f"{timed_out_member.mention} has been timed out for **12 hours** for violating Rule #{rule_num}.",
            inline=False,
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

    timed_out_member = None

    if message.reference is not None:
        # Reply mode — ping the author of the original message
        try:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            target_user = ref_msg.author

            # Rule #4 triggers a 12h timeout for the replied-to user (if in guild and not bot/self)
            if (
                rule_num == TIMEOUT_RULE_NUM
                and message.guild is not None
                and not target_user.bot
                and target_user.id != message.author.id
            ):
                target_member = message.guild.get_member(target_user.id)
                if target_member is None:
                    try:
                        target_member = await message.guild.fetch_member(target_user.id)
                    except discord.HTTPException:
                        target_member = None

                if target_member:
                    try:
                        reason = f"Triggered by {message.author} via !r4 (Rule #{rule_num}: {rule.get('title', 'Rule violation')})"
                        await target_member.timeout(TIMEOUT_DURATION, reason=reason)
                        timed_out_member = target_member
                    except discord.Forbidden:
                        print(f"⚠️ [rules_trigger] Lacking permission to timeout {target_member} (ID: {target_member.id})")
                    except discord.HTTPException as e:
                        print(f"⚠️ [rules_trigger] Failed to timeout {target_member}: {e}")

            embed = _build_rule_embed(rule_num, rule, timed_out_member=timed_out_member)
            await ref_msg.reply(embed=embed, mention_author=True)

            if timed_out_member and _send_log_fn:
                try:
                    log_embed = discord.Embed(
                        title="⏱️ Member Timed Out (!r4)",
                        color=0x9B59B6,
                        timestamp=discord.utils.utcnow(),
                    )
                    log_embed.add_field(
                        name="Target",
                        value=f"{timed_out_member.mention} (`{timed_out_member}` / `{timed_out_member.id}`)",
                        inline=False,
                    )
                    log_embed.add_field(
                        name="Triggered By",
                        value=f"{message.author.mention} (`{message.author}` / `{message.author.id}`)",
                        inline=False,
                    )
                    log_embed.add_field(name="Duration", value="12 hours", inline=True)
                    log_embed.add_field(
                        name="Channel",
                        value=message.channel.mention if hasattr(message.channel, "mention") else str(message.channel),
                        inline=True,
                    )
                    log_embed.add_field(
                        name="Rule",
                        value=f"Rule #{rule_num} — {rule.get('title', 'N/A')}",
                        inline=False,
                    )
                    if hasattr(ref_msg, "jump_url") and ref_msg.jump_url:
                        log_embed.add_field(
                            name="Context Message",
                            value=f"[Jump to Message]({ref_msg.jump_url})",
                            inline=False,
                        )

                    res = _send_log_fn(log_embed)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    print(f"⚠️ [rules_trigger] Failed to send log embed: {e}")

        except discord.HTTPException:
            embed = _build_rule_embed(rule_num, rule)
            await message.channel.send(embed=embed)
    else:
        # Normal mode — just send the embed
        embed = _build_rule_embed(rule_num, rule)
        await message.channel.send(embed=embed)

    # Delete the trigger message
    try:
        await message.delete()
    except discord.HTTPException:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────


def setup(bot: discord.Client, get_rules_fn=None, send_log_fn=None):
    """
    Register the !ruleN listener.

    Args:
        bot: The discord client.
        get_rules_fn: Callable that returns the live rules dict (bot.RULES_MAP).
        send_log_fn: Optional callable to send log embeds to log channel.
    """
    global _bot, _get_rules_fn, _send_log_fn
    _bot = bot
    if get_rules_fn:
        _get_rules_fn = get_rules_fn
    if send_log_fn:
        _send_log_fn = send_log_fn

    @bot.listen("on_message")
    async def on_message_rules(message: discord.Message):
        await _handle(message)

    print("✅ rules_trigger loaded — prefix: !ruleN (reads live from RULES_MAP, !r4 timeouts for 12h)")
