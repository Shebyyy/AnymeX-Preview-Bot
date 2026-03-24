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
  - [📺 AniList/MAL Integration](#-anilistmal-integration)
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

AnymeX Preview Bot is a feature-rich Discord bot designed for anime communities and development teams. It combines powerful moderation tools with AniList/MAL integration and GitHub workflow management.

### Key Highlights

- 🍯 **Honeypot Trap System** - Catch raiders and spammers automatically
- 🤖 **Auto-Moderation** - Spam, invite, link, caps, and mention filters
- 📺 **AniList/MAL Integration** - Search anime, manga, characters, and more
- 🔧 **GitHub Integration** - Trigger builds, create releases, manage repos
- 🌍 **Multi-Server Support** - Each server has its own configuration
- 💾 **GitHub Storage** - All data persists in your GitHub repository

---

## 🚀 Features

### 🍯 Honeypot System

A powerful trap system to catch malicious users. When someone sends a message in a honeypot channel:

| Action | Description |
|--------|-------------|
| 🦵 **Kick** | Kick the user from the server |
| 🔨 **Ban** | Ban the user permanently |
| 🔇 **Mute** | Mute the user for a set duration |
| 🗑️ **Message Deletion** | Delete all messages from the user in the last X hours |
| 📨 **DM Notification** | Send a customizable DM before taking action |
| 📋 **Logging** | Log all honeypot triggers to a specified channel |

**Configuration:**
```
/honeypot channel:#trap action:kick delete_hours:24
/honeypot whitelist_role:Admin log_channel:#logs
/honeypot dm_message:You have been caught in a restricted area.
```

---

### ⚠️ Warning System

A comprehensive warning system with automatic punishments:

| Feature | Description |
|---------|-------------|
| **Threshold** | Set how many warnings before action (default: 3) |
| **Auto-Action** | Automatically mute/kick/ban when threshold reached |
| **Expiration** | Warnings expire after X days (default: 30) |
| **Logging** | All warnings are logged and viewable |

**Commands:**
```
/warn @user Breaking rules
/warnings @user
/warnconfig threshold:3 action:mute expire_days:30
```

---

### 🔨 Moderation Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/mute @user [duration] [reason]` | Mute a user | Mod+ |
| `/unmute @user` | Unmute a user | Mod+ |
| `/kick @user [reason]` | Kick a user | Mod+ |
| `/ban @user [reason]` | Ban a user | Admin+ |
| `/unban [user_id]` | Unban a user | Admin+ |
| `/tempban @user [hours] [reason]` | Temporary ban | Admin+ |
| `/purge [amount] [@user]` | Delete messages | Mod+ |
| `/slowmode [seconds]` | Set slowmode | Mod+ |
| `/lockdown` | Lock current channel | Mod+ |
| `/unlock` | Unlock channel | Mod+ |

---

### 🤖 Auto-Moderation

Automatic filters to protect your server:

| Filter | Default Settings | Action |
|--------|------------------|--------|
| **Spam Protection** | 5 messages in 3 seconds | Mute 10 min |
| **Discord Invites** | Any discord.gg link | Delete + Kick |
| **Link Filter** | All URLs | Delete |
| **Caps Filter** | 70%+ caps (10+ chars) | Delete |
| **Mass Mention** | 5+ mentions | Mute 30 min |

**Commands:**
```
/automod spam enabled:true max_value:5 action:mute
/automod invites enabled:true action:kick
/automod caps enabled:true max_value:70
/automod all enabled:true
```

---

### 📝 Logging System

Comprehensive logging to keep track of all server activity:

| Event | Logged |
|-------|--------|
| Message Delete | ✅ |
| Message Edit | ✅ |
| User Join | ✅ |
| User Leave | ✅ |
| User Ban | ✅ |
| User Kick | ✅ |
| User Mute | ✅ |
| Honeypot Trigger | ✅ |
| Moderation Actions | ✅ |

---

### 📺 AniList/MAL Integration

Search and browse anime/manga data:

| Command | Description |
|---------|-------------|
| `/anime [title]` | Search for anime with details |
| `/manga [title]` | Search for manga with details |
| `/character [name]` | Get character information |
| `/studio [name]` | Get studio info with anime list |
| `/seasonal [season] [year]` | Browse seasonal anime |
| `/airing [anime_id]` | Get airing schedule |
| `/random_anime` | Get random anime recommendation |
| `/anilist_stats [user_id]` | View AniList user statistics |

---

### 🛠️ Utilities

| Command | Description |
|---------|-------------|
| `/snipe` | View last deleted message |
| `/userinfo [@user]` | Get user information |
| `/serverinfo` | Get server information |
| `/modlog [@user]` | View moderation history |
| `/setup [anilist_id] [mal_id]` | Link your accounts |
| `/myprofile` | View your profile |
| `/prefix [new_prefix]` | Change server prefix |

---

### 🌍 Timezone System

Coordinate with team members across timezones:

| Command | Description |
|---------|-------------|
| `/set_timezone [timezone]` | Set your timezone |
| `/my_time` | Check your current time |
| `/timezone_list` | View all timezones |

---

### 🔧 GitHub Integration

Manage your GitHub repository from Discord:

| Command | Description | Permission |
|---------|-------------|------------|
| `/build [platform] [type]` | Trigger GitHub Actions workflow | Mod+ |
| `/create_tag [tag] [message]` | Create a new release tag | Admin+ |

**Supported Platforms:**
- `all` - Build all platforms
- `android` - Android APK
- `linux` - Linux AppImage
- `windows` - Windows EXE
- `macos` - macOS DMG
- `ios` - iOS IPA

---

## 📥 Installation

### Prerequisites

- Python 3.11+
- Docker (optional)
- GitHub account with personal access token
- Discord bot token

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

### Render/Heroku Deployment

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Connect your GitHub repository
2. Set environment variables in dashboard
3. Deploy!

---

## ⚙️ Configuration

### Initial Setup

After inviting the bot to your server:

```
/server_setup
```

This creates a default configuration for your server.

### Setting Up Honeypot

```
/honeypot channel:#honeypot-trap action:kick delete_hours:24
/honeypot log_channel:#mod-logs
/honeypot whitelist_role:Admin
```

### Setting Up Auto-Moderation

```
/automod all enabled:true
/automod spam max_value:5 action:mute
/automod invites action:kick
```

### Setting Up Permissions

```
/addperm role:Admin level:admin
/addperm role:Moderator level:mod
/addperm role:Trusted level:trusted
```

### Setting Up Logging

```
/server_config setting:log_channel value:#mod-logs
```

---

## 📚 Commands

### Server Configuration

| Command | Description | Permission |
|---------|-------------|------------|
| `/server_setup` | Initialize bot for server | Admin |
| `/server_config [setting] [value]` | View/modify settings | Admin |
| `/addperm @role [level]` | Add permission role | Admin |
| `/removeperm @role [level]` | Remove permission role | Admin |
| `/listperms` | List all permission roles | Everyone |

### Honeypot

| Command | Description | Permission |
|---------|-------------|------------|
| `/honeypot [options]` | Configure honeypot | Admin |
| `/honeypot_disable` | Disable honeypot | Admin |

### Warnings

| Command | Description | Permission |
|---------|-------------|------------|
| `/warn @user [reason]` | Warn a user | Mod+ |
| `/warnings @user` | View warnings | Mod+ |
| `/clearwarnings @user` | Clear warnings | Admin |
| `/warnconfig [options]` | Configure warnings | Admin |

### Moderation

| Command | Description | Permission |
|---------|-------------|------------|
| `/mute @user [duration] [reason]` | Mute user | Mod+ |
| `/unmute @user` | Unmute user | Mod+ |
| `/kick @user [reason]` | Kick user | Mod+ |
| `/ban @user [reason]` | Ban user | Admin |
| `/unban [user_id]` | Unban user | Admin |
| `/tempban @user [hours] [reason]` | Temporary ban | Admin |

### Auto-Moderation

| Command | Description | Permission |
|---------|-------------|------------|
| `/automod [filter] [options]` | Configure filters | Admin |

### Utilities

| Command | Description | Permission |
|---------|-------------|------------|
| `/purge [amount] [@user]` | Delete messages | Mod+ |
| `/slowmode [seconds]` | Set slowmode | Mod+ |
| `/lockdown` | Lock channel | Mod+ |
| `/unlock` | Unlock channel | Mod+ |
| `/snipe` | View deleted message | Everyone |
| `/userinfo [@user]` | User info | Everyone |
| `/serverinfo` | Server info | Everyone |
| `/modlog [@user]` | Mod history | Mod+ |

### AniList/MAL

| Command | Description | Permission |
|---------|-------------|------------|
| `/anime [title]` | Search anime | Everyone |
| `/manga [title]` | Search manga | Everyone |
| `/character [name]` | Search character | Everyone |
| `/studio [name]` | Search studio | Everyone |
| `/seasonal [season] [year]` | Seasonal anime | Everyone |
| `/airing [anime_id]` | Airing schedule | Everyone |
| `/random_anime` | Random anime | Everyone |
| `/anilist_stats [user_id]` | User stats | Everyone |

### GitHub

| Command | Description | Permission |
|---------|-------------|------------|
| `/build [platform] [type]` | Trigger build | Mod+ |
| `/create_tag [tag] [message]` | Create release | Admin |

---

## 💾 Data Storage

All data is stored in your GitHub repository as JSON files:

| File | Description |
|------|-------------|
| `servers.json` | Multi-server configuration |
| `warnings.json` | User warnings per server |
| `mutes.json` | Active mutes and tempbans |
| `modlog.json` | Moderation action logs |
| `honeypot_logs.json` | Honeypot incident records |
| `snipe.json` | Deleted messages cache |
| `users.json` | User profiles (AniList/MAL IDs) |
| `timezones.json` | User timezone data |
| `underrated_anime.json` | Underrated anime list |
| `underrated_manga.json` | Underrated manga list |
| `prefixes.json` | Server prefixes |

---

## 🔐 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ Yes | Discord bot token |
| `GITHUB_TOKEN` | ✅ Yes | GitHub personal access token |
| `PORT` | ❌ No | Health server port (default: 8080) |

### GitHub Token Permissions

Your GitHub token needs these permissions:
- `repo` - Full repository access
- `workflow` - Trigger workflows

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

- [discord.py](https://github.com/Rapptz/discord.py) - Discord API wrapper
- [AniList API](https://anilist.co/graphql) - Anime/Manga data
- [GitHub REST API](https://docs.github.com/en/rest) - Repository management

---

<div align="center">

**Made with ❤️ by [Shebyyy](https://github.com/Shebyyy)**

[⬆ Back to Top](#-anymex-preview-bot)

</div>
