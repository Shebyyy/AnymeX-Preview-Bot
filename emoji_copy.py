# ══════════════════════════════════════════════════════════════════════════════
# emoji_copy.py — Copy custom emojis from one server to another
# ══════════════════════════════════════════════════════════════════════════════
# /copyemojis source:<server> target:<server>
#
# - Both options autocomplete from the servers the bot is in.
# - The invoker needs Manage Expressions (or Administrator) in BOTH servers,
#   or must be the bot owner. Checked on every call, and autocomplete only
#   lists servers where the invoker has it.
# - The bot needs Manage Expressions in the target server.
# - Emojis whose name already exists in the target are skipped.
# - Static and animated emojis have separate slot limits, respected here.
# - Runs in the background with live progress, one run per target at a time.
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
import discord
from typing import Optional, List
from discord import app_commands

CREATE_DELAY = 2.0          # seconds between uploads (emoji creation is heavily rate limited)
PROGRESS_EVERY = 5          # update the progress message every N emojis
MAX_EMOJI_BYTES = 256 * 1024

_bot: Optional[discord.Client] = None
_owner_id: Optional[int] = None
_send_log_fn = None
_running: set = set()       # target guild ids with a copy in progress


def _has_perm(guild: discord.Guild, user_id: int) -> bool:
    if user_id == _owner_id:
        return True
    member = guild.get_member(user_id)
    if member is None:
        return False
    p = member.guild_permissions
    return p.administrator or p.manage_emojis_and_stickers


def _find_guild(value: str) -> Optional[discord.Guild]:
    try:
        return _bot.get_guild(int(value))
    except (ValueError, TypeError):
        return None


async def _guild_choices(interaction: discord.Interaction, current: str):
    q = (current or "").strip().lower()
    out = []
    for g in _bot.guilds:
        if not _has_perm(g, interaction.user.id):
            continue
        if q and q not in g.name.lower() and q not in str(g.id):
            continue
        out.append(app_commands.Choice(name=f"{g.name} ({len(g.emojis)} emojis)"[:100], value=str(g.id)))
        if len(out) >= 25:
            break
    return out


def _bar(done: int, total: int, width: int = 16) -> str:
    filled = int(width * done / total) if total else width
    return "█" * filled + "░" * (width - filled)


async def _copy(interaction: discord.Interaction, source: discord.Guild, target: discord.Guild):
    me = target.me
    if not me.guild_permissions.manage_emojis_and_stickers:
        await interaction.edit_original_response(
            content=f"❌ I need **Manage Expressions** in **{target.name}**.")
        return

    existing = {e.name.lower() for e in target.emojis}
    limit = target.emoji_limit
    free_static = limit - sum(1 for e in target.emojis if not e.animated)
    free_anim = limit - sum(1 for e in target.emojis if e.animated)

    todo: List[discord.Emoji] = []
    skipped_exists = skipped_full = 0
    for e in source.emojis:
        if e.name.lower() in existing:
            skipped_exists += 1
            continue
        if e.animated:
            if free_anim <= 0:
                skipped_full += 1
                continue
            free_anim -= 1
        else:
            if free_static <= 0:
                skipped_full += 1
                continue
            free_static -= 1
        todo.append(e)

    total = len(todo)
    if total == 0:
        await interaction.edit_original_response(content=(
            f"ℹ️ Nothing to copy. Already there: **{skipped_exists}**, no free slots: **{skipped_full}**."))
        return

    created = failed = 0
    fail_names: List[str] = []
    stopped_reason = None

    async def progress(done: int):
        try:
            await interaction.edit_original_response(content=(
                f"⏳ Copying **{source.name}** → **{target.name}**\n"
                f"`{_bar(done, total)}` {done}/{total}  ✅ {created}  ❌ {failed}"))
        except discord.HTTPException:
            pass  # token expired or message gone; the final summary falls back to the channel

    await progress(0)

    for i, e in enumerate(todo, 1):
        try:
            data = await e.read()
            if len(data) > MAX_EMOJI_BYTES:
                raise ValueError("file over 256 KB")
            await target.create_custom_emoji(
                name=e.name, image=data,
                reason=f"Copied from {source.name} by {interaction.user} ({interaction.user.id})")
            created += 1
        except discord.Forbidden:
            stopped_reason = "I lost permission to create emojis."
            break
        except discord.HTTPException as ex:
            if ex.code == 30008:  # max emojis reached
                stopped_reason = "Emoji limit reached in the target server."
                break
            failed += 1
            fail_names.append(e.name)
        except Exception:
            failed += 1
            fail_names.append(e.name)

        if i % PROGRESS_EVERY == 0:
            await progress(i)
        await asyncio.sleep(CREATE_DELAY)

    lines = [
        f"{'⚠️' if stopped_reason or failed else '✅'} Finished **{source.name}** → **{target.name}**",
        f"Copied: **{created}** · Already existed: **{skipped_exists}** · "
        f"No free slot: **{skipped_full}** · Failed: **{failed}**",
    ]
    if stopped_reason:
        lines.append(f"Stopped early: {stopped_reason}")
    if fail_names:
        lines.append("Failed: " + ", ".join(f"`{n}`" for n in fail_names[:20]) + (" …" if len(fail_names) > 20 else ""))
    summary = "\n".join(lines)

    try:
        await interaction.edit_original_response(content=summary)
    except discord.HTTPException:
        # Interaction token (15 min) expired on a long run: post in the channel instead
        try:
            await interaction.channel.send(f"{interaction.user.mention}\n{summary}")
        except Exception:
            pass

    if _send_log_fn:
        try:
            emb = discord.Embed(title="😀 Emojis Copied", description=summary, color=0x2ECC71)
            res = _send_log_fn(emb)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
        except Exception:
            pass


def setup(bot: discord.Client, *, owner_id: Optional[int] = None, send_log_fn=None):
    global _bot, _owner_id, _send_log_fn
    _bot = bot
    _owner_id = owner_id
    _send_log_fn = send_log_fn

    @bot.tree.command(name="copyemojis", description="Copy all custom emojis from one server to another")
    @app_commands.describe(source="Server to copy emojis FROM", target="Server to copy emojis TO")
    @app_commands.default_permissions(manage_emojis_and_stickers=True)
    async def copyemojis(interaction: discord.Interaction, source: str, target: str):
        src, dst = _find_guild(source), _find_guild(target)
        if not src or not dst:
            await interaction.response.send_message(
                "❌ Pick both servers from the list (the bot must be in them).", ephemeral=True)
            return
        if src.id == dst.id:
            await interaction.response.send_message("❌ Source and target are the same server.", ephemeral=True)
            return
        if not (_has_perm(src, interaction.user.id) and _has_perm(dst, interaction.user.id)):
            await interaction.response.send_message(
                "❌ You need **Manage Expressions** (or Administrator) in **both** servers.", ephemeral=True)
            return
        if dst.id in _running:
            await interaction.response.send_message(
                f"⏳ A copy into **{dst.name}** is already running.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        _running.add(dst.id)
        try:
            await _copy(interaction, src, dst)
        finally:
            _running.discard(dst.id)

    copyemojis.autocomplete("source")(_guild_choices)
    copyemojis.autocomplete("target")(_guild_choices)
    print("✅ Emoji Copy module loaded")
