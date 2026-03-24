<div align="center">

# 🤖 AnymeX Preview Bot

**A Powerful Multi-Server Discord Bot with Advanced Moderation, AniList Integration & GitHub Management**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3.2-blue.svg)](https://github.com/Rapptz/discord.py)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[Features](#-features) • [Installation](#-installation) • [Commands](#-commands) • [Configuration](#-configuration) • [Contributing](#-contributing)

</div>

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#-features)
  - [🍯 Honeypot System](#-honeypot-system)
  - [⚠️ Warning System](#️-warning-system)
  - [🔨 Moderation Commands](#-moderation-commands)
  - [🤖 Auto-Moderation](#-auto-moderation)
  - [📝 Logging System](#-logging-system)
  - [📺 AniList Integration](#-anilist-integration)
  - [🛠️ Utilities](#️-utilities)
  - [🌍 Timezone System](#-timezone-system)
  - [🔧 GitHub Integration](#-github-integration)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Commands Reference](#-commands)
- [Data Storage](#-data-storage)
- [Environment Variables](#-environment-variables)
- [Contributing](#-contributing)

---

## Overview

AnymeX Preview Bot is a feature-rich Discord bot designed for anime communities and development teams. It combines powerful moderation tools with AniList integration and GitHub workflow management.

### Key Highlights

- 🍯 **Honeypot Trap System** — Catch raiders and spammers automatically
- 🤖 **Auto-Moderation** — Spam, invite, link, caps, and mention filters
- 📺 **AniList Integration** — Search anime, manga, characters, staff, and more
- 🔧 **GitHub Integration** — Trigger builds, create releases, manage repos
- 🌍 **Multi-Server Support** — Each server has its own configuration stored in JSON
- 💾 **GitHub Storage** — All data persists in your GitHub repository as JSON files
- ⌨️ **Dual Command System** — Every command available as both slash `/` and prefix `?`

---

## 🚀 Features

### 🍯 Honeypot System

A trap system to catch malicious users. When someone sends a message in a honeypot channel:

| Feature | Description |
|---------|-------------|
| 🦵 **Kick** | Kick the user from the server |
| 🔨 **Ban** | Ban the user permanently |
| 🔇 **Mute** | Timeout the user for 24 hours |
| 🗑️ **Soft Ban** | Ban then immediately unban (clears messages) |
| 📨 **DM Notification** | Customizable DM sent before punishment |
| 🧹 **Message Sweep** | Deletes all user messages from the last 24h across all channels |
| 📋 **Logging** | All incidents logged to the mod-log channel and `mod_cases.json` |

---

### ⚠️ Warning System

A comprehensive warning system with automatic punishments:

| Feature | Description |
|---------|-------------|
| **Thresholds** | Set warning counts that trigger auto-mute or auto-ban |
| **Auto-Action** | Automatically mutes or bans when threshold is reached |
| **Expiration** | Warnings expire after a configurable number of days (default: 30) |
| **Per-Server** | All warnings are stored separately per server |
| **Case Logging** | Every warn action creates a numbered mod case |

---

### 🔨 Moderation Commands

| Command | Description |
|---------|-------------|
| `/kick @user [reason]` | Kick a user |
| `/ban @user [reason] [delete_days]` | Ban a user |
| `/unban [user_id]` | Unban a user by ID |
| `/mute @user [duration_minutes] [reason]` | Timeout a user |
| `/unmute @user` | Remove timeout from a user |
| `/tempban @user [duration_hours] [reason]` | Temporary ban — auto-unbans via reminder task |
| `/purge [amount] [@user]` | Bulk delete messages (max 100) |
| `/slowmode [seconds]` | Set channel slowmode (0 to disable) |

All moderation actions are logged to the configured mod-log channel and saved to `mod_cases.json`.

---

### 🤖 Auto-Moderation

Automatic filters to protect your server, all configurable per-server via `/automod`:

| Filter | What it catches | Default Action |
|--------|-----------------|----------------|
| **Spam** | Messages exceeding rate limit | Mute |
| **Invite Links** | Any `discord.gg` or `discord.com/invite` URL | Delete |
| **Caps Filter** | Messages over configurable % caps | Delete |
| **Mention Spam** | Messages with too many mentions | Mute |
| **Blacklist** | Configurable word/phrase list | Delete |
| **URL Filter** | All URLs except whitelisted domains | Delete |

Each rule is independently toggled and has a configurable action (`delete`, `mute`, `kick`, `ban`).

---

### 📝 Logging System

Comprehensive event logging. Configure a mod-log channel and join/leave channel via `/server_config`.

| Event | Logged To |
|-------|-----------|
| Message Deleted | Mod Log |
| Message Edited | Mod Log |
| User Joined | Join/Leave Channel |
| User Left | Join/Leave Channel |
| Voice State Change | Mod Log |
| Kick / Ban / Mute / Warn | Mod Log + `mod_cases.json` |
| Honeypot Trigger | Mod Log + `mod_cases.json` |
| AutoMod Action | Mod Log |

---

### 📺 AniList Integration

Search and browse anime/manga data directly from Discord:

| Command | Description |
|---------|-------------|
| `/anime_search [title]` | Search anime with score, genres, episode count, description |
| `/manga_search [title]` | Search manga with score, chapters, genres, description |
| `/anilist_profile [username]` | View AniList user stats (anime count, days watched, manga read) |
| `/character_search [name]` | Get character info and which shows they appear in |
| `/staff_search [name]` | Get staff info, occupations, and bio |
| `/airing_schedule` | View upcoming episode air times with Discord timestamps |
| `/seasonal_anime [season] [year]` | Browse seasonal anime list with scores |

---

### 🛠️ Utilities

| Command | Description |
|---------|-------------|
| `/poll [question] [options]` | Create a reaction poll (comma-separated options, max 9) |
| `/remind [minutes] [message]` | Set a reminder — bot DMs you when time is up |
| `/userinfo [@user]` | View user info: ID, roles, join date, account age |
| `/serverinfo` | View server info: members, channels, roles, boost tier |
| `/avatar [@user]` | Get full-size avatar image |

---

### 🌍 Timezone System

Coordinate with team members across timezones:

| Command | Description |
|---------|-------------|
| `/set_timezone [timezone]` | Set your timezone (autocomplete supported) |
| `/my_time` | Check your current local time |
| `/friend_time @user` | Check a friend's current time |
| `/friend_compare @user` | See the hour difference between you and a friend |
| `/list_friends` | Show all team members' current times |
| `/timezone_list` | Browse all supported timezones by region |
| `/timezone_convert [from] [to] [HH:MM]` | Convert a time between two zones |
| `/timezone_stats` | See timezone distribution across the server |
| `/night_mode @user` | Check if a friend is likely sleeping |
| `/similar_timezone` | Find members within 2 hours of your timezone |
| `/world_clock` | Show current time for all unique team timezones |
| `/setup_timezone_menu [channel]` | Post an interactive dropdown for members to self-assign timezone |

All timezone data is stored in `timezones.json`.

---

### 🔧 GitHub Integration

Manage your GitHub repository from Discord:

| Command | Description |
|---------|-------------|
| `/build [platforms] [type]` | Trigger a GitHub Actions workflow dispatch |
| `/create_tag [tag] [message]` | Create an annotated Git tag on the beta branch |
| `/delete_tag [tag]` | Delete a Git tag and its associated release |
| `/latest_run` | Check the latest workflow run status (with cancel button if running) |

**Supported build platforms:** `all`, `android`, `linux`, `windows`, `macos`, `ios`, and combinations.
**Build types:** `alpha`, `stable`

---

## 📥 Installation

### Prerequisites

- Python 3.11+
- Docker (optional)
- GitHub personal access token (`repo` + `workflow` permissions)
- Discord bot token (with `message_content` and `members` intents enabled)

### Quick Start

1. **Clone the repository**
```bash
git clone https://github.com/Shebyyy/AnymeX-Preview-Bot.git
cd AnymeX-Preview-Bot
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set environment variables**
```bash
export DISCORD_TOKEN="your_discord_bot_token"
export GITHUB_TOKEN="your_github_personal_access_token"
```

4. **Run the bot**
```bash
python bot.py
```

### Docker Deployment

```bash
docker build -t anymex-bot .
docker run -d \
  -e DISCORD_TOKEN="your_token" \
  -e GITHUB_TOKEN="your_gh_token" \
  -p 8080:8080 \
  anymex-bot
```

### Render Deployment

1. Connect your GitHub repository to Render
2. Set `DISCORD_TOKEN` and `GITHUB_TOKEN` in the environment variables dashboard
3. Deploy — the health server on port 8080 keeps the instance alive automatically

---

## ⚙️ Configuration

### First-Time Setup

After inviting the bot, run:

```
/server_config
```

This displays the current server config. Use the parameters to set up your channels and roles.

### Setting Up Channels & Roles

```
/server_config mod_log_channel:#mod-logs join_leave_channel:#member-log mute_role:@Muted
/config_role action:add role:@Moderator
```

### Setting Up Honeypot

```
/honeypot_set channel:#honeypot-trap punishment:ban
/honeypot_set channel:#honeypot-trap punishment:kick dm_message:You triggered a restricted area.
```

### Setting Up Auto-Moderation

```
/automod rule:spam enabled:true threshold:5 action:mute
/automod rule:invite_links enabled:true action:delete
/automod rule:caps_filter enabled:true threshold:70 action:delete
/automod rule:blacklist enabled:true words:word1,word2,word3
/automod rule:url_filter enabled:true whitelist_domains:youtube.com,imgur.com
```

### Setting Warning Thresholds

```
/server_config warn_mute_threshold:3 warn_ban_threshold:5 warn_expiry_days:30
```

### Setting Bot Prefix

```
?setprefix add !
?setprefix remove ?
?setprefix list
```

---

## 📚 Commands

### ⚙️ Server Configuration

| Command | Description | Permission |
|---------|-------------|------------|
| `/server_config [options]` | View and update server settings | Admin |
| `/config_role action:add/remove role:@Role` | Add/remove allowed mod roles | Admin |
| `/setup_timezone_menu [channel]` | Post self-serve timezone dropdown | Admin |

### 🍯 Honeypot

| Command | Description | Permission |
|---------|-------------|------------|
| `/honeypot_set [channel] [punishment]` | Configure a honeypot channel | Admin |
| `/honeypot_remove [channel]` | Remove a honeypot channel | Admin |
| `/honeypot_list` | List all configured honeypot channels | Admin |

### ⚠️ Warnings

| Command | Description | Permission |
|---------|-------------|------------|
| `/warn @user [reason]` | Warn a user | Mod |
| `/warnings @user` | View a user's warnings | Mod |
| `/clearwarnings @user [index]` | Clear one or all warnings | Mod |

### 🔨 Moderation

| Command | Description | Permission |
|---------|-------------|------------|
| `/kick @user [reason]` | Kick user | Mod |
| `/ban @user [reason] [delete_days]` | Ban user | Mod |
| `/unban [user_id]` | Unban user | Mod |
| `/mute @user [duration_minutes] [reason]` | Timeout user | Mod |
| `/unmute @user` | Remove timeout | Mod |
| `/tempban @user [duration_hours] [reason]` | Temporary ban | Mod |
| `/purge [amount] [@user]` | Bulk delete messages | Mod |
| `/slowmode [seconds]` | Set channel slowmode | Mod |

### 🤖 Auto-Moderation

| Command | Description | Permission |
|---------|-------------|------------|
| `/automod [rule] [options]` | Configure automod filters | Admin |

### 📺 AniList

| Command | Description | Permission |
|---------|-------------|------------|
| `/anime_search [title]` | Search anime | Everyone |
| `/manga_search [title]` | Search manga | Everyone |
| `/anilist_profile [username]` | View AniList user profile | Everyone |
| `/character_search [name]` | Search character | Everyone |
| `/staff_search [name]` | Search staff | Everyone |
| `/airing_schedule` | Upcoming episode schedule | Everyone |
| `/seasonal_anime [season] [year]` | Seasonal anime list | Everyone |

### 🛠️ Utilities

| Command | Description | Permission |
|---------|-------------|------------|
| `/poll [question] [options]` | Create a reaction poll | Everyone |
| `/remind [minutes] [message]` | Set a reminder | Everyone |
| `/userinfo [@user]` | View user info | Everyone |
| `/serverinfo` | View server info | Everyone |
| `/avatar [@user]` | Get user avatar | Everyone |

### 🌍 Timezone

| Command | Description | Permission |
|---------|-------------|------------|
| `/set_timezone [tz]` | Set your timezone | Everyone |
| `/remove_timezone` | Remove your timezone | Everyone |
| `/my_time` | Check your local time | Everyone |
| `/friend_time @user` | Check a friend's time | Everyone |
| `/friend_compare @user` | Time diff with friend | Everyone |
| `/list_friends` | All team member times | Everyone |
| `/add_friend_timezone @user [tz]` | Set a friend's timezone | Everyone |
| `/timezone_list` | View all timezones | Everyone |
| `/timezone_convert [from] [to] [time]` | Convert time between zones | Everyone |
| `/timezone_stats` | Timezone distribution | Everyone |
| `/night_mode @user` | Is friend sleeping? | Everyone |
| `/similar_timezone` | Find nearby timezones | Everyone |
| `/world_clock` | Team world clock | Everyone |

### 🔧 GitHub

| Command | Description | Permission |
|---------|-------------|------------|
| `/build [platforms] [type]` | Trigger build workflow | Mod |
| `/create_tag [tag] [message]` | Create Git tag | Mod |
| `/delete_tag [tag]` | Delete Git tag + release | Mod |
| `/latest_run` | View latest run status | Mod |

### 👤 Profile (AniList/MAL Linking)

| Command | Description | Permission |
|---------|-------------|------------|
| `/setup [anilist_id] [mal_id]` | Link your accounts | Everyone |
| `/myprofile` | View your saved profile | Everyone |
| `/add_anime [anilist_url] [mal_url] [reason]` | Submit underrated anime | Everyone |
| `/add_manga [anilist_url] [mal_url] [reason]` | Submit underrated manga | Everyone |
| `/list_anime` | View underrated anime list | Mod |
| `/list_manga` | View underrated manga list | Mod |
| `/remove_anime [title/id]` | Remove from anime list | Mod |
| `/remove_manga [title/id]` | Remove from manga list | Mod |

---

## 💾 Data Storage

All data is stored in your GitHub repository as JSON files, auto-created on first startup:

| File | Description |
|------|-------------|
| `server_config.json` | Per-server settings (channels, roles, warn thresholds) |
| `warnings.json` | User warning history per server |
| `honeypot.json` | Honeypot channel configurations per server |
| `automod.json` | AutoMod rule settings per server |
| `reminders.json` | Pending reminders and scheduled tempban unbans |
| `mod_cases.json` | Full moderation case log per server |
| `users.json` | User profiles (AniList/MAL IDs) |
| `timezones.json` | User timezone data |
| `underrated_anime.json` | Community underrated anime submissions |
| `underrated_manga.json` | Community underrated manga submissions |
| `prefixes.json` | Bot prefix list |

---

## 🔐 Environment Variables

Only two environment variables are required. All other configuration is done through Discord commands and stored in GitHub JSON.

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ Yes | Discord bot token |
| `GITHUB_TOKEN` | ✅ Yes | GitHub personal access token (`repo` + `workflow`) |

> **Note:** `PORT` defaults to `8080` and is set internally. No other env vars are needed.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [discord.py](https://github.com/Rapptz/discord.py) — Discord API wrapper
- [AniList API](https://anilist.co/graphql) — Anime/Manga data
- [GitHub REST API](https://docs.github.com/en/rest) — Repository management

---

<div align="center">

**Made with ❤️ by [Shebyyy](https://github.com/Shebyyy)**

[⬆ Back to Top](#-anymex-preview-bot)

</div>
