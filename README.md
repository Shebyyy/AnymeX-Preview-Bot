---
title: Discord GitHub Bot
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# Discord GitHub Manager Bot

A Discord bot to manage GitHub repositories using slash commands.

## Slash Commands

| Command | Description |
|---|---|
| `/run_workflow` | Trigger a GitHub Actions workflow manually |
| `/create_tag` | Create a new Git tag/release |
| `/update_file` | Update or create a file in a repo |
| `/list_workflows` | List all workflows in a repo |

## Setup (Secrets)

Add these in **Settings → Variables and Secrets**:

| Secret | Value |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |
| `GITHUB_TOKEN` | Your GitHub personal access token |
| `GITHUB_OWNER` | Your GitHub username |
