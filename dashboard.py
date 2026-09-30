# ══════════════════════════════════════════════════════════════════════════════
# dashboard.py — Modern Management Web Dashboard for AnymeX Preview Bot
# ══════════════════════════════════════════════════════════════════════════════
# Provides:
#   - High-end dark theme UI (Linear/Discord style, clean SVG icons, no emoji clutter)
#   - Live side-by-side Discord Embed Builder & WYSIWYG Preview
#   - Full CRUD for Custom Prefix Commands (like 'nob') & Active Bot Prefixes
#   - Dual Persistence: Local Server Disk Backups + GitHub Repo Sync
#   - Authentication: Discord OAuth2 & Admin Passkey Login
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import json
import time
import hmac
import hashlib
import secrets
import urllib.parse
import aiohttp
from aiohttp import web
import discord
from typing import Optional, Dict, Any, List

import custom_triggers

_START_TIME = time.time()

# Environment & Auth Config
API_SECRET = os.environ.get("API_SECRET", "")
WEB_SECRET = os.environ.get("WEB_SECRET", "") or API_SECRET or "anymex_fallback_secret_key"
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
OAUTH_BASE_URL = os.environ.get("OAUTH_BASE_URL", "").rstrip("/")
SESSION_COOKIE_NAME = "anymex_session"

# Active login sessions: {session_id: {"user_id": str, "username": str, "avatar": str, "role": str, "expires": float}}
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

_bot: Optional[discord.Client] = None
_get_prefix_cache_fn = None
_set_prefix_cache_fn = None
_github_read_fn = None
_github_write_fn = None
_read_admins_fn = None


def _generate_session_token(user_info: dict) -> str:
    """Create a secure session token and record in active store."""
    token = secrets.token_urlsafe(32)
    _ACTIVE_SESSIONS[token] = {
        **user_info,
        "expires": time.time() + 86400 * 7  # 7 days
    }
    return token


def _get_current_session(request: web.Request) -> Optional[dict]:
    """Retrieve and validate session from cookie or Authorization header."""
    token = None
    # 1. Bearer Header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    # 2. Cookie fallback
    if not token:
        token = request.cookies.get(SESSION_COOKIE_NAME)

    if not token:
        return None

    # Check master API secret match directly
    if API_SECRET and token == API_SECRET:
        return {"username": "Admin (Key)", "role": "admin", "avatar": None}

    sess = _ACTIVE_SESSIONS.get(token)
    if sess:
        if time.time() > sess.get("expires", 0):
            _ACTIVE_SESSIONS.pop(token, None)
            return None
        return sess

    return None


def _require_auth(request: web.Request) -> Optional[dict]:
    """Verify admin auth. Returns user dict or raises HTTPUnauthorized."""
    sess = _get_current_session(request)
    if not sess:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Unauthorized. Please log in."}),
            content_type="application/json"
        )
    return sess


# ══════════════════════════════════════════════════════════════════════════════
# Auth API Endpoints
# ══════════════════════════════════════════════════════════════════════════════

async def api_login_passkey(request: web.Request):
    """POST /dashboard/api/login — Login with Server Passkey / API_SECRET."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    passkey = str(body.get("passkey", "")).strip()
    valid_keys = [k for k in [API_SECRET, WEB_SECRET] if k]

    if not valid_keys:
        # If no key set in env, allow emergency admin login
        is_valid = True
    else:
        is_valid = passkey in valid_keys

    if not is_valid:
        return web.json_response({"error": "Invalid access key"}, status=401)

    user_info = {
        "username": "Server Administrator",
        "role": "admin",
        "avatar": None
    }
    token = _generate_session_token(user_info)
    response = web.json_response({
        "success": True,
        "token": token,
        "user": user_info
    })
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=86400 * 7,
        httponly=True,
        samesite="Lax"
    )
    return response


async def api_logout(request: web.Request):
    """POST /dashboard/api/logout — Terminate session."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token and token in _ACTIVE_SESSIONS:
        _ACTIVE_SESSIONS.pop(token, None)
    response = web.json_response({"success": True})
    response.del_cookie(SESSION_COOKIE_NAME)
    return response


async def api_me(request: web.Request):
    """GET /dashboard/api/me — Return logged in user profile."""
    sess = _get_current_session(request)
    if not sess:
        return web.json_response({"authenticated": False}, status=401)
    return web.json_response({"authenticated": True, "user": sess})


def _get_oauth_base_url(request: web.Request) -> str:
    """Return the public base URL for OAuth callbacks."""
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("X-Forwarded-Host") or request.host

    # If accessed through HTTPS proxy (port 443) or no custom port in host, use that directly
    if proto == "https" or (host and ":8081" not in host):
        return f"{proto}://{host}"

    if OAUTH_BASE_URL:
        return OAUTH_BASE_URL.strip().rstrip("/")
    return f"{proto}://{host}"


async def auth_discord_redirect(request: web.Request):
    """GET /dashboard/auth/discord or /auth/discord — Initiate Discord OAuth2 flow."""
    if not DISCORD_CLIENT_ID:
        return web.HTTPBadRequest(text="DISCORD_CLIENT_ID not configured in environment.")

    base = _get_oauth_base_url(request)
    # Check if a custom callback path was requested or if hit via /auth/discord
    callback_path = request.query.get("callback_path")
    if not callback_path:
        if request.path.startswith("/auth"):
            callback_path = "/auth/callback"
        else:
            callback_path = "/dashboard/auth/discord/callback"

    redirect_uri = f"{base}{callback_path}"
    state = secrets.token_hex(16)

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state
    }
    url = f"https://discord.com/api/oauth2/authorize?{urllib.parse.urlencode(params)}"
    response = web.HTTPFound(url)
    response.set_cookie("oauth_state", state, max_age=300, httponly=True)
    response.set_cookie("oauth_redirect_uri", redirect_uri, max_age=600, httponly=True)
    return response


async def auth_discord_callback(request: web.Request):
    """Discord OAuth2 return handler (supports /dashboard/auth/discord/callback and /auth/callback)."""
    code = request.query.get("code")
    state = request.query.get("state")
    cookie_state = request.cookies.get("oauth_state")

    if not code or not state or state != cookie_state:
        return web.HTTPBadRequest(text="Invalid OAuth state or missing code.")

    # Match redirect_uri precisely: first from cookie, fallback to base + incoming request.path
    redirect_uri = request.cookies.get("oauth_redirect_uri")
    if not redirect_uri:
        base = _get_oauth_base_url(request)
        redirect_uri = f"{base}{request.path}"

    # Exchange code for token
    token_url = "https://discord.com/api/oauth2/token"
    token_data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=token_data) as r:
            if r.status != 200:
                return web.HTTPUnauthorized(text="Failed to exchange Discord authorization code.")
            token_res = await r.json()

        access_token = token_res.get("access_token")
        # Fetch user info
        async with session.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"}) as r:
            if r.status != 200:
                return web.HTTPUnauthorized(text="Failed to fetch Discord user information.")
            discord_user = await r.json()

    user_id = str(discord_user.get("id"))
    username = discord_user.get("username", "Discord User")
    avatar = discord_user.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png" if avatar else None

    # Check permissions: Admin list or Guild Administrator
    is_admin = False
    if _read_admins_fn:
        try:
            async with aiohttp.ClientSession() as session:
                admins, _ = await _read_admins_fn(session)
                if user_id in admins:
                    is_admin = True
        except Exception:
            pass

    if not is_admin and _bot:
        for guild in _bot.guilds:
            member = guild.get_member(int(user_id))
            if member and member.guild_permissions.administrator:
                is_admin = True
                break

    if not is_admin:
        return web.HTTPForbidden(text="Access denied: Your Discord account is not an authorized administrator.")

    token = _generate_session_token({
        "user_id": user_id,
        "username": username,
        "avatar": avatar_url,
        "role": "admin"
    })

    redirect_resp = web.HTTPFound("/dashboard")
    redirect_resp.set_cookie(SESSION_COOKIE_NAME, token, max_age=86400 * 7, httponly=True, samesite="Lax")
    redirect_resp.del_cookie("oauth_state")
    return redirect_resp


# ══════════════════════════════════════════════════════════════════════════════
# Custom Commands & Prefixes API
# ══════════════════════════════════════════════════════════════════════════════
# Custom Commands & Triggers Management API
# ══════════════════════════════════════════════════════════════════════════════

BUILTIN_COMMANDS = [
    {
        "name": "commands",
        "aliases": ["cmds", "cmd"],
        "description": "Show all available prefix commands, custom triggers, and active prefixes.",
        "category": "Core",
        "trigger_display": "{p}commands"
    },
    {
        "name": "help",
        "aliases": [],
        "description": "Show general bot overview and slash command directory.",
        "category": "Core",
        "trigger_display": "{p}help"
    },
    {
        "name": "setprefix",
        "aliases": [],
        "description": "Manage bot command prefixes (add, remove, list). Administrator only.",
        "category": "Admin",
        "trigger_display": "{p}setprefix [add|remove|list]"
    },
    {
        "name": "1-12",
        "aliases": ["faq1-12", "log1-12"],
        "description": "Display FAQ item by number. Can be used in reply to a user.",
        "category": "Info",
        "trigger_display": "{p}<num> or !faq<num>"
    },
    {
        "name": "rule1-10",
        "aliases": ["r1-10"],
        "description": "Display server rule item by number. Can be used in reply to a user.",
        "category": "Info",
        "trigger_display": "!rule<num>"
    },
    {
        "name": "hi",
        "aliases": ["single"],
        "description": "Playful greeting trigger response.",
        "category": "Fun",
        "trigger_display": "!hi or !single"
    }
]

RESERVED_COMMAND_NAMES = {
    "commands", "cmds", "cmd", "help", "prefix", "prefixes",
    "setprefix", "hi", "single", "faq", "log", "rule", "r"
}


def is_reserved_name(name: str) -> bool:
    clean = name.strip().lower()
    if clean in RESERVED_COMMAND_NAMES:
        return True
    if clean.isdigit():
        return True
    if re.match(r"^(?:faq|log|rule|r)\d+$", clean):
        return True
    return False
 

async def api_get_stats(request: web.Request):
    """GET /dashboard/api/stats — Return real-time bot metrics & sync health."""
    _require_auth(request)
    latency = 0.0
    if _bot and hasattr(_bot, "latency") and _bot.latency is not None:
        try:
            latency = round(_bot.latency * 1000, 1)
        except Exception:
            latency = 0.0

    guilds_count = len(_bot.guilds) if _bot else 0
    users_count = 0
    if _bot:
        try:
            users_count = sum((g.member_count or 0) for g in _bot.guilds)
        except Exception:
            pass

    uptime_sec = int(time.time() - _START_TIME)
    cmds = custom_triggers.get_commands()
    backups = custom_triggers.get_backups()
    prefixes = ["?"]
    if _get_prefix_cache_fn:
        try:
            prefixes = list(_get_prefix_cache_fn())
        except Exception:
            pass

    bot_avatar = None
    bot_name = "AnymeX Preview"
    if _bot and _bot.user:
        bot_name = _bot.user.name
        try:
            bot_avatar = str(_bot.user.display_avatar.url)
        except Exception:
            bot_avatar = None

    return web.json_response({
        "success": True,
        "bot_online": _bot.is_ready() if _bot else False,
        "bot_name": bot_name,
        "bot_avatar": bot_avatar,
        "latency_ms": latency,
        "guilds": guilds_count,
        "users": users_count,
        "uptime_seconds": uptime_sec,
        "custom_commands_count": len(cmds),
        "builtin_commands_count": len(BUILTIN_COMMANDS),
        "prefixes": prefixes,
        "backups_count": len(backups),
        "github_configured": bool(os.environ.get("GITHUB_TOKEN"))
    })


async def api_get_commands(request: web.Request):
    """GET /dashboard/api/commands — Return all custom commands and builtin commands."""
    _require_auth(request)
    cmds = custom_triggers.get_commands()
    return web.json_response({
        "success": True,
        "commands": cmds,
        "builtin_commands": BUILTIN_COMMANDS
    })


async def api_save_command(request: web.Request):
    """POST /dashboard/api/commands — Create or update a custom command."""
    sess = _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    name = str(body.get("name", "")).strip().lower()
    if not name:
        return web.json_response({"error": "Command name is required"}, status=400)
    if " " in name:
        return web.json_response({"error": "Command name cannot contain spaces"}, status=400)

    cmd_id = str(body.get("id", "")).strip() or f"cmd_{name}_{int(time.time())}"
    current_cmds = custom_triggers.get_commands()

    # Clean and deduplicate aliases
    aliases = []
    for a in body.get("aliases", []):
        a_clean = str(a).strip().lower()
        if not a_clean:
            continue
        if " " in a_clean:
            return web.json_response({"error": f"Alias '{a_clean}' cannot contain spaces"}, status=400)
        if a_clean != name and a_clean not in aliases:
            aliases.append(a_clean)

    # 1. Check against reserved built-in command names and patterns
    if is_reserved_name(name):
        return web.json_response({"error": f"Trigger '{name}' is reserved by a built-in bot command"}, status=409)

    for a in aliases:
        if is_reserved_name(a):
            return web.json_response({"error": f"Alias '{a}' is reserved by a built-in bot command"}, status=409)

    # 2. Check for collision with other custom commands and aliases
    all_new_triggers = [name] + aliases
    for c in current_cmds:
        if c.get("id") == cmd_id:
            continue
        c_name = str(c.get("name", "")).strip().lower()
        c_aliases = [str(x).strip().lower() for x in c.get("aliases", []) if str(x).strip()]
        c_all = [c_name] + c_aliases

        overlap = set(all_new_triggers) & set(c_all)
        if overlap:
            collided = sorted(list(overlap))[0]
            return web.json_response({
                "error": f"Trigger or alias '{collided}' is already used by custom command '{c_name}'"
            }, status=409)

    embed_data = body.get("embed") or {}
    updated_cmd = {
        "id": cmd_id,
        "name": name,
        "aliases": aliases,
        "description": str(body.get("description", "")).strip(),
        "enabled": bool(body.get("enabled", True)),
        "prefix_required": bool(body.get("prefix_required", True)),
        "delete_trigger": bool(body.get("delete_trigger", True)),
        "reply_mode": bool(body.get("reply_mode", True)),
        "mention_user": bool(body.get("mention_user", True)),
        "staff_only": bool(body.get("staff_only", False)),
        "allowed_channels": body.get("allowed_channels", []),
        "ignored_channels": body.get("ignored_channels", []),
        "content": str(body.get("content", "")).strip(),
        "embed": embed_data,
        "updated_at": int(time.time()),
        "created_by": sess.get("username", "Admin")
    }

    # Upsert in list
    existing_idx = next((i for i, c in enumerate(current_cmds) if c.get("id") == cmd_id), None)
    if existing_idx is not None:
        updated_cmd["created_at"] = current_cmds[existing_idx].get("created_at", int(time.time()))
        updated_cmd["usage_count"] = current_cmds[existing_idx].get("usage_count", 0)
        current_cmds[existing_idx] = updated_cmd
        action = f"Update command '{name}'"
    else:
        updated_cmd["created_at"] = int(time.time())
        updated_cmd["usage_count"] = 0
        current_cmds.append(updated_cmd)
        action = f"Create command '{name}'"

    # Dual persistence (server disk backup + GitHub sync)
    ok = await custom_triggers.save_commands_dual(current_cmds, commit_msg=f"dashboard: {action}")
    return web.json_response({
        "success": True,
        "action": action,
        "command": updated_cmd,
        "github_synced": ok
    })


async def api_delete_command(request: web.Request):
    """DELETE /dashboard/api/commands/{id} — Delete a custom command."""
    _require_auth(request)
    cmd_id = request.match_info.get("id")
    current_cmds = custom_triggers.get_commands()

    initial_len = len(current_cmds)
    filtered = [c for c in current_cmds if c.get("id") != cmd_id]
    if len(filtered) == initial_len:
        return web.json_response({"error": "Command not found"}, status=404)

    ok = await custom_triggers.save_commands_dual(filtered, commit_msg=f"dashboard: Delete command {cmd_id}")
    return web.json_response({"success": True, "github_synced": ok})


async def api_get_prefixes(request: web.Request):
    """GET /dashboard/api/prefixes — Return active bot prefixes."""
    _require_auth(request)
    prefixes = ["?"]
    if _get_prefix_cache_fn:
        try:
            prefixes = _get_prefix_cache_fn()
        except Exception:
            pass
    return web.json_response({"success": True, "prefixes": prefixes})


async def api_add_prefix(request: web.Request):
    """POST /dashboard/api/prefixes — Add a new bot prefix."""
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    new_prefix = str(body.get("prefix", "")).strip()
    if not new_prefix:
        return web.json_response({"error": "Prefix cannot be empty"}, status=400)
    if len(new_prefix) > 5:
        return web.json_response({"error": "Prefix must be 5 characters or fewer"}, status=400)

    prefixes = ["?"]
    if _get_prefix_cache_fn:
        prefixes = list(_get_prefix_cache_fn())

    if new_prefix in prefixes:
        return web.json_response({"error": f"Prefix '{new_prefix}' already exists"}, status=409)

    prefixes.append(new_prefix)

    # Sync to GitHub
    gh_synced = False
    if _github_write_fn and _github_read_fn:
        try:
            async with aiohttp.ClientSession() as session:
                _, sha = await _github_read_fn(session, "prefixes.json")
                gh_synced = await _github_write_fn(
                    session, "prefixes.json", prefixes, sha, f"dashboard: add prefix {new_prefix}"
                )
        except Exception as e:
            print(f"⚠️ Failed to push prefix to GitHub: {e}")

    if _set_prefix_cache_fn:
        _set_prefix_cache_fn(prefixes)

    return web.json_response({"success": True, "prefixes": prefixes, "github_synced": gh_synced})


async def api_delete_prefix(request: web.Request):
    """DELETE /dashboard/api/prefixes/{prefix} — Remove a prefix."""
    _require_auth(request)
    prefix_to_remove = urllib.parse.unquote(request.match_info.get("prefix", "")).strip()

    prefixes = ["?"]
    if _get_prefix_cache_fn:
        prefixes = list(_get_prefix_cache_fn())

    if prefix_to_remove not in prefixes:
        return web.json_response({"error": f"Prefix '{prefix_to_remove}' not found"}, status=404)

    if len(prefixes) <= 1:
        return web.json_response({"error": "Cannot remove the last active prefix. Add another first."}, status=400)

    prefixes.remove(prefix_to_remove)

    gh_synced = False
    if _github_write_fn and _github_read_fn:
        try:
            async with aiohttp.ClientSession() as session:
                _, sha = await _github_read_fn(session, "prefixes.json")
                gh_synced = await _github_write_fn(
                    session, "prefixes.json", prefixes, sha, f"dashboard: remove prefix {prefix_to_remove}"
                )
        except Exception as e:
            print(f"⚠️ Failed to push prefix deletion to GitHub: {e}")

    if _set_prefix_cache_fn:
        _set_prefix_cache_fn(prefixes)

    return web.json_response({"success": True, "prefixes": prefixes, "github_synced": gh_synced})


async def api_get_backups(request: web.Request):
    """GET /dashboard/api/backups — List server backup snapshots."""
    _require_auth(request)
    backups = custom_triggers.get_backups()
    return web.json_response({"success": True, "backups": backups})


async def api_restore_backup(request: web.Request):
    """POST /dashboard/api/backups/restore — Restore a server backup."""
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    filename = str(body.get("filename", "")).strip()
    if not filename:
        return web.json_response({"error": "Filename is required"}, status=400)

    ok = await custom_triggers.restore_from_backup(filename)
    if ok:
        return web.json_response({"success": True, "restored": filename})
    return web.json_response({"error": f"Failed to restore backup '{filename}'"}, status=500)


async def api_test_send(request: web.Request):
    """POST /dashboard/api/test_send — Send test embed to Discord channel."""
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    channel_id_raw = body.get("channel_id")
    if not channel_id_raw or not str(channel_id_raw).isdigit():
        return web.json_response({"error": "Valid channel ID is required"}, status=400)

    if not _bot:
        return web.json_response({"error": "Bot client not initialized"}, status=503)

    channel = _bot.get_channel(int(channel_id_raw))
    if not channel:
        return web.json_response({"error": f"Channel {channel_id_raw} not found or inaccessible by bot"}, status=404)

    cmd_data = body.get("command") or {}
    embed, view = custom_triggers.build_custom_embed(cmd_data, None, None)
    content = cmd_data.get("content", "").strip() or None

    try:
        sent = await channel.send(content=content, embed=embed, view=view)
        return web.json_response({"success": True, "message_id": sent.id, "channel": channel.name})
    except Exception as e:
        return web.json_response({"error": f"Discord error: {str(e)}"}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard Frontend HTML
# ══════════════════════════════════════════════════════════════════════════════

def _dashboard_page_html() -> str:
    """Return the modern, single-page application dashboard HTML/CSS/JS."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>AnymeX Bot — Command & Embed Dashboard</title>
  <link rel="icon" type="image/gif" href="/favicon.gif">
  <link rel="shortcut icon" type="image/gif" href="/favicon.gif">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #07090e;
      --bg-surface: #0e131f;
      --bg-elevated: #151d30;
      --bg-hover: #1e2842;
      --border-subtle: #1e293b;
      --border-strong: #334155;
      --border-accent: rgba(99, 102, 241, 0.35);
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-subtle: #64748b;
      --brand: #6366f1;
      --brand-hover: #4f46e5;
      --brand-glow: rgba(99, 102, 241, 0.28);
      --discord: #5865F2;
      --discord-dark: #313338;
      --discord-embed: #2b2d31;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --cyan: #38bdf8;
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --font-ui: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-display: 'Outfit', sans-serif;
      --font-code: 'JetBrains Mono', monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-ui);
      min-height: 100vh;
      min-height: 100dvh;
      line-height: 1.5;
      overflow-x: hidden;
      width: 100%;
    }

    /* SVG Icon styles */
    .icon {
      width: 17px;
      height: 17px;
      stroke-width: 2;
      stroke: currentColor;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
      display: inline-block;
      vertical-align: middle;
      flex-shrink: 0;
    }

    /* Top Navigation Header */
    header {
      background: rgba(14, 19, 31, 0.88);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-subtle);
      padding: 0 24px;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 60;
    }

    .brand-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
    }

    .brand-logo {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, #6366f1, #38bdf8);
      border-radius: var(--radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 0 16px var(--brand-glow);
      overflow: hidden;
    }
    .brand-logo img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .brand-text {
      display: flex;
      flex-direction: column;
    }
    .brand-title {
      font-family: var(--font-display);
      font-size: 17px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text-main);
      line-height: 1.2;
    }
    .brand-badge {
      font-size: 11px;
      color: var(--cyan);
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.25);
      color: #34d399;
      font-size: 12px;
      padding: 5px 12px;
      border-radius: 20px;
      font-weight: 500;
      white-space: nowrap;
    }

    .status-dot {
      width: 7px;
      height: 7px;
      background: #10b981;
      border-radius: 50%;
      box-shadow: 0 0 8px #10b981;
      animation: pulseDot 2s infinite;
    }
    @keyframes pulseDot {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.6; transform: scale(0.85); }
    }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 8px 16px;
      border-radius: var(--radius-md);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      border: 1px solid transparent;
      outline: none;
      font-family: var(--font-ui);
      white-space: nowrap;
      user-select: none;
    }

    .btn-primary {
      background: var(--brand);
      color: white;
      box-shadow: 0 4px 14px var(--brand-glow);
    }
    .btn-primary:hover {
      background: var(--brand-hover);
      transform: translateY(-1px);
    }

    .btn-secondary {
      background: var(--bg-elevated);
      color: var(--text-main);
      border-color: var(--border-subtle);
    }
    .btn-secondary:hover {
      background: var(--bg-hover);
      border-color: var(--border-strong);
    }

    .btn-danger {
      background: rgba(239, 68, 68, 0.12);
      color: #fca5a5;
      border-color: rgba(239, 68, 68, 0.25);
    }
    .btn-danger:hover {
      background: var(--danger);
      color: white;
    }

    .btn-sm {
      padding: 6px 11px;
      font-size: 12px;
      border-radius: var(--radius-sm);
    }

    .btn-icon-only {
      padding: 7px;
      border-radius: var(--radius-sm);
    }

    /* Navigation Bar / Tabs Bar */
    .nav-bar {
      background: rgba(11, 15, 25, 0.95);
      border-bottom: 1px solid var(--border-subtle);
      position: sticky;
      top: 64px;
      z-index: 50;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }
    .nav-bar::-webkit-scrollbar { display: none; }

    .nav-inner {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 24px;
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: max-content;
      height: 52px;
    }

    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 13px;
      font-weight: 600;
      padding: 8px 14px;
      border-radius: var(--radius-md);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.15s ease;
      white-space: nowrap;
      position: relative;
    }
    .tab-btn:hover {
      color: var(--text-main);
      background: var(--bg-elevated);
    }
    .tab-btn.active {
      color: white;
      background: rgba(99, 102, 241, 0.18);
      border: 1px solid rgba(99, 102, 241, 0.4);
      box-shadow: 0 0 14px rgba(99, 102, 241, 0.15);
    }
    .tab-badge {
      background: var(--bg-elevated);
      font-size: 10px;
      padding: 2px 7px;
      border-radius: 12px;
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      font-weight: 700;
    }
    .tab-btn.active .tab-badge {
      background: var(--brand);
      color: white;
      border-color: transparent;
    }

    /* Main Container */
    main {
      flex: 1;
      max-width: 1400px;
      width: 100%;
      margin: 0 auto;
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    /* Views */
    .view-content { display: none; }
    .view-content.active { display: block; animation: fadeIn 0.2s ease-out; }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Section Headers */
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .section-title {
      font-family: var(--font-display);
      font-size: 22px;
      font-weight: 700;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .section-subtitle {
      font-size: 13px;
      color: var(--text-subtle);
      margin-top: 3px;
    }

    /* Hero / Status Banner on Overview */
    .hero-banner {
      background: linear-gradient(135deg, rgba(20, 29, 48, 0.95), rgba(14, 19, 31, 0.95));
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      padding: 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      position: relative;
      overflow: hidden;
    }
    .hero-banner::after {
      content: "";
      position: absolute;
      top: -60px;
      right: -60px;
      width: 200px;
      height: 200px;
      background: radial-gradient(circle, rgba(99, 102, 241, 0.15) 0%, transparent 70%);
      pointer-events: none;
    }

    .hero-left {
      display: flex;
      align-items: center;
      gap: 18px;
    }
    .hero-avatar {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: var(--discord);
      display: flex;
      align-items: center;
      justify-content: center;
      border: 2px solid var(--brand);
      box-shadow: 0 0 20px var(--brand-glow);
      overflow: hidden;
      flex-shrink: 0;
    }
    .hero-avatar img { width: 100%; height: 100%; object-fit: cover; }
    .hero-name {
      font-family: var(--font-display);
      font-size: 22px;
      font-weight: 800;
      color: white;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .hero-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 6px;
    }
    .hero-chip {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      font-size: 11px;
      padding: 3px 9px;
      border-radius: 20px;
      color: var(--text-muted);
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }

    /* Metric Cards Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }
    .stat-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      transition: transform 0.15s, border-color 0.15s;
    }
    .stat-card:hover {
      border-color: var(--border-strong);
      transform: translateY(-2px);
    }
    .stat-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--text-subtle);
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .stat-val {
      font-family: var(--font-display);
      font-size: 26px;
      font-weight: 800;
      color: var(--text-main);
    }
    .stat-foot {
      font-size: 12px;
      color: var(--text-muted);
    }

    /* Search & Filter Toolbar */
    .toolbar-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .search-box {
      position: relative;
      flex: 1;
      max-width: 420px;
      min-width: 240px;
    }
    .search-box input {
      width: 100%;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 9px 14px 9px 36px;
      border-radius: var(--radius-md);
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s;
    }
    .search-box input:focus {
      border-color: var(--brand);
      box-shadow: 0 0 0 3px var(--brand-glow);
    }
    .search-box .search-icon {
      position: absolute;
      left: 11px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-subtle);
      pointer-events: none;
    }
    .filter-pills {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .filter-pill {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 600;
      padding: 6px 12px;
      border-radius: 20px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .filter-pill:hover {
      color: var(--text-main);
      background: var(--bg-elevated);
    }
    .filter-pill.active {
      background: var(--bg-elevated);
      color: var(--cyan);
      border-color: var(--cyan);
    }

    /* Commands Grid */
    .commands-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 16px;
    }

    .command-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 18px;
      transition: all 0.2s ease;
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: relative;
    }
    .command-card:hover {
      border-color: var(--border-strong);
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }

    .card-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }

    .trigger-badge {
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.35);
      color: #a5b4fc;
      font-family: var(--font-code);
      font-size: 14px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: var(--radius-sm);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .aliases-list {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 6px;
    }
    .alias-pill {
      background: var(--bg-elevated);
      color: var(--text-muted);
      font-size: 11px;
      font-family: var(--font-code);
      padding: 2px 7px;
      border-radius: 4px;
      border: 1px solid var(--border-subtle);
    }

    .card-badges {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      font-size: 11px;
    }
    .feature-badge {
      background: var(--bg-elevated);
      color: var(--text-muted);
      padding: 3px 8px;
      border-radius: 4px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .feature-badge.active {
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.25);
    }

    .card-embed-preview {
      background: #2b2d31;
      border-radius: 6px;
      padding: 10px 12px;
      border-left: 4px solid var(--discord);
      font-size: 12px;
    }
    .card-embed-title {
      font-weight: 600;
      color: white;
      margin-bottom: 4px;
    }
    .card-embed-desc {
      color: #dbdee1;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-top: 1px solid var(--border-subtle);
      padding-top: 12px;
      margin-top: auto;
      font-size: 12px;
      color: var(--text-subtle);
    }

    /* Accordion for Built-in Commands */
    .accordion-section {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      margin-bottom: 14px;
      overflow: hidden;
      transition: border-color 0.15s;
    }
    .accordion-section:hover {
      border-color: var(--border-strong);
    }
    .accordion-header {
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      user-select: none;
      background: var(--bg-surface);
      transition: background 0.15s;
    }
    .accordion-header:hover {
      background: var(--bg-elevated);
    }
    .accordion-title-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .accordion-title {
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 700;
      color: var(--text-main);
    }
    .accordion-desc {
      font-size: 12px;
      color: var(--text-subtle);
      margin-top: 2px;
    }
    .accordion-chevron {
      color: var(--text-muted);
      transition: transform 0.2s ease;
    }
    .accordion-section.open .accordion-chevron {
      transform: rotate(180deg);
    }
    .accordion-body {
      display: none;
      padding: 0 20px 20px 20px;
      border-top: 1px solid var(--border-subtle);
      background: rgba(14, 19, 31, 0.4);
    }
    .accordion-section.open .accordion-body {
      display: block;
      animation: accordionOpen 0.2s ease-out;
    }
    @keyframes accordionOpen {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Quick Action Grid (Overview) */
    .actions-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 16px;
    }
    .action-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 20px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 16px;
      transition: all 0.15s ease;
    }
    .action-card:hover {
      border-color: var(--brand);
      background: var(--bg-elevated);
      transform: translateY(-2px);
    }
    .action-icon-wrap {
      width: 44px;
      height: 44px;
      border-radius: var(--radius-md);
      background: rgba(99, 102, 241, 0.15);
      color: var(--cyan);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .action-title {
      font-size: 15px;
      font-weight: 700;
      color: var(--text-main);
    }
    .action-sub {
      font-size: 12px;
      color: var(--text-subtle);
      margin-top: 2px;
    }

    /* Modal / Drawer for Embed Builder */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.78);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .modal-backdrop.open { display: flex; }

    .modal-container {
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      width: 100%;
      max-width: 1280px;
      height: 92vh;
      max-height: 940px;
      display: flex;
      flex-direction: column;
      box-shadow: 0 24px 70px rgba(0,0,0,0.65);
      overflow: hidden;
    }

    .modal-header {
      padding: 16px 22px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-elevated);
      flex-shrink: 0;
      gap: 12px;
    }
    .modal-title-wrap {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .modal-title {
      font-family: var(--font-display);
      font-size: 18px;
      font-weight: 700;
    }

    /* Mobile Segmented Switch in Modal Header */
    .modal-view-switch {
      display: none;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 3px;
      gap: 4px;
    }
    .switch-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 600;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .switch-btn.active {
      background: var(--brand);
      color: white;
    }

    .modal-body {
      flex: 1;
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      overflow: hidden;
      min-height: 0;
    }

    /* Form Column */
    .form-column {
      padding: 22px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
      border-right: 1px solid var(--border-subtle);
    }

    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-label {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .form-input, .form-textarea, .form-select {
      background: var(--bg-elevated);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 10px 13px;
      border-radius: var(--radius-md);
      font-size: 13px;
      font-family: var(--font-ui);
      transition: border-color 0.15s;
      width: 100%;
    }
    .form-input:focus, .form-textarea:focus, .form-select:focus {
      outline: none;
      border-color: var(--brand);
      box-shadow: 0 0 0 3px var(--brand-glow);
    }
    .form-textarea { resize: vertical; min-height: 84px; line-height: 1.45; }

    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-elevated);
      padding: 10px 14px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border-subtle);
    }
    .toggle-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .toggle-title { font-size: 13px; font-weight: 600; color: var(--text-main); }
    .toggle-desc { font-size: 11px; color: var(--text-subtle); }

    /* Custom Toggle Switch */
    .switch {
      position: relative;
      display: inline-block;
      width: 42px;
      height: 24px;
      flex-shrink: 0;
    }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider {
      position: absolute;
      cursor: pointer;
      inset: 0;
      background-color: var(--border-strong);
      transition: .2s;
      border-radius: 24px;
    }
    .slider:before {
      position: absolute;
      content: "";
      height: 18px;
      width: 18px;
      left: 3px;
      bottom: 3px;
      background-color: white;
      transition: .2s;
      border-radius: 50%;
    }
    input:checked + .slider { background-color: var(--brand); }
    input:checked + .slider:before { transform: translateX(18px); }

    /* Color Swatches */
    .color-picker-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .color-swatch {
      width: 26px;
      height: 26px;
      border-radius: 50%;
      cursor: pointer;
      border: 2px solid transparent;
      transition: transform 0.15s;
    }
    .color-swatch:hover { transform: scale(1.15); }
    .color-swatch.active { border-color: white; box-shadow: 0 0 8px rgba(255,255,255,0.4); }

    /* Discord Preview Column */
    .preview-column {
      background: #1e1f22;
      padding: 24px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .preview-header {
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #949ba4;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* 1:1 Discord Message Mockup */
    .discord-message {
      display: flex;
      gap: 14px;
      font-family: 'Inter', 'gg sans', sans-serif;
    }
    .discord-avatar {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: #5865F2;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-weight: 700;
      flex-shrink: 0;
      overflow: hidden;
    }
    .discord-avatar img { width: 100%; height: 100%; object-fit: cover; }
    .discord-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }
    .discord-meta {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 14px;
    }
    .discord-username {
      font-weight: 600;
      color: #f2f3f5;
    }
    .discord-bot-tag {
      background: #5865F2;
      color: white;
      font-size: 10px;
      font-weight: 600;
      padding: 1px 4px;
      border-radius: 3px;
      text-transform: uppercase;
    }
    .discord-timestamp {
      color: #949ba4;
      font-size: 12px;
    }

    /* Discord Embed Component */
    .discord-embed {
      background: #2b2d31;
      border-radius: 4px;
      padding: 14px 16px;
      border-left: 4px solid #5865F2;
      max-width: 520px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      font-size: 13px;
      color: #dbdee1;
      word-break: break-word;
    }

    .d-author {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 600;
      color: white;
    }
    .d-author img {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      object-fit: cover;
    }

    .d-title {
      font-size: 16px;
      font-weight: 700;
      color: white;
      text-decoration: none;
    }
    .d-title:hover { text-decoration: underline; color: #00a8fc; }

    .d-desc {
      line-height: 1.45;
      white-space: pre-wrap;
    }

    .d-fields {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-top: 4px;
    }
    .d-field-name {
      font-size: 12px;
      font-weight: 700;
      color: white;
      margin-bottom: 2px;
    }
    .d-field-val {
      font-size: 13px;
      color: #dbdee1;
    }

    .d-image {
      max-width: 100%;
      border-radius: 4px;
      margin-top: 6px;
      display: none;
    }
    .d-thumb {
      max-width: 80px;
      max-height: 80px;
      border-radius: 4px;
      float: right;
    }

    .d-footer {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      color: #949ba4;
      margin-top: 4px;
    }

    /* Send Test Embed Widget */
    .test-send-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 14px;
    }

    /* Toast Notification */
    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      padding: 12px 20px;
      border-radius: var(--radius-md);
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      font-weight: 500;
      z-index: 250;
      transform: translateY(100px);
      opacity: 0;
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    #toast.show {
      transform: translateY(0);
      opacity: 1;
    }
    #toast.success { border-color: #10b981; color: #34d399; }
    #toast.error { border-color: #ef4444; color: #f87171; }

    /* ══════════════════════════════════════════════════════════════════════════
       RESPONSIVE BREAKPOINTS (Mobile & Tablet)
       ══════════════════════════════════════════════════════════════════════════ */
    @media (max-width: 992px) {
      .stats-grid {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    @media (max-width: 900px) {
      /* Modal switches to Tabbed View on Mobile */
      .modal-container {
        height: 100vh;
        height: 100dvh;
        max-height: 100dvh;
        border-radius: 0;
        border: none;
      }
      .modal-backdrop {
        padding: 0;
      }
      .modal-view-switch {
        display: inline-flex;
      }
      .modal-body {
        grid-template-columns: 1fr;
      }
      .form-column {
        border-right: none;
      }
      .preview-column {
        display: none;
      }
      /* When Preview Mode Active on Mobile */
      .modal-container.mobile-preview .form-column {
        display: none;
      }
      .modal-container.mobile-preview .preview-column {
        display: flex;
      }
    }

    @media (max-width: 768px) {
      header {
        padding: 0 16px;
        height: 58px;
      }
      .brand-title {
        font-size: 15px;
      }
      .brand-badge {
        display: none;
      }
      .status-badge {
        padding: 4px 8px;
        font-size: 11px;
      }
      .status-text-full {
        display: none;
      }

      .nav-inner {
        padding: 0 14px;
        height: 48px;
      }
      .tab-btn {
        font-size: 12px;
        padding: 6px 11px;
      }

      main {
        padding: 14px;
        gap: 16px;
      }

      .hero-banner {
        flex-direction: column;
        align-items: flex-start;
        padding: 18px;
      }
      .hero-left {
        width: 100%;
      }

      .commands-grid {
        grid-template-columns: 1fr;
      }

      .section-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
      }

      .toolbar-bar {
        flex-direction: column;
        align-items: stretch;
      }
      .search-box {
        max-width: 100%;
      }
    }

    @media (max-width: 520px) {
      .stats-grid {
        grid-template-columns: 1fr;
      }
      .stat-val {
        font-size: 22px;
      }
      .form-grid-2 {
        grid-template-columns: 1fr !important;
      }
      .toggles-grid-2 {
        grid-template-columns: 1fr !important;
      }
      .field-row-grid {
        grid-template-columns: 1fr !important;
      }
    }
  </style>
</head>
<body>

  <!-- Top Navigation -->
  <header>
    <a href="#" class="brand-wrap" onclick="switchTab('overview'); return false;">
      <div class="brand-logo">
        <img src="/favicon.gif" alt="AnymeX" onerror="this.onerror=null; this.src='https://raw.githubusercontent.com/Shebyyy/AnymeX-Preview/beta/assets/logo.png';">
      </div>
      <div class="brand-text">
        <span class="brand-title">AnymeX Preview</span>
        <span class="brand-badge">⚡ Bot Dashboard</span>
      </div>
    </a>

    <div class="header-actions">
      <div class="status-badge" id="top-status-badge">
        <span class="status-dot"></span>
        <span id="top-status-text">Online</span>
        <span class="status-text-full" id="top-ping-text">• Dual Sync</span>
      </div>
      <button class="btn btn-primary btn-sm" onclick="openCommandModal()">
        <svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        <span>New Command</span>
      </button>
      <button class="btn btn-secondary btn-sm btn-icon-only" onclick="logout()" title="Sign Out">
        <svg class="icon" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      </button>
    </div>
  </header>

  <!-- Sticky Horizontal Navigation Tabs Bar -->
  <nav class="nav-bar">
    <div class="nav-inner">
      <button class="tab-btn active" id="tab-btn-overview" onclick="switchTab('overview')">
        <svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
        <span>Overview</span>
      </button>
      <button class="tab-btn" id="tab-btn-commands" onclick="switchTab('commands')">
        <svg class="icon" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <span>Custom Commands</span>
        <span class="tab-badge" id="badge-custom-count">0</span>
      </button>
      <button class="tab-btn" id="tab-btn-builtin" onclick="switchTab('builtin')">
        <svg class="icon" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
        <span>Built-in Triggers</span>
        <span class="tab-badge" id="badge-builtin-count">6</span>
      </button>
      <button class="tab-btn" id="tab-btn-prefixes" onclick="switchTab('prefixes')">
        <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
        <span>Bot Prefixes</span>
        <span class="tab-badge" id="badge-prefixes-count">1</span>
      </button>
      <button class="tab-btn" id="tab-btn-backups" onclick="switchTab('backups')">
        <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        <span>Backups & Sync</span>
        <span class="tab-badge" id="badge-backups-count">0</span>
      </button>
    </div>
  </nav>

  <!-- Main Container -->
  <main>

    <!-- ══════════════════════════════════════════════════════════════════════
         TAB 1: OVERVIEW & BOT METRICS
         ══════════════════════════════════════════════════════════════════════ -->
    <section id="view-overview" class="view-content active">
      <!-- Hero Banner -->
      <div class="hero-banner">
        <div class="hero-left">
          <div class="hero-avatar">
            <img id="hero-bot-avatar" src="/favicon.gif" alt="Bot Avatar" onerror="this.onerror=null; this.src='https://raw.githubusercontent.com/Shebyyy/AnymeX-Preview/beta/assets/logo.png';">
          </div>
          <div>
            <div class="hero-name">
              <span id="hero-bot-name">AnymeX Preview</span>
              <span style="background: var(--discord); font-size: 11px; padding: 2px 6px; border-radius: 4px; font-family: var(--font-ui); font-weight: 700;">BOT</span>
            </div>
            <div class="hero-chips">
              <span class="hero-chip">
                <span class="status-dot"></span>
                <span id="hero-status-text">Online</span>
              </span>
              <span class="hero-chip" id="hero-latency-chip">
                <svg class="icon" style="width:13px; height:13px;" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                <span id="hero-ping-val">-- ms</span>
              </span>
              <span class="hero-chip">
                <svg class="icon" style="width:13px; height:13px;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span id="hero-uptime-val">Uptime: Active</span>
              </span>
              <span class="hero-chip" style="color: #38bdf8; border-color: rgba(56, 189, 248, 0.3);">
                <svg class="icon" style="width:13px; height:13px;" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                Dual Persistence Active
              </span>
            </div>
          </div>
        </div>
        <div>
          <button class="btn btn-primary" onclick="openCommandModal()">
            <svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Create Trigger
          </button>
        </div>
      </div>

      <!-- Stats Grid -->
      <div class="stats-grid" style="margin-top: 18px;">
        <div class="stat-card">
          <div class="stat-top">
            <span>Custom Commands</span>
            <svg class="icon" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          </div>
          <div class="stat-val" id="stat-custom-val">0</div>
          <div class="stat-foot">Dynamic embeds & keyword triggers</div>
        </div>

        <div class="stat-card">
          <div class="stat-top">
            <span>Built-in Triggers</span>
            <svg class="icon" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          </div>
          <div class="stat-val" id="stat-builtin-val">6</div>
          <div class="stat-foot">Protected native bot commands</div>
        </div>

        <div class="stat-card">
          <div class="stat-top">
            <span>Active Prefixes</span>
            <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
          </div>
          <div class="stat-val" id="stat-prefixes-val">?</div>
          <div class="stat-foot">Configured message prefixes</div>
        </div>

        <div class="stat-card">
          <div class="stat-top">
            <span>Server Backups</span>
            <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/></svg>
          </div>
          <div class="stat-val" id="stat-backups-val">0</div>
          <div class="stat-foot">Disk snapshots ready to restore</div>
        </div>
      </div>

      <!-- Quick Action Shortcuts -->
      <div style="margin-top: 24px;">
        <h3 style="font-size: 16px; font-weight: 700; margin-bottom: 14px; color: var(--text-main);">Quick Management Actions</h3>
        <div class="actions-grid">
          <div class="action-card" onclick="openCommandModal()">
            <div class="action-icon-wrap">
              <svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            </div>
            <div>
              <div class="action-title">Create Custom Command</div>
              <div class="action-sub">Build a new trigger with rich Discord embed</div>
            </div>
          </div>

          <div class="action-card" onclick="switchTab('builtin')">
            <div class="action-icon-wrap" style="color: #a78bfa; background: rgba(167, 139, 250, 0.15);">
              <svg class="icon" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
            </div>
            <div>
              <div class="action-title">Browse Built-in Commands</div>
              <div class="action-sub">View collapsible categories & native triggers</div>
            </div>
          </div>

          <div class="action-card" onclick="switchTab('prefixes')">
            <div class="action-icon-wrap" style="color: #34d399; background: rgba(52, 211, 153, 0.15);">
              <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
            </div>
            <div>
              <div class="action-title">Manage Bot Prefixes</div>
              <div class="action-sub">Add or remove symbols like '?' or '!'</div>
            </div>
          </div>

          <div class="action-card" onclick="switchTab('backups')">
            <div class="action-icon-wrap" style="color: #f59e0b; background: rgba(245, 158, 11, 0.15);">
              <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            </div>
            <div>
              <div class="action-title">Restore / View Backups</div>
              <div class="action-sub">Inspect snapshots and sync status</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Dual Sync Architecture Info -->
      <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 20px; margin-top: 24px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 15px;">
            <svg class="icon" style="color: #38bdf8;" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span>Dual-Persistence Engine Active</span>
          </div>
          <span style="font-size: 11px; padding: 2px 8px; border-radius: 12px; background: rgba(16, 185, 129, 0.15); color: #34d399; font-weight: 600;">Zero Data Loss</span>
        </div>
        <p style="font-size: 13px; color: var(--text-muted); line-height: 1.6;">
          Every custom trigger created, edited, or removed through this dashboard is automatically backed up in two locations simultaneously:
          <strong style="color: white;">Local Server Disk</strong> (rolling timestamped snapshots) and <strong style="color: white;">GitHub Repository</strong> (synced to <code>custom_commands.json</code>).
        </p>
      </div>
    </section>

    <!-- ══════════════════════════════════════════════════════════════════════
         TAB 2: CUSTOM COMMANDS & TRIGGERS
         ══════════════════════════════════════════════════════════════════════ -->
    <section id="view-commands" class="view-content">
      <div class="section-header">
        <div>
          <h2 class="section-title">
            <svg class="icon" style="color: var(--cyan);" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <span>Custom Commands & Triggers</span>
          </h2>
          <p class="section-subtitle">Manage dynamic prefix commands (like ?nob) and keyword auto-responses.</p>
        </div>
        <button class="btn btn-primary" onclick="openCommandModal()">
          <svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <span>New Command</span>
        </button>
      </div>

      <!-- Search & Filters Toolbar -->
      <div class="toolbar-bar">
        <div class="search-box">
          <svg class="icon search-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" id="custom-search-input" placeholder="Search trigger, alias, or title..." oninput="filterCustomCommands()">
        </div>
        <div class="filter-pills">
          <button class="filter-pill active" onclick="setFilter('all', this)">All</button>
          <button class="filter-pill" onclick="setFilter('prefix', this)">Prefix Required</button>
          <button class="filter-pill" onclick="setFilter('direct', this)">Direct Keyword</button>
          <button class="filter-pill" onclick="setFilter('autodel', this)">Auto-Delete</button>
        </div>
      </div>

      <!-- Commands Grid -->
      <div class="commands-grid" id="commands-container">
        <!-- Rendered via JS -->
      </div>
    </section>

    <!-- ══════════════════════════════════════════════════════════════════════
         TAB 3: BUILT-IN COMMANDS (COLLAPSIBLE & ORGANIZED)
         ══════════════════════════════════════════════════════════════════════ -->
    <section id="view-builtin" class="view-content">
      <div class="section-header">
        <div>
          <h2 class="section-title">
            <svg class="icon" style="color: #a78bfa;" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
            <span>Built-in Native Bot Commands</span>
          </h2>
          <p class="section-subtitle">Hardcoded bot features categorized by domain. Click any category to expand or collapse.</p>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions(true)">Expand All</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions(false)">Collapse All</button>
        </div>
      </div>

      <!-- Search in Builtin -->
      <div class="toolbar-bar" style="margin-bottom: 16px;">
        <div class="search-box">
          <svg class="icon search-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" id="builtin-search-input" placeholder="Search built-in command..." oninput="filterBuiltinCommands()">
        </div>
        <span style="font-size: 12px; color: var(--text-subtle);">Protected Native Python Handlers</span>
      </div>

      <!-- Accordion Container -->
      <div id="builtin-accordion-container">
        <!-- Rendered via JS by category -->
      </div>
    </section>

    <!-- ══════════════════════════════════════════════════════════════════════
         TAB 4: BOT PREFIXES
         ══════════════════════════════════════════════════════════════════════ -->
    <section id="view-prefixes" class="view-content">
      <div class="section-header">
        <div>
          <h2 class="section-title">
            <svg class="icon" style="color: #34d399;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
            <span>Active Bot Prefixes</span>
          </h2>
          <p class="section-subtitle">Prefixes recognized by AnymeX Preview Bot across Discord (synced with prefixes.json).</p>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px;">
        <!-- Add Prefix Card -->
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 22px;">
          <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 6px; color: var(--text-main);">Add New Prefix</h3>
          <p style="font-size: 12px; color: var(--text-subtle); margin-bottom: 16px;">Enter a character symbol (e.g. ! or . or >) that users type before commands.</p>

          <div style="display: flex; gap: 10px; margin-bottom: 14px;">
            <input type="text" id="new-prefix-input" class="form-input" placeholder="e.g. !" maxlength="5" style="width: 140px; font-family: var(--font-code); font-weight: 700; font-size: 16px;">
            <button class="btn btn-primary" onclick="addPrefix()">Add Prefix</button>
          </div>

          <div style="background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 12px; font-size: 12px; color: var(--text-muted);">
            <div style="font-weight: 600; color: white; margin-bottom: 4px;">Live Invocation Preview</div>
            <div>Typing <code style="color: #38bdf8; font-family: var(--font-code);" id="prefix-demo-text">?commands</code> or <code style="color: #38bdf8; font-family: var(--font-code);" id="prefix-demo-text-custom">?nob</code> will trigger the bot.</div>
          </div>
        </div>

        <!-- Active Prefixes List Card -->
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 22px;">
          <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 6px; color: var(--text-main);">Currently Active Prefixes</h3>
          <p style="font-size: 12px; color: var(--text-subtle); margin-bottom: 16px;">All prefixes recognized in server chats:</p>
          <div id="prefixes-list" style="display: flex; flex-wrap: wrap; gap: 10px;">
            <!-- Rendered via JS -->
          </div>
        </div>
      </div>
    </section>

    <!-- ══════════════════════════════════════════════════════════════════════
         TAB 5: BACKUPS & DUAL PERSISTENCE
         ══════════════════════════════════════════════════════════════════════ -->
    <section id="view-backups" class="view-content">
      <div class="section-header">
        <div>
          <h2 class="section-title">
            <svg class="icon" style="color: #f59e0b;" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Backups & Dual Persistence</span>
          </h2>
          <p class="section-subtitle">Local server disk snapshots and GitHub dual synchronization status.</p>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="fetchBackups(true)">
          <svg class="icon" viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
          Refresh Backups
        </button>
      </div>

      <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 22px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
          <div>
            <h3 style="font-size: 15px; font-weight: 700; color: white;">Disk Snapshots (Rolling 20 Backups)</h3>
            <p style="font-size: 12px; color: var(--text-subtle);">Click 'Restore' on any snapshot to revert custom commands.</p>
          </div>
          <span style="font-size: 11px; padding: 3px 8px; border-radius: 12px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; font-weight: 600;">Auto-Pruned</span>
        </div>

        <div id="backups-container" style="display: flex; flex-direction: column; gap: 10px;">
          <!-- Rendered via JS -->
        </div>
      </div>
    </section>
  </main>

  <!-- ══════════════════════════════════════════════════════════════════════════
       MODAL: COMMAND & EMBED BUILDER (Responsive & Mobile Segmented)
       ══════════════════════════════════════════════════════════════════════════ -->
  <div class="modal-backdrop" id="command-modal">
    <div class="modal-container" id="modal-container-card">
      <div class="modal-header">
        <div class="modal-title-wrap">
          <h3 class="modal-title" id="modal-heading">Create Custom Command</h3>
        </div>

        <!-- Segmented Switch for Mobile (<900px) -->
        <div class="modal-view-switch">
          <button class="switch-btn active" id="sw-btn-editor" onclick="switchModalView('editor')">
            <svg class="icon" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            <span>Editor</span>
          </button>
          <button class="switch-btn" id="sw-btn-preview" onclick="switchModalView('preview')">
            <svg class="icon" viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            <span>Preview</span>
          </button>
        </div>

        <div style="display: flex; gap: 8px;">
          <button class="btn btn-secondary btn-sm" onclick="closeCommandModal()">Close</button>
        </div>
      </div>

      <div class="modal-body">
        <!-- Form Column -->
        <div class="form-column">
          <input type="hidden" id="cmd-id">

          <!-- Trigger and Aliases -->
          <div class="form-grid-2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
            <div class="form-group">
              <label class="form-label">
                <span>Trigger Keyword</span>
                <span style="color: var(--brand); font-size: 10px;">Required</span>
              </label>
              <input type="text" id="cmd-name" class="form-input" placeholder="e.g. nob" oninput="updatePreview()" style="font-family: var(--font-code); font-weight: 700;">
            </div>
            <div class="form-group">
              <label class="form-label">
                <span>Aliases (Comma separated)</span>
              </label>
              <input type="text" id="cmd-aliases" class="form-input" placeholder="e.g. noob, nub" style="font-family: var(--font-code);">
            </div>
          </div>

          <!-- Toggles Grid -->
          <div class="toggles-grid-2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">Prefix Required</span>
                <span class="toggle-desc">e.g. ?nob vs plain nob</span>
              </div>
              <label class="switch">
                <input type="checkbox" id="cmd-prefix-req" checked>
                <span class="slider"></span>
              </label>
            </div>

            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">Auto-Delete Trigger</span>
                <span class="toggle-desc">Deletes caller's chat text</span>
              </div>
              <label class="switch">
                <input type="checkbox" id="cmd-delete-trigger" checked>
                <span class="slider"></span>
              </label>
            </div>

            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">Reply to Target</span>
                <span class="toggle-desc">Replies if triggered on user</span>
              </div>
              <label class="switch">
                <input type="checkbox" id="cmd-reply-mode" checked>
                <span class="slider"></span>
              </label>
            </div>

            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">Mention User</span>
                <span class="toggle-desc">Pings targeted user</span>
              </div>
              <label class="switch">
                <input type="checkbox" id="cmd-mention-user" checked>
                <span class="slider"></span>
              </label>
            </div>
          </div>

          <!-- Plain Content (Optional Text above embed) -->
          <div class="form-group">
            <label class="form-label">Optional Chat Message (Plain Text above Embed)</label>
            <input type="text" id="cmd-content" class="form-input" placeholder="e.g. Hey {user}, check this out!" oninput="updatePreview()">
          </div>

          <!-- Embed Builder Fields -->
          <div style="border-top: 1px solid var(--border-subtle); padding-top: 16px;">
            <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 12px; color: var(--text-main); display: flex; align-items: center; gap: 6px;">
              <svg class="icon" style="color: var(--discord);" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
              <span>Discord Response Embed</span>
            </h4>

            <!-- Color Palette -->
            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label">Embed Accent Color</label>
              <div class="color-picker-wrap">
                <div class="color-swatch active" style="background: #5865F2;" onclick="setColor('#5865F2')" title="Blurple"></div>
                <div class="color-swatch" style="background: #38BDF8;" onclick="setColor('#38BDF8')" title="Cyan"></div>
                <div class="color-swatch" style="background: #10B981;" onclick="setColor('#10B981')" title="Green"></div>
                <div class="color-swatch" style="background: #F59E0B;" onclick="setColor('#F59E0B')" title="Amber"></div>
                <div class="color-swatch" style="background: #EF4444;" onclick="setColor('#EF4444')" title="Red"></div>
                <div class="color-swatch" style="background: #8B5CF6;" onclick="setColor('#8B5CF6')" title="Purple"></div>
                <input type="color" id="cmd-color-picker" value="#5865F2" style="width: 28px; height: 28px; border: none; background: transparent; cursor: pointer;" onchange="setColor(this.value)">
                <input type="text" id="cmd-color-hex" class="form-input" value="#5865F2" style="width: 95px; font-family: var(--font-code); padding: 5px 8px; font-size: 12px;" oninput="setColor(this.value)">
              </div>
            </div>

            <!-- Author -->
            <div class="form-grid-2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
              <div class="form-group">
                <label class="form-label">Author Name</label>
                <input type="text" id="cmd-author-name" class="form-input" placeholder="e.g. AnymeX Support" oninput="updatePreview()">
              </div>
              <div class="form-group">
                <label class="form-label">Author Icon URL</label>
                <input type="text" id="cmd-author-icon" class="form-input" placeholder="https://..." oninput="updatePreview()">
              </div>
            </div>

            <!-- Title & URL -->
            <div class="form-grid-2" style="display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 12px; margin-bottom: 12px;">
              <div class="form-group">
                <label class="form-label">Embed Title</label>
                <input type="text" id="cmd-title" class="form-input" placeholder="e.g. Quick Help & Guide" oninput="updatePreview()">
              </div>
              <div class="form-group">
                <label class="form-label">Title Link URL</label>
                <input type="text" id="cmd-title-url" class="form-input" placeholder="https://..." oninput="updatePreview()">
              </div>
            </div>

            <!-- Description -->
            <div class="form-group" style="margin-bottom: 12px;">
              <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
                <label class="form-label" style="margin-bottom:0;">Description</label>
                <div style="display: flex; gap: 6px;">
                  <button type="button" class="btn btn-secondary btn-sm" style="padding: 2px 7px; font-size: 10px;" onclick="insertTag('{user}')">+ {user}</button>
                  <button type="button" class="btn btn-secondary btn-sm" style="padding: 2px 7px; font-size: 10px;" onclick="insertTag('{server}')">+ {server}</button>
                </div>
              </div>
              <textarea id="cmd-desc" class="form-textarea" placeholder="Hello {user}! Check this guide..." oninput="updatePreview()"></textarea>
            </div>

            <!-- Fields Dynamic Section -->
            <div style="margin-bottom: 14px;">
              <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <label class="form-label" style="margin-bottom:0;">Embed Fields</label>
                <button type="button" class="btn btn-secondary btn-sm" onclick="addField()">+ Add Field</button>
              </div>
              <div id="fields-container" style="display: flex; flex-direction: column; gap: 8px;">
                <!-- Dynamic Fields added here -->
              </div>
            </div>

            <!-- Thumbnail & Banner -->
            <div class="form-grid-2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
              <div class="form-group">
                <label class="form-label">Thumbnail URL</label>
                <input type="text" id="cmd-thumb" class="form-input" placeholder="https://..." oninput="updatePreview()">
              </div>
              <div class="form-group">
                <label class="form-label">Banner Image URL</label>
                <input type="text" id="cmd-image" class="form-input" placeholder="https://..." oninput="updatePreview()">
              </div>
            </div>

            <!-- Footer -->
            <div class="form-group" style="margin-bottom: 14px;">
              <label class="form-label">Footer Text</label>
              <input type="text" id="cmd-footer" class="form-input" placeholder="AnymeX • Quick Commands" oninput="updatePreview()">
            </div>

            <!-- Test Send Directly from Modal -->
            <div class="test-send-card">
              <div style="font-weight: 600; font-size: 12px; color: var(--text-main); display: flex; align-items: center; gap: 6px;">
                <svg class="icon" style="color: var(--cyan);" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                <span>Live Discord Channel Test</span>
              </div>
              <div style="display: flex; gap: 8px;">
                <input type="text" id="test-channel-id" class="form-input" placeholder="Discord Channel ID (e.g. 123456789...)" style="font-family: var(--font-code); font-size: 12px;">
                <button type="button" class="btn btn-secondary btn-sm" onclick="sendTestFromModal()">
                  <span>Send Test</span>
                </button>
              </div>
            </div>
          </div>

          <!-- Bottom Action Buttons -->
          <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 10px; position: sticky; bottom: 0; background: var(--bg-surface); padding-top: 10px; border-top: 1px solid var(--border-subtle);">
            <button class="btn btn-secondary" onclick="closeCommandModal()">Cancel</button>
            <button class="btn btn-primary" id="save-cmd-btn" onclick="saveCommand()">
              <svg class="icon" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              <span>Save & Sync Dual</span>
            </button>
          </div>
        </div>

        <!-- Live Preview Side -->
        <div class="preview-column">
          <div class="preview-header">
            <svg class="icon" viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            <span>Live Discord Preview</span>
          </div>

          <div class="discord-message">
            <div class="discord-avatar">
              <img id="p-bot-avatar" src="/favicon.gif" alt="Bot" onerror="this.onerror=null; this.src='https://raw.githubusercontent.com/Shebyyy/AnymeX-Preview/beta/assets/logo.png';">
            </div>
            <div class="discord-content">
              <div class="discord-meta">
                <span class="discord-username" id="p-bot-name">AnymeX Preview</span>
                <span class="discord-bot-tag">BOT</span>
                <span class="discord-timestamp">Today at 12:00 PM</span>
              </div>

              <!-- Content above embed -->
              <div id="p-content-text" style="font-size: 14px; color: #dbdee1; margin-bottom: 4px; display: none;"></div>

              <!-- Embed Card -->
              <div class="discord-embed" id="preview-embed">
                <div class="d-author" id="p-author" style="display:none;">
                  <img id="p-author-icon" style="display:none;" alt="">
                  <span id="p-author-name"></span>
                </div>
                <a class="d-title" id="p-title" href="#" target="_blank" style="display:none;"></a>
                <div class="d-desc" id="p-desc"></div>
                <div class="d-fields" id="p-fields" style="display:none;"></div>
                <img class="d-image" id="p-image" style="display:none;" alt="">
                <div class="d-footer" id="p-footer" style="display:none;">
                  <span id="p-footer-text"></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Toast Element -->
  <div id="toast"></div>

  <!-- ══════════════════════════════════════════════════════════════════════════
       FRONTEND JAVASCRIPT LOGIC
       ══════════════════════════════════════════════════════════════════════════ -->
  <script>
    let activeCommands = [];
    let builtinCommands = [];
    let activePrefixes = ['?'];
    let serverBackups = [];
    let currentColor = '#5865F2';
    let currentFilter = 'all';

    async function init() {
      await fetchMe();
      await fetchStats();
      await fetchCommands();
      await fetchPrefixes();
      await fetchBackups();
    }

    async function fetchMe() {
      try {
        const res = await fetch('/dashboard/api/me');
        if (res.status === 401) {
          window.location.href = '/dashboard/login';
        }
      } catch(e) {}
    }

    async function fetchStats() {
      try {
        const res = await fetch('/dashboard/api/stats');
        const data = await res.json();
        if (data.success) {
          const pingStr = `${data.latency_ms}ms`;
          document.getElementById('top-status-text').innerText = data.bot_online ? 'Online' : 'Offline';
          document.getElementById('top-ping-text').innerText = `• ${pingStr}`;
          document.getElementById('hero-ping-val').innerText = pingStr;
          document.getElementById('hero-status-text').innerText = data.bot_online ? 'Online' : 'Standby';

          if (data.bot_name) {
            document.getElementById('hero-bot-name').innerText = data.bot_name;
            document.getElementById('p-bot-name').innerText = data.bot_name;
          }
          if (data.bot_avatar) {
            document.getElementById('hero-bot-avatar').src = data.bot_avatar;
            document.getElementById('p-bot-avatar').src = data.bot_avatar;
          }

          // Format uptime
          const sec = data.uptime_seconds || 0;
          const d = Math.floor(sec / 86400);
          const h = Math.floor((sec % 86400) / 3600);
          const m = Math.floor((sec % 3600) / 60);
          const uptimeStr = d > 0 ? `${d}d ${h}h ${m}m` : (h > 0 ? `${h}h ${m}m` : `${m}m active`);
          document.getElementById('hero-uptime-val').innerText = `Uptime: ${uptimeStr}`;

          // Stats badges
          document.getElementById('stat-custom-val').innerText = data.custom_commands_count || 0;
          document.getElementById('badge-custom-count').innerText = data.custom_commands_count || 0;
          document.getElementById('stat-builtin-val').innerText = data.builtin_commands_count || 6;
          document.getElementById('badge-builtin-count').innerText = data.builtin_commands_count || 6;
          document.getElementById('stat-prefixes-val').innerText = (data.prefixes || ['?']).join('  ');
          document.getElementById('badge-prefixes-count').innerText = (data.prefixes || ['?']).length;
          document.getElementById('stat-backups-val').innerText = data.backups_count || 0;
          document.getElementById('badge-backups-count').innerText = data.backups_count || 0;
        }
      } catch(e) {}
    }

    async function fetchCommands() {
      try {
        const res = await fetch('/dashboard/api/commands');
        const data = await res.json();
        if (data.success) {
          activeCommands = data.commands || [];
          builtinCommands = data.builtin_commands || [];
          renderCommands();
          renderBuiltinAccordion();
          document.getElementById('badge-custom-count').innerText = activeCommands.length;
          document.getElementById('stat-custom-val').innerText = activeCommands.length;
        }
      } catch(e) {
        showToast('Failed to load commands', true);
      }
    }

    async function fetchPrefixes() {
      try {
        const res = await fetch('/dashboard/api/prefixes');
        const data = await res.json();
        if (data.success) {
          activePrefixes = data.prefixes || ['?'];
          renderPrefixes();
          renderCommands();
          renderBuiltinAccordion();
          document.getElementById('badge-prefixes-count').innerText = activePrefixes.length;
          document.getElementById('stat-prefixes-val').innerText = activePrefixes.join('  ');
          const p = activePrefixes[0] || '?';
          document.getElementById('prefix-demo-text').innerText = `${p}commands`;
          document.getElementById('prefix-demo-text-custom').innerText = `${p}nob`;
        }
      } catch(e) {}
    }

    async function fetchBackups(showNotice = false) {
      try {
        const res = await fetch('/dashboard/api/backups');
        const data = await res.json();
        if (data.success) {
          serverBackups = data.backups || [];
          renderBackups();
          document.getElementById('badge-backups-count').innerText = serverBackups.length;
          document.getElementById('stat-backups-val').innerText = serverBackups.length;
          if (showNotice) showToast('Backups refreshed');
        }
      } catch(e) {}
    }

    /* ══════════════════════════════════════════════════════════════════════════
       RENDERERS
       ══════════════════════════════════════════════════════════════════════════ */

    function renderCommands() {
      const c = document.getElementById('commands-container');
      const search = (document.getElementById('custom-search-input')?.value || '').toLowerCase().trim();
      const p = activePrefixes[0] || '?';

      const filtered = activeCommands.filter(cmd => {
        // Filter by pill
        if (currentFilter === 'prefix' && !cmd.prefix_required) return false;
        if (currentFilter === 'direct' && cmd.prefix_required) return false;
        if (currentFilter === 'autodel' && !cmd.delete_trigger) return false;

        // Search match
        if (!search) return true;
        const nameMatch = (cmd.name || '').toLowerCase().includes(search);
        const aliasMatch = (cmd.aliases || []).some(a => a.toLowerCase().includes(search));
        const titleMatch = (cmd.embed?.title || '').toLowerCase().includes(search);
        const descMatch = (cmd.embed?.description || '').toLowerCase().includes(search);
        return nameMatch || aliasMatch || titleMatch || descMatch;
      });

      if (!filtered.length) {
        c.innerHTML = `
          <div style="grid-column: 1/-1; text-align: center; color: var(--text-subtle); padding: 50px 20px; background: var(--bg-surface); border: 1px dashed var(--border-subtle); border-radius: var(--radius-lg);">
            <svg class="icon" style="width: 36px; height: 36px; color: var(--text-subtle); margin-bottom: 12px;" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <div style="font-size: 15px; font-weight: 700; color: var(--text-main); margin-bottom: 6px;">No Custom Commands Found</div>
            <div style="font-size: 13px; max-width: 400px; margin: 0 auto 16px auto;">
              ${search ? 'No commands match your search query.' : 'Create your first custom trigger (like "nob") with rich Discord response embeds.'}
            </div>
            <button class="btn btn-primary btn-sm" onclick="openCommandModal()">+ Create New Command</button>
          </div>
        `;
        return;
      }

      c.innerHTML = filtered.map(cmd => {
        const triggerDisplay = cmd.prefix_required ? `${p}${cmd.name}` : cmd.name;
        const aliasesHtml = (cmd.aliases || []).map(a => `<span class="alias-pill">${escapeHtml(a)}</span>`).join('');
        const embedColor = cmd.embed?.color || '#5865F2';

        return `
          <div class="command-card">
            <div class="card-top">
              <div>
                <span class="trigger-badge">${escapeHtml(triggerDisplay)}</span>
                <div class="aliases-list">${aliasesHtml}</div>
              </div>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-secondary btn-sm btn-icon-only" onclick="editCommand('${cmd.id}')" title="Edit Command">
                  <svg class="icon" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="btn btn-secondary btn-sm btn-icon-only" onclick="promptSendTest('${cmd.id}')" title="Test Send to Channel">
                  <svg class="icon" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                </button>
                <button class="btn btn-danger btn-sm btn-icon-only" onclick="deleteCommand('${cmd.id}')" title="Delete">
                  <svg class="icon" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </div>
            </div>

            <div class="card-badges">
              <span class="feature-badge ${cmd.prefix_required ? 'active' : ''}">Prefix Req</span>
              <span class="feature-badge ${cmd.delete_trigger ? 'active' : ''}">Auto-Delete</span>
              <span class="feature-badge ${cmd.reply_mode ? 'active' : ''}">Reply</span>
              <span class="feature-badge ${cmd.mention_user ? 'active' : ''}">Mention</span>
            </div>

            <div class="card-embed-preview" style="border-left-color: ${embedColor};">
              <div class="card-embed-title">${escapeHtml(cmd.embed?.title || cmd.name)}</div>
              <div class="card-embed-desc">${escapeHtml(cmd.embed?.description || 'Custom response embed')}</div>
            </div>

            <div class="card-footer">
              <span>Used ${cmd.usage_count || 0} times</span>
              <span style="color: #38bdf8;">Dual Persisted</span>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderBuiltinAccordion() {
      const container = document.getElementById('builtin-accordion-container');
      if (!container) return;

      const p = activePrefixes[0] || '?';
      const search = (document.getElementById('builtin-search-input')?.value || '').toLowerCase().trim();

      // Group commands by category
      const categories = [
        {
          id: 'core',
          name: 'Core Bot Commands',
          desc: 'Primary navigation and directory triggers',
          icon: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'
        },
        {
          id: 'admin',
          name: 'Admin & Configuration',
          desc: 'Prefix and bot management triggers',
          icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        },
        {
          id: 'info',
          name: 'Information & FAQ Triggers',
          desc: 'Knowledge base items and server rules',
          icon: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>'
        },
        {
          id: 'fun',
          name: 'Fun & Interactive Triggers',
          desc: 'Chat greetings and playful responses',
          icon: '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>'
        }
      ];

      container.innerHTML = categories.map((cat, idx) => {
        const catCmds = builtinCommands.filter(c => {
          const matchCat = (c.category || 'Core').toLowerCase() === cat.id;
          if (!matchCat) return false;
          if (!search) return true;
          return (c.name || '').toLowerCase().includes(search) ||
                 (c.description || '').toLowerCase().includes(search) ||
                 (c.aliases || []).some(a => a.toLowerCase().includes(search));
        });

        if (search && catCmds.length === 0) return '';

        const cardsHtml = catCmds.map(cmd => {
          const triggerDisplay = (cmd.trigger_display || cmd.name).replace(/{p}/g, p);
          const aliasesHtml = (cmd.aliases || []).map(a => `<span class="alias-pill">${escapeHtml(a)}</span>`).join('');
          return `
            <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 16px; display: flex; flex-direction: column; gap: 8px;">
              <div style="display: flex; align-items: center; justify-content: space-between;">
                <span class="trigger-badge" style="background: rgba(167, 139, 250, 0.15); color: #c4b5fd; border-color: rgba(167, 139, 250, 0.3);">
                  ${escapeHtml(triggerDisplay)}
                </span>
                <span style="font-size: 11px; padding: 2px 7px; border-radius: 4px; background: var(--bg-elevated); color: var(--text-subtle);">Protected</span>
              </div>
              <div class="aliases-list">${aliasesHtml}</div>
              <div style="font-size: 13px; color: var(--text-muted); line-height: 1.5; margin-top: 4px;">
                ${escapeHtml(cmd.description || '')}
              </div>
            </div>
          `;
        }).join('');

        const isOpen = idx === 0 || !!search; // First open by default, or all open when searching

        return `
          <div class="accordion-section ${isOpen ? 'open' : ''}" id="acc-${cat.id}">
            <div class="accordion-header" onclick="toggleAccordion('acc-${cat.id}')">
              <div class="accordion-title-wrap">
                <svg class="icon" style="color: #a78bfa;" viewBox="0 0 24 24">${cat.icon}</svg>
                <div>
                  <div class="accordion-title">${cat.name} (${catCmds.length})</div>
                  <div class="accordion-desc">${cat.desc}</div>
                </div>
              </div>
              <svg class="icon accordion-chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
            </div>
            <div class="accordion-body">
              <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 14px;">
                ${cardsHtml || '<div style="color: var(--text-subtle); font-size: 13px;">No commands in this category.</div>'}
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    function toggleAccordion(id) {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('open');
    }

    function toggleAllAccordions(open) {
      document.querySelectorAll('.accordion-section').forEach(sec => {
        if (open) sec.classList.add('open');
        else sec.classList.remove('open');
      });
    }

    function filterBuiltinCommands() {
      renderBuiltinAccordion();
    }

    function filterCustomCommands() {
      renderCommands();
    }

    function setFilter(filter, btn) {
      currentFilter = filter;
      document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      renderCommands();
    }

    function renderPrefixes() {
      const list = document.getElementById('prefixes-list');
      if (!list) return;
      list.innerHTML = activePrefixes.map(p => `
        <div style="background: var(--bg-elevated); border: 1px solid var(--border-subtle); padding: 8px 14px; border-radius: var(--radius-md); display: flex; align-items: center; gap: 10px;">
          <span style="font-family: var(--font-code); font-weight: 700; color: #38bdf8; font-size: 16px;">${escapeHtml(p)}</span>
          <button class="btn btn-danger btn-sm" style="padding: 2px 6px;" onclick="removePrefix('${p}')" title="Delete prefix">✕</button>
        </div>
      `).join('');
    }

    function renderBackups() {
      const container = document.getElementById('backups-container');
      if (!container) return;

      if (!serverBackups.length) {
        container.innerHTML = '<div style="color: var(--text-subtle); font-size: 13px; text-align: center; padding: 20px;">No backup files found yet on server disk.</div>';
        return;
      }

      container.innerHTML = serverBackups.map(b => {
        const sizeKb = (b.size_bytes / 1024).toFixed(1);
        return `
          <div style="background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
            <div>
              <div style="font-family: var(--font-code); font-size: 13px; font-weight: 700; color: white;">${escapeHtml(b.filename)}</div>
              <div style="font-size: 11px; color: var(--text-subtle); margin-top: 2px;">
                <span>Saved: ${escapeHtml(b.formatted_time || 'Recent')}</span> • <span>${sizeKb} KB</span>
              </div>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="restoreBackup('${b.filename}')">
              <svg class="icon" viewBox="0 0 24 24"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
              <span>Restore</span>
            </button>
          </div>
        `;
      }).join('');
    }

    /* ══════════════════════════════════════════════════════════════════════════
       ACTIONS & MODAL LOGIC
       ══════════════════════════════════════════════════════════════════════════ */

    function switchTab(tab) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view-content').forEach(v => v.classList.remove('active'));

      const btn = document.getElementById(`tab-btn-${tab}`);
      const view = document.getElementById(`view-${tab}`);
      if (btn) btn.classList.add('active');
      if (view) view.classList.add('active');

      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function switchModalView(mode) {
      const container = document.getElementById('modal-container-card');
      const swEditor = document.getElementById('sw-btn-editor');
      const swPreview = document.getElementById('sw-btn-preview');

      if (mode === 'preview') {
        container.classList.add('mobile-preview');
        swPreview.classList.add('active');
        swEditor.classList.remove('active');
      } else {
        container.classList.remove('mobile-preview');
        swEditor.classList.add('active');
        swPreview.classList.remove('active');
      }
    }

    function openCommandModal(cmd = null) {
      document.getElementById('cmd-id').value = cmd?.id || '';
      document.getElementById('modal-heading').innerText = cmd ? `Edit Trigger: ${cmd.name}` : 'Create Custom Command';
      document.getElementById('cmd-name').value = cmd?.name || '';
      document.getElementById('cmd-aliases').value = (cmd?.aliases || []).join(', ');
      document.getElementById('cmd-prefix-req').checked = cmd ? cmd.prefix_required : true;
      document.getElementById('cmd-delete-trigger').checked = cmd ? cmd.delete_trigger : true;
      document.getElementById('cmd-reply-mode').checked = cmd ? cmd.reply_mode : true;
      document.getElementById('cmd-mention-user').checked = cmd ? cmd.mention_user : true;
      document.getElementById('cmd-content').value = cmd?.content || '';

      const embed = cmd?.embed || {};
      setColor(embed.color || '#5865F2');
      document.getElementById('cmd-author-name').value = embed.author?.name || '';
      document.getElementById('cmd-author-icon').value = embed.author?.icon_url || '';
      document.getElementById('cmd-title').value = embed.title || '';
      document.getElementById('cmd-title-url').value = embed.url || '';
      document.getElementById('cmd-desc').value = embed.description || '';
      document.getElementById('cmd-thumb').value = embed.thumbnail_url || '';
      document.getElementById('cmd-image').value = embed.image_url || '';
      document.getElementById('cmd-footer').value = embed.footer?.text || '';

      const fieldsCont = document.getElementById('fields-container');
      fieldsCont.innerHTML = '';
      (embed.fields || []).forEach(f => addField(f.name, f.value, f.inline));

      switchModalView('editor');
      updatePreview();
      document.getElementById('command-modal').classList.add('open');
    }

    function closeCommandModal() {
      document.getElementById('command-modal').classList.remove('open');
    }

    function editCommand(id) {
      const cmd = activeCommands.find(c => c.id === id);
      if (cmd) openCommandModal(cmd);
    }

    function insertTag(tag) {
      const textarea = document.getElementById('cmd-desc');
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const text = textarea.value;
      textarea.value = text.substring(0, start) + tag + text.substring(end);
      textarea.focus();
      textarea.selectionStart = textarea.selectionEnd = start + tag.length;
      updatePreview();
    }

    function setColor(hex) {
      if (!hex.startsWith('#')) hex = '#' + hex;
      currentColor = hex;
      document.getElementById('cmd-color-hex').value = hex;
      document.getElementById('cmd-color-picker').value = hex;
      document.getElementById('preview-embed').style.borderLeftColor = hex;

      document.querySelectorAll('.color-swatch').forEach(sw => {
        sw.classList.toggle('active', sw.getAttribute('onclick')?.includes(hex));
      });
    }

    function addField(name = '', val = '', inline = true) {
      const container = document.getElementById('fields-container');
      const div = document.createElement('div');
      div.className = 'field-item';
      div.style.cssText = 'display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; align-items: center;';
      div.innerHTML = `
        <input type="text" class="form-input f-name" placeholder="Field Title" value="${escapeHtml(name)}" oninput="updatePreview()">
        <input type="text" class="form-input f-val" placeholder="Field Value" value="${escapeHtml(val)}" oninput="updatePreview()">
        <button type="button" class="btn btn-danger btn-sm" onclick="this.parentElement.remove(); updatePreview();">✕</button>
      `;
      container.appendChild(div);
      updatePreview();
    }

    function updatePreview() {
      const content = document.getElementById('cmd-content').value;
      const author = document.getElementById('cmd-author-name').value;
      const authorIcon = document.getElementById('cmd-author-icon').value;
      const title = document.getElementById('cmd-title').value;
      const titleUrl = document.getElementById('cmd-title-url').value;
      const desc = document.getElementById('cmd-desc').value;
      const image = document.getElementById('cmd-image').value;
      const footer = document.getElementById('cmd-footer').value;

      // Plain content above embed
      const pContent = document.getElementById('p-content-text');
      if (content) {
        pContent.innerText = content;
        pContent.style.display = 'block';
      } else {
        pContent.style.display = 'none';
      }

      // Author
      const pAuthor = document.getElementById('p-author');
      const pAuthorName = document.getElementById('p-author-name');
      const pAuthorIcon = document.getElementById('p-author-icon');
      if (author) {
        pAuthor.style.display = 'flex';
        pAuthorName.innerText = author;
        if (authorIcon) {
          pAuthorIcon.src = authorIcon;
          pAuthorIcon.style.display = 'inline-block';
        } else {
          pAuthorIcon.style.display = 'none';
        }
      } else {
        pAuthor.style.display = 'none';
      }

      // Title
      const pTitle = document.getElementById('p-title');
      if (title) {
        pTitle.style.display = 'block';
        pTitle.innerText = title;
        pTitle.href = titleUrl || '#';
      } else {
        pTitle.style.display = 'none';
      }

      // Desc
      document.getElementById('p-desc').innerText = desc || 'Embed response preview...';

      // Fields
      const pFields = document.getElementById('p-fields');
      const fieldItems = document.querySelectorAll('.field-item');
      if (fieldItems.length > 0) {
        pFields.style.display = 'grid';
        pFields.innerHTML = Array.from(fieldItems).map(item => {
          const fn = item.querySelector('.f-name').value;
          const fv = item.querySelector('.f-val').value;
          return `<div><div class="d-field-name">${escapeHtml(fn || 'Field')}</div><div class="d-field-val">${escapeHtml(fv || 'Value')}</div></div>`;
        }).join('');
      } else {
        pFields.style.display = 'none';
      }

      // Banner Image
      const pImg = document.getElementById('p-image');
      if (image) {
        pImg.src = image;
        pImg.style.display = 'block';
      } else {
        pImg.style.display = 'none';
      }

      // Footer
      const pFooter = document.getElementById('p-footer');
      if (footer) {
        pFooter.style.display = 'flex';
        document.getElementById('p-footer-text').innerText = footer;
      } else {
        pFooter.style.display = 'none';
      }
    }

    async function saveCommand() {
      const name = document.getElementById('cmd-name').value.trim();
      if (!name) {
        showToast('Command trigger keyword is required', true);
        return;
      }

      const saveBtn = document.getElementById('save-cmd-btn');
      saveBtn.disabled = true;
      saveBtn.innerText = 'Saving...';

      const aliases = document.getElementById('cmd-aliases').value
        .split(',')
        .map(a => a.trim())
        .filter(Boolean);

      const fieldItems = document.querySelectorAll('.field-item');
      const fields = Array.from(fieldItems).map(item => ({
        name: item.querySelector('.f-name').value.trim(),
        value: item.querySelector('.f-val').value.trim(),
        inline: true
      })).filter(f => f.name && f.value);

      const payload = {
        id: document.getElementById('cmd-id').value,
        name: name,
        aliases: aliases,
        prefix_required: document.getElementById('cmd-prefix-req').checked,
        delete_trigger: document.getElementById('cmd-delete-trigger').checked,
        reply_mode: document.getElementById('cmd-reply-mode').checked,
        mention_user: document.getElementById('cmd-mention-user').checked,
        content: document.getElementById('cmd-content').value.trim(),
        embed: {
          title: document.getElementById('cmd-title').value.trim(),
          url: document.getElementById('cmd-title-url').value.trim(),
          description: document.getElementById('cmd-desc').value.trim(),
          color: currentColor,
          author: {
            name: document.getElementById('cmd-author-name').value.trim(),
            icon_url: document.getElementById('cmd-author-icon').value.trim()
          },
          thumbnail_url: document.getElementById('cmd-thumb').value.trim(),
          image_url: document.getElementById('cmd-image').value.trim(),
          footer: {
            text: document.getElementById('cmd-footer').value.trim()
          },
          fields: fields
        }
      };

      try {
        const res = await fetch('/dashboard/api/commands', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
          closeCommandModal();
          await fetchCommands();
          await fetchBackups();
          showToast(`Saved '${name}' to Server Disk & Synced to GitHub!`);
        } else {
          showToast(data.error || 'Failed to save', true);
        }
      } catch(e) {
        showToast('Network error while saving command', true);
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerText = 'Save & Sync Dual';
      }
    }

    async function deleteCommand(id) {
      const cmd = activeCommands.find(c => c.id === id);
      const name = cmd ? cmd.name : id;
      if (!confirm(`Are you sure you want to delete custom trigger '${name}'?`)) return;

      const res = await fetch(`/dashboard/api/commands/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        activeCommands = activeCommands.filter(c => c.id !== id);
        renderCommands();
        await fetchBackups();
        showToast(`Command '${name}' deleted and dual synced`);
      } else {
        showToast(data.error || 'Failed to delete', true);
      }
    }

    async function addPrefix() {
      const input = document.getElementById('new-prefix-input');
      const val = input.value.trim();
      if (!val) return;
      const res = await fetch('/dashboard/api/prefixes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prefix: val })
      });
      const data = await res.json();
      if (data.success) {
        input.value = '';
        activePrefixes = data.prefixes;
        renderPrefixes();
        renderCommands();
        renderBuiltinAccordion();
        showToast(`Prefix '${val}' added and synced to GitHub!`);
      } else {
        showToast(data.error || 'Failed to add prefix', true);
      }
    }

    async function removePrefix(p) {
      if (activePrefixes.length <= 1) {
        showToast('Cannot remove the only active prefix', true);
        return;
      }
      if (!confirm(`Remove prefix '${p}'?`)) return;

      const res = await fetch(`/dashboard/api/prefixes/${encodeURIComponent(p)}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        activePrefixes = data.prefixes;
        renderPrefixes();
        renderCommands();
        renderBuiltinAccordion();
        showToast(`Prefix '${p}' removed`);
      } else {
        showToast(data.error || 'Failed to remove', true);
      }
    }

    async function restoreBackup(filename) {
      if (!confirm(`Are you sure you want to restore custom commands from snapshot '${filename}'? This will replace current custom commands.`)) return;
      const res = await fetch('/dashboard/api/backups/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename })
      });
      const data = await res.json();
      if (data.success) {
        await fetchCommands();
        await fetchBackups();
        showToast(`Successfully restored from ${filename}!`);
        switchTab('commands');
      } else {
        showToast(data.error || 'Failed to restore', true);
      }
    }

    async function sendTestFromModal() {
      const channelId = document.getElementById('test-channel-id').value.trim();
      if (!channelId) {
        showToast('Enter a Discord Channel ID first', true);
        return;
      }

      const payload = {
        channel_id: channelId,
        command: {
          name: document.getElementById('cmd-name').value.trim() || 'preview',
          content: document.getElementById('cmd-content').value.trim(),
          embed: {
            title: document.getElementById('cmd-title').value.trim(),
            url: document.getElementById('cmd-title-url').value.trim(),
            description: document.getElementById('cmd-desc').value.trim(),
            color: currentColor,
            author: {
              name: document.getElementById('cmd-author-name').value.trim(),
              icon_url: document.getElementById('cmd-author-icon').value.trim()
            },
            thumbnail_url: document.getElementById('cmd-thumb').value.trim(),
            image_url: document.getElementById('cmd-image').value.trim(),
            footer: {
              text: document.getElementById('cmd-footer').value.trim()
            }
          }
        }
      };

      try {
        const res = await fetch('/dashboard/api/test_send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Test embed sent to #${data.channel}!`);
        } else {
          showToast(data.error || 'Failed to send test message', true);
        }
      } catch(e) {
        showToast('Connection error sending test', true);
      }
    }

    async function promptSendTest(cmdId) {
      const cmd = activeCommands.find(c => c.id === cmdId);
      if (!cmd) return;
      const channelId = prompt(`Enter Discord Channel ID to test send '${cmd.name}':`);
      if (!channelId) return;

      try {
        const res = await fetch('/dashboard/api/test_send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ channel_id: channelId.trim(), command: cmd })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Sent test message to #${data.channel}!`);
        } else {
          showToast(data.error || 'Failed to send test', true);
        }
      } catch(e) {
        showToast('Connection error', true);
      }
    }

    function showToast(msg, isError = false) {
      const t = document.getElementById('toast');
      t.innerText = msg;
      t.className = isError ? 'error show' : 'success show';
      setTimeout(() => t.classList.remove('show'), 3500);
    }

    async function logout() {
      await fetch('/dashboard/api/logout', { method: 'POST' });
      window.location.href = '/dashboard/login';
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
    }

    init();
  </script>
</body>
</html>"""


def _login_page_html() -> str:
    """Return sleek modern login page with Discord OAuth and Passkey options."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login — AnymeX Preview Bot Dashboard</title>
  <link rel="icon" type="image/gif" href="/favicon.gif">
  <link rel="shortcut icon" type="image/gif" href="/favicon.gif">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@600;700;800&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #080b11;
      color: #f8fafc;
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .login-card {
      background: #0e1422;
      border: 1px solid #1e293b;
      border-radius: 16px;
      padding: 40px;
      max-width: 420px;
      width: 100%;
      box-shadow: 0 20px 50px rgba(0,0,0,0.5);
      text-align: center;
    }
    .logo-badge {
      width: 48px;
      height: 48px;
      background: linear-gradient(135deg, #6366f1, #38bdf8);
      border-radius: 12px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: 'Outfit', sans-serif;
      font-size: 24px;
      font-weight: 800;
      color: white;
      margin-bottom: 20px;
      box-shadow: 0 0 24px rgba(99, 102, 241, 0.4);
    }
    h1 {
      font-family: 'Outfit', sans-serif;
      font-size: 22px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    p {
      color: #94a3b8;
      font-size: 13px;
      margin-bottom: 28px;
    }
    .btn {
      width: 100%;
      padding: 12px 18px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      border: 1px solid transparent;
      text-decoration: none;
      transition: all 0.15s;
    }
    .btn-discord {
      background: #5865F2;
      color: white;
      margin-bottom: 20px;
    }
    .btn-discord:hover { background: #4752c4; }
    .divider {
      display: flex;
      align-items: center;
      color: #64748b;
      font-size: 12px;
      margin-bottom: 20px;
    }
    .divider::before, .divider::after {
      content: '';
      flex: 1;
      height: 1px;
      background: #1e293b;
    }
    .divider span { padding: 0 12px; }
    .input-passkey {
      width: 100%;
      background: #141c30;
      border: 1px solid #1e293b;
      color: white;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 14px;
      margin-bottom: 12px;
    }
    .input-passkey:focus {
      outline: none;
      border-color: #6366f1;
    }
    .btn-passkey {
      background: #1c2742;
      color: white;
      border-color: #334155;
    }
    .btn-passkey:hover { background: #233152; }
    .error-msg {
      color: #f87171;
      font-size: 12px;
      margin-top: 12px;
      display: none;
    }
  </style>
</head>
<body>
  <div class="login-card">
    <div class="logo-badge" style="overflow: hidden; padding: 0; display: inline-flex; align-items: center; justify-content: center;">
      <img src="/favicon.gif" alt="AnymeX" style="width: 100%; height: 100%; object-fit: cover; border-radius: 12px;">
    </div>
    <h1>AnymeX Bot Dashboard</h1>
    <p>Sign in to manage custom commands, responses, and bot prefixes.</p>

    <a href="/dashboard/auth/discord" class="btn btn-discord">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.893.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
      Login with Discord (Admin)
    </a>

    <div class="divider"><span>OR PASSKEY</span></div>

    <form onsubmit="handlePasskeyLogin(event)">
      <input type="password" id="passkey" class="input-passkey" placeholder="Enter API Secret / Passkey" required>
      <button type="submit" class="btn btn-passkey">Sign in with Passkey</button>
      <div id="error-msg" class="error-msg"></div>
    </form>
  </div>

  <script>
    async function handlePasskeyLogin(e) {
      e.preventDefault();
      const passkey = document.getElementById('passkey').value.trim();
      const err = document.getElementById('error-msg');
      err.style.display = 'none';

      try {
        const res = await fetch('/dashboard/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ passkey })
        });
        const data = await res.json();
        if (data.success) {
          window.location.href = '/dashboard';
        } else {
          err.innerText = data.error || 'Invalid passkey';
          err.style.display = 'block';
        }
      } catch(err) {
        err.innerText = 'Connection error';
        err.style.display = 'block';
      }
    }
  </script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# Route registration setup
# ══════════════════════════════════════════════════════════════════════════════

def setup(app: web.Application, bot: discord.Client, *,
          get_prefix_cache_fn=None,
          set_prefix_cache_fn=None,
          github_read_fn=None,
          github_write_fn=None,
          read_admins_fn=None):
    """Mount all dashboard and API routes onto the aiohttp application."""
    global _bot, _get_prefix_cache_fn, _set_prefix_cache_fn, _github_read_fn, _github_write_fn, _read_admins_fn
    _bot = bot
    _get_prefix_cache_fn = get_prefix_cache_fn
    _set_prefix_cache_fn = set_prefix_cache_fn
    _github_read_fn = github_read_fn
    _github_write_fn = github_write_fn
    _read_admins_fn = read_admins_fn

    # Web Pages
    async def _handle_dashboard(request):
        sess = _get_current_session(request)
        if not sess:
            return web.HTTPFound("/dashboard/login")
        return web.Response(text=_dashboard_page_html(), content_type="text/html")

    async def _handle_login(request):
        sess = _get_current_session(request)
        if sess:
            return web.HTTPFound("/dashboard")
        return web.Response(text=_login_page_html(), content_type="text/html")

    app.router.add_get("/dashboard", _handle_dashboard)
    app.router.add_get("/dashboard/", _handle_dashboard)
    app.router.add_get("/dashboard/login", _handle_login)

    # Favicon routes (animated favicon.gif)
    favicon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "favicon.gif")
    async def _handle_favicon(request: web.Request):
        if os.path.exists(favicon_path):
            return web.FileResponse(favicon_path, headers={"Content-Type": "image/gif", "Cache-Control": "public, max-age=86400"})
        return web.Response(status=204)
    app.router.add_get("/favicon.gif", _handle_favicon)
    app.router.add_get("/favicon.ico", _handle_favicon)

    # Auth
    app.router.add_get("/dashboard/auth/discord", auth_discord_redirect)
    app.router.add_get("/auth/discord", auth_discord_redirect)
    app.router.add_get("/dashboard/auth/discord/callback", auth_discord_callback)
    app.router.add_get("/auth/callback", auth_discord_callback)
    app.router.add_get("/dashboard/auth/callback", auth_discord_callback)
    app.router.add_post("/dashboard/api/login", api_login_passkey)
    app.router.add_post("/dashboard/api/logout", api_logout)
    app.router.add_get("/dashboard/api/me", api_me)

    # Commands & Prefixes
    app.router.add_get("/dashboard/api/stats", api_get_stats)
    app.router.add_get("/dashboard/api/commands", api_get_commands)
    app.router.add_post("/dashboard/api/commands", api_save_command)
    app.router.add_delete("/dashboard/api/commands/{id}", api_delete_command)

    app.router.add_get("/dashboard/api/prefixes", api_get_prefixes)
    app.router.add_post("/dashboard/api/prefixes", api_add_prefix)
    app.router.add_delete("/dashboard/api/prefixes/{prefix}", api_delete_prefix)

    app.router.add_get("/dashboard/api/backups", api_get_backups)
    app.router.add_post("/dashboard/api/backups/restore", api_restore_backup)
    app.router.add_post("/dashboard/api/test_send", api_test_send)

    print("✅ Dashboard routes mounted (/dashboard, /dashboard/login, /dashboard/api/*)")
