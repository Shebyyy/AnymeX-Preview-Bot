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
| `POST` | `/api/add_show` | ✅ | Add a TV show to the list |
| `POST` | `/api/add_movie` | ✅ | Add a movie to the list |
| `POST` | `/api/vote/anime/{media_id}` | ✅ | Vote on an anime entry |
| `POST` | `/api/vote/manga/{media_id}` | ✅ | Vote on a manga entry |
| `POST` | `/api/vote/show/{media_id}` | ✅ | Vote on a TV show entry |
| `POST` | `/api/vote/movie/{media_id}` | ✅ | Vote on a movie entry |
| `GET` | `/api/votes/anime/{media_id}` | ✅ | Get vote counts for an anime |
| `GET` | `/api/votes/manga/{media_id}` | ✅ | Get vote counts for a manga |
| `GET` | `/api/votes/show/{media_id}` | ✅ | Get vote counts for a TV show |
| `GET` | `/api/votes/movie/{media_id}` | ✅ | Get vote counts for a movie |
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

Add an anime to the underrated anime list. Title, poster, and score are fetched automatically.

### ID Resolution Flow

When you provide an ID, the bot resolves data in this order:

1. **If `anilist_id` provided** → Fetch from AniList directly
2. **If only `mal_id` provided** → Try AniList's `idMal` lookup first → If not on AniList, fall back to **Jikan API** (MAL data)
3. **Cross-reference** → The other ID is auto-resolved when possible

This means entries not on AniList will still get proper title, poster, and score from MAL via Jikan.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `anilist_id` | `int` | ⚠️ One of these | AniList media ID |
| `mal_id` | `int` | ⚠️ One of these | MAL media ID — resolved via AniList idMal or Jikan |
| `reason` | `string` | ✅ Required | Why this anime is underrated |
| `anilist_user_id` | `int` | ⚠️ One of these | Submitter's AniList user ID |
| `mal_user_id` | `int` | ⚠️ One of these | Submitter's MAL user ID |
| `author` | `string` | ❌ Optional | Display name — falls back to AniList username → MAL username → `"Unknown"` |
| `anilist_username` | `string` | ❌ Optional | Only used if user is not in `users.json` |
| `mal_username` | `string` | ❌ Optional | Only used if user is not in `users.json` |

> If the user exists in `users.json` (registered via `/setup` in Discord), their full profile including avatar and stats is used automatically.

**Example Request — with AniList ID**
```json
{
  "anilist_id": 74489,
  "reason": "Beautifully illustrated philosophical story about identity and change",
  "anilist_user_id": 5724017
}
```

**Example Request — with MAL ID only**
```json
{
  "mal_id": 147172,
  "reason": "The action scenes are pure goosebumps and the art is insane",
  "anilist_user_id": 778172
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
      "discord": { "id": 612532963938271232, "username": "asheby", "avatar": "https://..." },
      "anilist": { "id": 5724017, "username": "ASheby", "avatar": "https://..." },
      "mal": { "id": 13598844, "username": "ASheby", "avatar": "https://..." },
      "simkl": { "username": null }
    },
    "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx74489-...",
    "score": 89
  }
}
```

**Error responses:** `400` missing fields, `401` unauthorized, `404` not found on AniList or MAL, `409` already in list, `500` GitHub write failed.

---

## `POST /api/add_manga`

Identical to `/api/add_anime` but adds to the underrated manga list. Same request body, same responses.

---

## `POST /api/add_show`

Add a TV show to the underrated shows list. Title, poster, score, genres, and year are fetched automatically from Simkl using the `simkl_id`.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `simkl_id` | `int` | ✅ Required | Simkl show ID |
| `reason` | `string` | ✅ Required | Why this show is underrated |
| `author` | `string` | ❌ Optional | Display name — falls back to `simkl_username` → `"Unknown"` |
| `simkl_username` | `string` | ❌ Optional | Submitter's Simkl username — used to match their profile in `users.json` |

**Example Request**
```json
{
  "simkl_id": 40028,
  "reason": "Criminally underwatched psychological thriller",
  "simkl_username": "ASheby",
  "author": "ASheby"
}
```

### Responses

**`201` — Success**
```json
{
  "success": true,
  "entry": {
    "simkl_id": 40028,
    "title": "Dark",
    "year": 2017,
    "author": "ASheby",
    "reason": "Criminally underwatched psychological thriller",
    "user": {
      "discord": { "id": 612532963938271232, "username": "asheby", "avatar": "https://..." },
      "anilist": { "id": 5724017, "username": "ASheby", "avatar": "https://..." },
      "mal": { "id": 13598844, "username": "ASheby", "avatar": "https://..." },
      "simkl": { "username": "ASheby" }
    },
    "poster": "https://simkl.in/posters/40028_m.jpg",
    "score": 9.2,
    "genres": "Drama, Mystery, Sci-Fi, Thriller",
    "simkl_url": "https://simkl.com/shows/40028"
  }
}
```

**Error responses:** `400` missing fields or invalid `simkl_id`, `401` unauthorized, `404` not found on Simkl, `409` already in list, `500` GitHub write failed or `SIMKL_CLIENT_ID` not configured.

---

## `POST /api/add_movie`

Identical to `/api/add_show` but adds to the underrated movies list. Uses `simkl_id` from Simkl's movie catalog. Same request body and responses, with `simkl_url` pointing to `https://simkl.com/movies/{simkl_id}`.

---

## `POST /api/vote/anime/{media_id}`

Cast a vote on an anime entry. The `{media_id}` in the URL can be either an AniList ID or MAL ID — specify which using `id_type`.

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
| `display_name` | `string` | ❌ Optional | Voter's display name for commit logs |

**Example**
```json
{
  "anilist_user_id": 5724017,
  "direction": "up",
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
{ "error": "direction must be 'up' or 'down'" }
{ "error": "id_type must be 'anilist' or 'mal'" }
{ "error": "Invalid media_id in URL" }
{ "error": "Invalid JSON body" }
```

**`401` — Unauthorized** · **`404` — Entry not in list** · **`429` — Rate limited** · **`500` — GitHub write failed**

```json
{ "error": "Rate limited", "retry_after_seconds": 243.5 }
```

---

## `POST /api/vote/manga/{media_id}`

Identical to `/api/vote/anime/{media_id}` but for manga entries.

---

## `POST /api/vote/show/{media_id}`

Cast a vote on a TV show entry. The `{media_id}` in the URL is the **Simkl ID**.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `direction` | `string` | ✅ Required | `"up"` or `"down"` |
| `anilist_user_id` | `int` | ⚠️ One of these | Voter's AniList user ID |
| `mal_user_id` | `int` | ⚠️ One of these | Voter's MAL user ID |
| `display_name` | `string` | ❌ Optional | Voter's display name for commit logs |

> `id_type` is not applicable for shows/movies — the URL always uses the Simkl ID.

**Example**
```json
{
  "anilist_user_id": 5724017,
  "direction": "up",
  "display_name": "ASheby"
}
```

**Response `200`**
```json
{
  "success": true,
  "action": "added_up",
  "title": "Dark",
  "upvotes": 3,
  "downvotes": 0,
  "net": 3
}
```

Same error responses as `/api/vote/anime`.

---

## `POST /api/vote/movie/{media_id}`

Identical to `/api/vote/show/{media_id}` but for movie entries.

---

## `GET /api/votes/anime/{media_id}`

Get current vote counts for a specific anime entry.

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id_type` | `string` | `anilist` | `"anilist"` or `"mal"` — how to interpret `{media_id}` |

**Response `200`**
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

> Voter IDs are prefixed with `al:` for AniList users, `mal:` for MAL-only users, and `simkl:` for Simkl-only users.

Returns `total_upvotes: 0` / empty arrays if the entry has no votes yet (never a 404 for anilist id_type).

---

## `GET /api/votes/manga/{media_id}`

Identical to `/api/votes/anime/{media_id}` but for manga.

---

## `GET /api/votes/show/{media_id}`

Get current vote counts for a TV show entry. The `{media_id}` is the **Simkl ID**.

**Response `200`**
```json
{
  "media_type": "show",
  "anilist_id": 40028,
  "title": "Dark",
  "total_upvotes": 3,
  "total_downvotes": 0,
  "net": 3,
  "upvoters": ["al:5724017", "simkl:ASheby"],
  "downvoters": []
}
```

---

## `GET /api/votes/movie/{media_id}`

Identical to `/api/votes/show/{media_id}` but for movies.

---

## `GET /api/votes/leaderboard`

Get the vote leaderboard sorted by net score descending.

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | `string` | `anime` | `"anime"`, `"manga"`, `"show"`, or `"movie"` |
| `limit` | `int` | `10` | Max results, capped at `50` |

**Example**
```
GET /api/votes/leaderboard?type=show&limit=5
Authorization: Bearer YOUR_API_SECRET
```

**Response `200`**
```json
{
  "media_type": "show",
  "leaderboard": [
    {
      "rank": 1,
      "anilist_id": 40028,
      "title": "Dark",
      "total_upvotes": 3,
      "total_downvotes": 0,
      "net": 3
    }
  ]
}
```

**`400`** if `type` is not one of the four valid values.

---

## Entry Schemas

### Anime / Manga Entry

```json
{
  "anilist_id": 74489,
  "mal_id": 44489,
  "title": "Houseki no Kuni",
  "author": "ASheby",
  "reason": "Beautifully illustrated philosophical story about identity and change",
  "user": {
    "discord": { "id": 612532963938271232, "username": "asheby", "avatar": "https://..." },
    "anilist": { "id": 5724017, "username": "ASheby", "avatar": "https://..." },
    "mal":     { "id": 13598844, "username": "ASheby", "avatar": "https://..." },
    "simkl":   { "username": null }
  },
  "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx74489-...",
  "score": 89,
  "nsfw": false
}
```

### TV Show / Movie Entry

```json
{
  "simkl_id": 40028,
  "title": "Dark",
  "year": 2017,
  "author": "ASheby",
  "reason": "Criminally underwatched psychological thriller",
  "user": {
    "discord": { "id": 612532963938271232, "username": "asheby", "avatar": "https://..." },
    "anilist": { "id": 5724017, "username": "ASheby", "avatar": "https://..." },
    "mal":     { "id": 13598844, "username": "ASheby", "avatar": "https://..." },
    "simkl":   { "username": "ASheby" }
  },
  "poster": "https://simkl.in/posters/40028_m.jpg",
  "score": 9.2,
  "genres": "Drama, Mystery, Sci-Fi, Thriller",
  "simkl_url": "https://simkl.com/shows/40028"
}
```

### Field Reference

| Field | Anime/Manga | Show/Movie | Description |
|-------|-------------|------------|-------------|
| `anilist_id` | ✅ | ❌ | AniList media ID — `null` if entry only exists on MAL |
| `mal_id` | ✅ | ❌ | MAL media ID — null if not resolvable |
| `simkl_id` | ❌ | ✅ | Simkl media ID |
| `title` | ✅ | ✅ | Media title |
| `year` | ❌ | ✅ | Release year |
| `author` | ✅ | ✅ | Submitter's display name |
| `reason` | ✅ | ✅ | Why this is underrated |
| `user` | ✅ | ✅ | Submitter profile snapshot |
| `poster` | ✅ | ✅ | Cover image URL |
| `score` | ✅ | ✅ | Average score (AniList /100, MAL /10 via Jikan, or Simkl /10 for shows/movies) |
| `nsfw` | ✅ | ❌ | Adult content flag from AniList |
| `genres` | ❌ | ✅ | Comma-separated genre string |
| `simkl_url` | ❌ | ✅ | Direct Simkl page link |
