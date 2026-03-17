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

# ══════════════════════════════════════════════════════════════════════════════
# /setup
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="setup", description="Link your AniList, MAL and GitHub accounts to your Discord")
@app_commands.describe(
    anilist_user_id="Your AniList user ID",
    mal_user_id="Your MyAnimeList user ID",
    github_username="Your GitHub username (used to ping you after builds)",
    author_name="Display name for list entries (defaults to Discord username)",
)
async def setup(
    interaction: discord.Interaction,
    anilist_user_id: int,
    mal_user_id: int,
    github_username: str,
    author_name: str = "",
):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/users/{github_username}",
            headers=gh_headers(),
        ) as r:
            if r.status != 200:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ GitHub user not found",
                        description=f"`{github_username}` doesn't exist on GitHub.",
                        color=0xDA3633,
                    ),
                    ephemeral=True,
                )
                return
            gh_data = await r.json()
            gh_avatar = gh_data.get("avatar_url", "")

        users, sha = await github_read_json(session, FILE_USERS)
        discord_id = str(interaction.user.id)
        users[discord_id] = {
            "anilist_user_id": anilist_user_id,
            "mal_user_id":     mal_user_id,
            "github_username": github_username,
            "author":          author_name or interaction.user.display_name,
            "discord_tag":     str(interaction.user),
        }
        ok = await github_write_json(
            session, FILE_USERS, users, sha,
            f"chore: register user {interaction.user} ({discord_id})"
        )

    if ok:
        embed = discord.Embed(title="✅ Profile Saved!", color=0x2EA043)
        embed.add_field(name="AniList ID",  value=f"`{anilist_user_id}`", inline=True)
        embed.add_field(name="MAL ID",      value=f"`{mal_user_id}`",     inline=True)
        embed.add_field(name="GitHub",      value=f"`{github_username}`", inline=True)
        embed.add_field(name="Author Name", value=author_name or interaction.user.display_name, inline=True)
        if gh_avatar:
            embed.set_thumbnail(url=gh_avatar)
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
async def build(interaction: discord.Interaction, platforms: app_commands.Choice[str], build_type: app_commands.Choice[str], pr_numbers: str = "", tag_override: str = ""):
    await interaction.response.defer()

    profile = await get_profile(str(interaction.user.id))
    github_username = profile.get("github_username", "") if profile else ""

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "platforms":    platforms.value,
            "build_type":   build_type.value,
            "pr_numbers":   pr_numbers,
            "tag_override": tag_override,
            "triggered_by": github_username,
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
        embed = discord.Embed(title="🚀 Build Triggered!", color=0x2EA043)
        embed.add_field(name="📦 Repo",       value=f"`{GITHUB_OWNER}/{GITHUB_REPO}`", inline=True)
        embed.add_field(name="🌿 Branch",     value=f"`{GITHUB_BRANCH}`",              inline=True)
        embed.add_field(name="🏗️ Build Type", value=f"`{build_type.value}`",           inline=True)
        embed.add_field(name="🖥️ Platforms",  value=f"`{platforms.value}`",            inline=True)
        if pr_numbers:
            embed.add_field(name="🔀 PRs",    value=pr_numbers,     inline=True)
        embed.add_field(name="🏷️ Tag",        value=f"`{tag_override}`" if tag_override else "Auto-detect", inline=True)
        if github_username:
            embed.add_field(name="👤 Triggered by", value=f"`{github_username}`", inline=True)
        else:
            embed.add_field(name="⚠️ Note", value="Run `/setup` with your GitHub username so the workflow pings you!", inline=False)
        embed.add_field(name="🔗 View Run", value=f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)", inline=False)
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
    else:
        embed = discord.Embed(title="❌ Failed to Trigger Build", description=f"**Status:** `{status}`\n```{body[:1000]}```", color=0xDA3633)
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /create_tag
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="create_tag", description="Create a new Git tag on the beta branch")
@app_commands.describe(tag="Tag name (e.g. v3.0.4-alpha)", message="Tag message")
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
# /latest_run
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="latest_run", description="Check the latest build run status")
async def latest_run(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs?per_page=1&branch={GITHUB_BRANCH}", headers=gh_headers()) as r:
            status = r.status; data = await r.json()

    if status != 200 or not data.get("workflow_runs"):
        await interaction.followup.send("❌ Could not fetch runs."); return

    run = data["workflow_runs"][0]
    conclusion = run.get("conclusion") or "in_progress"
    EMOJI_MAP = {"success": "✅", "failure": "❌", "cancelled": "🚫", "in_progress": "⏳"}
    emoji = EMOJI_MAP.get(conclusion, "❓")
    color = 0x2EA043 if conclusion == "success" else (0xDA3633 if conclusion == "failure" else 0xFFA500)

    embed = discord.Embed(title=f"{emoji} Latest Build Run", color=color)
    embed.add_field(name="Workflow", value=run["name"],                      inline=True)
    embed.add_field(name="Status",   value=f"`{conclusion}`",                inline=True)
    embed.add_field(name="Branch",   value=f"`{run['head_branch']}`",        inline=True)
    embed.add_field(name="Run #",    value=f"`{run['run_number']}`",         inline=True)
    embed.add_field(name="🔗 Link",  value=f"[View Run]({run['html_url']})", inline=False)
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# Run bot + health server together
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    await start_health_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
