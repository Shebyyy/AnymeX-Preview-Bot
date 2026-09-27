# ══════════════════════════════════════════════════════════════════════════════
# custom_triggers.py — Dynamic Custom Commands & Embed Responder with Dual Sync
# ══════════════════════════════════════════════════════════════════════════════
# Handles custom prefix commands (e.g. ?nob, !nob) and keyword triggers.
# Features:
#   - Full Discord Embed builder support (Author, Title, Desc, Fields, Banner, Thumbs, Buttons)
#   - Reply targeting: replies to referenced user and mentions them
#   - Auto-delete trigger message to keep channels clean
#   - Dual-persistence: Saves to local disk + GitHub repo (AnymeX-Preview/custom_commands.json)
#   - Automatic fallback and startup recovery
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import json
import time
import glob
import asyncio
import aiohttp
import discord
from typing import Optional, Callable, Dict, Any, List

FILE_CUSTOM_COMMANDS = "custom_commands.json"
_bot_data_env = os.environ.get("BOT_DATA_DIR", "")
if _bot_data_env and os.path.isdir(_bot_data_env):
    LOCAL_DATA_DIR = _bot_data_env
elif os.path.isdir("/root/bot_data"):
    LOCAL_DATA_DIR = "/root/bot_data"
else:
    LOCAL_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

LOCAL_BACKUPS_DIR = os.path.join(LOCAL_DATA_DIR, "backups")
LOCAL_COMMANDS_PATH = os.path.join(LOCAL_DATA_DIR, FILE_CUSTOM_COMMANDS)

# In-memory cached list of custom commands
CUSTOM_COMMANDS: List[Dict[str, Any]] = []
_bot: Optional[discord.Client] = None
_get_prefixes_fn: Optional[Callable] = None
_github_read_json_fn: Optional[Callable] = None
_github_write_json_fn: Optional[Callable] = None
_is_admin_fn: Optional[Callable] = None


def _ensure_dirs():
    """Ensure local data and backup directories exist."""
    os.makedirs(LOCAL_DATA_DIR, exist_ok=True)
    os.makedirs(LOCAL_BACKUPS_DIR, exist_ok=True)


def _load_local_commands() -> List[Dict[str, Any]]:
    """Read custom commands from local disk."""
    _ensure_dirs()
    if os.path.exists(LOCAL_COMMANDS_PATH):
        try:
            with open(LOCAL_COMMANDS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"⚠️ Error reading local {LOCAL_COMMANDS_PATH}: {e}")
    return []


def _save_local_commands(commands: List[Dict[str, Any]]) -> bool:
    """Save custom commands to local disk and create a timestamped backup."""
    _ensure_dirs()
    try:
        # Write primary local copy
        with open(LOCAL_COMMANDS_PATH, "w", encoding="utf-8") as f:
            json.dump(commands, f, indent=2, ensure_ascii=False)

        # Write timestamped backup (keep last 20)
        ts = int(time.time())
        backup_path = os.path.join(LOCAL_BACKUPS_DIR, f"custom_commands_{ts}.json")
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(commands, f, indent=2, ensure_ascii=False)

        # Prune old backups if more than 20
        all_backups = sorted(glob.glob(os.path.join(LOCAL_BACKUPS_DIR, "custom_commands_*.json")))
        if len(all_backups) > 20:
            for old_file in all_backups[:-20]:
                try:
                    os.remove(old_file)
                except OSError:
                    pass
        return True
    except Exception as e:
        print(f"❌ Error saving local custom commands: {e}")
        return False


def get_commands() -> List[Dict[str, Any]]:
    """Return live in-memory custom commands list."""
    return CUSTOM_COMMANDS


def get_backups() -> List[Dict[str, Any]]:
    """Return list of available local backup snapshots."""
    _ensure_dirs()
    backups = []
    files = sorted(glob.glob(os.path.join(LOCAL_BACKUPS_DIR, "custom_commands_*.json")), reverse=True)
    for f in files:
        filename = os.path.basename(f)
        try:
            stats = os.stat(f)
            # extract timestamp from filename
            m = re.search(r"custom_commands_(\d+)\.json", filename)
            ts = int(m.group(1)) if m else int(stats.st_mtime)
            backups.append({
                "filename": filename,
                "timestamp": ts,
                "size_bytes": stats.st_size,
                "formatted_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            })
        except Exception:
            continue
    return backups


async def restore_from_backup(filename: str) -> bool:
    """Restore custom commands from a specified backup file and sync to GitHub."""
    target = os.path.join(LOCAL_BACKUPS_DIR, filename)
    if not os.path.exists(target):
        return False
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            ok = await save_commands_dual(data, commit_msg=f"Restore custom commands from {filename}")
            return ok
    except Exception as e:
        print(f"❌ Failed to restore backup {filename}: {e}")
    return False


async def load_commands_from_github_or_local():
    """Load commands on startup from GitHub with fallback to local server disk."""
    global CUSTOM_COMMANDS
    _ensure_dirs()
    loaded_from_gh = False

    if _github_read_json_fn:
        try:
            async with aiohttp.ClientSession() as session:
                data, sha = await _github_read_json_fn(session, FILE_CUSTOM_COMMANDS)
                if data and isinstance(data, list):
                    CUSTOM_COMMANDS = data
                    loaded_from_gh = True
                    # Update local copy and backup on startup
                    _save_local_commands(data)
                    print(f"✅ Loaded {len(CUSTOM_COMMANDS)} custom commands from GitHub ({FILE_CUSTOM_COMMANDS})")
                elif sha is None:
                    print(f"ℹ️ {FILE_CUSTOM_COMMANDS} not found on GitHub, checking local disk...")
        except Exception as e:
            print(f"⚠️ Failed to fetch {FILE_CUSTOM_COMMANDS} from GitHub: {e}")

    if not loaded_from_gh:
        local_data = _load_local_commands()
        if local_data:
            CUSTOM_COMMANDS = local_data
            print(f"✅ Loaded {len(CUSTOM_COMMANDS)} custom commands from local disk backup")
        else:
            CUSTOM_COMMANDS = []
            print("ℹ️ No existing custom commands found.")


async def save_commands_dual(commands: List[Dict[str, Any]], commit_msg: str = "Update custom commands") -> bool:
    """Save to both local disk (with timestamped backup) and GitHub repository."""
    global CUSTOM_COMMANDS
    CUSTOM_COMMANDS = commands

    # 1. Save locally first (instant and guaranteed)
    _save_local_commands(commands)

    # 2. Push to GitHub repository asynchronously
    if _github_write_json_fn and _github_read_json_fn:
        try:
            async with aiohttp.ClientSession() as session:
                _, sha = await _github_read_json_fn(session, FILE_CUSTOM_COMMANDS)
                ok = await _github_write_json_fn(
                    session,
                    FILE_CUSTOM_COMMANDS,
                    commands,
                    sha,
                    commit_msg
                )
                if ok:
                    print(f"✅ Custom commands synced to GitHub ({FILE_CUSTOM_COMMANDS})")
                else:
                    print(f"⚠️ Failed to push custom commands to GitHub (saved locally)")
                return ok
        except Exception as e:
            print(f"⚠️ Error syncing custom commands to GitHub: {e}")
            return False
    return True


def _parse_color(color_val) -> int:
    """Safely convert hex string (e.g. #5865F2 or 5865F2) or int into integer color."""
    if isinstance(color_val, int):
        return color_val
    if isinstance(color_val, str):
        color_val = color_val.strip().lstrip("#")
        try:
            return int(color_val, 16)
        except ValueError:
            pass
    return 0x5865F2  # Default Discord / AnymeX blurple


def _replace_vars(text: str, message: discord.Message, target_user: Optional[discord.User | discord.Member] = None) -> str:
    """Replace template variables like {user}, {username}, {server}, {avatar}."""
    if not text or not isinstance(text, str):
        return ""
    author = message.author
    target = target_user or author
    guild_name = message.guild.name if message.guild else "Direct Message"

    text = text.replace("{user}", target.mention)
    text = text.replace("{username}", getattr(target, "display_name", target.name))
    text = text.replace("{author}", author.mention)
    text = text.replace("{author_name}", getattr(author, "display_name", author.name))
    text = text.replace("{server}", guild_name)
    text = text.replace("{avatar}", target.display_avatar.url if hasattr(target, "display_avatar") else "")
    return text


def build_custom_embed(cmd: Dict[str, Any], message: discord.Message, target_user: Optional[discord.User | discord.Member] = None) -> tuple[Optional[discord.Embed], Optional[discord.ui.View]]:
    """Construct discord.Embed and discord.ui.View from command definition."""
    embed_cfg = cmd.get("embed")
    if not embed_cfg or not isinstance(embed_cfg, dict):
        return None, None

    # Embed basics
    title = _replace_vars(embed_cfg.get("title", ""), message, target_user)
    desc = _replace_vars(embed_cfg.get("description", ""), message, target_user)
    color = _parse_color(embed_cfg.get("color", 0x5865F2))
    url = embed_cfg.get("url", "").strip() or None

    embed = discord.Embed(
        title=title if title else None,
        description=desc if desc else None,
        color=color,
        url=url
    )

    # Author
    author_cfg = embed_cfg.get("author")
    if isinstance(author_cfg, dict) and author_cfg.get("name"):
        embed.set_author(
            name=_replace_vars(author_cfg.get("name", ""), message, target_user),
            icon_url=author_cfg.get("icon_url", "").strip() or None,
            url=author_cfg.get("url", "").strip() or None
        )

    # Thumbnail & Image
    thumb_url = embed_cfg.get("thumbnail_url", "").strip()
    if thumb_url and (thumb_url.startswith("http://") or thumb_url.startswith("https://")):
        embed.set_thumbnail(url=thumb_url)

    image_url = embed_cfg.get("image_url", "").strip()
    if image_url and (image_url.startswith("http://") or image_url.startswith("https://")):
        embed.set_image(url=image_url)

    # Footer
    footer_cfg = embed_cfg.get("footer")
    if isinstance(footer_cfg, dict) and footer_cfg.get("text"):
        embed.set_footer(
            text=_replace_vars(footer_cfg.get("text", ""), message, target_user),
            icon_url=footer_cfg.get("icon_url", "").strip() or None
        )

    # Fields
    fields = embed_cfg.get("fields", [])
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                f_name = _replace_vars(f.get("name", ""), message, target_user).strip()
                f_val = _replace_vars(f.get("value", ""), message, target_user).strip()
                if f_name and f_val:
                    embed.add_field(name=f_name, value=f_val, inline=bool(f.get("inline", False)))

    # Action Buttons (Links)
    view = None
    buttons = embed_cfg.get("buttons", [])
    if isinstance(buttons, list) and len(buttons) > 0:
        view = discord.ui.View(timeout=None)
        for b in buttons:
            if isinstance(b, dict):
                b_label = b.get("label", "Open Link").strip()
                b_url = b.get("url", "").strip()
                if b_label and b_url and (b_url.startswith("http://") or b_url.startswith("https://")):
                    view.add_item(discord.ui.Button(label=b_label, url=b_url, style=discord.ButtonStyle.link))

    return embed, view


async def handle_message(message: discord.Message) -> bool:
    """
    Core message processor for custom commands.
    Returns True if a custom command was handled.
    """
    if message.author.bot or not message.content:
        return False

    raw_content = message.content.strip()
    lower_content = raw_content.lower()

    # Get active prefixes (e.g. ['?', '!', '??'])
    prefixes = []
    if _get_prefixes_fn:
        try:
            prefixes = _get_prefixes_fn()
        except Exception:
            prefixes = ["?"]
    if not prefixes:
        prefixes = ["?"]

    for cmd in CUSTOM_COMMANDS:
        if not cmd.get("enabled", True):
            continue

        cmd_name = cmd.get("name", "").strip().lower()
        if not cmd_name:
            continue

        # Aliases list (e.g. ["noob", "nub"])
        aliases = [a.strip().lower() for a in cmd.get("aliases", []) if a and isinstance(a, str)]
        trigger_names = [cmd_name] + aliases

        matched = False
        prefix_required = cmd.get("prefix_required", True)

        if prefix_required:
            # Check if message starts with any active prefix + trigger name
            for p in prefixes:
                p_lower = p.lower()
                for name in trigger_names:
                    trigger_prefix = f"{p_lower}{name}"
                    if lower_content == trigger_prefix or lower_content.startswith(f"{trigger_prefix} "):
                        matched = True
                        break
                if matched:
                    break
        else:
            # Standalone word or exact match
            for name in trigger_names:
                if lower_content == name or lower_content.startswith(f"{name} "):
                    matched = True
                    break

        if not matched:
            continue

        # ── Permission Check ──────────────────────────────────────────────────
        if cmd.get("staff_only", False):
            is_staff = False
            if message.guild:
                if message.author.guild_permissions.administrator or message.author.guild_permissions.manage_messages:
                    is_staff = True
            if not is_staff and _is_admin_fn:
                try:
                    is_staff = _is_admin_fn(message)
                except Exception:
                    pass
            if not is_staff:
                # Silently ignore or send ephemeral error if user isn't staff
                return False

        # ── Channel Whitelist / Blacklist ──────────────────────────────────────
        allowed_channels = cmd.get("allowed_channels", [])
        if allowed_channels and message.channel.id not in allowed_channels:
            continue

        ignored_channels = cmd.get("ignored_channels", [])
        if ignored_channels and message.channel.id in ignored_channels:
            continue

        # ── Target Resolution & Reply Mode ────────────────────────────────────
        target_user = None
        referenced_msg = None

        if message.reference is not None and message.reference.message_id:
            try:
                referenced_msg = await message.channel.fetch_message(message.reference.message_id)
                target_user = referenced_msg.author
            except (discord.NotFound, discord.HTTPException):
                referenced_msg = None

        # Build embed and interactive components
        embed, view = build_custom_embed(cmd, message, target_user)
        raw_text_content = _replace_vars(cmd.get("content", ""), message, target_user).strip() or None

        # Send response
        try:
            if referenced_msg and cmd.get("reply_mode", True):
                # Reply directly to the referenced message
                mention_target = bool(cmd.get("mention_user", True))
                await referenced_msg.reply(
                    content=raw_text_content,
                    embed=embed,
                    view=view,
                    mention_author=mention_target
                )
            else:
                # Regular channel send
                await message.channel.send(
                    content=raw_text_content,
                    embed=embed,
                    view=view
                )
        except discord.HTTPException as e:
            print(f"❌ Failed to send custom command response for '{cmd_name}': {e}")
            return False

        # ── Auto-Delete Trigger Message ────────────────────────────────────────
        if cmd.get("delete_trigger", True):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        # Increment in-memory usage counter
        cmd["usage_count"] = cmd.get("usage_count", 0) + 1
        return True

    return False


def setup(bot: discord.Client, *, get_prefixes_fn=None, github_read_fn=None, github_write_fn=None, is_admin_fn=None):
    """Initialize custom trigger listener with bot client."""
    global _bot, _get_prefixes_fn, _github_read_json_fn, _github_write_json_fn, _is_admin_fn
    _bot = bot
    _get_prefixes_fn = get_prefixes_fn
    _github_read_json_fn = github_read_fn
    _github_write_json_fn = github_write_fn
    _is_admin_fn = is_admin_fn

    @bot.listen("on_message")
    async def _custom_trigger_listener(message: discord.Message):
        await handle_message(message)

    # Schedule startup load from GitHub/local disk
    asyncio.create_task(load_commands_from_github_or_local())
    print("✅ Custom Triggers module loaded")
