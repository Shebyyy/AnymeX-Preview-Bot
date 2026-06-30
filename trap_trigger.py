# ══════════════════════════════════════════════════════════════════════════════
# trap_trigger.py  —  Trap channel for hacked accounts / spam bots
# ══════════════════════════════════════════════════════════════════════════════
#
# HOW IT WORKS:
#   You set a "trap channel" (e.g. #spam-bait). Anyone who posts ANYTHING in
#   that channel gets immediately temp-banned and their recent messages are
#   deleted from ALL channels.
#
#   Unban records are stored in a GitHub JSON file (trap_bans.json) so the
#   bot can auto-unban even after a restart/crash/redeploy.
#
# WHITELIST:
#   - Roles listed in TRAP_WHITELIST_ROLE_IDS are immune
#   - Users listed in TRAP_WHITELIST_USER_IDS are immune
#   - Bots are NOT immune — their message is deleted but no ban (can't ban bots)
#
# CONFIG (env vars):
#   TRAP_CHANNEL_ID            — the bait channel ID
#   TRAP_BAN_DURATION          — seconds to ban (default 3600 = 1 hour)
#   TRAP_WHITELIST_ROLE_IDS    — comma-separated role IDs (immune)
#   TRAP_WHITELIST_USER_IDS    — comma-separated user IDs (immune)
#   TRAP_LOG_CHANNEL_ID        — where to log bans (optional)
#
# SLASH COMMANDS (admin-only):
#   /trap_config               — show current config
#   /trap_unban                — manually unban someone early
#   /trap_whitelist_role       — add/remove/list whitelisted roles
#   /trap_whitelist_user       — add/remove/list whitelisted users
#   /trap_duration <seconds>   — change ban duration
# ══════════════════════════════════════════════════════════════════════════════

import os
import time
import asyncio
import aiohttp
import discord
from discord import app_commands

# ─────────────────────────────────────────────────────────────────────────────
# Config (loaded from env vars)
# ─────────────────────────────────────────────────────────────────────────────

FILE_TRAP_BANS = "trap_bans.json"

BAN_REASON = "🪤 Auto-ban: Posted in scam detection channel"

def _parse_int_set(env_var: str) -> set[int]:
    """Parse comma-separated IDs from env var into a set of ints."""
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return set()
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return result


def _parse_int(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var, "").strip()
    if raw.isdigit():
        return int(raw)
    return default


# Mutable config — can be changed at runtime via slash commands
_config = {
    "channel_id": _parse_int("TRAP_CHANNEL_ID", 0),
    "ban_duration": _parse_int("TRAP_BAN_DURATION", 3600),  # 1 hour
    "whitelist_role_ids": _parse_int_set("TRAP_WHITELIST_ROLE_IDS"),
    "whitelist_user_ids": _parse_int_set("TRAP_WHITELIST_USER_IDS"),
    "log_channel_id": _parse_int("TRAP_LOG_CHANNEL_ID", 0),
}

# GitHub storage functions (injected from bot.py via setup())
_github_read_json_fn = None
_github_write_json_fn = None
_userdata_repo = None
_userdata_branch = None

_bot = None


# ─────────────────────────────────────────────────────────────────────────────
# GitHub storage for ban records
# ─────────────────────────────────────────────────────────────────────────────

async def _read_bans_from_github() -> tuple[dict, str | None]:
    """Read trap_bans.json from GitHub. Returns (bans_dict, sha).

    bans_dict shape:
        {
          "guild_id:user_id": {
            "user_id": 123,
            "username": "spammer#1234",
            "guild_id": 456,
            "guild_name": "Server Name",
            "channel_id": 789,
            "banned_at": 1700000000,
            "unban_at": 1700003600,
            "duration_seconds": 3600,
            "message_content": "free nitro click here",
            "unbanned": false
          },
          ...
        }
    """
    if not _github_read_json_fn:
        return {}, None
    try:
        async with aiohttp.ClientSession() as session:
            data, sha = await _github_read_json_fn(
                session, FILE_TRAP_BANS,
                repo=_userdata_repo, branch=_userdata_branch,
            )
            if not isinstance(data, dict):
                return {}, sha
            return data, sha
    except Exception as e:
        print(f"[trap_trigger] Read bans from GitHub error: {e}")
        return {}, None


async def _write_bans_to_github(data: dict, sha: str | None, commit_msg: str) -> bool:
    """Write trap_bans.json to GitHub. Returns True on success, False on failure."""
    if not _github_write_json_fn:
        print("[trap_trigger] ❌ Cannot write bans: no GitHub write function configured")
        return False
    try:
        async with aiohttp.ClientSession() as session:
            ok = await _github_write_json_fn(
                session, FILE_TRAP_BANS, data, sha, commit_msg,
                repo=_userdata_repo, branch=_userdata_branch,
            )
        if not ok:
            print(
                f"[trap_trigger] ❌ GitHub write FAILED for {FILE_TRAP_BANS} "
                f"(repo={_userdata_repo}, branch={_userdata_branch}, sha={'new file' if sha is None else 'update'})"
            )
        return bool(ok)
    except Exception as e:
        print(f"[trap_trigger] ❌ Write bans to GitHub error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Whitelist check
# ─────────────────────────────────────────────────────────────────────────────

def _is_whitelisted(member: discord.Member) -> bool:
    """Check if a member is immune to the trap."""
    # Whitelisted user IDs
    if member.id in _config["whitelist_user_ids"]:
        return True

    # Whitelisted roles
    try:
        member_role_ids = {r.id for r in member.roles}
    except Exception:
        member_role_ids = set()
    if member_role_ids & _config["whitelist_role_ids"]:
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Core trap logic
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_trap_message(message: discord.Message):
    """Check if a message is in the trap channel and ban the user if so."""
    # Skip if trap not configured
    if not _config["channel_id"]:
        return

    # Skip if not in trap channel
    if message.channel.id != _config["channel_id"]:
        return

    # Must be in a guild
    if not message.guild:
        return

    # Get member (might be cached)
    member = message.guild.get_member(message.author.id)
    if member is None:
        try:
            member = await message.guild.fetch_member(message.author.id)
        except Exception:
            member = None

    # Whitelist check — only whitelisted roles/users are immune
    if member and _is_whitelisted(member):
        return

    # ── NOT whitelisted → action ──
    user = message.author
    guild = message.guild
    duration = _config["ban_duration"]
    is_bot = user.bot

    # Try to DM the user first (before ban, so they know what happened)
    # Skip for bots (they don't read DMs)
    if not is_bot:
        try:
            await user.send(
                f"🪤 You were caught in the **scam detection channel** in **{guild.name}**.\n"
                f"You are temp-banned for **{_format_duration(duration)}**.\n"
                f"You will be auto-unbanned when the timer expires.\n"
                f"If this was a mistake, contact a moderator of the server."
            )
        except Exception:
            pass  # DMs closed — that's fine

    # Delete the trap message immediately (so others don't see the spam)
    try:
        await message.delete()
        print(f"[trap_trigger] Deleted trap message from {user}")
    except Exception as e:
        print(f"[trap_trigger] Could not delete trap message: {e}")

    # ── Bots: just delete the message, don't ban (Discord doesn't allow banning bots) ──
    if is_bot:
        print(f"[trap_trigger] 🦘 Bot {user} message deleted (no ban for bots)")
        await _log_trap(user, guild, message.channel, duration, "deleted")
        return

    # ── Real user → BAN ──
    action_taken = "none"
    try:
        await guild.ban(
            user,
            reason=BAN_REASON,
            delete_message_seconds=duration,  # wipe their messages from the ban window
        )
        action_taken = "banned"
        print(f"[trap_trigger] Banned {user} for {duration}s (trap channel)")
    except discord.Forbidden:
        print(f"[trap_trigger] ❌ Missing Ban permission or cannot ban {user}")
    except discord.HTTPException as e:
        if e.code == 50013:  # Missing permissions / can't ban owner
            print(f"[trap_trigger] ❌ Cannot ban {user} (likely server owner or higher role)")
        else:
            print(f"[trap_trigger] ❌ Ban HTTP error: {e}")

    # ── Record the ban in GitHub for auto-unban ──
    if action_taken == "banned":
        await _record_ban(user, guild, message.channel, duration, message.content)

    # Log to log channel if configured
    await _log_trap(user, guild, message.channel, duration, action_taken)


async def _record_ban(
    user: discord.abc.User,
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    duration: int,
    message_content: str,
):
    """Record a ban in the GitHub JSON file so we can auto-unban later."""
    now = int(time.time())
    unban_at = now + duration

    # Truncate message content for storage (keep it small)
    content_preview = (message_content or "")[:200]

    bans, sha = await _read_bans_from_github()

    key = f"{guild.id}:{user.id}"
    bans[key] = {
        "user_id": user.id,
        "username": str(user),
        "guild_id": guild.id,
        "guild_name": guild.name,
        "channel_id": channel.id,
        "banned_at": now,
        "unban_at": unban_at,
        "duration_seconds": duration,
        "message_content": content_preview,
    }

    ok = await _write_bans_to_github(
        bans, sha, f"🪤 Trap ban: {user} in {guild.name} (unban at {unban_at})"
    )
    if ok:
        print(f"[trap_trigger] ✅ Recorded ban in GitHub: {key} → unban at {unban_at}")
    else:
        print(f"[trap_trigger] ❌ FAILED to record ban in GitHub: {key} (user is banned but won't auto-unban!)")


# ─────────────────────────────────────────────────────────────────────────────
# Logging to Discord channel
# ─────────────────────────────────────────────────────────────────────────────

async def _log_trap(
    user: discord.abc.User,
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    duration: int,
    action: str,
):
    """Send a log message to the log channel (if configured).

    action: "banned" | "deleted" | "none" (failed)
    """
    if not _config["log_channel_id"]:
        return

    log_channel = guild.get_channel(_config["log_channel_id"])
    if not log_channel:
        return

    status_map = {
        "banned":  ("✅ Banned (temp)", 0xFF4444),
        "deleted": ("🦘 Message deleted (bot)", 0x9B59B6),
        "none":    ("❌ Action failed (check permissions)", 0xFF8800),
    }
    status_text, color = status_map.get(action, ("❓ Unknown", 0xFF8800))

    embed = discord.Embed(
        title="🪤 Trap Triggered",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)" + (" 🦾 [BOT]" if user.bot else ""), inline=False)
    embed.add_field(name="Channel", value=f"<#{channel.id}>", inline=True)
    embed.add_field(name="Duration", value=_format_duration(duration), inline=True)
    embed.add_field(name="Action", value=status_text, inline=False)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)

    try:
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"[trap_trigger] Could not send log: {e}")


def _format_duration(seconds: int) -> str:
    """Human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


# ─────────────────────────────────────────────────────────────────────────────
# Auto-unban background task
# ─────────────────────────────────────────────────────────────────────────────

async def _auto_unban_loop():
    """Background task that runs every 60 seconds.

    Reads trap_bans.json from GitHub, finds expired bans, unbans users,
    and marks them as unbanned in the JSON. Survives bot restarts because
    the unban time lives in the GitHub file, not in memory.
    """
    await _bot.wait_until_ready()
    print("✅ [trap_trigger] Auto-unban loop started")

    while not _bot.is_closed():
        try:
            now = int(time.time())
            bans, sha = await _read_bans_from_github()

            if not bans:
                await asyncio.sleep(60)
                continue

            changed = False
            keys_to_delete = []
            for key, record in list(bans.items()):
                # Skip already unbanned (cleanup pass — delete old records)
                if record.get("unbanned"):
                    keys_to_delete.append(key)
                    changed = True
                    continue

                unban_at = record.get("unban_at", 0)
                if now < unban_at:
                    continue  # not yet time

                user_id = record.get("user_id")
                guild_id = record.get("guild_id")
                if not user_id or not guild_id:
                    keys_to_delete.append(key)
                    changed = True
                    continue

                guild = _bot.get_guild(guild_id)
                if not guild:
                    # Bot not in this guild anymore — delete record (can't unban)
                    keys_to_delete.append(key)
                    changed = True
                    continue

                try:
                    user = await _bot.fetch_user(user_id)
                except Exception:
                    user = None

                try:
                    await guild.unban(
                        user or discord.Object(id=user_id),
                        reason="Trap temp-ban expired (auto-unban)",
                    )
                    print(f"[trap_trigger] ✅ Auto-unbanned {user_id} (trap timer expired)")
                    # Try to DM them
                    if user:
                        try:
                            await user.send(
                                f"✅ Your trap temp-ban in **{guild.name}** has expired. "
                                f"You can rejoin the server."
                            )
                        except Exception:
                            pass
                except discord.NotFound:
                    # Already unbanned — fine, just delete the record
                    print(f"[trap_trigger] User {user_id} already unbanned")
                except Exception as e:
                    print(f"[trap_trigger] Error unbanning {user_id}: {e}")
                    continue  # try again next loop

                # Mark for deletion (don't keep records after unban)
                keys_to_delete.append(key)
                changed = True

            # Delete all processed records
            for key in keys_to_delete:
                bans.pop(key, None)

            if changed:
                await _write_bans_to_github(
                    bans, sha, f"🪤 Trap auto-unban cycle — removed expired records"
                )

        except Exception as e:
            print(f"[trap_trigger] Auto-unban loop error: {e}")

        # Run every 60 seconds
        await asyncio.sleep(60)


# ─────────────────────────────────────────────────────────────────────────────
# Slash commands (admin-only)
# ─────────────────────────────────────────────────────────────────────────────

def _is_admin(interaction: discord.Interaction) -> bool:
    """Check if the user is a guild administrator."""
    if not interaction.user:
        return False
    # guild.owner check
    if interaction.guild and interaction.user.id == interaction.guild.owner_id:
        return True
    # administrator permission
    if isinstance(interaction.user, discord.Member):
        return interaction.user.guild_permissions.administrator
    return False


def _register_slash_commands(bot: discord.Client):
    """Register all trap slash commands on the bot's command tree."""

    @bot.tree.command(
        name="trap_config",
        description="Show current trap channel configuration (Admin only)",
    )
    @app_commands.default_permissions(administrator=True)
    async def trap_config(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        channel = f"<#{_config['channel_id']}>" if _config["channel_id"] else "❌ Not set"
        log_ch = f"<#{_config['log_channel_id']}>" if _config["log_channel_id"] else "Not set"

        roles_str = "None" if not _config["whitelist_role_ids"] else ", ".join(
            f"<@&{r}>" for r in _config["whitelist_role_ids"]
        )
        users_str = "None" if not _config["whitelist_user_ids"] else ", ".join(
            f"<@{u}>" for u in _config["whitelist_user_ids"]
        )

        embed = discord.Embed(
            title="🪤 Trap Channel Configuration",
            color=0x5865F2,
        )
        embed.add_field(name="Trap Channel", value=channel, inline=False)
        embed.add_field(name="Ban Duration", value=_format_duration(_config["ban_duration"]), inline=False)
        embed.add_field(name="Whitelisted Roles", value=roles_str, inline=False)
        embed.add_field(name="Whitelisted Users", value=users_str, inline=False)
        embed.add_field(name="Log Channel", value=log_ch, inline=False)
        embed.add_field(name="Ban Reason", value=f"`{BAN_REASON}`", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="trap_unban",
        description="Manually unban a user from a trap ban early (Admin only)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user_id="The user ID to unban (right-click user → Copy ID)")
    async def trap_unban(interaction: discord.Interaction, user_id: str):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ Must be in a server.", ephemeral=True)
            return

        try:
            uid = int(user_id.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return

        try:
            user = await _bot.fetch_user(uid)
        except Exception:
            user = None

        # Unban on Discord
        try:
            await interaction.guild.unban(
                user or discord.Object(id=uid),
                reason=f"Trap temp-ban manually ended by {interaction.user}",
            )
            discord_unbanned = True
        except discord.NotFound:
            discord_unbanned = False
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
            return

        # Remove the record from GitHub (no need to keep records after unban)
        bans, sha = await _read_bans_from_github()
        key = f"{interaction.guild_id}:{uid}"
        if key in bans:
            bans.pop(key, None)
            await _write_bans_to_github(bans, sha, f"🪤 Trap manual unban: removed {uid}")

        msg = f"✅ Unbanned `{uid}`" + (f" ({user})" if user else "")
        if not discord_unbanned:
            msg += "\nℹ️ (User wasn't in Discord ban list, but GitHub record marked as unbanned)"
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(
        name="trap_whitelist_role",
        description="Add/remove/list whitelisted roles for the trap (Admin only)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(action="add, remove, or list", role="Role to configure")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
            app_commands.Choice(name="list", value="list"),
        ]
    )
    async def trap_whitelist_role(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        role: discord.Role = None,
    ):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        if action.value == "list":
            if not _config["whitelist_role_ids"]:
                await interaction.response.send_message(
                    "📋 Whitelisted roles: **None**", ephemeral=True
                )
                return
            msg = "**📋 Whitelisted roles:**\n" + "\n".join(
                f"<@&{r}> (`{r}`)" for r in _config["whitelist_role_ids"]
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if not role:
            await interaction.response.send_message("❌ Please provide a role.", ephemeral=True)
            return

        if action.value == "add":
            if role.id in _config["whitelist_role_ids"]:
                await interaction.response.send_message(
                    f"⚠️ {role.mention} is already whitelisted.", ephemeral=True
                )
                return
            _config["whitelist_role_ids"].add(role.id)
            await interaction.response.send_message(
                f"✅ Added {role.mention} to trap whitelist.\n"
                f"⚠️ Note: this is in-memory — set `TRAP_WHITELIST_ROLE_IDS` env var for persistence across restarts.",
                ephemeral=True,
            )
        else:  # remove
            if role.id not in _config["whitelist_role_ids"]:
                await interaction.response.send_message(
                    f"❌ {role.mention} is not in the whitelist.", ephemeral=True
                )
                return
            _config["whitelist_role_ids"].discard(role.id)
            await interaction.response.send_message(
                f"✅ Removed {role.mention} from trap whitelist.", ephemeral=True
            )

    @bot.tree.command(
        name="trap_whitelist_user",
        description="Add/remove/list whitelisted users for the trap (Admin only)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(action="add, remove, or list", user="User to configure")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
            app_commands.Choice(name="list", value="list"),
        ]
    )
    async def trap_whitelist_user(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        user: discord.User = None,
    ):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        if action.value == "list":
            if not _config["whitelist_user_ids"]:
                await interaction.response.send_message(
                    "📋 Whitelisted users: **None**", ephemeral=True
                )
                return
            msg = "**📋 Whitelisted users:**\n" + "\n".join(
                f"<@{u}> (`{u}`)" for u in _config["whitelist_user_ids"]
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if not user:
            await interaction.response.send_message("❌ Please provide a user.", ephemeral=True)
            return

        if action.value == "add":
            if user.id in _config["whitelist_user_ids"]:
                await interaction.response.send_message(
                    f"⚠️ {user.mention} is already whitelisted.", ephemeral=True
                )
                return
            _config["whitelist_user_ids"].add(user.id)
            await interaction.response.send_message(
                f"✅ Added {user.mention} to trap whitelist.\n"
                f"⚠️ Note: this is in-memory — set `TRAP_WHITELIST_USER_IDS` env var for persistence across restarts.",
                ephemeral=True,
            )
        else:  # remove
            if user.id not in _config["whitelist_user_ids"]:
                await interaction.response.send_message(
                    f"❌ {user.mention} is not in the whitelist.", ephemeral=True
                )
                return
            _config["whitelist_user_ids"].discard(user.id)
            await interaction.response.send_message(
                f"✅ Removed {user.mention} from trap whitelist.", ephemeral=True
            )

    @bot.tree.command(
        name="trap_duration",
        description="Change the trap ban duration (Admin only)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        seconds="Ban duration in seconds (e.g. 3600 = 1 hour, 86400 = 1 day)"
    )
    async def trap_duration(interaction: discord.Interaction, seconds: int):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        if seconds < 60:
            await interaction.response.send_message(
                "❌ Duration must be at least 60 seconds.", ephemeral=True
            )
            return
        if seconds > 604800:  # 7 days — Discord's max for delete_message_seconds
            await interaction.response.send_message(
                "❌ Duration must be at most 604800 seconds (7 days).", ephemeral=True
            )
            return

        _config["ban_duration"] = seconds
        await interaction.response.send_message(
            f"✅ Trap ban duration set to **{_format_duration(seconds)}**.\n"
            f"⚠️ Note: this is in-memory — set `TRAP_BAN_DURATION` env var for persistence across restarts.",
            ephemeral=True,
        )

    @bot.tree.command(
        name="trap_list",
        description="List all active trap bans (Admin only)",
    )
    @app_commands.default_permissions(administrator=True)
    async def trap_list(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        bans, _ = await _read_bans_from_github()
        # All records in GitHub are active (we delete them on unban)
        active = bans

        if not active:
            await interaction.followup.send("📋 No active trap bans.", ephemeral=True)
            return

        now = int(time.time())
        lines = ["**📋 Active trap bans:**\n"]
        for key, r in list(active.items())[:20]:  # limit to 20
            remaining = r.get("unban_at", 0) - now
            if remaining < 0:
                remaining_str = "expiring..."
            else:
                remaining_str = _format_duration(remaining)
            lines.append(
                f"• <@{r['user_id']}> (`{r['user_id']}`) — "
                f"{r.get('guild_name', '?')} — "
                f"remaining: **{remaining_str}**"
            )

        if len(active) > 20:
            lines.append(f"\n*...and {len(active) - 20} more*")

        await interaction.followup.send("\n".join(lines), ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

def setup(
    bot: discord.Client,
    github_read_json_fn=None,
    github_write_json_fn=None,
    userdata_repo: str = None,
    userdata_branch: str = None,
):
    """Set up the trap trigger module.

    Pass the GitHub read/write functions so we can store ban records in
    trap_bans.json in the userdata repo (for auto-unban after restarts).
    """
    global _bot
    global _github_read_json_fn, _github_write_json_fn
    global _userdata_repo, _userdata_branch

    _bot = bot
    _github_read_json_fn = github_read_json_fn
    _github_write_json_fn = github_write_json_fn
    _userdata_repo = userdata_repo
    _userdata_branch = userdata_branch

    @bot.listen("on_message")
    async def on_message_trap(message: discord.Message):
        await _handle_trap_message(message)

    @bot.listen("on_message_edit")
    async def on_message_edit_trap(before: discord.Message, after: discord.Message):
        # Catch edits too (someone tries to sneak in via editing an old message)
        await _handle_trap_message(after)

    # Register slash commands
    _register_slash_commands(bot)

    # Start auto-unban background task
    asyncio.create_task(_auto_unban_loop())

    # Status report
    storage = "GitHub" if _github_read_json_fn else "⚠️ no GitHub storage (ban records won't persist!)"
    if _config["channel_id"]:
        status = (
            f"✅ trap_trigger loaded — watching <#{_config['channel_id']}> — "
            f"ban: {_format_duration(_config['ban_duration'])} — "
            f"whitelisted roles: {len(_config['whitelist_role_ids'])}, "
            f"users: {len(_config['whitelist_user_ids'])} — "
            f"storage: {storage}"
        )
    else:
        status = (
            "⚠️ trap_trigger loaded but TRAP_CHANNEL_ID is not set — "
            "set it via env var to activate the trap."
        )
    print(status)
