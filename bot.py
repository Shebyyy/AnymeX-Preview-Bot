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

# ── PERMISSION SETTINGS ────────────────────────────────────────────────────────
# Role names that can use restricted commands
# Example: "ALLOWED_ROLE_NAMES=Maintainer,Developer"
ALLOWED_ROLE_NAMES = set()
try:
    allowed_roles_str = os.environ.get("ALLOWED_ROLE_NAMES", "")
    if allowed_roles_str:
        ALLOWED_ROLE_NAMES = set(role.strip() for role in allowed_roles_str.split(","))
except:
    pass

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

# ── Permission Decorators ──────────────────────────────────────────────────────

def has_allowed_role():
    """Check if user has any of the allowed roles"""
    async def predicate(interaction: discord.Interaction) -> bool:
        # Check if user has any of the allowed roles
        user_roles = {role.name for role in interaction.user.roles}
        has_role = bool(user_roles & ALLOWED_ROLE_NAMES)
        
        if has_role:
            return True
        
        # Create helpful message
        if ALLOWED_ROLE_NAMES:
            roles_list = ", ".join(sorted(ALLOWED_ROLE_NAMES))
            await interaction.response.send_message(
                f"❌ You need one of these roles to use this command: `{roles_list}`",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ This command is restricted. No roles are currently configured.",
                ephemeral=True
            )
        return False
    return app_commands.check(predicate)

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
        print(f"⚠️  WARNING: ALLOWED_ROLE_NAMES not configured! Restricted commands will be locked.")

# ══════════════════════════════════════════════════════════════════════════════
# /setup — Anyone can use
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

        profile = {
            "discord_id": discord_id,
            "anilist_user_id": anilist_user_id,
            "mal_user_id": mal_user_id,
            "author_name": author_display,
        }

        users[discord_id] = profile

        success = await github_write_json(
            session, FILE_USERS, users, sha,
            f"Setup profile for {interaction.user.display_name}"
        )

    if success:
        embed = discord.Embed(title="✅ Profile Saved!", color=0x2EA043)
        embed.add_field(name="AniList ID", value=f"`{anilist_user_id}`", inline=True)
        embed.add_field(name="MAL ID", value=f"`{mal_user_id}`", inline=True)
        embed.add_field(name="Author Name", value=author_display, inline=True)
        embed.set_footer(text="You can now use /add_anime, /add_manga and /build!")
    else:
        embed = discord.Embed(
            title="❌ Setup Failed",
            description="Failed to save your profile to GitHub.",
            color=0xDA3633
        )

    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /add_anime & /add_manga handler
# ══════════════════════════════════════════════════════════════════════════════

async def handle_add(interaction: discord.Interaction, anilist_link: str, mal_link: str, reason: str, author: str, anilist_user_id: int, mal_user_id: int, media_type: str):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)
    profile = await get_profile(discord_id)

    # Use provided values or fall back to profile, then to Discord username
    anilist_id = anilist_user_id or (profile.get("anilist_user_id") if profile else None)
    mal_id = mal_user_id or (profile.get("mal_user_id") if profile else None)
    author_name = author or (profile.get("author_name") if profile else "") or interaction.user.display_name

    # Extract media IDs from links
    media_anilist_id = extract_anilist_id(anilist_link)
    media_mal_id = extract_mal_id(mal_link)

    if not media_anilist_id or not media_mal_id:
        embed = discord.Embed(
            title="❌ Invalid Links",
            description="Please provide valid AniList and MAL URLs.",
            color=0xDA3633
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    async with aiohttp.ClientSession() as session:
        media_data = await fetch_anilist(session, media_anilist_id, media_type)

    if not media_data:
        embed = discord.Embed(
            title="❌ Media Not Found",
            description=f"Could not fetch {media_type.lower()} data from AniList.",
            color=0xDA3633
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Get title
    titles = media_data.get("title", {})
    title = titles.get("english") or titles.get("romaji") or titles.get("native") or "Unknown"
    cover_url = media_data.get("coverImage", {}).get("large", "")
    score = media_data.get("averageScore") or "N/A"

    # Create entry
    entry = {
        "anilist_id": media_anilist_id,
        "mal_id": media_mal_id,
        "anilist_user_id": anilist_id,
        "mal_user_id": mal_id,
        "title": title,
        "reason": reason,
        "author": author_name,
        "score": score,
    }

    async with aiohttp.ClientSession() as session:
        if media_type == "ANIME":
            entries, sha = await github_read_json(session, FILE_ANIME)
        else:
            entries, sha = await github_read_json(session, FILE_MANGA)

        entries.append(entry)

        filename = FILE_ANIME if media_type == "ANIME" else FILE_MANGA
        success = await github_write_json(
            session, filename, entries, sha,
            f"Add {media_type.lower()} by {author_name}"
        )

    if success:
        embed = discord.Embed(title=f"✅ {title}", color=0x2EA043)
        embed.add_field(name="Author", value=author_name, inline=True)
        embed.add_field(name="Score", value=f"{score}/100" if isinstance(score, (int, float)) else score, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        if cover_url:
            embed.set_thumbnail(url=cover_url)
        embed.set_footer(text=f"Added to {filename}")
    else:
        embed = discord.Embed(
            title="❌ Failed to Add",
            description=f"Could not save {media_type.lower()} to GitHub.",
            color=0xDA3633
        )

    await interaction.followup.send(embed=embed, ephemeral=True)

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

    # Create paginated response
    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason provided"),
            color=0x0066FF
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True)
        embed.add_field(name="AniList ID", value=entry.get("anilist_id", "N/A"), inline=True)
        embed.add_field(name="MAL ID", value=entry.get("mal_id", "N/A"), inline=True)
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

    # Create paginated response
    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason provided"),
            color=0xFF6B6B
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True)
        embed.add_field(name="AniList ID", value=entry.get("anilist_id", "N/A"), inline=True)
        embed.add_field(name="MAL ID", value=entry.get("mal_id", "N/A"), inline=True)
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])

# ══════════════════════════════════════════════════════════════════════════════
# /remove_anime — Restricted
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="remove_anime", description="Remove an anime from the list")
@app_commands.describe(search_term="Title or AniList ID to remove")
@has_allowed_role()
async def remove_anime(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_ANIME)

    # Search by title or ID
    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit():
            if str(entry.get("anilist_id")) == search_term:
                found_index = i
                break
        else:
            if search_term.lower() in entry.get("title", "").lower():
                found_index = i
                break

    if found_index is None:
        embed = discord.Embed(
            title="❌ Not Found",
            description=f"No anime found matching `{search_term}`",
            color=0xDA3633
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    removed_entry = entries.pop(found_index)

    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_ANIME, entries, sha,
            f"Remove anime: {removed_entry.get('title', 'Unknown')}"
        )

    if success:
        embed = discord.Embed(
            title="✅ Removed",
            description=removed_entry.get("title", "Unknown"),
            color=0x2EA043
        )
        embed.add_field(name="Author", value=removed_entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="AniList ID", value=removed_entry.get("anilist_id", "N/A"), inline=True)
    else:
        embed = discord.Embed(
            title="❌ Failed to Remove",
            description="Could not remove anime from GitHub.",
            color=0xDA3633
        )

    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /remove_manga — Restricted
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="remove_manga", description="Remove a manga from the list")
@app_commands.describe(search_term="Title or AniList ID to remove")
@has_allowed_role()
async def remove_manga(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_MANGA)

    # Search by title or ID
    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit():
            if str(entry.get("anilist_id")) == search_term:
                found_index = i
                break
        else:
            if search_term.lower() in entry.get("title", "").lower():
                found_index = i
                break

    if found_index is None:
        embed = discord.Embed(
            title="❌ Not Found",
            description=f"No manga found matching `{search_term}`",
            color=0xDA3633
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    removed_entry = entries.pop(found_index)

    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_MANGA, entries, sha,
            f"Remove manga: {removed_entry.get('title', 'Unknown')}"
        )

    if success:
        embed = discord.Embed(
            title="✅ Removed",
            description=removed_entry.get("title", "Unknown"),
            color=0x2EA043
        )
        embed.add_field(name="Author", value=removed_entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="AniList ID", value=removed_entry.get("anilist_id", "N/A"), inline=True)
    else:
        embed = discord.Embed(
            title="❌ Failed to Remove",
            description="Could not remove manga from GitHub.",
            color=0xDA3633
        )

    await interaction.followup.send(embed=embed, ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /build — Restricted
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

    if status == 204:
        embed = discord.Embed(title="Build Triggered!", color=0x2EA043)
        embed.add_field(name="Repo", value=f"`{GITHUB_OWNER}/{GITHUB_REPO}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="Build Type", value=f"`{build_type.value}`", inline=True)
        embed.add_field(name="Platforms", value=f"`{platforms.value}`", inline=True)
        if pr_numbers:
            embed.add_field(name="PRs", value=pr_numbers, inline=True)
        embed.add_field(name="Tag", value=f"`{tag_override}`" if tag_override else "Auto-detect", inline=True)
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
    else:
        embed = discord.Embed(title="❌ Failed to Trigger Build", color=0xDA3633)

    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /create_tag — Restricted
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
            await interaction.followup.send(embed=discord.Embed(title="❌ Branch not found", color=0xDA3633)); return

        sha = ref_data["object"]["sha"]
        async with session.post(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/tags", headers=gh_headers(), json={"tag": tag, "message": message, "object": sha, "type": "commit"}) as r:
            status = r.status; tag_data = await r.json()
        if status not in (200, 201):
            await interaction.followup.send(embed=discord.Embed(title="❌ Tag creation failed", color=0xDA3633)); return

        async with session.post(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs", headers=gh_headers(), json={"ref": f"refs/tags/{tag}", "sha": tag_data["sha"]}) as r:
            status = r.status; ref_result = await r.json()

    if status in (200, 201):
        embed = discord.Embed(title="Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        embed.add_field(name="Message", value=message, inline=False)
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
    else:
        embed = discord.Embed(title="❌ Ref creation failed", color=0xDA3633)

    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /delete_tag — Restricted
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="delete_tag", description="Delete a Git tag and its release if it exists")
@app_commands.describe(tag="Tag name to delete (e.g. v3.0.4-alpha)")
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
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="Release", value="Deleted" if release_status in (200, 204) else "Not found", inline=True)
        embed.set_footer(text=f"Deleted by {interaction.user.display_name}")
    else:
        embed = discord.Embed(
            title="❌ Failed to Delete Tag",
            description=f"Tag `{tag}` not found.",
            color=0xDA3633
        )

    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /latest_run — Restricted
# ══════════════════════════════════════════════════════════════════════════════

WORKFLOWS_TO_CHECK = ["beta_manual.yml", "Notify.yml", "build.yml", "changelog.yaml"]

@bot.tree.command(name="latest_run", description="Check the latest run for all workflows")
@has_allowed_role()
async def latest_run(interaction: discord.Interaction):
    await interaction.response.defer()

    embeds = []
    
    async with aiohttp.ClientSession() as session:
        for workflow_file in WORKFLOWS_TO_CHECK:
            async with session.get(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow_file}/runs?per_page=1&branch={GITHUB_BRANCH}",
                headers=gh_headers()
            ) as r:
                if r.status != 200:
                    continue
                data = await r.json()

            if not data.get("workflow_runs"):
                continue

            run = data["workflow_runs"][0]
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
            embed.set_footer(text=f"Workflow: {workflow_file}")
            embeds.append(embed)

    if not embeds:
        embed = discord.Embed(
            title="❌ No Runs Found",
            description="Could not fetch workflow runs.",
            color=0xDA3633
        )
        await interaction.followup.send(embed=embed)
        return

    await interaction.followup.send(embeds=embeds)

# ══════════════════════════════════════════════════════════════════════════════
# Run bot + health server together
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    await start_health_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
