# ══════════════════════════════════════════════════════════════════════════════
# nickname_lock.py — Nickname Lock with Dual Sync (GitHub + local disk)
# ══════════════════════════════════════════════════════════════════════════════
# Locks a member's server nickname. If they (or anyone) change it, the bot
# puts it back.
#
# Commands (slash and prefix). All three need Manage Nicknames or Administrator,
# checked server-side on every call, plus Discord's role-hierarchy rule:
#   /locknick set @user <nickname>      ?locknick set @user <nickname>
#   /locknick remove <autocomplete>     ?locknick remove @user
#       (nobody can remove their own lock, even with the permission)
#   /locknick list                      ?locknick list
#
# Storage (same pattern as custom_triggers.py):
#   - GitHub (primary): Shebyyy/AnymeX-Preview, branch "beta",
#     file  bot_data/locked_nicknames.json
#   - Local disk (backup): <data dir>/locked_nicknames.json + last 20 snapshots
#   - Load: GitHub first, fall back to local disk
#   - GitHub is written only when a lock is set or removed. Reverts use memory.
#
# Layout of the JSON file:
#   { "<guild_id>": { "<user_id>": { "nickname": str, "set_by": int, "set_at": str } } }
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import json
import time
import glob
import asyncio
import aiohttp
import discord
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any
from discord import app_commands

# Proper place on GitHub: its own folder in the main repo (beta branch),
# not mixed in with the root data files. Change this one constant to move it.
FILE_LOCKED_NICKS = "bot_data/locked_nicknames.json"

_LOCAL_NAME = "locked_nicknames.json"
_bot_data_env = os.environ.get("BOT_DATA_DIR", "")
if _bot_data_env and os.path.isdir(_bot_data_env):
    LOCAL_DATA_DIR = _bot_data_env
elif os.path.isdir("/root/bot_data"):
    LOCAL_DATA_DIR = "/root/bot_data"
else:
    LOCAL_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

LOCAL_BACKUPS_DIR = os.path.join(LOCAL_DATA_DIR, "backups")
LOCAL_PATH = os.path.join(LOCAL_DATA_DIR, _LOCAL_NAME)

MAX_NICK_LEN = 32
AUDIT_INTERVAL = 300      # seconds between full re-checks of all locks
REVERT_DELAY = 1.0        # seconds to wait before reverting (rate-limit friendly)

# guild_id (str) -> user_id (str) -> {"nickname", "set_by", "set_at"}
LOCKS: Dict[str, Dict[str, Dict[str, Any]]] = {}

_bot: Optional[discord.Client] = None
_get_prefixes_fn: Optional[Callable] = None
_github_read_json_fn: Optional[Callable] = None
_github_write_json_fn: Optional[Callable] = None
_send_log_fn: Optional[Callable] = None

_save_lock = asyncio.Lock()
_user_locks: Dict[tuple, asyncio.Lock] = {}
_warned: set = set()      # (guild_id, user_id) we already warned about (can't edit)
_audit_started = False
_loaded = asyncio.Event()   # set once startup load has finished


# ── Local disk ────────────────────────────────────────────────────────────────

def _ensure_dirs():
    os.makedirs(LOCAL_DATA_DIR, exist_ok=True)
    os.makedirs(LOCAL_BACKUPS_DIR, exist_ok=True)


def _load_local() -> Dict[str, Dict[str, Dict[str, Any]]]:
    _ensure_dirs()
    if os.path.exists(LOCAL_PATH):
        try:
            with open(LOCAL_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"⚠️ Error reading local {LOCAL_PATH}: {e}")
    return {}


def _save_local(data: Dict[str, Any]) -> bool:
    """Write the local copy plus a timestamped backup (keep last 20)."""
    _ensure_dirs()
    try:
        with open(LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        ts = int(time.time())
        backup = os.path.join(LOCAL_BACKUPS_DIR, f"locked_nicknames_{ts}.json")
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        backups = sorted(glob.glob(os.path.join(LOCAL_BACKUPS_DIR, "locked_nicknames_*.json")))
        for old in backups[:-20]:
            try:
                os.remove(old)
            except OSError:
                pass
        return True
    except Exception as e:
        print(f"❌ Error saving local locked nicknames: {e}")
        return False


# ── Dual persistence ──────────────────────────────────────────────────────────

def get_locks() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return LOCKS


async def load_locks():
    try:
        await _load_locks_inner()
    finally:
        _loaded.set()


async def _load_locks_inner():
    """Startup: GitHub first, local disk as fallback. Keeps both in sync."""
    global LOCKS
    _ensure_dirs()
    loaded = False

    if _github_read_json_fn:
        try:
            async with aiohttp.ClientSession() as session:
                data, sha = await _github_read_json_fn(session, FILE_LOCKED_NICKS)
                if isinstance(data, dict) and data:
                    LOCKS = data
                    loaded = True
                    _save_local(LOCKS)
                    print(f"✅ Loaded nickname locks from GitHub ({FILE_LOCKED_NICKS})")
                elif sha is None:
                    print(f"ℹ️ {FILE_LOCKED_NICKS} not found on GitHub, checking local disk...")
        except Exception as e:
            print(f"⚠️ Failed to fetch {FILE_LOCKED_NICKS} from GitHub: {e}")

    if not loaded:
        local = _load_local()
        if local:
            LOCKS = local
            print("✅ Loaded nickname locks from local disk backup")
            # GitHub was empty/unreachable: push the local copy up
            await _save_locks("Restore nickname locks from local backup")
        else:
            LOCKS = {}
            print("ℹ️ No existing nickname locks found.")


async def _save_locks(commit_msg: str) -> bool:
    """Save locally first, then push to GitHub. Returns GitHub result."""
    async with _save_lock:
        _save_local(LOCKS)
        if _github_read_json_fn and _github_write_json_fn:
            try:
                async with aiohttp.ClientSession() as session:
                    _, sha = await _github_read_json_fn(session, FILE_LOCKED_NICKS)
                    ok = await _github_write_json_fn(session, FILE_LOCKED_NICKS, LOCKS, sha, commit_msg)
                    if not ok:
                        print("⚠️ Failed to push nickname locks to GitHub (saved locally)")
                    return ok
            except Exception as e:
                print(f"⚠️ Error syncing nickname locks to GitHub: {e}")
                return False
        return True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(embed: discord.Embed):
    if _send_log_fn:
        try:
            res = _send_log_fn(embed)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
        except Exception as e:
            print(f"⚠️ nickname_lock log failed: {e}")


def _log_embed(title: str, desc: str, color: int = 0x5865F2) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color, timestamp=datetime.now(timezone.utc))


def _user_lock(guild_id: int, user_id: int) -> asyncio.Lock:
    key = (guild_id, user_id)
    if key not in _user_locks:
        _user_locks[key] = asyncio.Lock()
    return _user_locks[key]


def _get_lock(guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    return LOCKS.get(str(guild_id), {}).get(str(user_id))


def _can_manage(invoker: discord.Member) -> bool:
    p = invoker.guild_permissions
    return p.administrator or p.manage_nicknames


def _check_hierarchy(guild: discord.Guild, invoker: discord.Member, target: discord.Member) -> Optional[str]:
    """Return an error string if the lock can't be applied, else None."""
    me = guild.me
    if target.id == guild.owner_id:
        return "I can't change the server owner's nickname."
    if not me.guild_permissions.manage_nicknames:
        return "I need the **Manage Nicknames** permission."
    if target.top_role >= me.top_role:
        return "That member's top role is at or above mine. Move my role higher."
    if invoker.id != guild.owner_id and target.top_role >= invoker.top_role:
        return "You can't lock someone whose top role is at or above yours."
    return None


def _validate_nick(nick: str) -> Optional[str]:
    nick = nick.strip()
    if not nick:
        return "Nickname can't be empty."
    if len(nick) > MAX_NICK_LEN:
        return f"Nickname must be {MAX_NICK_LEN} characters or less (got {len(nick)})."
    return None


# ── Enforcement ───────────────────────────────────────────────────────────────

async def _enforce(member: discord.Member, *, delay: float = REVERT_DELAY) -> bool:
    """Put the locked nickname back if it differs. Returns True if changed."""
    lock = _get_lock(member.guild.id, member.id)
    if not lock:
        return False
    wanted = lock["nickname"]

    async with _user_lock(member.guild.id, member.id):
        # Re-read inside the lock: another task may have fixed it already
        lock = _get_lock(member.guild.id, member.id)
        if not lock:
            return False
        wanted = lock["nickname"]
        if member.nick == wanted:
            return False

        if delay:
            await asyncio.sleep(delay)

        try:
            await member.edit(nick=wanted, reason="Nickname lock")
            _warned.discard((member.guild.id, member.id))
            _log(_log_embed(
                "🔒 Nickname Reverted",
                f"{member.mention} (`{member.id}`) was set back to **{wanted}**.",
                0xF1C40F,
            ))
            return True
        except discord.Forbidden:
            key = (member.guild.id, member.id)
            if key not in _warned:
                _warned.add(key)
                _log(_log_embed(
                    "⚠️ Nickname Lock Failed",
                    f"I can't edit {member.mention} (`{member.id}`). "
                    "Check my **Manage Nicknames** permission and role position.",
                    0xE74C3C,
                ))
            return False
        except discord.HTTPException as e:
            print(f"⚠️ nickname_lock revert failed for {member.id}: {e}")
            return False


async def _audit_guild(guild: discord.Guild):
    users = LOCKS.get(str(guild.id), {})
    for uid in list(users.keys()):
        member = guild.get_member(int(uid))
        if member is None:
            continue
        await _enforce(member, delay=0)
        await asyncio.sleep(0.5)


async def _audit_all():
    if not _bot:
        return
    for guild in list(_bot.guilds):
        if str(guild.id) in LOCKS:
            await _audit_guild(guild)


async def _audit_loop():
    await _bot.wait_until_ready()
    await _loaded.wait()
    await _audit_all()
    while not _bot.is_closed():
        await asyncio.sleep(AUDIT_INTERVAL)
        try:
            await _audit_all()
        except Exception as e:
            print(f"⚠️ nickname_lock audit error: {e}")


# ── Core actions (shared by slash and prefix commands) ────────────────────────

async def _do_set(guild: discord.Guild, invoker: discord.Member, target: discord.Member, nickname: str) -> str:
    if not _can_manage(invoker):
        return "❌ You need **Manage Nicknames** or **Administrator**."
    err = _validate_nick(nickname)
    if err:
        return f"❌ {err}"
    nickname = nickname.strip()
    err = _check_hierarchy(guild, invoker, target)
    if err:
        return f"❌ {err}"

    # Apply first. Only store the lock if Discord accepts the change.
    async with _user_lock(guild.id, target.id):
        if target.nick != nickname:
            try:
                await target.edit(nick=nickname, reason=f"Nickname lock set by {invoker} ({invoker.id})")
            except discord.Forbidden:
                return "❌ Discord refused the change (permissions or role position)."
            except discord.HTTPException as e:
                return f"❌ Discord error: {e}"

        LOCKS.setdefault(str(guild.id), {})[str(target.id)] = {
            "nickname": nickname,
            "set_by": invoker.id,
            "set_at": datetime.now(timezone.utc).isoformat(),
        }
        _warned.discard((guild.id, target.id))

    ok = await _save_locks(f"Lock nickname: {target.id} in {guild.id}")
    _log(_log_embed(
        "🔒 Nickname Locked",
        f"{target.mention} (`{target.id}`) locked to **{nickname}** by {invoker.mention}.",
        0x2ECC71,
    ))
    note = "" if ok else "\n⚠️ Saved locally, but the GitHub sync failed. I'll retry on the next change."
    return f"🔒 Locked {target.mention} to **{nickname}**.{note}"


async def _do_remove(guild: discord.Guild, invoker: discord.Member, target_id: int) -> str:
    if not _can_manage(invoker):
        return "❌ You need **Manage Nicknames** or **Administrator**."
    # Nobody can lift their own lock, even with Manage Nicknames / Administrator
    # (and the server owner too). Someone else has to do it.
    if invoker.id == target_id:
        return "❌ You can't remove your own nickname lock. Ask another moderator to do it."
    users = LOCKS.get(str(guild.id), {})
    if str(target_id) not in users:
        return "ℹ️ That user doesn't have a nickname lock."
    # Same rule as Discord: you can only manage members below your top role
    member = guild.get_member(target_id)
    if member is not None and invoker.id != guild.owner_id and member.top_role >= invoker.top_role:
        return "❌ You can't unlock someone whose top role is at or above yours."
    del users[str(target_id)]
    if not users:
        LOCKS.pop(str(guild.id), None)
    _warned.discard((guild.id, target_id))

    ok = await _save_locks(f"Unlock nickname: {target_id} in {guild.id}")
    _log(_log_embed(
        "🔓 Nickname Unlocked",
        f"<@{target_id}> (`{target_id}`) unlocked by {invoker.mention}.",
        0x95A5A6,
    ))
    note = "" if ok else "\n⚠️ Removed locally, but the GitHub sync failed."
    return f"🔓 Removed the nickname lock for <@{target_id}>.{note}"


def _list_embed(guild: discord.Guild) -> discord.Embed:
    users = LOCKS.get(str(guild.id), {})
    embed = discord.Embed(title="🔒 Locked Nicknames", color=0x5865F2)
    if not users:
        embed.description = "No locked nicknames in this server."
        return embed
    lines = []
    for uid, info in users.items():
        lines.append(f"<@{uid}> → **{info.get('nickname', '?')}** (by <@{info.get('set_by', 0)}>)")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    embed.description = text
    embed.set_footer(text=f"{len(users)} lock(s)")
    return embed


async def _locked_user_choices(interaction: discord.Interaction, current: str):
    """Autocomplete for /locknick remove: locked users in this guild + their nickname."""
    guild = interaction.guild
    if guild is None or not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
        return []
    q = (current or "").strip().lower()
    out = []
    for uid, info in LOCKS.get(str(guild.id), {}).items():
        if int(uid) == interaction.user.id:
            continue  # can't remove your own lock, so don't offer it
        member = guild.get_member(int(uid))
        user_name = member.name if member else "unknown user"
        display = member.display_name if member else uid
        nick = info.get("nickname", "?")
        haystack = f"{display} {user_name} {nick} {uid}".lower()
        if q and q not in haystack:
            continue
        label = f"{display} (@{user_name}) → {nick}"
        out.append(app_commands.Choice(name=label[:100], value=uid))
        if len(out) >= 25:
            break
    return out


# ── Prefix command handling ───────────────────────────────────────────────────

_MENTION_RE = re.compile(r"<@!?(\d+)>")


async def _handle_prefix(message: discord.Message):
    if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
        return
    content = message.content.strip()
    lower = content.lower()
    prefixes = _get_prefixes_fn() if _get_prefixes_fn else ["?"]

    rest = None
    for p in prefixes:
        head = f"{p.lower()}locknick"
        if lower == head or lower.startswith(head + " "):
            rest = content[len(head):].strip()
            break
    if rest is None:
        return

    usage = ("Usage: `locknick set @user <nickname>` · `locknick remove @user` · `locknick list`")
    parts = rest.split(None, 1)
    if not parts:
        await message.reply(usage, mention_author=False)
        return
    action = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if not _can_manage(message.author):
        await message.reply("❌ You need **Manage Nicknames** or **Administrator**.", mention_author=False)
        return

    if action == "list":
        await message.reply(embed=_list_embed(message.guild), mention_author=False)
        return

    if action in ("set", "remove"):
        m = _MENTION_RE.search(args) or re.match(r"\s*(\d{15,22})", args)
        if not m:
            await message.reply(usage, mention_author=False)
            return
        uid = int(m.group(1))
        nick_text = (args[:m.start()] + args[m.end():]).strip()

        if action == "remove":
            await message.reply(await _do_remove(message.guild, message.author, uid), mention_author=False)
            return

        member = message.guild.get_member(uid)
        if member is None:
            await message.reply("❌ I can't find that member in this server.", mention_author=False)
            return
        await message.reply(await _do_set(message.guild, message.author, member, nick_text), mention_author=False)
        return

    await message.reply(usage, mention_author=False)


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup(
    bot: discord.Client,
    *,
    get_prefixes_fn=None,
    github_read_fn=None,
    github_write_fn=None,
    send_log_fn=None,
):
    """Initialize nickname lock: commands, listeners, and startup load."""
    global _bot, _get_prefixes_fn, _github_read_json_fn, _github_write_json_fn, _send_log_fn
    _bot = bot
    _get_prefixes_fn = get_prefixes_fn
    _github_read_json_fn = github_read_fn
    _github_write_json_fn = github_write_fn
    _send_log_fn = send_log_fn

    # ── Slash commands ────────────────────────────────────────────────────────
    group = app_commands.Group(
        name="locknick",
        description="Lock a member's nickname",
        guild_only=True,
        default_permissions=discord.Permissions(manage_nicknames=True),
    )

    @group.command(name="set", description="Lock a member's nickname")
    @app_commands.describe(user="Member to lock", nickname="Nickname to enforce (max 32 chars)")
    async def _set(interaction: discord.Interaction, user: discord.Member, nickname: str):
        await interaction.response.defer(ephemeral=True)
        msg = await _do_set(interaction.guild, interaction.user, user, nickname)
        await interaction.followup.send(msg, ephemeral=True)

    @group.command(name="remove", description="Remove a member's nickname lock")
    @app_commands.describe(user="Locked member to unlock (pick from the list)")
    async def _remove(interaction: discord.Interaction, user: str):
        await interaction.response.defer(ephemeral=True)
        m = re.search(r"\d{15,22}", user)
        if not m:
            await interaction.followup.send("❌ Pick a locked user from the list.", ephemeral=True)
            return
        msg = await _do_remove(interaction.guild, interaction.user, int(m.group(0)))
        await interaction.followup.send(msg, ephemeral=True)

    @_remove.autocomplete("user")
    async def _remove_autocomplete(interaction: discord.Interaction, current: str):
        return await _locked_user_choices(interaction, current)

    @group.command(name="list", description="Show locked nicknames in this server")
    async def _list(interaction: discord.Interaction):
        if not _can_manage(interaction.user):
            await interaction.response.send_message(
                "❌ You need **Manage Nicknames** or **Administrator**.", ephemeral=True)
            return
        await interaction.response.send_message(embed=_list_embed(interaction.guild), ephemeral=True)

    bot.tree.add_command(group)

    # ── Listeners ─────────────────────────────────────────────────────────────
    @bot.listen("on_message")
    async def _nl_on_message(message: discord.Message):
        try:
            await _handle_prefix(message)
        except Exception as e:
            print(f"⚠️ nickname_lock prefix handler error: {e}")

    @bot.listen("on_member_update")
    async def _nl_on_member_update(before: discord.Member, after: discord.Member):
        if before.nick == after.nick:
            return
        lock = _get_lock(after.guild.id, after.id)
        # Already the locked value (e.g. our own change): nothing to do, no loop
        if not lock or after.nick == lock["nickname"]:
            return
        await _enforce(after)

    @bot.listen("on_member_join")
    async def _nl_on_member_join(member: discord.Member):
        if _get_lock(member.guild.id, member.id):
            await _enforce(member, delay=2.0)

    @bot.listen("on_ready")
    async def _nl_on_ready():
        global _audit_started
        if not _audit_started:
            _audit_started = True
            asyncio.create_task(_audit_loop())

    asyncio.create_task(load_locks())
    print("✅ Nickname Lock module loaded")
