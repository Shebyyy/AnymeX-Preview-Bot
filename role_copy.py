# ══════════════════════════════════════════════════════════════════════════════
# role_copy.py — Copy selected roles (name, colour, hoist) between servers
# ══════════════════════════════════════════════════════════════════════════════
# /copyroles source:<server> target:<server> [roles:<comma separated names>]
#
# - Defaults to the Dartotsu leveling roles (FIRST MATE … OVERLORD).
# - Copies name + colour, shown separately in the member list. No permissions.
# - Names that already exist in the target are skipped.
# - New roles are placed just under the bot's top role, in the order given.
# - Invoker needs Manage Roles (or Administrator) in BOTH servers; bot owner always allowed.
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
import discord
from typing import Optional, List
from discord import app_commands

import emoji_copy  # reuse server autocomplete / lookup

# Lowest level first, so the order matches the level ladder
DEFAULT_ROLES = (
    "FIRST MATE, CAPTAIN, KNIGHT, NUB, PALADIN, NO LONGER HUMAN, "
    "IMMORTAL, DIABLO, ANGEL, OVERLORD"
)
CREATE_DELAY = 1.0

_bot: Optional[discord.Client] = None
_owner_id: Optional[int] = None


def _can_roles(guild: discord.Guild, user_id: int) -> bool:
    if user_id == _owner_id:
        return True
    m = guild.get_member(user_id)
    return bool(m and (m.guild_permissions.administrator or m.guild_permissions.manage_roles))


async def _guild_choices(interaction: discord.Interaction, current: str):
    q = (current or "").strip().lower()
    out = []
    for g in _bot.guilds:
        if not _can_roles(g, interaction.user.id):
            continue
        if q and q not in g.name.lower() and q not in str(g.id):
            continue
        out.append(app_commands.Choice(name=f"{g.name} ({len(g.roles)} roles)"[:100], value=str(g.id)))
        if len(out) >= 25:
            break
    return out


async def _copy_roles(source: discord.Guild, target: discord.Guild, invoker, names: List[str]) -> str:
    me = target.me
    if not me.guild_permissions.manage_roles:
        return f"❌ I need **Manage Roles** in **{target.name}**."

    src_by_name = {r.name.lower(): r for r in source.roles if not r.is_default() and not r.managed}
    existing = {r.name.lower() for r in target.roles}

    created: List[discord.Role] = []
    exists, missing, failed = [], [], []

    for name in names:
        src = src_by_name.get(name.lower())
        if src is None:
            missing.append(name)
            continue
        if src.name.lower() in existing:
            exists.append(src.name)
            continue
        try:
            new = await target.create_role(
                name=src.name,
                colour=src.colour,
                hoist=True,  # display role members separately
                mentionable=False,
                reason=f"Copied from {source.name} by {invoker} ({invoker.id})",
            )
            created.append(new)
        except discord.HTTPException as e:
            failed.append(f"{src.name} ({e.status})")
        await asyncio.sleep(CREATE_DELAY)

    # Put them in order right under the bot's top role (lowest level lowest)
    note = ""
    if created:
        try:
            top = me.top_role.position
            n = len(created)
            positions = {role: max(1, top - n + i) for i, role in enumerate(created)}
            await target.edit_role_positions(positions=positions)
        except Exception:
            note = ("\n⚠️ Couldn't auto-order them. Drag them in Server Settings → Roles "
                    "(keep them under the bot's role).")

    lines = [f"{'✅' if created and not failed and not missing else '⚠️'} **{source.name}** → **{target.name}**",
             f"Created: **{len(created)}**" + (": " + ", ".join(r.name for r in created) if created else "")]
    if exists:
        lines.append("Already existed: " + ", ".join(exists))
    if missing:
        lines.append("Not found in source: " + ", ".join(missing))
    if failed:
        lines.append("Failed: " + ", ".join(failed))
    return "\n".join(lines) + note


def setup(bot: discord.Client, *, owner_id: Optional[int] = None):
    global _bot, _owner_id
    _bot = bot
    _owner_id = owner_id

    @bot.tree.command(name="copyroles", description="Copy selected roles (name + colour) to another server")
    @app_commands.describe(
        source="Server to copy roles FROM",
        target="Server to copy roles TO",
        roles="Comma-separated role names (default: the leveling roles)",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def copyroles(interaction: discord.Interaction, source: str, target: str, roles: Optional[str] = None):
        src, dst = emoji_copy._find_guild(source), emoji_copy._find_guild(target)
        if not src or not dst:
            await interaction.response.send_message(
                "❌ Pick both servers from the list (the bot must be in them).", ephemeral=True)
            return
        if src.id == dst.id:
            await interaction.response.send_message("❌ Source and target are the same server.", ephemeral=True)
            return
        if not (_can_roles(src, interaction.user.id) and _can_roles(dst, interaction.user.id)):
            await interaction.response.send_message(
                "❌ You need **Manage Roles** (or Administrator) in **both** servers.", ephemeral=True)
            return
        names = [n.strip() for n in (roles or DEFAULT_ROLES).split(",") if n.strip()]
        if not names:
            await interaction.response.send_message("❌ No role names given.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msg = await _copy_roles(src, dst, interaction.user, names)
        await interaction.followup.send(msg[:1900], ephemeral=True)

    copyroles.autocomplete("source")(_guild_choices)
    copyroles.autocomplete("target")(_guild_choices)
    print("✅ Role Copy module loaded")
