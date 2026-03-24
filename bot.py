import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from aiohttp import web
import asyncio
import os
import base64
import json
import re
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

DISCORD_TOKEN  = os.environ.get("DISCORD_TOKEN")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN")
PORT           = int(os.environ.get("PORT", 8080))

GITHUB_OWNER   = "Shebyyy"
GITHUB_REPO    = "AnymeX-Preview"
GITHUB_BRANCH  = "beta"
WORKFLOW_FILE  = "beta_manual.yml"

GITHUB_API     = "https://api.github.com"
ANILIST_API    = "https://graphql.anilist.co"

# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL HTTP SESSION (Singleton Pattern)
# ══════════════════════════════════════════════════════════════════════════════

_http_session: aiohttp.ClientSession = None

async def get_session() -> aiohttp.ClientSession:
    """Get or create the global HTTP session."""
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=10, enable_cleanup_closed=True)
        _http_session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": "AnymeX-Preview-Bot/2.0"}
        )
    return _http_session

async def close_session():
    """Close the global HTTP session."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None

# File names on GitHub
FILE_ANIME        = "underrated_anime.json"
FILE_MANGA        = "underrated_manga.json"
FILE_USERS        = "users.json"
FILE_TIMEZONES    = "timezones.json"
FILE_PREFIXES     = "prefixes.json"
FILE_SERVERS      = "servers.json"      # Multi-server config
FILE_WARNINGS     = "warnings.json"     # Warnings per server
FILE_MUTES        = "mutes.json"        # Active mutes
FILE_MODLOG       = "modlog.json"       # Moderation logs
FILE_HONEYPOT     = "honeypot_logs.json" # Honeypot incidents
FILE_SNIPE        = "snipe.json"        # Deleted messages cache

DEFAULT_PREFIXES = ["?"]

# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT SERVER CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def get_default_server_config(guild_id: str, guild_name: str) -> dict:
    return {
        "guild_id": guild_id,
        "name": guild_name,
        "prefix": "?",
        "honeypot": {
            "enabled": False,
            "channel_id": None,
            "action": "kick",
            "delete_hours": 24,
            "whitelist_roles": [],
            "log_channel": None,
            "dm_message": "You were caught in a honeypot trap. This channel is restricted. If you believe this is an error, contact server staff."
        },
        "automod": {
            "enabled": True,
            "spam": {"enabled": True, "max_messages": 5, "seconds": 3, "action": "mute", "mute_duration": 10},
            "links": {"enabled": True, "delete": True, "warn": True, "whitelist": []},
            "invites": {"enabled": True, "delete": True, "action": "kick", "whitelist": []},
            "caps": {"enabled": True, "threshold": 70, "min_length": 10, "action": "delete"},
            "bad_words": {"enabled": False, "words": [], "action": "delete"},
            "mass_mention": {"enabled": True, "max_mentions": 5, "action": "mute", "mute_duration": 30}
        },
        "warnings": {
            "threshold": 3,
            "action": "mute",
            "mute_duration": 24,
            "expire_days": 30
        },
        "logging": {
            "modlog_channel": None,
            "message_delete": True,
            "message_edit": True,
            "user_join": True,
            "user_leave": True,
            "user_ban": True,
            "user_kick": True,
            "user_mute": True,
            "channel_changes": True,
            "role_changes": True
        },
        "permissions": {
            "admin_roles": [],
            "mod_roles": [],
            "trusted_roles": []
        },
        "muted_role_id": None,
        "welcome": {
            "enabled": False,
            "channel_id": None,
            "message": "Welcome {user} to {server}!",
            "dm_message": None
        },
        "leave": {
            "enabled": False,
            "channel_id": None,
            "message": "Goodbye {user}!"
        }
    }

# ══════════════════════════════════════════════════════════════════════════════
# COMPLETE WORLD TIMEZONE DATABASE
# ══════════════════════════════════════════════════════════════════════════════

TIMEZONES = {
    "BIT": {"code": "BIT", "name": "Baker Island Time", "offset": -12.0, "utc": "UTC-12:00", "region": "Pacific", "iana": "Etc/GMT+12"},
    "SST": {"code": "SST", "name": "Samoa Standard Time", "offset": -11.0, "utc": "UTC-11:00", "region": "Pacific", "iana": "Pacific/Pago_Pago"},
    "HST": {"code": "HST", "name": "Hawaii-Aleutian Standard Time", "offset": -10.0, "utc": "UTC-10:00", "region": "Americas", "iana": "Pacific/Honolulu"},
    "AKST": {"code": "AKST", "name": "Alaska Standard Time", "offset": -9.0, "utc": "UTC-09:00", "region": "Americas", "iana": "America/Anchorage"},
    "PST": {"code": "PST", "name": "Pacific Standard Time", "offset": -8.0, "utc": "UTC-08:00", "region": "Americas", "iana": "America/Los_Angeles"},
    "MST": {"code": "MST", "name": "Mountain Standard Time", "offset": -7.0, "utc": "UTC-07:00", "region": "Americas", "iana": "America/Denver"},
    "CST_US": {"code": "CST", "name": "Central Standard Time (US)", "offset": -6.0, "utc": "UTC-06:00", "region": "Americas", "iana": "America/Chicago"},
    "EST": {"code": "EST", "name": "Eastern Standard Time", "offset": -5.0, "utc": "UTC-05:00", "region": "Americas", "iana": "America/New_York"},
    "AST": {"code": "AST", "name": "Atlantic Standard Time", "offset": -4.0, "utc": "UTC-04:00", "region": "Americas", "iana": "America/Halifax"},
    "ART": {"code": "ART", "name": "Argentina Time", "offset": -3.0, "utc": "UTC-03:00", "region": "Americas", "iana": "America/Argentina/Buenos_Aires"},
    "UTC": {"code": "UTC", "name": "Coordinated Universal Time", "offset": 0.0, "utc": "UTC±00:00", "region": "UTC", "iana": "UTC"},
    "GMT": {"code": "GMT", "name": "Greenwich Mean Time", "offset": 0.0, "utc": "UTC±00:00", "region": "Europe", "iana": "Europe/London"},
    "CET": {"code": "CET", "name": "Central European Time", "offset": 1.0, "utc": "UTC+01:00", "region": "Europe", "iana": "Europe/Paris"},
    "EET": {"code": "EET", "name": "Eastern European Time", "offset": 2.0, "utc": "UTC+02:00", "region": "Europe", "iana": "Europe/Athens"},
    "MSK": {"code": "MSK", "name": "Moscow Standard Time", "offset": 3.0, "utc": "UTC+03:00", "region": "Europe", "iana": "Europe/Moscow"},
    "GST": {"code": "GST", "name": "Gulf Standard Time", "offset": 4.0, "utc": "UTC+04:00", "region": "Asia", "iana": "Asia/Dubai"},
    "PKT": {"code": "PKT", "name": "Pakistan Standard Time", "offset": 5.0, "utc": "UTC+05:00", "region": "Asia", "iana": "Asia/Karachi"},
    "IST": {"code": "IST", "name": "Indian Standard Time", "offset": 5.5, "utc": "UTC+05:30", "region": "Asia", "iana": "Asia/Kolkata"},
    "BDT": {"code": "BDT", "name": "Bangladesh Standard Time", "offset": 6.0, "utc": "UTC+06:00", "region": "Asia", "iana": "Asia/Dhaka"},
    "ICT": {"code": "ICT", "name": "Indochina Time", "offset": 7.0, "utc": "UTC+07:00", "region": "Asia", "iana": "Asia/Bangkok"},
    "WIB": {"code": "WIB", "name": "Western Indonesia Time", "offset": 7.0, "utc": "UTC+07:00", "region": "Asia", "iana": "Asia/Jakarta"},
    "CST": {"code": "CST", "name": "China Standard Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Shanghai"},
    "SGT": {"code": "SGT", "name": "Singapore Standard Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Singapore"},
    "JST": {"code": "JST", "name": "Japan Standard Time", "offset": 9.0, "utc": "UTC+09:00", "region": "Asia", "iana": "Asia/Tokyo"},
    "KST": {"code": "KST", "name": "Korea Standard Time", "offset": 9.0, "utc": "UTC+09:00", "region": "Asia", "iana": "Asia/Seoul"},
    "ACST": {"code": "ACST", "name": "Australian Central Standard Time", "offset": 9.5, "utc": "UTC+09:30", "region": "Australia", "iana": "Australia/Adelaide"},
    "AEST": {"code": "AEST", "name": "Australian Eastern Standard Time", "offset": 10.0, "utc": "UTC+10:00", "region": "Australia", "iana": "Australia/Sydney"},
    "NZST": {"code": "NZST", "name": "New Zealand Standard Time", "offset": 12.0, "utc": "UTC+12:00", "region": "Pacific", "iana": "Pacific/Auckland"},
}

# ══════════════════════════════════════════════════════════════════════════════
# GITHUB STORAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

async def github_read_json(filepath: str) -> tuple:
    """Read a JSON file from GitHub. Returns (parsed_data, sha)."""
    session = await get_session()
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}?ref={GITHUB_BRANCH}"
    
    try:
        async with session.get(url, headers=gh_headers()) as r:
            if r.status == 404:
                # Return appropriate default based on file type
                if filepath in (FILE_USERS, FILE_TIMEZONES, FILE_SERVERS, FILE_WARNINGS, FILE_MUTES, FILE_MODLOG, FILE_HONEYPOT, FILE_SNIPE):
                    return {}, None
                elif filepath == FILE_PREFIXES:
                    return DEFAULT_PREFIXES[:], None
                else:
                    return [], None
            
            if r.status != 200:
                text = await r.text()
                # Check if response is HTML (Cloudflare error)
                if text.startswith("<!DOCTYPE") or text.startswith("<html"):
                    print(f"GitHub API returned HTML (Cloudflare?) for {filepath}")
                else:
                    print(f"GitHub API error {r.status} for {filepath}: {text[:200]}")
                # Return defaults on error
                if filepath in (FILE_USERS, FILE_TIMEZONES, FILE_SERVERS, FILE_WARNINGS, FILE_MUTES, FILE_MODLOG, FILE_HONEYPOT, FILE_SNIPE):
                    return {}, None
                elif filepath == FILE_PREFIXES:
                    return DEFAULT_PREFIXES[:], None
                else:
                    return [], None
            
            data = await r.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
    except asyncio.TimeoutError:
        print(f"Timeout reading {filepath} from GitHub")
        if filepath in (FILE_USERS, FILE_TIMEZONES, FILE_SERVERS, FILE_WARNINGS, FILE_MUTES, FILE_MODLOG, FILE_HONEYPOT, FILE_SNIPE):
            return {}, None
        elif filepath == FILE_PREFIXES:
            return DEFAULT_PREFIXES[:], None
        else:
            return [], None
    except Exception as e:
        print(f"Error reading {filepath} from GitHub: {e}")
        # Return defaults on error
        if filepath in (FILE_USERS, FILE_TIMEZONES, FILE_SERVERS, FILE_WARNINGS, FILE_MUTES, FILE_MODLOG, FILE_HONEYPOT, FILE_SNIPE):
            return {}, None
        elif filepath == FILE_PREFIXES:
            return DEFAULT_PREFIXES[:], None
        else:
            return [], None

async def github_write_json(filepath: str, data, sha, commit_msg: str) -> bool:
    """Write/update a JSON file on GitHub. Returns True on success."""
    session = await get_session()
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(
            json.dumps(data, indent=2, ensure_ascii=False).encode()
        ).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}"
    
    try:
        async with session.put(url, headers=gh_headers(), json=payload) as r:
            if r.status not in (200, 201):
                text = await r.text()
                if text.startswith("<!DOCTYPE") or text.startswith("<html"):
                    print(f"GitHub API returned HTML (Cloudflare?) when writing {filepath}")
                else:
                    print(f"GitHub write error {r.status} for {filepath}: {text[:200]}")
            return r.status in (200, 201)
    except asyncio.TimeoutError:
        print(f"Timeout writing {filepath} to GitHub")
        return False
    except Exception as e:
        print(f"Error writing {filepath} to GitHub: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SERVER CONFIG MANAGER
# ══════════════════════════════════════════════════════════════════════════════

_server_config_cache: Dict[str, dict] = {}

async def get_server_config(guild_id: str) -> dict:
    """Get server config from cache or GitHub."""
    if guild_id in _server_config_cache:
        return _server_config_cache[guild_id]
    
    servers, _ = await github_read_json(FILE_SERVERS)
    
    if guild_id not in servers:
        return None
    
    _server_config_cache[guild_id] = servers[guild_id]
    return servers[guild_id]

async def save_server_config(guild_id: str, config: dict) -> bool:
    """Save server config to GitHub."""
    servers, sha = await github_read_json(FILE_SERVERS)
    servers[guild_id] = config
    success = await github_write_json(FILE_SERVERS, servers, sha, f"Update config for guild {guild_id}")
    
    if success:
        _server_config_cache[guild_id] = config
    return success

async def ensure_server_config(guild_id: str, guild_name: str) -> dict:
    """Ensure server has a config, create if not exists."""
    config = await get_server_config(guild_id)
    if config is None:
        config = get_default_server_config(guild_id, guild_name)
        await save_server_config(guild_id, config)
    return config

# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION CHECKS
# ══════════════════════════════════════════════════════════════════════════════

async def is_admin(interaction: discord.Interaction) -> bool:
    """Check if user is admin (by role or Discord permissions)."""
    if interaction.user.guild_permissions.administrator:
        return True
    
    config = await get_server_config(str(interaction.guild.id))
    if config:
        user_roles = {role.name for role in interaction.user.roles}
        admin_roles = set(config.get("permissions", {}).get("admin_roles", []))
        return bool(user_roles & admin_roles)
    return False

async def is_mod(interaction: discord.Interaction) -> bool:
    """Check if user is mod or admin."""
    if await is_admin(interaction):
        return True
    
    config = await get_server_config(str(interaction.guild.id))
    if config:
        user_roles = {role.name for role in interaction.user.roles}
        mod_roles = set(config.get("permissions", {}).get("mod_roles", []))
        return bool(user_roles & mod_roles)
    return False

def has_mod_permission():
    """Decorator for mod-level commands."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_mod(interaction):
            return True
        await interaction.response.send_message(
            "❌ You need **Moderator** or **Admin** permissions to use this command.",
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

def has_admin_permission():
    """Decorator for admin-level commands."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_admin(interaction):
            return True
        await interaction.response.send_message(
            "❌ You need **Admin** permissions to use this command.",
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

# ══════════════════════════════════════════════════════════════════════════════
# HEALTH SERVER
# ══════════════════════════════════════════════════════════════════════════════

async def health(request):
    return web.Response(text="✅ Bot is running!")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Health server running on port {PORT}")

# ══════════════════════════════════════════════════════════════════════════════
# DISCORD BOT SETUP
# ══════════════════════════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.bans = True
intents.guilds = True

_prefix_cache = {}

async def get_prefix(bot, message):
    if message.guild:
        config = await get_server_config(str(message.guild.id))
        if config:
            return config.get("prefix", "?")
    return "?"

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# ══════════════════════════════════════════════════════════════════════════════
# ANILIST HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_anilist(session: aiohttp.ClientSession, media_id: int, media_type: str):
    query = """
    query ($id: Int, $type: MediaType) {
      Media(id: $id, type: $type) {
        id
        title { romaji english native }
        coverImage { large }
        averageScore
        genres
        description
        episodes
        chapters
        volumes
        status
        season
        seasonYear
        format
        startDate { year month day }
        endDate { year month day }
      }
    }
    """
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": {"id": media_id, "type": media_type}},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("Media")

async def search_anilist(session: aiohttp.ClientSession, search: str, media_type: str, page: int = 1, per_page: int = 10):
    query = """
    query ($search: String, $type: MediaType, $page: Int, $perPage: Int) {
      Page(page: $page, perPage: $perPage) {
        pageInfo { total currentPage lastPage hasNextPage perPage }
        media(search: $search, type: $type, sort: POPULARITY_DESC) {
          id
          title { romaji english native }
          coverImage { large }
          averageScore
          genres
          episodes
          chapters
          status
          format
          seasonYear
        }
      }
    }
    """
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": {"search": search, "type": media_type, "page": page, "perPage": per_page}},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("Page")

async def get_anilist_user_stats(session: aiohttp.ClientSession, user_id: int):
    query = """
    query ($userId: Int) {
      User(id: $userId) {
        id
        name
        avatar { large }
        statistics {
          anime {
            count
            minutesWatched
            episodesWatched
            meanScore
          }
          manga {
            count
            chaptersRead
            volumesRead
            meanScore
          }
        }
      }
    }
    """
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": {"userId": user_id}},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("User")

async def get_seasonal_anime(session: aiohttp.ClientSession, season: str = None, year: int = None, page: int = 1):
    now = datetime.now()
    if season is None:
        seasons = ["WINTER", "SPRING", "SUMMER", "FALL"]
        month = now.month
        season = seasons[(month - 1) // 3]
    if year is None:
        year = now.year
    
    query = """
    query ($season: MediaSeason, $seasonYear: Int, $page: Int) {
      Page(page: $page, perPage: 25) {
        pageInfo { total currentPage lastPage hasNextPage }
        media(season: $season, seasonYear: $seasonYear, type: ANIME, sort: POPULARITY_DESC) {
          id
          title { romaji english native }
          coverImage { large }
          averageScore
          genres
          episodes
          status
          format
          studios(isMain: true) { nodes { name } }
        }
      }
    }
    """
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": {"season": season, "seasonYear": year, "page": page}},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("Page")

async def get_airing_schedule(session: aiohttp.ClientSession, media_id: int = None, airing_at_greater: int = None):
    query = """
    query ($mediaId: Int, $airingAt_greater: Int) {
      Page(page: 1, perPage: 10) {
        airingSchedules(mediaId: $mediaId, airingAt_greater: $airingAt_greater, sort: TIME) {
          id
          episode
          airingAt
          timeUntilAiring
          media {
            id
            title { romaji english }
            coverImage { large }
          }
        }
      }
    }
    """
    variables = {}
    if media_id:
        variables["mediaId"] = media_id
    if airing_at_greater:
        variables["airingAt_greater"] = airing_at_greater
    
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("Page")

async def get_character(session: aiohttp.ClientSession, search: str):
    query = """
    query ($search: String) {
      Character(search: $search) {
        id
        name { full native }
        image { large }
        description
        dateOfBirth { year month day }
        bloodType
        gender
        age
        media(page: 1, perPage: 5, sort: POPULARITY_DESC) {
          nodes {
            id
            title { romaji english }
            type
          }
        }
      }
    }
    """
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": {"search": search}},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("Character")

async def get_studio(session: aiohttp.ClientSession, search: str):
    query = """
    query ($search: String) {
      Studio(search: $search) {
        id
        name
        isAnimationStudio
        media(page: 1, perPage: 10, sort: POPULARITY_DESC) {
          nodes {
            id
            title { romaji english }
            coverImage { large }
            averageScore
            seasonYear
            format
          }
        }
      }
    }
    """
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": {"search": search}},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return None
        result = await r.json()
        return result.get("data", {}).get("Studio")

# ══════════════════════════════════════════════════════════════════════════════
# MODERATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def log_mod_action(guild_id: str, action: str, target_id: str, moderator_id: str, reason: str, extra: dict = None):
    """Log a moderation action to GitHub."""
    session = await get_session()
    logs, sha = await github_read_json(FILE_MODLOG)
        
    if guild_id not in logs:
        logs[guild_id] = []
        
    entry = {
        "action": action,
        "target_id": target_id,
        "moderator_id": moderator_id,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "extra": extra or {}
    }
    logs[guild_id].append(entry)
        
    await github_write_json(FILE_MODLOG, logs, sha, f"Log {action} for user {target_id}")

async def get_user_warnings(guild_id: str, user_id: str) -> List[dict]:
    """Get all active warnings for a user in a guild."""
    session = await get_session()
    warnings, _ = await github_read_json(FILE_WARNINGS)
    
    guild_warnings = warnings.get(guild_id, {})
    user_warnings = guild_warnings.get(user_id, [])
    
    # Filter out expired warnings
    config = await get_server_config(guild_id)
    expire_days = config.get("warnings", {}).get("expire_days", 30) if config else 30
    
    active_warnings = []
    now = datetime.utcnow()
    for w in user_warnings:
        warned_at = datetime.fromisoformat(w.get("timestamp", now.isoformat()))
        if (now - warned_at).days < expire_days:
            active_warnings.append(w)
    
    return active_warnings

async def add_warning(guild_id: str, user_id: str, moderator_id: str, reason: str) -> dict:
    """Add a warning to a user. Returns {count, threshold_reached}."""
    session = await get_session()
    warnings, sha = await github_read_json(FILE_WARNINGS)
        
    if guild_id not in warnings:
        warnings[guild_id] = {}
    if user_id not in warnings[guild_id]:
        warnings[guild_id][user_id] = []
        
    warning = {
        "reason": reason,
        "moderator_id": moderator_id,
        "timestamp": datetime.utcnow().isoformat()
    }
    warnings[guild_id][user_id].append(warning)
        
    await github_write_json(FILE_WARNINGS, warnings, sha, f"Add warning for user {user_id}")
    
    # Check threshold
    config = await get_server_config(guild_id)
    threshold = config.get("warnings", {}).get("threshold", 3) if config else 3
    active_count = len(await get_user_warnings(guild_id, user_id))
    
    return {
        "count": active_count,
        "threshold_reached": active_count >= threshold
    }

async def clear_warnings(guild_id: str, user_id: str) -> bool:
    """Clear all warnings for a user."""
    session = await get_session()
    warnings, sha = await github_read_json(FILE_WARNINGS)
        
    if guild_id in warnings and user_id in warnings[guild_id]:
        del warnings[guild_id][user_id]
        return await github_write_json(FILE_WARNINGS, warnings, sha, f"Clear warnings for user {user_id}")
    return False

async def get_muted_role(guild: discord.Guild) -> discord.Role:
    """Get or create muted role."""
    config = await get_server_config(str(guild.id))
    
    # Check if muted role exists in config
    if config and config.get("muted_role_id"):
        role = guild.get_role(config["muted_role_id"])
        if role:
            return role
    
    # Look for existing "Muted" role
    for role in guild.roles:
        if role.name.lower() == "muted":
            if config:
                config["muted_role_id"] = role.id
                await save_server_config(str(guild.id), config)
            return role
    
    # Create new muted role
    muted_role = await guild.create_role(
        name="Muted",
        reason="Auto-created muted role",
        color=discord.Color.dark_grey()
    )
    
    # Set permissions for all channels
    for channel in guild.channels:
        try:
            await channel.set_permissions(
                muted_role,
                send_messages=False,
                speak=False,
                add_reactions=False,
                stream=False
            )
        except:
            pass
    
    # Save to config
    if config:
        config["muted_role_id"] = muted_role.id
        await save_server_config(str(guild.id), config)
    
    return muted_role

async def mute_user(member: discord.Member, duration_minutes: int, reason: str, moderator_id: str) -> bool:
    """Mute a user for a duration."""
    try:
        muted_role = await get_muted_role(member.guild)
        await member.add_roles(muted_role, reason=reason)
        
        # Store mute info
        session = await get_session()
        mutes, sha = await github_read_json(FILE_MUTES)
            
        guild_id = str(member.guild.id)
        if guild_id not in mutes:
            mutes[guild_id] = {}
            
        mutes[guild_id][str(member.id)] = {
            "end_time": (datetime.utcnow() + timedelta(minutes=duration_minutes)).isoformat(),
            "reason": reason,
            "moderator_id": moderator_id
        }
            
        await github_write_json(FILE_MUTES, mutes, sha, f"Mute user {member.id}")
        
        await log_mod_action(str(member.guild.id), "mute", str(member.id), moderator_id, reason, {"duration": duration_minutes})
        return True
    except Exception as e:
        print(f"Error muting user: {e}")
        return False

async def unmute_user(member: discord.Member) -> bool:
    """Unmute a user."""
    try:
        muted_role = await get_muted_role(member.guild)
        await member.remove_roles(muted_role, reason="Mute expired or removed")
        
        # Remove from mutes file
        session = await get_session()
        mutes, sha = await github_read_json(FILE_MUTES)
            
        guild_id = str(member.guild.id)
        if guild_id in mutes and str(member.id) in mutes[guild_id]:
            del mutes[guild_id][str(member.id)]
            await github_write_json(FILE_MUTES, mutes, sha, f"Unmute user {member.id}")
        
        return True
    except Exception as e:
        print(f"Error unmuting user: {e}")
        return False

async def check_expired_mutes():
    """Check and remove expired mutes. Called periodically."""
    session = await get_session()
    mutes, _ = await github_read_json(FILE_MUTES)
    
    now = datetime.utcnow()
    
    for guild_id, guild_mutes in mutes.items():
        for user_id, mute_data in list(guild_mutes.items()):
            end_time = datetime.fromisoformat(mute_data.get("end_time", ""))
            if now >= end_time:
                try:
                    guild = bot.get_guild(int(guild_id))
                    if guild:
                        member = guild.get_member(int(user_id))
                        if member:
                            await unmute_user(member)
                except Exception as e:
                    print(f"Error removing expired mute: {e}")

async def delete_user_messages(guild: discord.Guild, user_id: int, hours: int = 24, log_channel: discord.TextChannel = None):
    """Delete all messages from a user in the last X hours."""
    deleted_count = 0
    failed_count = 0
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    for channel in guild.text_channels:
        try:
            # Try to purge messages from this user
            def check(msg):
                return msg.author.id == user_id and msg.created_at >= cutoff
            
            deleted = await channel.purge(limit=100, check=check, after=cutoff)
            deleted_count += len(deleted)
        except discord.Forbidden:
            failed_count += 1
        except discord.HTTPException as e:
            if e.code == 50034:  # Cannot delete messages older than 14 days via bulk
                # Try individual delete
                try:
                    async for msg in channel.history(limit=100, after=cutoff):
                        if msg.author.id == user_id:
                            try:
                                await msg.delete()
                                deleted_count += 1
                            except:
                                failed_count += 1
                except:
                    pass
        except Exception as e:
            print(f"Error deleting messages in {channel.name}: {e}")
    
    # Log the deletion summary
    if log_channel:
        embed = discord.Embed(
            title="🗑️ Message Deletion Summary",
            color=0xFF6B6B
        )
        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(name="Messages Deleted", value=str(deleted_count), inline=True)
        embed.add_field(name="Time Range", value=f"Last {hours} hours", inline=True)
        if failed_count > 0:
            embed.add_field(name="Failed Channels", value=str(failed_count), inline=True)
        embed.set_footer(text=f"Executed at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        await log_channel.send(embed=embed)
    
    return deleted_count, failed_count

# ══════════════════════════════════════════════════════════════════════════════
# HONEYPOT SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

async def handle_honeypot_trigger(message: discord.Message, config: dict):
    """Handle when someone triggers the honeypot."""
    guild = message.guild
    user = message.author
    honeypot_config = config.get("honeypot", {})
    
    # Delete the message immediately
    try:
        await message.delete()
    except:
        pass
    
    # Check whitelist
    user_roles = {role.name for role in user.roles}
    whitelist = set(honeypot_config.get("whitelist_roles", []))
    if user_roles & whitelist:
        return  # User is whitelisted
    
    # Check if user has manage_messages or admin (immune)
    if user.guild_permissions.manage_messages or user.guild_permissions.administrator:
        return
    
    # Log the incident
    log_channel_id = honeypot_config.get("log_channel")
    log_channel = guild.get_channel(int(log_channel_id)) if log_channel_id else None
    
    action = honeypot_config.get("action", "kick")
    delete_hours = honeypot_config.get("delete_hours", 24)
    dm_message = honeypot_config.get("dm_message", "You were caught in a honeypot trap.")
    
    # Log to honeypot_logs.json
    session = await get_session()
    logs, sha = await github_read_json(FILE_HONEYPOT)
        
    guild_id = str(guild.id)
    if guild_id not in logs:
        logs[guild_id] = []
        
    logs[guild_id].append({
        "user_id": str(user.id),
        "user_name": user.display_name,
        "channel_id": str(message.channel.id),
        "message_content": message.content[:500],
        "action_taken": action,
        "timestamp": datetime.utcnow().isoformat()
    })
        
    await github_write_json(FILE_HONEYPOT, logs, sha, f"Honeypot triggered by {user.id}")
    
    # DM the user
    try:
        await user.send(f"⚠️ **{dm_message}**\n\n**Server:** {guild.name}\n**Action:** {action.upper()}")
    except:
        pass
    
    # Delete user's messages
    deleted_count, _ = await delete_user_messages(guild, user.id, delete_hours, log_channel)
    
    # Take action
    action_taken = "No action"
    try:
        if action == "kick":
            await guild.kick(user, reason="Honeypot triggered")
            action_taken = "Kicked"
        elif action == "ban":
            await guild.ban(user, reason="Honeypot triggered", delete_message_days=1)
            action_taken = "Banned"
        elif action == "mute":
            await mute_user(user, 1440, "Honeypot triggered", str(guild.owner_id))  # 24h mute
            action_taken = "Muted (24h)"
    except Exception as e:
        action_taken = f"Failed: {str(e)}"
    
    # Log to channel
    if log_channel:
        embed = discord.Embed(
            title="🍯 Honeypot Triggered!",
            color=0xFF0000
        )
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Action", value=action_taken, inline=True)
        embed.add_field(name="Messages Deleted", value=str(deleted_count), inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Message Content", value=f"```{message.content[:200]}```" if message.content else "No content", inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        await log_channel.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-MODERATION
# ══════════════════════════════════════════════════════════════════════════════

# Spam tracking
_spam_tracker: Dict[str, List[float]] = {}

async def check_automod(message: discord.Message, config: dict) -> bool:
    """Check message against automod rules. Returns True if message was deleted/action taken."""
    if message.author.bot:
        return False
    
    if message.author.guild_permissions.manage_messages:
        return False
    
    automod_config = config.get("automod", {})
    if not automod_config.get("enabled", True):
        return False
    
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    
    # Spam check
    spam_config = automod_config.get("spam", {})
    if spam_config.get("enabled", True):
        now = datetime.utcnow().timestamp()
        key = f"{guild_id}:{user_id}"
        
        if key not in _spam_tracker:
            _spam_tracker[key] = []
        
        _spam_tracker[key].append(now)
        # Remove old entries
        _spam_tracker[key] = [t for t in _spam_tracker[key] if now - t < spam_config.get("seconds", 3)]
        
        if len(_spam_tracker[key]) > spam_config.get("max_messages", 5):
            # Spam detected!
            await message.delete()
            action = spam_config.get("action", "mute")
            if action == "mute":
                await mute_user(message.author, spam_config.get("mute_duration", 10), "Spam detected", str(message.guild.owner_id))
            await message.channel.send(f"⚠️ {message.author.mention}, slow down! You're sending messages too fast.", delete_after=5)
            return True
    
    # Invite check
    invites_config = automod_config.get("invites", {})
    if invites_config.get("enabled", True):
        invite_pattern = r"(discord\.(?:gg|io|me|li|com)/[\w-]+|discordapp\.com/invite/[\w-]+)"
        if re.search(invite_pattern, message.content, re.IGNORECASE):
            # Check whitelist
            whitelist = invites_config.get("whitelist", [])
            if not any(inv in message.content for inv in whitelist):
                await message.delete()
                if invites_config.get("delete", True):
                    await message.channel.send(f"⚠️ {message.author.mention}, invite links are not allowed!", delete_after=5)
                return True
    
    # Links check
    links_config = automod_config.get("links", {})
    if links_config.get("enabled", True):
        url_pattern = r"https?://[^\s]+"
        if re.search(url_pattern, message.content, re.IGNORECASE):
            whitelist = links_config.get("whitelist", [])
            if whitelist and not any(link in message.content for link in whitelist):
                if links_config.get("delete", True):
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention}, links are not allowed!", delete_after=5)
                return True
    
    # Caps check
    caps_config = automod_config.get("caps", {})
    if caps_config.get("enabled", True):
        content = message.content
        if len(content) >= caps_config.get("min_length", 10):
            upper_count = sum(1 for c in content if c.isupper())
            alpha_count = sum(1 for c in content if c.isalpha())
            if alpha_count > 0 and (upper_count / alpha_count * 100) >= caps_config.get("threshold", 70):
                if caps_config.get("action") == "delete":
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention}, please don't use excessive caps!", delete_after=5)
                return True
    
    # Mass mention check
    mention_config = automod_config.get("mass_mention", {})
    if mention_config.get("enabled", True):
        mention_count = len(message.mentions) + len(message.role_mentions)
        if mention_count > mention_config.get("max_mentions", 5):
            await message.delete()
            if mention_config.get("action") == "mute":
                await mute_user(message.author, mention_config.get("mute_duration", 30), "Mass mention", str(message.guild.owner_id))
            await message.channel.send(f"⚠️ {message.author.mention}, mass mentions are not allowed!", delete_after=5)
            return True
    
    return False

# ══════════════════════════════════════════════════════════════════════════════
# SNIPE SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

_snipe_cache: Dict[str, dict] = {}

async def add_to_snipe(message: discord.Message, action: str):
    """Add a deleted message to snipe cache."""
    channel_id = str(message.channel.id)
    _snipe_cache[channel_id] = {
        "content": message.content,
        "author_id": str(message.author.id),
        "author_name": message.author.display_name,
        "author_avatar": str(message.author.display_avatar.url),
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "attachments": [a.url for a in message.attachments]
    }
    
    # Also save to GitHub for persistence
    session = await get_session()
    snipes, sha = await github_read_json(FILE_SNIPE)
    guild_id = str(message.guild.id)
    if guild_id not in snipes:
        snipes[guild_id] = {}
    snipes[guild_id][channel_id] = _snipe_cache[channel_id]
    await github_write_json(FILE_SNIPE, snipes, sha, f"Update snipe cache for {channel_id}")

# ══════════════════════════════════════════════════════════════════════════════
# BOT EVENTS
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} — slash commands synced")
    await ensure_json_files()
    
    # Start background tasks
    bot.loop.create_task(check_mutes_loop())
    bot.loop.create_task(cleanup_spam_tracker())

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Create config for new servers."""
    await ensure_server_config(str(guild.id), guild.name)
    print(f"✅ Joined new guild: {guild.name} ({guild.id})")

@bot.event
async def on_guild_remove(guild: discord.Guild):
    """Handle leaving a guild."""
    print(f"❌ Left guild: {guild.name} ({guild.id})")

@bot.event
async def on_member_join(member: discord.Member):
    """Handle new member join."""
    config = await get_server_config(str(member.guild.id))
    if not config:
        return
    
    # Welcome message
    welcome_config = config.get("welcome", {})
    if welcome_config.get("enabled"):
        channel_id = welcome_config.get("channel_id")
        if channel_id:
            channel = member.guild.get_channel(int(channel_id))
            if channel:
                msg = welcome_config.get("message", "Welcome {user} to {server}!")
                msg = msg.replace("{user}", member.mention).replace("{server}", member.guild.name)
                try:
                    await channel.send(msg)
                except:
                    pass
    
    # Log join
    logging_config = config.get("logging", {})
    if logging_config.get("user_join"):
        log_channel_id = logging_config.get("modlog_channel")
        if log_channel_id:
            log_channel = member.guild.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(title="👤 Member Joined", color=0x2EA043)
                embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=False)
                embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M UTC"), inline=False)
                embed.set_thumbnail(url=member.display_avatar.url)
                await log_channel.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    """Handle member leave/kick."""
    config = await get_server_config(str(member.guild.id))
    if not config:
        return
    
    # Leave message
    leave_config = config.get("leave", {})
    if leave_config.get("enabled"):
        channel_id = leave_config.get("channel_id")
        if channel_id:
            channel = member.guild.get_channel(int(channel_id))
            if channel:
                msg = leave_config.get("message", "Goodbye {user}!")
                msg = msg.replace("{user}", member.display_name).replace("{server}", member.guild.name)
                try:
                    await channel.send(msg)
                except:
                    pass
    
    # Log leave
    logging_config = config.get("logging", {})
    if logging_config.get("user_leave"):
        log_channel_id = logging_config.get("modlog_channel")
        if log_channel_id:
            log_channel = member.guild.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(title="👋 Member Left", color=0xFF6B6B)
                embed.add_field(name="User", value=f"{member.display_name} (`{member.id}`)", inline=False)
                embed.set_thumbnail(url=member.display_avatar.url)
                await log_channel.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    """Handle messages."""
    if message.author.bot:
        return
    
    if not message.guild:
        return
    
    config = await get_server_config(str(message.guild.id))
    if not config:
        config = await ensure_server_config(str(message.guild.id), message.guild.name)
    
    # Check honeypot
    honeypot_config = config.get("honeypot", {})
    if honeypot_config.get("enabled") and honeypot_config.get("channel_id"):
        if str(message.channel.id) == str(honeypot_config.get("channel_id")):
            await handle_honeypot_trigger(message, config)
            return
    
    # Check automod
    if await check_automod(message, config):
        return
    
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    """Handle message deletion."""
    if message.author.bot:
        return
    
    if not message.guild:
        return
    
    # Add to snipe cache
    await add_to_snipe(message, "deleted")
    
    # Log deletion
    config = await get_server_config(str(message.guild.id))
    if config and config.get("logging", {}).get("message_delete"):
        log_channel_id = config.get("logging", {}).get("modlog_channel")
        if log_channel_id:
            log_channel = message.guild.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(title="🗑️ Message Deleted", color=0xFF6B6B)
                embed.add_field(name="Author", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                embed.add_field(name="Content", value=message.content[:500] or "No content", inline=False)
                if message.attachments:
                    embed.add_field(name="Attachments", value=str(len(message.attachments)), inline=True)
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await log_channel.send(embed=embed)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """Handle message edit."""
    if before.author.bot:
        return
    
    if before.content == after.content:
        return
    
    if not before.guild:
        return
    
    # Log edit
    config = await get_server_config(str(before.guild.id))
    if config and config.get("logging", {}).get("message_edit"):
        log_channel_id = config.get("logging", {}).get("modlog_channel")
        if log_channel_id:
            log_channel = before.guild.get_channel(int(log_channel_id))
            if log_channel:
                embed = discord.Embed(title="✏️ Message Edited", color=0xFFA500)
                embed.add_field(name="Author", value=f"{before.author.mention} (`{before.author.id}`)", inline=False)
                embed.add_field(name="Channel", value=before.channel.mention, inline=True)
                embed.add_field(name="Before", value=before.content[:500] or "No content", inline=False)
                embed.add_field(name="After", value=after.content[:500] or "No content", inline=False)
                embed.set_thumbnail(url=before.author.display_avatar.url)
                await log_channel.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ══════════════════════════════════════════════════════════════════════════════

async def check_mutes_loop():
    """Check for expired mutes every minute."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_expired_mutes()
        except Exception as e:
            print(f"Error in mute check loop: {e}")
        await asyncio.sleep(60)

async def cleanup_spam_tracker():
    """Clean up old spam tracker entries every 5 minutes."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            now = datetime.utcnow().timestamp()
            for key in list(_spam_tracker.keys()):
                _spam_tracker[key] = [t for t in _spam_tracker[key] if now - t < 60]
                if not _spam_tracker[key]:
                    del _spam_tracker[key]
        except Exception as e:
            print(f"Error in spam tracker cleanup: {e}")
        await asyncio.sleep(300)

# ══════════════════════════════════════════════════════════════════════════════
# HELPER: Ensure JSON files exist
# ══════════════════════════════════════════════════════════════════════════════

async def ensure_json_files():
    """Auto-create all required JSON files on GitHub if they don't exist."""
    global _prefix_cache
    files = {
        FILE_USERS: {},
        FILE_TIMEZONES: {},
        FILE_ANIME: [],
        FILE_MANGA: [],
        FILE_PREFIXES: DEFAULT_PREFIXES[:],
        FILE_SERVERS: {},
        FILE_WARNINGS: {},
        FILE_MUTES: {},
        FILE_MODLOG: {},
        FILE_HONEYPOT: {},
        FILE_SNIPE: {},
    }
    for filepath, default in files.items():
        data, sha = await github_read_json(filepath)
        if sha is None:
            await github_write_json(filepath, default, None, f"init: create {filepath}")
            print(f"✅ Created {filepath} on GitHub")
        else:
            print(f"✅ {filepath} already exists")
    # Load prefixes into cache
    prefixes, _ = await github_read_json(FILE_PREFIXES)
    _prefix_cache = prefixes if isinstance(prefixes, list) and prefixes else DEFAULT_PREFIXES[:]
    print(f"✅ Active prefixes: {_prefix_cache}")

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - SERVER SETUP
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="server_setup", description="Initialize bot for this server")
@has_admin_permission()
async def server_setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    embed = discord.Embed(title="✅ Server Setup Complete!", color=0x2EA043)
    embed.add_field(name="Prefix", value=f"`{config['prefix']}`", inline=True)
    embed.add_field(name="Honeypot", value="Disabled", inline=True)
    embed.add_field(name="Auto-mod", value="Enabled", inline=True)
    embed.set_footer(text="Use /server_config to customize settings")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="server_config", description="View or modify server configuration")
@app_commands.describe(setting="Setting to view/modify", value="New value")
@has_admin_permission()
async def server_config(interaction: discord.Interaction, setting: str = None, value: str = None):
    await interaction.response.defer(ephemeral=True)
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    if setting is None:
        # Show current config
        embed = discord.Embed(title="⚙️ Server Configuration", color=0x0078D4)
        embed.add_field(name="Prefix", value=f"`{config['prefix']}`", inline=True)
        
        # Honeypot status
        hp = config.get("honeypot", {})
        hp_status = "✅ Enabled" if hp.get("enabled") else "❌ Disabled"
        embed.add_field(name="Honeypot", value=hp_status, inline=True)
        
        # Automod status
        am = config.get("automod", {})
        am_status = "✅ Enabled" if am.get("enabled") else "❌ Disabled"
        embed.add_field(name="Auto-mod", value=am_status, inline=True)
        
        # Warning config
        wc = config.get("warnings", {})
        embed.add_field(name="Warning Threshold", value=str(wc.get("threshold", 3)), inline=True)
        embed.add_field(name="Warning Action", value=wc.get("action", "mute").capitalize(), inline=True)
        
        # Logging
        lc = config.get("logging", {})
        log_channel = lc.get("modlog_channel")
        embed.add_field(name="Log Channel", value=f"<#{log_channel}>" if log_channel else "Not set", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        # Modify setting
        setting = setting.lower()
        
        if setting == "prefix":
            if value is None:
                await interaction.followup.send("Usage: `/server_config setting:prefix value:?`", ephemeral=True)
                return
            config["prefix"] = value
            await save_server_config(str(interaction.guild.id), config)
            await interaction.followup.send(f"✅ Prefix changed to `{value}`", ephemeral=True)
        
        elif setting == "log_channel":
            if value is None:
                await interaction.followup.send("Usage: `/server_config setting:log_channel value:#channel`", ephemeral=True)
                return
            # Extract channel ID from mention
            channel_id = value.strip("<#>")
            if not channel_id.isdigit():
                await interaction.followup.send("❌ Please mention a valid channel", ephemeral=True)
                return
            config["logging"]["modlog_channel"] = channel_id
            await save_server_config(str(interaction.guild.id), config)
            await interaction.followup.send(f"✅ Log channel set to <#{channel_id}>", ephemeral=True)
        
        else:
            await interaction.followup.send(f"❌ Unknown setting: `{setting}`\nAvailable: prefix, log_channel", ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - HONEYPOT
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="honeypot", description="Configure the honeypot trap system")
@app_commands.describe(
    action="Action to take (kick/ban/mute)",
    channel="Channel to set as honeypot",
    delete_hours="Hours of messages to delete (1-168)",
    whitelist_role="Role to whitelist (immune to honeypot)",
    log_channel="Channel to log honeypot triggers",
    dm_message="Custom DM message to send",
    enable="Enable/disable honeypot",
    test="Test honeypot (no real punishment)"
)
@has_admin_permission()
async def honeypot(
    interaction: discord.Interaction,
    action: str = None,
    channel: discord.TextChannel = None,
    delete_hours: int = None,
    whitelist_role: discord.Role = None,
    log_channel: discord.TextChannel = None,
    dm_message: str = None,
    enable: bool = None,
    test: bool = None
):
    await interaction.response.defer(ephemeral=True)
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    hp_config = config.get("honeypot", {})
    
    if action:
        if action.lower() in ("kick", "ban", "mute"):
            hp_config["action"] = action.lower()
        else:
            await interaction.followup.send("❌ Action must be: kick, ban, or mute", ephemeral=True)
            return
    
    if channel:
        hp_config["channel_id"] = str(channel.id)
        hp_config["enabled"] = True
    
    if delete_hours:
        if 1 <= delete_hours <= 168:
            hp_config["delete_hours"] = delete_hours
        else:
            await interaction.followup.send("❌ Delete hours must be between 1 and 168", ephemeral=True)
            return
    
    if whitelist_role:
        whitelist = hp_config.get("whitelist_roles", [])
        if whitelist_role.name not in whitelist:
            whitelist.append(whitelist_role.name)
        hp_config["whitelist_roles"] = whitelist
    
    if log_channel:
        hp_config["log_channel"] = str(log_channel.id)
    
    if dm_message:
        hp_config["dm_message"] = dm_message
    
    if enable is not None:
        hp_config["enabled"] = enable
    
    config["honeypot"] = hp_config
    await save_server_config(str(interaction.guild.id), config)
    
    # Show current config
    embed = discord.Embed(title="🍯 Honeypot Configuration", color=0xFFA500)
    embed.add_field(name="Enabled", value="✅ Yes" if hp_config.get("enabled") else "❌ No", inline=True)
    embed.add_field(name="Action", value=hp_config.get("action", "kick").upper(), inline=True)
    embed.add_field(name="Delete Hours", value=str(hp_config.get("delete_hours", 24)), inline=True)
    
    channel_id = hp_config.get("channel_id")
    embed.add_field(name="Channel", value=f"<#{channel_id}>" if channel_id else "Not set", inline=True)
    
    log_ch = hp_config.get("log_channel")
    embed.add_field(name="Log Channel", value=f"<#{log_ch}>" if log_ch else "Not set", inline=True)
    
    whitelist = hp_config.get("whitelist_roles", [])
    embed.add_field(name="Whitelist Roles", value=", ".join(whitelist) if whitelist else "None", inline=False)
    
    if test:
        embed.add_field(name="⚠️ TEST MODE", value="This was a test, no real changes made", inline=False)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="honeypot_disable", description="Disable the honeypot system")
@has_admin_permission()
async def honeypot_disable(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    config = await get_server_config(str(interaction.guild.id))
    if config:
        config["honeypot"]["enabled"] = False
        await save_server_config(str(interaction.guild.id), config)
    
    await interaction.followup.send("✅ Honeypot disabled", ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - WARNINGS
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="warn", description="Warn a user")
@app_commands.describe(user="User to warn", reason="Reason for warning")
@has_mod_permission()
async def warn_cmd(interaction: discord.Interaction, user: discord.Member, reason: str):
    await interaction.response.defer()
    
    result = await add_warning(str(interaction.guild.id), str(user.id), str(interaction.user.id), reason)
    
    embed = discord.Embed(title="⚠️ User Warned", color=0xFFA500)
    embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=str(result["count"]), inline=True)
    embed.add_field(name="Threshold", value="⚠️ REACHED!" if result["threshold_reached"] else "Not reached", inline=True)
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.followup.send(embed=embed)
    
    # Log
    await log_mod_action(str(interaction.guild.id), "warn", str(user.id), str(interaction.user.id), reason)
    
    # DM user
    try:
        await user.send(f"⚠️ You have been warned in **{interaction.guild.name}**\n**Reason:** {reason}\n**Total Warnings:** {result['count']}")
    except:
        pass
    
    # Take action if threshold reached
    if result["threshold_reached"]:
        config = await get_server_config(str(interaction.guild.id))
        wc = config.get("warnings", {})
        action = wc.get("action", "mute")
        
        if action == "mute":
            duration = wc.get("mute_duration", 24)
            await mute_user(user, duration * 60, f"Warning threshold reached ({result['count']} warnings)", str(interaction.user.id))
            await interaction.followup.send(f"🔇 {user.mention} has been muted for {duration} hours (warning threshold reached)")
        elif action == "kick":
            await interaction.guild.kick(user, reason=f"Warning threshold reached ({result['count']} warnings)")
            await interaction.followup.send(f"👢 {user.mention} has been kicked (warning threshold reached)")
        elif action == "ban":
            await interaction.guild.ban(user, reason=f"Warning threshold reached ({result['count']} warnings)")
            await interaction.followup.send(f"🔨 {user.mention} has been banned (warning threshold reached)")

@bot.tree.command(name="warnings", description="View warnings for a user")
@app_commands.describe(user="User to check")
@has_mod_permission()
async def warnings_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    user_warnings = await get_user_warnings(str(interaction.guild.id), str(user.id))
    
    embed = discord.Embed(title=f"⚠️ Warnings for {user.display_name}", color=0xFFA500)
    embed.set_thumbnail(url=user.display_avatar.url)
    
    if not user_warnings:
        embed.description = "No active warnings"
    else:
        for i, w in enumerate(user_warnings[-5:], 1):  # Show last 5
            timestamp = datetime.fromisoformat(w.get("timestamp", "")).strftime("%Y-%m-%d %H:%M")
            embed.add_field(
                name=f"#{i} - {timestamp}",
                value=f"**Reason:** {w.get('reason', 'No reason')}\n**By:** <@{w.get('moderator_id', 'Unknown')}>",
                inline=False
            )
    
    embed.set_footer(text=f"Total: {len(user_warnings)} warnings")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarnings", description="Clear all warnings for a user")
@app_commands.describe(user="User to clear warnings for")
@has_admin_permission()
async def clearwarnings_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    success = await clear_warnings(str(interaction.guild.id), str(user.id))
    
    if success:
        await interaction.followup.send(f"✅ Cleared all warnings for {user.mention}", ephemeral=True)
        await log_mod_action(str(interaction.guild.id), "clear_warnings", str(user.id), str(interaction.user.id), "Warnings cleared")
    else:
        await interaction.followup.send(f"❌ No warnings found for {user.mention}", ephemeral=True)

@bot.tree.command(name="warnconfig", description="Configure warning system")
@app_commands.describe(threshold="Warnings before action", action="Action to take (mute/kick/ban)", mute_duration="Mute duration in hours", expire_days="Days before warnings expire")
@has_admin_permission()
async def warnconfig_cmd(interaction: discord.Interaction, threshold: int = None, action: str = None, mute_duration: int = None, expire_days: int = None):
    await interaction.response.defer(ephemeral=True)
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    wc = config.get("warnings", {})
    
    if threshold:
        wc["threshold"] = threshold
    if action and action.lower() in ("mute", "kick", "ban"):
        wc["action"] = action.lower()
    if mute_duration:
        wc["mute_duration"] = mute_duration
    if expire_days:
        wc["expire_days"] = expire_days
    
    config["warnings"] = wc
    await save_server_config(str(interaction.guild.id), config)
    
    embed = discord.Embed(title="⚙️ Warning Configuration", color=0x0078D4)
    embed.add_field(name="Threshold", value=str(wc.get("threshold", 3)), inline=True)
    embed.add_field(name="Action", value=wc.get("action", "mute").capitalize(), inline=True)
    embed.add_field(name="Mute Duration", value=f"{wc.get('mute_duration', 24)} hours", inline=True)
    embed.add_field(name="Expire After", value=f"{wc.get('expire_days', 30)} days", inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - MUTE/BAN/KICK
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="mute", description="Mute a user")
@app_commands.describe(user="User to mute", duration="Duration in minutes", reason="Reason for mute")
@has_mod_permission()
async def mute_cmd(interaction: discord.Interaction, user: discord.Member, duration: int = 60, reason: str = "No reason provided"):
    await interaction.response.defer()
    
    if user.guild_permissions.administrator:
        await interaction.followup.send("❌ Cannot mute an administrator!", ephemeral=True)
        return
    
    success = await mute_user(user, duration, reason, str(interaction.user.id))
    
    if success:
        embed = discord.Embed(title="🔇 User Muted", color=0xFFA500)
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Duration", value=f"{duration} minutes", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)
        
        # DM user
        try:
            await user.send(f"🔇 You have been muted in **{interaction.guild.name}**\n**Duration:** {duration} minutes\n**Reason:** {reason}")
        except:
            pass
    else:
        await interaction.followup.send("❌ Failed to mute user", ephemeral=True)

@bot.tree.command(name="unmute", description="Unmute a user")
@app_commands.describe(user="User to unmute")
@has_mod_permission()
async def unmute_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    
    success = await unmute_user(user)
    
    if success:
        await interaction.followup.send(f"✅ {user.mention} has been unmuted")
        await log_mod_action(str(interaction.guild.id), "unmute", str(user.id), str(interaction.user.id), "Unmuted")
    else:
        await interaction.followup.send("❌ Failed to unmute user (may not be muted)", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a user")
@app_commands.describe(user="User to kick", reason="Reason for kick")
@has_mod_permission()
async def kick_cmd(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await interaction.response.defer()
    
    if user.guild_permissions.administrator:
        await interaction.followup.send("❌ Cannot kick an administrator!", ephemeral=True)
        return
    
    # DM user before kick
    try:
        await user.send(f"👢 You have been kicked from **{interaction.guild.name}**\n**Reason:** {reason}")
    except:
        pass
    
    try:
        await interaction.guild.kick(user, reason=reason)
        
        embed = discord.Embed(title="👢 User Kicked", color=0xFF6B6B)
        embed.add_field(name="User", value=f"{user.display_name} (`{user.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)
        await log_mod_action(str(interaction.guild.id), "kick", str(user.id), str(interaction.user.id), reason)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to kick user: {e}", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a user")
@app_commands.describe(user="User to ban", reason="Reason for ban", delete_days="Days of messages to delete (0-7)")
@has_admin_permission()
async def ban_cmd(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided", delete_days: int = 1):
    await interaction.response.defer()
    
    if user.guild_permissions.administrator:
        await interaction.followup.send("❌ Cannot ban an administrator!", ephemeral=True)
        return
    
    # DM user before ban
    try:
        await user.send(f"🔨 You have been banned from **{interaction.guild.name}**\n**Reason:** {reason}")
    except:
        pass
    
    try:
        await interaction.guild.ban(user, reason=reason, delete_message_days=delete_days)
        
        embed = discord.Embed(title="🔨 User Banned", color=0xFF0000)
        embed.add_field(name="User", value=f"{user.display_name} (`{user.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Messages Deleted", value=f"{delete_days} days", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)
        await log_mod_action(str(interaction.guild.id), "ban", str(user.id), str(interaction.user.id), reason, {"delete_days": delete_days})
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to ban user: {e}", ephemeral=True)

@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="User ID to unban")
@has_admin_permission()
async def unban_cmd(interaction: discord.Interaction, user_id: str):
    await interaction.response.defer()
    
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        
        await interaction.followup.send(f"✅ Unbanned {user.display_name} (`{user_id}`)")
        await log_mod_action(str(interaction.guild.id), "unban", user_id, str(interaction.user.id), "Unbanned")
    except discord.NotFound:
        await interaction.followup.send("❌ User not found in ban list", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unban: {e}", ephemeral=True)

@bot.tree.command(name="tempban", description="Temporarily ban a user")
@app_commands.describe(user="User to ban", hours="Duration in hours", reason="Reason for ban")
@has_admin_permission()
async def tempban_cmd(interaction: discord.Interaction, user: discord.Member, hours: int, reason: str = "No reason provided"):
    await interaction.response.defer()
    
    if user.guild_permissions.administrator:
        await interaction.followup.send("❌ Cannot ban an administrator!", ephemeral=True)
        return
    
    # DM user
    try:
        await user.send(f"🔨 You have been temporarily banned from **{interaction.guild.name}**\n**Duration:** {hours} hours\n**Reason:** {reason}")
    except:
        pass
    
    try:
        await interaction.guild.ban(user, reason=f"Tempban: {reason}", delete_message_days=1)
        
        # Store tempban in mutes file (reuse for tempbans)
        session = await get_session()
        mutes, sha = await github_read_json(FILE_MUTES)
            
        guild_id = str(interaction.guild.id)
        if guild_id not in mutes:
            mutes[guild_id] = {}
            
        mutes[guild_id][f"tempban_{user.id}"] = {
            "end_time": (datetime.utcnow() + timedelta(hours=hours)).isoformat(),
            "reason": reason,
            "moderator_id": str(interaction.user.id),
            "type": "tempban"
        }
            
        await github_write_json(FILE_MUTES, mutes, sha, f"Tempban user {user.id}")
        
        embed = discord.Embed(title="🔨 User Temporarily Banned", color=0xFF0000)
        embed.add_field(name="User", value=f"{user.display_name} (`{user.id}`)", inline=False)
        embed.add_field(name="Duration", value=f"{hours} hours", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)
        await log_mod_action(str(interaction.guild.id), "tempban", str(user.id), str(interaction.user.id), reason, {"hours": hours})
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to tempban: {e}", ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - AUTO-MOD
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="automod", description="Configure auto-moderation")
@app_commands.describe(
    filter_type="Filter to configure (spam/links/invites/caps/mass_mention)",
    enabled="Enable or disable this filter",
    max_value="Max value (for spam: messages, for caps: %, for mentions: count)",
    action="Action to take (delete/mute/kick)"
)
@has_admin_permission()
async def automod_cmd(interaction: discord.Interaction, filter_type: str, enabled: bool = None, max_value: int = None, action: str = None):
    await interaction.response.defer(ephemeral=True)
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    automod_config = config.get("automod", {})
    filter_type = filter_type.lower()
    
    if filter_type == "spam":
        fc = automod_config.get("spam", {})
        if enabled is not None:
            fc["enabled"] = enabled
        if max_value is not None:
            fc["max_messages"] = max_value
        if action:
            fc["action"] = action.lower()
        automod_config["spam"] = fc
    
    elif filter_type == "links":
        fc = automod_config.get("links", {})
        if enabled is not None:
            fc["enabled"] = enabled
        if action:
            fc["delete"] = action.lower() == "delete"
        automod_config["links"] = fc
    
    elif filter_type == "invites":
        fc = automod_config.get("invites", {})
        if enabled is not None:
            fc["enabled"] = enabled
        if action:
            fc["action"] = action.lower()
        automod_config["invites"] = fc
    
    elif filter_type == "caps":
        fc = automod_config.get("caps", {})
        if enabled is not None:
            fc["enabled"] = enabled
        if max_value is not None:
            fc["threshold"] = max_value
        automod_config["caps"] = fc
    
    elif filter_type == "mass_mention":
        fc = automod_config.get("mass_mention", {})
        if enabled is not None:
            fc["enabled"] = enabled
        if max_value is not None:
            fc["max_mentions"] = max_value
        if action:
            fc["action"] = action.lower()
        automod_config["mass_mention"] = fc
    
    elif filter_type == "all":
        if enabled is not None:
            automod_config["enabled"] = enabled
    
    else:
        await interaction.followup.send(f"❌ Unknown filter: `{filter_type}`\nAvailable: spam, links, invites, caps, mass_mention, all", ephemeral=True)
        return
    
    config["automod"] = automod_config
    await save_server_config(str(interaction.guild.id), config)
    
    embed = discord.Embed(title="🤖 Auto-Moderation Configuration", color=0x0078D4)
    embed.add_field(name="Global", value="✅ Enabled" if automod_config.get("enabled", True) else "❌ Disabled", inline=False)
    
    for fname, fc in automod_config.items():
        if fname == "enabled":
            continue
        status = "✅" if fc.get("enabled", True) else "❌"
        embed.add_field(name=f"{status} {fname.title()}", value=str(fc)[:100], inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="purge", description="Delete multiple messages")
@app_commands.describe(amount="Number of messages to delete (1-100)", user="Only delete messages from this user")
@has_mod_permission()
async def purge_cmd(interaction: discord.Interaction, amount: int, user: discord.Member = None):
    await interaction.response.defer(ephemeral=True)
    
    if amount < 1 or amount > 100:
        await interaction.followup.send("❌ Amount must be between 1 and 100", ephemeral=True)
        return
    
    def check(msg):
        if user:
            return msg.author.id == user.id
        return True
    
    try:
        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(f"✅ Deleted {len(deleted)} messages", ephemeral=True)
        await log_mod_action(str(interaction.guild.id), "purge", str(interaction.channel.id), str(interaction.user.id), f"Purged {len(deleted)} messages")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to purge: {e}", ephemeral=True)

@bot.tree.command(name="slowmode", description="Set slowmode for current channel")
@app_commands.describe(seconds="Seconds between messages (0 to disable)")
@has_mod_permission()
async def slowmode_cmd(interaction: discord.Interaction, seconds: int):
    await interaction.response.defer()
    
    try:
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.followup.send("✅ Slowmode disabled")
        else:
            await interaction.followup.send(f"✅ Slowmode set to {seconds} seconds")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to set slowmode: {e}", ephemeral=True)

@bot.tree.command(name="lockdown", description="Lock current channel")
@app_commands.describe(reason="Reason for lockdown")
@has_mod_permission()
async def lockdown_cmd(interaction: discord.Interaction, reason: str = "No reason provided"):
    await interaction.response.defer()
    
    try:
        # Get @everyone role
        everyone = interaction.guild.default_role
        await interaction.channel.set_permissions(everyone, send_messages=False, reason=reason)
        
        await interaction.followup.send(f"🔒 Channel locked: {reason}")
        await log_mod_action(str(interaction.guild.id), "lockdown", str(interaction.channel.id), str(interaction.user.id), reason)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to lockdown: {e}", ephemeral=True)

@bot.tree.command(name="unlock", description="Unlock current channel")
@has_mod_permission()
async def unlock_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    
    try:
        everyone = interaction.guild.default_role
        await interaction.channel.set_permissions(everyone, send_messages=None, reason="Channel unlocked")
        
        await interaction.followup.send("🔓 Channel unlocked")
        await log_mod_action(str(interaction.guild.id), "unlock", str(interaction.channel.id), str(interaction.user.id), "Channel unlocked")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unlock: {e}", ephemeral=True)

@bot.tree.command(name="snipe", description="Show last deleted message in this channel")
async def snipe_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    channel_id = str(interaction.channel.id)
    
    # Check cache
    if channel_id in _snipe_cache:
        snipe_data = _snipe_cache[channel_id]
    else:
        # Check GitHub
        session = await get_session()
        snipes, _ = await github_read_json(FILE_SNIPE)
        guild_id = str(interaction.guild.id)
        if guild_id in snipes and channel_id in snipes[guild_id]:
            snipe_data = snipes[guild_id][channel_id]
        else:
            snipe_data = None
    
    if not snipe_data:
        await interaction.followup.send("❌ No deleted messages to snipe", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎯 Sniped Message",
        description=snipe_data.get("content", "No content"),
        color=0xFF6B6B
    )
    embed.add_field(name="Author", value=f"<@{snipe_data.get('author_id')}>", inline=True)
    embed.add_field(name="Action", value=snipe_data.get("action", "deleted"), inline=True)
    
    timestamp = snipe_data.get("timestamp", "")
    if timestamp:
        embed.add_field(name="Time", value=datetime.fromisoformat(timestamp).strftime("%H:%M:%S"), inline=True)
    
    if snipe_data.get("attachments"):
        embed.add_field(name="Attachments", value=str(len(snipe_data["attachments"])), inline=True)
    
    embed.set_footer(text=f"Author: {snipe_data.get('author_name', 'Unknown')}")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="userinfo", description="Get information about a user")
@app_commands.describe(user="User to get info about")
async def userinfo_cmd(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()
    
    if user is None:
        user = interaction.user
    
    embed = discord.Embed(title=f"👤 {user.display_name}", color=user.color)
    embed.set_thumbnail(url=user.display_avatar.url)
    
    embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
    embed.add_field(name="Nickname", value=user.nick or "None", inline=True)
    embed.add_field(name="Bot", value="Yes" if user.bot else "No", inline=True)
    
    embed.add_field(name="Created", value=user.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="Joined", value=user.joined_at.strftime("%Y-%m-%d") if user.joined_at else "Unknown", inline=True)
    
    # Roles
    roles = [r.mention for r in user.roles[1:]]  # Skip @everyone
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles[:10]) or "None", inline=False)
    
    # Warnings
    warnings = await get_user_warnings(str(interaction.guild.id), str(user.id))
    embed.add_field(name="Warnings", value=str(len(warnings)), inline=True)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="serverinfo", description="Get information about this server")
async def serverinfo_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    
    guild = interaction.guild
    
    embed = discord.Embed(title=f"📊 {guild.name}", color=0x0078D4)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Text Channels", value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name="Voice Channels", value=str(len(guild.voice_channels)), inline=True)
    
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Emojis", value=str(len(guild.emojis)), inline=True)
    embed.add_field(name="Boost Level", value=str(guild.premium_tier), inline=True)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="modlog", description="View moderation log for a user")
@app_commands.describe(user="User to check", limit="Number of entries to show")
@has_mod_permission()
async def modlog_cmd(interaction: discord.Interaction, user: discord.Member = None, limit: int = 10):
    await interaction.response.defer(ephemeral=True)
    
    session = await get_session()
    logs, _ = await github_read_json(FILE_MODLOG)
    
    guild_id = str(interaction.guild.id)
    guild_logs = logs.get(guild_id, [])
    
    if user:
        guild_logs = [l for l in guild_logs if l.get("target_id") == str(user.id)]
    
    if not guild_logs:
        await interaction.followup.send("❌ No logs found", ephemeral=True)
        return
    
    embed = discord.Embed(title="📋 Moderation Log", color=0x0078D4)
    
    for entry in guild_logs[-limit:]:
        timestamp = datetime.fromisoformat(entry.get("timestamp", "")).strftime("%m/%d %H:%M")
        action = entry.get("action", "unknown")
        target_id = entry.get("target_id", "unknown")
        reason = entry.get("reason", "No reason")[:50]
        
        embed.add_field(
            name=f"{action.upper()} - {timestamp}",
            value=f"Target: <@{target_id}>\nReason: {reason}",
            inline=False
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - PERMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="addperm", description="Add a role to mod/admin permissions")
@app_commands.describe(role="Role to add", level="Permission level (mod/admin/trusted)")
@has_admin_permission()
async def addperm_cmd(interaction: discord.Interaction, role: discord.Role, level: str):
    await interaction.response.defer(ephemeral=True)
    
    level = level.lower()
    if level not in ("mod", "admin", "trusted"):
        await interaction.followup.send("❌ Level must be: mod, admin, or trusted", ephemeral=True)
        return
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    key = f"{level}_roles"
    if key not in config["permissions"]:
        config["permissions"][key] = []
    
    if role.name not in config["permissions"][key]:
        config["permissions"][key].append(role.name)
        await save_server_config(str(interaction.guild.id), config)
    
    await interaction.followup.send(f"✅ Added **{role.name}** to **{level}** permissions", ephemeral=True)

@bot.tree.command(name="removeperm", description="Remove a role from permissions")
@app_commands.describe(role="Role to remove", level="Permission level (mod/admin/trusted)")
@has_admin_permission()
async def removeperm_cmd(interaction: discord.Interaction, role: discord.Role, level: str):
    await interaction.response.defer(ephemeral=True)
    
    level = level.lower()
    if level not in ("mod", "admin", "trusted"):
        await interaction.followup.send("❌ Level must be: mod, admin, or trusted", ephemeral=True)
        return
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        await interaction.followup.send("❌ No config found", ephemeral=True)
        return
    
    key = f"{level}_roles"
    if role.name in config["permissions"].get(key, []):
        config["permissions"][key].remove(role.name)
        await save_server_config(str(interaction.guild.id), config)
    
    await interaction.followup.send(f"✅ Removed **{role.name}** from **{level}** permissions", ephemeral=True)

@bot.tree.command(name="listperms", description="List all permission roles")
async def listperms_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    config = await get_server_config(str(interaction.guild.id))
    if not config:
        config = await ensure_server_config(str(interaction.guild.id), interaction.guild.name)
    
    embed = discord.Embed(title="🔐 Permission Roles", color=0x0078D4)
    
    perms = config.get("permissions", {})
    embed.add_field(name="Admin Roles", value=", ".join(perms.get("admin_roles", [])) or "None", inline=False)
    embed.add_field(name="Mod Roles", value=", ".join(perms.get("mod_roles", [])) or "None", inline=False)
    embed.add_field(name="Trusted Roles", value=", ".join(perms.get("trusted_roles", [])) or "None", inline=False)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - ANILIST/MAL SEARCH
# ══════════════════════════════════════════════════════════════════════════════

async def anime_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not current:
        return []
    
    session = await get_session()
    result = await search_anilist(session, current, "ANIME", per_page=10)
    
    if not result:
        return []
    
    choices = []
    for media in result.get("media", []):
        title = media.get("title", {}).get("english") or media.get("title", {}).get("romaji", "Unknown")
        choices.append(app_commands.Choice(name=title[:100], value=str(media["id"])))
    
    return choices

async def manga_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not current:
        return []
    
    session = await get_session()
    result = await search_anilist(session, current, "MANGA", per_page=10)
    
    if not result:
        return []
    
    choices = []
    for media in result.get("media", []):
        title = media.get("title", {}).get("english") or media.get("title", {}).get("romaji", "Unknown")
        choices.append(app_commands.Choice(name=title[:100], value=str(media["id"])))
    
    return choices

@bot.tree.command(name="anime", description="Search for an anime")
@app_commands.describe(query="Anime title to search")
@app_commands.autocomplete(query=anime_autocomplete)
async def anime_search_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    session = await get_session()
    # Try as ID first, then search
    if query.isdigit():
        media = await fetch_anilist(session, int(query), "ANIME")
    else:
        result = await search_anilist(session, query, "ANIME", per_page=1)
        media = result.get("media", [None])[0] if result else None
    
    if not media:
        await interaction.followup.send("❌ Anime not found")
        return
    
    title = media.get("title", {}).get("english") or media.get("title", {}).get("romaji", "Unknown")
    
    embed = discord.Embed(title=f"📺 {title}", url=f"https://anilist.co/anime/{media['id']}", color=0x3DB4F2)
    
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    
    # Description (truncate)
    desc = media.get("description", "No description")
    if desc:
        desc = re.sub(r'<[^>]+>', '', desc)[:500]  # Remove HTML and truncate
    embed.description = desc
    
    embed.add_field(name="Format", value=media.get("format", "Unknown"), inline=True)
    embed.add_field(name="Episodes", value=media.get("episodes", "Unknown"), inline=True)
    embed.add_field(name="Status", value=media.get("status", "Unknown").replace("_", " "), inline=True)
    embed.add_field(name="Score", value=f"{media.get('averageScore', 'N/A')}/100" if media.get("averageScore") else "N/A", inline=True)
    embed.add_field(name="Season", value=f"{media.get('season', '')} {media.get('seasonYear', '')}".strip() or "Unknown", inline=True)
    embed.add_field(name="Genres", value=", ".join(media.get("genres", [])[:5]) or "N/A", inline=True)
    
    embed.set_footer(text=f"ID: {media['id']} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="manga", description="Search for a manga")
@app_commands.describe(query="Manga title to search")
@app_commands.autocomplete(query=manga_autocomplete)
async def manga_search_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    session = await get_session()
    if query.isdigit():
        media = await fetch_anilist(session, int(query), "MANGA")
    else:
        result = await search_anilist(session, query, "MANGA", per_page=1)
        media = result.get("media", [None])[0] if result else None
    
    if not media:
        await interaction.followup.send("❌ Manga not found")
        return
    
    title = media.get("title", {}).get("english") or media.get("title", {}).get("romaji", "Unknown")
    
    embed = discord.Embed(title=f"📖 {title}", url=f"https://anilist.co/manga/{media['id']}", color=0xE85D75)
    
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    
    desc = media.get("description", "No description")
    if desc:
        desc = re.sub(r'<[^>]+>', '', desc)[:500]
    embed.description = desc
    
    embed.add_field(name="Format", value=media.get("format", "Unknown"), inline=True)
    embed.add_field(name="Chapters", value=media.get("chapters", "Unknown"), inline=True)
    embed.add_field(name="Volumes", value=media.get("volumes", "Unknown"), inline=True)
    embed.add_field(name="Status", value=media.get("status", "Unknown").replace("_", " "), inline=True)
    embed.add_field(name="Score", value=f"{media.get('averageScore', 'N/A')}/100" if media.get("averageScore") else "N/A", inline=True)
    embed.add_field(name="Genres", value=", ".join(media.get("genres", [])[:5]) or "N/A", inline=True)
    
    embed.set_footer(text=f"ID: {media['id']} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="character", description="Search for a character")
@app_commands.describe(name="Character name to search")
async def character_search_cmd(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    
    session = await get_session()
    char = await get_character(session, name)
    
    if not char:
        await interaction.followup.send("❌ Character not found")
        return
    
    embed = discord.Embed(title=f"👤 {char.get('name', {}).get('full', 'Unknown')}", color=0xFFC0CB)
    
    if char.get("image", {}).get("large"):
        embed.set_thumbnail(url=char["image"]["large"])
    
    desc = char.get("description", "No description")
    if desc:
        desc = re.sub(r'<[^>]+>', '', desc)[:400]
    embed.description = desc
    
    if char.get("name", {}).get("native"):
        embed.add_field(name="Native", value=char["name"]["native"], inline=True)
    if char.get("gender"):
        embed.add_field(name="Gender", value=char["gender"], inline=True)
    if char.get("age"):
        embed.add_field(name="Age", value=char["age"], inline=True)
    
    # Media appearances
    media_list = char.get("media", {}).get("nodes", [])[:5]
    if media_list:
        media_names = []
        for m in media_list:
            mtitle = m.get("title", {}).get("english") or m.get("title", {}).get("romaji", "Unknown")
            media_names.append(f"{mtitle} ({m.get('type', 'Unknown')})")
        embed.add_field(name="Appearances", value="\n".join(media_names), inline=False)
    
    embed.set_footer(text=f"ID: {char.get('id')} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="studio", description="Search for a studio")
@app_commands.describe(name="Studio name to search")
async def studio_search_cmd(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    
    session = await get_session()
    studio = await get_studio(session, name)
    
    if not studio:
        await interaction.followup.send("❌ Studio not found")
        return
    
    embed = discord.Embed(title=f"🎬 {studio.get('name', 'Unknown')}", color=0x8B4513)
    
    media_list = studio.get("media", {}).get("nodes", [])[:10]
    if media_list:
        for m in media_list:
            mtitle = m.get("title", {}).get("english") or m.get("title", {}).get("romaji", "Unknown")
            score = f" ({m.get('averageScore')}⭐)" if m.get("averageScore") else ""
            year = f" [{m.get('seasonYear', '')}]" if m.get("seasonYear") else ""
            embed.add_field(name=mtitle, value=f"{m.get('format', '')}{year}{score}", inline=False)
    
    embed.set_footer(text=f"ID: {studio.get('id')} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="seasonal", description="Get seasonal anime")
@app_commands.describe(season="Season (winter/spring/summer/fall)", year="Year (e.g., 2024)")
async def seasonal_cmd(interaction: discord.Interaction, season: str = None, year: int = None):
    await interaction.response.defer()
    
    season = season.upper() if season else None
    if season and season not in ("WINTER", "SPRING", "SUMMER", "FALL"):
        await interaction.followup.send("❌ Season must be: winter, spring, summer, or fall")
        return
    
    session = await get_session()
    result = await get_seasonal_anime(session, season, year)
    
    if not result or not result.get("media"):
        await interaction.followup.send("❌ No anime found for this season")
        return
    
    # Get season info from first anime
    first = result["media"][0]
    season_name = f"{first.get('season', '').capitalize()} {first.get('seasonYear', '')}"
    
    embed = discord.Embed(title=f"🌸 Seasonal Anime: {season_name}", color=0xFF69B4)
    
    for i, anime in enumerate(result["media"][:10], 1):
        title = anime.get("title", {}).get("english") or anime.get("title", {}).get("romaji", "Unknown")
        score = f" ({anime.get('averageScore')}⭐)" if anime.get("averageScore") else ""
        eps = anime.get("episodes", "?")
        studios = anime.get("studios", {}).get("nodes", [])
        studio_name = studios[0].get("name", "") if studios else ""
        
        embed.add_field(
            name=f"{i}. {title}{score}",
            value=f"📺 {anime.get('format', '')} | 🎬 {eps} eps | {studio_name}",
            inline=False
        )
    
    embed.set_footer(text=f"Page 1 of {result.get('pageInfo', {}).get('lastPage', 1)} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="airing", description="Get airing schedule for an anime")
@app_commands.describe(anime_id="AniList anime ID")
async def airing_cmd(interaction: discord.Interaction, anime_id: int):
    await interaction.response.defer()
    
    session = await get_session()
    # Get anime info
    media = await fetch_anilist(session, anime_id, "ANIME")
    if not media:
        await interaction.followup.send("❌ Anime not found")
        return
        
    # Get airing schedule
    now = int(datetime.utcnow().timestamp())
    schedule = await get_airing_schedule(session, anime_id, now)
    
    title = media.get("title", {}).get("english") or media.get("title", {}).get("romaji", "Unknown")
    
    embed = discord.Embed(title=f"📅 Airing Schedule: {title}", color=0x3DB4F2)
    
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    
    airing_list = schedule.get("airingSchedules", []) if schedule else []
    
    if not airing_list:
        embed.description = "No upcoming episodes found"
    else:
        for ep in airing_list[:5]:
            episode = ep.get("episode", "?")
            time_until = ep.get("timeUntilAiring", 0)
            
            days = time_until // 86400
            hours = (time_until % 86400) // 3600
            minutes = (time_until % 3600) // 60
            
            if days > 0:
                time_str = f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                time_str = f"{hours}h {minutes}m"
            else:
                time_str = f"{minutes}m"
            
            embed.add_field(name=f"Episode {episode}", value=f"⏰ {time_str}", inline=True)
    
    embed.set_footer(text=f"ID: {anime_id} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="random_anime", description="Get a random anime recommendation")
@app_commands.describe(genre="Genre filter (optional)")
async def random_anime_cmd(interaction: discord.Interaction, genre: str = None):
    await interaction.response.defer()
    
    # Random search query to get variety
    import random
    queries = ["a", "the", "of", "to", "and", "in", "is", "it"]
    query = random.choice(queries)
    
    page = random.randint(1, 50)
    
    session = await get_session()
    result = await search_anilist(session, query, "ANIME", page=page, per_page=1)
    
    if not result or not result.get("media"):
        await interaction.followup.send("❌ Couldn't fetch random anime")
        return
    
    media = random.choice(result["media"])
    title = media.get("title", {}).get("english") or media.get("title", {}).get("romaji", "Unknown")
    
    embed = discord.Embed(title=f"🎲 Random Anime: {title}", url=f"https://anilist.co/anime/{media['id']}", color=0x3DB4F2)
    
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    
    embed.add_field(name="Format", value=media.get("format", "Unknown"), inline=True)
    embed.add_field(name="Episodes", value=media.get("episodes", "Unknown"), inline=True)
    embed.add_field(name="Score", value=f"{media.get('averageScore', 'N/A')}/100" if media.get("averageScore") else "N/A", inline=True)
    embed.add_field(name="Genres", value=", ".join(media.get("genres", [])[:5]) or "N/A", inline=True)
    embed.add_field(name="Year", value=str(media.get("seasonYear", "Unknown")), inline=True)
    
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - USER PROFILE (EXISTING)
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="setup", description="Link your AniList and MAL accounts to your Discord")
@app_commands.describe(
    anilist_user_id="Your AniList user ID",
    mal_user_id="Your MyAnimeList user ID",
    author_name="Display name for list entries (defaults to Discord username)",
)
async def setup(interaction: discord.Interaction, anilist_user_id: int, mal_user_id: int, author_name: str = ""):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    author_display = author_name or interaction.user.display_name

    session = await get_session()
    users, sha = await github_read_json(FILE_USERS)

    users[discord_id] = {
        "anilist_user_id": anilist_user_id,
        "mal_user_id": mal_user_id,
        "author_name": author_display,
    }

    ok = await github_write_json(FILE_USERS, users, sha, f"Setup profile for {interaction.user.display_name}")

    if ok:
        embed = discord.Embed(title="✅ Profile Saved!", color=0x2EA043)
        embed.add_field(name="AniList ID", value=f"`{anilist_user_id}`", inline=True)
        embed.add_field(name="MAL ID", value=f"`{mal_user_id}`", inline=True)
        embed.add_field(name="Author Name", value=author_display, inline=True)
    else:
        embed = discord.Embed(title="❌ Failed to save profile", color=0xDA3633)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="myprofile", description="View your saved profile")
async def myprofile(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    session = await get_session()
    users, _ = await github_read_json(FILE_USERS)

    profile = users.get(str(interaction.user.id))
    if not profile:
        await interaction.followup.send("❌ No profile found. Run `/setup` first!", ephemeral=True)
        return

    embed = discord.Embed(title="👤 Your Profile", color=0x0078D4)
    embed.add_field(name="Author Name", value=profile.get("author_name", "—"), inline=True)
    embed.add_field(name="AniList UserID", value=f"`{profile['anilist_user_id']}`", inline=True)
    embed.add_field(name="MAL UserID", value=f"`{profile['mal_user_id']}`", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="anilist_stats", description="View AniList user statistics")
@app_commands.describe(user_id="AniList user ID")
async def anilist_stats_cmd(interaction: discord.Interaction, user_id: int):
    await interaction.response.defer()
    
    session = await get_session()
    user = await get_anilist_user_stats(session, user_id)
    
    if not user:
        await interaction.followup.send("❌ User not found on AniList")
        return
    
    embed = discord.Embed(title=f"📊 {user.get('name', 'Unknown')}", url=f"https://anilist.co/user/{user_id}", color=0x3DB4F2)
    
    if user.get("avatar", {}).get("large"):
        embed.set_thumbnail(url=user["avatar"]["large"])
    
    anime_stats = user.get("statistics", {}).get("anime", {})
    manga_stats = user.get("statistics", {}).get("manga", {})
    
    embed.add_field(name="📺 Anime Watched", value=str(anime_stats.get("count", 0)), inline=True)
    embed.add_field(name="🎬 Episodes", value=str(anime_stats.get("episodesWatched", 0)), inline=True)
    embed.add_field(name="⏱️ Minutes Watched", value=str(anime_stats.get("minutesWatched", 0)), inline=True)
    
    embed.add_field(name="📖 Manga Read", value=str(manga_stats.get("count", 0)), inline=True)
    embed.add_field(name="📄 Chapters", value=str(manga_stats.get("chaptersRead", 0)), inline=True)
    embed.add_field(name="📚 Volumes", value=str(manga_stats.get("volumesRead", 0)), inline=True)
    
    anime_mean = anime_stats.get("meanScore")
    manga_mean = manga_stats.get("meanScore")
    embed.add_field(name="⭐ Anime Mean Score", value=str(anime_mean) if anime_mean else "N/A", inline=True)
    embed.add_field(name="⭐ Manga Mean Score", value=str(manga_mean) if manga_mean else "N/A", inline=True)
    
    embed.set_footer(text=f"ID: {user_id} | Powered by AniList")
    
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - TIMEZONE (EXISTING)
# ══════════════════════════════════════════════════════════════════════════════

async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not current:
        choices = [
            app_commands.Choice(
                name=f"{TIMEZONES[tz]['code']} ({TIMEZONES[tz]['utc']}) - {TIMEZONES[tz]['name']}",
                value=tz
            )
            for tz in sorted(TIMEZONES.keys())[:25]
        ]
    else:
        current_upper = current.upper()
        matching = [tz for tz in TIMEZONES.keys() if current_upper in tz or current_upper in TIMEZONES[tz]['name'].upper()]
        choices = [
            app_commands.Choice(
                name=f"{TIMEZONES[tz]['code']} ({TIMEZONES[tz]['utc']}) - {TIMEZONES[tz]['name']}",
                value=tz
            )
            for tz in sorted(matching)[:25]
        ]
    return choices

@bot.tree.command(name="set_timezone", description="Set your timezone")
@app_commands.describe(timezone="Your timezone code (autocomplete available)")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def set_timezone(interaction: discord.Interaction, timezone: str):
    await interaction.response.defer(ephemeral=True)
    
    tz_upper = timezone.upper()
    if tz_upper not in TIMEZONES:
        await interaction.followup.send(embed=discord.Embed(title="❌ Invalid Timezone", description=f"Timezone `{tz_upper}` not found.", color=0xDA3633), ephemeral=True)
        return
    
    discord_id = str(interaction.user.id)
    session = await get_session()
    timezones, sha = await github_read_json(FILE_TIMEZONES)
    tz_info = TIMEZONES[tz_upper]
    timezones[discord_id] = {"code": tz_info["code"], "name": tz_info["name"], "offset": tz_info["offset"], "utc": tz_info["utc"]}
    success = await github_write_json(FILE_TIMEZONES, timezones, sha, f"Set timezone for {interaction.user.display_name}")
    
    if success:
        embed = discord.Embed(title="✅ Timezone Set!", description=f"**{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}", color=0x2EA043)
    else:
        embed = discord.Embed(title="❌ Failed to save timezone", color=0xDA3633)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="my_time", description="Check your current time")
async def my_time(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    session = await get_session()
    timezones, _ = await github_read_json(FILE_TIMEZONES)
    
    if discord_id not in timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ Timezone Not Set", description="Use `/set_timezone` first.", color=0xDA3633), ephemeral=True)
        return
    
    tz_data = timezones[discord_id]
    offset = tz_data["offset"]
    
    utc_now = datetime.utcnow()
    your_time = utc_now + timedelta(hours=offset)
    time_12 = your_time.strftime("%I:%M %p")
    
    embed = discord.Embed(title="🕐 Your Time", description=f"**{time_12}**", color=0x0066FF)
    embed.add_field(name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True)
    embed.add_field(name="Full Name", value=tz_data['name'], inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS - GITHUB BUILD (EXISTING)
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM_CHOICES = [
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="android", value="android"),
    app_commands.Choice(name="linux", value="linux"),
    app_commands.Choice(name="windows", value="windows"),
    app_commands.Choice(name="macos", value="macos"),
    app_commands.Choice(name="ios", value="ios"),
]

BUILD_TYPE_CHOICES = [
    app_commands.Choice(name="alpha", value="alpha"),
    app_commands.Choice(name="stable", value="stable"),
]

@bot.tree.command(name="build", description="Trigger the AnymeX-Preview build workflow")
@app_commands.describe(platforms="Platforms to build", build_type="Build type", pr_numbers="PR numbers (comma-separated)", tag_override="Version tag override")
@app_commands.choices(platforms=PLATFORM_CHOICES, build_type=BUILD_TYPE_CHOICES)
@has_mod_permission()
async def build(interaction: discord.Interaction, platforms: app_commands.Choice[str], build_type: app_commands.Choice[str], pr_numbers: str = "", tag_override: str = ""):
    await interaction.response.defer()

    discord_user_id = str(interaction.user.id)

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "platforms": platforms.value,
            "build_type": build_type.value,
            "pr_numbers": pr_numbers,
            "tag_override": tag_override,
            "triggered_by": discord_user_id,
        }
    }

    session = await get_session()
    async with session.post(
        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
        headers=gh_headers(), json=payload,
    ) as r:
        status = r.status
        body = await r.text()

    if status == 204:
        embed = discord.Embed(title="Build Triggered!", color=0x2EA043)
        embed.add_field(name="Repo", value=f"`{GITHUB_OWNER}/{GITHUB_REPO}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="Build Type", value=f"`{build_type.value}`", inline=True)
        embed.add_field(name="Platforms", value=f"`{platforms.value}`", inline=True)
        embed.add_field(name="View Run", value=f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)", inline=False)
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
    else:
        embed = discord.Embed(title="❌ Failed to Trigger Build", description=f"**Status:** `{status}`\n```{body[:500]}```", color=0xDA3633)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="create_tag", description="Create a new Git tag on the beta branch")
@app_commands.describe(tag="Tag name (e.g. v3.0.4-alpha)", message="Tag message")
@has_admin_permission()
async def create_tag(interaction: discord.Interaction, tag: str, message: str):
    await interaction.response.defer()

    session = await get_session()
    async with session.get(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}", headers=gh_headers()) as r:
        status = r.status
        ref_data = await r.json()
        
    if status != 200:
        await interaction.followup.send(embed=discord.Embed(title="❌ Branch not found", description=ref_data.get("message"), color=0xDA3633))
        return

    sha = ref_data["object"]["sha"]
    async with session.post(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/tags", headers=gh_headers(), json={"tag": tag, "message": message, "object": sha, "type": "commit"}) as r:
        status = r.status
        tag_data = await r.json()
        
    if status not in (200, 201):
        await interaction.followup.send(embed=discord.Embed(title="❌ Tag creation failed", description=tag_data.get("message"), color=0xDA3633))
        return

    async with session.post(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs", headers=gh_headers(), json={"ref": f"refs/tags/{tag}", "sha": tag_data["sha"]}) as r:
        status = r.status
        ref_result = await r.json()

    if status in (200, 201):
        embed = discord.Embed(title="🏷️ Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        embed.add_field(name="Message", value=message, inline=False)
    else:
        embed = discord.Embed(title="❌ Ref creation failed", description=ref_result.get("message"), color=0xDA3633)
    
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    await start_health_server()
    await bot.start(DISCORD_TOKEN)

async def shutdown():
    """Graceful shutdown."""
    print("Shutting down...")
    await close_session()
    await bot.close()

def signal_handler(sig, frame):
    """Handle shutdown signals."""
    print(f"Received signal {sig}")
    asyncio.create_task(shutdown())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    finally:
        asyncio.run(close_session())
