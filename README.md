<div align="center">

# 🤖 AnymeX Preview Bot

**A Discord bot for the AnymeX community — anime, manga, TV show & movie submissions, AniList/MAL/Simkl integration, GitHub build management, and team timezone coordination.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.3.2-blue.svg)](https://github.com/Rapptz/discord.py)
[![Render](https://img.shields.io/badge/Hosted%20on-Render-46E3B7.svg)](https://render.com/)
[![API](https://img.shields.io/badge/API-Live-brightgreen.svg)](https://anymex-preview-bot.onrender.com)

[Features](#-features) • [Commands](#-commands) • [API](API.md) • [Data](#-data-storage) • [Setup](#-setup)

</div>

---

## Overview

AnymeX Preview Bot is the backbone of the AnymeX community Discord. It lets members submit underrated anime, manga, TV shows, and movie recommendations, links their AniList, MAL, and Simkl profiles, manages GitHub build workflows, and keeps the team in sync across timezones. All data is stored as JSON files directly in your GitHub repository — no database needed.

### Key Highlights

- 🎌 **Underrated Anime & Manga** — Members submit recommendations linked to their AniList/MAL profiles
- 🎬 **TV Shows & Movies** — Submit underrated shows and movies via Simkl integration
- 👤 **Profile System** — Link AniList, MAL, and Simkl accounts with full stats sync
- 📺 **AniList Integration** — Search anime, manga, characters, staff, seasonal lists
- 🔧 **GitHub Integration** — Trigger builds, create/delete tags, monitor workflow runs
- 🌍 **Timezone System** — Full team timezone coordination with 100+ supported zones
- 🗳️ **Voting System** — Upvote/downvote community submissions with leaderboards
- 🔄 **Auto Sync** — Weekly repopulator keeps all profiles and entry data fresh
- 🌐 **REST API** — External apps can add entries and cast votes via HTTP
- ⌨️ **Dual Commands** — Every command works as both slash `/` and prefix `?`

---

## 🚀 Features

### 👤 Profile System

Members link their AniList, MAL, and/or Simkl accounts once via `/setup`. The bot fetches and stores their full profile — avatar, stats, anime/manga counts, mean score — and uses it to attribute all submissions correctly. Simkl usernames are verified live against the Simkl API (no OAuth required).

The **repopulator** runs on startup and weekly to keep all profile data fresh. It re-fetches every user's AniList and MAL profile and syncs the updated info into all anime, manga, show, and movie entries automatically.

---

### 🎌 Underrated Anime & Manga

Members submit anime and manga they think are underrated, with a reason. Each entry is stored with full submitter profile data — AniList/MAL IDs, avatars, and stats. Posters and scores are fetched directly from AniList. Submissions go through a confirmation step before being committed to GitHub.

---

### 🎬 Underrated TV Shows & Movies

Same submission flow as anime/manga, but powered by Simkl. Members search for shows and movies with autocomplete, add a reason, and confirm. Entries include the Simkl ID, poster, score, genres, year, and a direct Simkl link.

---

### 🗳️ Voting System

Members can upvote or downvote any entry in the list — anime, manga, shows, or movies. Votes are tracked per user with a 5-minute cooldown per item. Toggling the same direction removes the vote. Switching direction moves the vote automatically. `/vote_stats` shows leaderboards for all four media types.

---

### 📺 AniList Integration

Search AniList directly from Discord — anime, manga, characters, staff, airing schedules, and seasonal lists. All results include cover images, scores, genres, and descriptions.

---

### 🔧 GitHub Integration

Trigger GitHub Actions workflow dispatches, create and delete annotated Git tags, and monitor the latest workflow run — all from Discord. Running builds can be cancelled directly via a button in the bot's response.

---

### 🌍 Timezone System

Over 100 timezones supported with autocomplete. Members set their timezone once and can then check each other's current time, compare time differences, find members in similar zones, and convert times between zones. Admins can post a self-serve timezone dropdown menu in any channel.

---

### 🌐 REST API

A built-in HTTP server exposes endpoints so external apps (like the AnymeX app) can interact with the bot's data directly. See [API.md](API.md) for the full reference.

Base URL: `https://anymex-preview-bot.onrender.com`

---

## 📚 Commands

### 👤 Profile

| Command | Description | Permission |
|---------|-------------|------------|
| `/setup [anilist_username] [mal_username] [author_name]` | Link AniList/MAL by username (public profiles only) | Everyone |
| `/link_anilist` | Link AniList via OAuth (supports **private** profiles) | Everyone |
| `/link_mal` | Link MAL via OAuth with PKCE (supports **private** profiles) | Everyone |
| `/link_simkl` | Link Simkl via OAuth redirect | Everyone |
| `/myprofile` | View your saved profile and stats | Everyone |
| `/repopulate` | Manually refresh all profiles and sync entries | Admin |

---

### 🎌 Anime & Manga

| Command | Description | Permission |
|---------|-------------|------------|
| `/add_anime [title] [reason]` | Submit an underrated anime (with autocomplete) | Everyone |
| `/add_manga [title] [reason]` | Submit an underrated manga (with autocomplete) | Everyone |
| `/list_anime` | View the underrated anime list | Everyone |
| `/list_manga` | View the underrated manga list | Everyone |
| `/remove_anime [title or id]` | Remove an anime from the list | Mod |
| `/remove_manga [title or id]` | Remove a manga from the list | Mod |

---

### 🎬 TV Shows & Movies

| Command | Description | Permission |
|---------|-------------|------------|
| `/add_show [title] [reason]` | Submit an underrated TV show (Simkl autocomplete) | Everyone |
| `/add_movie [title] [reason]` | Submit an underrated movie (Simkl autocomplete) | Everyone |
| `/list_shows` | View the underrated TV shows list | Everyone |
| `/list_movies` | View the underrated movies list | Everyone |
| `/remove_show [title or id]` | Remove a show from the list | Mod |
| `/remove_movie [title or id]` | Remove a movie from the list | Mod |

---

### 🗳️ Voting

| Command | Description | Permission |
|---------|-------------|------------|
| `/vote_anime [title] [👍/👎]` | Upvote or downvote an anime entry | Everyone |
| `/vote_manga [title] [👍/👎]` | Upvote or downvote a manga entry | Everyone |
| `/vote_show [title] [👍/👎]` | Upvote or downvote a TV show entry | Everyone |
| `/vote_movie [title] [👍/👎]` | Upvote or downvote a movie entry | Everyone |
| `/vote_stats [anime/manga/show/movie]` | View the vote leaderboard | Everyone |
| `/my_votes` | See all your personal votes | Everyone |

---

### 📺 AniList Search

| Command | Description | Permission |
|---------|-------------|------------|
| `/anime_search [title]` | Search anime — score, genres, episodes, description | Everyone |
| `/manga_search [title]` | Search manga — score, chapters, genres, description | Everyone |
| `/anilist_profile [username]` | View AniList user stats | Everyone |
| `/character_search [name]` | Get character info and appearances | Everyone |
| `/staff_search [name]` | Get staff info and occupations | Everyone |
| `/airing_schedule` | Upcoming episode air times with Discord timestamps | Everyone |
| `/seasonal_anime [season] [year]` | Browse seasonal anime with scores | Everyone |

---

### 🔧 GitHub

| Command | Description | Permission |
|---------|-------------|------------|
| `/build [platforms] [type]` | Trigger a GitHub Actions workflow dispatch | Mod |
| `/create_tag [tag] [message]` | Create an annotated Git tag on the beta branch | Mod |
| `/delete_tag [tag]` | Delete a Git tag and its release | Mod |
| `/latest_run` | View latest workflow run status (with cancel button) | Mod |

**Platforms:** `all`, `android`, `linux`, `windows`, `macos`, `ios`, and combinations like `android,linux,ios`  
**Build types:** `alpha`, `stable`

---

### 🌍 Timezone

| Command | Description | Permission |
|---------|-------------|------------|
| `/set_timezone [tz]` | Set your timezone (autocomplete supported) | Everyone |
| `/remove_timezone` | Remove your timezone | Everyone |
| `/my_time` | Check your current local time | Everyone |
| `/friend_time @user` | Check a friend's current time | Everyone |
| `/friend_compare @user` | See the hour difference between you and a friend | Everyone |
| `/add_friend_timezone @user [tz]` | Set a friend's timezone | Everyone |
| `/list_friends` | Show all team members' current times | Everyone |
| `/timezone_list` | Browse all supported timezones by region | Everyone |
| `/timezone_convert [from] [to] [HH:MM]` | Convert a time between two zones | Everyone |
| `/timezone_stats` | See timezone distribution across the server | Everyone |
| `/night_mode @user` | Check if a friend is likely sleeping (10PM–7AM) | Everyone |
| `/similar_timezone` | Find members within 2 hours of your timezone | Everyone |
| `/world_clock` | Show current time for all unique team timezones | Everyone |
| `/setup_timezone_menu [channel]` | Post a self-serve timezone dropdown in a channel | Admin |

---

### ⚙️ Admin & Config

| Command | Description | Permission |
|---------|-------------|------------|
| `/config_role action:add/remove/list role:@Role` | Manage roles allowed to use mod commands | Admin |
| `/fix_discord_info` | Backfill Discord avatars and usernames for all entries | Admin |
| `?setprefix add/remove/list [prefix]` | Manage bot prefixes | Admin |
| `?sync` | Force re-sync all slash commands | Admin |

---

### Prefix Commands

All slash commands also have a prefix equivalent using `?` (or your configured prefix). Additional prefix-only commands:

| Command | Description |
|---------|-------------|
| `?help [command]` | Show help for all commands or a specific one |
| `?setup [anilist_id] [mal_id]` | Quick profile setup by numeric IDs |
| `?myprofile` | View your profile |
| `?sync` | Force slash command sync (Admin) |
| `?setprefix add/remove/list [prefix]` | Manage prefixes (Admin) |

---

## 💾 Data Storage

All data is stored as JSON files across two GitHub repositories:

### Main Repo (`AnymeX-Preview`, branch: `beta`)

| File | Description |
|------|-------------|
| `underrated_anime.json` | Community underrated anime submissions |
| `underrated_manga.json` | Community underrated manga submissions |
| `underrated_shows.json` | Community underrated TV show submissions |
| `underrated_movies.json` | Community underrated movie submissions |
| `votes.json` | Upvote/downvote records per media entry |
| `timezones.json` | User timezone preferences |
| `prefixes.json` | Bot command prefix list |
| `server_config.json` | Per-server allowed roles configuration |
| `faq.json` | FAQ entries for support channel |

### Private Repo (`clients-userdata`, branch: `main`)

| File | Description |
|------|-------------|
| `users.json` | User profiles — AniList/MAL/Simkl IDs, usernames, avatars, stats, **encrypted OAuth tokens** |

---

## 🔐 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `GITHUB_TOKEN` | ✅ | GitHub PAT with `repo` + `workflow` permissions |
| `API_SECRET` | ✅ | Bearer token for REST API authentication |
| `REPOPULATOR_CHANNEL_ID` | ✅ | Discord channel ID for repopulator reports |
| `SIMKL_CLIENT_ID` | ✅ | Simkl API client ID for show/movie search and user verification |
| `SIMKL_ENCRYPT_KEY` | ✅ | Fernet key for encrypting Simkl tokens (generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `ANILIST_CLIENT_ID` | ✅ | AniList OAuth client ID (register at https://anilist.co/settings/developer) |
| `MAL_CLIENT_ID` | ✅ | MAL OAuth client ID (register at https://myanimelist.net/apiconfig) |
| `MAL_CLIENT_SECRET` | ✅ | MAL OAuth client secret |
| `OAUTH_BASE_URL` | ✅ | Bot's public URL for OAuth callbacks (e.g. `https://anymex-preview-bot.onrender.com`) |
| `PORT` | ❌ | HTTP server port (default: `8080`) |
| `OAUTH_ENCRYPT_KEY` | ❌ | Dedicated encryption key for AniList/MAL tokens (falls back to `SIMKL_ENCRYPT_KEY`) |
| `PROXY_HOST` | ❌ | Proxy host (optional) |
| `PROXY_PORT` | ❌ | Proxy port (optional) |
| `PROXY_USER` | ❌ | Proxy username (optional) |
| `PROXY_PASS` | ❌ | Proxy password (optional) |
| `DESK_SYNC_URL` | ❌ | AnymeX Desk URL (default: `https://anymex-desk.asheby.workers.dev`) |
| `DESK_SYNC_SECRET` | ❌ | Shared auth token for Desk sync endpoint (optional) |
| `DESK_GUILD_ID` | ❌ | Contributor Discord Server ID (default: `1545003117018357850`) |
| `DESK_FORUM_CHANNEL_IDS` | ❌ | Comma-separated forum channel IDs (default: Bugs, Suggestions, and Extensions forum channels) |

---

## 📥 Setup

### Prerequisites

- Python 3.11+
- Discord bot token with `message_content` and `members` intents enabled
- GitHub personal access token with `repo` and `workflow` permissions
- Simkl API client ID (free at [simkl.com/apps](https://simkl.com/apps/))

### Quick Start

```bash
git clone https://github.com/Shebyyy/AnymeX-Preview-Bot.git
cd AnymeX-Preview-Bot
pip install -r requirements.txt
```

Set your environment variables then run:

```bash
python bot.py
```

### Deploy on Render

1. Connect your GitHub repo to Render
2. Set all environment variables in Render dashboard
3. Set start command to `python bot.py`
4. Deploy — the bot will auto-create all JSON files on first startup

### First-Time Discord Setup

1. Invite the bot with `bot` and `applications.commands` scopes
2. Run `?sync` as admin to register all slash commands
3. Run `/setup` to link your AniList/MAL/Simkl profile
4. Run `/config_role action:add role:@YourModRole` to give mods access to restricted commands

---

## 🙏 Acknowledgments

- [discord.py](https://github.com/Rapptz/discord.py) — Discord API wrapper
- [AniList GraphQL API](https://anilist.co/graphql) — Anime/manga data and covers
- [Jikan API](https://jikan.moe/) — MAL profile data
- [Simkl API](https://simkl.com/api/) — TV show and movie data
- [GitHub REST API](https://docs.github.com/en/rest) — Repository and workflow management

---

<div align="center">

**Made with ❤️ for the AnymeX community by [Shebyyy](https://github.com/Shebyyy)**

[⬆ Back to Top](#-anymex-preview-bot)

</div>
