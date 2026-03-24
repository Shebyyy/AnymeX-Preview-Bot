import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
from aiohttp import web
import asyncio
import os
import base64
import json
import re
import threading

# ── Config ─────────────────────────────────────────────────────────────────────

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

# ── Proxy Config ───────────────────────────────────────────────────────────────
_PROXY_HOST = os.environ.get("PROXY_HOST")
_PROXY_PORT = os.environ.get("PROXY_PORT")
_PROXY_USER = os.environ.get("PROXY_USER")
_PROXY_PASS = os.environ.get("PROXY_PASS")
PROXY_URL = (
    f"http://{_PROXY_USER}:{_PROXY_PASS}@{_PROXY_HOST}:{_PROXY_PORT}"
    if all([_PROXY_HOST, _PROXY_PORT, _PROXY_USER, _PROXY_PASS])
    else None
)

GITHUB_OWNER = "Shebyyy"
GITHUB_REPO = "AnymeX-Preview"
GITHUB_BRANCH = "beta"
WORKFLOW_FILE = "beta_manual.yml"

GITHUB_API = "https://api.github.com"
ANILIST_API = "https://graphql.anilist.co"
MAL_API = "https://api.myanimelist.net/v2"

# ── GitHub JSON file paths ──────────────────────────────────────────────────────
FILE_ANIME = "underrated_anime.json"
FILE_MANGA = "underrated_manga.json"
FILE_USERS = "users.json"
FILE_TIMEZONES = "timezones.json"
FILE_PREFIXES = "prefixes.json"
FILE_SERVER_CFG = (
    "server_config.json"  # per-server config (roles, log channels, lang, etc.)
)
FILE_WARNINGS = "warnings.json"  # per-server user warnings
FILE_HONEYPOT = "honeypot.json"  # honeypot channel configs per server
FILE_AUTOMOD = "automod.json"  # per-server automod rules
FILE_REMINDERS = "reminders.json"  # pending reminders
FILE_MOD_CASES = "mod_cases.json"  # moderation case log

DEFAULT_PREFIXES = ["?"]

# ── Default per-server config skeleton ─────────────────────────────────────────
DEFAULT_SERVER_CFG = {
    "prefix": "?",
    "language": "en",
    "mod_log_channel": None,
    "join_leave_channel": None,
    "allowed_roles": [],  # role IDs allowed to use restricted commands
    "admin_roles": [],  # role IDs treated as admins for bot
    "mute_role": None,
    "warn_thresholds": {"3": "mute", "5": "ban"},  # warnings -> action
    "warn_expiry_days": 30,  # 0 = never expire
}

# ── Default automod config ──────────────────────────────────────────────────────
DEFAULT_AUTOMOD = {
    "spam": {
        "enabled": False,
        "max_messages": 5,
        "interval_seconds": 5,
        "action": "mute",
    },
    "invite_links": {"enabled": False, "action": "delete"},
    "caps_filter": {"enabled": False, "threshold": 70, "action": "delete"},
    "mention_spam": {"enabled": False, "max_mentions": 5, "action": "mute"},
    "blacklist": {"enabled": False, "words": [], "action": "delete"},
    "url_filter": {"enabled": False, "whitelist": [], "action": "delete"},
}

# ── In-memory spam tracking (not persisted) ────────────────────────────────────
_spam_tracker: dict = {}  # guild_id -> user_id -> [timestamps]

# ── COMPLETE WORLD TIMEZONE DATABASE (NEW FORMAT ONLY) ────────────────────────
TIMEZONES = {
    # UTC−12:00
    "BIT": {
        "code": "BIT",
        "name": "Baker Island Time",
        "offset": -12.0,
        "utc": "UTC-12:00",
        "region": "Pacific",
        "iana": "Etc/GMT+12",
    },
    # UTC−11:00
    "SST": {
        "code": "SST",
        "name": "Samoa Standard Time",
        "offset": -11.0,
        "utc": "UTC-11:00",
        "region": "Pacific",
        "iana": "Pacific/Pago_Pago",
    },
    # UTC−10:00
    "HST": {
        "code": "HST",
        "name": "Hawaii-Aleutian Standard Time",
        "offset": -10.0,
        "utc": "UTC-10:00",
        "region": "Americas",
        "iana": "Pacific/Honolulu",
    },
    # UTC−09:00
    "AKST": {
        "code": "AKST",
        "name": "Alaska Standard Time",
        "offset": -9.0,
        "utc": "UTC-09:00",
        "region": "Americas",
        "iana": "America/Anchorage",
    },
    "AKDT": {
        "code": "AKDT",
        "name": "Alaska Daylight Time",
        "offset": -8.0,
        "utc": "UTC-08:00",
        "region": "Americas",
        "iana": "America/Anchorage",
    },
    # UTC−08:00
    "PST": {
        "code": "PST",
        "name": "Pacific Standard Time",
        "offset": -8.0,
        "utc": "UTC-08:00",
        "region": "Americas",
        "iana": "America/Los_Angeles",
    },
    "PDT": {
        "code": "PDT",
        "name": "Pacific Daylight Time",
        "offset": -7.0,
        "utc": "UTC-07:00",
        "region": "Americas",
        "iana": "America/Los_Angeles",
    },
    # UTC−07:00
    "MST": {
        "code": "MST",
        "name": "Mountain Standard Time",
        "offset": -7.0,
        "utc": "UTC-07:00",
        "region": "Americas",
        "iana": "America/Denver",
    },
    "MDT": {
        "code": "MDT",
        "name": "Mountain Daylight Time",
        "offset": -6.0,
        "utc": "UTC-06:00",
        "region": "Americas",
        "iana": "America/Denver",
    },
    # UTC−06:00
    "CST_US": {
        "code": "CST",
        "name": "Central Standard Time (US)",
        "offset": -6.0,
        "utc": "UTC-06:00",
        "region": "Americas",
        "iana": "America/Chicago",
    },
    "CDT": {
        "code": "CDT",
        "name": "Central Daylight Time",
        "offset": -5.0,
        "utc": "UTC-05:00",
        "region": "Americas",
        "iana": "America/Chicago",
    },
    # UTC−05:00
    "EST": {
        "code": "EST",
        "name": "Eastern Standard Time",
        "offset": -5.0,
        "utc": "UTC-05:00",
        "region": "Americas",
        "iana": "America/New_York",
    },
    "EDT": {
        "code": "EDT",
        "name": "Eastern Daylight Time",
        "offset": -4.0,
        "utc": "UTC-04:00",
        "region": "Americas",
        "iana": "America/New_York",
    },
    # UTC−04:00
    "AST": {
        "code": "AST",
        "name": "Atlantic Standard Time",
        "offset": -4.0,
        "utc": "UTC-04:00",
        "region": "Americas",
        "iana": "America/Halifax",
    },
    "ADT": {
        "code": "ADT",
        "name": "Atlantic Daylight Time",
        "offset": -3.0,
        "utc": "UTC-03:00",
        "region": "Americas",
        "iana": "America/Halifax",
    },
    # UTC−03:00
    "ART": {
        "code": "ART",
        "name": "Argentina Time",
        "offset": -3.0,
        "utc": "UTC-03:00",
        "region": "Americas",
        "iana": "America/Argentina/Buenos_Aires",
    },
    "BRT": {
        "code": "BRT",
        "name": "Brasilia Time",
        "offset": -3.0,
        "utc": "UTC-03:00",
        "region": "Americas",
        "iana": "America/Sao_Paulo",
    },
    # UTC−02:00
    "GMTSG": {
        "code": "GST",
        "name": "South Georgia Time",
        "offset": -2.0,
        "utc": "UTC-02:00",
        "region": "Atlantic",
        "iana": "Atlantic/South_Georgia",
    },
    # UTC−01:00
    "AZOT": {
        "code": "AZOT",
        "name": "Azores Time",
        "offset": -1.0,
        "utc": "UTC-01:00",
        "region": "Atlantic",
        "iana": "Atlantic/Azores",
    },
    # UTC±00:00
    "UTC": {
        "code": "UTC",
        "name": "Coordinated Universal Time",
        "offset": 0.0,
        "utc": "UTC±00:00",
        "region": "UTC",
        "iana": "UTC",
    },
    "GMT": {
        "code": "GMT",
        "name": "Greenwich Mean Time",
        "offset": 0.0,
        "utc": "UTC±00:00",
        "region": "Europe",
        "iana": "Europe/London",
    },
    "WET": {
        "code": "WET",
        "name": "Western European Time",
        "offset": 0.0,
        "utc": "UTC±00:00",
        "region": "Europe",
        "iana": "Europe/London",
    },
    # UTC+01:00
    "WAT": {
        "code": "WAT",
        "name": "West Africa Time",
        "offset": 1.0,
        "utc": "UTC+01:00",
        "region": "Africa",
        "iana": "Africa/Lagos",
    },
    "CET": {
        "code": "CET",
        "name": "Central European Time",
        "offset": 1.0,
        "utc": "UTC+01:00",
        "region": "Europe",
        "iana": "Europe/Paris",
    },
    "BST": {
        "code": "BST",
        "name": "British Summer Time",
        "offset": 1.0,
        "utc": "UTC+01:00",
        "region": "Europe",
        "iana": "Europe/London",
    },
    "IST_EU": {
        "code": "IST",
        "name": "Irish Standard Time",
        "offset": 1.0,
        "utc": "UTC+01:00",
        "region": "Europe",
        "iana": "Europe/Dublin",
    },
    # UTC+02:00
    "CEST": {
        "code": "CEST",
        "name": "Central European Summer Time",
        "offset": 2.0,
        "utc": "UTC+02:00",
        "region": "Europe",
        "iana": "Europe/Paris",
    },
    "CAT": {
        "code": "CAT",
        "name": "Central Africa Time",
        "offset": 2.0,
        "utc": "UTC+02:00",
        "region": "Africa",
        "iana": "Africa/Johannesburg",
    },
    "SAST": {
        "code": "SAST",
        "name": "South Africa Standard Time",
        "offset": 2.0,
        "utc": "UTC+02:00",
        "region": "Africa",
        "iana": "Africa/Johannesburg",
    },
    "EET": {
        "code": "EET",
        "name": "Eastern European Time",
        "offset": 2.0,
        "utc": "UTC+02:00",
        "region": "Europe",
        "iana": "Europe/Athens",
    },
    "EGT": {
        "code": "EGT",
        "name": "Egypt Standard Time",
        "offset": 2.0,
        "utc": "UTC+02:00",
        "region": "Africa",
        "iana": "Africa/Cairo",
    },
    # UTC+03:00
    "EAT": {
        "code": "EAT",
        "name": "East Africa Time",
        "offset": 3.0,
        "utc": "UTC+03:00",
        "region": "Africa",
        "iana": "Africa/Nairobi",
    },
    "MSK": {
        "code": "MSK",
        "name": "Moscow Standard Time",
        "offset": 3.0,
        "utc": "UTC+03:00",
        "region": "Europe",
        "iana": "Europe/Moscow",
    },
    "EEST": {
        "code": "EEST",
        "name": "Eastern European Summer Time",
        "offset": 3.0,
        "utc": "UTC+03:00",
        "region": "Europe",
        "iana": "Europe/Athens",
    },
    # UTC+04:00
    "GST": {
        "code": "GST",
        "name": "Gulf Standard Time",
        "offset": 4.0,
        "utc": "UTC+04:00",
        "region": "Asia",
        "iana": "Asia/Dubai",
    },
    # UTC+04:30
    "AFT": {
        "code": "AFT",
        "name": "Afghanistan Time",
        "offset": 4.5,
        "utc": "UTC+04:30",
        "region": "Asia",
        "iana": "Asia/Kabul",
    },
    # UTC+05:00
    "PKT": {
        "code": "PKT",
        "name": "Pakistan Standard Time",
        "offset": 5.0,
        "utc": "UTC+05:00",
        "region": "Asia",
        "iana": "Asia/Karachi",
    },
    # UTC+05:30
    "IST": {
        "code": "IST",
        "name": "Indian Standard Time",
        "offset": 5.5,
        "utc": "UTC+05:30",
        "region": "Asia",
        "iana": "Asia/Kolkata",
    },
    # UTC+05:45
    "NPT": {
        "code": "NPT",
        "name": "Nepal Time",
        "offset": 5.75,
        "utc": "UTC+05:45",
        "region": "Asia",
        "iana": "Asia/Kathmandu",
    },
    # UTC+06:00
    "BDT": {
        "code": "BDT",
        "name": "Bangladesh Standard Time",
        "offset": 6.0,
        "utc": "UTC+06:00",
        "region": "Asia",
        "iana": "Asia/Dhaka",
    },
    # UTC+06:30
    "MMT": {
        "code": "MMT",
        "name": "Myanmar Time",
        "offset": 6.5,
        "utc": "UTC+06:30",
        "region": "Asia",
        "iana": "Asia/Yangon",
    },
    # UTC+07:00
    "ICT": {
        "code": "ICT",
        "name": "Indochina Time",
        "offset": 7.0,
        "utc": "UTC+07:00",
        "region": "Asia",
        "iana": "Asia/Bangkok",
    },
    "WIB": {
        "code": "WIB",
        "name": "Western Indonesia Time",
        "offset": 7.0,
        "utc": "UTC+07:00",
        "region": "Asia",
        "iana": "Asia/Jakarta",
    },
    # UTC+08:00
    "CST": {
        "code": "CST",
        "name": "China Standard Time",
        "offset": 8.0,
        "utc": "UTC+08:00",
        "region": "Asia",
        "iana": "Asia/Shanghai",
    },
    "SGT": {
        "code": "SGT",
        "name": "Singapore Standard Time",
        "offset": 8.0,
        "utc": "UTC+08:00",
        "region": "Asia",
        "iana": "Asia/Singapore",
    },
    "MYT": {
        "code": "MYT",
        "name": "Malaysia Time",
        "offset": 8.0,
        "utc": "UTC+08:00",
        "region": "Asia",
        "iana": "Asia/Kuala_Lumpur",
    },
    "PHT": {
        "code": "PHT",
        "name": "Philippine Standard Time",
        "offset": 8.0,
        "utc": "UTC+08:00",
        "region": "Asia",
        "iana": "Asia/Manila",
    },
    "HKT": {
        "code": "HKT",
        "name": "Hong Kong Time",
        "offset": 8.0,
        "utc": "UTC+08:00",
        "region": "Asia",
        "iana": "Asia/Hong_Kong",
    },
    "AWST": {
        "code": "AWST",
        "name": "Australian Western Standard Time",
        "offset": 8.0,
        "utc": "UTC+08:00",
        "region": "Australia",
        "iana": "Australia/Perth",
    },
    # UTC+09:00
    "JST": {
        "code": "JST",
        "name": "Japan Standard Time",
        "offset": 9.0,
        "utc": "UTC+09:00",
        "region": "Asia",
        "iana": "Asia/Tokyo",
    },
    "KST": {
        "code": "KST",
        "name": "Korea Standard Time",
        "offset": 9.0,
        "utc": "UTC+09:00",
        "region": "Asia",
        "iana": "Asia/Seoul",
    },
    # UTC+09:30
    "ACST": {
        "code": "ACST",
        "name": "Australian Central Standard Time",
        "offset": 9.5,
        "utc": "UTC+09:30",
        "region": "Australia",
        "iana": "Australia/Adelaide",
    },
    "ACDT": {
        "code": "ACDT",
        "name": "Australian Central Daylight Time",
        "offset": 10.5,
        "utc": "UTC+10:30",
        "region": "Australia",
        "iana": "Australia/Adelaide",
    },
    # UTC+10:00
    "AEST": {
        "code": "AEST",
        "name": "Australian Eastern Standard Time",
        "offset": 10.0,
        "utc": "UTC+10:00",
        "region": "Australia",
        "iana": "Australia/Sydney",
    },
    "AEDT": {
        "code": "AEDT",
        "name": "Australian Eastern Daylight Time",
        "offset": 11.0,
        "utc": "UTC+11:00",
        "region": "Australia",
        "iana": "Australia/Sydney",
    },
    # UTC+10:30
    "LHST": {
        "code": "LHST",
        "name": "Lord Howe Standard Time",
        "offset": 10.5,
        "utc": "UTC+10:30",
        "region": "Australia",
        "iana": "Australia/Lord_Howe",
    },
    # UTC+11:00
    "SBT": {
        "code": "SBT",
        "name": "Solomon Islands Time",
        "offset": 11.0,
        "utc": "UTC+11:00",
        "region": "Pacific",
        "iana": "Pacific/Guadalcanal",
    },
    "NACT": {
        "code": "NACT",
        "name": "Norfolk Island Time",
        "offset": 11.0,
        "utc": "UTC+11:00",
        "region": "Pacific",
        "iana": "Pacific/Norfolk",
    },
    # UTC+12:00
    "NZST": {
        "code": "NZST",
        "name": "New Zealand Standard Time",
        "offset": 12.0,
        "utc": "UTC+12:00",
        "region": "Pacific",
        "iana": "Pacific/Auckland",
    },
    "FJT": {
        "code": "FJT",
        "name": "Fiji Time",
        "offset": 12.0,
        "utc": "UTC+12:00",
        "region": "Pacific",
        "iana": "Pacific/Fiji",
    },
    # UTC+12:45
    "CHAST": {
        "code": "CHAST",
        "name": "Chatham Islands Standard Time",
        "offset": 12.75,
        "utc": "UTC+12:45",
        "region": "Pacific",
        "iana": "Pacific/Chatham",
    },
    # UTC+13:00
    "NZDT": {
        "code": "NZDT",
        "name": "New Zealand Daylight Time",
        "offset": 13.0,
        "utc": "UTC+13:00",
        "region": "Pacific",
        "iana": "Pacific/Auckland",
    },
    "PHOT": {
        "code": "PHOT",
        "name": "Phoenix Islands Time",
        "offset": 13.0,
        "utc": "UTC+13:00",
        "region": "Pacific",
        "iana": "Pacific/Kiritimati",
    },
    # UTC+14:00
    "LINT": {
        "code": "LINT",
        "name": "Line Islands Time",
        "offset": 14.0,
        "utc": "UTC+14:00",
        "region": "Pacific",
        "iana": "Pacific/Kiritimati",
    },
}

# ── Permission Helpers ─────────────────────────────────────────────────────────


async def get_server_cfg(session, guild_id: str) -> dict:
    """Return per-server config, merging with defaults."""
    all_cfg, _ = await github_read_json(session, FILE_SERVER_CFG)
    cfg = all_cfg.get(guild_id, {})
    merged = {**DEFAULT_SERVER_CFG, **cfg}
    return merged


async def save_server_cfg(session, guild_id: str, cfg: dict) -> bool:
    all_cfg, sha = await github_read_json(session, FILE_SERVER_CFG)
    all_cfg[guild_id] = cfg
    result = await github_write_json(
        session, FILE_SERVER_CFG, all_cfg, sha, f"Update config for guild {guild_id}"
    )
    _invalidate_cache(guild_id)
    return result


def _user_has_allowed_role_sync(
    interaction: discord.Interaction, allowed_role_ids: list
) -> bool:
    if not allowed_role_ids:
        return interaction.user.guild_permissions.administrator
    user_role_ids = {role.id for role in interaction.user.roles}
    return bool(user_role_ids & set(allowed_role_ids))


def has_allowed_role():
    """Check if user has any of the configured allowed roles (from JSON config)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        guild_id = str(interaction.guild_id)
        async with aiohttp.ClientSession() as session:
            cfg = await get_server_cfg(session, guild_id)
        allowed = cfg.get("allowed_roles", [])
        if not allowed:
            await interaction.response.send_message(
                "❌ This command is restricted. Ask an admin to configure `/server_config`.",
                ephemeral=True,
            )
            return False
        user_role_ids = {role.id for role in interaction.user.roles}
        if user_role_ids & set(allowed):
            return True
        await interaction.response.send_message(
            "❌ You don't have a role allowed to use this command.", ephemeral=True
        )
        return False

    return app_commands.check(predicate)


def has_allowed_role_prefix():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        guild_id = str(ctx.guild.id)
        async with aiohttp.ClientSession() as session:
            cfg = await get_server_cfg(session, guild_id)
        allowed = cfg.get("allowed_roles", [])
        if not allowed:
            await ctx.send(
                "❌ This command is restricted. Ask an admin to configure the bot."
            )
            return False
        user_role_ids = {role.id for role in ctx.author.roles}
        if user_role_ids & set(allowed):
            return True
        await ctx.send("❌ You don't have a role allowed to use this command.")
        return False

    return commands.check(predicate)


# ── Health check server (keeps Render awake) ───────────────────────────────────


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


# ── Intents ────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True  # required for prefix commands
intents.members = True  # required for join/leave logging and member operations

# In-memory prefix cache (loaded on startup)
_prefix_cache = ["?"]


async def get_prefix(bot, message):
    return _prefix_cache


bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# ── GitHub helpers ─────────────────────────────────────────────────────────────


def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def github_read_json(session: aiohttp.ClientSession, filepath: str) -> tuple:
    """Read a JSON file from GitHub. Returns (parsed_data, sha)."""
    async with session.get(
        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}?ref={GITHUB_BRANCH}",
        headers=gh_headers(),
    ) as r:
        if r.status == 404:
            dict_files = (
                FILE_USERS,
                FILE_TIMEZONES,
                FILE_SERVER_CFG,
                FILE_WARNINGS,
                FILE_HONEYPOT,
                FILE_AUTOMOD,
                FILE_MOD_CASES,
            )
            list_files = (FILE_ANIME, FILE_MANGA, FILE_REMINDERS)
            if filepath in dict_files:
                default = {}
            elif filepath == FILE_PREFIXES:
                default = DEFAULT_PREFIXES[:]
            elif filepath in list_files:
                default = []
            else:
                default = {}
            return default, None
        data = await r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data["sha"]


async def github_write_json(
    session: aiohttp.ClientSession, filepath: str, data, sha, commit_msg: str
) -> bool:
    """Write/update a JSON file on GitHub. Returns True on success."""
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(
            json.dumps(data, indent=2, ensure_ascii=False).encode()
        ).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    async with session.put(
        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}",
        headers=gh_headers(),
        json=payload,
    ) as r:
        return r.status in (200, 201)


# ── AniList helper ─────────────────────────────────────────────────────────────


async def fetch_anilist(session: aiohttp.ClientSession, media_id: int, media_type: str):
    query = """
    query ($id: Int, $type: MediaType) {
      Media(id: $id, type: $type) {
        id
        title { romaji english native }
        coverImage { large }
        averageScore
        genres
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


# ── ID extractors ──────────────────────────────────────────────────────────────


def extract_anilist_id(url: str):
    m = re.search(r"anilist\.co/(?:anime|manga)/(\d+)", url)
    return int(m.group(1)) if m else None


def extract_mal_id(url: str):
    m = re.search(r"myanimelist\.net/(?:anime|manga)/(\d+)", url)
    return int(m.group(1)) if m else None


# ── User profile helper ────────────────────────────────────────────────────────


async def get_profile(discord_id: str):
    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
    return users.get(discord_id)


# ── on ready ───────────────────────────────────────────────────────────────────


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await ensure_json_files()
    if not process_reminders.is_running():
        process_reminders.start()
    # Sync slash commands once to avoid Cloudflare rate limiting on every restart
    if not getattr(bot, "_synced", False):
        try:
            await bot.tree.sync()
            bot._synced = True
            print("✅ Slash commands synced")
        except Exception as e:
            print(f"⚠️ Failed to sync slash commands: {e}")


async def ensure_json_files():
    """Auto-create all required JSON files on GitHub if they don't exist."""
    global _prefix_cache
    files = {
        FILE_USERS: {},
        FILE_TIMEZONES: {},
        FILE_ANIME: [],
        FILE_MANGA: [],
        FILE_PREFIXES: DEFAULT_PREFIXES[:],
        FILE_SERVER_CFG: {},
        FILE_WARNINGS: {},
        FILE_HONEYPOT: {},
        FILE_AUTOMOD: {},
        FILE_REMINDERS: [],
        FILE_MOD_CASES: {},
    }
    async with aiohttp.ClientSession() as session:
        for filepath, default in files.items():
            data, sha = await github_read_json(session, filepath)
            if sha is None:
                await github_write_json(
                    session, filepath, default, None, f"init: create {filepath}"
                )
                print(f"✅ Created {filepath} on GitHub")
            else:
                print(f"✅ {filepath} already exists")
        # Load prefixes into cache
        prefixes, _ = await github_read_json(session, FILE_PREFIXES)
        _prefix_cache[:] = (
            prefixes if isinstance(prefixes, list) and prefixes else DEFAULT_PREFIXES[:]
        )
    print(f"✅ Active prefixes: {_prefix_cache}")


# ══════════════════════════════════════════════════════════════════════════════
# /setup
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="setup", description="Link your AniList and MAL accounts to your Discord"
)
@app_commands.describe(
    anilist_user_id="Your AniList user ID",
    mal_user_id="Your MyAnimeList user ID",
    author_name="Display name for list entries (defaults to Discord username)",
)
async def setup(
    interaction: discord.Interaction,
    anilist_user_id: int,
    mal_user_id: int,
    author_name: str = "",
):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    author_display = author_name or interaction.user.display_name

    async with aiohttp.ClientSession() as session:
        users, sha = await github_read_json(session, FILE_USERS)

        users[discord_id] = {
            "anilist_user_id": anilist_user_id,
            "mal_user_id": mal_user_id,
            "author_name": author_display,
        }

        ok = await github_write_json(
            session,
            FILE_USERS,
            users,
            sha,
            f"Setup profile for {interaction.user.display_name}",
        )

    if ok:
        embed = discord.Embed(title="✅ Profile Saved!", color=0x2EA043)
        embed.add_field(name="AniList ID", value=f"`{anilist_user_id}`", inline=True)
        embed.add_field(name="MAL ID", value=f"`{mal_user_id}`", inline=True)
        embed.add_field(name="Author Name", value=author_display, inline=True)
        embed.set_footer(text="You can now use /add_anime, /add_manga and /build!")
    else:
        embed = discord.Embed(title="❌ Failed to save profile", color=0xDA3633)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /myprofile
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="myprofile", description="View your saved profile")
async def myprofile(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)

    profile = users.get(str(interaction.user.id))
    if not profile:
        await interaction.followup.send(
            "❌ No profile found. Run `/setup` first!", ephemeral=True
        )
        return

    embed = discord.Embed(title="👤 Your Profile", color=0x0078D4)
    embed.add_field(name="Author Name", value=profile.get("author", "—"), inline=True)
    embed.add_field(
        name="GitHub", value=f"`{profile.get('github_username', '—')}`", inline=True
    )
    embed.add_field(
        name="AniList UserID", value=f"`{profile['anilist_user_id']}`", inline=True
    )
    embed.add_field(name="MAL UserID", value=f"`{profile['mal_user_id']}`", inline=True)
    embed.set_footer(text="Use /setup to update your profile.")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Confirm/Cancel view
# ══════════════════════════════════════════════════════════════════════════════


class ConfirmView(discord.ui.View):
    def __init__(self, entry: dict, filepath: str, media_type: str, cover_url: str):
        super().__init__(timeout=120)
        self.entry = entry
        self.filepath = filepath
        self.media_type = media_type
        self.cover_url = cover_url

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        self.stop()

        async with aiohttp.ClientSession() as session:
            entries, sha = await github_read_json(session, self.filepath)
            if any(e.get("anilist_id") == self.entry["anilist_id"] for e in entries):
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="⚠️ Already exists",
                        description=f"**{self.entry['title']}** is already in the list!",
                        color=0xFFA500,
                    )
                )
                return
            entries.append(self.entry)
            ok = await github_write_json(
                session,
                self.filepath,
                entries,
                sha,
                f"feat: add {self.entry['title']} to underrated {self.media_type}s by {self.entry['author']}",
            )

        if ok:
            embed = discord.Embed(
                title=f"🎉 Added to underrated_{self.media_type}s!", color=0x2EA043
            )
            embed.add_field(name="Title", value=self.entry["title"], inline=True)
            embed.add_field(name="Author", value=self.entry["author"], inline=True)
            embed.add_field(name="Reason", value=self.entry["reason"], inline=False)
            if self.cover_url:
                embed.set_thumbnail(url=self.cover_url)
        else:
            embed = discord.Embed(title="❌ Failed to commit to GitHub", color=0xDA3633)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("Cancelled.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Shared add logic
# ══════════════════════════════════════════════════════════════════════════════


async def handle_add(
    interaction,
    anilist_link,
    mal_link,
    reason,
    author_override,
    anilist_uid_override,
    mal_uid_override,
    media_type,
):
    await interaction.response.defer()

    anilist_id = extract_anilist_id(anilist_link)
    mal_id = extract_mal_id(mal_link)

    if not anilist_id:
        await interaction.followup.send(
            "❌ Invalid AniList link. Use `https://anilist.co/anime/387`",
            ephemeral=True,
        )
        return
    if not mal_id:
        await interaction.followup.send(
            "❌ Invalid MAL link. Use `https://myanimelist.net/anime/387`",
            ephemeral=True,
        )
        return

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
        profile = users.get(str(interaction.user.id))

        if not profile and (anilist_uid_override is None or mal_uid_override is None):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ Profile not set up",
                    description="Run `/setup` first, or pass `anilist_user_id` and `mal_user_id` manually.",
                    color=0xFFA500,
                ),
                ephemeral=True,
            )
            return

        anilist_user_id = anilist_uid_override or profile["anilist_user_id"]
        mal_user_id = mal_uid_override or profile["mal_user_id"]
        author = author_override or (
            profile["author"] if profile else interaction.user.display_name
        )
        media = await fetch_anilist(session, anilist_id, media_type)

    if not media:
        await interaction.followup.send(
            "❌ Could not fetch info from AniList.", ephemeral=True
        )
        return

    titles = media["title"]
    title = (
        titles.get("english")
        or titles.get("romaji")
        or titles.get("native")
        or "Unknown"
    )
    cover_url = media.get("coverImage", {}).get("large", "")
    score = media.get("averageScore") or "N/A"
    genres = ", ".join(media.get("genres", [])[:4]) or "N/A"

    entry = {
        "anilist_id": anilist_id,
        "mal_id": mal_id,
        "title": title,
        "anilist_user_id": anilist_user_id,
        "mal_user_id": mal_user_id,
        "author": author,
        "reason": reason,
    }

    filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"*Confirm to add to `{filepath}`*",
        color=0x0078D4,
    )
    preview.add_field(name="AniList ID", value=f"`{anilist_id}`", inline=True)
    preview.add_field(name="MAL ID", value=f"`{mal_id}`", inline=True)
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Genres", value=genres, inline=True)
    preview.add_field(name="AniList User ID", value=f"`{anilist_user_id}`", inline=True)
    preview.add_field(name="MAL User ID", value=f"`{mal_user_id}`", inline=True)
    preview.add_field(name="Author", value=author, inline=True)
    preview.add_field(name="Reason", value=reason, inline=False)
    if cover_url:
        preview.set_thumbnail(url=cover_url)
    preview.set_footer(text="You have 2 minutes to confirm.")

    view = ConfirmView(
        entry=entry,
        filepath=filepath,
        media_type=media_type.lower(),
        cover_url=cover_url,
    )
    await interaction.followup.send(embed=preview, view=view)


# ══════════════════════════════════════════════════════════════════════════════
# /add_anime
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_anime", description="Add an underrated anime to the list")
@app_commands.describe(
    anilist_link="AniList URL (e.g. https://anilist.co/anime/387)",
    mal_link="MAL URL (e.g. https://myanimelist.net/anime/387)",
    reason="Why is it underrated?",
    author="Override display name",
    anilist_user_id="Override your AniList user ID",
    mal_user_id="Override your MAL user ID",
)
async def add_anime(
    interaction: discord.Interaction,
    anilist_link: str,
    mal_link: str,
    reason: str,
    author: str = "",
    anilist_user_id: int = None,
    mal_user_id: int = None,
):
    await handle_add(
        interaction,
        anilist_link,
        mal_link,
        reason,
        author,
        anilist_user_id,
        mal_user_id,
        "ANIME",
    )


# ══════════════════════════════════════════════════════════════════════════════
# /add_manga
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_manga", description="Add an underrated manga to the list")
@app_commands.describe(
    anilist_link="AniList URL (e.g. https://anilist.co/manga/74489)",
    mal_link="MAL URL (e.g. https://myanimelist.net/manga/44489)",
    reason="Why is it underrated?",
    author="Override display name",
    anilist_user_id="Override your AniList user ID",
    mal_user_id="Override your MAL user ID",
)
async def add_manga(
    interaction: discord.Interaction,
    anilist_link: str,
    mal_link: str,
    reason: str,
    author: str = "",
    anilist_user_id: int = None,
    mal_user_id: int = None,
):
    await handle_add(
        interaction,
        anilist_link,
        mal_link,
        reason,
        author,
        anilist_user_id,
        mal_user_id,
        "MANGA",
    )


# ══════════════════════════════════════════════════════════════════════════════
# /list_anime — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_anime", description="View the underrated anime list")
@has_allowed_role()
async def list_anime(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_ANIME)

    if not entries:
        embed = discord.Embed(
            title="Anime List", description="No anime added yet.", color=0x0066FF
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0x0066FF,
        )
        embed.add_field(
            name="Author", value=entry.get("author", "Unknown"), inline=True
        )
        embed.add_field(
            name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True
        )
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_manga — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_manga", description="View the underrated manga list")
@has_allowed_role()
async def list_manga(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MANGA)

    if not entries:
        embed = discord.Embed(
            title="Manga List", description="No manga added yet.", color=0xFF6B6B
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0xFF6B6B,
        )
        embed.add_field(
            name="Author", value=entry.get("author", "Unknown"), inline=True
        )
        embed.add_field(
            name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True
        )
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /remove_anime — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_anime", description="Remove an anime from the list")
@app_commands.describe(search_term="Title or AniList ID")
@has_allowed_role()
async def remove_anime(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_ANIME)

    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit() and str(entry.get("anilist_id")) == search_term:
            found_index = i
            break
        elif search_term.lower() in entry.get("title", "").lower():
            found_index = i
            break

    if found_index is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No anime matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_ANIME, entries, sha, f"Remove anime: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(
            title="Removed", description=removed.get("title"), color=0x2EA043
        )
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /remove_manga — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_manga", description="Remove a manga from the list")
@app_commands.describe(search_term="Title or AniList ID")
@has_allowed_role()
async def remove_manga(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_MANGA)

    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit() and str(entry.get("anilist_id")) == search_term:
            found_index = i
            break
        elif search_term.lower() in entry.get("title", "").lower():
            found_index = i
            break

    if found_index is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No manga matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_MANGA, entries, sha, f"Remove manga: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(
            title="Removed", description=removed.get("title"), color=0x2EA043
        )
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /build
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM_CHOICES = [
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="android", value="android"),
    app_commands.Choice(name="linux", value="linux"),
    app_commands.Choice(name="windows", value="windows"),
    app_commands.Choice(name="macos", value="macos"),
    app_commands.Choice(name="ios", value="ios"),
    app_commands.Choice(name="android + linux + ios", value="android,linux,ios"),
    app_commands.Choice(name="android + ios", value="android,ios"),
    app_commands.Choice(name="android + windows", value="android,windows"),
    app_commands.Choice(name="android + linux", value="android,linux"),
    app_commands.Choice(name="android + macos", value="android,macos"),
    app_commands.Choice(name="linux + windows", value="linux,windows"),
    app_commands.Choice(name="linux + macos", value="linux,macos"),
    app_commands.Choice(name="windows + macos", value="windows,macos"),
    app_commands.Choice(name="ios + macos", value="ios,macos"),
]
BUILD_TYPE_CHOICES = [
    app_commands.Choice(name="alpha", value="alpha"),
    app_commands.Choice(name="stable", value="stable"),
]


@bot.tree.command(name="build", description="Trigger the AnymeX-Preview build workflow")
@app_commands.describe(
    platforms="Platforms to build",
    build_type="Build type",
    pr_numbers="PR numbers (comma-separated)",
    tag_override="Version tag override",
)
@app_commands.choices(platforms=PLATFORM_CHOICES, build_type=BUILD_TYPE_CHOICES)
@has_allowed_role()
async def build(
    interaction: discord.Interaction,
    platforms: app_commands.Choice[str],
    build_type: app_commands.Choice[str],
    pr_numbers: str = "",
    tag_override: str = "",
):
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
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
            headers=gh_headers(),
            json=payload,
        ) as r:
            status = r.status
            body = await r.text()

    if status == 204:
        embed = discord.Embed(title="Build Triggered!", color=0x2EA043)
        embed.add_field(
            name="Repo", value=f"`{GITHUB_OWNER}/{GITHUB_REPO}`", inline=True
        )
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="Build Type", value=f"`{build_type.value}`", inline=True)
        embed.add_field(name="Platforms", value=f"`{platforms.value}`", inline=True)
        if pr_numbers:
            embed.add_field(name="PRs", value=pr_numbers, inline=True)
        embed.add_field(
            name="Tag",
            value=f"`{tag_override}`" if tag_override else "Auto-detect",
            inline=True,
        )
        embed.add_field(
            name="View Run",
            value=f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)",
            inline=False,
        )
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        embed.description = "Build started - use button below to cancel if needed"

        # Fetch latest run to get run ID for cancel button
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=1&branch={GITHUB_BRANCH}",
                headers=gh_headers(),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("workflow_runs"):
                        run_id = data["workflow_runs"][0]["id"]

                        class CancelView(discord.ui.View):
                            def __init__(self, run_id):
                                super().__init__()
                                self.run_id = run_id

                            @discord.ui.button(
                                label="Cancel Build", style=discord.ButtonStyle.red
                            )
                            async def cancel_button(
                                self,
                                button_interaction: discord.Interaction,
                                button: discord.ui.Button,
                            ):
                                await button_interaction.response.defer()

                                async with aiohttp.ClientSession() as session:
                                    async with session.post(
                                        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{self.run_id}/cancel",
                                        headers=gh_headers(),
                                    ) as r:
                                        if r.status == 202:
                                            await button_interaction.followup.send(
                                                embed=discord.Embed(
                                                    title="✅ Build cancelled",
                                                    color=0x2EA043,
                                                ),
                                                ephemeral=True,
                                            )
                                        else:
                                            await button_interaction.followup.send(
                                                embed=discord.Embed(
                                                    title="❌ Failed to cancel build",
                                                    color=0xDA3633,
                                                ),
                                                ephemeral=True,
                                            )

                        await interaction.followup.send(
                            embed=embed, view=CancelView(run_id)
                        )
                        return

        # Fallback if we can't get run ID
        await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Failed to Trigger Build",
            description=f"**Status:** `{status}`\n```{body[:1000]}```",
            color=0xDA3633,
        )
        await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /create_tag
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="create_tag", description="Create a new Git tag on the beta branch"
)
@app_commands.describe(tag="Tag name (e.g. v3.0.4-alpha)", message="Tag message")
@has_allowed_role()
async def create_tag(interaction: discord.Interaction, tag: str, message: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            status = r.status
            ref_data = await r.json()
        if status != 200:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Branch not found",
                    description=ref_data.get("message"),
                    color=0xDA3633,
                )
            )
            return

        sha = ref_data["object"]["sha"]
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/tags",
            headers=gh_headers(),
            json={"tag": tag, "message": message, "object": sha, "type": "commit"},
        ) as r:
            status = r.status
            tag_data = await r.json()
        if status not in (200, 201):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Tag creation failed",
                    description=tag_data.get("message"),
                    color=0xDA3633,
                )
            )
            return

        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs",
            headers=gh_headers(),
            json={"ref": f"refs/tags/{tag}", "sha": tag_data["sha"]},
        ) as r:
            status = r.status
            ref_result = await r.json()

    if status in (200, 201):
        embed = discord.Embed(title="🏷️ Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        embed.add_field(name="Message", value=message, inline=False)
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
    else:
        embed = discord.Embed(
            title="❌ Ref creation failed",
            description=ref_result.get("message"),
            color=0xDA3633,
        )
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /delete_tag — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="delete_tag", description="Delete a Git tag and its release")
@app_commands.describe(tag="Tag name to delete")
@has_allowed_role()
async def delete_tag(interaction: discord.Interaction, tag: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs/tags/{tag}",
            headers=gh_headers(),
        ) as r:
            tag_status = r.status

        release_status = 404
        if tag_status in (200, 204):
            async with session.delete(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag}",
                headers=gh_headers(),
            ) as r:
                release_status = r.status

    if tag_status in (200, 204):
        embed = discord.Embed(title="Tag Deleted!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(
            name="Release",
            value="Deleted" if release_status in (200, 204) else "Not found",
            inline=True,
        )
    else:
        embed = discord.Embed(
            title="Failed to Delete",
            description=f"Tag `{tag}` not found",
            color=0xDA3633,
        )

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /latest_run — Restricted (only beta_manual.yml)
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="latest_run",
    description="Check the latest beta_manual.yml run and cancel if running",
)
@has_allowed_role()
async def latest_run(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/beta_manual.yml/runs?per_page=1&branch={GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            if r.status != 200:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Error fetching runs", color=0xDA3633)
                )
                return
            data = await r.json()

    if not data.get("workflow_runs"):
        await interaction.followup.send(
            embed=discord.Embed(title="❌ No runs found", color=0xDA3633)
        )
        return

    run = data["workflow_runs"][0]
    run_id = run["id"]
    conclusion = run.get("conclusion") or "in_progress"

    EMOJI_MAP = {
        "success": "✅",
        "failure": "❌",
        "cancelled": "🚫",
        "in_progress": "⏳",
    }
    emoji = EMOJI_MAP.get(conclusion, "❓")
    color = (
        0x2EA043
        if conclusion == "success"
        else (0xDA3633 if conclusion == "failure" else 0xFFA500)
    )

    embed = discord.Embed(title=f"{emoji} {run['name']}", color=color)
    embed.add_field(name="Status", value=f"`{conclusion}`", inline=True)
    embed.add_field(name="Branch", value=f"`{run['head_branch']}`", inline=True)
    embed.add_field(name="Run #", value=f"`{run['run_number']}`", inline=True)
    embed.add_field(name="Link", value=f"[View Run]({run['html_url']})", inline=False)

    # Add cancel button if still running
    if conclusion == "in_progress":
        embed.description = "Running - click button to cancel"
        embed.set_footer(text=f"Run ID: {run_id}")

        class CancelView(discord.ui.View):
            def __init__(self, run_id):
                super().__init__()
                self.run_id = run_id

            @discord.ui.button(label="Cancel Run", style=discord.ButtonStyle.red)
            async def cancel_button(
                self, button_interaction: discord.Interaction, button: discord.ui.Button
            ):
                await button_interaction.response.defer()

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{self.run_id}/cancel",
                        headers=gh_headers(),
                    ) as r:
                        if r.status == 202:
                            await button_interaction.followup.send(
                                embed=discord.Embed(
                                    title="✅ Run cancelled", color=0x2EA043
                                ),
                                ephemeral=True,
                            )
                        else:
                            await button_interaction.followup.send(
                                embed=discord.Embed(
                                    title="❌ Failed to cancel", color=0xDA3633
                                ),
                                ephemeral=True,
                            )

        await interaction.followup.send(embed=embed, view=CancelView(run_id))
    else:
        await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /build (add cancel button for running builds)

# ══════════════════════════════════════════════════════════════════════════════
# TIMEZONE AUTOCOMPLETE & HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


async def timezone_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for timezone selection - shows format: IST (UTC+05:30) - Indian Standard Time"""
    if not current:
        choices = [
            app_commands.Choice(
                name=f"{TIMEZONES[tz]['code']} ({TIMEZONES[tz]['utc']}) - {TIMEZONES[tz]['name']}",
                value=tz,
            )
            for tz in sorted(TIMEZONES.keys())[:25]
        ]
    else:
        current_upper = current.upper()
        matching = [
            tz
            for tz in TIMEZONES.keys()
            if current_upper in tz or current_upper in TIMEZONES[tz]["name"].upper()
        ]
        choices = [
            app_commands.Choice(
                name=f"{TIMEZONES[tz]['code']} ({TIMEZONES[tz]['utc']}) - {TIMEZONES[tz]['name']}",
                value=tz,
            )
            for tz in sorted(matching)[:25]
        ]
    return choices


# ══════════════════════════════════════════════════════════════════════════════
# /timezone_list
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="timezone_list", description="View all available timezones grouped by region"
)
async def timezone_list(interaction: discord.Interaction):
    await interaction.response.defer()

    regions = {}
    for tz, info in TIMEZONES.items():
        region = info["region"]
        if region not in regions:
            regions[region] = []
        regions[region].append(f"**{info['code']}** ({info['utc']}) - {info['name']}")

    embeds = []
    for region in sorted(regions.keys()):
        embed = discord.Embed(title=f"🌍 {region} Timezones", color=0x0066FF)
        embed.description = "\n".join(regions[region])
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds)


# ══════════════════════════════════════════════════════════════════════════════
# /set_timezone
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="set_timezone", description="Set your timezone")
@app_commands.describe(timezone="Your timezone code (autocomplete available)")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def set_timezone(interaction: discord.Interaction, timezone: str):
    await interaction.response.defer(ephemeral=True)

    tz_upper = timezone.upper()
    if tz_upper not in TIMEZONES:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Invalid Timezone",
                description=f"Timezone `{tz_upper}` not found.",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    discord_id = str(interaction.user.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        tz_info = TIMEZONES[tz_upper]
        timezones[discord_id] = {
            "code": tz_info["code"],
            "name": tz_info["name"],
            "offset": tz_info["offset"],
            "utc": tz_info["utc"],
        }
        success = await github_write_json(
            session,
            FILE_TIMEZONES,
            timezones,
            sha,
            f"Set timezone for {interaction.user.display_name}",
        )

    if success:
        embed = discord.Embed(
            title="✅ Timezone Set!",
            description=f"**{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}",
            color=0x2EA043,
        )
    else:
        embed = discord.Embed(title="❌ Failed to save timezone", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /my_time
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="my_time", description="Check your current time")
async def my_time(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if discord_id not in timezones:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Timezone Not Set",
                description="Use `/set_timezone` first.",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    tz_data = timezones[discord_id]
    offset = tz_data["offset"]

    from datetime import datetime, timedelta

    utc_now = datetime.utcnow()
    your_time = utc_now + timedelta(hours=offset)
    time_12 = your_time.strftime("%I:%M %p")

    embed = discord.Embed(
        title="🕐 Your Time", description=f"**{time_12}**", color=0x0066FF
    )
    embed.add_field(
        name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True
    )
    embed.add_field(name="Full Name", value=tz_data["name"], inline=True)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /add_friend_timezone
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_friend_timezone", description="Add a friend's timezone")
@app_commands.describe(user="Friend to add", timezone="Their timezone")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def add_friend_timezone(
    interaction: discord.Interaction, user: discord.User, timezone: str
):
    await interaction.response.defer(ephemeral=True)

    tz_upper = timezone.upper()
    if tz_upper not in TIMEZONES:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Invalid Timezone", color=0xDA3633),
            ephemeral=True,
        )
        return

    friend_id = str(user.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        tz_info = TIMEZONES[tz_upper]
        timezones[friend_id] = {
            "code": tz_info["code"],
            "name": tz_info["name"],
            "offset": tz_info["offset"],
            "utc": tz_info["utc"],
        }
        success = await github_write_json(
            session,
            FILE_TIMEZONES,
            timezones,
            sha,
            f"Add timezone for {user.display_name}",
        )

    if success:
        embed = discord.Embed(
            title="✅ Friend's Timezone Added!",
            description=f"**{user.mention}** → **{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}",
            color=0x2EA043,
        )
    else:
        embed = discord.Embed(title="❌ Failed to save", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /friend_time
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="friend_time", description="Check a friend's time")
@app_commands.describe(user="Friend to check")
async def friend_time(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)

    friend_id = str(user.id)
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if friend_id not in timezones:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Friend's Timezone Not Set", color=0xDA3633),
            ephemeral=True,
        )
        return

    tz_data = timezones[friend_id]
    offset = tz_data["offset"]

    from datetime import datetime, timedelta

    utc_now = datetime.utcnow()
    friend_time_calc = utc_now + timedelta(hours=offset)
    time_12 = friend_time_calc.strftime("%I:%M %p")

    embed = discord.Embed(
        title=f"🕐 {user.display_name}'s Time",
        description=f"**{time_12}**",
        color=0x0066FF,
    )
    embed.add_field(
        name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True
    )
    embed.add_field(name="Full Name", value=tz_data["name"], inline=True)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /list_friends
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="list_friends", description="Show all friends' timezones and current times"
)
async def list_friends(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if not timezones:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ No timezones set", color=0xDA3633)
        )
        return

    from datetime import datetime, timedelta

    utc_now = datetime.utcnow()
    embed = discord.Embed(title="🌍 Friends' Times", color=0x0066FF)

    for user_id, tz_data in sorted(timezones.items()):
        try:
            user = await interaction.client.fetch_user(int(user_id))
            user_name = user.display_name
        except:
            user_name = f"User {user_id}"

        offset = tz_data["offset"]
        user_time = utc_now + timedelta(hours=offset)
        time_12 = user_time.strftime("%I:%M %p")

        embed.add_field(
            name=f"👤 {user_name}",
            value=f"🕐 {time_12} ({tz_data['code']})",
            inline=False,
        )

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /remove_timezone
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_timezone", description="Remove your timezone")
async def remove_timezone(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)

        if discord_id not in timezones:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ No Timezone Set", color=0xDA3633),
                ephemeral=True,
            )
            return

        del timezones[discord_id]
        success = await github_write_json(
            session,
            FILE_TIMEZONES,
            timezones,
            sha,
            f"Remove timezone for {interaction.user.display_name}",
        )

    if success:
        embed = discord.Embed(title="✅ Timezone Removed!", color=0x2EA043)
    else:
        embed = discord.Embed(title="❌ Failed to remove timezone", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /friend_compare - Compare time difference
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="friend_compare", description="Compare time difference with a friend"
)
@app_commands.describe(user="Friend to compare with")
async def friend_compare(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)

    your_id = str(interaction.user.id)
    friend_id = str(user.id)

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if your_id not in timezones or friend_id not in timezones:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Timezone not set",
                description="Both users need timezone set",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    your_tz = timezones[your_id]
    friend_tz = timezones[friend_id]
    diff = friend_tz["offset"] - your_tz["offset"]
    sign = "+" if diff >= 0 else ""

    embed = discord.Embed(title="⏰ Time Difference", color=0x0066FF)
    embed.add_field(
        name="You", value=f"{your_tz['code']} ({your_tz['utc']})", inline=True
    )
    embed.add_field(
        name=f"{user.display_name}",
        value=f"{friend_tz['code']} ({friend_tz['utc']})",
        inline=True,
    )
    embed.add_field(name="Difference", value=f"{sign}{diff}h", inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /timezone_convert - Convert time between timezones
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="timezone_convert", description="Convert time between timezones")
@app_commands.describe(
    from_tz="Source timezone", to_tz="Target timezone", time="Time HH:MM (24-hour)"
)
@app_commands.autocomplete(from_tz=timezone_autocomplete)
@app_commands.autocomplete(to_tz=timezone_autocomplete)
async def timezone_convert(
    interaction: discord.Interaction, from_tz: str, to_tz: str, time: str
):
    await interaction.response.defer(ephemeral=True)

    from_upper = from_tz.upper()
    to_upper = to_tz.upper()

    if from_upper not in TIMEZONES or to_upper not in TIMEZONES:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Invalid timezone", color=0xDA3633),
            ephemeral=True,
        )
        return

    try:
        hour, minute = map(int, time.split(":"))
        from_data = TIMEZONES[from_upper]
        to_data = TIMEZONES[to_upper]

        offset_diff = to_data["offset"] - from_data["offset"]
        new_hour = (hour + int(offset_diff)) % 24

        embed = discord.Embed(title="🕐 Time Conversion", color=0x0066FF)
        embed.add_field(
            name=f"{from_data['code']}", value=f"{hour:02d}:{minute:02d}", inline=True
        )
        embed.add_field(
            name=f"{to_data['code']}", value=f"{new_hour:02d}:{minute:02d}", inline=True
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Error", description=str(e)[:100], color=0xDA3633
            ),
            ephemeral=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# /timezone_stats - Show timezone distribution
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="timezone_stats", description="Show team timezone distribution")
async def timezone_stats(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if not timezones:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ No timezones set", color=0xDA3633)
        )
        return

    tz_count = {}
    for tz_data in timezones.values():
        tz = tz_data["code"]
        tz_count[tz] = tz_count.get(tz, 0) + 1

    embed = discord.Embed(title="📊 Timezone Distribution", color=0x0066FF)
    for tz, count in sorted(tz_count.items(), key=lambda x: x[1], reverse=True):
        embed.add_field(name=tz, value=f"{count} member(s)", inline=True)

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /night_mode - Check if friend is sleeping (10 PM - 7 AM)
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="night_mode", description="Check if friend is sleeping (10 PM - 7 AM)"
)
@app_commands.describe(user="Friend to check")
async def night_mode(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)

    friend_id = str(user.id)
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if friend_id not in timezones:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Timezone not set", color=0xDA3633),
            ephemeral=True,
        )
        return

    from datetime import datetime, timedelta

    tz_data = timezones[friend_id]
    offset = tz_data["offset"]
    friend_time = datetime.utcnow() + timedelta(hours=offset)
    hour = friend_time.hour

    is_sleeping = hour < 7 or hour >= 22

    embed = discord.Embed(
        title=f"😴 {user.display_name}",
        description="🔴 SLEEPING" if is_sleeping else "🟢 AWAKE",
        color=0xDA3633 if is_sleeping else 0x2EA043,
    )
    embed.add_field(
        name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True
    )
    embed.add_field(name="Time", value=friend_time.strftime("%I:%M %p"), inline=True)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /similar_timezone - Find team members within 2 hours
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="similar_timezone",
    description="Find team members within 2 hours of your timezone",
)
async def similar_timezone(interaction: discord.Interaction):
    await interaction.response.defer()

    your_id = str(interaction.user.id)
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if your_id not in timezones:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Your timezone not set", color=0xDA3633)
        )
        return

    your_offset = timezones[your_id]["offset"]
    similar = []

    for user_id, tz_data in timezones.items():
        if user_id == your_id:
            continue
        offset = tz_data["offset"]
        diff = abs(offset - your_offset)
        if diff <= 2:
            similar.append((tz_data["code"], diff, user_id))

    embed = discord.Embed(title="🌍 Similar Timezones", color=0x0066FF)
    if similar:
        for tz, diff, user_id in sorted(similar, key=lambda x: x[1]):
            try:
                user = await interaction.client.fetch_user(int(user_id))
                user_name = user.display_name
            except:
                user_name = f"User {user_id}"
            embed.add_field(
                name=f"👤 {user_name}", value=f"{tz} ({diff}h diff)", inline=False
            )
    else:
        embed.description = "No one within 2 hours"

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /world_clock - Show all team timezones
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="world_clock", description="Show current time in all team timezones"
)
async def world_clock(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)

    if not timezones:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ No timezones set", color=0xDA3633)
        )
        return

    from datetime import datetime, timedelta

    utc_now = datetime.utcnow()
    embeds = []
    seen_tz = set()

    for tz_data in timezones.values():
        tz_code = tz_data["code"]
        if tz_code in seen_tz:
            continue
        seen_tz.add(tz_code)

        offset = tz_data["offset"]
        local_time = utc_now + timedelta(hours=offset)
        time_12 = local_time.strftime("%I:%M %p")
        date_str = local_time.strftime("%a, %b %d")

        embed = discord.Embed(title=f"🕐 {tz_code} ({tz_data['utc']})", color=0x0066FF)
        embed.add_field(name="Time", value=time_12, inline=True)
        embed.add_field(name="Date", value=date_str, inline=True)
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# TIMEZONE MENU - Single Command Setup (Admin Only)
# ══════════════════════════════════════════════════════════════════════════════


def build_tz_options(filter_text: str = "") -> list:
    """Build SelectOption list from TIMEZONES, optionally filtered by search text."""
    results = []
    query = filter_text.lower().strip()
    for tz_key in sorted(TIMEZONES.keys()):
        tz = TIMEZONES[tz_key]
        label = f"{tz['code']} ({tz['utc']}) - {tz['name']}"
        if (
            query
            and query not in label.lower()
            and query not in tz.get("region", "").lower()
            and query not in tz.get("iana", "").lower()
        ):
            continue
        results.append(
            discord.SelectOption(label=label[:100], value=tz_key, emoji="🌍")
        )
    return results


class TimezoneSearchModal(discord.ui.Modal, title="🔍 Search Timezone"):
    query = discord.ui.TextInput(
        label="Search",
        placeholder="e.g. India, UTC+8, Pacific, IST ...",
        required=True,
        max_length=50,
    )

    def __init__(self, all_options: list):
        super().__init__()
        self.all_options = all_options  # full unfiltered list (SelectOption objects)

    async def on_submit(self, interaction: discord.Interaction):
        filtered = build_tz_options(self.query.value)
        if not filtered:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ No Results",
                    description=f"No timezones found for **{self.query.value}**",
                    color=0xDA3633,
                ),
                ephemeral=True,
            )
            return
        new_view = TimezoneSelectView(
            self.all_options,
            page=0,
            filtered_options=filtered,
            search_query=self.query.value,
        )
        await interaction.response.edit_message(view=new_view)


class TimezoneSelectView(discord.ui.View):
    """Dropdown select for timezone with pagination + search"""

    def __init__(
        self,
        all_options: list,
        page: int = 0,
        filtered_options: list = None,
        search_query: str = "",
    ):
        super().__init__(timeout=None)
        self.all_options = all_options  # full list always kept
        self.page = page
        self.search_query = search_query
        # displayed list is filtered if a search is active, otherwise full list
        self.display_options = (
            filtered_options if filtered_options is not None else all_options
        )

        # ── Dropdown ──────────────────────────────────────────────────────────
        current_page_options = self.display_options[page * 25 : (page + 1) * 25]
        self.add_item(
            TimezoneSelect(current_page_options, len(self.display_options), page)
        )

        # ── Prev / Next buttons (added directly to self — no nested View) ─────
        if page > 0:
            prev_btn = discord.ui.Button(
                label="← Previous", style=discord.ButtonStyle.primary, row=1
            )

            async def prev_callback(interaction: discord.Interaction):
                await interaction.response.defer()
                new_view = TimezoneSelectView(
                    self.all_options, page - 1, self.display_options, self.search_query
                )
                await interaction.message.edit(view=new_view)

            prev_btn.callback = prev_callback
            self.add_item(prev_btn)

        if (page + 1) * 25 < len(self.display_options):
            next_btn = discord.ui.Button(
                label="Next →", style=discord.ButtonStyle.primary, row=1
            )

            async def next_callback(interaction: discord.Interaction):
                await interaction.response.defer()
                new_view = TimezoneSelectView(
                    self.all_options, page + 1, self.display_options, self.search_query
                )
                await interaction.message.edit(view=new_view)

            next_btn.callback = next_callback
            self.add_item(next_btn)

        # ── Search button ─────────────────────────────────────────────────────
        search_btn = discord.ui.Button(
            label=(
                "🔍 Search" if not search_query else f"🔍 Search: {search_query[:20]}"
            ),
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        async def search_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(TimezoneSearchModal(self.all_options))

        search_btn.callback = search_callback
        self.add_item(search_btn)

        # ── Clear search button (only shown when a filter is active) ──────────
        if search_query:
            clear_btn = discord.ui.Button(
                label="✖ Clear Filter", style=discord.ButtonStyle.danger, row=1
            )

            async def clear_callback(interaction: discord.Interaction):
                await interaction.response.defer()
                new_view = TimezoneSelectView(self.all_options, page=0)
                await interaction.message.edit(view=new_view)

            clear_btn.callback = clear_callback
            self.add_item(clear_btn)


class TimezoneSelect(discord.ui.Select):
    """Select dropdown for choosing timezone"""

    def __init__(self, options, total_count, page):
        super().__init__(
            placeholder=f"Select timezone (Page {page+1} of {max(1, (total_count+24)//25)}, {total_count} shown)...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self.total_count = total_count
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        selected_tz = self.values[0]
        user_id = str(interaction.user.id)
        tz_info = TIMEZONES[selected_tz]

        async with aiohttp.ClientSession() as session:
            timezones, sha = await github_read_json(session, FILE_TIMEZONES)
            timezones[user_id] = {
                "code": tz_info["code"],
                "name": tz_info["name"],
                "offset": tz_info["offset"],
                "utc": tz_info["utc"],
            }
            success = await github_write_json(
                session,
                FILE_TIMEZONES,
                timezones,
                sha,
                f"Set timezone for {interaction.user.display_name}",
            )

        if success:
            embed = discord.Embed(
                title="✅ Timezone Set!",
                description=f"**{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}",
                color=0x2EA043,
            )
        else:
            embed = discord.Embed(title="❌ Failed to save timezone", color=0xDA3633)

        await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="setup_timezone_menu", description="Setup timezone selection menu (Admin only)"
)
@app_commands.describe(
    channel="Channel to post in (required)",
    role="Role to mention (optional)",
    message="Custom message (optional - leave blank for default)",
)
@app_commands.default_permissions(administrator=True)
async def setup_timezone_menu(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role = None,
    message: str = None,
):
    """Admin command to setup timezone menu - all in one command"""
    await interaction.response.defer(ephemeral=True)

    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Admin only", color=0xDA3633), ephemeral=True
        )
        return

    # Build timezone select options for ALL timezones
    options = build_tz_options()

    # Use custom message or default
    if message:
        msg_content = message
    else:
        msg_content = "WHICH TIMEZONE ARE YOU ROUGHLY?\n\nSelect your timezone from the dropdown below\n\n(Scroll through pages to see all timezones)"

    # Add role mention if provided
    if role:
        msg_content = f"{role.mention}\n\n{msg_content}"

    # Create and send message with timezone selector (with pagination)
    embed = discord.Embed(
        title="🌍 Timezone Selector", description=msg_content, color=0x0066FF
    )
    embed.set_footer(text=f"Total timezones: {len(options)}")
    view = TimezoneSelectView(options, page=0)

    try:
        await channel.send(embed=embed, view=view)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Timezone menu posted!",
                description=f"Posted to {channel.mention}\n({len(options)} timezones available)",
                color=0x2EA043,
            ),
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Error", description=str(e)[:100], color=0xDA3633
            ),
            ephemeral=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PREFIX COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


def is_admin(ctx):
    return ctx.author.guild_permissions.administrator


# ── ?help ─────────────────────────────────────────────────────────────────────


@bot.command(name="help")
async def prefix_help(ctx, command_name: str = None):
    prefixes = _prefix_cache
    p = prefixes[0] if prefixes else "?"

    if command_name:
        help_map = {
            "setup": f"`{p}setup <anilist_id> <mal_id> [author_name]`\nLink your AniList and MAL accounts.",
            "myprofile": f"`{p}myprofile`\nView your saved profile.",
            "add_anime": f"`{p}add_anime <anilist_url> <mal_url> <reason>`\nAdd an underrated anime.",
            "add_manga": f"`{p}add_manga <anilist_url> <mal_url> <reason>`\nAdd an underrated manga.",
            "list_anime": f"`{p}list_anime`\nView the underrated anime list.",
            "list_manga": f"`{p}list_manga`\nView the underrated manga list.",
            "remove_anime": f"`{p}remove_anime <title or id>`\nRemove an anime from the list.",
            "remove_manga": f"`{p}remove_manga <title or id>`\nRemove a manga from the list.",
            "build": f"`{p}build <platforms> <build_type> [pr_numbers] [tag]`\nTrigger a build. Platforms: all/android/linux/windows/macos/ios. Type: alpha/stable",
            "create_tag": f"`{p}create_tag <tag> <message>`\nCreate a Git tag on the beta branch.",
            "delete_tag": f"`{p}delete_tag <tag>`\nDelete a Git tag and its release.",
            "latest_run": f"`{p}latest_run`\nCheck the latest workflow run.",
            "set_timezone": f"`{p}set_timezone <TZ_CODE>`\nSet your timezone. e.g. `{p}set_timezone IST`",
            "remove_timezone": f"`{p}remove_timezone`\nRemove your timezone.",
            "my_time": f"`{p}my_time`\nCheck your current local time.",
            "timezone_list": f"`{p}timezone_list`\nView all available timezones.",
            "add_friend_timezone": f"`{p}add_friend_timezone @user <TZ_CODE>`\nSet a friend's timezone.",
            "friend_time": f"`{p}friend_time @user`\nCheck a friend's current time.",
            "list_friends": f"`{p}list_friends`\nShow all team members' times.",
            "friend_compare": f"`{p}friend_compare @user`\nCompare time difference with a friend.",
            "timezone_convert": f"`{p}timezone_convert <FROM> <TO> <HH:MM>`\ne.g. `{p}timezone_convert IST EST 14:30`",
            "timezone_stats": f"`{p}timezone_stats`\nShow timezone distribution across the team.",
            "night_mode": f"`{p}night_mode @user`\nCheck if a friend is sleeping (10PM-7AM).",
            "similar_timezone": f"`{p}similar_timezone`\nFind members within 2 hours of your timezone.",
            "world_clock": f"`{p}world_clock`\nShow current time in all team timezones.",
            "setprefix": f"`{p}setprefix add <prefix>` — Add a prefix\n`{p}setprefix remove <prefix>` — Remove a prefix\n`{p}setprefix list` — Show active prefixes\n*(Admin only)*",
        }
        info = help_map.get(command_name.lower())
        if info:
            embed = discord.Embed(
                title=f"📖 Help: {command_name}", description=info, color=0x0066FF
            )
        else:
            embed = discord.Embed(
                title="❌ Unknown command",
                description=f"No help found for `{command_name}`.",
                color=0xDA3633,
            )
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="📖 AnymeX-Preview Bot",
        description=f"Active prefixes: `{'`, `'.join(prefixes)}`\nUse `{p}help <command>` for details.\nSlash commands `/` available for all features.",
        color=0x0066FF,
    )
    embed.add_field(name="👤 Profile", value="`setup` `myprofile`", inline=False)
    embed.add_field(
        name="🎌 Anime / Manga",
        value="`add_anime` `add_manga` `list_anime` `list_manga` `remove_anime` `remove_manga`",
        inline=False,
    )
    embed.add_field(
        name="🔨 Build / GitHub",
        value="`build` `create_tag` `delete_tag` `latest_run`",
        inline=False,
    )
    embed.add_field(
        name="🌍 Timezone",
        value="`set_timezone` `remove_timezone` `my_time` `timezone_list`\n`add_friend_timezone` `friend_time` `list_friends` `friend_compare`\n`timezone_convert` `timezone_stats` `night_mode` `similar_timezone` `world_clock`",
        inline=False,
    )
    embed.add_field(
        name="⚠️ Moderation (slash)",
        value="`/warn` `/warnings` `/clearwarnings` `/kick` `/ban` `/unban` `/mute` `/unmute` `/tempban` `/purge` `/slowmode`",
        inline=False,
    )
    embed.add_field(
        name="🍯 Honeypot (slash)",
        value="`/honeypot_set` `/honeypot_remove` `/honeypot_list`",
        inline=False,
    )
    embed.add_field(
        name="🤖 AutoMod (slash)",
        value="`/automod` — configure spam/caps/invite/mention/blacklist/url rules",
        inline=False,
    )
    embed.add_field(
        name="🔍 AniList (slash)",
        value="`/anime_search` `/manga_search` `/anilist_profile` `/character_search` `/staff_search` `/airing_schedule` `/seasonal_anime`",
        inline=False,
    )
    embed.add_field(
        name="🛠️ Utility (slash)",
        value="`/poll` `/remind` `/userinfo` `/serverinfo` `/avatar`",
        inline=False,
    )
    embed.add_field(
        name="⚙️ Config (slash)",
        value="`/server_config` `/config_role` `/setup_timezone_menu`",
        inline=False,
    )
    embed.add_field(name="⚙️ Admin (prefix)", value="`setprefix`", inline=False)
    await ctx.send(embed=embed)


# ── ?setprefix ────────────────────────────────────────────────────────────────


@bot.command(name="setprefix")
async def prefix_setprefix(ctx, action: str = None, new_prefix: str = None):
    if not is_admin(ctx):
        await ctx.send(embed=discord.Embed(title="❌ Admin only", color=0xDA3633))
        return

    if action is None or action.lower() not in ("add", "remove", "list"):
        await ctx.send(
            embed=discord.Embed(
                title="Usage",
                description=f"`{_prefix_cache[0]}setprefix add <prefix>`\n`{_prefix_cache[0]}setprefix remove <prefix>`\n`{_prefix_cache[0]}setprefix list`",
                color=0x0066FF,
            )
        )
        return

    async with aiohttp.ClientSession() as session:
        prefixes, sha = await github_read_json(session, FILE_PREFIXES)
        if not isinstance(prefixes, list):
            prefixes = DEFAULT_PREFIXES[:]

        if action.lower() == "list":
            await ctx.send(
                embed=discord.Embed(
                    title="⚙️ Active Prefixes",
                    description="\n".join(f"`{p}`" for p in prefixes),
                    color=0x0066FF,
                )
            )
            return

        if not new_prefix:
            await ctx.send("❌ Please provide a prefix.")
            return

        if action.lower() == "add":
            if new_prefix in prefixes:
                await ctx.send(
                    embed=discord.Embed(
                        title="⚠️ Already exists",
                        description=f"`{new_prefix}` is already a prefix.",
                        color=0xFFA500,
                    )
                )
                return
            if len(new_prefix) > 5:
                await ctx.send("❌ Prefix must be 5 characters or less.")
                return
            prefixes.append(new_prefix)
            ok = await github_write_json(
                session, FILE_PREFIXES, prefixes, sha, f"Add prefix: {new_prefix}"
            )
            if ok:
                _prefix_cache[:] = prefixes
                await ctx.send(
                    embed=discord.Embed(
                        title="✅ Prefix Added",
                        description=f"Added `{new_prefix}`\nActive: {', '.join(f'`{p}`' for p in prefixes)}",
                        color=0x2EA043,
                    )
                )
            else:
                await ctx.send(
                    embed=discord.Embed(title="❌ Failed to save", color=0xDA3633)
                )

        elif action.lower() == "remove":
            if new_prefix not in prefixes:
                await ctx.send(
                    embed=discord.Embed(
                        title="❌ Not found",
                        description=f"`{new_prefix}` is not an active prefix.",
                        color=0xDA3633,
                    )
                )
                return
            if len(prefixes) == 1:
                await ctx.send(
                    "❌ Can't remove the last prefix — add another one first."
                )
                return
            prefixes.remove(new_prefix)
            ok = await github_write_json(
                session, FILE_PREFIXES, prefixes, sha, f"Remove prefix: {new_prefix}"
            )
            if ok:
                _prefix_cache[:] = prefixes
                await ctx.send(
                    embed=discord.Embed(
                        title="✅ Prefix Removed",
                        description=f"Removed `{new_prefix}`\nActive: {', '.join(f'`{p}`' for p in prefixes)}",
                        color=0x2EA043,
                    )
                )
            else:
                await ctx.send(
                    embed=discord.Embed(title="❌ Failed to save", color=0xDA3633)
                )


# ── ?setup ────────────────────────────────────────────────────────────────────


@bot.command(name="setup")
async def prefix_setup(
    ctx, anilist_user_id: int = None, mal_user_id: int = None, *, author_name: str = ""
):
    if not anilist_user_id or not mal_user_id:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}setup <anilist_id> <mal_id> [author_name]`"
        )
        return
    discord_id = str(ctx.author.id)
    author_display = author_name or ctx.author.display_name
    async with aiohttp.ClientSession() as session:
        users, sha = await github_read_json(session, FILE_USERS)
        users[discord_id] = {
            "anilist_user_id": anilist_user_id,
            "mal_user_id": mal_user_id,
            "author_name": author_display,
        }
        ok = await github_write_json(
            session,
            FILE_USERS,
            users,
            sha,
            f"Setup profile for {ctx.author.display_name}",
        )
    if ok:
        embed = discord.Embed(title="✅ Profile Saved!", color=0x2EA043)
        embed.add_field(name="AniList ID", value=f"`{anilist_user_id}`", inline=True)
        embed.add_field(name="MAL ID", value=f"`{mal_user_id}`", inline=True)
        embed.add_field(name="Author Name", value=author_display, inline=True)
    else:
        embed = discord.Embed(title="❌ Failed to save profile", color=0xDA3633)
    await ctx.send(embed=embed)


# ── ?myprofile ────────────────────────────────────────────────────────────────


@bot.command(name="myprofile")
async def prefix_myprofile(ctx):
    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
    profile = users.get(str(ctx.author.id))
    if not profile:
        await ctx.send(f"❌ No profile found. Run `{_prefix_cache[0]}setup` first!")
        return
    embed = discord.Embed(title="👤 Your Profile", color=0x0078D4)
    embed.add_field(
        name="Author Name", value=profile.get("author_name", "—"), inline=True
    )
    embed.add_field(
        name="AniList ID", value=f"`{profile.get('anilist_user_id', '—')}`", inline=True
    )
    embed.add_field(
        name="MAL ID", value=f"`{profile.get('mal_user_id', '—')}`", inline=True
    )
    await ctx.send(embed=embed)


# ── ?add_anime / ?add_manga ───────────────────────────────────────────────────


async def prefix_handle_add(ctx, anilist_link, mal_link, reason, media_type):
    anilist_id = extract_anilist_id(anilist_link)
    mal_id = extract_mal_id(mal_link)
    if not anilist_id:
        await ctx.send("❌ Invalid AniList link.")
        return
    if not mal_id:
        await ctx.send("❌ Invalid MAL link.")
        return

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
        profile = users.get(str(ctx.author.id))
        if not profile:
            await ctx.send(f"❌ Run `{_prefix_cache[0]}setup` first!")
            return
        media = await fetch_anilist(session, anilist_id, media_type)

    if not media:
        await ctx.send("❌ Could not fetch info from AniList.")
        return

    titles = media["title"]
    title = (
        titles.get("english")
        or titles.get("romaji")
        or titles.get("native")
        or "Unknown"
    )
    cover_url = media.get("coverImage", {}).get("large", "")
    score = media.get("averageScore") or "N/A"
    author = (
        profile.get("author_name") or profile.get("author") or ctx.author.display_name
    )

    entry = {
        "anilist_id": anilist_id,
        "mal_id": mal_id,
        "title": title,
        "anilist_user_id": profile["anilist_user_id"],
        "mal_user_id": profile["mal_user_id"],
        "author": author,
        "reason": reason,
    }
    filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"React to confirm adding to `{filepath}`",
        color=0x0078D4,
    )
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Author", value=author, inline=True)
    preview.add_field(name="Reason", value=reason, inline=False)
    if cover_url:
        preview.set_thumbnail(url=cover_url)

    class PrefixConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
        async def confirm(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Not your confirmation!", ephemeral=True
                )
                return
            await interaction.response.defer()
            self.stop()
            async with aiohttp.ClientSession() as session:
                entries, sha = await github_read_json(session, filepath)
                if any(e.get("anilist_id") == anilist_id for e in entries):
                    await interaction.followup.send("⚠️ Already in the list!")
                    return
                entries.append(entry)
                ok = await github_write_json(
                    session, filepath, entries, sha, f"Add {title}"
                )
            await interaction.followup.send(
                embed=(
                    discord.Embed(title=f"🎉 Added {title}!", color=0x2EA043)
                    if ok
                    else discord.Embed(title="❌ Failed", color=0xDA3633)
                )
            )
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
        async def cancel(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Not your confirmation!", ephemeral=True
                )
                return
            self.stop()
            await interaction.response.send_message("Cancelled.", ephemeral=True)
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)

    await ctx.send(embed=preview, view=PrefixConfirmView())


@bot.command(name="add_anime")
@has_allowed_role_prefix()
async def prefix_add_anime(
    ctx, anilist_link: str = None, mal_link: str = None, *, reason: str = None
):
    if not anilist_link or not mal_link or not reason:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}add_anime <anilist_url> <mal_url> <reason>`"
        )
        return
    await prefix_handle_add(ctx, anilist_link, mal_link, reason, "ANIME")


@bot.command(name="add_manga")
@has_allowed_role_prefix()
async def prefix_add_manga(
    ctx, anilist_link: str = None, mal_link: str = None, *, reason: str = None
):
    if not anilist_link or not mal_link or not reason:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}add_manga <anilist_url> <mal_url> <reason>`"
        )
        return
    await prefix_handle_add(ctx, anilist_link, mal_link, reason, "MANGA")


# ── ?list_anime / ?list_manga ─────────────────────────────────────────────────


@bot.command(name="list_anime")
@has_allowed_role_prefix()
async def prefix_list_anime(ctx):
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_ANIME)
    if not entries:
        await ctx.send(
            embed=discord.Embed(
                title="Anime List", description="No anime added yet.", color=0x0066FF
            )
        )
        return
    embeds = []
    for i, entry in enumerate(entries, 1):
        e = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0x0066FF,
        )
        e.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        e.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(e)
    await ctx.send(embeds=embeds[:10])


@bot.command(name="list_manga")
@has_allowed_role_prefix()
async def prefix_list_manga(ctx):
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MANGA)
    if not entries:
        await ctx.send(
            embed=discord.Embed(
                title="Manga List", description="No manga added yet.", color=0xFF6B6B
            )
        )
        return
    embeds = []
    for i, entry in enumerate(entries, 1):
        e = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0xFF6B6B,
        )
        e.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        e.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(e)
    await ctx.send(embeds=embeds[:10])


# ── ?remove_anime / ?remove_manga ─────────────────────────────────────────────


async def prefix_remove(ctx, search_term, filepath, label):
    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
    found = next(
        (
            i
            for i, e in enumerate(entries)
            if (search_term.isdigit() and str(e.get("anilist_id")) == search_term)
            or search_term.lower() in e.get("title", "").lower()
        ),
        None,
    )
    if found is None:
        await ctx.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No {label} matching `{search_term}`",
                color=0xDA3633,
            )
        )
        return
    removed = entries.pop(found)
    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha, f"Remove {label}: {removed.get('title')}"
        )
    await ctx.send(
        embed=discord.Embed(
            title="✅ Removed" if ok else "❌ Failed",
            description=removed.get("title") if ok else None,
            color=0x2EA043 if ok else 0xDA3633,
        )
    )


@bot.command(name="remove_anime")
@has_allowed_role_prefix()
async def prefix_remove_anime(ctx, *, search_term: str = None):
    if not search_term:
        await ctx.send(f"Usage: `{_prefix_cache[0]}remove_anime <title or id>`")
        return
    await prefix_remove(ctx, search_term, FILE_ANIME, "anime")


@bot.command(name="remove_manga")
@has_allowed_role_prefix()
async def prefix_remove_manga(ctx, *, search_term: str = None):
    if not search_term:
        await ctx.send(f"Usage: `{_prefix_cache[0]}remove_manga <title or id>`")
        return
    await prefix_remove(ctx, search_term, FILE_MANGA, "manga")


# ── ?build ────────────────────────────────────────────────────────────────────

VALID_PLATFORMS = {
    "all",
    "android",
    "linux",
    "windows",
    "macos",
    "ios",
    "android,linux,ios",
    "android,ios",
    "android,windows",
    "android,linux",
    "android,macos",
    "linux,windows",
    "linux,macos",
    "windows,macos",
    "ios,macos",
}
VALID_BUILD_TYPES = {"alpha", "stable"}


@bot.command(name="build")
@has_allowed_role_prefix()
async def prefix_build(
    ctx,
    platforms: str = None,
    build_type: str = None,
    pr_numbers: str = "",
    tag_override: str = "",
):
    if not platforms or not build_type:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}build <platforms> <build_type> [pr_numbers] [tag]`\nPlatforms: `all`, `android`, `linux`, `windows`, `macos`, `ios`\nType: `alpha`, `stable`"
        )
        return
    if platforms not in VALID_PLATFORMS:
        await ctx.send(
            f"❌ Invalid platform. Valid: {', '.join(sorted(VALID_PLATFORMS))}"
        )
        return
    if build_type not in VALID_BUILD_TYPES:
        await ctx.send(f"❌ Invalid build type. Use `alpha` or `stable`.")
        return
    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "platforms": platforms,
            "build_type": build_type,
            "pr_numbers": pr_numbers,
            "tag_override": tag_override,
            "triggered_by": str(ctx.author.id),
        },
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
            headers=gh_headers(),
            json=payload,
        ) as r:
            status = r.status
            body = await r.text()
    if status == 204:
        embed = discord.Embed(title="🔨 Build Triggered!", color=0x2EA043)
        embed.add_field(name="Platforms", value=f"`{platforms}`", inline=True)
        embed.add_field(name="Type", value=f"`{build_type}`", inline=True)
        if pr_numbers:
            embed.add_field(name="PRs", value=pr_numbers, inline=True)
        if tag_override:
            embed.add_field(name="Tag", value=f"`{tag_override}`", inline=True)
        embed.set_footer(text=f"Triggered by {ctx.author.display_name}")
        await ctx.send(embed=embed)
    else:
        await ctx.send(
            embed=discord.Embed(
                title="❌ Build Failed",
                description=f"Status: `{status}`\n```{body[:500]}```",
                color=0xDA3633,
            )
        )


# ── ?create_tag / ?delete_tag ─────────────────────────────────────────────────


@bot.command(name="create_tag")
@has_allowed_role_prefix()
async def prefix_create_tag(ctx, tag: str = None, *, message: str = ""):
    if not tag:
        await ctx.send(f"Usage: `{_prefix_cache[0]}create_tag <tag> <message>`")
        return
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            if r.status != 200:
                await ctx.send("❌ Branch not found.")
                return
            sha = (await r.json())["object"]["sha"]
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/tags",
            headers=gh_headers(),
            json={"tag": tag, "message": message, "object": sha, "type": "commit"},
        ) as r:
            if r.status not in (200, 201):
                await ctx.send("❌ Tag creation failed.")
                return
            tag_sha = (await r.json())["sha"]
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs",
            headers=gh_headers(),
            json={"ref": f"refs/tags/{tag}", "sha": tag_sha},
        ) as r:
            ok = r.status in (200, 201)
    if ok:
        embed = discord.Embed(title="🏷️ Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Failed to create ref.")


@bot.command(name="delete_tag")
@has_allowed_role_prefix()
async def prefix_delete_tag(ctx, tag: str = None):
    if not tag:
        await ctx.send(f"Usage: `{_prefix_cache[0]}delete_tag <tag>`")
        return
    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs/tags/{tag}",
            headers=gh_headers(),
        ) as r:
            tag_status = r.status
        if tag_status in (200, 204):
            async with session.delete(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag}",
                headers=gh_headers(),
            ) as r:
                rel_status = r.status
        else:
            rel_status = 404
    if tag_status in (200, 204):
        embed = discord.Embed(title="✅ Tag Deleted!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(
            name="Release",
            value="Deleted" if rel_status in (200, 204) else "Not found",
            inline=True,
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send(
            embed=discord.Embed(
                title="❌ Tag not found", description=f"`{tag}`", color=0xDA3633
            )
        )


# ── ?latest_run ───────────────────────────────────────────────────────────────


@bot.command(name="latest_run")
@has_allowed_role_prefix()
async def prefix_latest_run(ctx):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/beta_manual.yml/runs?per_page=1&branch={GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            if r.status != 200:
                await ctx.send("❌ Error fetching runs.")
                return
            data = await r.json()
    if not data.get("workflow_runs"):
        await ctx.send("❌ No runs found.")
        return
    run = data["workflow_runs"][0]
    conclusion = run.get("conclusion") or "in_progress"
    EMOJI_MAP = {
        "success": "✅",
        "failure": "❌",
        "cancelled": "🚫",
        "in_progress": "⏳",
    }
    embed = discord.Embed(
        title=f"{EMOJI_MAP.get(conclusion,'❓')} {run['name']}",
        color=(
            0x2EA043
            if conclusion == "success"
            else (0xDA3633 if conclusion == "failure" else 0xFFA500)
        ),
    )
    embed.add_field(name="Status", value=f"`{conclusion}`", inline=True)
    embed.add_field(name="Run #", value=f"`{run['run_number']}`", inline=True)
    embed.add_field(name="Link", value=f"[View Run]({run['html_url']})", inline=False)
    await ctx.send(embed=embed)


# ── ?set_timezone ─────────────────────────────────────────────────────────────


@bot.command(name="set_timezone")
async def prefix_set_timezone(ctx, timezone: str = None):
    if not timezone:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}set_timezone <TZ_CODE>` e.g. `{_prefix_cache[0]}set_timezone IST`"
        )
        return
    tz_upper = timezone.upper()
    if tz_upper not in TIMEZONES:
        await ctx.send(
            embed=discord.Embed(
                title="❌ Invalid Timezone",
                description=f"`{tz_upper}` not found. Use `{_prefix_cache[0]}timezone_list` to see all.",
                color=0xDA3633,
            )
        )
        return
    discord_id = str(ctx.author.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        tz_info = TIMEZONES[tz_upper]
        timezones[discord_id] = {
            "code": tz_info["code"],
            "name": tz_info["name"],
            "offset": tz_info["offset"],
            "utc": tz_info["utc"],
        }
        ok = await github_write_json(
            session,
            FILE_TIMEZONES,
            timezones,
            sha,
            f"Set timezone for {ctx.author.display_name}",
        )
    await ctx.send(
        embed=(
            discord.Embed(
                title="✅ Timezone Set!",
                description=f"**{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}",
                color=0x2EA043,
            )
            if ok
            else discord.Embed(title="❌ Failed", color=0xDA3633)
        )
    )


# ── ?remove_timezone ──────────────────────────────────────────────────────────


@bot.command(name="remove_timezone")
async def prefix_remove_timezone(ctx):
    discord_id = str(ctx.author.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        if discord_id not in timezones:
            await ctx.send("❌ No timezone set.")
            return
        del timezones[discord_id]
        ok = await github_write_json(
            session,
            FILE_TIMEZONES,
            timezones,
            sha,
            f"Remove timezone for {ctx.author.display_name}",
        )
    await ctx.send(
        embed=discord.Embed(
            title="✅ Timezone Removed!" if ok else "❌ Failed",
            color=0x2EA043 if ok else 0xDA3633,
        )
    )


# ── ?my_time ──────────────────────────────────────────────────────────────────


@bot.command(name="my_time")
async def prefix_my_time(ctx):
    from datetime import datetime, timedelta

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    tz_data = timezones.get(str(ctx.author.id))
    if not tz_data:
        await ctx.send(
            f"❌ Timezone not set. Use `{_prefix_cache[0]}set_timezone <TZ_CODE>`"
        )
        return
    your_time = datetime.utcnow() + timedelta(hours=tz_data["offset"])
    embed = discord.Embed(
        title="🕐 Your Time",
        description=f"**{your_time.strftime('%I:%M %p')}**",
        color=0x0066FF,
    )
    embed.add_field(
        name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True
    )
    await ctx.send(embed=embed)


# ── ?timezone_list ────────────────────────────────────────────────────────────


@bot.command(name="timezone_list")
async def prefix_timezone_list(ctx):
    regions = {}
    for tz, info in TIMEZONES.items():
        regions.setdefault(info["region"], []).append(
            f"**{info['code']}** ({info['utc']}) - {info['name']}"
        )
    embeds = [
        discord.Embed(title=f"🌍 {region}", description="\n".join(tzs), color=0x0066FF)
        for region, tzs in sorted(regions.items())
    ]
    await ctx.send(embeds=embeds)


# ── ?add_friend_timezone ──────────────────────────────────────────────────────


@bot.command(name="add_friend_timezone")
async def prefix_add_friend_timezone(
    ctx, user: discord.User = None, timezone: str = None
):
    if not user or not timezone:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}add_friend_timezone @user <TZ_CODE>`"
        )
        return
    tz_upper = timezone.upper()
    if tz_upper not in TIMEZONES:
        await ctx.send(
            f"❌ Invalid timezone. Use `{_prefix_cache[0]}timezone_list` to see all."
        )
        return
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        tz_info = TIMEZONES[tz_upper]
        timezones[str(user.id)] = {
            "code": tz_info["code"],
            "name": tz_info["name"],
            "offset": tz_info["offset"],
            "utc": tz_info["utc"],
        }
        ok = await github_write_json(
            session,
            FILE_TIMEZONES,
            timezones,
            sha,
            f"Add timezone for {user.display_name}",
        )
    await ctx.send(
        embed=discord.Embed(
            title="✅ Friend's Timezone Added!" if ok else "❌ Failed",
            description=(
                f"{user.mention} → **{tz_info['code']}** ({tz_info['utc']})"
                if ok
                else None
            ),
            color=0x2EA043 if ok else 0xDA3633,
        )
    )


# ── ?friend_time ──────────────────────────────────────────────────────────────


@bot.command(name="friend_time")
async def prefix_friend_time(ctx, user: discord.User = None):
    if not user:
        await ctx.send(f"Usage: `{_prefix_cache[0]}friend_time @user`")
        return
    from datetime import datetime, timedelta

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    tz_data = timezones.get(str(user.id))
    if not tz_data:
        await ctx.send(f"❌ {user.display_name} hasn't set their timezone.")
        return
    friend_time = datetime.utcnow() + timedelta(hours=tz_data["offset"])
    embed = discord.Embed(
        title=f"🕐 {user.display_name}'s Time",
        description=f"**{friend_time.strftime('%I:%M %p')}**",
        color=0x0066FF,
    )
    embed.add_field(
        name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True
    )
    await ctx.send(embed=embed)


# ── ?list_friends ─────────────────────────────────────────────────────────────


@bot.command(name="list_friends")
async def prefix_list_friends(ctx):
    from datetime import datetime, timedelta

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    if not timezones:
        await ctx.send("❌ No timezones set.")
        return
    utc_now = datetime.utcnow()
    embed = discord.Embed(title="🌍 Friends' Times", color=0x0066FF)
    for user_id, tz_data in sorted(timezones.items()):
        try:
            user = await bot.fetch_user(int(user_id))
            name = user.display_name
        except:
            name = f"User {user_id}"
        t = utc_now + timedelta(hours=tz_data["offset"])
        embed.add_field(
            name=f"👤 {name}",
            value=f"🕐 {t.strftime('%I:%M %p')} ({tz_data['code']})",
            inline=False,
        )
    await ctx.send(embed=embed)


# ── ?friend_compare ───────────────────────────────────────────────────────────


@bot.command(name="friend_compare")
async def prefix_friend_compare(ctx, user: discord.User = None):
    if not user:
        await ctx.send(f"Usage: `{_prefix_cache[0]}friend_compare @user`")
        return
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    your_tz = timezones.get(str(ctx.author.id))
    friend_tz = timezones.get(str(user.id))
    if not your_tz or not friend_tz:
        await ctx.send("❌ Both users need a timezone set.")
        return
    diff = friend_tz["offset"] - your_tz["offset"]
    sign = "+" if diff >= 0 else ""
    embed = discord.Embed(title="⏰ Time Difference", color=0x0066FF)
    embed.add_field(
        name="You", value=f"{your_tz['code']} ({your_tz['utc']})", inline=True
    )
    embed.add_field(
        name=user.display_name,
        value=f"{friend_tz['code']} ({friend_tz['utc']})",
        inline=True,
    )
    embed.add_field(name="Difference", value=f"{sign}{diff}h", inline=False)
    await ctx.send(embed=embed)


# ── ?timezone_convert ─────────────────────────────────────────────────────────


@bot.command(name="timezone_convert")
async def prefix_timezone_convert(
    ctx, from_tz: str = None, to_tz: str = None, time: str = None
):
    if not from_tz or not to_tz or not time:
        await ctx.send(
            f"Usage: `{_prefix_cache[0]}timezone_convert <FROM> <TO> <HH:MM>` e.g. `{_prefix_cache[0]}timezone_convert IST EST 14:30`"
        )
        return
    from_upper, to_upper = from_tz.upper(), to_tz.upper()
    if from_upper not in TIMEZONES or to_upper not in TIMEZONES:
        await ctx.send("❌ Invalid timezone(s).")
        return
    try:
        hour, minute = map(int, time.split(":"))
        diff = TIMEZONES[to_upper]["offset"] - TIMEZONES[from_upper]["offset"]
        new_hour = (hour + int(diff)) % 24
        embed = discord.Embed(title="🕐 Time Conversion", color=0x0066FF)
        embed.add_field(
            name=TIMEZONES[from_upper]["code"],
            value=f"{hour:02d}:{minute:02d}",
            inline=True,
        )
        embed.add_field(
            name=TIMEZONES[to_upper]["code"],
            value=f"{new_hour:02d}:{minute:02d}",
            inline=True,
        )
        await ctx.send(embed=embed)
    except:
        await ctx.send("❌ Invalid time format. Use HH:MM (24h).")


# ── ?timezone_stats ───────────────────────────────────────────────────────────


@bot.command(name="timezone_stats")
async def prefix_timezone_stats(ctx):
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    if not timezones:
        await ctx.send("❌ No timezones set.")
        return
    tz_count = {}
    for tz_data in timezones.values():
        tz_count[tz_data["code"]] = tz_count.get(tz_data["code"], 0) + 1
    embed = discord.Embed(title="📊 Timezone Distribution", color=0x0066FF)
    for tz, count in sorted(tz_count.items(), key=lambda x: x[1], reverse=True):
        embed.add_field(name=tz, value=f"{count} member(s)", inline=True)
    await ctx.send(embed=embed)


# ── ?night_mode ───────────────────────────────────────────────────────────────


@bot.command(name="night_mode")
async def prefix_night_mode(ctx, user: discord.User = None):
    if not user:
        await ctx.send(f"Usage: `{_prefix_cache[0]}night_mode @user`")
        return
    from datetime import datetime, timedelta

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    tz_data = timezones.get(str(user.id))
    if not tz_data:
        await ctx.send(f"❌ {user.display_name} hasn't set their timezone.")
        return
    friend_time = datetime.utcnow() + timedelta(hours=tz_data["offset"])
    is_sleeping = friend_time.hour < 7 or friend_time.hour >= 22
    embed = discord.Embed(
        title=f"😴 {user.display_name}",
        description="🔴 SLEEPING" if is_sleeping else "🟢 AWAKE",
        color=0xDA3633 if is_sleeping else 0x2EA043,
    )
    embed.add_field(name="Time", value=friend_time.strftime("%I:%M %p"), inline=True)
    embed.add_field(
        name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True
    )
    await ctx.send(embed=embed)


# ── ?similar_timezone ─────────────────────────────────────────────────────────


@bot.command(name="similar_timezone")
async def prefix_similar_timezone(ctx):
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    your_id = str(ctx.author.id)
    if your_id not in timezones:
        await ctx.send(
            f"❌ Your timezone not set. Use `{_prefix_cache[0]}set_timezone <TZ_CODE>`"
        )
        return
    your_offset = timezones[your_id]["offset"]
    similar = [
        (tz_data["code"], abs(tz_data["offset"] - your_offset), uid)
        for uid, tz_data in timezones.items()
        if uid != your_id and abs(tz_data["offset"] - your_offset) <= 2
    ]
    embed = discord.Embed(title="🌍 Similar Timezones", color=0x0066FF)
    if similar:
        for tz, diff, uid in sorted(similar, key=lambda x: x[1]):
            try:
                u = await bot.fetch_user(int(uid))
                name = u.display_name
            except:
                name = f"User {uid}"
            embed.add_field(
                name=f"👤 {name}", value=f"{tz} ({diff}h diff)", inline=False
            )
    else:
        embed.description = "No one within 2 hours."
    await ctx.send(embed=embed)


# ── ?world_clock ──────────────────────────────────────────────────────────────


@bot.command(name="world_clock")
async def prefix_world_clock(ctx):
    from datetime import datetime, timedelta

    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    if not timezones:
        await ctx.send("❌ No timezones set.")
        return
    utc_now = datetime.utcnow()
    embeds, seen = [], set()
    for tz_data in timezones.values():
        if tz_data["code"] in seen:
            continue
        seen.add(tz_data["code"])
        t = utc_now + timedelta(hours=tz_data["offset"])
        e = discord.Embed(
            title=f"🕐 {tz_data['code']} ({tz_data['utc']})", color=0x0066FF
        )
        e.add_field(name="Time", value=t.strftime("%I:%M %p"), inline=True)
        e.add_field(name="Date", value=t.strftime("%a, %b %d"), inline=True)
        embeds.append(e)
    await ctx.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# Run bot + health server together
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SERVER CONFIG COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="server_config", description="View or update server configuration (Admin only)"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    mod_log_channel="Channel for moderation logs",
    join_leave_channel="Channel for join/leave logs",
    mute_role="Role to apply when muting users",
    warn_mute_threshold="Number of warnings before auto-mute",
    warn_ban_threshold="Number of warnings before auto-ban",
    warn_expiry_days="Days until warnings expire (0 = never)",
)
async def server_config(
    interaction: discord.Interaction,
    mod_log_channel: discord.TextChannel = None,
    join_leave_channel: discord.TextChannel = None,
    mute_role: discord.Role = None,
    warn_mute_threshold: int = None,
    warn_ban_threshold: int = None,
    warn_expiry_days: int = None,
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
        changed = False
        if mod_log_channel:
            cfg["mod_log_channel"] = mod_log_channel.id
            changed = True
        if join_leave_channel:
            cfg["join_leave_channel"] = join_leave_channel.id
            changed = True
        if mute_role:
            cfg["mute_role"] = mute_role.id
            changed = True
        if warn_mute_threshold is not None:
            cfg["warn_thresholds"][str(warn_mute_threshold)] = "mute"
            changed = True
        if warn_ban_threshold is not None:
            cfg["warn_thresholds"][str(warn_ban_threshold)] = "ban"
            changed = True
        if warn_expiry_days is not None:
            cfg["warn_expiry_days"] = warn_expiry_days
            changed = True
        if changed:
            await save_server_cfg(session, guild_id, cfg)
    embed = discord.Embed(title="⚙️ Server Configuration", color=0x0066FF)
    embed.add_field(
        name="Mod Log",
        value=(
            f"<#{cfg['mod_log_channel']}>" if cfg.get("mod_log_channel") else "Not set"
        ),
        inline=True,
    )
    embed.add_field(
        name="Join/Leave Log",
        value=(
            f"<#{cfg['join_leave_channel']}>"
            if cfg.get("join_leave_channel")
            else "Not set"
        ),
        inline=True,
    )
    embed.add_field(
        name="Mute Role",
        value=f"<@&{cfg['mute_role']}>" if cfg.get("mute_role") else "Not set",
        inline=True,
    )
    embed.add_field(
        name="Warn Thresholds", value=str(cfg.get("warn_thresholds", {})), inline=True
    )
    embed.add_field(
        name="Warn Expiry", value=f"{cfg.get('warn_expiry_days', 30)} days", inline=True
    )
    embed.add_field(
        name="Allowed Roles",
        value=", ".join(f"<@&{r}>" for r in cfg.get("allowed_roles", [])) or "None",
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="config_role",
    description="Add or remove a role from the allowed roles list (Admin only)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="add or remove", role="Role to configure")
@app_commands.choices(
    action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ]
)
async def config_role(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    role: discord.Role,
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
        roles = cfg.get("allowed_roles", [])
        if action.value == "add":
            if role.id not in roles:
                roles.append(role.id)
                msg = f"✅ Added {role.mention} to allowed roles."
            else:
                msg = f"⚠️ {role.mention} is already in allowed roles."
        else:
            if role.id in roles:
                roles.remove(role.id)
                msg = f"✅ Removed {role.mention} from allowed roles."
            else:
                msg = f"❌ {role.mention} was not in allowed roles."
        cfg["allowed_roles"] = roles
        await save_server_cfg(session, guild_id, cfg)
    await interaction.followup.send(msg, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# WARNING SYSTEM
# ══════════════════════════════════════════════════════════════════════════════


async def _get_guild_warnings(session, guild_id: str) -> tuple:
    all_warns, sha = await github_read_json(session, FILE_WARNINGS)
    return all_warns.get(guild_id, {}), sha, all_warns


async def _save_guild_warnings(
    session, guild_id: str, guild_warns: dict, all_warns: dict, sha
):
    all_warns[guild_id] = guild_warns
    return await github_write_json(
        session, FILE_WARNINGS, all_warns, sha, f"Update warnings for guild {guild_id}"
    )


async def _log_mod_action(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("mod_log_channel")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if ch:
        try:
            await ch.send(embed=embed)
        except Exception:
            pass


async def _add_mod_case(session, guild_id: str, case: dict):
    all_cases, sha = await github_read_json(session, FILE_MOD_CASES)
    guild_cases = all_cases.get(guild_id, [])
    case["case_id"] = len(guild_cases) + 1
    guild_cases.append(case)
    all_cases[guild_id] = guild_cases
    await github_write_json(
        session, FILE_MOD_CASES, all_cases, sha, f"Add mod case for guild {guild_id}"
    )
    return case["case_id"]


@bot.tree.command(name="warn", description="Warn a user")
@app_commands.describe(user="User to warn", reason="Reason for warning")
@has_allowed_role()
async def warn_user(
    interaction: discord.Interaction, user: discord.Member, reason: str
):
    await interaction.response.defer()
    guild_id = str(interaction.guild_id)
    user_id = str(user.id)
    from datetime import datetime

    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
        guild_warns, sha, all_warns = await _get_guild_warnings(session, guild_id)
        expiry_days = cfg.get("warn_expiry_days", 30)
        now = datetime.utcnow()
        # Expire old warnings
        if user_id in guild_warns and expiry_days > 0:
            guild_warns[user_id] = [
                w
                for w in guild_warns[user_id]
                if (now - datetime.fromisoformat(w["timestamp"])).days < expiry_days
            ]
        if user_id not in guild_warns:
            guild_warns[user_id] = []
        entry = {
            "reason": reason,
            "moderator": str(interaction.user.id),
            "timestamp": now.isoformat(),
        }
        guild_warns[user_id].append(entry)
        count = len(guild_warns[user_id])
        await _save_guild_warnings(session, guild_id, guild_warns, all_warns, sha)
        case_id = await _add_mod_case(
            session,
            guild_id,
            {
                "type": "warn",
                "user": user_id,
                "mod": str(interaction.user.id),
                "reason": reason,
                "timestamp": now.isoformat(),
            },
        )

        # Check thresholds
        thresholds = cfg.get("warn_thresholds", {})
        action_taken = None
        for threshold_str, action in sorted(
            thresholds.items(), key=lambda x: int(x[0])
        ):
            if count == int(threshold_str):
                action_taken = action
                break

        embed = discord.Embed(title=f"⚠️ Warning #{count}", color=0xFFA500)
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Total Warnings", value=str(count), inline=True)
        embed.set_footer(text=f"Case #{case_id}")

        log_embed = discord.Embed(
            title=f"⚠️ User Warned | Case #{case_id}", color=0xFFA500
        )
        log_embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
        log_embed.add_field(name="Moderator", value=str(interaction.user), inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="Warning #", value=str(count), inline=True)
        await _log_mod_action(interaction.guild, cfg, log_embed)

        if action_taken == "mute":
            mute_role_id = cfg.get("mute_role")
            if mute_role_id:
                mute_role = interaction.guild.get_role(mute_role_id)
                if mute_role:
                    await user.add_roles(
                        mute_role, reason=f"Auto-mute: {count} warnings"
                    )
            else:
                await user.timeout(
                    discord.utils.utcnow() + __import__("datetime").timedelta(hours=1),
                    reason=f"Auto-mute: {count} warnings",
                )
            embed.add_field(
                name="Auto Action", value="🔇 Muted (threshold reached)", inline=False
            )
        elif action_taken == "ban":
            await user.ban(reason=f"Auto-ban: {count} warnings")
            embed.add_field(
                name="Auto Action", value="🔨 Banned (threshold reached)", inline=False
            )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="warnings", description="View warnings for a user")
@app_commands.describe(user="User to check")
@has_allowed_role()
async def view_warnings(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        guild_warns, _, _ = await _get_guild_warnings(session, guild_id)
    warns = guild_warns.get(str(user.id), [])
    if not warns:
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"✅ No warnings for {user.display_name}", color=0x2EA043
            ),
            ephemeral=True,
        )
        return
    embed = discord.Embed(title=f"⚠️ Warnings for {user.display_name}", color=0xFFA500)
    for i, w in enumerate(warns[-10:], 1):
        embed.add_field(
            name=f"#{i} — {w['timestamp'][:10]}",
            value=f"**Reason:** {w['reason']}\n**By:** <@{w['moderator']}>",
            inline=False,
        )
    embed.set_footer(text=f"Total: {len(warns)} warning(s)")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="clearwarnings", description="Clear all or specific warnings for a user"
)
@app_commands.describe(
    user="User", index="Warning number to remove (leave blank to clear all)"
)
@has_allowed_role()
async def clear_warnings(
    interaction: discord.Interaction, user: discord.Member, index: int = None
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        guild_warns, sha, all_warns = await _get_guild_warnings(session, guild_id)
        uid = str(user.id)
        if uid not in guild_warns or not guild_warns[uid]:
            await interaction.followup.send("❌ No warnings found.", ephemeral=True)
            return
        if index is None:
            removed = len(guild_warns[uid])
            guild_warns[uid] = []
            msg = f"✅ Cleared all {removed} warning(s) for {user.mention}."
        else:
            if index < 1 or index > len(guild_warns[uid]):
                await interaction.followup.send(
                    "❌ Invalid warning number.", ephemeral=True
                )
                return
            guild_warns[uid].pop(index - 1)
            msg = f"✅ Removed warning #{index} for {user.mention}."
        await _save_guild_warnings(session, guild_id, guild_warns, all_warns, sha)
    await interaction.followup.send(msg, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# MODERATION COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="kick", description="Kick a user")
@app_commands.describe(user="User to kick", reason="Reason")
@has_allowed_role()
async def kick_user(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided",
):
    await interaction.response.defer()
    from datetime import datetime

    try:
        await user.kick(reason=reason)
        embed = discord.Embed(title="👢 User Kicked", color=0xFFA500)
        embed.add_field(name="User", value=str(user), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {interaction.user}")
        async with aiohttp.ClientSession() as session:
            cfg = await get_server_cfg(session, str(interaction.guild_id))
            await _log_mod_action(interaction.guild, cfg, embed)
            await _add_mod_case(
                session,
                str(interaction.guild_id),
                {
                    "type": "kick",
                    "user": str(user.id),
                    "mod": str(interaction.user.id),
                    "reason": reason,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to kick that user.")


@bot.tree.command(name="ban", description="Ban a user")
@app_commands.describe(
    user="User to ban", reason="Reason", delete_days="Days of messages to delete (0-7)"
)
@has_allowed_role()
async def ban_user(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str = "No reason provided",
    delete_days: int = 0,
):
    await interaction.response.defer()
    from datetime import datetime

    try:
        await user.ban(reason=reason, delete_message_days=min(delete_days, 7))
        embed = discord.Embed(title="🔨 User Banned", color=0xDA3633)
        embed.add_field(name="User", value=str(user), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {interaction.user}")
        async with aiohttp.ClientSession() as session:
            cfg = await get_server_cfg(session, str(interaction.guild_id))
            await _log_mod_action(interaction.guild, cfg, embed)
            await _add_mod_case(
                session,
                str(interaction.guild_id),
                {
                    "type": "ban",
                    "user": str(user.id),
                    "mod": str(interaction.user.id),
                    "reason": reason,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to ban that user.")


@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="Discord user ID to unban", reason="Reason")
@has_allowed_role()
async def unban_user(
    interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"
):
    await interaction.response.defer()
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        embed = discord.Embed(title="✅ User Unbanned", color=0x2EA043)
        embed.add_field(name="User", value=str(user), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed: {e}")


@bot.tree.command(name="mute", description="Timeout (mute) a user")
@app_commands.describe(
    user="User to mute", duration_minutes="Duration in minutes", reason="Reason"
)
@has_allowed_role()
async def mute_user(
    interaction: discord.Interaction,
    user: discord.Member,
    duration_minutes: int = 60,
    reason: str = "No reason provided",
):
    await interaction.response.defer()
    from datetime import datetime, timedelta

    try:
        until = discord.utils.utcnow() + timedelta(minutes=duration_minutes)
        await user.timeout(until, reason=reason)
        embed = discord.Embed(title="🔇 User Muted", color=0xFFA500)
        embed.add_field(name="User", value=str(user), inline=True)
        embed.add_field(
            name="Duration", value=f"{duration_minutes} minutes", inline=True
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        async with aiohttp.ClientSession() as session:
            cfg = await get_server_cfg(session, str(interaction.guild_id))
            await _log_mod_action(interaction.guild, cfg, embed)
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to timeout that user."
        )


@bot.tree.command(name="unmute", description="Remove timeout from a user")
@app_commands.describe(user="User to unmute")
@has_allowed_role()
async def unmute_user(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    try:
        await user.timeout(None)
        await interaction.followup.send(
            embed=discord.Embed(title=f"✅ {user.display_name} unmuted", color=0x2EA043)
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to remove that timeout."
        )


@bot.tree.command(name="tempban", description="Temporarily ban a user")
@app_commands.describe(
    user="User to tempban", duration_hours="Hours to ban", reason="Reason"
)
@has_allowed_role()
async def tempban_user(
    interaction: discord.Interaction,
    user: discord.Member,
    duration_hours: int = 24,
    reason: str = "No reason provided",
):
    await interaction.response.defer()
    from datetime import datetime, timedelta

    try:
        await user.ban(reason=f"[TEMPBAN {duration_hours}h] {reason}")
        unban_time = datetime.utcnow() + timedelta(hours=duration_hours)
        # Store pending unban in reminders json
        async with aiohttp.ClientSession() as session:
            reminders, sha = await github_read_json(session, FILE_REMINDERS)
            reminders.append(
                {
                    "type": "unban",
                    "guild_id": str(interaction.guild_id),
                    "user_id": str(user.id),
                    "unban_at": unban_time.isoformat(),
                }
            )
            await github_write_json(
                session, FILE_REMINDERS, reminders, sha, f"Schedule unban for {user.id}"
            )
        embed = discord.Embed(title="⏳ User Temp-Banned", color=0xDA3633)
        embed.add_field(name="User", value=str(user), inline=True)
        embed.add_field(name="Duration", value=f"{duration_hours} hours", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to ban that user.")


@bot.tree.command(name="purge", description="Bulk delete messages")
@app_commands.describe(
    amount="Number of messages to delete (max 100)",
    user="Only delete messages from this user (optional)",
)
@has_allowed_role()
async def purge_messages(
    interaction: discord.Interaction, amount: int = 10, user: discord.Member = None
):
    await interaction.response.defer(ephemeral=True)
    amount = min(amount, 100)

    def check(m):
        return (user is None) or (m.author == user)

    deleted = await interaction.channel.purge(limit=amount, check=check)
    await interaction.followup.send(
        embed=discord.Embed(
            title=f"🗑️ Deleted {len(deleted)} message(s)", color=0x2EA043
        ),
        ephemeral=True,
    )


@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.describe(seconds="Slowmode seconds (0 to disable)")
@has_allowed_role()
async def slowmode(interaction: discord.Interaction, seconds: int = 0):
    await interaction.response.defer()
    await interaction.channel.edit(slowmode_delay=seconds)
    msg = f"✅ Slowmode set to {seconds}s" if seconds > 0 else "✅ Slowmode disabled"
    await interaction.followup.send(embed=discord.Embed(title=msg, color=0x2EA043))


# ══════════════════════════════════════════════════════════════════════════════
# HONEYPOT SYSTEM
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="honeypot_set", description="Configure a honeypot channel (Admin only)"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    channel="Channel to set as honeypot",
    punishment="Action to take on trigger",
    dm_message="DM message to send before punishment (optional)",
)
@app_commands.choices(
    punishment=[
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="ban", value="ban"),
        app_commands.Choice(name="mute", value="mute"),
        app_commands.Choice(name="softban", value="softban"),
    ]
)
async def honeypot_set(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    punishment: app_commands.Choice[str],
    dm_message: str = "",
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        all_hp, sha = await github_read_json(session, FILE_HONEYPOT)
        if guild_id not in all_hp:
            all_hp[guild_id] = {}
        all_hp[guild_id][str(channel.id)] = {
            "punishment": punishment.value,
            "dm_message": dm_message
            or f"You triggered a honeypot channel and have been {punishment.value}ed.",
        }
        await github_write_json(
            session,
            FILE_HONEYPOT,
            all_hp,
            sha,
            f"Set honeypot channel {channel.id} for guild {guild_id}",
        )
    _invalidate_cache(str(interaction.guild_id))
    await interaction.followup.send(
        embed=discord.Embed(
            title=f"🍯 Honeypot Set",
            description=f"{channel.mention} → **{punishment.value}**",
            color=0x2EA043,
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="honeypot_remove", description="Remove a honeypot channel (Admin only)"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="Channel to remove from honeypot list")
async def honeypot_remove(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        all_hp, sha = await github_read_json(session, FILE_HONEYPOT)
        removed = all_hp.get(guild_id, {}).pop(str(channel.id), None)
        if removed:
            await github_write_json(
                session, FILE_HONEYPOT, all_hp, sha, f"Remove honeypot {channel.id}"
            )
            _invalidate_cache(str(interaction.guild_id))
            await interaction.followup.send(
                f"✅ Removed {channel.mention} from honeypot list.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ {channel.mention} is not a honeypot channel.", ephemeral=True
            )


@bot.tree.command(
    name="honeypot_list", description="List all honeypot channels (Admin only)"
)
@app_commands.default_permissions(administrator=True)
async def honeypot_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        all_hp, _ = await github_read_json(session, FILE_HONEYPOT)
    guild_hp = all_hp.get(guild_id, {})
    if not guild_hp:
        await interaction.followup.send(
            "No honeypot channels configured.", ephemeral=True
        )
        return
    embed = discord.Embed(title="🍯 Honeypot Channels", color=0xFFA500)
    for ch_id, cfg in guild_hp.items():
        embed.add_field(
            name=f"<#{ch_id}>",
            value=f"Punishment: **{cfg['punishment']}**",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── on_message: honeypot + automod ─────────────────────────────────────────────

# ── In-memory cache for on_message hot path (avoids GitHub API on every message) ─
_cfg_cache: dict = {}  # guild_id -> (cfg_dict, fetched_at_timestamp)
_hp_cache: dict = {}  # guild_id -> (hp_dict, fetched_at_timestamp)
_automod_cache: dict = {}  # guild_id -> (am_dict, fetched_at_timestamp)
_CACHE_TTL = 120  # seconds before re-fetching from GitHub

import time as _time


async def _cached_cfg(guild_id: str) -> dict:
    now = _time.monotonic()
    if guild_id in _cfg_cache:
        data, ts = _cfg_cache[guild_id]
        if now - ts < _CACHE_TTL:
            return data
    async with aiohttp.ClientSession() as session:
        data = await get_server_cfg(session, guild_id)
    _cfg_cache[guild_id] = (data, now)
    return data


async def _cached_hp(guild_id: str) -> dict:
    now = _time.monotonic()
    if guild_id in _hp_cache:
        data, ts = _hp_cache[guild_id]
        if now - ts < _CACHE_TTL:
            return data
    async with aiohttp.ClientSession() as session:
        all_hp, _ = await github_read_json(session, FILE_HONEYPOT)
    data = all_hp.get(guild_id, {})
    _hp_cache[guild_id] = (data, now)
    return data


async def _cached_automod(guild_id: str) -> dict:
    now = _time.monotonic()
    if guild_id in _automod_cache:
        data, ts = _automod_cache[guild_id]
        if now - ts < _CACHE_TTL:
            return data
    async with aiohttp.ClientSession() as session:
        all_am, _ = await github_read_json(session, FILE_AUTOMOD)
    data = {**DEFAULT_AUTOMOD, **all_am.get(guild_id, {})}
    _automod_cache[guild_id] = (data, now)
    return data


def _invalidate_cache(guild_id: str):
    """Call after any config write so next message re-fetches fresh data."""
    _cfg_cache.pop(guild_id, None)
    _hp_cache.pop(guild_id, None)
    _automod_cache.pop(guild_id, None)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    guild_id = str(message.guild.id)
    user = message.author
    channel_id = str(message.channel.id)

    # Use cached reads — no GitHub hit on every message
    guild_hp = await _cached_hp(guild_id)
    cfg = await _cached_cfg(guild_id)

    # ── Honeypot Check ─────────────────────────────────────────────────────
    if channel_id in guild_hp:
        hp_cfg = guild_hp[channel_id]
        punishment = hp_cfg["punishment"]
        dm_msg = hp_cfg.get("dm_message", "You triggered a honeypot.")

        # DM first before punishment
        try:
            await user.send(dm_msg)
        except Exception:
            pass

        # Apply punishment first so user can't keep posting while we sweep
        from datetime import datetime, timedelta

        try:
            if punishment == "kick":
                await user.kick(reason="Honeypot triggered")
            elif punishment == "ban":
                await user.ban(reason="Honeypot triggered", delete_message_days=1)
            elif punishment == "softban":
                await user.ban(
                    reason="Honeypot triggered (softban)", delete_message_days=7
                )
                await message.guild.unban(user, reason="Softban — immediate unban")
            elif punishment == "mute":
                await user.timeout(
                    discord.utils.utcnow() + timedelta(hours=24),
                    reason="Honeypot triggered",
                )
        except Exception:
            pass

        # Sweep messages — rate-limit safe: one channel at a time with sleep
        cutoff = discord.utils.utcnow() - timedelta(hours=24)
        for ch in message.guild.text_channels:
            try:
                to_delete = [
                    m
                    async for m in ch.history(limit=100, after=cutoff)
                    if m.author.id == user.id
                ]
                if to_delete:
                    # delete_messages only works for ≤100 messages, bulk only for <14 days
                    await ch.delete_messages(to_delete)
                    await asyncio.sleep(
                        0.5
                    )  # stay well within rate limits between channels
            except discord.Forbidden:
                pass
            except Exception:
                pass

        log_embed = discord.Embed(title="🍯 Honeypot Triggered", color=0xDA3633)
        log_embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
        log_embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        log_embed.add_field(name="Punishment", value=punishment, inline=True)
        await _log_mod_action(message.guild, cfg, log_embed)
        async with aiohttp.ClientSession() as session:
            await _add_mod_case(
                session,
                guild_id,
                {
                    "type": f"honeypot_{punishment}",
                    "user": str(user.id),
                    "mod": "AUTO",
                    "reason": "Honeypot triggered",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        await bot.process_commands(message)
        return

    # ── AutoMod ────────────────────────────────────────────────────────────
    am = await _cached_automod(guild_id)
    content = message.content

    async def _automod_action(action: str, reason: str):
        if action == "delete":
            try:
                await message.delete()
            except Exception:
                pass
        elif action == "mute":
            try:
                await user.timeout(
                    discord.utils.utcnow()
                    + __import__("datetime").timedelta(minutes=10),
                    reason=reason,
                )
            except Exception:
                pass
        log_embed = discord.Embed(title=f"🤖 AutoMod: {reason}", color=0xFFA500)
        log_embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
        log_embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        log_embed.add_field(name="Action", value=action, inline=True)
        await _log_mod_action(message.guild, cfg, log_embed)

    # Invite links
    if am["invite_links"]["enabled"] and re.search(
        r"discord\.gg/\S+|discord\.com/invite/\S+", content, re.I
    ):
        await _automod_action(am["invite_links"]["action"], "Invite Link")

    # Caps filter
    elif am["caps_filter"]["enabled"] and len(content) > 8:
        caps_pct = sum(1 for c in content if c.isupper()) / max(len(content), 1) * 100
        if caps_pct >= am["caps_filter"]["threshold"]:
            await _automod_action(am["caps_filter"]["action"], "Excessive Caps")

    # Mention spam
    elif (
        am["mention_spam"]["enabled"]
        and len(message.mentions) >= am["mention_spam"]["max_mentions"]
    ):
        await _automod_action(am["mention_spam"]["action"], "Mention Spam")

    # Blacklist
    elif am["blacklist"]["enabled"]:
        lower_content = content.lower()
        if any(w in lower_content for w in am["blacklist"]["words"]):
            await _automod_action(am["blacklist"]["action"], "Blacklisted Word")

    # URL filter
    elif am["url_filter"]["enabled"]:
        urls = re.findall(r"https?://\S+", content)
        whitelist = am["url_filter"].get("whitelist", [])
        if urls and not all(any(w in u for w in whitelist) for u in urls):
            await _automod_action(am["url_filter"]["action"], "Blocked URL")

    # Spam detection
    elif am["spam"]["enabled"]:
        import time

        now_ts = time.time()
        key = f"{guild_id}:{user.id}"
        if guild_id not in _spam_tracker:
            _spam_tracker[guild_id] = {}
        timestamps = _spam_tracker[guild_id].get(str(user.id), [])
        interval = am["spam"]["interval_seconds"]
        timestamps = [t for t in timestamps if now_ts - t < interval]
        timestamps.append(now_ts)
        _spam_tracker[guild_id][str(user.id)] = timestamps
        if len(timestamps) >= am["spam"]["max_messages"]:
            await _automod_action(am["spam"]["action"], "Spam")

    await bot.process_commands(message)


# ══════════════════════════════════════════════════════════════════════════════
# AUTOMOD CONFIG COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="automod", description="Configure automod rules (Admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    rule="Rule to configure",
    enabled="Enable or disable",
    action="Action to take",
    threshold="Numeric threshold (varies by rule)",
    words="Comma-separated words for blacklist",
    whitelist_domains="Comma-separated allowed domains for URL filter",
)
@app_commands.choices(
    rule=[
        app_commands.Choice(name="spam", value="spam"),
        app_commands.Choice(name="invite_links", value="invite_links"),
        app_commands.Choice(name="caps_filter", value="caps_filter"),
        app_commands.Choice(name="mention_spam", value="mention_spam"),
        app_commands.Choice(name="blacklist", value="blacklist"),
        app_commands.Choice(name="url_filter", value="url_filter"),
    ],
    action=[
        app_commands.Choice(name="delete", value="delete"),
        app_commands.Choice(name="mute", value="mute"),
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="ban", value="ban"),
    ],
)
async def automod_config(
    interaction: discord.Interaction,
    rule: app_commands.Choice[str],
    enabled: bool,
    action: app_commands.Choice[str] = None,
    threshold: int = None,
    words: str = None,
    whitelist_domains: str = None,
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        all_am, sha = await github_read_json(session, FILE_AUTOMOD)
        am = {**DEFAULT_AUTOMOD, **all_am.get(guild_id, {})}
        rule_cfg = am[rule.value]
        rule_cfg["enabled"] = enabled
        if action:
            rule_cfg["action"] = action.value
        if threshold is not None:
            if rule.value == "spam":
                rule_cfg["max_messages"] = threshold
            elif rule.value == "caps_filter":
                rule_cfg["threshold"] = threshold
            elif rule.value == "mention_spam":
                rule_cfg["max_mentions"] = threshold
        if words and rule.value == "blacklist":
            rule_cfg["words"] = [w.strip().lower() for w in words.split(",")]
        if whitelist_domains and rule.value == "url_filter":
            rule_cfg["whitelist"] = [d.strip() for d in whitelist_domains.split(",")]
        am[rule.value] = rule_cfg
        all_am[guild_id] = am
        await github_write_json(
            session, FILE_AUTOMOD, all_am, sha, f"Update automod for guild {guild_id}"
        )
    _invalidate_cache(guild_id)
    embed = discord.Embed(title=f"🤖 AutoMod: `{rule.value}` updated", color=0x2EA043)
    embed.add_field(name="Enabled", value=str(enabled), inline=True)
    embed.add_field(name="Action", value=rule_cfg.get("action", "—"), inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOGGING EVENTS
# ══════════════════════════════════════════════════════════════════════════════


@bot.event
async def on_member_join(member: discord.Member):
    guild_id = str(member.guild.id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
    ch_id = cfg.get("join_leave_channel")
    if not ch_id:
        return
    ch = member.guild.get_channel(ch_id)
    if ch:
        embed = discord.Embed(title="📥 Member Joined", color=0x2EA043)
        embed.add_field(name="User", value=f"{member.mention} ({member})", inline=True)
        embed.add_field(
            name="Account Created",
            value=member.created_at.strftime("%Y-%m-%d"),
            inline=True,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await ch.send(embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    guild_id = str(member.guild.id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
    ch_id = cfg.get("join_leave_channel")
    if not ch_id:
        return
    ch = member.guild.get_channel(ch_id)
    if ch:
        embed = discord.Embed(title="📤 Member Left", color=0xDA3633)
        embed.add_field(name="User", value=f"{member} ({member.id})", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ch.send(embed=embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    guild_id = str(before.guild.id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
    ch_id = cfg.get("mod_log_channel")
    if not ch_id:
        return
    ch = before.guild.get_channel(ch_id)
    if ch:
        embed = discord.Embed(title="✏️ Message Edited", color=0x0066FF)
        embed.add_field(name="Author", value=f"{before.author.mention}", inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Before", value=before.content[:512] or "—", inline=False)
        embed.add_field(name="After", value=after.content[:512] or "—", inline=False)
        embed.add_field(
            name="Jump", value=f"[Go to message]({after.jump_url})", inline=False
        )
        await ch.send(embed=embed)


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    guild_id = str(message.guild.id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
    ch_id = cfg.get("mod_log_channel")
    if not ch_id:
        return
    ch = message.guild.get_channel(ch_id)
    if ch:
        embed = discord.Embed(title="🗑️ Message Deleted", color=0xFFA500)
        embed.add_field(name="Author", value=f"{message.author.mention}", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(
            name="Content", value=message.content[:512] or "—", inline=False
        )
        await ch.send(embed=embed)


@bot.event
async def on_voice_state_update(
    member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
):
    if before.channel == after.channel:
        return
    guild_id = str(member.guild.id)
    async with aiohttp.ClientSession() as session:
        cfg = await get_server_cfg(session, guild_id)
    ch_id = cfg.get("mod_log_channel")
    if not ch_id:
        return
    ch = member.guild.get_channel(ch_id)
    if ch:
        if before.channel is None:
            desc = f"Joined **{after.channel.name}**"
            color = 0x2EA043
        elif after.channel is None:
            desc = f"Left **{before.channel.name}**"
            color = 0xDA3633
        else:
            desc = f"Moved from **{before.channel.name}** → **{after.channel.name}**"
            color = 0x0066FF
        embed = discord.Embed(
            title="🎙️ Voice State", description=f"{member.mention} {desc}", color=color
        )
        await ch.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# ANILIST INTEGRATION (SLASH)
# ══════════════════════════════════════════════════════════════════════════════


async def _anilist_query(
    session: aiohttp.ClientSession, query: str, variables: dict
) -> dict:
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return {}
        return (await r.json()).get("data", {})


ANILIST_SEARCH_QUERY = """
query ($search: String, $type: MediaType) {
  Media(search: $search, type: $type, sort: POPULARITY_DESC) {
    id title { romaji english native }
    coverImage { large }
    averageScore status episodes chapters
    genres description(asHtml: false)
    siteUrl startDate { year month day }
  }
}
"""
ANILIST_CHARACTER_QUERY = """
query ($search: String) {
  Character(search: $search) {
    id name { full native }
    image { large }
    description(asHtml: false)
    siteUrl
    media(perPage: 3) { nodes { title { romaji } siteUrl } }
  }
}
"""
ANILIST_STAFF_QUERY = """
query ($search: String) {
  Staff(search: $search) {
    id name { full native }
    image { large }
    description(asHtml: false)
    siteUrl primaryOccupations
  }
}
"""
ANILIST_SCHEDULE_QUERY = """
query ($page: Int) {
  Page(page: $page, perPage: 10) {
    airingSchedules(notYetAired: true, sort: TIME) {
      airingAt episode
      media { title { romaji } siteUrl }
    }
  }
}
"""
ANILIST_SEASON_QUERY = """
query ($season: MediaSeason, $year: Int) {
  Page(perPage: 10) {
    media(season: $season, seasonYear: $year, sort: POPULARITY_DESC, type: ANIME) {
      title { romaji }
      averageScore episodes status
      genres siteUrl
      coverImage { large }
    }
  }
}
"""
ANILIST_USER_QUERY = """
query ($name: String) {
  User(name: $name) {
    id name avatar { large }
    siteUrl
    statistics { anime { count meanScore minutesWatched } manga { count chaptersRead } }
  }
}
"""


@bot.tree.command(name="anime_search", description="Search for an anime on AniList")
@app_commands.describe(title="Anime title to search")
async def anime_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(
            session, ANILIST_SEARCH_QUERY, {"search": title, "type": "ANIME"}
        )
    media = data.get("Media")
    if not media:
        await interaction.followup.send("❌ Anime not found.")
        return
    t = media["title"]
    embed = discord.Embed(
        title=t.get("english") or t.get("romaji") or "Unknown",
        url=media.get("siteUrl", ""),
        color=0x0066FF,
    )
    embed.add_field(name="Romaji", value=t.get("romaji", "—"), inline=True)
    embed.add_field(
        name="Score", value=f"{media.get('averageScore','N/A')}/100", inline=True
    )
    embed.add_field(name="Status", value=media.get("status", "—"), inline=True)
    embed.add_field(name="Episodes", value=str(media.get("episodes", "?")), inline=True)
    embed.add_field(
        name="Genres", value=", ".join(media.get("genres", [])[:4]) or "—", inline=True
    )
    desc = (media.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Description", value=desc, inline=False)
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="manga_search", description="Search for a manga on AniList")
@app_commands.describe(title="Manga title to search")
async def manga_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(
            session, ANILIST_SEARCH_QUERY, {"search": title, "type": "MANGA"}
        )
    media = data.get("Media")
    if not media:
        await interaction.followup.send("❌ Manga not found.")
        return
    t = media["title"]
    embed = discord.Embed(
        title=t.get("english") or t.get("romaji") or "Unknown",
        url=media.get("siteUrl", ""),
        color=0xFF6B6B,
    )
    embed.add_field(
        name="Score", value=f"{media.get('averageScore','N/A')}/100", inline=True
    )
    embed.add_field(name="Chapters", value=str(media.get("chapters", "?")), inline=True)
    embed.add_field(name="Status", value=media.get("status", "—"), inline=True)
    embed.add_field(
        name="Genres", value=", ".join(media.get("genres", [])[:4]) or "—", inline=True
    )
    desc = (media.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Description", value=desc, inline=False)
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="anilist_profile", description="View an AniList user profile")
@app_commands.describe(username="AniList username")
async def anilist_profile(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_USER_QUERY, {"name": username})
    user = data.get("User")
    if not user:
        await interaction.followup.send("❌ AniList user not found.")
        return
    stats = user.get("statistics", {})
    a, m = stats.get("anime", {}), stats.get("manga", {})
    embed = discord.Embed(
        title=user["name"], url=user.get("siteUrl", ""), color=0x0066FF
    )
    embed.add_field(name="Anime Watched", value=str(a.get("count", 0)), inline=True)
    embed.add_field(name="Mean Score", value=str(a.get("meanScore", "—")), inline=True)
    embed.add_field(
        name="Days Watched",
        value=f"{round(a.get('minutesWatched',0)/1440,1)}d",
        inline=True,
    )
    embed.add_field(name="Manga Read", value=str(m.get("count", 0)), inline=True)
    embed.add_field(
        name="Chapters Read", value=str(m.get("chaptersRead", 0)), inline=True
    )
    if user.get("avatar", {}).get("large"):
        embed.set_thumbnail(url=user["avatar"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="character_search",
    description="Search for an anime/manga character on AniList",
)
@app_commands.describe(name="Character name")
async def character_search(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_CHARACTER_QUERY, {"search": name})
    char = data.get("Character")
    if not char:
        await interaction.followup.send("❌ Character not found.")
        return
    cn = char["name"]
    embed = discord.Embed(
        title=cn.get("full", "—"), url=char.get("siteUrl", ""), color=0x0066FF
    )
    if cn.get("native"):
        embed.add_field(name="Native", value=cn["native"], inline=True)
    appeared_in = [n["title"]["romaji"] for n in char.get("media", {}).get("nodes", [])]
    if appeared_in:
        embed.add_field(name="Appears In", value="\n".join(appeared_in), inline=False)
    desc = (char.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Description", value=desc, inline=False)
    if char.get("image", {}).get("large"):
        embed.set_thumbnail(url=char["image"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="staff_search", description="Search for anime staff on AniList")
@app_commands.describe(name="Staff member name")
async def staff_search(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_STAFF_QUERY, {"search": name})
    staff = data.get("Staff")
    if not staff:
        await interaction.followup.send("❌ Staff not found.")
        return
    sn = staff["name"]
    embed = discord.Embed(
        title=sn.get("full", "—"), url=staff.get("siteUrl", ""), color=0x0066FF
    )
    if sn.get("native"):
        embed.add_field(name="Native", value=sn["native"], inline=True)
    if staff.get("primaryOccupations"):
        embed.add_field(
            name="Occupations",
            value=", ".join(staff["primaryOccupations"]),
            inline=True,
        )
    desc = (staff.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Bio", value=desc, inline=False)
    if staff.get("image", {}).get("large"):
        embed.set_thumbnail(url=staff["image"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="airing_schedule", description="View upcoming airing anime schedule"
)
async def airing_schedule(interaction: discord.Interaction):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_SCHEDULE_QUERY, {"page": 1})
    schedules = data.get("Page", {}).get("airingSchedules", [])
    if not schedules:
        await interaction.followup.send("❌ No upcoming episodes found.")
        return
    from datetime import datetime, timezone

    embed = discord.Embed(title="📅 Upcoming Airing Schedule", color=0x0066FF)
    for s in schedules[:10]:
        dt = datetime.fromtimestamp(s["airingAt"], tz=timezone.utc)
        media = s.get("media", {})
        title = media.get("title", {}).get("romaji", "Unknown")
        embed.add_field(
            name=f"Ep {s['episode']} — {title}",
            value=f"<t:{s['airingAt']}:R>",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="seasonal_anime", description="View seasonal anime list")
@app_commands.describe(
    season="Season (WINTER/SPRING/SUMMER/FALL)", year="Year (e.g. 2025)"
)
@app_commands.choices(
    season=[
        app_commands.Choice(name="Winter", value="WINTER"),
        app_commands.Choice(name="Spring", value="SPRING"),
        app_commands.Choice(name="Summer", value="SUMMER"),
        app_commands.Choice(name="Fall", value="FALL"),
    ]
)
async def seasonal_anime(
    interaction: discord.Interaction, season: app_commands.Choice[str], year: int
):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(
            session, ANILIST_SEASON_QUERY, {"season": season.value, "year": year}
        )
    shows = data.get("Page", {}).get("media", [])
    if not shows:
        await interaction.followup.send("❌ No anime found for that season.")
        return
    embed = discord.Embed(title=f"🌸 {season.name} {year} Anime", color=0x0066FF)
    for s in shows:
        t = s["title"]["romaji"]
        score = s.get("averageScore", "?")
        eps = s.get("episodes", "?")
        embed.add_field(name=t, value=f"Score: {score}/100 | Eps: {eps}", inline=False)
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="poll", description="Create a poll")
@app_commands.describe(
    question="Poll question", options="Comma-separated options (max 9)"
)
async def create_poll(interaction: discord.Interaction, question: str, options: str):
    await interaction.response.defer()
    opts = [o.strip() for o in options.split(",") if o.strip()][:9]
    if len(opts) < 2:
        await interaction.followup.send(
            "❌ Provide at least 2 options.", ephemeral=True
        )
        return
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    embed = discord.Embed(title=f"📊 {question}", color=0x0066FF)
    desc = "\n".join(f"{number_emojis[i]} {opt}" for i, opt in enumerate(opts))
    embed.description = desc
    embed.set_footer(text=f"Poll by {interaction.user.display_name}")
    msg = await interaction.followup.send(embed=embed)
    for i in range(len(opts)):
        await msg.add_reaction(number_emojis[i])


@bot.tree.command(name="remind", description="Set a reminder")
@app_commands.describe(
    minutes="Remind you in how many minutes", message="What to remind you about"
)
async def remind(interaction: discord.Interaction, minutes: int, message: str):
    await interaction.response.defer(ephemeral=True)
    from datetime import datetime, timedelta

    remind_at = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
    async with aiohttp.ClientSession() as session:
        reminders, sha = await github_read_json(session, FILE_REMINDERS)
        reminders.append(
            {
                "type": "remind",
                "user_id": str(interaction.user.id),
                "channel_id": str(interaction.channel_id),
                "message": message,
                "remind_at": remind_at,
            }
        )
        await github_write_json(session, FILE_REMINDERS, reminders, sha, "Add reminder")
    await interaction.followup.send(
        f"✅ I'll remind you in **{minutes}** minute(s): *{message}*", ephemeral=True
    )


@bot.tree.command(name="userinfo", description="View information about a user")
@app_commands.describe(user="User to look up (defaults to yourself)")
async def userinfo(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()
    target = user or interaction.user
    roles = [r.mention for r in target.roles if r.name != "@everyone"][-10:]
    embed = discord.Embed(title=f"👤 {target}", color=target.color)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="ID", value=str(target.id), inline=True)
    embed.add_field(name="Nickname", value=target.nick or "None", inline=True)
    embed.add_field(
        name="Joined Server", value=target.joined_at.strftime("%Y-%m-%d"), inline=True
    )
    embed.add_field(
        name="Account Created",
        value=target.created_at.strftime("%Y-%m-%d"),
        inline=True,
    )
    embed.add_field(name="Roles", value=" ".join(roles) or "None", inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="serverinfo", description="View server information")
async def serverinfo(interaction: discord.Interaction):
    await interaction.response.defer()
    g = interaction.guild
    embed = discord.Embed(title=g.name, color=0x0066FF)
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Owner", value=str(g.owner), inline=True)
    embed.add_field(name="Members", value=str(g.member_count), inline=True)
    embed.add_field(name="Channels", value=str(len(g.channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(g.roles)), inline=True)
    embed.add_field(
        name="Created", value=g.created_at.strftime("%Y-%m-%d"), inline=True
    )
    embed.add_field(name="Boost Tier", value=str(g.premium_tier), inline=True)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="avatar", description="Get a user's avatar")
@app_commands.describe(user="User whose avatar to fetch")
async def avatar(interaction: discord.Interaction, user: discord.User = None):
    await interaction.response.defer()
    target = user or interaction.user
    embed = discord.Embed(title=f"🖼️ {target.display_name}'s Avatar", color=0x0066FF)
    embed.set_image(url=target.display_avatar.url)
    await interaction.followup.send(embed=embed)


# ── Background task: process reminders and tempbans ────────────────────────────


@tasks.loop(minutes=1)
async def process_reminders():
    from datetime import datetime

    now = datetime.utcnow()
    async with aiohttp.ClientSession() as session:
        reminders, sha = await github_read_json(session, FILE_REMINDERS)
        remaining = []
        changed = False
        for r in reminders:
            remind_at = datetime.fromisoformat(r["remind_at"])
            if now >= remind_at:
                changed = True
                if r["type"] == "remind":
                    ch = bot.get_channel(int(r["channel_id"]))
                    if ch:
                        try:
                            await ch.send(
                                f"<@{r['user_id']}> ⏰ Reminder: **{r['message']}**"
                            )
                        except Exception:
                            pass
                elif r["type"] == "unban":
                    guild = bot.get_guild(int(r["guild_id"]))
                    if guild:
                        try:
                            user = await bot.fetch_user(int(r["user_id"]))
                            await guild.unban(user, reason="Tempban expired")
                        except Exception:
                            pass
            else:
                remaining.append(r)
        if changed:
            await github_write_json(
                session, FILE_REMINDERS, remaining, sha, "Process reminders"
            )


async def main():
    await start_health_server()
    if PROXY_URL:
        print(f"✅ Using proxy: {_PROXY_HOST}:{_PROXY_PORT}")
        from discord.http import HTTPClient
        bot.http.proxy = PROXY_URL
    else:
        print("⚠️ No proxy configured, connecting directly")
    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
