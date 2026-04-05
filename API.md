<div align="center">

# AnymeX Preview Bot — API Reference

**Base URL:** `https://anymex-preview-bot.onrender.com`

</div>

---

## Authentication

All endpoints except `/health` require a Bearer token.

```
Authorization: Bearer YOUR_API_SECRET
Content-Type: application/json
```

Missing or wrong token returns:

```json
{ "error": "Unauthorized" }
```
`Status: 401`

---

## Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/health` | ❌ | Health check |
| `POST` | `/api/add_anime` | ✅ | Add an anime to the list |
| `POST` | `/api/add_manga` | ✅ | Add a manga to the list |
| `POST` | `/api/vote/anime/{media_id}` | ✅ | Vote on an anime entry |
| `POST` | `/api/vote/manga/{media_id}` | ✅ | Vote on a manga entry |
| `GET` | `/api/votes/anime/{media_id}` | ✅ | Get vote counts for an anime |
| `GET` | `/api/votes/manga/{media_id}` | ✅ | Get vote counts for a manga |
| `GET` | `/api/votes/leaderboard` | ✅ | Get vote leaderboard |

---

## `GET /health`

Health check. No auth required.

**Response `200`**
```
✅ Bot is running!
```

---

## `POST /api/add_anime`

Add an anime to the underrated anime list. Title, poster, and score are fetched automatically from AniList using the `anilist_id`.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `anilist_id` | `int` | ✅ Required | AniList media ID |
| `reason` | `string` | ✅ Required | Why this anime is underrated |
| `anilist_user_id` | `int` | ⚠️ One of these | Submitter's AniList user ID |
| `mal_user_id` | `int` | ⚠️ One of these | Submitter's MAL user ID |
| `author` | `string` | ❌ Optional | Display name — falls back to AniList username → MAL username → `"Unknown"` |
| `mal_id` | `int` | ❌ Optional | MAL media ID — auto-resolved from AniList if omitted |
| `anilist_username` | `string` | ❌ Optional | Submitter's AniList username — only used if user is not in `users.json` |
| `mal_username` | `string` | ❌ Optional | Submitter's MAL username — only used if user is not in `users.json` |

> If the user exists in `users.json` (registered via `/setup` in Discord), their full profile including avatar and stats is used automatically. If not, a minimal snapshot is built from the request body fields.

**Example Request — minimal**
```json
{
  "anilist_id": 74489,
  "reason": "Beautifully illustrated philosophical story about identity and change",
  "anilist_user_id": 5724017
}
```

**Example Request — full**
```json
{
  "anilist_id": 74489,
  "reason": "Beautifully illustrated philosophical story about identity and change",
  "anilist_user_id": 5724017,
  "mal_user_id": 13598844,
  "author": "ASheby",
  "mal_id": 44489
}
```

### Responses

**`201` — Success**
```json
{
  "success": true,
  "entry": {
    "anilist_id": 74489,
    "mal_id": 44489,
    "title": "Houseki no Kuni",
    "author": "ASheby",
    "reason": "Beautifully illustrated philosophical story about identity and change",
    "user": {
      "discord": {
        "id": 612532963938271232,
        "username": "asheby",
        "avatar": "https://cdn.discordapp.com/avatars/612532963938271232/..."
      },
      "anilist": {
        "id": 5724017,
        "username": "ASheby",
        "avatar": "https://s4.anilist.co/file/anilistcdn/user/avatar/large/b5724017-..."
      },
      "mal": {
        "id": 13598844,
        "username": "ASheby",
        "avatar": "https://cdn.myanimelist.net/s/common/userimages/..."
      }
    },
    "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx74489-...",
    "score": 89
  }
}
```

**`400` — Missing or invalid fields**
```json
{ "error": "Missing required fields: reason" }
```
```json
{ "error": "Provide at least one of: anilist_user_id, mal_user_id" }
```
```json
{ "error": "anilist_id must be an integer" }
```
```json
{ "error": "Invalid JSON body" }
```

**`401` — Unauthorized**
```json
{ "error": "Unauthorized" }
```

**`404` — Not found on AniList**
```json
{ "error": "Could not find anime with anilist_id=99999 on AniList" }
```

**`409` — Already in list**
```json
{ "error": "Houseki no Kuni is already in the list", "title": "Houseki no Kuni" }
```

**`500` — GitHub write failed**
```json
{ "error": "Failed to write to GitHub" }
```

---

## `POST /api/add_manga`

Identical to `/api/add_anime` but adds to the underrated manga list. Same request body, same responses.

**Example Request**
```json
{
  "anilist_id": 30936,
  "reason": "A psychological thriller exploring the human psyche through surreal hallucinations",
  "anilist_user_id": 5724017,
  "mal_user_id": 13598844
}
```

**`201` — Success**
```json
{
  "success": true,
  "entry": {
    "anilist_id": 30936,
    "mal_id": 936,
    "title": "Homunculus",
    "author": "ASheby",
    "reason": "A psychological thriller exploring the human psyche through surreal hallucinations",
    "user": {
      "discord": { "id": 612532963938271232, "username": "asheby", "avatar": "https://..." },
      "anilist": { "id": 5724017, "username": "ASheby", "avatar": "https://..." },
      "mal": { "id": 13598844, "username": "ASheby", "avatar": "https://..." }
    },
    "poster": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx30936-...",
    "score": 83
  }
}
```

---

## `POST /api/vote/anime/{media_id}`

Cast a vote on an anime entry. The `{media_id}` in the URL can be either an AniList ID or MAL ID — specify which using `id_type` in the body.

Voting the same direction again **removes** the vote. Switching direction **moves** the vote automatically. **5-minute cooldown** per user per item.

### URL Parameter

| Parameter | Type | Description |
|-----------|------|-------------|
| `media_id` | `int` | AniList ID or MAL ID of the anime |

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `direction` | `string` | ✅ Required | `"up"` or `"down"` |
| `anilist_user_id` | `int` | ⚠️ One of these | Voter's AniList user ID |
| `mal_user_id` | `int` | ⚠️ One of these | Voter's MAL user ID |
| `id_type` | `string` | ❌ Optional | `"anilist"` (default) or `"mal"` — how to interpret `{media_id}` |
| `display_name` | `string` | ❌ Optional | Voter's display name for commit logs (defaults to `"API User"`) |

**Example — vote by AniList ID**
```json
{
  "anilist_user_id": 5724017,
  "direction": "up",
  "display_name": "ASheby"
}
```

**Example — vote by MAL ID**
```json
{
  "mal_user_id": 13598844,
  "direction": "up",
  "id_type": "mal",
  "display_name": "ASheby"
}
```

### Responses

**`200` — Success**

The `action` field tells you exactly what happened:

| Action | Meaning |
|--------|---------|
| `added_up` | Upvote added |
| `added_down` | Downvote added |
| `switched_to_up` | Was downvoted, switched to upvote |
| `switched_to_down` | Was upvoted, switched to downvote |
| `removed_up` | Was upvoted, vote removed |
| `removed_down` | Was downvoted, vote removed |

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

**`400` — Invalid input**
```json
{ "error": "Provide at least one of: anilist_user_id, mal_user_id" }
```
```json
{ "error": "direction must be 'up' or 'down'" }
```
```json
{ "error": "id_type must be 'anilist' or 'mal'" }
```
```json
{ "error": "Invalid media_id in URL" }
```
```json
{ "error": "Invalid JSON body" }
```

**`401` — Unauthorized**
```json
{ "error": "Unauthorized" }
```

**`404` — Entry not in list**
```json
{ "error": "No anime with anilist_id=74489 found in the list." }
```
```json
{ "error": "No anime with mal_id=44489 found in the list." }
```

**`429` — Rate limited**
```json
{ "error": "Rate limited", "retry_after_seconds": 243.5 }
```

**`500` — GitHub write failed**
```json
{ "error": "Failed to save vote to GitHub." }
```

---

## `POST /api/vote/manga/{media_id}`

Identical to `/api/vote/anime/{media_id}` but for manga entries. Same request body, same responses.

---

## `GET /api/votes/anime/{media_id}`

Get current vote counts for a specific anime entry.

### URL Parameter

| Parameter | Type | Description |
|-----------|------|-------------|
| `media_id` | `int` | AniList ID or MAL ID of the anime |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `id_type` | `string` | ❌ Optional | `anilist` | `"anilist"` or `"mal"` — how to interpret `{media_id}` |

**Example — by AniList ID**
```
GET /api/votes/anime/74489
Authorization: Bearer YOUR_API_SECRET
```

**Example — by MAL ID**
```
GET /api/votes/anime/44489?id_type=mal
Authorization: Bearer YOUR_API_SECRET
```

### Responses

**`200` — Has votes**
```json
{
  "media_type": "anime",
  "anilist_id": 74489,
  "title": "Houseki no Kuni",
  "total_upvotes": 5,
  "total_downvotes": 1,
  "net": 4,
  "upvoters": ["al:5724017", "al:6201895", "mal:18232702"],
  "downvoters": ["al:7754776"]
}
```

> Voter IDs are prefixed with `al:` for AniList users and `mal:` for MAL-only users.

**`200` — No votes yet**
```json
{
  "media_type": "anime",
  "anilist_id": 74489,
  "total_upvotes": 0,
  "total_downvotes": 0,
  "net": 0,
  "upvoters": [],
  "downvoters": []
}
```

**`400` — Invalid input**
```json
{ "error": "Invalid media_id in URL" }
```
```json
{ "error": "id_type must be 'anilist' or 'mal'" }
```

**`401` — Unauthorized**
```json
{ "error": "Unauthorized" }
```

**`404` — Only returned when using `id_type=mal`**
```json
{ "error": "No anime with mal_id=99999 found." }
```

---

## `GET /api/votes/manga/{media_id}`

Identical to `/api/votes/anime/{media_id}` but for manga.

**`200` — Success**
```json
{
  "media_type": "manga",
  "anilist_id": 30936,
  "title": "Homunculus",
  "total_upvotes": 3,
  "total_downvotes": 0,
  "net": 3,
  "upvoters": ["al:5724017", "al:6335658", "al:7460497"],
  "downvoters": []
}
```

---

## `GET /api/votes/leaderboard`

Get the vote leaderboard sorted by net score descending.

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | `string` | ❌ Optional | `anime` | `"anime"` or `"manga"` |
| `limit` | `int` | ❌ Optional | `10` | Max results, capped at `50` |

**Example**
```
GET /api/votes/leaderboard?type=manga&limit=5
Authorization: Bearer YOUR_API_SECRET
```

### Responses

**`200` — Success**
```json
{
  "media_type": "manga",
  "leaderboard": [
    {
      "rank": 1,
      "anilist_id": 30936,
      "title": "Homunculus",
      "total_upvotes": 3,
      "total_downvotes": 0,
      "net": 3
    },
    {
      "rank": 2,
      "anilist_id": 74489,
      "title": "Houseki no Kuni",
      "total_upvotes": 5,
      "total_downvotes": 3,
      "net": 2
    }
  ]
}
```

**`400` — Invalid type**
```json
{ "error": "type must be 'anime' or 'manga'" }
```

**`401` — Unauthorized**
```json
{ "error": "Unauthorized" }
```

---

## Entry Schema

Every entry in the list follows this exact structure:

```json
{
  "anilist_id": 74489,
  "mal_id": 44489,
  "title": "Houseki no Kuni",
  "author": "ASheby",
  "reason": "Beautifully illustrated philosophical story about identity, purpose, and change",
  "user": {
    "discord": {
      "id": 612532963938271232,
      "username": "asheby",
      "avatar": "https://cdn.discordapp.com/avatars/612532963938271232/..."
    },
    "anilist": {
      "id": 5724017,
      "username": "ASheby",
      "avatar": "https://s4.anilist.co/file/anilistcdn/user/avatar/large/b5724017-..."
    },
    "mal": {
      "id": 13598844,
      "username": "ASheby",
      "avatar": "https://cdn.myanimelist.net/s/common/userimages/..."
    }
  },
  "poster": "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx74489-...",
  "score": 89
}
```

| Field | Type | Description |
|-------|------|-------------|
| `anilist_id` | `int` | AniList media ID |
| `mal_id` | `int \| null` | MAL media ID — null if not resolvable |
| `title` | `string` | English title, falls back to romaji then native |
| `author` | `string` | Submitter's display name |
| `reason` | `string` | Why this is underrated |
| `user.discord` | `object` | Submitter's Discord info — fields may be null if not synced |
| `user.anilist` | `object` | Submitter's AniList info — null fields if not linked |
| `user.mal` | `object` | Submitter's MAL info — null fields if not linked |
| `poster` | `string \| null` | AniList cover image URL |
| `score` | `int \| null` | AniList average score out of 100 |
