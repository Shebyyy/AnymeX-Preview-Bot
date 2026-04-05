<div align="center">

# 🤖 AnymeX Preview Bot

**A Discord bot for the AnymeX community — anime & manga submissions, AniList integration, GitHub build management, and team timezone coordination.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.3.2-blue.svg)](https://github.com/Rapptz/discord.py)
[![Render](https://img.shields.io/badge/Hosted%20on-Render-46E3B7.svg)](https://render.com/)
[![API](https://img.shields.io/badge/API-Live-brightgreen.svg)](https://anymex-preview-bot.onrender.com)

[Features](#-features) • [Commands](#-commands) • [API](#-rest-api) • [Data](#-data-storage) • [Setup](#-setup)

</div>

---

## Overview

AnymeX Preview Bot is the backbone of the AnymeX community Discord. It lets members submit underrated anime and manga recommendations, links their AniList and MAL profiles, manages GitHub build workflows, and keeps the team in sync across timezones. All data is stored as JSON files directly in your GitHub repository — no database needed.

### Key Highlights

- 🎌 **Underrated Anime & Manga List** — Members submit recommendations linked to their AniList/MAL profiles
- 👤 **Profile System** — Link AniList and MAL accounts with full stats sync
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

Members link their AniList and/or MAL accounts once via `/setup`. The bot fetches and stores their full profile — avatar, stats, anime/manga counts, mean score — and uses it to attribute all submissions correctly.

The **repopulator** runs on startup and weekly to keep all profile data fresh. It re-fetches every user's AniList and MAL profile and syncs the updated info into all anime and manga entries automatically.

---

### 🎌 Underrated Anime & Manga

The core feature. Members submit anime and manga they think are underrated, with a reason. Each entry is stored with:

```json
{
  "anilist_id": 74489,
  "mal_id": 44489,
  "title": "Houseki no Kuni",
  "author": "ASheby",
  "reason": "Beautifully illustrated philosophical story...",
  "user": {
    "discord": { "id": "...", "username": "...", "avatar": "..." },
    "anilist": { "id": 5724017, "username": "ASheby", "avatar": "..." },
    "mal":     { "id": 13598844, "username": "ASheby", "avatar": "..." }
  },
  "poster": "https://s4.anilist.co/...",
  "score": 89
}
```

Posters and scores are fetched directly from AniList. Submissions go through a confirmation step before being committed to GitHub.

---

### 🗳️ Voting System

Members can upvote or downvote any entry in the list. Votes are tracked per user (using their AniList or MAL ID) with a 5-minute cooldown per item. Toggling the same direction removes the vote. Switching direction moves the vote automatically.

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

A built-in HTTP server exposes endpoints so external apps (like the AnymeX app) can interact with the bot's data directly.

Base URL: `https://anymex-preview-bot.onrender.com`

All write endpoints require:
```
Authorization: Bearer YOUR_API_SECRET
Content-Type: application/json
```

---

## 📚 Commands

### 👤 Profile

| Command | Description | Permission |
|---------|-------------|------------|
| `/setup [anilist_username] [mal_username]` | Link your AniList and/or MAL accounts | Everyone |
| `/myprofile` | View your saved profile and stats | Everyone |
| `/repopulate` | Manually refresh all profiles and sync entries | Admin |

---

### 🎌 Anime & Manga Submissions

| Command | Description | Permission |
|---------|-------------|------------|
| `/add_anime [title] [reason]` | Submit an underrated anime (with autocomplete) | Everyone |
| `/add_manga [title] [reason]` | Submit an underrated manga (with autocomplete) | Everyone |
| `/list_anime` | View the underrated anime list | Everyone |
| `/list_manga` | View the underrated manga list | Everyone |
| `/remove_anime [title or id]` | Remove an anime from the list | Mod |
| `/remove_manga [title or id]` | Remove a manga from the list | Mod |

---

### 🗳️ Voting

| Command | Description | Permission |
|---------|-------------|------------|
| `/vote_anime [title] [👍/👎]` | Upvote or downvote an anime entry | Everyone |
| `/vote_manga [title] [👍/👎]` | Upvote or downvote a manga entry | Everyone |
| `/vote_stats [anime/manga]` | View the vote leaderboard | Everyone |
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

## 🌐 REST API

Base URL: `https://anymex-preview-bot.onrender.com`

### Authentication

All write endpoints require a Bearer token:
```
Authorization: Bearer YOUR_API_SECRET
```

---

### Endpoints

#### `GET /health`
Health check. Returns `✅ Bot is running!`

---

#### `POST /api/add_anime`
Add an anime to the underrated list.

**Body:**
```json
{
  "anilist_id": 74489,
  "author": "ASheby",
  "reason": "Why it's underrated",
  "anilist_user_id": 5724017,
  "mal_user_id": 13598844,
  "mal_id": 44489
}
```

**Response `201`:**
```json
{
  "success": true,
  "entry": { "anilist_id": 74489, "title": "...", "poster": "...", "score": 89, ... }
}
```

**Error responses:** `400` missing fields, `404` not found on AniList, `409` already in list, `500` GitHub write failed.

---

#### `POST /api/add_manga`
Same as `/api/add_anime` but for manga.

---

#### `POST /api/vote/anime/{anilist_id}`
Cast a vote on an anime entry.

**Body:**
```json
{
  "anilist_user_id": 5724017,
  "direction": "up",
  "display_name": "ASheby"
}
```

Use `"mal_user_id"` instead of `"anilist_user_id"` if the user only has MAL.  
`direction` must be `"up"` or `"down"`. Voting the same direction again removes the vote.

**Response `200`:**
```json
{
  "success": true,
  "action": "added_up",
  "title": "Houseki no Kuni",
  "upvotes": 5,
  "downvotes": 1,
  "net": 4
}
```

**Error responses:** `400` bad input, `401` unauthorized, `404` not in list, `429` rate limited (5 min cooldown).

---

#### `POST /api/vote/manga/{anilist_id}`
Same as vote anime but for manga.

---

#### `GET /api/votes/anime/{anilist_id}`
Get vote counts for an anime entry.

**Response `200`:**
```json
{
  "media_type": "anime",
  "anilist_id": 74489,
  "title": "Houseki no Kuni",
  "total_upvotes": 5,
  "total_downvotes": 1,
  "net": 4,
  "upvoters": ["al:5724017"],
  "downvoters": []
}
```

---

#### `GET /api/votes/manga/{anilist_id}`
Same as above but for manga.

---

#### `GET /api/votes/leaderboard?type=anime&limit=10`
Get the vote leaderboard.

**Query params:**
- `type` — `anime` or `manga` (default: `anime`)
- `limit` — max results, up to 50 (default: `10`)

**Response `200`:**
```json
{
  "media_type": "anime",
  "leaderboard": [
    { "rank": 1, "anilist_id": 74489, "title": "...", "total_upvotes": 5, "total_downvotes": 1, "net": 4 }
  ]
}
```

---

## 💾 Data Storage

All data is stored as JSON files in your GitHub repository, auto-created on first startup:

| File | Description |
|------|-------------|
| `users.json` | User profiles — AniList/MAL IDs, usernames, avatars, stats |
| `underrated_anime.json` | Community underrated anime submissions |
| `underrated_manga.json` | Community underrated manga submissions |
| `votes.json` | Upvote/downvote records per media entry |
| `timezones.json` | User timezone preferences |
| `prefixes.json` | Bot command prefix list |
| `server_config.json` | Per-server allowed roles configuration |

---

## 🔐 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `GITHUB_TOKEN` | ✅ | GitHub PAT with `repo` + `workflow` permissions |
| `API_SECRET` | ✅ | Bearer token for REST API authentication |
| `REPOPULATOR_CHANNEL_ID` | ✅ | Discord channel ID for repopulator reports |
| `PORT` | ❌ | HTTP server port (default: `8080`) |
| `PROXY_HOST` | ❌ | Proxy host (optional) |
| `PROXY_PORT` | ❌ | Proxy port (optional) |
| `PROXY_USER` | ❌ | Proxy username (optional) |
| `PROXY_PASS` | ❌ | Proxy password (optional) |

---

## 📥 Setup

### Prerequisites

- Python 3.11+
- Discord bot token with `message_content` and `members` intents enabled
- GitHub personal access token with `repo` and `workflow` permissions

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
3. Run `/setup` to link your AniList/MAL profile
4. Run `/config_role action:add role:@YourModRole` to give mods access to restricted commands

---

## 🙏 Acknowledgments

- [discord.py](https://github.com/Rapptz/discord.py) — Discord API wrapper
- [AniList GraphQL API](https://anilist.co/graphql) — Anime/manga data and covers
- [Jikan API](https://jikan.moe/) — MAL profile data
- [GitHub REST API](https://docs.github.com/en/rest) — Repository and workflow management

---

<div align="center">

**Made with ❤️ for the AnymeX community by [Shebyyy](https://github.com/Shebyyy)**

[⬆ Back to Top](#-anymex-preview-bot)

</div>
