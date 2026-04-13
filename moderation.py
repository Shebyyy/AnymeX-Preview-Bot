# ══════════════════════════════════════════════════════════════════════════════
# moderation.py  —  Ban / Unban / Mute / Unmute / Timeout / Untimeout
# ══════════════════════════════════════════════════════════════════════════════

import re
import time
import asyncio
import aiohttp
import discord
from discord import app_commands
from datetime import datetime, timezone

# Import names from bot.py — safe because bot.py defines `bot` on line 999
# *before* `from moderation import *` on line 1001, so the `bot` module is
# already partially loaded in sys.modules when this runs.
from bot import (
    bot, github_read_json, github_write_json,
    USERDATA_REPO, USERDATA_BRANCH, read_users,
    is_bot_admin, _send_log,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

FILE_BANNED = "banned.json"   # stored in USERDATA_REPO (private repo)

# Max Discord timeout is 28 days
_DISCORD_TIMEOUT_MAX_DAYS = 28

# Duration preset choices shown in /mute_user and /timeout_user
_DURATION_PRESETS = [
    app_commands.Choice(name="15 minutes",  value="15m"),
    app_commands.Choice(name="30 minutes",  value="30m"),
    app_commands.Choice(name="1 hour",      value="1h"),
    app_commands.Choice(name="6 hours",     value="6h"),
    app_commands.Choice(name="12 hours",    value="12h"),
    app_commands.Choice(name="1 day",       value="1d"),
    app_commands.Choice(name="3 days",      value="3d"),
    app_commands.Choice(name="7 days",      value="7d"),
    app_commands.Choice(name="30 days",     value="30d"),
    app_commands.Choice(name="Permanent",   value="permanent"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Duration helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_duration(text: str) -> int | None:
    """
    Parse '1h30m', '7d', '90m', '2h', '1d12h' etc. into total seconds.
    Returns None if invalid or zero. 'permanent' returns None (no expiry).
    """
    if not text:
        return None
    text = text.strip().lower()
    if text == "permanent":
        return None
    m = re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', text)
    if not m or not any(m.groups()):
        return None
    total = (
        int(m.group(1) or 0) * 86400 +
        int(m.group(2) or 0) * 3600  +
        int(m.group(3) or 0) * 60    +
        int(m.group(4) or 0)
    )
    return total if total > 0 else None


def _fmt_duration(seconds: float) -> str:
    """Format seconds → '2d 3h 15m 5s' style string."""
    seconds = int(seconds)
    parts = []
    for unit, label in ((86400, "d"), (3600, "h"), (60, "m"), (1, "s")):
        if seconds >= unit:
            parts.append(f"{seconds // unit}{label}")
            seconds %= unit
    return " ".join(parts) if parts else "0s"


# ─────────────────────────────────────────────────────────────────────────────
# banned.json read/write helpers
# ─────────────────────────────────────────────────────────────────────────────

async def read_banned(session: aiohttp.ClientSession) -> tuple[dict, str | None]:
    """Read banned.json from private userdata repo. Returns (data, sha)."""
    # github_read_json / USERDATA_REPO / USERDATA_BRANCH come from bot.py scope
    data, sha = await github_read_json(
        session, FILE_BANNED, repo=USERDATA_REPO, branch=USERDATA_BRANCH
    )
    if not isinstance(data, dict):
        data = {}
    return data, sha


async def write_banned(
    session: aiohttp.ClientSession,
    data: dict,
    sha: str | None,
    message: str,
) -> bool:
    return await github_write_json(
        session, FILE_BANNED, data, sha, message,
        repo=USERDATA_REPO, branch=USERDATA_BRANCH,
    )


async def _get_ban_record(
    discord_id=None,
    anilist_id=None,
    mal_id=None,
    simkl_id=None,
) -> dict | None:
    """
    Return the active ban/mute/timeout record for this user, or None.
    Checks all provided IDs against all keys in banned.json.
    Auto-removes expired entries silently.
    """
    async with aiohttp.ClientSession() as session:
        banned, sha = await read_banned(session)
    if not banned:
        return None

    now = time.time()
    checks = []
    if discord_id:  checks.append(f"discord:{discord_id}")
    if anilist_id:  checks.append(f"anilist:{anilist_id}")
    if mal_id:      checks.append(f"mal:{mal_id}")
    if simkl_id:    checks.append(f"simkl:{simkl_id}")

    for key in checks:
        rec = banned.get(key)
        if not rec:
            continue
        exp = rec.get("expires_at")
        if exp and now > exp:
            # Silently expire — the expiry task will log it
            banned.pop(key)
            async with aiohttp.ClientSession() as session:
                _, sha2 = await read_banned(session)
                await write_banned(session, banned, sha2,
                    f"auto: expired {rec.get('type','mute')} for {key}")
            return None
        return rec
    return None


# ─────────────────────────────────────────────────────────────────────────────
# User search autocomplete  (shared by all 6 commands)
# ─────────────────────────────────────────────────────────────────────────────

async def _search_users_for_mod(query: str) -> list[dict]:
    """
    Search users.json for any user matching the query against:
    discord_username, discord_display_name, anilist_username,
    mal_username, simkl_username, or any numeric ID.
    Returns up to 25 matches.
    """
    async with aiohttp.ClientSession() as session:
        users, _ = await read_users(session)  # read_users from bot.py

    q = query.lower().strip()
    results = []

    for discord_id, p in users.items():
        haystack = " ".join(filter(None, [
            str(p.get("discord_username")     or ""),
            str(p.get("discord_display_name") or ""),
            str(p.get("anilist_username")     or ""),
            str(p.get("mal_username")         or ""),
            str(p.get("simkl_username")       or ""),
            str(p.get("anilist_user_id")      or ""),
            str(p.get("mal_user_id")          or ""),
            str(p.get("simkl_user_id")        or ""),
            str(discord_id),
        ])).lower()

        if q in haystack:
            results.append({
                "discord_id":       discord_id,
                "discord_username": p.get("discord_username"),
                "discord_display":  p.get("discord_display_name"),
                "anilist_id":       p.get("anilist_user_id"),
                "anilist_username": p.get("anilist_username"),
                "mal_id":           p.get("mal_user_id"),
                "mal_username":     p.get("mal_username"),
                "simkl_id":        p.get("simkl_user_id"),
                "simkl_username":   p.get("simkl_username"),
            })

        if len(results) >= 25:
            break

    return results


async def mod_user_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """
    Autocomplete for the `user` parameter on all moderation commands.
    Shows: DC:username · AL:anilist · MAL:mal · SK:simkl
    Value encodes all 4 IDs as  discord_id|anilist_id|mal_id|simkl_id
    """
    if len(current) < 2:
        return [app_commands.Choice(
            name="🔍 Type at least 2 characters to search users...",
            value="__none__"
        )]

    try:
        results = await _search_users_for_mod(current)
    except Exception:
        return []

    if not results:
        return [app_commands.Choice(
            name=f"❌ No users found matching '{current[:30]}'",
            value="__none__"
        )]

    choices = []
    for u in results:
        # Build readable label with all known usernames
        parts = []
        name = u.get("discord_display") or u.get("discord_username")
        if name:                        parts.append(f"DC:{name}")
        if u.get("anilist_username"):   parts.append(f"AL:{u['anilist_username']}")
        if u.get("mal_username"):       parts.append(f"MAL:{u['mal_username']}")
        if u.get("simkl_username"):     parts.append(f"SK:{u['simkl_username']}")
        label = " · ".join(parts) if parts else f"discord:{u['discord_id']}"
        label = label[:100]

        # Value = pipe-separated IDs
        value = "|".join([
            str(u.get("discord_id")   or ""),
            str(u.get("anilist_id")   or ""),
            str(u.get("mal_id")       or ""),
            str(u.get("simkl_id")     or ""),
        ])[:100]

        choices.append(app_commands.Choice(name=label, value=value))

    return choices


def _unpack_user_value(value: str) -> tuple:
    """
    Unpack autocomplete value back into (discord_id, anilist_id, mal_id, simkl_id).
    Returns (str|None, int|None, int|None, int|None).
    """
    parts = (value + "|||").split("|")
    def _int(v): return int(v) if v and v.strip().isdigit() else None
    def _str(v): return v.strip() if v and v.strip() else None
    return (
        _str(parts[0]),
        _int(parts[1]),
        _int(parts[2]),
        _int(parts[3]),
    )


def _ids_display(discord_id=None, anilist_id=None, mal_id=None, simkl_id=None) -> str:
    """Build a compact IDs line for embeds."""
    parts = []
    if discord_id:  parts.append(f"DC:`{discord_id}`")
    if anilist_id:  parts.append(f"AL:`{anilist_id}`")
    if mal_id:      parts.append(f"MAL:`{mal_id}`")
    if simkl_id:    parts.append(f"SK:`{simkl_id}`")
    return " · ".join(parts) if parts else "N/A"


# ─────────────────────────────────────────────────────────────────────────────
# Confirmation View  (shared by all 6 commands)
# ─────────────────────────────────────────────────────────────────────────────

class ModerationConfirmView(discord.ui.View):
    """
    Single confirm/cancel view used by ban, unban, mute, unmute, timeout, untimeout.
    - For ban/mute/timeout:   writes record to banned.json
    - For unban/unmute/untimeout: removes record from banned.json
    """

    def __init__(
        self,
        *,
        action: str,                              # ban|unban|mute|unmute|timeout|untimeout
        ban_key: str,                             # e.g. "discord:123456"
        ban_record: dict | None,                  # record to write (None for removals)
        discord_member: discord.Member | None,    # needed for timeout actions
        actioned_by: discord.User | discord.Member,
    ):
        super().__init__(timeout=60)
        self.action = action
        self.ban_key = ban_key
        self.ban_record = ban_record
        self.discord_member = discord_member
        self.actioned_by = actioned_by

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.actioned_by.id:
            await interaction.response.send_message(
                "❌ Only the admin who ran this command can confirm.", ephemeral=True
            )
            return False
        return True

    async def _disable_buttons(self, message):
        for child in self.children:
            child.disabled = True
        try:
            await message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()
        await self._disable_buttons(interaction.message)

        is_write  = self.action in ("ban", "mute", "timeout")
        is_discord_action = self.action in ("timeout", "untimeout")

        # ── Write to banned.json ──────────────────────────────────────────────
        try:
            async with aiohttp.ClientSession() as session:
                banned, sha = await read_banned(session)

                if is_write:
                    banned[self.ban_key] = self.ban_record
                else:
                    # Remove primary key
                    banned.pop(self.ban_key, None)
                    # Also clean up any alternate-ID keys for same user
                    if self.ban_record:
                        ids = self.ban_record.get("identifiers", {})
                        for prefix, val in [
                            ("discord",  ids.get("discord_id")),
                            ("anilist",  ids.get("anilist_id")),
                            ("mal",      ids.get("mal_id")),
                            ("simkl",    ids.get("simkl_id")),
                        ]:
                            alt = f"{prefix}:{val}" if val else None
                            if alt and alt != self.ban_key:
                                banned.pop(alt, None)

                ok = await write_banned(
                    session, banned, sha,
                    f"{self.action}: {self.ban_key} by {self.actioned_by}",
                )
        except Exception as e:
            await interaction.followup.send(f"❌ GitHub write failed: {e}", ephemeral=True)
            return

        if not ok:
            await interaction.followup.send("❌ Failed to write to GitHub.", ephemeral=True)
            return


        # ── Result embed ──────────────────────────────────────────────────────
        colors = {
            "ban": 0xDA3633,   "unban":    0x2EA043,
            "mute": 0xFF6B35,  "unmute":   0x2EA043,
            "timeout": 0x9B59B6, "untimeout": 0x2EA043,
        }
        emojis = {
            "ban": "🔨", "unban": "✅",
            "mute": "🔇", "unmute": "🔉",
            "timeout": "⏱️", "untimeout": "✅",
        }
        verbs = {
            "ban": "Banned", "unban": "Unbanned",
            "mute": "Muted", "unmute": "Unmuted",
            "timeout": "Timed Out", "untimeout": "Timeout Lifted",
        }

        result = discord.Embed(
            title=f"{emojis[self.action]} {verbs[self.action]}",
            color=colors[self.action],
        )
        result.add_field(name="Key", value=self.ban_key, inline=True)
        result.add_field(name="By", value=self.actioned_by.mention, inline=True)

        if self.ban_record and is_write:
            result.add_field(
                name="Reason",
                value=self.ban_record.get("reason", "N/A"),
                inline=False,
            )
            exp = self.ban_record.get("expires_at")
            if exp:
                result.add_field(
                    name="Expires",
                    value=f"<t:{int(exp)}:R>  (<t:{int(exp)}:f>)",
                    inline=False,
                )
            else:
                result.add_field(name="Duration", value="Permanent", inline=True)

        await interaction.followup.send(embed=result)

        # ── DM the user ───────────────────────────────────────────────────────
        dm_discord_id = None
        if self.ban_record:
            dm_discord_id = self.ban_record.get("identifiers", {}).get("discord_id")
        # For removals (unban/unmute/untimeout), ban_record holds the old record
        if dm_discord_id:
            try:
                target_user = await bot.fetch_user(int(dm_discord_id))
                dm_messages = {
                    "ban":       "🔨 You have been **banned** from accessing community recommendations, including all related slash commands on our Discord server and the community features within the AnymeX app.",
                    "unban":     "✅ Your ban has been **lifted**. You can now access community recommendations, including all related slash commands on our Discord server and the community features within the AnymeX app.",
                    "mute":      "🔇 You have been **muted** from accessing community recommendations, including all related slash commands on our Discord server and the community features within the AnymeX app.",
                    "unmute":    "🔉 Your mute has been **lifted**. You can now access community recommendations, including all related slash commands on our Discord server and the community features within the AnymeX app.",
                    "timeout":   "⏱️ You have been **timed out** from accessing community recommendations, including all related slash commands on our Discord server and the community features within the AnymeX app.",
                    "untimeout": "✅ Your timeout has been **lifted**. You can now access community recommendations, including all related slash commands on our Discord server and the community features within the AnymeX app.",
                }
                dm_text = dm_messages.get(self.action)
                if dm_text:
                    dm_embed = discord.Embed(description=dm_text, color=colors[self.action])
                    dm_embed.set_footer(text="If you believe this is a mistake, please contact a server admin.")
                    await target_user.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # User has DMs disabled — silently ignore
            except Exception as e:
                print(f"⚠️ [Mod DM] Failed to DM user {dm_discord_id}: {e}")

        # ── Log embed ─────────────────────────────────────────────────────────
        log = discord.Embed(
            title=f"{emojis[self.action]} {verbs[self.action]}",
            color=colors[self.action],
        )
        log.add_field(name="Key",        value=self.ban_key, inline=True)
        log.add_field(name="Actioned by", value=f"{self.actioned_by.mention} (`{self.actioned_by}`)", inline=True)
        if self.ban_record:
            ids = self.ban_record.get("identifiers", {})
            log.add_field(
                name="IDs",
                value=_ids_display(
                    discord_id=ids.get("discord_id"),
                    anilist_id=ids.get("anilist_id"),
                    mal_id=ids.get("mal_id"),
                    simkl_id=ids.get("simkl_id"),
                ),
                inline=False,
            )
            if is_write:
                log.add_field(name="Reason", value=self.ban_record.get("reason", "N/A"), inline=False)
                exp = self.ban_record.get("expires_at")
                if exp:
                    log.add_field(name="Expires", value=f"<t:{int(exp)}:R>", inline=True)
                else:
                    log.add_field(name="Duration", value="Permanent", inline=True)

        await _send_log(log)  # _send_log from bot.py

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await self._disable_buttons(interaction.message)
        await interaction.response.send_message("❌ Cancelled.", ephemeral=True)

    async def on_timeout(self):
        # Disable buttons if admin never responded
        try:
            for child in self.children:
                child.disabled = True
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# /ban_user
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="ban_user", description="Ban a user from community recommendations")
@app_commands.describe(
    user="Search and select the user to ban",
    reason="Reason for the ban",
)
@app_commands.autocomplete(user=mod_user_autocomplete)
async def ban_user(interaction: discord.Interaction, user: str, reason: str):
    await interaction.response.defer(ephemeral=True)

    if not await is_bot_admin(interaction.user.id):
        await interaction.followup.send("❌ Only bot admins can use this command.", ephemeral=True)
        return

    if user == "__none__":
        await interaction.followup.send("❌ Please select a user from the dropdown.", ephemeral=True)
        return

    discord_id, anilist_id, mal_id, simkl_id = _unpack_user_value(user)

    if not any([discord_id, anilist_id, mal_id, simkl_id]):
        await interaction.followup.send("❌ Could not resolve user. Please select from the dropdown.", ephemeral=True)
        return

    # Check if already banned
    existing = await _get_ban_record(discord_id, anilist_id, mal_id, simkl_id)
    if existing and existing.get("type") == "ban":
        await interaction.followup.send(
            f"⚠️ This user is already banned. Reason: `{existing.get('reason','N/A')}`",
            ephemeral=True,
        )
        return

    ban_key = (
        f"discord:{discord_id}" if discord_id else
        f"anilist:{anilist_id}" if anilist_id else
        f"mal:{mal_id}"         if mal_id     else
        f"simkl:{simkl_id}"
    )

    ban_record = {
        "type": "ban",
        "reason": reason,
        "actioned_by_discord_id": str(interaction.user.id),
        "actioned_by_username":   interaction.user.name,
        "actioned_at":            time.time(),
        "expires_at":             None,  # bans are permanent
        "identifiers": {
            "discord_id":  discord_id,
            "anilist_id":  anilist_id,
            "mal_id":      mal_id,
            "simkl_id":    simkl_id,
        },
    }

    preview = discord.Embed(title="🔨 Confirm Ban", color=0xDA3633)
    preview.add_field(name="User", value=_ids_display(discord_id, anilist_id, mal_id, simkl_id), inline=False)
    preview.add_field(name="Reason", value=reason, inline=False)
    preview.add_field(name="Duration", value="⚠️ **Permanent**", inline=True)
    preview.set_footer(text="This blocks all bot commands and API calls. You have 60s to confirm.")

    # Try to resolve Discord member for display
    discord_member = None
    if discord_id and interaction.guild:
        try:
            discord_member = interaction.guild.get_member(int(discord_id)) or await interaction.guild.fetch_member(int(discord_id))
            if discord_member:
                preview.set_thumbnail(url=discord_member.display_avatar.url)
                preview.insert_field_at(0, name="Discord", value=f"{discord_member.mention} (`{discord_member}`)", inline=False)
        except Exception:
            pass

    view = ModerationConfirmView(
        action="ban",
        ban_key=ban_key,
        ban_record=ban_record,
        discord_member=discord_member,
        actioned_by=interaction.user,
    )
    await interaction.followup.send(embed=preview, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# /unban_user
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="unban_user", description="Unban a user from community recommendations")
@app_commands.describe(user="Search and select the user to unban")
@app_commands.autocomplete(user=mod_user_autocomplete)
async def unban_user(interaction: discord.Interaction, user: str):
    await interaction.response.defer(ephemeral=True)

    if not await is_bot_admin(interaction.user.id):
        await interaction.followup.send("❌ Only bot admins can use this command.", ephemeral=True)
        return

    if user == "__none__":
        await interaction.followup.send("❌ Please select a user from the dropdown.", ephemeral=True)
        return

    discord_id, anilist_id, mal_id, simkl_id = _unpack_user_value(user)

    existing = await _get_ban_record(discord_id, anilist_id, mal_id, simkl_id)
    if not existing:
        await interaction.followup.send("❌ This user is not currently banned.", ephemeral=True)
        return
    if existing.get("type") != "ban":
        await interaction.followup.send(
            f"⚠️ This user has a `{existing.get('type')}` record, not a ban. Use the correct command.",
            ephemeral=True,
        )
        return

    # Find the actual key in banned.json
    ban_key = (
        f"discord:{discord_id}" if discord_id else
        f"anilist:{anilist_id}" if anilist_id else
        f"mal:{mal_id}"         if mal_id     else
        f"simkl:{simkl_id}"
    )

    preview = discord.Embed(title="✅ Confirm Unban", color=0x2EA043)
    preview.add_field(name="User", value=_ids_display(discord_id, anilist_id, mal_id, simkl_id), inline=False)
    preview.add_field(name="Original Reason", value=existing.get("reason", "N/A"), inline=False)
    preview.add_field(name="Banned by", value=existing.get("actioned_by_username", "Unknown"), inline=True)
    preview.add_field(
        name="Banned at",
        value=f"<t:{int(existing['actioned_at'])}:R>" if existing.get("actioned_at") else "Unknown",
        inline=True,
    )
    preview.set_footer(text="You have 60s to confirm.")

    view = ModerationConfirmView(
        action="unban",
        ban_key=ban_key,
        ban_record=existing,
        discord_member=None,
        actioned_by=interaction.user,
    )
    await interaction.followup.send(embed=preview, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# /mute_user
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="mute_user", description="Mute a user from community recommendations (temporary or permanent)")
@app_commands.describe(
    user="Search and select the user to mute",
    reason="Reason for the mute",
    duration_preset="Pick a preset duration",
    duration_custom="Or type a custom duration: e.g. 90m, 2h30m, 3d (overrides preset)",
)
@app_commands.autocomplete(user=mod_user_autocomplete)
@app_commands.choices(duration_preset=_DURATION_PRESETS)
async def mute_user(
    interaction: discord.Interaction,
    user: str,
    reason: str,
    duration_preset: app_commands.Choice[str] = None,
    duration_custom: str = None,
):
    await interaction.response.defer(ephemeral=True)

    if not await is_bot_admin(interaction.user.id):
        await interaction.followup.send("❌ Only bot admins can use this command.", ephemeral=True)
        return

    if user == "__none__":
        await interaction.followup.send("❌ Please select a user from the dropdown.", ephemeral=True)
        return

    discord_id, anilist_id, mal_id, simkl_id = _unpack_user_value(user)

    # Resolve duration — custom wins over preset
    duration_str = duration_custom or (duration_preset.value if duration_preset else None)
    duration_secs = _parse_duration(duration_str) if duration_str else None
    expires_at = time.time() + duration_secs if duration_secs else None

    # Check if already muted
    existing = await _get_ban_record(discord_id, anilist_id, mal_id, simkl_id)
    if existing and existing.get("type") == "mute":
        exp = existing.get("expires_at")
        exp_str = f"<t:{int(exp)}:R>" if exp else "permanent"
        await interaction.followup.send(
            f"⚠️ This user is already muted (expires {exp_str}). Use `/unmute_user` first.",
            ephemeral=True,
        )
        return

    # Validate custom duration if provided
    if duration_custom and duration_secs is None and duration_custom.lower() != "permanent":
        await interaction.followup.send(
            "❌ Invalid custom duration. Use formats like `90m`, `2h`, `1d12h`, `7d` or `permanent`.",
            ephemeral=True,
        )
        return

    ban_key = (
        f"discord:{discord_id}" if discord_id else
        f"anilist:{anilist_id}" if anilist_id else
        f"mal:{mal_id}"         if mal_id     else
        f"simkl:{simkl_id}"
    )

    mute_record = {
        "type": "mute",
        "reason": reason,
        "actioned_by_discord_id": str(interaction.user.id),
        "actioned_by_username":   interaction.user.name,
        "actioned_at":            time.time(),
        "expires_at":             expires_at,
        "identifiers": {
            "discord_id":  discord_id,
            "anilist_id":  anilist_id,
            "mal_id":      mal_id,
            "simkl_id":    simkl_id,
        },
    }

    duration_display = (
        f"{_fmt_duration(duration_secs)} (expires <t:{int(expires_at)}:R>)"
        if expires_at else "⚠️ Permanent"
    )

    preview = discord.Embed(title="🔇 Confirm Mute", color=0xFF6B35)
    preview.add_field(name="User", value=_ids_display(discord_id, anilist_id, mal_id, simkl_id), inline=False)
    preview.add_field(name="Reason", value=reason, inline=False)
    preview.add_field(name="Duration", value=duration_display, inline=False)
    preview.set_footer(text="This blocks all bot commands and API calls. You have 60s to confirm.")

    discord_member = None
    if discord_id and interaction.guild:
        try:
            discord_member = interaction.guild.get_member(int(discord_id)) or await interaction.guild.fetch_member(int(discord_id))
            if discord_member:
                preview.set_thumbnail(url=discord_member.display_avatar.url)
                preview.insert_field_at(0, name="Discord", value=f"{discord_member.mention} (`{discord_member}`)", inline=False)
        except Exception:
            pass

    view = ModerationConfirmView(
        action="mute",
        ban_key=ban_key,
        ban_record=mute_record,
        discord_member=discord_member,
        actioned_by=interaction.user,
    )
    await interaction.followup.send(embed=preview, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# /unmute_user
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="unmute_user", description="Unmute a user from community recommendations")
@app_commands.describe(user="Search and select the user to unmute")
@app_commands.autocomplete(user=mod_user_autocomplete)
async def unmute_user(interaction: discord.Interaction, user: str):
    await interaction.response.defer(ephemeral=True)

    if not await is_bot_admin(interaction.user.id):
        await interaction.followup.send("❌ Only bot admins can use this command.", ephemeral=True)
        return

    if user == "__none__":
        await interaction.followup.send("❌ Please select a user from the dropdown.", ephemeral=True)
        return

    discord_id, anilist_id, mal_id, simkl_id = _unpack_user_value(user)

    existing = await _get_ban_record(discord_id, anilist_id, mal_id, simkl_id)
    if not existing:
        await interaction.followup.send("❌ This user is not currently muted.", ephemeral=True)
        return
    if existing.get("type") != "mute":
        await interaction.followup.send(
            f"⚠️ This user has a `{existing.get('type')}` record, not a mute. Use the correct command.",
            ephemeral=True,
        )
        return

    ban_key = (
        f"discord:{discord_id}" if discord_id else
        f"anilist:{anilist_id}" if anilist_id else
        f"mal:{mal_id}"         if mal_id     else
        f"simkl:{simkl_id}"
    )

    exp = existing.get("expires_at")
    preview = discord.Embed(title="🔉 Confirm Unmute", color=0x2EA043)
    preview.add_field(name="User", value=_ids_display(discord_id, anilist_id, mal_id, simkl_id), inline=False)
    preview.add_field(name="Original Reason", value=existing.get("reason", "N/A"), inline=False)
    preview.add_field(name="Muted by", value=existing.get("actioned_by_username", "Unknown"), inline=True)
    preview.add_field(
        name="Was set to expire",
        value=f"<t:{int(exp)}:R>" if exp else "Permanent",
        inline=True,
    )
    preview.set_footer(text="You have 60s to confirm.")

    view = ModerationConfirmView(
        action="unmute",
        ban_key=ban_key,
        ban_record=existing,
        discord_member=None,
        actioned_by=interaction.user,
    )
    await interaction.followup.send(embed=preview, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# /timeout_user  (bot/API timeout only — does NOT apply Discord server timeout)
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="timeout_user", description="Timeout a user from community recommendations (temporary)")
@app_commands.describe(
    user="Search and select the user to timeout",
    reason="Reason for the timeout",
    duration_preset="Pick a preset duration",
    duration_custom="Or type a custom duration: e.g. 90m, 2h30m, 3d",
)
@app_commands.autocomplete(user=mod_user_autocomplete)
@app_commands.choices(duration_preset=_DURATION_PRESETS)
async def timeout_user(
    interaction: discord.Interaction,
    user: str,
    reason: str,
    duration_preset: app_commands.Choice[str] = None,
    duration_custom: str = None,
):
    await interaction.response.defer(ephemeral=True)

    if not await is_bot_admin(interaction.user.id):
        await interaction.followup.send("❌ Only bot admins can use this command.", ephemeral=True)
        return

    if user == "__none__":
        await interaction.followup.send("❌ Please select a user from the dropdown.", ephemeral=True)
        return

    discord_id, anilist_id, mal_id, simkl_id = _unpack_user_value(user)

    # Resolve duration
    duration_str = duration_custom or (duration_preset.value if duration_preset else None)
    duration_secs = _parse_duration(duration_str) if duration_str else None

    if duration_custom and duration_secs is None and (not duration_str or duration_str.lower() != "permanent"):
        await interaction.followup.send(
            "❌ Invalid duration. Use formats like `90m`, `2h`, `1d12h`, `7d`.",
            ephemeral=True,
        )
        return

    # Cap at 28 days for Discord
    expires_at = time.time() + duration_secs if duration_secs else None

    ban_key = f"discord:{discord_id}"

    timeout_record = {
        "type": "timeout",
        "reason": reason,
        "actioned_by_discord_id": str(interaction.user.id),
        "actioned_by_username":   interaction.user.name,
        "actioned_at":            time.time(),
        "expires_at":             expires_at,
        "identifiers": {
            "discord_id":  discord_id,
            "anilist_id":  anilist_id,
            "mal_id":      mal_id,
            "simkl_id":    simkl_id,
        },
    }

    duration_display = (
        f"{_fmt_duration(duration_secs)} (until <t:{int(expires_at)}:f>)"
        if expires_at else "⚠️ Permanent"
    )

    preview = discord.Embed(title="⏱️ Confirm Timeout", color=0x9B59B6)
    preview.add_field(name="User", value=_ids_display(discord_id, anilist_id, mal_id, simkl_id), inline=False)
    preview.add_field(name="Reason", value=reason, inline=False)
    preview.add_field(name="Duration", value=duration_display, inline=False)
    preview.add_field(
        name="What happens",
        value="• Cannot use bot commands or API",
        inline=False,
    )
    preview.set_footer(text="You have 60s to confirm.")

    discord_member = None
    if discord_id and interaction.guild:
        try:
            discord_member = interaction.guild.get_member(int(discord_id)) or await interaction.guild.fetch_member(int(discord_id))
            if discord_member:
                preview.set_thumbnail(url=discord_member.display_avatar.url)
                preview.insert_field_at(0, name="Discord", value=f"{discord_member.mention} (`{discord_member}`)", inline=False)
        except Exception:
            pass

    view = ModerationConfirmView(
        action="timeout",
        ban_key=ban_key,
        ban_record=timeout_record,
        discord_member=discord_member,
        actioned_by=interaction.user,
    )
    await interaction.followup.send(embed=preview, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# /untimeout_user
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="untimeout_user", description="Lift a timeout from a user for community recommendations")
@app_commands.describe(user="Search and select the user to remove timeout from")
@app_commands.autocomplete(user=mod_user_autocomplete)
async def untimeout_user(interaction: discord.Interaction, user: str):
    await interaction.response.defer(ephemeral=True)

    if not await is_bot_admin(interaction.user.id):
        await interaction.followup.send("❌ Only bot admins can use this command.", ephemeral=True)
        return

    if user == "__none__":
        await interaction.followup.send("❌ Please select a user from the dropdown.", ephemeral=True)
        return

    discord_id, anilist_id, mal_id, simkl_id = _unpack_user_value(user)

    if not discord_id:
        await interaction.followup.send("❌ Timeout removal requires a Discord ID.", ephemeral=True)
        return

    existing = await _get_ban_record(discord_id, anilist_id, mal_id, simkl_id)
    if not existing:
        await interaction.followup.send("❌ No active timeout record found for this user.", ephemeral=True)
        return
    if existing.get("type") != "timeout":
        await interaction.followup.send(
            f"⚠️ This user has a `{existing.get('type')}` record, not a timeout.",
            ephemeral=True,
        )
        return

    discord_member = None
    if interaction.guild:
        try:
            discord_member = interaction.guild.get_member(int(discord_id)) or await interaction.guild.fetch_member(int(discord_id))
        except Exception:
            pass

    ban_key = f"discord:{discord_id}"
    exp = existing.get("expires_at")

    preview = discord.Embed(title="✅ Confirm Remove Timeout", color=0x2EA043)
    if discord_member:
        preview.add_field(name="User", value=f"{discord_member.mention} (`{discord_member}`)", inline=False)
        preview.set_thumbnail(url=discord_member.display_avatar.url)
    else:
        preview.add_field(name="User", value=f"`{discord_id}`", inline=False)
    preview.add_field(name="Original Reason", value=existing.get("reason", "N/A"), inline=False)
    preview.add_field(name="Timed out by", value=existing.get("actioned_by_username", "Unknown"), inline=True)
    preview.add_field(
        name="Was set to expire",
        value=f"<t:{int(exp)}:R>" if exp else "Permanent",
        inline=True,
    )
    preview.set_footer(text="You have 60s to confirm.")

    view = ModerationConfirmView(
        action="untimeout",
        ban_key=ban_key,
        ban_record=existing,
        discord_member=discord_member,
        actioned_by=interaction.user,
    )
    await interaction.followup.send(embed=preview, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-expiry background task
# Start this in on_ready inside _bg_init() with:
#   asyncio.create_task(_mute_expiry_task())
# ─────────────────────────────────────────────────────────────────────────────

async def _mute_expiry_task():
    """
    Runs every 60 seconds.
    Finds expired mute/timeout records in banned.json, removes them,
    and sends a log embed for each.
    """
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(60)
        try:
            now = time.time()
            async with aiohttp.ClientSession() as session:
                banned, sha = await read_banned(session)

            if not isinstance(banned, dict) or not banned:
                continue

            expired = {
                k: v for k, v in banned.items()
                if v.get("expires_at") and now > v["expires_at"]
            }
            if not expired:
                continue

            for key, rec in expired.items():
                banned.pop(key)
                ban_type  = rec.get("type", "mute")
                ids       = rec.get("identifiers", {})
                discord_id = ids.get("discord_id")
                reason    = rec.get("reason", "N/A")
                by        = rec.get("actioned_by_username", "Unknown")
                acted_at  = rec.get("actioned_at", 0)
                exp_at    = rec.get("expires_at", 0)
                duration  = exp_at - acted_at if acted_at else 0


                # Log
                emojis = {"ban": "🔨", "mute": "🔇", "timeout": "⏱️"}
                log = discord.Embed(
                    title=f"⏰ {ban_type.title()} Auto-Expired",
                    color=0x2EA043,
                )
                log.add_field(name="Key",       value=key, inline=True)
                log.add_field(name="Type",      value=ban_type, inline=True)
                log.add_field(name="Duration was", value=_fmt_duration(duration), inline=True)
                log.add_field(name="Reason",    value=rec.get("reason", "N/A"), inline=False)
                log.add_field(name="Actioned by", value=by, inline=True)
                log.add_field(
                    name="IDs",
                    value=_ids_display(
                        discord_id=ids.get("discord_id"),
                        anilist_id=ids.get("anilist_id"),
                        mal_id=ids.get("mal_id"),
                        simkl_id=ids.get("simkl_id"),
                    ),
                    inline=False,
                )
                log.set_footer(text="Auto-lifted by expiry task")
                await _send_log(log)
                print(f"✅ [Expiry] Auto-lifted {ban_type} for {key}")

            # Save cleaned banned.json
            async with aiohttp.ClientSession() as session:
                _, sha2 = await read_banned(session)
                await write_banned(
                    session, banned, sha2,
                    f"auto: lifted {len(expired)} expired record(s)",
                )

        except Exception as e:
            print(f"⚠️ [MuteExpiry] Error: {type(e).__name__}: {e}")
