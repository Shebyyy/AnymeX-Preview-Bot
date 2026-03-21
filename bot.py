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
import threading

# ── Config ─────────────────────────────────────────────────────────────────────

DISCORD_TOKEN  = os.environ.get("DISCORD_TOKEN")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN")
PORT           = int(os.environ.get("PORT", 8080))

GITHUB_OWNER   = "Shebyyy"
GITHUB_REPO    = "AnymeX-Preview"
GITHUB_BRANCH  = "beta"
WORKFLOW_FILE  = "beta_manual.yml"

GITHUB_API     = "https://api.github.com"
ANILIST_API    = "https://graphql.anilist.co"

FILE_ANIME     = "underrated_anime.json"
FILE_MANGA     = "underrated_manga.json"
FILE_USERS     = "users.json"
FILE_TIMEZONES = "timezones.json"

# ── COMPLETE WORLD TIMEZONE DATABASE (NEW FORMAT ONLY) ────────────────────────
TIMEZONES = {
    # UTC−12:00
    "BIT": {"code": "BIT", "name": "Baker Island Time", "offset": -12.0, "utc": "UTC-12:00", "region": "Pacific", "iana": "Etc/GMT+12"},
    # UTC−11:00
    "SST": {"code": "SST", "name": "Samoa Standard Time", "offset": -11.0, "utc": "UTC-11:00", "region": "Pacific", "iana": "Pacific/Pago_Pago"},
    # UTC−10:00
    "HST": {"code": "HST", "name": "Hawaii-Aleutian Standard Time", "offset": -10.0, "utc": "UTC-10:00", "region": "Americas", "iana": "Pacific/Honolulu"},
    # UTC−09:00
    "AKST": {"code": "AKST", "name": "Alaska Standard Time", "offset": -9.0, "utc": "UTC-09:00", "region": "Americas", "iana": "America/Anchorage"},
    "AKDT": {"code": "AKDT", "name": "Alaska Daylight Time", "offset": -8.0, "utc": "UTC-08:00", "region": "Americas", "iana": "America/Anchorage"},
    # UTC−08:00
    "PST": {"code": "PST", "name": "Pacific Standard Time", "offset": -8.0, "utc": "UTC-08:00", "region": "Americas", "iana": "America/Los_Angeles"},
    "PDT": {"code": "PDT", "name": "Pacific Daylight Time", "offset": -7.0, "utc": "UTC-07:00", "region": "Americas", "iana": "America/Los_Angeles"},
    # UTC−07:00
    "MST": {"code": "MST", "name": "Mountain Standard Time", "offset": -7.0, "utc": "UTC-07:00", "region": "Americas", "iana": "America/Denver"},
    "MDT": {"code": "MDT", "name": "Mountain Daylight Time", "offset": -6.0, "utc": "UTC-06:00", "region": "Americas", "iana": "America/Denver"},
    # UTC−06:00
    "CST_US": {"code": "CST", "name": "Central Standard Time (US)", "offset": -6.0, "utc": "UTC-06:00", "region": "Americas", "iana": "America/Chicago"},
    "CDT": {"code": "CDT", "name": "Central Daylight Time", "offset": -5.0, "utc": "UTC-05:00", "region": "Americas", "iana": "America/Chicago"},
    # UTC−05:00
    "EST": {"code": "EST", "name": "Eastern Standard Time", "offset": -5.0, "utc": "UTC-05:00", "region": "Americas", "iana": "America/New_York"},
    "EDT": {"code": "EDT", "name": "Eastern Daylight Time", "offset": -4.0, "utc": "UTC-04:00", "region": "Americas", "iana": "America/New_York"},
    # UTC−04:00
    "AST": {"code": "AST", "name": "Atlantic Standard Time", "offset": -4.0, "utc": "UTC-04:00", "region": "Americas", "iana": "America/Halifax"},
    "ADT": {"code": "ADT", "name": "Atlantic Daylight Time", "offset": -3.0, "utc": "UTC-03:00", "region": "Americas", "iana": "America/Halifax"},
    # UTC−03:00
    "ART": {"code": "ART", "name": "Argentina Time", "offset": -3.0, "utc": "UTC-03:00", "region": "Americas", "iana": "America/Argentina/Buenos_Aires"},
    "BRT": {"code": "BRT", "name": "Brasilia Time", "offset": -3.0, "utc": "UTC-03:00", "region": "Americas", "iana": "America/Sao_Paulo"},
    # UTC−02:00
    "GMTSG": {"code": "GST", "name": "South Georgia Time", "offset": -2.0, "utc": "UTC-02:00", "region": "Atlantic", "iana": "Atlantic/South_Georgia"},
    # UTC−01:00
    "AZOT": {"code": "AZOT", "name": "Azores Time", "offset": -1.0, "utc": "UTC-01:00", "region": "Atlantic", "iana": "Atlantic/Azores"},
    # UTC±00:00
    "UTC": {"code": "UTC", "name": "Coordinated Universal Time", "offset": 0.0, "utc": "UTC±00:00", "region": "UTC", "iana": "UTC"},
    "GMT": {"code": "GMT", "name": "Greenwich Mean Time", "offset": 0.0, "utc": "UTC±00:00", "region": "Europe", "iana": "Europe/London"},
    "WET": {"code": "WET", "name": "Western European Time", "offset": 0.0, "utc": "UTC±00:00", "region": "Europe", "iana": "Europe/London"},
    # UTC+01:00
    "WAT": {"code": "WAT", "name": "West Africa Time", "offset": 1.0, "utc": "UTC+01:00", "region": "Africa", "iana": "Africa/Lagos"},
    "CET": {"code": "CET", "name": "Central European Time", "offset": 1.0, "utc": "UTC+01:00", "region": "Europe", "iana": "Europe/Paris"},
    "BST": {"code": "BST", "name": "British Summer Time", "offset": 1.0, "utc": "UTC+01:00", "region": "Europe", "iana": "Europe/London"},
    "IST_EU": {"code": "IST", "name": "Irish Standard Time", "offset": 1.0, "utc": "UTC+01:00", "region": "Europe", "iana": "Europe/Dublin"},
    # UTC+02:00
    "CEST": {"code": "CEST", "name": "Central European Summer Time", "offset": 2.0, "utc": "UTC+02:00", "region": "Europe", "iana": "Europe/Paris"},
    "CAT": {"code": "CAT", "name": "Central Africa Time", "offset": 2.0, "utc": "UTC+02:00", "region": "Africa", "iana": "Africa/Johannesburg"},
    "SAST": {"code": "SAST", "name": "South Africa Standard Time", "offset": 2.0, "utc": "UTC+02:00", "region": "Africa", "iana": "Africa/Johannesburg"},
    "EET": {"code": "EET", "name": "Eastern European Time", "offset": 2.0, "utc": "UTC+02:00", "region": "Europe", "iana": "Europe/Athens"},
    "EGT": {"code": "EGT", "name": "Egypt Standard Time", "offset": 2.0, "utc": "UTC+02:00", "region": "Africa", "iana": "Africa/Cairo"},
    # UTC+03:00
    "EAT": {"code": "EAT", "name": "East Africa Time", "offset": 3.0, "utc": "UTC+03:00", "region": "Africa", "iana": "Africa/Nairobi"},
    "MSK": {"code": "MSK", "name": "Moscow Standard Time", "offset": 3.0, "utc": "UTC+03:00", "region": "Europe", "iana": "Europe/Moscow"},
    "EEST": {"code": "EEST", "name": "Eastern European Summer Time", "offset": 3.0, "utc": "UTC+03:00", "region": "Europe", "iana": "Europe/Athens"},
    # UTC+04:00
    "GST": {"code": "GST", "name": "Gulf Standard Time", "offset": 4.0, "utc": "UTC+04:00", "region": "Asia", "iana": "Asia/Dubai"},
    # UTC+04:30
    "AFT": {"code": "AFT", "name": "Afghanistan Time", "offset": 4.5, "utc": "UTC+04:30", "region": "Asia", "iana": "Asia/Kabul"},
    # UTC+05:00
    "PKT": {"code": "PKT", "name": "Pakistan Standard Time", "offset": 5.0, "utc": "UTC+05:00", "region": "Asia", "iana": "Asia/Karachi"},
    # UTC+05:30
    "IST": {"code": "IST", "name": "Indian Standard Time", "offset": 5.5, "utc": "UTC+05:30", "region": "Asia", "iana": "Asia/Kolkata"},
    # UTC+05:45
    "NPT": {"code": "NPT", "name": "Nepal Time", "offset": 5.75, "utc": "UTC+05:45", "region": "Asia", "iana": "Asia/Kathmandu"},
    # UTC+06:00
    "BDT": {"code": "BDT", "name": "Bangladesh Standard Time", "offset": 6.0, "utc": "UTC+06:00", "region": "Asia", "iana": "Asia/Dhaka"},
    # UTC+06:30
    "MMT": {"code": "MMT", "name": "Myanmar Time", "offset": 6.5, "utc": "UTC+06:30", "region": "Asia", "iana": "Asia/Yangon"},
    # UTC+07:00
    "ICT": {"code": "ICT", "name": "Indochina Time", "offset": 7.0, "utc": "UTC+07:00", "region": "Asia", "iana": "Asia/Bangkok"},
    "WIB": {"code": "WIB", "name": "Western Indonesia Time", "offset": 7.0, "utc": "UTC+07:00", "region": "Asia", "iana": "Asia/Jakarta"},
    # UTC+08:00
    "CST": {"code": "CST", "name": "China Standard Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Shanghai"},
    "SGT": {"code": "SGT", "name": "Singapore Standard Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Singapore"},
    "MYT": {"code": "MYT", "name": "Malaysia Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Kuala_Lumpur"},
    "PHT": {"code": "PHT", "name": "Philippine Standard Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Manila"},
    "HKT": {"code": "HKT", "name": "Hong Kong Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Asia", "iana": "Asia/Hong_Kong"},
    "AWST": {"code": "AWST", "name": "Australian Western Standard Time", "offset": 8.0, "utc": "UTC+08:00", "region": "Australia", "iana": "Australia/Perth"},
    # UTC+09:00
    "JST": {"code": "JST", "name": "Japan Standard Time", "offset": 9.0, "utc": "UTC+09:00", "region": "Asia", "iana": "Asia/Tokyo"},
    "KST": {"code": "KST", "name": "Korea Standard Time", "offset": 9.0, "utc": "UTC+09:00", "region": "Asia", "iana": "Asia/Seoul"},
    # UTC+09:30
    "ACST": {"code": "ACST", "name": "Australian Central Standard Time", "offset": 9.5, "utc": "UTC+09:30", "region": "Australia", "iana": "Australia/Adelaide"},
    "ACDT": {"code": "ACDT", "name": "Australian Central Daylight Time", "offset": 10.5, "utc": "UTC+10:30", "region": "Australia", "iana": "Australia/Adelaide"},
    # UTC+10:00
    "AEST": {"code": "AEST", "name": "Australian Eastern Standard Time", "offset": 10.0, "utc": "UTC+10:00", "region": "Australia", "iana": "Australia/Sydney"},
    "AEDT": {"code": "AEDT", "name": "Australian Eastern Daylight Time", "offset": 11.0, "utc": "UTC+11:00", "region": "Australia", "iana": "Australia/Sydney"},
    # UTC+10:30
    "LHST": {"code": "LHST", "name": "Lord Howe Standard Time", "offset": 10.5, "utc": "UTC+10:30", "region": "Australia", "iana": "Australia/Lord_Howe"},
    # UTC+11:00
    "SBT": {"code": "SBT", "name": "Solomon Islands Time", "offset": 11.0, "utc": "UTC+11:00", "region": "Pacific", "iana": "Pacific/Guadalcanal"},
    "NACT": {"code": "NACT", "name": "Norfolk Island Time", "offset": 11.0, "utc": "UTC+11:00", "region": "Pacific", "iana": "Pacific/Norfolk"},
    # UTC+12:00
    "NZST": {"code": "NZST", "name": "New Zealand Standard Time", "offset": 12.0, "utc": "UTC+12:00", "region": "Pacific", "iana": "Pacific/Auckland"},
    "FJT": {"code": "FJT", "name": "Fiji Time", "offset": 12.0, "utc": "UTC+12:00", "region": "Pacific", "iana": "Pacific/Fiji"},
    # UTC+12:45
    "CHAST": {"code": "CHAST", "name": "Chatham Islands Standard Time", "offset": 12.75, "utc": "UTC+12:45", "region": "Pacific", "iana": "Pacific/Chatham"},
    # UTC+13:00
    "NZDT": {"code": "NZDT", "name": "New Zealand Daylight Time", "offset": 13.0, "utc": "UTC+13:00", "region": "Pacific", "iana": "Pacific/Auckland"},
    "PHOT": {"code": "PHOT", "name": "Phoenix Islands Time", "offset": 13.0, "utc": "UTC+13:00", "region": "Pacific", "iana": "Pacific/Kiritimati"},
    # UTC+14:00
    "LINT": {"code": "LINT", "name": "Line Islands Time", "offset": 14.0, "utc": "UTC+14:00", "region": "Pacific", "iana": "Pacific/Kiritimati"},
}

# ── PERMISSION SETTINGS ────────────────────────────────────────────────────────
# Role names that can use restricted commands
ALLOWED_ROLE_NAMES = set()
try:
    allowed_roles_str = os.environ.get("ALLOWED_ROLE_NAMES", "")
    if allowed_roles_str:
        ALLOWED_ROLE_NAMES = set(role.strip() for role in allowed_roles_str.split(","))
except:
    pass

# ── Permission Decorators ──────────────────────────────────────────────────────

def has_allowed_role():
    """Check if user has any of the allowed roles"""
    async def predicate(interaction: discord.Interaction) -> bool:
        user_roles = {role.name for role in interaction.user.roles}
        has_role = bool(user_roles & ALLOWED_ROLE_NAMES)
        
        if has_role:
            return True
        
        if ALLOWED_ROLE_NAMES:
            roles_list = ", ".join(sorted(ALLOWED_ROLE_NAMES))
            await interaction.response.send_message(
                f"❌ You need one of these roles: `{roles_list}`",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ This command is restricted.", ephemeral=True)
        return False
    return app_commands.check(predicate)

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
bot = commands.Bot(command_prefix="!", intents=intents)

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
            default = {} if filepath == FILE_USERS else []
            return default, None
        data = await r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data["sha"]

async def github_write_json(session: aiohttp.ClientSession, filepath: str, data, sha, commit_msg: str) -> bool:
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
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} — slash commands synced")
    if ALLOWED_ROLE_NAMES:
        roles_list = ", ".join(sorted(ALLOWED_ROLE_NAMES))
        print(f"🔐 Restricted commands require role: {roles_list}")
    else:
        print(f"⚠️  ALLOWED_ROLE_NAMES not configured")

# ══════════════════════════════════════════════════════════════════════════════
# /setup
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="setup", description="Link your AniList and MAL accounts to your Discord")
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
            "mal_user_id":     mal_user_id,
            "author_name":     author_display,
        }

        ok = await github_write_json(
            session, FILE_USERS, users, sha,
            f"Setup profile for {interaction.user.display_name}"
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
        await interaction.followup.send("❌ No profile found. Run `/setup` first!", ephemeral=True)
        return

    embed = discord.Embed(title="👤 Your Profile", color=0x0078D4)
    embed.add_field(name="Author Name",    value=profile.get("author", "—"),               inline=True)
    embed.add_field(name="GitHub",         value=f"`{profile.get('github_username', '—')}`", inline=True)
    embed.add_field(name="AniList UserID", value=f"`{profile['anilist_user_id']}`",         inline=True)
    embed.add_field(name="MAL UserID",     value=f"`{profile['mal_user_id']}`",             inline=True)
    embed.set_footer(text="Use /setup to update your profile.")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# Confirm/Cancel view
# ══════════════════════════════════════════════════════════════════════════════

class ConfirmView(discord.ui.View):
    def __init__(self, entry: dict, filepath: str, media_type: str, cover_url: str):
        super().__init__(timeout=120)
        self.entry      = entry
        self.filepath   = filepath
        self.media_type = media_type
        self.cover_url  = cover_url

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()

        async with aiohttp.ClientSession() as session:
            entries, sha = await github_read_json(session, self.filepath)
            if any(e.get("anilist_id") == self.entry["anilist_id"] for e in entries):
                await interaction.followup.send(embed=discord.Embed(
                    title="⚠️ Already exists",
                    description=f"**{self.entry['title']}** is already in the list!",
                    color=0xFFA500,
                ))
                return
            entries.append(self.entry)
            ok = await github_write_json(
                session, self.filepath, entries, sha,
                f"feat: add {self.entry['title']} to underrated {self.media_type}s by {self.entry['author']}"
            )

        if ok:
            embed = discord.Embed(title=f"🎉 Added to underrated_{self.media_type}s!", color=0x2EA043)
            embed.add_field(name="Title",  value=self.entry["title"],  inline=True)
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

async def handle_add(interaction, anilist_link, mal_link, reason, author_override, anilist_uid_override, mal_uid_override, media_type):
    await interaction.response.defer()

    anilist_id = extract_anilist_id(anilist_link)
    mal_id     = extract_mal_id(mal_link)

    if not anilist_id:
        await interaction.followup.send("❌ Invalid AniList link. Use `https://anilist.co/anime/387`", ephemeral=True)
        return
    if not mal_id:
        await interaction.followup.send("❌ Invalid MAL link. Use `https://myanimelist.net/anime/387`", ephemeral=True)
        return

    async with aiohttp.ClientSession() as session:
        users, _ = await github_read_json(session, FILE_USERS)
        profile = users.get(str(interaction.user.id))

        if not profile and (anilist_uid_override is None or mal_uid_override is None):
            await interaction.followup.send(embed=discord.Embed(
                title="⚠️ Profile not set up",
                description="Run `/setup` first, or pass `anilist_user_id` and `mal_user_id` manually.",
                color=0xFFA500,
            ), ephemeral=True)
            return

        anilist_user_id = anilist_uid_override or profile["anilist_user_id"]
        mal_user_id     = mal_uid_override     or profile["mal_user_id"]
        author          = author_override      or (profile["author"] if profile else interaction.user.display_name)
        media           = await fetch_anilist(session, anilist_id, media_type)

    if not media:
        await interaction.followup.send("❌ Could not fetch info from AniList.", ephemeral=True)
        return

    titles    = media["title"]
    title     = titles.get("english") or titles.get("romaji") or titles.get("native") or "Unknown"
    cover_url = media.get("coverImage", {}).get("large", "")
    score     = media.get("averageScore") or "N/A"
    genres    = ", ".join(media.get("genres", [])[:4]) or "N/A"

    entry = {
        "anilist_id":      anilist_id,
        "mal_id":          mal_id,
        "title":           title,
        "anilist_user_id": anilist_user_id,
        "mal_user_id":     mal_user_id,
        "author":          author,
        "reason":          reason,
    }

    filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA

    preview = discord.Embed(title=f"📋 Preview — {title}", description=f"*Confirm to add to `{filepath}`*", color=0x0078D4)
    preview.add_field(name="AniList ID",      value=f"`{anilist_id}`",      inline=True)
    preview.add_field(name="MAL ID",          value=f"`{mal_id}`",          inline=True)
    preview.add_field(name="Score",           value=f"`{score}`",           inline=True)
    preview.add_field(name="Genres",          value=genres,                 inline=True)
    preview.add_field(name="AniList User ID", value=f"`{anilist_user_id}`", inline=True)
    preview.add_field(name="MAL User ID",     value=f"`{mal_user_id}`",     inline=True)
    preview.add_field(name="Author",          value=author,                 inline=True)
    preview.add_field(name="Reason",          value=reason,                 inline=False)
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
    anilist_link="AniList URL (e.g. https://anilist.co/anime/387)",
    mal_link="MAL URL (e.g. https://myanimelist.net/anime/387)",
    reason="Why is it underrated?",
    author="Override display name",
    anilist_user_id="Override your AniList user ID",
    mal_user_id="Override your MAL user ID",
)
async def add_anime(interaction: discord.Interaction, anilist_link: str, mal_link: str, reason: str, author: str = "", anilist_user_id: int = None, mal_user_id: int = None):
    await handle_add(interaction, anilist_link, mal_link, reason, author, anilist_user_id, mal_user_id, "ANIME")

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
async def add_manga(interaction: discord.Interaction, anilist_link: str, mal_link: str, reason: str, author: str = "", anilist_user_id: int = None, mal_user_id: int = None):
    await handle_add(interaction, anilist_link, mal_link, reason, author, anilist_user_id, mal_user_id, "MANGA")

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
        embed = discord.Embed(title="Anime List", description="No anime added yet.", color=0x0066FF)
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0x0066FF
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True)
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
        embed = discord.Embed(title="Manga List", description="No manga added yet.", color=0xFF6B6B)
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0xFF6B6B
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True)
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
        await interaction.followup.send(embed=discord.Embed(title="Not Found", description=f"No anime matching `{search_term}`", color=0xDA3633), ephemeral=True)
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(session, FILE_ANIME, entries, sha, f"Remove anime: {removed.get('title')}")

    if success:
        embed = discord.Embed(title="Removed", description=removed.get("title"), color=0x2EA043)
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
        await interaction.followup.send(embed=discord.Embed(title="Not Found", description=f"No manga matching `{search_term}`", color=0xDA3633), ephemeral=True)
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(session, FILE_MANGA, entries, sha, f"Remove manga: {removed.get('title')}")

    if success:
        embed = discord.Embed(title="Removed", description=removed.get("title"), color=0x2EA043)
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /build
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM_CHOICES = [
    app_commands.Choice(name="all",                   value="all"),
    app_commands.Choice(name="android",               value="android"),
    app_commands.Choice(name="linux",                 value="linux"),
    app_commands.Choice(name="windows",               value="windows"),
    app_commands.Choice(name="macos",                 value="macos"),
    app_commands.Choice(name="ios",                   value="ios"),
    app_commands.Choice(name="android + linux + ios", value="android,linux,ios"),
    app_commands.Choice(name="android + ios",         value="android,ios"),
    app_commands.Choice(name="android + windows",     value="android,windows"),
    app_commands.Choice(name="android + linux",       value="android,linux"),
    app_commands.Choice(name="android + macos",       value="android,macos"),
    app_commands.Choice(name="linux + windows",       value="linux,windows"),
    app_commands.Choice(name="linux + macos",         value="linux,macos"),
    app_commands.Choice(name="windows + macos",       value="windows,macos"),
    app_commands.Choice(name="ios + macos",           value="ios,macos"),
]
BUILD_TYPE_CHOICES = [
    app_commands.Choice(name="alpha",  value="alpha"),
    app_commands.Choice(name="stable", value="stable"),
]

@bot.tree.command(name="build", description="Trigger the AnymeX-Preview build workflow")
@app_commands.describe(platforms="Platforms to build", build_type="Build type", pr_numbers="PR numbers (comma-separated)", tag_override="Version tag override")
@app_commands.choices(platforms=PLATFORM_CHOICES, build_type=BUILD_TYPE_CHOICES)
@has_allowed_role()
async def build(interaction: discord.Interaction, platforms: app_commands.Choice[str], build_type: app_commands.Choice[str], pr_numbers: str = "", tag_override: str = ""):
    await interaction.response.defer()

    discord_user_id = str(interaction.user.id)

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "platforms":    platforms.value,
            "build_type":   build_type.value,
            "pr_numbers":   pr_numbers,
            "tag_override": tag_override,
            "triggered_by": discord_user_id,
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
            headers=gh_headers(), json=payload,
        ) as r:
            status = r.status
            body   = await r.text()

    if status == 204:
        embed = discord.Embed(title="Build Triggered!", color=0x2EA043)
        embed.add_field(name="Repo", value=f"`{GITHUB_OWNER}/{GITHUB_REPO}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="Build Type", value=f"`{build_type.value}`", inline=True)
        embed.add_field(name="Platforms", value=f"`{platforms.value}`", inline=True)
        if pr_numbers:
            embed.add_field(name="PRs", value=pr_numbers, inline=True)
        embed.add_field(name="Tag", value=f"`{tag_override}`" if tag_override else "Auto-detect", inline=True)
        embed.add_field(name="View Run", value=f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)", inline=False)
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        embed.description = "Build started - use button below to cancel if needed"
        
        # Fetch latest run to get run ID for cancel button
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=1&branch={GITHUB_BRANCH}",
                headers=gh_headers()
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("workflow_runs"):
                        run_id = data["workflow_runs"][0]["id"]
                        
                        class CancelView(discord.ui.View):
                            def __init__(self, run_id):
                                super().__init__()
                                self.run_id = run_id
                            
                            @discord.ui.button(label="Cancel Build", style=discord.ButtonStyle.red)
                            async def cancel_button(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                                await button_interaction.response.defer()
                                
                                async with aiohttp.ClientSession() as session:
                                    async with session.post(
                                        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{self.run_id}/cancel",
                                        headers=gh_headers()
                                    ) as r:
                                        if r.status == 202:
                                            await button_interaction.followup.send(
                                                embed=discord.Embed(title="✅ Build cancelled", color=0x2EA043),
                                                ephemeral=True
                                            )
                                        else:
                                            await button_interaction.followup.send(
                                                embed=discord.Embed(title="❌ Failed to cancel build", color=0xDA3633),
                                                ephemeral=True
                                            )
                        
                        await interaction.followup.send(embed=embed, view=CancelView(run_id))
                        return
        
        # Fallback if we can't get run ID
        await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(title="❌ Failed to Trigger Build", description=f"**Status:** `{status}`\n```{body[:1000]}```", color=0xDA3633)
        await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /create_tag
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="create_tag", description="Create a new Git tag on the beta branch")
@app_commands.describe(tag="Tag name (e.g. v3.0.4-alpha)", message="Tag message")
@has_allowed_role()
async def create_tag(interaction: discord.Interaction, tag: str, message: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}", headers=gh_headers()) as r:
            status = r.status; ref_data = await r.json()
        if status != 200:
            await interaction.followup.send(embed=discord.Embed(title="❌ Branch not found", description=ref_data.get("message"), color=0xDA3633)); return

        sha = ref_data["object"]["sha"]
        async with session.post(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/tags", headers=gh_headers(), json={"tag": tag, "message": message, "object": sha, "type": "commit"}) as r:
            status = r.status; tag_data = await r.json()
        if status not in (200, 201):
            await interaction.followup.send(embed=discord.Embed(title="❌ Tag creation failed", description=tag_data.get("message"), color=0xDA3633)); return

        async with session.post(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs", headers=gh_headers(), json={"ref": f"refs/tags/{tag}", "sha": tag_data["sha"]}) as r:
            status = r.status; ref_result = await r.json()

    if status in (200, 201):
        embed = discord.Embed(title="🏷️ Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        embed.add_field(name="Message", value=message, inline=False)
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
    else:
        embed = discord.Embed(title="❌ Ref creation failed", description=ref_result.get("message"), color=0xDA3633)
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
            headers=gh_headers()
        ) as r:
            tag_status = r.status

        release_status = 404
        if tag_status in (200, 204):
            async with session.delete(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag}",
                headers=gh_headers()
            ) as r:
                release_status = r.status

    if tag_status in (200, 204):
        embed = discord.Embed(title="Tag Deleted!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Release", value="Deleted" if release_status in (200, 204) else "Not found", inline=True)
    else:
        embed = discord.Embed(title="Failed to Delete", description=f"Tag `{tag}` not found", color=0xDA3633)

    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /latest_run — Restricted (only beta_manual.yml)
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="latest_run", description="Check the latest beta_manual.yml run and cancel if running")
@has_allowed_role()
async def latest_run(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/beta_manual.yml/runs?per_page=1&branch={GITHUB_BRANCH}",
            headers=gh_headers()
        ) as r:
            if r.status != 200:
                await interaction.followup.send(embed=discord.Embed(title="❌ Error fetching runs", color=0xDA3633))
                return
            data = await r.json()

    if not data.get("workflow_runs"):
        await interaction.followup.send(embed=discord.Embed(title="❌ No runs found", color=0xDA3633))
        return

    run = data["workflow_runs"][0]
    run_id = run["id"]
    conclusion = run.get("conclusion") or "in_progress"
    
    EMOJI_MAP = {"success": "✅", "failure": "❌", "cancelled": "🚫", "in_progress": "⏳"}
    emoji = EMOJI_MAP.get(conclusion, "❓")
    color = 0x2EA043 if conclusion == "success" else (0xDA3633 if conclusion == "failure" else 0xFFA500)

    embed = discord.Embed(
        title=f"{emoji} {run['name']}",
        color=color
    )
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
            async def cancel_button(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.defer()
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{self.run_id}/cancel",
                        headers=gh_headers()
                    ) as r:
                        if r.status == 202:
                            await button_interaction.followup.send(
                                embed=discord.Embed(title="✅ Run cancelled", color=0x2EA043),
                                ephemeral=True
                            )
                        else:
                            await button_interaction.followup.send(
                                embed=discord.Embed(title="❌ Failed to cancel", color=0xDA3633),
                                ephemeral=True
                            )
        
        await interaction.followup.send(embed=embed, view=CancelView(run_id))
    else:
        await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /build (add cancel button for running builds)

# ══════════════════════════════════════════════════════════════════════════════
# TIMEZONE AUTOCOMPLETE & HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for timezone selection - shows format: IST (UTC+05:30) - Indian Standard Time"""
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

# ══════════════════════════════════════════════════════════════════════════════
# /timezone_list
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="timezone_list", description="View all available timezones grouped by region")
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
            embed=discord.Embed(title="❌ Invalid Timezone", description=f"Timezone `{tz_upper}` not found.", color=0xDA3633),
            ephemeral=True
        )
        return
    
    discord_id = str(interaction.user.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        tz_info = TIMEZONES[tz_upper]
        timezones[discord_id] = {"code": tz_info["code"], "name": tz_info["name"], "offset": tz_info["offset"], "utc": tz_info["utc"]}
        success = await github_write_json(session, FILE_TIMEZONES, timezones, sha, f"Set timezone for {interaction.user.display_name}")
    
    if success:
        embed = discord.Embed(title="✅ Timezone Set!", description=f"**{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}", color=0x2EA043)
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
        await interaction.followup.send(embed=discord.Embed(title="❌ Timezone Not Set", description="Use `/set_timezone` first.", color=0xDA3633), ephemeral=True)
        return
    
    tz_data = timezones[discord_id]
    offset = tz_data["offset"]
    
    from datetime import datetime, timedelta
    utc_now = datetime.utcnow()
    your_time = utc_now + timedelta(hours=offset)
    time_12 = your_time.strftime("%I:%M %p")
    
    embed = discord.Embed(title="🕐 Your Time", description=f"**{time_12}**", color=0x0066FF)
    embed.add_field(name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True)
    embed.add_field(name="Full Name", value=tz_data['name'], inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /add_friend_timezone
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="add_friend_timezone", description="Add a friend's timezone")
@app_commands.describe(user="Friend to add", timezone="Their timezone")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def add_friend_timezone(interaction: discord.Interaction, user: discord.User, timezone: str):
    await interaction.response.defer(ephemeral=True)
    
    tz_upper = timezone.upper()
    if tz_upper not in TIMEZONES:
        await interaction.followup.send(embed=discord.Embed(title="❌ Invalid Timezone", color=0xDA3633), ephemeral=True)
        return
    
    friend_id = str(user.id)
    async with aiohttp.ClientSession() as session:
        timezones, sha = await github_read_json(session, FILE_TIMEZONES)
        tz_info = TIMEZONES[tz_upper]
        timezones[friend_id] = {"code": tz_info["code"], "name": tz_info["name"], "offset": tz_info["offset"], "utc": tz_info["utc"]}
        success = await github_write_json(session, FILE_TIMEZONES, timezones, sha, f"Add timezone for {user.display_name}")
    
    if success:
        embed = discord.Embed(title="✅ Friend's Timezone Added!", description=f"**{user.mention}** → **{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}", color=0x2EA043)
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
        await interaction.followup.send(embed=discord.Embed(title="❌ Friend's Timezone Not Set", color=0xDA3633), ephemeral=True)
        return
    
    tz_data = timezones[friend_id]
    offset = tz_data["offset"]
    
    from datetime import datetime, timedelta
    utc_now = datetime.utcnow()
    friend_time_calc = utc_now + timedelta(hours=offset)
    time_12 = friend_time_calc.strftime("%I:%M %p")
    
    embed = discord.Embed(title=f"🕐 {user.display_name}'s Time", description=f"**{time_12}**", color=0x0066FF)
    embed.add_field(name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True)
    embed.add_field(name="Full Name", value=tz_data['name'], inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /list_friends
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="list_friends", description="Show all friends' timezones and current times")
async def list_friends(interaction: discord.Interaction):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    
    if not timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ No timezones set", color=0xDA3633))
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
        
        embed.add_field(name=f"👤 {user_name}", value=f"🕐 {time_12} ({tz_data['code']})", inline=False)
    
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
            await interaction.followup.send(embed=discord.Embed(title="❌ No Timezone Set", color=0xDA3633), ephemeral=True)
            return
        
        del timezones[discord_id]
        success = await github_write_json(session, FILE_TIMEZONES, timezones, sha, f"Remove timezone for {interaction.user.display_name}")
    
    if success:
        embed = discord.Embed(title="✅ Timezone Removed!", color=0x2EA043)
    else:
        embed = discord.Embed(title="❌ Failed to remove timezone", color=0xDA3633)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /friend_compare - Compare time difference
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="friend_compare", description="Compare time difference with a friend")
@app_commands.describe(user="Friend to compare with")
async def friend_compare(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    
    your_id = str(interaction.user.id)
    friend_id = str(user.id)
    
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    
    if your_id not in timezones or friend_id not in timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ Timezone not set", description="Both users need timezone set", color=0xDA3633), ephemeral=True)
        return
    
    your_tz = timezones[your_id]
    friend_tz = timezones[friend_id]
    diff = friend_tz["offset"] - your_tz["offset"]
    sign = "+" if diff >= 0 else ""
    
    embed = discord.Embed(title="⏰ Time Difference", color=0x0066FF)
    embed.add_field(name="You", value=f"{your_tz['code']} ({your_tz['utc']})", inline=True)
    embed.add_field(name=f"{user.display_name}", value=f"{friend_tz['code']} ({friend_tz['utc']})", inline=True)
    embed.add_field(name="Difference", value=f"{sign}{diff}h", inline=False)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /timezone_convert - Convert time between timezones
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="timezone_convert", description="Convert time between timezones")
@app_commands.describe(from_tz="Source timezone", to_tz="Target timezone", time="Time HH:MM (24-hour)")
@app_commands.autocomplete(from_tz=timezone_autocomplete)
@app_commands.autocomplete(to_tz=timezone_autocomplete)
async def timezone_convert(interaction: discord.Interaction, from_tz: str, to_tz: str, time: str):
    await interaction.response.defer(ephemeral=True)
    
    from_upper = from_tz.upper()
    to_upper = to_tz.upper()
    
    if from_upper not in TIMEZONES or to_upper not in TIMEZONES:
        await interaction.followup.send(embed=discord.Embed(title="❌ Invalid timezone", color=0xDA3633), ephemeral=True)
        return
    
    try:
        hour, minute = map(int, time.split(":"))
        from_data = TIMEZONES[from_upper]
        to_data = TIMEZONES[to_upper]
        
        offset_diff = to_data["offset"] - from_data["offset"]
        new_hour = (hour + int(offset_diff)) % 24
        
        embed = discord.Embed(title="🕐 Time Conversion", color=0x0066FF)
        embed.add_field(name=f"{from_data['code']}", value=f"{hour:02d}:{minute:02d}", inline=True)
        embed.add_field(name=f"{to_data['code']}", value=f"{new_hour:02d}:{minute:02d}", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(title="❌ Error", description=str(e)[:100], color=0xDA3633), ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /timezone_stats - Show timezone distribution
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="timezone_stats", description="Show team timezone distribution")
async def timezone_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    
    if not timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ No timezones set", color=0xDA3633))
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

@bot.tree.command(name="night_mode", description="Check if friend is sleeping (10 PM - 7 AM)")
@app_commands.describe(user="Friend to check")
async def night_mode(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    
    friend_id = str(user.id)
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    
    if friend_id not in timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ Timezone not set", color=0xDA3633), ephemeral=True)
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
        color=0xDA3633 if is_sleeping else 0x2EA043
    )
    embed.add_field(name="Timezone", value=f"{tz_data['code']} ({tz_data['utc']})", inline=True)
    embed.add_field(name="Time", value=friend_time.strftime("%I:%M %p"), inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /similar_timezone - Find team members within 2 hours
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="similar_timezone", description="Find team members within 2 hours of your timezone")
async def similar_timezone(interaction: discord.Interaction):
    await interaction.response.defer()
    
    your_id = str(interaction.user.id)
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    
    if your_id not in timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ Your timezone not set", color=0xDA3633))
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
            embed.add_field(name=f"👤 {user_name}", value=f"{tz} ({diff}h diff)", inline=False)
    else:
        embed.description = "No one within 2 hours"
    
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /world_clock - Show all team timezones
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="world_clock", description="Show current time in all team timezones")
async def world_clock(interaction: discord.Interaction):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        timezones, _ = await github_read_json(session, FILE_TIMEZONES)
    
    if not timezones:
        await interaction.followup.send(embed=discord.Embed(title="❌ No timezones set", color=0xDA3633))
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
        if query and query not in label.lower() and query not in tz.get("region", "").lower() and query not in tz.get("iana", "").lower():
            continue
        results.append(discord.SelectOption(label=label[:100], value=tz_key, emoji="🌍"))
    return results


class TimezoneSearchModal(discord.ui.Modal, title="🔍 Search Timezone"):
    query = discord.ui.TextInput(
        label="Search",
        placeholder="e.g. India, UTC+8, Pacific, IST ...",
        required=True,
        max_length=50
    )

    def __init__(self, all_options: list):
        super().__init__()
        self.all_options = all_options  # full unfiltered list (SelectOption objects)

    async def on_submit(self, interaction: discord.Interaction):
        filtered = build_tz_options(self.query.value)
        if not filtered:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ No Results", description=f"No timezones found for **{self.query.value}**", color=0xDA3633),
                ephemeral=True
            )
            return
        new_view = TimezoneSelectView(self.all_options, page=0, filtered_options=filtered, search_query=self.query.value)
        await interaction.response.edit_message(view=new_view)


class TimezoneSelectView(discord.ui.View):
    """Dropdown select for timezone with pagination + search"""
    def __init__(self, all_options: list, page: int = 0, filtered_options: list = None, search_query: str = ""):
        super().__init__(timeout=None)
        self.all_options = all_options          # full list always kept
        self.page = page
        self.search_query = search_query
        # displayed list is filtered if a search is active, otherwise full list
        self.display_options = filtered_options if filtered_options is not None else all_options

        # ── Dropdown ──────────────────────────────────────────────────────────
        current_page_options = self.display_options[page * 25:(page + 1) * 25]
        self.add_item(TimezoneSelect(current_page_options, len(self.display_options), page))

        # ── Prev / Next buttons (added directly to self — no nested View) ─────
        if page > 0:
            prev_btn = discord.ui.Button(label="← Previous", style=discord.ButtonStyle.primary, row=1)
            async def prev_callback(interaction: discord.Interaction):
                await interaction.response.defer()
                new_view = TimezoneSelectView(self.all_options, page - 1, self.display_options, self.search_query)
                await interaction.message.edit(view=new_view)
            prev_btn.callback = prev_callback
            self.add_item(prev_btn)

        if (page + 1) * 25 < len(self.display_options):
            next_btn = discord.ui.Button(label="Next →", style=discord.ButtonStyle.primary, row=1)
            async def next_callback(interaction: discord.Interaction):
                await interaction.response.defer()
                new_view = TimezoneSelectView(self.all_options, page + 1, self.display_options, self.search_query)
                await interaction.message.edit(view=new_view)
            next_btn.callback = next_callback
            self.add_item(next_btn)

        # ── Search button ─────────────────────────────────────────────────────
        search_btn = discord.ui.Button(
            label="🔍 Search" if not search_query else f"🔍 Search: {search_query[:20]}",
            style=discord.ButtonStyle.secondary,
            row=1
        )
        async def search_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(TimezoneSearchModal(self.all_options))
        search_btn.callback = search_callback
        self.add_item(search_btn)

        # ── Clear search button (only shown when a filter is active) ──────────
        if search_query:
            clear_btn = discord.ui.Button(label="✖ Clear Filter", style=discord.ButtonStyle.danger, row=1)
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
            row=0
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
            timezones[user_id] = {"code": tz_info["code"], "name": tz_info["name"], "offset": tz_info["offset"], "utc": tz_info["utc"]}
            success = await github_write_json(session, FILE_TIMEZONES, timezones, sha, f"Set timezone for {interaction.user.display_name}")

        if success:
            embed = discord.Embed(
                title="✅ Timezone Set!",
                description=f"**{tz_info['code']}** ({tz_info['utc']}) - {tz_info['name']}",
                color=0x2EA043
            )
        else:
            embed = discord.Embed(title="❌ Failed to save timezone", color=0xDA3633)

        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_timezone_menu", description="Setup timezone selection menu (Admin only)")
@app_commands.describe(
    channel="Channel to post in (required)",
    role="Role to mention (optional)",
    message="Custom message (optional - leave blank for default)"
)
@app_commands.default_permissions(administrator=True)
async def setup_timezone_menu(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role = None,
    message: str = None
):
    """Admin command to setup timezone menu - all in one command"""
    await interaction.response.defer(ephemeral=True)
    
    # Check if user is admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.followup.send(embed=discord.Embed(title="❌ Admin only", color=0xDA3633), ephemeral=True)
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
    embed = discord.Embed(title="🌍 Timezone Selector", description=msg_content, color=0x0066FF)
    embed.set_footer(text=f"Total timezones: {len(options)}")
    view = TimezoneSelectView(options, page=0)
    
    try:
        await channel.send(embed=embed, view=view)
        await interaction.followup.send(embed=discord.Embed(title="✅ Timezone menu posted!", description=f"Posted to {channel.mention}\n({len(options)} timezones available)", color=0x2EA043), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(title="❌ Error", description=str(e)[:100], color=0xDA3633), ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Run bot + health server together
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    await start_health_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
