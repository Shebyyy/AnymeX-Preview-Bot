# ══════════════════════════════════════════════════════════════════════════════
# role_copy.py — Copy selected roles (name, colour, hoist) between servers
# ══════════════════════════════════════════════════════════════════════════════
# /copyroles target:<server> [source:<server>] [roles:<names>]
#            [source_server_id:<id> source_token:<bot token>]
#
# Source can be a server this bot is in (pick from the list), OR any server
# you give a server ID + bot token for (e.g. a test bot that is in it).
# The token option is bot-owner only, used once for read-only role fetch,
# never stored or logged, and the reply is ephemeral.
#
# - Defaults to the Dartotsu leveling roles (FIRST MATE … OVERLORD).
# - Copies name + colour, shown separately in the member list. No permissions.
# - Names that already exist in the target are skipped.
# - New roles are placed just under the bot's top role, in the order given.
# - Invoker needs Manage Roles (or Administrator) in BOTH servers; bot owner always allowed.
# ══════════════════════════════════════════════════════════════════════════════

import re
import asyncio
import aiohttp
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


_target_choices = _guild_choices


async def _fetch_external_roles(server_id: int, token: str):
    """Read roles of a server using another bot's token. Returns (name, roles) or raises ValueError."""
    headers = {"Authorization": f"Bot {token.strip()}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"https://discord.com/api/v10/guilds/{server_id}/roles") as r:
            if r.status == 401:
                raise ValueError("That bot token is invalid.")
            if r.status in (403, 404):
                raise ValueError("That bot isn't in that server (or the server ID is wrong).")
            if r.status != 200:
                raise ValueError(f"Discord returned {r.status} while reading the source roles.")
            roles = await r.json()
        label = f"server {server_id}"
        async with session.get(f"https://discord.com/api/v10/guilds/{server_id}") as r:
            if r.status == 200:
                label = (await r.json()).get("name", label)
    return label, [
        {"name": x["name"], "color": x["color"], "managed": x.get("managed", False), "everyone": x["id"] == str(server_id)}
        for x in roles
    ]


def _guild_roles(guild: discord.Guild):
    return [
        {"name": r.name, "color": r.colour.value, "managed": r.managed, "everyone": r.is_default()}
        for r in guild.roles
    ]


async def _copy_roles(source_label: str, source_roles: list, target: discord.Guild, invoker, names: List[str]) -> str:
    me = target.me
    if not me.guild_permissions.manage_roles:
        return f"❌ I need **Manage Roles** in **{target.name}**."

    src_by_name = {r["name"].lower(): r for r in source_roles if not r["everyone"] and not r["managed"]}
    existing = {r.name.lower() for r in target.roles}

    created: List[discord.Role] = []
    exists, missing, failed = [], [], []

    for name in names:
        src = src_by_name.get(name.lower())
        if src is None:
            missing.append(name)
            continue
        if src["name"].lower() in existing:
            exists.append(src["name"])
            continue
        try:
            new = await target.create_role(
                name=src["name"],
                colour=discord.Colour(src["color"]),
                hoist=True,  # display role members separately
                mentionable=False,
                reason=f"Copied from {source_label} by {invoker} ({invoker.id})",
            )
            created.append(new)
        except discord.HTTPException as e:
            failed.append(f"{src['name']} ({e.status})")
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

    lines = [f"{'✅' if created and not failed and not missing else '⚠️'} **{source_label}** → **{target.name}**",
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

    @bot.tree.command(name="copyroles", description="Copy selected roles (name + colour) from another server")
    @app_commands.describe(
        target="Server to copy roles TO",
        source="Server the bot is in to copy FROM (or use the ID + token below)",
        roles="Comma-separated role names (default: the leveling roles)",
        source_server_id="Source server ID, for a server this bot is NOT in",
        source_token="Bot token of a bot that IS in the source server (owner only)",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def copyroles(
        interaction: discord.Interaction,
        target: str,
        source: Optional[str] = None,
        roles: Optional[str] = None,
        source_server_id: Optional[str] = None,
        source_token: Optional[str] = None,
    ):
        dst = emoji_copy._find_guild(target)
        if not dst:
            await interaction.response.send_message(
                "❌ Pick the target server from the list (the bot must be in it).", ephemeral=True)
            return
        if not _can_roles(dst, interaction.user.id):
            await interaction.response.send_message(
                f"❌ You need **Manage Roles** (or Administrator) in **{dst.name}**.", ephemeral=True)
            return
        names = [n.strip() for n in (roles or DEFAULT_ROLES).split(",") if n.strip()]
        if not names:
            await interaction.response.send_message("❌ No role names given.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if source_token or source_server_id:
            if interaction.user.id != _owner_id:
                await interaction.followup.send(
                    "❌ Using a bot token for the source is limited to the bot owner.", ephemeral=True)
                return
            m = re.fullmatch(r"\d{15,22}", (source_server_id or "").strip())
            if not source_token or not m:
                await interaction.followup.send(
                    "❌ Give **both** `source_server_id` and `source_token`.", ephemeral=True)
                return
            try:
                label, src_roles = await _fetch_external_roles(int(m.group(0)), source_token)
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
                return
            except Exception:
                await interaction.followup.send("❌ Couldn't reach Discord to read the source roles.", ephemeral=True)
                return
        else:
            src = emoji_copy._find_guild(source) if source else None
            if not src:
                await interaction.followup.send(
                    "❌ Pick a source server, or give `source_server_id` + `source_token`.", ephemeral=True)
                return
            if src.id == dst.id:
                await interaction.followup.send("❌ Source and target are the same server.", ephemeral=True)
                return
            if not _can_roles(src, interaction.user.id):
                await interaction.followup.send(
                    f"❌ You need **Manage Roles** (or Administrator) in **{src.name}**.", ephemeral=True)
                return
            label, src_roles = src.name, _guild_roles(src)

        msg = await _copy_roles(label, src_roles, dst, interaction.user, names)
        await interaction.followup.send(msg[:1900], ephemeral=True)

    copyroles.autocomplete("source")(_guild_choices)
    copyroles.autocomplete("target")(_target_choices)
    print("✅ Role Copy module loaded")
