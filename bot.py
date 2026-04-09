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
from cryptography.fernet import Fernet

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
SIMKL_API = "https://api.simkl.com"
SIMKL_CLIENT_ID = os.environ.get("SIMKL_CLIENT_ID")
SIMKL_ENCRYPT_KEY = os.environ.get("SIMKL_ENCRYPT_KEY")  # Fernet key — run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# ── GitHub JSON file paths ──────────────────────────────────────────────────────
FILE_ANIME = "underrated_anime.json"
FILE_MANGA = "underrated_manga.json"
FILE_SHOWS = "underrated_shows.json"
FILE_MOVIES = "underrated_movies.json"
FILE_USERS = "users.json"
FILE_TIMEZONES = "timezones.json"
FILE_PREFIXES = "prefixes.json"
FILE_SERVER_CFG = "server_config.json"  # stores allowed_roles per server
FILE_VOTES = "votes.json"               # upvote/downvote records per media item


DEFAULT_PREFIXES = ["?"]

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


async def get_allowed_roles(guild_id: str) -> list:
    """Return list of allowed role IDs for this guild."""
    async with aiohttp.ClientSession() as session:
        all_cfg, _ = await github_read_json(session, FILE_SERVER_CFG)
    return all_cfg.get(guild_id, {}).get("allowed_roles", [])


def has_allowed_role():
    """Check if user has an allowed role OR is an administrator."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        allowed = await get_allowed_roles(str(interaction.guild_id))
        user_role_ids = {role.id for role in interaction.user.roles}
        if allowed and user_role_ids & set(allowed):
            return True
        await interaction.response.send_message(
            "❌ You don't have a role allowed to use this command.", ephemeral=True
        )
        return False

    return app_commands.check(predicate)


def has_allowed_role_prefix():
    """Check if user has an allowed role OR is an administrator (prefix commands)."""

    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        allowed = await get_allowed_roles(str(ctx.guild.id))
        user_role_ids = {role.id for role in ctx.author.roles}
        if allowed and user_role_ids & set(allowed):
            return True
        await ctx.send("❌ You don't have a role allowed to use this command.")
        return False

    return commands.check(predicate)


# ── Intents & Bot ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True  # required for prefix commands
intents.members = True

# In-memory prefix cache (loaded on startup)
_prefix_cache = ["?"]


async def get_prefix(bot, message):
    return _prefix_cache


bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# ── /config_role ───────────────────────────────────────────────────────────────


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
        app_commands.Choice(name="list", value="list"),
    ]
)
async def config_role(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    role: discord.Role = None,
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        all_cfg, sha = await github_read_json(session, FILE_SERVER_CFG)
        cfg = all_cfg.get(guild_id, {})
        roles = cfg.get("allowed_roles", [])

        if action.value == "list":
            if not roles:
                msg = "No allowed roles configured."
            else:
                msg = "**Allowed roles:**\n" + "\n".join(f"<@&{r}>" for r in roles)
            await interaction.followup.send(msg, ephemeral=True)
            return

        if not role:
            await interaction.followup.send("❌ Please provide a role.", ephemeral=True)
            return

        if action.value == "add":
            if role.id in roles:
                await interaction.followup.send(f"⚠️ {role.mention} is already allowed.", ephemeral=True)
                return
            roles.append(role.id)
            msg = f"✅ Added {role.mention} to allowed roles."
        else:
            if role.id not in roles:
                await interaction.followup.send(f"❌ {role.mention} is not in allowed roles.", ephemeral=True)
                return
            roles.remove(role.id)
            msg = f"✅ Removed {role.mention} from allowed roles."

        cfg["allowed_roles"] = roles
        all_cfg[guild_id] = cfg
        await github_write_json(session, FILE_SERVER_CFG, all_cfg, sha, f"Update allowed_roles for guild {guild_id}")

    await interaction.followup.send(msg, ephemeral=True)



# ── Health check server (keeps Render awake) ───────────────────────────────────


API_SECRET = os.environ.get("API_SECRET")  # set this in Render env vars


async def health(request):
    return web.Response(text="✅ Bot is running!")


def _check_auth(request):
    """Return True if the request carries a valid API_SECRET."""
    if not API_SECRET:
        return True  # no secret configured → open (not recommended for prod)
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET}"


async def _api_add_media(request, media_type: str):
    """Shared handler for POST /api/add_anime and POST /api/add_manga."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    anilist_id = body.get("anilist_id")
    mal_id = body.get("mal_id")             # optional — falls back to AniList's idMal
    anilist_user_id = body.get("anilist_user_id")   # optional
    anilist_username = (body.get("anilist_username") or "").strip() or None
    mal_user_id = body.get("mal_user_id")           # optional
    mal_username = (body.get("mal_username") or "").strip() or None
    author = (body.get("author") or "").strip() or None  # optional — falls back to anilist/mal username
    reason = (body.get("reason") or "").strip()

    # Required fields
    missing = [k for k, v in [
        ("anilist_id", anilist_id),
        ("reason", reason),
    ] if not v]
    if missing:
        return web.json_response({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)

    if not anilist_user_id and not mal_user_id:
        return web.json_response({"error": "Provide at least one of: anilist_user_id, mal_user_id"}, status=400)

    if not isinstance(anilist_id, int):
        return web.json_response({"error": "anilist_id must be an integer"}, status=400)

    async with aiohttp.ClientSession() as session:
        media = await fetch_anilist(session, anilist_id, media_type)
        if not media:
            return web.json_response(
                {"error": f"Could not find {media_type.lower()} with anilist_id={anilist_id} on AniList"},
                status=404,
            )

        titles = media["title"]
        title = titles.get("english") or titles.get("romaji") or titles.get("native") or "Unknown"
        resolved_mal_id = mal_id if mal_id is not None else media.get("idMal")
        score = media.get("averageScore") or "N/A"
        type_path = "anime" if media_type == "ANIME" else "manga"
        anilist_url = f"https://anilist.co/{type_path}/{anilist_id}"
        mal_url = f"https://myanimelist.net/{type_path}/{resolved_mal_id}" if resolved_mal_id else "N/A"

        # Try to find this user's full profile from users.json for the snapshot
        users_data, _ = await github_read_json(session, FILE_USERS)
        matched_profile = None
        for _discord_id, p in users_data.items():
            if anilist_user_id and p.get("anilist_user_id") == anilist_user_id:
                matched_profile = p
                break
            if mal_user_id and p.get("mal_user_id") == mal_user_id:
                matched_profile = p
                break

        if matched_profile:
            user_snapshot = _build_user_snapshot(matched_profile)
        else:
            # API caller not in users.json — build a minimal snapshot from request body
            user_snapshot = {
                "anilist": {
                    "id": anilist_user_id,
                    "username": anilist_username,
                    "avatar": None,
                },
                "mal": {
                    "id": mal_user_id,
                    "username": mal_username,
                    "avatar": None,
                },
            }

        # Resolve author: use provided value, fall back to anilist username → mal username → "Unknown"
        resolved_author = (
            author
            or user_snapshot.get("anilist", {}).get("username")
            or user_snapshot.get("mal", {}).get("username")
            or "Unknown"
        )

        entry = {
            "anilist_id": anilist_id,
            "mal_id": resolved_mal_id,
            "title": title,
            "author": resolved_author,
            "reason": reason,
            "user": user_snapshot,
            "poster": media.get("coverImage", {}).get("large", ""),
            "score": score,
            "nsfw": bool(media.get("isAdult") or False),
        }

        filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA
        entries, sha = await github_read_json(session, filepath)

        if any(e.get("anilist_id") == anilist_id for e in entries):
            return web.json_response(
                {"error": f"{title} is already in the list", "title": title},
                status=409,
            )

        entries.append(entry)
        ok = await github_write_json(
            session,
            filepath,
            entries,
            sha,
            f"feat: add {title} to underrated {media_type.lower()}s by {author} (API)",
        )

    if ok:
        return web.json_response({"success": True, "entry": entry}, status=201)
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_add_anime(request):
    return await _api_add_media(request, "ANIME")


async def api_add_manga(request):
    return await _api_add_media(request, "MANGA")


async def _api_add_simkl(request, media_type: str):
    """Shared handler for POST /api/add_show and POST /api/add_movie."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    simkl_id = body.get("simkl_id")
    reason = (body.get("reason") or "").strip()
    author = (body.get("author") or "").strip() or None

    missing = [k for k, v in [("simkl_id", simkl_id), ("reason", reason)] if not v]
    if missing:
        return web.json_response({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)

    if not isinstance(simkl_id, int):
        return web.json_response({"error": "simkl_id must be an integer"}, status=400)

    if not SIMKL_CLIENT_ID:
        return web.json_response({"error": "SIMKL_CLIENT_ID not configured on server"}, status=500)

    # Fetch from Simkl
    if media_type == "show":
        media = await _simkl_fetch_show(simkl_id)
    else:
        media = await _simkl_fetch_movie(simkl_id)

    if not media:
        return web.json_response(
            {"error": f"Could not find {media_type} with simkl_id={simkl_id} on Simkl"},
            status=404,
        )

    title = media.get("title") or media.get("en_title") or f"Simkl ID {simkl_id}"
    poster_url = _simkl_poster(media)
    score = media.get("ratings", {}).get("simkl", {}).get("rating") or "N/A"
    genres = ", ".join(media.get("genres", [])[:4]) or "N/A"
    year = media.get("year") or ""
    _adult_certs = {"NC-17", "X", "TV-MA", "R18", "18+", "AO"}
    certification = (media.get("certification") or "").upper().strip()
    nsfw = certification in _adult_certs
    simkl_url = f"https://simkl.com/{media_type}s/{simkl_id}"

    # Try to match a user by simkl_username from request
    simkl_username = (body.get("simkl_username") or "").strip() or None
    async with aiohttp.ClientSession() as session:
        users_data, _ = await github_read_json(session, FILE_USERS)

    matched_profile = None
    if simkl_username:
        for _discord_id, p in users_data.items():
            if p.get("simkl_username", "").lower() == simkl_username.lower():
                matched_profile = p
                break

    if matched_profile:
        user_snapshot = _build_user_snapshot(matched_profile)
        resolved_author = author or matched_profile.get("author_name") or simkl_username or "Unknown"
    else:
        user_snapshot = {"simkl": {"username": simkl_username}}
        resolved_author = author or simkl_username or "Unknown"

    entry = {
        "simkl_id": simkl_id,
        "title": title,
        "year": year,
        "author": resolved_author,
        "reason": reason,
        "user": user_snapshot,
        "poster": poster_url or "",
        "score": score,
        "genres": genres,
        "simkl_url": simkl_url,
        "nsfw": nsfw,
    }

    filepath = FILE_SHOWS if media_type == "show" else FILE_MOVIES

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
        if any(e.get("simkl_id") == simkl_id for e in entries):
            return web.json_response(
                {"error": f"{title} is already in the list", "title": title},
                status=409,
            )
        entries.append(entry)
        ok = await github_write_json(
            session,
            filepath,
            entries,
            sha,
            f"feat: add {title} to underrated {media_type}s by {resolved_author} (API)",
        )

    if ok:
        return web.json_response({"success": True, "entry": entry}, status=201)
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_add_show(request):
    return await _api_add_simkl(request, "show")


async def api_add_movie(request):
    return await _api_add_simkl(request, "movie")


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    # ── media add ──────────────────────────────────────────────────────────────
    app.router.add_post("/api/add_anime", api_add_anime)
    app.router.add_post("/api/add_manga", api_add_manga)
    app.router.add_post("/api/add_show", api_add_show)
    app.router.add_post("/api/add_movie", api_add_movie)
    # ── voting ─────────────────────────────────────────────────────────────────
    app.router.add_post("/api/vote/anime/{anilist_id}", api_vote_anime)
    app.router.add_post("/api/vote/manga/{anilist_id}", api_vote_manga)
    app.router.add_post("/api/vote/show/{anilist_id}", api_vote_show)
    app.router.add_post("/api/vote/movie/{anilist_id}", api_vote_movie)
    app.router.add_get("/api/votes/anime/{anilist_id}", api_get_votes_anime)
    app.router.add_get("/api/votes/manga/{anilist_id}", api_get_votes_manga)
    app.router.add_get("/api/votes/show/{anilist_id}", api_get_votes_show)
    app.router.add_get("/api/votes/movie/{anilist_id}", api_get_votes_movie)
    app.router.add_get("/api/votes/leaderboard", api_leaderboard)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Health server running on port {PORT}")


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
                FILE_VOTES,
            )
            list_files = (FILE_ANIME, FILE_MANGA, FILE_SHOWS, FILE_MOVIES)
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
        id idMal
        title { romaji english native }
        coverImage { large }
        bannerImage
        averageScore
        genres
        isAdult
        status
        format
        episodes
        duration
        chapters
        volumes
        season
        seasonYear
        description(asHtml: false)
        studios(isMain: true) { nodes { name } }
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


async def fetch_anilist_batch(session: aiohttp.ClientSession, ids: list[int], media_type: str) -> dict[int, dict]:
    """Fetch up to 50 media items in one AniList request. Returns {id: media_dict}."""
    if not ids:
        return {}
    query = """
    query ($ids: [Int], $type: MediaType) {
      Page(perPage: 50) {
        media(id_in: $ids, type: $type) {
          id coverImage { large } averageScore isAdult
        }
      }
    }
    """
    try:
        async with session.post(
            ANILIST_API,
            json={"query": query, "variables": {"ids": ids, "type": media_type}},
            headers={"Content-Type": "application/json"},
        ) as r:
            if r.status != 200:
                return {}
            data = await r.json()
        results = data.get("data", {}).get("Page", {}).get("media", [])
        return {m["id"]: m for m in results}
    except Exception:
        return {}


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


def _build_user_snapshot(profile: dict) -> dict:
    return {
        "discord": {
            "id": profile.get("discord_id"),
            "username": profile.get("discord_username"),
            "avatar": profile.get("discord_avatar"),
        },
        "anilist": {
            "id": profile.get("anilist_user_id"),
            "username": profile.get("anilist_username"),
            "avatar": profile.get("anilist_avatar"),
        },
        "mal": {
            "id": profile.get("mal_user_id"),
            "username": profile.get("mal_username"),
            "avatar": profile.get("mal_avatar"),
        },
        "simkl": {
            "username": profile.get("simkl_username"),
            "id": profile.get("simkl_user_id"),
            "avatar": profile.get("simkl_avatar"),
        },
    }


# ── AniList autocomplete search helpers ────────────────────────────────────────


async def _anilist_search(query_str: str, media_type: str) -> list:
    """Search AniList for anime/manga, returns list of (id, idMal, display_title)."""
    query = """
    query ($search: String, $type: MediaType) {
      Page(perPage: 25) {
        media(search: $search, type: $type, sort: POPULARITY_DESC) {
          id idMal title { romaji english }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"search": query_str, "type": media_type}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        results = data.get("data", {}).get("Page", {}).get("media", [])
        out = []
        for m in results:
            title = m["title"].get("english") or m["title"].get("romaji") or "Unknown"
            out.append({"id": m["id"], "idMal": m.get("idMal"), "title": title})
        return out
    except Exception:
        return []


async def _anilist_user_search(query_str: str) -> list:
    """Search AniList users, returns list with full profile info."""
    query = """
    query ($search: String) {
      Page(perPage: 25) {
        users(search: $search) {
          id name
          avatar { large }
          bannerImage
          siteUrl
          about
          statistics {
            anime { count meanScore minutesWatched episodesWatched }
            manga { count chaptersRead volumesRead }
          }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"search": query_str}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        return data.get("data", {}).get("Page", {}).get("users", [])
    except Exception:
        return []


async def _anilist_fetch_user_by_id(user_id: int) -> dict | None:
    """Fetch full AniList user profile by ID."""
    query = """
    query ($id: Int) {
      User(id: $id) {
        id name
        avatar { large }
        bannerImage
        siteUrl
        about
        statistics {
          anime { count meanScore minutesWatched episodesWatched }
          manga { count chaptersRead volumesRead }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"id": user_id}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return data.get("data", {}).get("User")
    except Exception:
        return None


async def _anilist_fetch_user_by_name(username: str) -> dict | None:
    """Fetch exact AniList user profile by username. Returns None if not found."""
    query = """
    query ($name: String) {
      User(name: $name) {
        id name
        avatar { large }
        bannerImage
        siteUrl
        about
        statistics {
          anime { count meanScore minutesWatched episodesWatched }
          manga { count chaptersRead volumesRead }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"name": username}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return data.get("data", {}).get("User")
    except Exception:
        return None


async def _mal_get_user_id(mal_username: str) -> int | None:
    """Fetch MAL user ID from username via Jikan API (no auth needed)."""
    profile = await _mal_fetch_full_profile(mal_username)
    return profile.get("mal_id") if profile else None


async def _mal_fetch_username_by_id(mal_id: int) -> str | None:
    """Fetch MAL username from user ID via Jikan API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.jikan.moe/v4/users/userbyid/{mal_id}",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return data.get("data", {}).get("username")
    except Exception:
        return None


async def _mal_fetch_full_profile(mal_username: str) -> dict | None:
    """Fetch full MAL user profile via Jikan API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.jikan.moe/v4/users/{mal_username}/full",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        d = data.get("data", {})
        if not d:
            return None
        return {
            "mal_id": d.get("mal_id"),
            "username": d.get("username"),
            "url": d.get("url"),
            "image_url": d.get("images", {}).get("jpg", {}).get("image_url"),
            "about": (d.get("about") or "")[:300],
            "anime_stats": {
                "days_watched": d.get("statistics", {}).get("anime", {}).get("days_watched"),
                "mean_score": d.get("statistics", {}).get("anime", {}).get("mean_score"),
                "watching": d.get("statistics", {}).get("anime", {}).get("watching"),
                "completed": d.get("statistics", {}).get("anime", {}).get("completed"),
                "total_entries": d.get("statistics", {}).get("anime", {}).get("total_entries"),
            },
            "manga_stats": {
                "days_read": d.get("statistics", {}).get("manga", {}).get("days_read"),
                "mean_score": d.get("statistics", {}).get("manga", {}).get("mean_score"),
                "reading": d.get("statistics", {}).get("manga", {}).get("reading"),
                "completed": d.get("statistics", {}).get("manga", {}).get("completed"),
                "total_entries": d.get("statistics", {}).get("manga", {}).get("total_entries"),
            },
        }
    except Exception:
        return None


# ── Simkl token encryption ─────────────────────────────────────────────────────


def _simkl_encrypt_token(token: str) -> str | None:
    """Encrypt a Simkl access token for safe storage in GitHub JSON."""
    if not SIMKL_ENCRYPT_KEY:
        print("[Simkl encrypt] SIMKL_ENCRYPT_KEY not set — cannot encrypt token")
        return None
    try:
        f = Fernet(SIMKL_ENCRYPT_KEY.encode())
        return f.encrypt(token.encode()).decode()
    except Exception as e:
        print(f"[Simkl encrypt] failed: {e}")
        return None


def _simkl_decrypt_token(encrypted: str) -> str | None:
    """Decrypt a stored Simkl access token for use in API calls."""
    if not SIMKL_ENCRYPT_KEY or not encrypted:
        return None
    try:
        f = Fernet(SIMKL_ENCRYPT_KEY.encode())
        return f.decrypt(encrypted.encode()).decode()
    except Exception as e:
        print(f"[Simkl decrypt] failed: {e}")
        return None


# ── Simkl OAuth PIN flow ────────────────────────────────────────────────────────


async def _simkl_get_pin() -> dict | None:
    """Start Simkl PIN auth. Returns user_code, verification_url, expires_in, interval."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/oauth/pin",
                params={"client_id": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    print(f"[Simkl PIN] failed to get pin: status={r.status}")
                    return None
                return await r.json()
    except Exception as e:
        print(f"[Simkl PIN] exception getting pin: {e}")
        return None


async def _simkl_poll_pin(user_code: str) -> str | None:
    """Poll for access token. Returns token string when approved, None if still pending."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/oauth/pin/{user_code}",
                params={"client_id": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                if data.get("result") == "OK":
                    return data.get("access_token")
                return None
    except Exception as e:
        print(f"[Simkl PIN] poll exception: {e}")
        return None


async def _simkl_fetch_user_with_token(access_token: str) -> dict | None:
    """Fetch authenticated Simkl user profile. Returns username, user_id, avatar_url."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/users/settings",
                headers={
                    "simkl-api-key": SIMKL_CLIENT_ID,
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[Simkl user settings] status={r.status} body={body[:200]}")
                    return None
                data = await r.json()
                print(f"[Simkl user settings] raw={str(data)[:500]}")
                # /users/settings response shape:
                # {"account": {"id": 123, ...}, "user": {"name": "...", "avatar": "..."}}
                account = data.get("account") or {}
                user = data.get("user") or data
                # ID is under account.id
                user_id = account.get("id") or user.get("user_id") or user.get("id")
                avatar_raw = user.get("avatar")
                if avatar_raw:
                    if avatar_raw.startswith("http"):
                        avatar_url = avatar_raw
                    else:
                        avatar_url = f"https://simkl.in/avatars/{avatar_raw}/{avatar_raw}_100.jpg"
                elif user_id:
                    avatar_url = f"https://simkl.in/avatars/{user_id}/{user_id}_100.jpg"
                else:
                    avatar_url = None
                return {
                    "username": user.get("name") or user.get("username"),
                    "user_id": user_id,
                    "avatar_url": avatar_url,
                }
    except Exception as e:
        print(f"[Simkl user settings] exception: {e}")
        return None


# ── /link_simkl command ────────────────────────────────────────────────────────


@bot.tree.command(name="link_simkl", description="Link your Simkl account via OAuth")
async def link_simkl(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not SIMKL_CLIENT_ID:
        await interaction.followup.send("❌ Simkl integration is not configured on this bot.", ephemeral=True)
        return

    if not SIMKL_ENCRYPT_KEY:
        await interaction.followup.send("❌ Simkl token encryption key is not configured. Contact the bot admin.", ephemeral=True)
        return

    pin_data = await _simkl_get_pin()
    if not pin_data:
        await interaction.followup.send("❌ Failed to start Simkl auth. Try again later.", ephemeral=True)
        return

    user_code = pin_data.get("user_code")
    verification_url = pin_data.get("verification_url") or f"https://simkl.com/pin/{user_code}"
    expires_in = pin_data.get("expires_in", 600)
    interval = max(pin_data.get("interval", 5), 5)
    expires_mins = expires_in // 60

    embed = discord.Embed(
        title="🔗 Link your Simkl Account",
        description=(
            f"**1.** Click the button below to open Simkl\n"
            f"**2.** Enter the PIN code below on the page\n\n"
            f"⏳ Expires in **{expires_mins} minutes**."
        ),
        color=0x1DB954,
    )
    embed.add_field(name="📋 PIN Code (tap & hold to copy)", value=user_code, inline=False)
    embed.set_footer(text="Waiting for you to authorize on Simkl...")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="🔗 Open Simkl PIN Page",
        url=verification_url,
        style=discord.ButtonStyle.link,
    ))
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    discord_id = str(interaction.user.id)
    deadline = asyncio.get_event_loop().time() + expires_in

    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(interval)
        access_token = await _simkl_poll_pin(user_code)
        if not access_token:
            continue

        simkl_profile = await _simkl_fetch_user_with_token(access_token)
        if not simkl_profile:
            await interaction.followup.send(
                "✅ Authorized but failed to fetch your Simkl profile. Try again.",
                ephemeral=True,
            )
            return

        encrypted_token = _simkl_encrypt_token(access_token)
        if not encrypted_token:
            await interaction.followup.send(
                "❌ Failed to encrypt your token. Contact the bot admin.",
                ephemeral=True,
            )
            return

        async with aiohttp.ClientSession() as session:
            users, sha = await github_read_json(session, FILE_USERS)
            existing = users.get(discord_id, {})
            existing["simkl_username"] = simkl_profile["username"]
            existing["simkl_user_id"] = simkl_profile["user_id"]
            existing["simkl_avatar"] = simkl_profile["avatar_url"]
            existing["simkl_token"] = encrypted_token
            existing.setdefault("discord_id", interaction.user.id)
            existing.setdefault("discord_username", interaction.user.name)
            existing.setdefault("discord_display_name", interaction.user.display_name)
            existing.setdefault("discord_avatar", str(interaction.user.display_avatar.url) if interaction.user.display_avatar else None)
            users[discord_id] = existing
            ok = await github_write_json(
                session, FILE_USERS, users, sha,
                f"link: Simkl OAuth for {interaction.user.display_name}",
            )

        if ok:
            embed = discord.Embed(title="✅ Simkl Linked!", color=0x2EA043)
            embed.add_field(name="Username", value=simkl_profile["username"] or "Unknown", inline=True)
            embed.add_field(name="Simkl ID", value=f"`{simkl_profile['user_id']}`", inline=True)
            if simkl_profile["avatar_url"]:
                embed.set_thumbnail(url=simkl_profile["avatar_url"])
            embed.set_footer(text="Your token is encrypted and stored securely.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to save your Simkl profile. Try again.", ephemeral=True)
        return

    await interaction.followup.send(
        f"⏰ Authorization timed out after {expires_mins} minutes. Run `/link_simkl` again.",
        ephemeral=True,
    )

# ── Simkl helper functions ─────────────────────────────────────────────────────


async def _simkl_fetch_user(simkl_username: str) -> dict | None:
    """
    Fetch a Simkl user's public profile using /search/users (works with client_id only, no OAuth).
    Avatar URL format per Simkl docs: https://simkl.in/avatars/{hash}/{hash}_100.jpg
    """
    if not SIMKL_CLIENT_ID:
        print(f"[Simkl fetch user] SIMKL_CLIENT_ID is not set — cannot fetch user {simkl_username!r}")
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/search/users",
                params={"q": simkl_username, "client_id": SIMKL_CLIENT_ID, "limit": 5},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[Simkl fetch user] status={r.status} for {simkl_username!r} — body: {body[:200]}")
                    return None
                data = await r.json()
                print(f"[Simkl fetch user] raw response for {simkl_username!r}: {str(data)[:300]}")

                # /search/users returns a list — find exact username match (case-insensitive)
                users = data if isinstance(data, list) else data.get("users", [])
                user = None
                for u in users:
                    if (u.get("name") or u.get("username") or "").lower() == simkl_username.lower():
                        user = u
                        break
                # fallback to first result if no exact match
                if not user and users:
                    user = users[0]

                if not user:
                    print(f"[Simkl fetch user] no results found for {simkl_username!r}")
                    return None

                user_id = user.get("id")
                avatar_raw = user.get("avatar")

                if avatar_raw:
                    if avatar_raw.startswith("http"):
                        avatar_url = avatar_raw
                    else:
                        avatar_url = f"https://simkl.in/avatars/{avatar_raw}/{avatar_raw}_100.jpg"
                elif user_id:
                    avatar_url = f"https://simkl.in/avatars/{user_id}/{user_id}_100.jpg"
                else:
                    avatar_url = None

                result = {
                    "username": user.get("name") or user.get("username") or simkl_username,
                    "user_id": user_id,
                    "avatar_url": avatar_url,
                }
                print(f"[Simkl fetch user] parsed → {result}")
                return result
    except Exception as e:
        print(f"[Simkl fetch user] exception for {simkl_username!r}: {e}")
        return None


# Keep old name as alias
_simkl_verify_user = _simkl_fetch_user


async def _simkl_search_tv(query_str: str) -> list:
    """Search Simkl TV shows via /search/tv."""
    if not SIMKL_CLIENT_ID:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/search/tv",
                params={"q": query_str, "client_id": SIMKL_CLIENT_ID, "limit": 25},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    print(f"[Simkl /search/tv] status={r.status} query={query_str!r}")
                    return []
                data = await r.json()
                return data if isinstance(data, list) else data.get("results", [])
    except Exception as e:
        print(f"[Simkl /search/tv] exception: {e}")
        return []


async def _simkl_search_movies(query_str: str) -> list:
    """Search Simkl movies via /search/movies."""
    if not SIMKL_CLIENT_ID:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/search/movie",
                params={"q": query_str, "client_id": SIMKL_CLIENT_ID, "limit": 25},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    print(f"[Simkl /search/movies] status={r.status} query={query_str!r}")
                    return []
                data = await r.json()
                return data if isinstance(data, list) else data.get("results", [])
    except Exception as e:
        print(f"[Simkl /search/movies] exception: {e}")
        return []


async def _simkl_fetch_show(simkl_id: int) -> dict | None:
    """Fetch full TV show details from Simkl."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/tv/{simkl_id}",
                params={"extended": "full", "client_id": SIMKL_CLIENT_ID},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                body = await r.text()
                print(f"[Simkl fetch show] id={simkl_id} status={r.status} body={body[:300]}")
                if r.status != 200:
                    return None
                import json
                return json.loads(body)
    except Exception as e:
        print(f"[Simkl fetch show] exception id={simkl_id}: {e}")
        return None


async def _simkl_fetch_movie(simkl_id: int) -> dict | None:
    """Fetch full movie details from Simkl."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/movies/{simkl_id}",
                params={"extended": "full", "client_id": SIMKL_CLIENT_ID},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                body = await r.text()
                print(f"[Simkl fetch movie] id={simkl_id} status={r.status} body={body[:300]}")
                if r.status != 200:
                    return None
                import json
                return json.loads(body)
    except Exception as e:
        print(f"[Simkl fetch movie] exception id={simkl_id}: {e}")
        return None


def _simkl_poster(simkl_data: dict) -> str | None:
    """Extract poster URL from Simkl media data."""
    poster = simkl_data.get("poster")
    if poster:
        return f"https://simkl.in/posters/{poster}_m.jpg"
    return None


# ── Autocomplete functions ─────────────────────────────────────────────────────


async def anime_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _anilist_search(current, "ANIME")
    return [
        app_commands.Choice(
            name=f"{r['title'][:90]} (AL:{r['id']} MAL:{r['idMal'] or '?'})",
            value=str(r["id"]),
        )
        for r in results
    ][:25]


async def manga_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _anilist_search(current, "MANGA")
    return [
        app_commands.Choice(
            name=f"{r['title'][:90]} (AL:{r['id']} MAL:{r['idMal'] or '?'})",
            value=str(r["id"]),
        )
        for r in results
    ][:25]


async def anilist_user_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _anilist_user_search(current)
    return [
        app_commands.Choice(name=f"{u['name']} (ID: {u['id']})", value=str(u["id"]))
        for u in results
    ][:25]


async def show_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _simkl_search_tv(current)
    choices = []
    for r in results[:25]:
        # Simkl may return ids nested under "ids" dict or directly as "simkl_id"
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        title = r.get("title", "Unknown")
        year = r.get("year", "")
        if simkl_id:
            label = f"{title[:90]} ({year})" if year else title[:100]
            choices.append(app_commands.Choice(name=label, value=str(simkl_id)))
    return choices


async def movie_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _simkl_search_movies(current)
    choices = []
    for r in results[:25]:
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        title = r.get("title", "Unknown")
        year = r.get("year", "")
        if simkl_id:
            label = f"{title[:90]} ({year})" if year else title[:100]
            choices.append(app_commands.Choice(name=label, value=str(simkl_id)))
    return choices


# ── on ready ───────────────────────────────────────────────────────────────────


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await ensure_json_files()


    # Sync slash commands once to avoid Cloudflare rate limiting on every restart
    if not getattr(bot, "_synced", False):
        try:
            await bot.tree.sync()
            bot._synced = True
            print("✅ Slash commands synced")
        except Exception as e:
            print(f"⚠️ Failed to sync slash commands: {e}")

    # ── Run repopulator on startup ─────────────────────────────────────────────
    print("🔄 Running startup repopulator...")
    try:
        result = await run_repopulator(triggered_by="bot startup")
        print(f"✅ Startup repopulator done: {result}")
        channel = bot.get_channel(REPOPULATOR_CHANNEL_ID)
        if channel:
            embed = _build_repopulator_embed(result, "🚀 Startup Profile Sync Complete")
            await channel.send(embed=embed)
    except Exception as e:
        print(f"⚠️ Startup repopulator failed: {e}")

    # ── Start weekly loop if not already running ───────────────────────────────
    if not weekly_repopulator.is_running():
        weekly_repopulator.start()
        print("✅ Weekly repopulator loop started")

async def ensure_json_files():
    """Auto-create all required JSON files on GitHub if they don't exist."""
    global _prefix_cache
    files = {
        FILE_USERS: {},
        FILE_TIMEZONES: {},
        FILE_ANIME: [],
        FILE_MANGA: [],
        FILE_SHOWS: [],
        FILE_MOVIES: [],
        FILE_PREFIXES: DEFAULT_PREFIXES[:],
        FILE_SERVER_CFG: {},
        FILE_VOTES: {},
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
    name="setup", description="Link your AniList and/or MAL accounts to your Discord"
)
@app_commands.describe(
    anilist_username="Your AniList username (optional — leave blank if you don't have one)",
    mal_username="Your MyAnimeList username (optional — leave blank if you don't have one)",
    author_name="Display name for list entries (defaults to Discord username)",
)
@app_commands.autocomplete(anilist_username=anilist_user_autocomplete)
async def setup(
    interaction: discord.Interaction,
    anilist_username: str = "",
    mal_username: str = "",
    author_name: str = "",
):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    author_display = author_name or interaction.user.display_name

    if not anilist_username and not mal_username:
        await interaction.followup.send(
            "❌ Please provide at least one of: AniList username or MAL username. To link Simkl, use /link_simkl instead.",
            ephemeral=True,
        )
        return

    # ── AniList resolution ────────────────────────────────────────────────────
    anilist_profile_data = None
    anilist_user_id = None
    anilist_username_display = None

    if anilist_username:
        if anilist_username.isdigit():
            anilist_user_id = int(anilist_username)
            anilist_profile_data = await _anilist_fetch_user_by_id(anilist_user_id)
            if not anilist_profile_data:
                await interaction.followup.send(
                    f"❌ AniList user with ID `{anilist_user_id}` not found.",
                    ephemeral=True,
                )
                return
            anilist_username_display = anilist_profile_data["name"]
        else:
            anilist_profile_data = await _anilist_fetch_user_by_name(anilist_username)
            if not anilist_profile_data:
                await interaction.followup.send(
                    f"❌ AniList user `{anilist_username}` not found. Try the autocomplete suggestions.",
                    ephemeral=True,
                )
                return
            anilist_user_id = anilist_profile_data["id"]
            anilist_username_display = anilist_profile_data["name"]

    # ── MAL resolution ────────────────────────────────────────────────────────
    mal_profile_data = None
    mal_user_id = None

    if mal_username:
        mal_profile_data = await _mal_fetch_full_profile(mal_username)
        if not mal_profile_data:
            await interaction.followup.send(
                f"❌ MAL user `{mal_username}` not found. Check your username and try again.",
                ephemeral=True,
            )
            return
        mal_user_id = mal_profile_data["mal_id"]

    # ── Build stored profile ──────────────────────────────────────────────────
    profile_entry = {
        "author_name": author_display,
        "discord_id": interaction.user.id,
        "discord_username": interaction.user.name,
        "discord_display_name": interaction.user.display_name,
        "discord_avatar": str(interaction.user.display_avatar.url) if interaction.user.display_avatar else None,
        # AniList — None if user has no AniList
        "anilist_user_id": anilist_user_id,
        "anilist_username": anilist_username_display,
        "anilist_url": anilist_profile_data.get("siteUrl") if anilist_profile_data else None,
        "anilist_avatar": (
            anilist_profile_data.get("avatar", {}).get("large")
            if anilist_profile_data else None
        ),
        "anilist_banner": anilist_profile_data.get("bannerImage") if anilist_profile_data else None,
        "anilist_about": (anilist_profile_data.get("about") or "")[:300] if anilist_profile_data else None,
        "anilist_anime_count": (
            anilist_profile_data.get("statistics", {}).get("anime", {}).get("count")
            if anilist_profile_data else None
        ),
        "anilist_manga_count": (
            anilist_profile_data.get("statistics", {}).get("manga", {}).get("count")
            if anilist_profile_data else None
        ),
        "anilist_mean_score": (
            anilist_profile_data.get("statistics", {}).get("anime", {}).get("meanScore")
            if anilist_profile_data else None
        ),
        "anilist_minutes_watched": (
            anilist_profile_data.get("statistics", {}).get("anime", {}).get("minutesWatched")
            if anilist_profile_data else None
        ),
        "anilist_chapters_read": (
            anilist_profile_data.get("statistics", {}).get("manga", {}).get("chaptersRead")
            if anilist_profile_data else None
        ),
        # MAL — None if user has no MAL
        "mal_user_id": mal_user_id,
        "mal_username": mal_profile_data.get("username") if mal_profile_data else None,
        "mal_url": mal_profile_data.get("url") if mal_profile_data else None,
        "mal_avatar": mal_profile_data.get("image_url") if mal_profile_data else None,
        "mal_about": mal_profile_data.get("about") if mal_profile_data else None,
        "mal_anime_completed": (
            mal_profile_data.get("anime_stats", {}).get("completed")
            if mal_profile_data else None
        ),
        "mal_anime_mean_score": (
            mal_profile_data.get("anime_stats", {}).get("mean_score")
            if mal_profile_data else None
        ),
        "mal_manga_completed": (
            mal_profile_data.get("manga_stats", {}).get("completed")
            if mal_profile_data else None
        ),
        "mal_manga_mean_score": (
            mal_profile_data.get("manga_stats", {}).get("mean_score")
            if mal_profile_data else None
        ),
    }

    async with aiohttp.ClientSession() as session:
        users, sha = await github_read_json(session, FILE_USERS)

        # Merge into existing profile so previously linked accounts aren't wiped.
        # Only overwrite keys that are being actively set in this /setup call.
        existing = users.get(discord_id, {})

        # Always update Discord identity fields
        merged = {**existing}
        merged["author_name"] = author_display
        merged["discord_id"] = interaction.user.id
        merged["discord_username"] = interaction.user.name
        merged["discord_display_name"] = interaction.user.display_name
        merged["discord_avatar"] = str(interaction.user.display_avatar.url) if interaction.user.display_avatar else None

        # Only overwrite AniList fields if an AniList username was provided this time
        if anilist_username:
            merged.update({
                "anilist_user_id": profile_entry["anilist_user_id"],
                "anilist_username": profile_entry["anilist_username"],
                "anilist_url": profile_entry["anilist_url"],
                "anilist_avatar": profile_entry["anilist_avatar"],
                "anilist_banner": profile_entry["anilist_banner"],
                "anilist_about": profile_entry["anilist_about"],
                "anilist_anime_count": profile_entry["anilist_anime_count"],
                "anilist_manga_count": profile_entry["anilist_manga_count"],
                "anilist_mean_score": profile_entry["anilist_mean_score"],
                "anilist_minutes_watched": profile_entry["anilist_minutes_watched"],
                "anilist_chapters_read": profile_entry["anilist_chapters_read"],
            })

        # Only overwrite MAL fields if a MAL username was provided this time
        if mal_username:
            merged.update({
                "mal_user_id": profile_entry["mal_user_id"],
                "mal_username": profile_entry["mal_username"],
                "mal_url": profile_entry["mal_url"],
                "mal_avatar": profile_entry["mal_avatar"],
                "mal_about": profile_entry["mal_about"],
                "mal_anime_completed": profile_entry["mal_anime_completed"],
                "mal_anime_mean_score": profile_entry["mal_anime_mean_score"],
                "mal_manga_completed": profile_entry["mal_manga_completed"],
                "mal_manga_mean_score": profile_entry["mal_manga_mean_score"],
            })

        users[discord_id] = merged
        profile_entry = merged  # use merged for embed display below

        ok = await github_write_json(
            session,
            FILE_USERS,
            users,
            sha,
            f"Setup profile for {interaction.user.display_name}",
        )

    if ok:
        embed = discord.Embed(title="✅ Profile Saved!", color=0x2EA043)
        embed.add_field(name="Author Name", value=author_display, inline=False)

        # Show full merged state (previously linked accounts are preserved)
        merged_al_id = profile_entry.get("anilist_user_id")
        merged_al_name = profile_entry.get("anilist_username")
        merged_al_url = profile_entry.get("anilist_url")
        if merged_al_id:
            tag = " *(updated)*" if anilist_username else " *(existing)*"
            embed.add_field(
                name=f"AniList{tag}",
                value=f"[{merged_al_name}]({merged_al_url}) (ID: `{merged_al_id}`)",
                inline=True,
            )
        else:
            embed.add_field(name="AniList", value="Not linked", inline=True)

        merged_mal_id = profile_entry.get("mal_user_id")
        merged_mal_name = profile_entry.get("mal_username")
        merged_mal_url = profile_entry.get("mal_url")
        if merged_mal_id:
            tag = " *(updated)*" if mal_username else " *(existing)*"
            embed.add_field(
                name=f"MAL{tag}",
                value=f"[{merged_mal_name}]({merged_mal_url}) (ID: `{merged_mal_id}`)",
                inline=True,
            )
        else:
            embed.add_field(name="MAL", value="Not linked", inline=True)

        merged_simkl = profile_entry.get("simkl_username")
        if merged_simkl:
            embed.add_field(
                name="Simkl *(existing)*",
                value=f"[{merged_simkl}](https://simkl.com/users/{merged_simkl})",
                inline=True,
            )
        else:
            embed.add_field(name="Simkl", value="Not linked — use `/link_simkl`", inline=True)

        # Set avatar: prefer AniList, fallback to MAL, then Simkl
        avatar = profile_entry.get("anilist_avatar") or profile_entry.get("mal_avatar") or profile_entry.get("simkl_avatar")
        if avatar:
            embed.set_thumbnail(url=avatar)
        embed.set_footer(text="You can now use /add_anime, /add_manga, /add_show, /add_movie!")
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

    embed = discord.Embed(title=f"👤 {profile.get('author_name', interaction.user.display_name)}'s Profile", color=0x0078D4)

    # ── AniList section ──────────────────────────────────────────────────────
    al_id = profile.get("anilist_user_id")
    al_name = profile.get("anilist_username")
    al_url = profile.get("anilist_url")
    al_avatar = profile.get("anilist_avatar")
    al_anime = profile.get("anilist_anime_count")
    al_manga = profile.get("anilist_manga_count")
    al_score = profile.get("anilist_mean_score")
    al_minutes = profile.get("anilist_minutes_watched")
    al_chapters = profile.get("anilist_chapters_read")

    if al_id:
        al_link = f"[{al_name}]({al_url})" if al_url else (al_name or str(al_id))
        embed.add_field(name="🔵 AniList", value=al_link, inline=True)
        embed.add_field(name="AL ID", value=f"`{al_id}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        stats_lines = []
        if al_anime is not None:
            stats_lines.append(f"Anime: **{al_anime}** | Score: **{al_score or 'N/A'}**")
        if al_minutes is not None:
            days = round(al_minutes / 1440, 1)
            stats_lines.append(f"Days Watched: **{days}**")
        if al_manga is not None:
            stats_lines.append(f"Manga: **{al_manga}** | Chapters: **{al_chapters or 'N/A'}**")
        if stats_lines:
            embed.add_field(name="AniList Stats", value="\n".join(stats_lines), inline=False)
    else:
        embed.add_field(name="🔵 AniList", value="*Not linked*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    # ── MAL section ───────────────────────────────────────────────────────────
    mal_id = profile.get("mal_user_id")
    mal_name = profile.get("mal_username")
    mal_url = profile.get("mal_url")
    mal_avatar = profile.get("mal_avatar")
    mal_anime_done = profile.get("mal_anime_completed")
    mal_anime_score = profile.get("mal_anime_mean_score")
    mal_manga_done = profile.get("mal_manga_completed")
    mal_manga_score = profile.get("mal_manga_mean_score")

    if mal_id:
        mal_link = f"[{mal_name}]({mal_url})" if mal_url else (mal_name or str(mal_id))
        embed.add_field(name="🔴 MAL", value=mal_link, inline=True)
        embed.add_field(name="MAL ID", value=f"`{mal_id}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        mal_stats_lines = []
        if mal_anime_done is not None:
            mal_stats_lines.append(f"Anime Completed: **{mal_anime_done}** | Score: **{mal_anime_score or 'N/A'}**")
        if mal_manga_done is not None:
            mal_stats_lines.append(f"Manga Completed: **{mal_manga_done}** | Score: **{mal_manga_score or 'N/A'}**")
        if mal_stats_lines:
            embed.add_field(name="MAL Stats", value="\n".join(mal_stats_lines), inline=False)
    else:
        embed.add_field(name="🔴 MAL", value="*Not linked*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Avatar: prefer AniList, fallback to MAL
    avatar = al_avatar or mal_avatar
    if avatar:
        embed.set_thumbnail(url=avatar)

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
            u = self.entry.get("user", {})
            al = u.get("anilist", {})
            author_display = (al.get("username") or u.get("mal", {}).get("username") or "Unknown")
            embed.add_field(name="Author", value=author_display, inline=True)
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


async def handle_add(interaction, anilist_id: int, reason: str, media_type: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
        profile = users.get(str(interaction.user.id))

        if not profile:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ Profile not set up",
                    description="Run `/setup` first!",
                    color=0xFFA500,
                ),
                ephemeral=True,
            )
            return

        media = await fetch_anilist(session, anilist_id, media_type)

    if not media:
        await interaction.followup.send("❌ Could not fetch info from AniList.", ephemeral=True)
        return

    titles = media["title"]
    title = titles.get("english") or titles.get("romaji") or titles.get("native") or "Unknown"
    cover_url = media.get("coverImage", {}).get("large", "")
    score = media.get("averageScore") or "N/A"
    genres = ", ".join(media.get("genres", [])[:4]) or "N/A"
    mal_id = media.get("idMal")

    # Build AniList and MAL links
    type_path = "anime" if media_type == "ANIME" else "manga"
    anilist_url = f"https://anilist.co/{type_path}/{anilist_id}"
    mal_url = f"https://myanimelist.net/{type_path}/{mal_id}" if mal_id else "N/A"

    author = profile.get("author_name") or profile.get("author") or interaction.user.display_name

    user_snapshot = _build_user_snapshot(profile)

    episodes = media.get("episodes")
    duration = media.get("duration")
    chapters = media.get("chapters")
    volumes = media.get("volumes")
    status = media.get("status")
    fmt = media.get("format")
    season = media.get("season")
    season_year = media.get("seasonYear")
    description = (media.get("description") or "")[:500]
    studios = [s["name"] for s in (media.get("studios", {}).get("nodes") or [])]

    entry = {
        "anilist_id": anilist_id,
        "mal_id": mal_id,
        "title": title,
        "author": author,
        "reason": reason,
        "user": user_snapshot,
        "poster": cover_url,
        "score": score,
        "genres": media.get("genres", []),
        "nsfw": bool(media.get("isAdult") or False),
        "status": status,
        "format": fmt,
        "episodes": episodes,
        "duration": duration,
        "chapters": chapters,
        "volumes": volumes,
        "season": season,
        "season_year": season_year,
        "description": description,
        "studios": studios,
    }

    filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA

    # Build preview embed — show profile links for the submitter
    al_uid = user_snapshot["anilist"]["id"]
    al_uname = user_snapshot["anilist"]["username"]
    mal_uid = user_snapshot["mal"]["id"]
    mal_uname = user_snapshot["mal"]["username"]

    al_profile_link = (
        f"[{al_uname}](https://anilist.co/user/{al_uname})" if al_uid and al_uname
        else (f"ID `{al_uid}`" if al_uid else "Not linked")
    )
    mal_profile_link = (
        f"[{mal_uname}](https://myanimelist.net/profile/{mal_uname})" if mal_uid and mal_uname
        else (f"ID `{mal_uid}`" if mal_uid else "Not linked")
    )

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"*Confirm to add to `{filepath}`*",
        color=0x0078D4,
    )
    preview.add_field(name="AniList", value=f"[Link]({anilist_url}) (ID: `{anilist_id}`)", inline=True)
    preview.add_field(name="MAL", value=f"[Link]({mal_url}) (ID: `{mal_id or '?'}`)", inline=True)
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Genres", value=genres, inline=True)
    if fmt:
        preview.add_field(name="Format", value=fmt, inline=True)
    if status:
        preview.add_field(name="Status", value=status.replace("_", " ").title(), inline=True)
    if episodes:
        preview.add_field(name="Episodes", value=str(episodes), inline=True)
    if duration:
        preview.add_field(name="Ep. Duration", value=f"{duration} min", inline=True)
    if chapters:
        preview.add_field(name="Chapters", value=str(chapters), inline=True)
    if season and season_year:
        preview.add_field(name="Season", value=f"{season.title()} {season_year}", inline=True)
    if studios:
        preview.add_field(name="Studio", value=", ".join(studios[:2]), inline=True)
    preview.add_field(name="Author", value=author, inline=True)
    preview.add_field(name="AniList Profile", value=al_profile_link, inline=True)
    preview.add_field(name="MAL Profile", value=mal_profile_link, inline=True)
    preview.add_field(name="Reason", value=reason, inline=False)
    if cover_url:
        preview.set_thumbnail(url=cover_url)
    preview.set_footer(text="You have 2 minutes to confirm.")

    view = ConfirmView(entry=entry, filepath=filepath, media_type=media_type.lower(), cover_url=cover_url)
    await interaction.followup.send(embed=preview, view=view)


# ══════════════════════════════════════════════════════════════════════════════
# /add_anime
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_anime", description="Add an underrated anime to the list")
@app_commands.describe(
    title="Search for the anime (type to get suggestions)",
    reason="Why is it underrated?",
)
@app_commands.autocomplete(title=anime_autocomplete)
async def add_anime(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select an anime from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_add(interaction, int(title), reason, "ANIME")


# ══════════════════════════════════════════════════════════════════════════════
# /add_manga
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_manga", description="Add an underrated manga to the list")
@app_commands.describe(
    title="Search for the manga (type to get suggestions)",
    reason="Why is it underrated?",
)
@app_commands.autocomplete(title=manga_autocomplete)
async def add_manga(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select a manga from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_add(interaction, int(title), reason, "MANGA")


# ══════════════════════════════════════════════════════════════════════════════
# Simkl add handler (shows & movies)
# ══════════════════════════════════════════════════════════════════════════════


async def handle_simkl_add(
    interaction: discord.Interaction,
    simkl_id: int,
    reason: str,
    media_type: str,  # "show" or "movie"
):
    await interaction.response.defer()

    discord_id = str(interaction.user.id)

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)

    profile = users.get(discord_id)
    if not profile:
        await interaction.followup.send(
            "❌ You need to run `/setup` first before adding content.", ephemeral=True
        )
        return

    # Fetch media from Simkl
    if media_type == "show":
        media = await _simkl_fetch_show(simkl_id)
    else:
        media = await _simkl_fetch_movie(simkl_id)

    if not media:
        await interaction.followup.send(
            f"❌ Could not fetch {media_type} details from Simkl (ID: {simkl_id}).",
            ephemeral=True,
        )
        return

    title = media.get("title") or media.get("en_title") or f"Simkl ID {simkl_id}"
    poster_url = _simkl_poster(media)
    score = media.get("ratings", {}).get("simkl", {}).get("rating") or "N/A"
    genres = ", ".join(media.get("genres", [])[:4]) or "N/A"
    year = media.get("year") or ""

    # Simkl has no isAdult flag — derive nsfw from certification rating
    _adult_certs = {"NC-17", "X", "TV-MA", "R18", "18+", "AO"}
    certification = (media.get("certification") or "").upper().strip()
    nsfw = certification in _adult_certs

    author = profile.get("author_name") or interaction.user.display_name
    user_snapshot = _build_user_snapshot(profile)

    filepath = FILE_SHOWS if media_type == "show" else FILE_MOVIES
    simkl_url = f"https://simkl.com/{media_type}s/{simkl_id}"

    entry = {
        "simkl_id": simkl_id,
        "title": title,
        "year": year,
        "author": author,
        "reason": reason,
        "user": user_snapshot,
        "poster": poster_url or "",
        "score": score,
        "genres": genres,
        "simkl_url": simkl_url,
        "nsfw": nsfw,
    }

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"*Confirm to add to the underrated {media_type}s list*",
        color=0x9B59B6,
    )
    preview.add_field(name="Simkl", value=f"[Link]({simkl_url}) (ID: `{simkl_id}`)", inline=True)
    preview.add_field(name="Year", value=str(year) if year else "N/A", inline=True)
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Genres", value=genres, inline=True)
    preview.add_field(name="Author", value=author, inline=True)
    preview.add_field(name="Reason", value=reason, inline=False)
    if poster_url:
        preview.set_thumbnail(url=poster_url)
    preview.set_footer(text="You have 2 minutes to confirm.")

    view = SimklConfirmView(entry=entry, filepath=filepath, media_type=media_type, poster_url=poster_url)
    await interaction.followup.send(embed=preview, view=view)


class SimklConfirmView(discord.ui.View):
    def __init__(self, entry: dict, filepath: str, media_type: str, poster_url: str | None):
        super().__init__(timeout=120)
        self.entry = entry
        self.filepath = filepath
        self.media_type = media_type
        self.poster_url = poster_url

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        async with aiohttp.ClientSession() as session:
            entries, sha = await github_read_json(session, self.filepath)

            if any(e.get("simkl_id") == self.entry["simkl_id"] for e in entries):
                await interaction.followup.send(
                    f"⚠️ **{self.entry['title']}** is already in the list!", ephemeral=True
                )
                self.stop()
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
                title=f"✅ Added — {self.entry['title']}",
                description=self.entry.get("reason"),
                color=0x2EA043,
            )
            if self.poster_url:
                embed.set_thumbnail(url=self.poster_url)
        else:
            embed = discord.Embed(title="❌ Failed to save to GitHub", color=0xDA3633)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(embed=embed)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("❌ Cancelled.", ephemeral=True)
        self.stop()


# ══════════════════════════════════════════════════════════════════════════════
# /add_show
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_show", description="Add an underrated TV show to the list")
@app_commands.describe(
    title="Search for the TV show (type to get suggestions)",
    reason="Why is it underrated?",
)
@app_commands.autocomplete(title=show_autocomplete)
async def add_show(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select a TV show from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_simkl_add(interaction, int(title), reason, "show")


# ══════════════════════════════════════════════════════════════════════════════
# /add_movie
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_movie", description="Add an underrated movie to the list")
@app_commands.describe(
    title="Search for the movie (type to get suggestions)",
    reason="Why is it underrated?",
)
@app_commands.autocomplete(title=movie_autocomplete)
async def add_movie(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select a movie from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_simkl_add(interaction, int(title), reason, "movie")


# ══════════════════════════════════════════════════════════════════════════════
# /list_anime — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_anime", description="View the underrated anime list")
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
        u = entry.get("user", {})
        al = u.get("anilist", {})
        author_display = al.get("username") or u.get("mal", {}).get("username") or "Unknown"
        embed.add_field(
            name="Author", value=author_display, inline=True
        )
        embed.add_field(
            name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True
        )
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_manga — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_manga", description="View the underrated manga list")
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
        u = entry.get("user", {})
        al = u.get("anilist", {})
        author_display = al.get("username") or u.get("mal", {}).get("username") or "Unknown"
        embed.add_field(
            name="Author", value=author_display, inline=True
        )
        embed.add_field(
            name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True
        )
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_shows
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_shows", description="View the underrated TV shows list")
async def list_shows(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_SHOWS)

    if not entries:
        embed = discord.Embed(
            title="TV Shows List", description="No shows added yet.", color=0x9B59B6
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0x9B59B6,
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Year", value=str(entry.get("year", "N/A")), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}", inline=True)
        if entry.get("simkl_url"):
            embed.add_field(name="Simkl", value=f"[Link]({entry['simkl_url']})", inline=True)
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_movies
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_movies", description="View the underrated movies list")
async def list_movies(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MOVIES)

    if not entries:
        embed = discord.Embed(
            title="Movies List", description="No movies added yet.", color=0xE67E22
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0xE67E22,
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Year", value=str(entry.get("year", "N/A")), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}", inline=True)
        if entry.get("simkl_url"):
            embed.add_field(name="Simkl", value=f"[Link]({entry['simkl_url']})", inline=True)
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
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
# /remove_show — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_show", description="Remove a TV show from the list")
@app_commands.describe(search_term="Title or Simkl ID")
@has_allowed_role()
async def remove_show(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_SHOWS)

    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit() and str(entry.get("simkl_id")) == search_term:
            found_index = i
            break
        elif search_term.lower() in entry.get("title", "").lower():
            found_index = i
            break

    if found_index is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No show matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_SHOWS, entries, sha, f"Remove show: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(title="Removed", description=removed.get("title"), color=0x2EA043)
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /remove_movie — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_movie", description="Remove a movie from the list")
@app_commands.describe(search_term="Title or Simkl ID")
@has_allowed_role()
async def remove_movie(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_MOVIES)

    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit() and str(entry.get("simkl_id")) == search_term:
            found_index = i
            break
        elif search_term.lower() in entry.get("title", "").lower():
            found_index = i
            break

    if found_index is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No movie matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_MOVIES, entries, sha, f"Remove movie: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(title="Removed", description=removed.get("title"), color=0x2EA043)
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
        name="🔍 AniList (slash)",
        value="`/anime_search` `/manga_search` `/anilist_profile` `/character_search` `/staff_search` `/airing_schedule` `/seasonal_anime`",
        inline=False,
    )
    embed.add_field(
        name="⚙️ Config (slash)",
        value="`/setup_timezone_menu`",
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
            "discord_id": ctx.author.id,
            "discord_username": ctx.author.name,
            "discord_display_name": ctx.author.display_name,
            "discord_avatar": str(ctx.author.display_avatar.url) if ctx.author.display_avatar else None,
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

    user_snapshot = _build_user_snapshot(profile)

    al_uname = user_snapshot["anilist"]["username"]
    mal_uname = user_snapshot["mal"]["username"]
    author_display = al_uname or mal_uname or ctx.author.display_name

    entry = {
        "anilist_id": anilist_id,
        "mal_id": mal_id,
        "title": title,
        "author": author_display,
        "reason": reason,
        "user": user_snapshot,
        "poster": cover_url,
        "score": score,
        "nsfw": bool(media.get("isAdult") or False),
    }
    filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"React to confirm adding to `{filepath}`",
        color=0x0078D4,
    )
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Author", value=author_display, inline=True)
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
        u = entry.get("user", {})
        author_display = u.get("anilist", {}).get("username") or u.get("mal", {}).get("username") or "Unknown"
        e.add_field(name="Author", value=author_display, inline=True)
        if entry.get("poster"):
            e.set_thumbnail(url=entry["poster"])
        e.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(e)
    await ctx.send(embeds=embeds[:10])


@bot.command(name="list_manga")
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
        u = entry.get("user", {})
        author_display = u.get("anilist", {}).get("username") or u.get("mal", {}).get("username") or "Unknown"
        e.add_field(name="Author", value=author_display, inline=True)
        if entry.get("poster"):
            e.set_thumbnail(url=entry["poster"])
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


@bot.tree.command(name="show_search", description="Search for a TV show on Simkl")
@app_commands.describe(title="TV show title to search")
@app_commands.autocomplete(title=show_autocomplete)
async def show_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    # If selected from autocomplete, title is the simkl_id — fetch details directly
    if title.isdigit():
        media = await _simkl_fetch_show(int(title))
        if not media:
            await interaction.followup.send("❌ Could not fetch show details from Simkl.", ephemeral=True)
            return
        embed = _build_simkl_embed(media, "show")
        await interaction.followup.send(embed=embed)
        return
    # Free-text search — return top results as a list
    results = await _simkl_search_tv(title)
    if not results:
        await interaction.followup.send("❌ No TV shows found on Simkl.", ephemeral=True)
        return
    embed = discord.Embed(title=f"🔍 Simkl TV Show Results: {title}", color=0x9B59B6)
    for r in results[:8]:
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        show_title = r.get("title", "Unknown")
        year = r.get("year", "")
        url = f"https://simkl.com/tv/{simkl_id}" if simkl_id else ""
        score = r.get("ratings", {}).get("simkl", {}).get("rating", "N/A")
        genres = ", ".join(r.get("genres", [])[:3]) or "—"
        val = f"Year: {year} | Score: {score} | {genres}"
        if url:
            val += f"\n[Simkl]({url})"
        embed.add_field(name=show_title, value=val, inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="movie_search", description="Search for a movie on Simkl")
@app_commands.describe(title="Movie title to search")
@app_commands.autocomplete(title=movie_autocomplete)
async def movie_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    # If selected from autocomplete, title is the simkl_id — fetch details directly
    if title.isdigit():
        media = await _simkl_fetch_movie(int(title))
        if not media:
            await interaction.followup.send("❌ Could not fetch movie details from Simkl.", ephemeral=True)
            return
        embed = _build_simkl_embed(media, "movie")
        await interaction.followup.send(embed=embed)
        return
    # Free-text search — return top results as a list
    results = await _simkl_search_movies(title)
    if not results:
        await interaction.followup.send("❌ No movies found on Simkl.", ephemeral=True)
        return
    embed = discord.Embed(title=f"🔍 Simkl Movie Results: {title}", color=0xE67E22)
    for r in results[:8]:
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        movie_title = r.get("title", "Unknown")
        year = r.get("year", "")
        url = f"https://simkl.com/movies/{simkl_id}" if simkl_id else ""
        score = r.get("ratings", {}).get("simkl", {}).get("rating", "N/A")
        genres = ", ".join(r.get("genres", [])[:3]) or "—"
        val = f"Year: {year} | Score: {score} | {genres}"
        if url:
            val += f"\n[Simkl]({url})"
        embed.add_field(name=movie_title, value=val, inline=False)
    await interaction.followup.send(embed=embed)


def _build_simkl_embed(media: dict, media_type: str) -> discord.Embed:
    """Build a rich embed for a single Simkl show or movie."""
    title = media.get("title") or media.get("en_title") or "Unknown"
    ids = media.get("ids", {})
    simkl_id = ids.get("simkl_id") or ids.get("simkl") or media.get("simkl_id") or media.get("id")
    url = f"https://simkl.com/{media_type}s/{simkl_id}" if simkl_id else ""
    color = 0x9B59B6 if media_type == "show" else 0xE67E22

    embed = discord.Embed(title=title, url=url, color=color)
    year = media.get("year", "")
    if year:
        embed.add_field(name="Year", value=str(year), inline=True)
    score = media.get("ratings", {}).get("simkl", {}).get("rating", "N/A")
    embed.add_field(name="Score", value=str(score), inline=True)
    status = media.get("status", "")
    if status:
        embed.add_field(name="Status", value=status.replace("_", " ").title(), inline=True)
    if media_type == "show":
        ep_count = media.get("total_episodes") or media.get("ep_count", "")
        if ep_count:
            embed.add_field(name="Episodes", value=str(ep_count), inline=True)
        runtime = media.get("runtime", "")
        if runtime:
            embed.add_field(name="Runtime", value=f"{runtime} min/ep", inline=True)
    else:
        runtime = media.get("runtime", "")
        if runtime:
            embed.add_field(name="Runtime", value=f"{runtime} min", inline=True)
    genres = ", ".join(media.get("genres", [])[:5]) or "—"
    embed.add_field(name="Genres", value=genres, inline=False)
    overview = (media.get("overview") or media.get("description") or "")[:512]
    if overview:
        embed.add_field(name="Overview", value=overview, inline=False)
    poster = _simkl_poster(media)
    if poster:
        embed.set_thumbnail(url=poster)
    return embed



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
# Profile Repopulator — refreshes user info in users.json, anime/manga JSONs
# ══════════════════════════════════════════════════════════════════════════════

# Channel ID to post weekly/startup repopulator reports (set via env var)
REPOPULATOR_CHANNEL_ID = int(os.environ.get("REPOPULATOR_CHANNEL_ID", 0))


async def run_repopulator(triggered_by: str = "system") -> dict:
    """
    Re-fetches every user's AniList + MAL profile and updates:
      - users.json            (full profile refresh)
      - underrated_anime.json (author name, anilist_username, mal_username, score per entry)
      - underrated_manga.json (same)

    Returns a result dict with counts for reporting.
    """
    result = {
        "users_updated": 0,
        "users_skipped": 0,
        "users_failed": 0,
        "anime_entries_updated": 0,
        "manga_entries_updated": 0,
        "show_entries_updated": 0,
        "movie_entries_updated": 0,
        "triggered_by": triggered_by,
    }

    async with aiohttp.ClientSession() as session:
        # ── Step 1: Load all data at once ─────────────────────────────────────
        users, users_sha = await github_read_json(session, FILE_USERS)
        anime_entries, anime_sha = await github_read_json(session, FILE_ANIME)
        manga_entries, manga_sha = await github_read_json(session, FILE_MANGA)
        show_entries, show_sha = await github_read_json(session, FILE_SHOWS)
        movie_entries, movie_sha = await github_read_json(session, FILE_MOVIES)

        if not users:
            result["note"] = "No users found in users.json — nothing to repopulate."
            return result

        # ── Step 2: Refresh each user's profile ───────────────────────────────
        # Build a lookup: anilist_user_id → refreshed profile data
        # and:            mal_user_id     → refreshed profile data
        al_id_to_profile: dict[int, dict] = {}
        mal_id_to_profile: dict[int, dict] = {}
        simkl_uname_to_profile: dict[str, dict] = {}

        for discord_id, profile in users.items():
            al_id = profile.get("anilist_user_id")
            mal_uname = profile.get("mal_username")
            refreshed = False

            # -- AniList refresh --
            if al_id:
                try:
                    al_data = await _anilist_fetch_user_by_id(al_id)
                    if al_data:
                        profile["anilist_username"] = al_data.get("name")
                        profile["anilist_url"] = al_data.get("siteUrl")
                        profile["anilist_avatar"] = (al_data.get("avatar") or {}).get("large")
                        profile["anilist_banner"] = al_data.get("bannerImage")
                        profile["anilist_about"] = (al_data.get("about") or "")[:300]
                        stats = al_data.get("statistics") or {}
                        a_stats = stats.get("anime") or {}
                        m_stats = stats.get("manga") or {}
                        profile["anilist_anime_count"] = a_stats.get("count")
                        profile["anilist_manga_count"] = m_stats.get("count")
                        profile["anilist_mean_score"] = a_stats.get("meanScore")
                        profile["anilist_minutes_watched"] = a_stats.get("minutesWatched")
                        profile["anilist_chapters_read"] = m_stats.get("chaptersRead")
                        al_id_to_profile[al_id] = profile
                        refreshed = True
                    else:
                        # Account gone — keep old data, still register lookup
                        if al_id:
                            al_id_to_profile[al_id] = profile
                except Exception:
                    if al_id:
                        al_id_to_profile[al_id] = profile

            # -- MAL refresh --
            mal_id = profile.get("mal_user_id")
            if mal_id:
                # If username is missing, resolve it from the ID first
                if not mal_uname:
                    mal_uname = await _mal_fetch_username_by_id(mal_id)
                    if mal_uname:
                        profile["mal_username"] = mal_uname
                try:
                    mal_data = await _mal_fetch_full_profile(mal_uname) if mal_uname else None
                    if mal_data:
                        profile["mal_username"] = mal_data.get("username", mal_uname)
                        profile["mal_url"] = mal_data.get("url")
                        profile["mal_avatar"] = mal_data.get("image_url")
                        profile["mal_about"] = mal_data.get("about")
                        a = mal_data.get("anime_stats") or {}
                        m = mal_data.get("manga_stats") or {}
                        profile["mal_anime_completed"] = a.get("completed")
                        profile["mal_anime_mean_score"] = a.get("mean_score")
                        profile["mal_manga_completed"] = m.get("completed")
                        profile["mal_manga_mean_score"] = m.get("mean_score")
                        mal_id_to_profile[mal_id] = profile
                        refreshed = True
                    else:
                        if mal_id:
                            mal_id_to_profile[mal_id] = profile
                except Exception:
                    if mal_id:
                        mal_id_to_profile[mal_id] = profile

            # -- Simkl refresh --
            simkl_token_enc = profile.get("simkl_token")
            simkl_uname = profile.get("simkl_username")
            if simkl_token_enc:
                try:
                    access_token = _simkl_decrypt_token(simkl_token_enc)
                    if access_token:
                        simkl_data = await _simkl_fetch_user_with_token(access_token)
                        if simkl_data:
                            profile["simkl_username"] = simkl_data["username"]
                            profile["simkl_user_id"] = simkl_data["user_id"]
                            profile["simkl_avatar"] = simkl_data["avatar_url"]
                            refreshed = True
                            if simkl_data["username"]:
                                simkl_uname_to_profile[simkl_data["username"].lower()] = profile
                        else:
                            print(f"[Repopulator] Simkl token fetch failed for discord_id={discord_id}")
                            if simkl_uname:
                                simkl_uname_to_profile[simkl_uname.lower()] = profile
                    else:
                        print(f"[Repopulator] Simkl token decrypt failed for discord_id={discord_id}")
                        if simkl_uname:
                            simkl_uname_to_profile[simkl_uname.lower()] = profile
                except Exception as e:
                    print(f"[Repopulator] Simkl exception for discord_id={discord_id}: {e}")
                    if simkl_uname:
                        simkl_uname_to_profile[simkl_uname.lower()] = profile
            elif simkl_uname:
                # No token yet (old profile before OAuth) — still register for entry matching
                simkl_uname_to_profile[simkl_uname.lower()] = profile

            if refreshed:
                result["users_updated"] += 1
            else:
                result["users_skipped"] += 1

            users[discord_id] = profile

        # ── Step 3: Update anime entries ──────────────────────────────────────
        anime_ids = [e["anilist_id"] for e in anime_entries]
        anime_media_map = await fetch_anilist_batch(session, anime_ids, "ANIME")

        for entry in anime_entries:
            changed = False
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")

            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]

            if matched:
                entry["user"] = _build_user_snapshot(matched)
                changed = True

            media = anime_media_map.get(entry["anilist_id"])
            if media:
                entry["poster"] = media.get("coverImage", {}).get("large")
                entry["score"] = media.get("averageScore")
                entry["nsfw"] = media.get("isAdult", False)
                changed = True
            else:
                print(f"⚠️ AniList returned no data for anime {entry['anilist_id']} ({entry.get('title')})")

            if changed:
                result["anime_entries_updated"] += 1

        # ── Step 4: Update manga entries ──────────────────────────────────────
        manga_ids = [e["anilist_id"] for e in manga_entries]
        manga_media_map = await fetch_anilist_batch(session, manga_ids, "MANGA")

        for entry in manga_entries:
            changed = False
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")

            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]

            if matched:
                entry["user"] = _build_user_snapshot(matched)
                changed = True

            media = manga_media_map.get(entry["anilist_id"])
            if media:
                entry["poster"] = media.get("coverImage", {}).get("large")
                entry["score"] = media.get("averageScore")
                entry["nsfw"] = media.get("isAdult", False)
                changed = True
            else:
                print(f"⚠️ AniList returned no data for manga {entry['anilist_id']} ({entry.get('title')})")

            if changed:
                result["manga_entries_updated"] += 1

        # ── Step 4b: Update show entries ──────────────────────────────────────
        _adult_certs = {"NC-17", "X", "TV-MA", "R18", "18+", "AO"}
        for entry in show_entries:
            changed = False
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")

            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            elif simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                matched = simkl_uname_to_profile[simkl_uname.lower()]

            if matched:
                entry["user"] = _build_user_snapshot(matched)
                changed = True

            simkl_id = entry.get("simkl_id")
            if simkl_id:
                media = await _simkl_fetch_show(simkl_id)
                if media:
                    certification = (media.get("certification") or "").upper().strip()
                    entry["nsfw"] = certification in _adult_certs
                    entry["poster"] = _simkl_poster(media) or entry.get("poster", "")
                    entry["score"] = media.get("ratings", {}).get("simkl", {}).get("rating") or entry.get("score", "N/A")
                    changed = True
                else:
                    print(f"⚠️ Simkl returned no data for show {simkl_id} ({entry.get('title')})")

            if changed:
                result["show_entries_updated"] += 1

        # ── Step 4c: Update movie entries ─────────────────────────────────────
        for entry in movie_entries:
            changed = False
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")

            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            elif simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                matched = simkl_uname_to_profile[simkl_uname.lower()]

            if matched:
                entry["user"] = _build_user_snapshot(matched)
                changed = True

            simkl_id = entry.get("simkl_id")
            if simkl_id:
                media = await _simkl_fetch_movie(simkl_id)
                if media:
                    certification = (media.get("certification") or "").upper().strip()
                    entry["nsfw"] = certification in _adult_certs
                    entry["poster"] = _simkl_poster(media) or entry.get("poster", "")
                    entry["score"] = media.get("ratings", {}).get("simkl", {}).get("rating") or entry.get("score", "N/A")
                    changed = True
                else:
                    print(f"⚠️ Simkl returned no data for movie {simkl_id} ({entry.get('title')})")

            if changed:
                result["movie_entries_updated"] += 1

        # ── Step 5: Write all files ────────────────────────────────────────────
        await github_write_json(
            session, FILE_USERS, users, users_sha,
            f"chore: repopulate user profiles ({triggered_by})"
        )
        await github_write_json(
            session, FILE_ANIME, anime_entries, anime_sha,
            f"chore: sync anime entry usernames ({triggered_by})"
        )
        await github_write_json(
            session, FILE_MANGA, manga_entries, manga_sha,
            f"chore: sync manga entry usernames ({triggered_by})"
        )
        await github_write_json(
            session, FILE_SHOWS, show_entries, show_sha,
            f"chore: sync show entry usernames ({triggered_by})"
        )
        await github_write_json(
            session, FILE_MOVIES, movie_entries, movie_sha,
            f"chore: sync movie entry usernames ({triggered_by})"
        )

    return result


def _build_repopulator_embed(result: dict, title: str) -> discord.Embed:
    """Build a nice embed from repopulator result dict."""
    embed = discord.Embed(title=title, color=0x2EA043)
    embed.add_field(
        name="👥 Users",
        value=(
            f"✅ Updated: **{result['users_updated']}**\n"
            f"⏭️ Skipped: **{result['users_skipped']}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="📺 Anime Entries",
        value=f"🔄 Synced: **{result['anime_entries_updated']}**",
        inline=True,
    )
    embed.add_field(
        name="📖 Manga Entries",
        value=f"🔄 Synced: **{result['manga_entries_updated']}**",
        inline=True,
    )
    embed.add_field(
        name="🎬 Show Entries",
        value=f"🔄 Synced: **{result.get('show_entries_updated', 0)}**",
        inline=True,
    )
    embed.add_field(
        name="🎥 Movie Entries",
        value=f"🔄 Synced: **{result.get('movie_entries_updated', 0)}**",
        inline=True,
    )
    if result.get("note"):
        embed.add_field(name="ℹ️ Note", value=result["note"], inline=False)
    embed.set_footer(text=f"Triggered by: {result.get('triggered_by', 'system')}")
    return embed


# ── Weekly task (runs every Sunday at midnight UTC) ────────────────────────────

@tasks.loop(hours=168)  # 168 hours = 7 days
async def weekly_repopulator():
    print("🔄 Weekly repopulator running...")
    result = await run_repopulator(triggered_by="weekly scheduler")
    channel = bot.get_channel(REPOPULATOR_CHANNEL_ID)
    if channel:
        embed = _build_repopulator_embed(result, "🔄 Weekly Profile Sync Complete")
        await channel.send(embed=embed)
    print(f"✅ Weekly repopulator done: {result}")

@weekly_repopulator.before_loop
async def before_weekly_repopulator():
    await bot.wait_until_ready()
    # Skip the first iteration — startup already runs repopulator in on_ready
    await asyncio.sleep(168 * 3600)


# ── Slash command: /repopulate ─────────────────────────────────────────────────

@bot.tree.command(
    name="repopulate",
    description="Manually refresh all user profiles and sync anime/manga entries (Admin only)",
)
@app_commands.default_permissions(administrator=True)
async def repopulate(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🔄 Repopulator Started",
            description=(
                "Fetching all user profiles from AniList and MAL...\n"
                "This may take a moment depending on how many users are registered.\n"
                "I'll send a follow-up here when done!"
            ),
            color=0x0078D4,
        )
    )

    try:
        result = await run_repopulator(triggered_by=f"{interaction.user.display_name} (manual)")
        embed = _build_repopulator_embed(result, "✅ Repopulator Complete")
    except Exception as e:
        embed = discord.Embed(
            title="❌ Repopulator Failed",
            description=f"An error occurred:\n```{e}```",
            color=0xDA3633,
        )

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# Voting System — upvote/downvote for underrated anime & manga
# ══════════════════════════════════════════════════════════════════════════════

import time

# In-memory rate limit store: { "discord_id:vote_key" -> timestamp_of_last_vote }
# Resets on bot restart — intentional, lightweight, no DB needed
_vote_rate_limit: dict[str, float] = {}
VOTE_COOLDOWN_SECONDS = 300  # 5 minutes per user per item


def _vote_key(media_type: str, anilist_id: int) -> str:
    """Canonical key used in votes.json and rate limit store."""
    return f"{media_type}:{anilist_id}"


def _check_vote_rate_limit(discord_id: str, vote_key: str) -> float | None:
    """
    Returns None if allowed, or seconds remaining on cooldown if blocked.
    Also cleans up expired entries to keep memory tidy.
    """
    rl_key = f"{discord_id}:{vote_key}"
    now = time.monotonic()
    last = _vote_rate_limit.get(rl_key)
    if last is not None:
        elapsed = now - last
        if elapsed < VOTE_COOLDOWN_SECONDS:
            return VOTE_COOLDOWN_SECONDS - elapsed
    return None


def _stamp_vote_rate_limit(discord_id: str, vote_key: str):
    """Record that this user just voted on this item."""
    _vote_rate_limit[f"{discord_id}:{vote_key}"] = time.monotonic()


async def _cast_vote(
    voter_id: str,
    display_name: str,
    media_type: str,
    anilist_id: int,
    direction: str,  # "up" or "down"
) -> dict:
    """
    Core vote logic. voter_id is the AniList user ID (or MAL user ID prefixed
    with 'mal:') of the person voting — NOT a Discord ID.
    Returns a result dict: { success, upvotes, downvotes, action, title }
    action is one of: "added_up", "added_down", "switched_to_up",
                      "switched_to_down", "removed_up", "removed_down"
    """
    vote_key = _vote_key(media_type, anilist_id)

    async with aiohttp.ClientSession() as session:
        votes, votes_sha = await github_read_json(session, FILE_VOTES)
        if media_type == "anime":
            media_file = FILE_ANIME
        elif media_type == "manga":
            media_file = FILE_MANGA
        elif media_type == "show":
            media_file = FILE_SHOWS
        else:
            media_file = FILE_MOVIES
        entries, _ = await github_read_json(session, media_file)

    # For shows/movies the "anilist_id" param is actually simkl_id
    if media_type in ("show", "movie"):
        entry = next((e for e in entries if e.get("simkl_id") == anilist_id), None)
    else:
        entry = next((e for e in entries if e.get("anilist_id") == anilist_id), None)
    if not entry:
        return {"success": False, "error": f"No {media_type} with AniList ID {anilist_id} found in the list."}

    title = entry.get("title", str(anilist_id))

    record = votes.get(vote_key, {
        "media_type": media_type,
        "anilist_id": anilist_id,
        "title": title,
        "upvotes": [],
        "downvotes": [],
        "total_upvotes": 0,
        "total_downvotes": 0,
    })

    upvotes: list = record.get("upvotes", [])
    downvotes: list = record.get("downvotes", [])

    action = ""
    if direction == "up":
        if voter_id in upvotes:
            upvotes.remove(voter_id)
            action = "removed_up"
        else:
            upvotes.append(voter_id)
            if voter_id in downvotes:
                downvotes.remove(voter_id)
                action = "switched_to_up"
            else:
                action = "added_up"
    else:  # down
        if voter_id in downvotes:
            downvotes.remove(voter_id)
            action = "removed_down"
        else:
            downvotes.append(voter_id)
            if voter_id in upvotes:
                upvotes.remove(voter_id)
                action = "switched_to_down"
            else:
                action = "added_down"

    record["upvotes"] = upvotes
    record["downvotes"] = downvotes
    record["total_upvotes"] = len(upvotes)
    record["total_downvotes"] = len(downvotes)
    record["title"] = title
    votes[vote_key] = record

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, FILE_VOTES, votes, votes_sha,
            f"vote: {display_name} {action} {media_type} '{title}' (id:{anilist_id})"
        )

    if not ok:
        return {"success": False, "error": "Failed to save vote to GitHub."}

    return {
        "success": True,
        "action": action,
        "title": title,
        "upvotes": len(upvotes),
        "downvotes": len(downvotes),
        "net": len(upvotes) - len(downvotes),
    }


def _vote_action_text(action: str) -> str:
    return {
        "added_up": "✅ Upvoted",
        "added_down": "❌ Downvoted",
        "switched_to_up": "🔄 Switched to upvote",
        "switched_to_down": "🔄 Switched to downvote",
        "removed_up": "↩️ Upvote removed",
        "removed_down": "↩️ Downvote removed",
    }.get(action, "Voted")


async def _handle_vote_interaction(
    interaction: discord.Interaction,
    media_type: str,
    anilist_id_str: str,
    direction: str,
):
    """Shared slash command handler for voting."""
    await interaction.response.defer(ephemeral=True)

    if not anilist_id_str.isdigit():
        await interaction.followup.send("❌ Please select an item from the dropdown.", ephemeral=True)
        return

    anilist_id = int(anilist_id_str)
    discord_id = str(interaction.user.id)

    # Resolve the voter's AniList or MAL ID from their profile
    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
    profile = users.get(discord_id)

    if not profile:
        await interaction.followup.send(
            "❌ You need to run `/setup` and link your AniList or MAL account before voting.",
            ephemeral=True,
        )
        return

    al_id = profile.get("anilist_user_id")
    mal_id = profile.get("mal_user_id")
    simkl_uname = profile.get("simkl_username")

    if al_id:
        voter_id = f"al:{al_id}"
        display_name = profile.get("anilist_username") or interaction.user.display_name
    elif mal_id:
        voter_id = f"mal:{mal_id}"
        display_name = profile.get("mal_username") or interaction.user.display_name
    elif simkl_uname:
        voter_id = f"simkl:{simkl_uname}"
        display_name = simkl_uname
    else:
        await interaction.followup.send(
            "❌ Your profile has no linked AniList, MAL, or Simkl account. Run `/setup` to link one.",
            ephemeral=True,
        )
        return

    vote_key = _vote_key(media_type, anilist_id)

    # Rate limit check (keyed on voter_id, not discord_id)
    cooldown = _check_vote_rate_limit(voter_id, vote_key)
    if cooldown is not None:
        mins = int(cooldown // 60)
        secs = int(cooldown % 60)
        await interaction.followup.send(
            f"⏳ You already voted on this recently. Try again in **{mins}m {secs}s**.",
            ephemeral=True,
        )
        return

    result = await _cast_vote(voter_id, display_name, media_type, anilist_id, direction)

    if not result["success"]:
        await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
        return

    _stamp_vote_rate_limit(voter_id, vote_key)

    action_text = _vote_action_text(result["action"])
    color = 0x2EA043 if "up" in result["action"] else (0xDA3633 if "down" in result["action"] else 0x888888)

    embed = discord.Embed(
        title=f"{action_text} — {result['title']}",
        color=color,
    )
    embed.add_field(name="👍 Upvotes", value=f"**{result['upvotes']}**", inline=True)
    embed.add_field(name="👎 Downvotes", value=f"**{result['downvotes']}**", inline=True)
    embed.add_field(name="📊 Net", value=f"**{result['net']:+d}**", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── Autocomplete for existing list entries ─────────────────────────────────────

async def _existing_anime_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_ANIME)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["anilist_id"]))
        for e in filtered[:25]
    ]


async def _existing_manga_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MANGA)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["anilist_id"]))
        for e in filtered[:25]
    ]


async def _existing_show_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_SHOWS)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["simkl_id"]))
        for e in filtered[:25]
    ]


async def _existing_movie_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MOVIES)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["simkl_id"]))
        for e in filtered[:25]
    ]


# ── /vote_anime ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_anime", description="Upvote or downvote an underrated anime")
@app_commands.describe(
    title="Search for the anime in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_anime_autocomplete)
async def vote_anime(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "anime", title, direction.value)


# ── /vote_manga ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_manga", description="Upvote or downvote an underrated manga")
@app_commands.describe(
    title="Search for the manga in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_manga_autocomplete)
async def vote_manga(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "manga", title, direction.value)


# ── /vote_show ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_show", description="Upvote or downvote an underrated TV show")
@app_commands.describe(
    title="Search for the show in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_show_autocomplete)
async def vote_show(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "show", title, direction.value)


# ── /vote_movie ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_movie", description="Upvote or downvote an underrated movie")
@app_commands.describe(
    title="Search for the movie in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_movie_autocomplete)
async def vote_movie(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "movie", title, direction.value)


# ── /vote_stats ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_stats", description="See vote leaderboard for anime, manga, shows or movies")
@app_commands.describe(media_type="Which list to show")
@app_commands.choices(media_type=[
    app_commands.Choice(name="Anime", value="anime"),
    app_commands.Choice(name="Manga", value="manga"),
    app_commands.Choice(name="TV Shows", value="show"),
    app_commands.Choice(name="Movies", value="movie"),
])
async def vote_stats(interaction: discord.Interaction, media_type: app_commands.Choice[str]):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        votes, _ = await github_read_json(session, FILE_VOTES)

    # Filter by media type and sort by net score desc
    relevant = [
        v for k, v in votes.items()
        if v.get("media_type") == media_type.value
    ]
    relevant.sort(key=lambda v: v.get("total_upvotes", 0) - v.get("total_downvotes", 0), reverse=True)

    if not relevant:
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"No votes yet for {media_type.name}",
                description="Be the first to vote using `/vote_anime` or `/vote_manga`!",
                color=0x0078D4,
            )
        )
        return

    emoji = {"anime": "📺", "manga": "📖", "show": "🎬", "movie": "🎥"}.get(media_type.value, "📺")
    label = {"anime": "Anime", "manga": "Manga", "show": "TV Shows", "movie": "Movies"}.get(media_type.value, media_type.name)
    embed = discord.Embed(
        title=f"{emoji} {label} Vote Leaderboard",
        color=0x0078D4,
    )

    medals = ["🥇", "🥈", "🥉"]
    for i, v in enumerate(relevant[:10]):
        up = v.get("total_upvotes", 0)
        down = v.get("total_downvotes", 0)
        net = up - down
        prefix = medals[i] if i < 3 else f"`#{i+1}`"
        embed.add_field(
            name=f"{prefix} {v.get('title', '?')}",
            value=f"👍 {up}  👎 {down}  📊 **{net:+d}**",
            inline=False,
        )

    embed.set_footer(text=f"Showing top {min(len(relevant), 10)} of {len(relevant)} entries")
    await interaction.followup.send(embed=embed)


# ── /my_votes ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="my_votes", description="See all your votes")
async def my_votes(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
        votes, _ = await github_read_json(session, FILE_VOTES)

    profile = users.get(discord_id)
    if not profile:
        await interaction.followup.send(
            "❌ No profile found. Run `/setup` first!", ephemeral=True
        )
        return

    al_id = profile.get("anilist_user_id")
    mal_id = profile.get("mal_user_id")
    voter_id = f"al:{al_id}" if al_id else (f"mal:{mal_id}" if mal_id else None)

    if not voter_id:
        await interaction.followup.send(
            "❌ Your profile has no linked AniList or MAL account.", ephemeral=True
        )
        return

    my_up = []
    my_down = []
    for key, v in votes.items():
        if voter_id in v.get("upvotes", []):
            my_up.append(f"👍 **{v.get('title', key)}** ({v.get('media_type', '?')})")
        elif voter_id in v.get("downvotes", []):
            my_down.append(f"👎 **{v.get('title', key)}** ({v.get('media_type', '?')})")

    embed = discord.Embed(title=f"🗳️ {interaction.user.display_name}'s Votes", color=0x0078D4)

    if my_up:
        embed.add_field(name="👍 Upvoted", value="\n".join(my_up[:15]), inline=False)
    if my_down:
        embed.add_field(name="👎 Downvoted", value="\n".join(my_down[:15]), inline=False)
    if not my_up and not my_down:
        embed.description = "You haven't voted on anything yet!\nUse `/vote_anime`, `/vote_manga`, `/vote_show`, or `/vote_movie` to get started."

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Voting API endpoints
# POST /api/vote/anime/{anilist_id}   body: { "anilist_user_id": int } or { "mal_user_id": int }, "direction": "up"/"down"
# POST /api/vote/manga/{anilist_id}
# GET  /api/votes/anime/{anilist_id}
# GET  /api/votes/manga/{anilist_id}
# GET  /api/votes/leaderboard?type=anime|manga&limit=10
# ══════════════════════════════════════════════════════════════════════════════

async def api_vote_handler(request, media_type: str):
    """POST /api/vote/{media_type}/{media_id}
    Body: { "anilist_user_id": int } OR { "mal_user_id": int }, plus "direction": "up"/"down"
    Supports looking up entry by anilist_id or mal_id via "id_type": "anilist" | "mal"
    """
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        media_id = int(request.match_info["anilist_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid media_id in URL"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    al_uid = body.get("anilist_user_id")
    mal_uid = body.get("mal_user_id")
    simkl_uid = body.get("simkl_user_id")
    display_name = str(body.get("display_name", "API User")).strip()
    direction = str(body.get("direction", "")).strip().lower()
    id_type = str(body.get("id_type", "anilist")).strip().lower()  # "anilist", "mal", or "simkl"

    if not al_uid and not mal_uid and not simkl_uid:
        return web.json_response({"error": "Provide at least one of: anilist_user_id, mal_user_id, simkl_user_id"}, status=400)
    if direction not in ("up", "down"):
        return web.json_response({"error": "direction must be 'up' or 'down'"}, status=400)
    if id_type not in ("anilist", "mal", "simkl"):
        return web.json_response({"error": "id_type must be 'anilist', 'mal', or 'simkl'"}, status=400)

    if al_uid:
        voter_id = f"al:{al_uid}"
    elif mal_uid:
        voter_id = f"mal:{mal_uid}"
    else:
        voter_id = f"simkl:{simkl_uid}"

    # Resolve anilist_id from the media_id — if id_type is "mal", look up by mal_id
    async with aiohttp.ClientSession() as session:
        if media_type == "anime":
            media_file = FILE_ANIME
        elif media_type == "manga":
            media_file = FILE_MANGA
        elif media_type == "show":
            media_file = FILE_SHOWS
        else:
            media_file = FILE_MOVIES
        entries, _ = await github_read_json(session, media_file)

    if media_type in ("show", "movie"):
        # For shows/movies, the URL param is simkl_id
        entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
    elif id_type == "mal":
        entry = next((e for e in entries if e.get("mal_id") == media_id), None)
    elif id_type == "simkl":
        entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
    else:
        entry = next((e for e in entries if e.get("anilist_id") == media_id), None)

    if not entry:
        return web.json_response(
            {"error": f"No {media_type} with {id_type}_id={media_id} found in the list."},
            status=404,
        )

    # For show/movie entries the canonical ID is simkl_id; reuse the anilist_id param name for the vote key
    anilist_id = entry.get("simkl_id") if media_type in ("show", "movie") else entry["anilist_id"]
    vote_key = _vote_key(media_type, anilist_id)
    cooldown = _check_vote_rate_limit(voter_id, vote_key)
    if cooldown is not None:
        return web.json_response(
            {"error": "Rate limited", "retry_after_seconds": round(cooldown, 1)},
            status=429,
        )

    result = await _cast_vote(voter_id, display_name, media_type, anilist_id, direction)
    if not result["success"]:
        status = 404 if "found" in result.get("error", "") else 500
        return web.json_response({"error": result["error"]}, status=status)

    _stamp_vote_rate_limit(voter_id, vote_key)
    return web.json_response(result, status=200)


async def api_get_votes(request, media_type: str):
    """GET /api/votes/{media_type}/{media_id}?id_type=anilist|mal"""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        media_id = int(request.match_info["anilist_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid media_id in URL"}, status=400)

    id_type = request.rel_url.query.get("id_type", "anilist").lower()
    if id_type not in ("anilist", "mal"):
        return web.json_response({"error": "id_type must be 'anilist' or 'mal'"}, status=400)

    async with aiohttp.ClientSession() as session:
        votes, _ = await github_read_json(session, FILE_VOTES)
        # Resolve anilist_id if mal id_type provided (anime/manga only)
        if id_type == "mal" and media_type in ("anime", "manga"):
            media_file = FILE_ANIME if media_type == "anime" else FILE_MANGA
            entries, _ = await github_read_json(session, media_file)
            entry = next((e for e in entries if e.get("mal_id") == media_id), None)
            if not entry:
                return web.json_response({"error": f"No {media_type} with mal_id={media_id} found."}, status=404)
            anilist_id = entry["anilist_id"]
        elif media_type in ("show", "movie"):
            media_file = FILE_SHOWS if media_type == "show" else FILE_MOVIES
            entries, _ = await github_read_json(session, media_file)
            entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
            if not entry:
                return web.json_response({"error": f"No {media_type} with simkl_id={media_id} found."}, status=404)
            anilist_id = entry["simkl_id"]
        else:
            anilist_id = media_id

    vote_key = _vote_key(media_type, anilist_id)
    record = votes.get(vote_key)
    if not record:
        return web.json_response({
            "media_type": media_type,
            "anilist_id": anilist_id,
            "total_upvotes": 0,
            "total_downvotes": 0,
            "net": 0,
            "upvoters": [],
            "downvoters": [],
        })

    return web.json_response({
        "media_type": media_type,
        "anilist_id": anilist_id,
        "title": record.get("title"),
        "total_upvotes": record.get("total_upvotes", 0),
        "total_downvotes": record.get("total_downvotes", 0),
        "net": record.get("total_upvotes", 0) - record.get("total_downvotes", 0),
        "upvoters": record.get("upvotes", []),
        "downvoters": record.get("downvotes", []),
    })


async def api_leaderboard(request):
    """GET /api/votes/leaderboard?type=anime|manga&limit=10"""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    media_type = request.rel_url.query.get("type", "anime").lower()
    if media_type not in ("anime", "manga", "show", "movie"):
        return web.json_response({"error": "type must be 'anime', 'manga', 'show', or 'movie'"}, status=400)
    try:
        limit = min(int(request.rel_url.query.get("limit", 10)), 50)
    except ValueError:
        limit = 10

    async with aiohttp.ClientSession() as session:
        votes, _ = await github_read_json(session, FILE_VOTES)

    relevant = [
        v for k, v in votes.items() if v.get("media_type") == media_type
    ]
    relevant.sort(
        key=lambda v: v.get("total_upvotes", 0) - v.get("total_downvotes", 0),
        reverse=True,
    )

    return web.json_response({
        "media_type": media_type,
        "leaderboard": [
            {
                "rank": i + 1,
                "anilist_id": v.get("anilist_id"),
                "title": v.get("title"),
                "total_upvotes": v.get("total_upvotes", 0),
                "total_downvotes": v.get("total_downvotes", 0),
                "net": v.get("total_upvotes", 0) - v.get("total_downvotes", 0),
            }
            for i, v in enumerate(relevant[:limit])
        ],
    })


# Route shims
async def api_vote_anime(request): return await api_vote_handler(request, "anime")
async def api_vote_manga(request): return await api_vote_handler(request, "manga")
async def api_vote_show(request): return await api_vote_handler(request, "show")
async def api_vote_movie(request): return await api_vote_handler(request, "movie")
async def api_get_votes_anime(request): return await api_get_votes(request, "anime")
async def api_get_votes_manga(request): return await api_get_votes(request, "manga")
async def api_get_votes_show(request): return await api_get_votes(request, "show")
async def api_get_votes_movie(request): return await api_get_votes(request, "movie")


@bot.tree.command(
    name="fix_discord_info",
    description="Backfill missing Discord info for all users and entries (Admin only)",
)
@app_commands.default_permissions(administrator=True)
async def fix_discord_info(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🔧 Fixing Discord Info...",
            description="Fetching Discord profiles for all users. This will take a moment.",
            color=0x0078D4,
        )
    )

    async with aiohttp.ClientSession() as session:
        users, users_sha = await github_read_json(session, FILE_USERS)
        anime_entries, anime_sha = await github_read_json(session, FILE_ANIME)
        manga_entries, manga_sha = await github_read_json(session, FILE_MANGA)
        show_entries, show_sha = await github_read_json(session, FILE_SHOWS)
        movie_entries, movie_sha = await github_read_json(session, FILE_MOVIES)

        fixed_users = 0
        failed_users = 0

        # Step 1: update discord info in users.json using bot.fetch_user
        for discord_id, profile in users.items():
            try:
                user = await bot.fetch_user(int(discord_id))
                profile["discord_id"] = user.id
                profile["discord_username"] = user.name
                profile["discord_display_name"] = user.display_name
                profile["discord_avatar"] = str(user.display_avatar.url) if user.display_avatar else None
                fixed_users += 1
                print(f"✅ Updated discord info for {user.name} ({discord_id})")
            except Exception as e:
                failed_users += 1
                print(f"⚠️ Failed to fetch Discord user {discord_id}: {e}")
            await asyncio.sleep(0.5)

        # Build lookups: anilist_user_id -> profile, mal_user_id -> profile, simkl_username -> profile
        al_id_to_profile = {}
        mal_id_to_profile = {}
        simkl_uname_to_profile = {}
        for profile in users.values():
            al_id = profile.get("anilist_user_id")
            mal_id = profile.get("mal_user_id")
            simkl_uname = profile.get("simkl_username")
            if al_id:
                al_id_to_profile[al_id] = profile
            if mal_id:
                mal_id_to_profile[mal_id] = profile
            if simkl_uname:
                simkl_uname_to_profile[simkl_uname.lower()] = profile

        # Step 2: update anime entries
        anime_updated = 0
        for entry in anime_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                anime_updated += 1

        # Step 3: update manga entries
        manga_updated = 0
        for entry in manga_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                manga_updated += 1

        # Step 3b: update show entries
        show_updated = 0
        for entry in show_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            elif simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                matched = simkl_uname_to_profile[simkl_uname.lower()]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                show_updated += 1

        # Step 3c: update movie entries
        movie_updated = 0
        for entry in movie_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            elif simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                matched = simkl_uname_to_profile[simkl_uname.lower()]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                movie_updated += 1

        # Step 4: write all files
        await github_write_json(session, FILE_USERS, users, users_sha, "fix: backfill discord info for all users")
        await github_write_json(session, FILE_ANIME, anime_entries, anime_sha, "fix: sync discord info in anime entries")
        await github_write_json(session, FILE_MANGA, manga_entries, manga_sha, "fix: sync discord info in manga entries")
        await github_write_json(session, FILE_SHOWS, show_entries, show_sha, "fix: sync discord info in show entries")
        await github_write_json(session, FILE_MOVIES, movie_entries, movie_sha, "fix: sync discord info in movie entries")

    embed = discord.Embed(title="✅ Discord Info Fixed!", color=0x2EA043)
    embed.add_field(
        name="👥 Users",
        value=f"✅ Fixed: **{fixed_users}**\n❌ Failed: **{failed_users}**",
        inline=True,
    )
    embed.add_field(name="📺 Anime Entries", value=f"🔄 Updated: **{anime_updated}**", inline=True)
    embed.add_field(name="📖 Manga Entries", value=f"🔄 Updated: **{manga_updated}**", inline=True)
    embed.add_field(name="🎬 Show Entries", value=f"🔄 Updated: **{show_updated}**", inline=True)
    embed.add_field(name="🎥 Movie Entries", value=f"🔄 Updated: **{movie_updated}**", inline=True)
    await interaction.followup.send(embed=embed)



@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)


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
