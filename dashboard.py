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
    """Return the public base URL for OAuth callbacks, strictly enforcing HTTPS for non-localhost."""
    raw_base = (OAUTH_BASE_URL or "").strip().rstrip("/")
    if raw_base:
        base = raw_base
    else:
        host = request.headers.get("X-Forwarded-Host") or request.host
        proto = request.headers.get("X-Forwarded-Proto")
        if not proto:
            proto = "http" if ("localhost" in host or "127.0.0.1" in host) else "https"
        base = f"{proto}://{host}"

    # Enforce https for all public domains
    if not ("localhost" in base or "127.0.0.1" in base):
        if base.startswith("http://"):
            base = "https://" + base[7:]
        elif not base.startswith("https://"):
            base = "https://" + base

    return base


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

async def api_get_commands(request: web.Request):
    """GET /dashboard/api/commands — Return all custom commands."""
    _require_auth(request)
    cmds = custom_triggers.get_commands()
    return web.json_response({"success": True, "commands": cmds})


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

    # Check for name collision with other commands
    for c in current_cmds:
        if c.get("id") != cmd_id and c.get("name", "").lower() == name:
            return web.json_response({"error": f"A command with trigger '{name}' already exists"}, status=409)

    embed_data = body.get("embed") or {}
    updated_cmd = {
        "id": cmd_id,
        "name": name,
        "aliases": [str(a).strip().lower() for a in body.get("aliases", []) if str(a).strip()],
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AnymeX Bot — Command & Embed Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #080b11;
      --bg-surface: #0e1422;
      --bg-elevated: #141c30;
      --bg-hover: #1c2742;
      --border-subtle: #1e293b;
      --border-strong: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-subtle: #64748b;
      --brand: #6366f1;
      --brand-hover: #4f46e5;
      --brand-glow: rgba(99, 102, 241, 0.25);
      --discord: #5865F2;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --font-ui: 'Inter', -apple-system, sans-serif;
      --font-display: 'Outfit', sans-serif;
      --font-code: 'JetBrains Mono', monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-ui);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      line-height: 1.5;
      overflow-x: hidden;
    }

    /* SVG Icon styles */
    .icon {
      width: 18px;
      height: 18px;
      stroke-width: 2;
      stroke: currentColor;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
      display: inline-block;
      vertical-align: middle;
    }

    /* Top Navigation Header */
    header {
      background: rgba(14, 20, 34, 0.85);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-subtle);
      padding: 0 28px;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 50;
    }

    .brand-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-logo {
      width: 34px;
      height: 34px;
      background: linear-gradient(135deg, #6366f1, #38bdf8);
      border-radius: var(--radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-weight: 800;
      font-family: var(--font-display);
      font-size: 18px;
      box-shadow: 0 0 16px var(--brand-glow);
    }

    .brand-title {
      font-family: var(--font-display);
      font-size: 18px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text-main);
    }

    .brand-badge {
      background: var(--bg-elevated);
      border: 1px solid var(--border-subtle);
      color: var(--brand);
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 20px;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .status-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.25);
      color: #34d399;
      font-size: 12px;
      padding: 4px 10px;
      border-radius: 20px;
      font-weight: 500;
    }

    .status-dot {
      width: 7px;
      height: 7px;
      background: #10b981;
      border-radius: 50%;
      box-shadow: 0 0 8px #10b981;
    }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: var(--radius-md);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      border: 1px solid transparent;
      outline: none;
      font-family: var(--font-ui);
    }

    .btn-primary {
      background: var(--brand);
      color: white;
      box-shadow: 0 4px 12px var(--brand-glow);
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
      background: rgba(239, 68, 68, 0.15);
      color: #fca5a5;
      border-color: rgba(239, 68, 68, 0.3);
    }
    .btn-danger:hover {
      background: var(--danger);
      color: white;
    }

    .btn-sm {
      padding: 5px 10px;
      font-size: 12px;
      border-radius: var(--radius-sm);
    }

    /* Main Container & Tabs */
    main {
      flex: 1;
      max-width: 1440px;
      width: 100%;
      margin: 0 auto;
      padding: 28px;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    .nav-tabs {
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 12px;
    }

    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 14px;
      font-weight: 600;
      padding: 8px 16px;
      border-radius: var(--radius-md);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.15s;
    }
    .tab-btn:hover {
      color: var(--text-main);
      background: var(--bg-elevated);
    }
    .tab-btn.active {
      color: white;
      background: var(--brand);
      box-shadow: 0 4px 12px var(--brand-glow);
    }

    /* Views */
    .view-content { display: none; }
    .view-content.active { display: block; }

    /* Commands Grid */
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
    }
    .section-title {
      font-family: var(--font-display);
      font-size: 20px;
      font-weight: 700;
      color: var(--text-main);
    }
    .section-subtitle {
      font-size: 13px;
      color: var(--text-subtle);
      margin-top: 2px;
    }

    .commands-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 18px;
    }

    .command-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 20px;
      transition: all 0.2s ease;
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: relative;
    }
    .command-card:hover {
      border-color: var(--border-strong);
      transform: translateY(-2px);
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.3);
    }

    .card-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
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
      gap: 6px;
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

    .card-desc {
      color: var(--text-muted);
      font-size: 13px;
      flex: 1;
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
      padding-top: 14px;
      margin-top: auto;
    }

    .usage-count {
      font-size: 12px;
      color: var(--text-subtle);
      display: flex;
      align-items: center;
      gap: 4px;
    }

    /* Modal / Drawer for Embed Builder */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .modal-backdrop.open { display: flex; }

    .modal-container {
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      width: 100%;
      max-width: 1260px;
      height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 24px 60px rgba(0,0,0,0.6);
      overflow: hidden;
    }

    .modal-header {
      padding: 18px 24px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-elevated);
    }
    .modal-title {
      font-family: var(--font-display);
      font-size: 18px;
      font-weight: 700;
    }

    .modal-body {
      flex: 1;
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      overflow: hidden;
    }

    /* Form Column */
    .form-column {
      padding: 24px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 20px;
      border-right: 1px solid var(--border-subtle);
    }

    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-label {
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
    }
    .form-input, .form-textarea, .form-select {
      background: var(--bg-elevated);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 10px 14px;
      border-radius: var(--radius-md);
      font-size: 13px;
      font-family: var(--font-ui);
      transition: border-color 0.15s;
    }
    .form-input:focus, .form-textarea:focus, .form-select:focus {
      outline: none;
      border-color: var(--brand);
      box-shadow: 0 0 0 3px var(--brand-glow);
    }
    .form-textarea { resize: vertical; min-height: 80px; }

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
      gap: 10px;
    }
    .color-swatch {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      cursor: pointer;
      border: 2px solid transparent;
      transition: transform 0.15s;
    }
    .color-swatch:hover { transform: scale(1.15); }
    .color-swatch.active { border-color: white; }

    /* Discord Preview Column */
    .preview-column {
      background: #1e1f22;
      padding: 28px;
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
      gap: 16px;
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
    .d-footer img { width: 18px; height: 18px; border-radius: 50%; }

    .d-buttons-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }
    .d-btn {
      background: #4e5058;
      color: white;
      font-size: 13px;
      font-weight: 500;
      padding: 6px 14px;
      border-radius: 3px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
    }
    .d-btn:hover { background: #6d6f78; }

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
      z-index: 200;
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
  </style>
</head>
<body>

  <!-- Top Navigation -->
  <header>
    <div class="brand-wrap">
      <div class="brand-logo">A</div>
      <div>
        <span class="brand-title">AnymeX Preview</span>
        <span class="brand-badge">Bot Dashboard</span>
      </div>
    </div>

    <div class="header-actions">
      <div class="status-badge">
        <span class="status-dot"></span>
        <span>Bot Online & Dual Sync Active</span>
      </div>
      <button class="btn btn-secondary btn-sm" onclick="showBackupsModal()">
        <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        Backups
      </button>
      <button class="btn btn-primary btn-sm" onclick="openCommandModal()">
        <svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New Command
      </button>
      <button class="btn btn-secondary btn-sm" onclick="logout()" title="Logout">
        <svg class="icon" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      </button>
    </div>
  </header>

  <!-- Main Content -->
  <main>
    <!-- Navigation Tabs -->
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('commands')">
        <svg class="icon" viewBox="0 0 24 24"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
        Custom Commands & Triggers
      </button>
      <button class="tab-btn" onclick="switchTab('prefixes')">
        <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
        Bot Prefixes
      </button>
    </div>

    <!-- Commands Tab -->
    <section id="view-commands" class="view-content active">
      <div class="section-header">
        <div>
          <h2 class="section-title">Trigger Commands</h2>
          <p class="section-subtitle">Commands triggered by prefix (e.g. ?nob) or keyword, with auto-delete and reply targeting.</p>
        </div>
      </div>

      <div class="commands-grid" id="commands-container">
        <!-- Rendered via JS -->
      </div>
    </section>

    <!-- Prefixes Tab -->
    <section id="view-prefixes" class="view-content">
      <div class="section-header">
        <div>
          <h2 class="section-title">Active Bot Prefixes</h2>
          <p class="section-subtitle">Prefixes recognized by AnymeX Preview Bot across Discord (synced with prefixes.json).</p>
        </div>
      </div>

      <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); padding: 24px; max-width: 600px;">
        <div style="display: flex; gap: 10px; margin-bottom: 20px;">
          <input type="text" id="new-prefix-input" class="form-input" placeholder="e.g. ! or . or >" maxlength="5" style="width: 160px; font-family: var(--font-code);">
          <button class="btn btn-primary" onclick="addPrefix()">Add Prefix</button>
        </div>
        <div id="prefixes-list" style="display: flex; flex-wrap: wrap; gap: 10px;">
          <!-- Rendered via JS -->
        </div>
      </div>
    </section>
  </main>

  <!-- Command Modal & Embed Builder -->
  <div class="modal-backdrop" id="command-modal">
    <div class="modal-container">
      <div class="modal-header">
        <h3 class="modal-title" id="modal-heading">Create Custom Command</h3>
        <button class="btn btn-secondary btn-sm" onclick="closeCommandModal()">Close</button>
      </div>

      <div class="modal-body">
        <!-- Form Side -->
        <div class="form-column">
          <input type="hidden" id="cmd-id">

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
            <div class="form-group">
              <label class="form-label">Command Trigger Name</label>
              <input type="text" id="cmd-name" class="form-input" placeholder="e.g. nob" oninput="updatePreview()">
            </div>
            <div class="form-group">
              <label class="form-label">Aliases (Comma separated)</label>
              <input type="text" id="cmd-aliases" class="form-input" placeholder="e.g. noob, nub">
            </div>
          </div>

          <!-- Toggles -->
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
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
                <span class="toggle-desc">Cleans chat message</span>
              </div>
              <label class="switch">
                <input type="checkbox" id="cmd-delete-trigger" checked>
                <span class="slider"></span>
              </label>
            </div>

            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">Reply to Reference</span>
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

          <!-- Embed Builder Fields -->
          <div style="border-top: 1px solid var(--border-subtle); padding-top: 16px;">
            <h4 style="font-size: 14px; font-weight: 700; margin-bottom: 12px; color: var(--text-main);">Custom Response Embed</h4>

            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label">Embed Color</label>
              <div class="color-picker-wrap">
                <div class="color-swatch active" style="background: #5865F2;" onclick="setColor('#5865F2')"></div>
                <div class="color-swatch" style="background: #10B981;" onclick="setColor('#10B981')"></div>
                <div class="color-swatch" style="background: #F59E0B;" onclick="setColor('#F59E0B')"></div>
                <div class="color-swatch" style="background: #EF4444;" onclick="setColor('#EF4444')"></div>
                <div class="color-swatch" style="background: #8B5CF6;" onclick="setColor('#8B5CF6')"></div>
                <input type="color" id="cmd-color-picker" value="#5865F2" style="width: 32px; height: 32px; border: none; background: transparent; cursor: pointer;" onchange="setColor(this.value)">
                <input type="text" id="cmd-color-hex" class="form-input" value="#5865F2" style="width: 100px; font-family: var(--font-code);" oninput="setColor(this.value)">
              </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
              <div class="form-group">
                <label class="form-label">Author Name</label>
                <input type="text" id="cmd-author-name" class="form-input" placeholder="e.g. AnymeX Support" oninput="updatePreview()">
              </div>
              <div class="form-group">
                <label class="form-label">Author Icon URL</label>
                <input type="text" id="cmd-author-icon" class="form-input" placeholder="https://..." oninput="updatePreview()">
              </div>
            </div>

            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label">Embed Title</label>
              <input type="text" id="cmd-title" class="form-input" placeholder="e.g. Quick Help & Guide" oninput="updatePreview()">
            </div>

            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label">Title Link URL (Optional)</label>
              <input type="text" id="cmd-title-url" class="form-input" placeholder="https://..." oninput="updatePreview()">
            </div>

            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label">Description (Supports {user}, {server})</label>
              <textarea id="cmd-desc" class="form-textarea" placeholder="Hello {user}! Check this guide..." oninput="updatePreview()"></textarea>
            </div>

            <!-- Fields Dynamic Section -->
            <div style="margin-bottom: 14px;">
              <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <label class="form-label">Embed Fields</label>
                <button type="button" class="btn btn-secondary btn-sm" onclick="addField()">+ Add Field</button>
              </div>
              <div id="fields-container" style="display: flex; flex-direction: column; gap: 8px;">
                <!-- Fields added here -->
              </div>
            </div>

            <!-- Thumbnail & Banner -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
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
            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label">Footer Text</label>
              <input type="text" id="cmd-footer" class="form-input" placeholder="AnymeX • Quick Commands" oninput="updatePreview()">
            </div>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 10px;">
            <button class="btn btn-secondary" onclick="closeCommandModal()">Cancel</button>
            <button class="btn btn-primary" onclick="saveCommand()">Save & Sync to GitHub</button>
          </div>
        </div>

        <!-- Live Preview Side -->
        <div class="preview-column">
          <div class="preview-header">
            <svg class="icon" viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            Live Discord Message Preview
          </div>

          <div class="discord-message">
            <div class="discord-avatar">
              <img src="https://raw.githubusercontent.com/Shebyyy/AnymeX-Preview/beta/assets/logo.png" onerror="this.src=''">
            </div>
            <div class="discord-content">
              <div class="discord-meta">
                <span class="discord-username">AnymeX Preview</span>
                <span class="discord-bot-tag">BOT</span>
                <span class="discord-timestamp">Today at 12:00 PM</span>
              </div>

              <!-- Embed Card -->
              <div class="discord-embed" id="preview-embed">
                <div class="d-author" id="p-author" style="display:none;">
                  <img id="p-author-icon" src="" style="display:none;">
                  <span id="p-author-name"></span>
                </div>
                <a class="d-title" id="p-title" href="#" target="_blank" style="display:none;"></a>
                <div class="d-desc" id="p-desc"></div>
                <div class="d-fields" id="p-fields" style="display:none;"></div>
                <img class="d-image" id="p-image" src="">
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

  <script>
    let activeCommands = [];
    let activePrefixes = [];
    let currentColor = '#5865F2';

    async function init() {
      await fetchMe();
      await fetchCommands();
      await fetchPrefixes();
    }

    async function fetchMe() {
      try {
        const res = await fetch('/dashboard/api/me');
        if (res.status === 401) {
          window.location.href = '/dashboard/login';
        }
      } catch(e) {}
    }

    async function fetchCommands() {
      try {
        const res = await fetch('/dashboard/api/commands');
        const data = await res.json();
        if (data.success) {
          activeCommands = data.commands;
          renderCommands();
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
          activePrefixes = data.prefixes;
          renderPrefixes();
        }
      } catch(e) {}
    }

    function renderCommands() {
      const c = document.getElementById('commands-container');
      if (!activeCommands.length) {
        c.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-subtle); padding: 40px;">No custom commands yet. Click "New Command" to create one like "nob".</div>';
        return;
      }
      c.innerHTML = activeCommands.map(cmd => {
        const p = activePrefixes[0] || '?';
        const triggerDisplay = cmd.prefix_required ? `${p}${cmd.name}` : cmd.name;
        const aliasesHtml = (cmd.aliases || []).map(a => `<span class="alias-pill">${a}</span>`).join('');
        return `
          <div class="command-card">
            <div class="card-top">
              <div>
                <span class="trigger-badge">${triggerDisplay}</span>
                <div class="aliases-list">${aliasesHtml}</div>
              </div>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-secondary btn-sm" onclick="editCommand('${cmd.id}')" title="Edit">
                  <svg class="icon" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="btn btn-danger btn-sm" onclick="deleteCommand('${cmd.id}')" title="Delete">
                  <svg class="icon" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </div>
            </div>

            <div class="card-badges">
              <span class="feature-badge ${cmd.delete_trigger ? 'active' : ''}">Auto-Delete</span>
              <span class="feature-badge ${cmd.reply_mode ? 'active' : ''}">Reply Target</span>
              <span class="feature-badge ${cmd.mention_user ? 'active' : ''}">Mention</span>
            </div>

            <div class="card-embed-preview" style="border-left-color: ${cmd.embed?.color || '#5865F2'}">
              <div class="card-embed-title">${escapeHtml(cmd.embed?.title || cmd.name)}</div>
              <div class="card-embed-desc">${escapeHtml(cmd.embed?.description || 'Custom response embed')}</div>
            </div>

            <div class="card-footer">
              <span class="usage-count">Used ${cmd.usage_count || 0} times</span>
              <span style="font-size: 11px; color: var(--text-subtle);">Dual Persisted</span>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderPrefixes() {
      const list = document.getElementById('prefixes-list');
      list.innerHTML = activePrefixes.map(p => `
        <div style="background: var(--bg-elevated); border: 1px solid var(--border-subtle); padding: 8px 14px; border-radius: var(--radius-md); display: flex; align-items: center; gap: 10px;">
          <span style="font-family: var(--font-code); font-weight: 700; color: #a5b4fc; font-size: 16px;">${escapeHtml(p)}</span>
          <button class="btn btn-danger btn-sm" style="padding: 2px 6px;" onclick="removePrefix('${p}')">✕</button>
        </div>
      `).join('');
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
        showToast('Prefix added and saved!');
      } else {
        showToast(data.error || 'Failed to add prefix', true);
      }
    }

    async function removePrefix(p) {
      if (activePrefixes.length <= 1) {
        showToast('Cannot remove the only prefix', true);
        return;
      }
      const res = await fetch(`/dashboard/api/prefixes/${encodeURIComponent(p)}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        activePrefixes = data.prefixes;
        renderPrefixes();
        renderCommands();
        showToast('Prefix removed');
      } else {
        showToast(data.error || 'Failed to remove', true);
      }
    }

    function openCommandModal(cmd = null) {
      document.getElementById('cmd-id').value = cmd?.id || '';
      document.getElementById('modal-heading').innerText = cmd ? 'Edit Command' : 'Create Custom Command';
      document.getElementById('cmd-name').value = cmd?.name || '';
      document.getElementById('cmd-aliases').value = (cmd?.aliases || []).join(', ');
      document.getElementById('cmd-prefix-req').checked = cmd ? cmd.prefix_required : true;
      document.getElementById('cmd-delete-trigger').checked = cmd ? cmd.delete_trigger : true;
      document.getElementById('cmd-reply-mode').checked = cmd ? cmd.reply_mode : true;
      document.getElementById('cmd-mention-user').checked = cmd ? cmd.mention_user : true;

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

      updatePreview();
      document.getElementById('command-modal').classList.add('open');
    }

    function editCommand(id) {
      const cmd = activeCommands.find(c => c.id === id);
      if (cmd) openCommandModal(cmd);
    }

    async function deleteCommand(id) {
      if (!confirm('Are you sure you want to delete this command?')) return;
      const res = await fetch(`/dashboard/api/commands/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        activeCommands = activeCommands.filter(c => c.id !== id);
        renderCommands();
        showToast('Command deleted and synced');
      } else {
        showToast(data.error || 'Failed to delete', true);
      }
    }

    function closeCommandModal() {
      document.getElementById('command-modal').classList.remove('open');
    }

    function setColor(hex) {
      currentColor = hex;
      document.getElementById('cmd-color-hex').value = hex;
      document.getElementById('cmd-color-picker').value = hex;
      document.getElementById('preview-embed').style.borderLeftColor = hex;
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
      const author = document.getElementById('cmd-author-name').value;
      const authorIcon = document.getElementById('cmd-author-icon').value;
      const title = document.getElementById('cmd-title').value;
      const titleUrl = document.getElementById('cmd-title-url').value;
      const desc = document.getElementById('cmd-desc').value;
      const image = document.getElementById('cmd-image').value;
      const footer = document.getElementById('cmd-footer').value;

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
      document.getElementById('p-desc').innerText = desc || 'Embed description preview...';

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

      // Image
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
        showToast('Command trigger name is required', true);
        return;
      }

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

      const res = await fetch('/dashboard/api/commands', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        closeCommandModal();
        await fetchCommands();
        showToast(`Saved '${name}' to Server & Synced to GitHub!`);
      } else {
        showToast(data.error || 'Failed to save', true);
      }
    }

    function switchTab(tab) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view-content').forEach(v => v.classList.remove('active'));
      if (tab === 'commands') {
        document.querySelectorAll('.tab-btn')[0].classList.add('active');
        document.getElementById('view-commands').classList.add('active');
      } else {
        document.querySelectorAll('.tab-btn')[1].classList.add('active');
        document.getElementById('view-prefixes').classList.add('active');
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
    <div class="logo-badge">A</div>
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
