import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
from aiohttp import web
import asyncio
import os
import base64
import hashlib
import secrets
import time
import json
import re
import threading
import urllib.parse
from cryptography.fernet import Fernet

# ── Config ─────────────────────────────────────────────────────────────────────

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

# Support channel where "faq #N" replies are handled (set via env var)
_SUPPORT_CHANNEL_RAW = os.environ.get("SUPPORT_CHANNEL_ID", "")
SUPPORT_CHANNEL_ID = int(_SUPPORT_CHANNEL_RAW) if _SUPPORT_CHANNEL_RAW.strip().isdigit() else None

# ── Load FAQ data ───────────────────────────────────────────────────────────────
FAQ_MAP: dict[int, dict] = {}  # populated in on_ready
RULES_MAP: dict[int, dict] = {}  # populated in on_ready


async def _parse_faq_pages(raw_pages) -> dict[int, dict]:
    """Parse the 2-page embed JSON into {id: {title, description}} dict."""
    if not isinstance(raw_pages, list):
        raise ValueError(f"expected a list of pages, got {type(raw_pages).__name__}")

    entries: dict[int, dict] = {}
    for page in raw_pages:
        embeds = page.get("embeds")
        if not isinstance(embeds, list):
            continue
        for emb in embeds:
            title_raw = emb.get("title", "")
            desc_raw = emb.get("description", "")
            if not title_raw:
                continue
            num_match = re.match(r"^(\d+)\.\s*", title_raw)
            if not num_match:
                continue
            faq_id = int(num_match.group(1))
            clean_title = title_raw[num_match.end():].strip()
            if isinstance(desc_raw, list):
                desc_raw = "\n".join(str(item) for item in desc_raw)
            entries[faq_id] = {"title": clean_title, "description": str(desc_raw)}
    return entries


async def _safe_json_loads(text: str):
    """Parse JSON that may be a valid array, or multiple bare objects without [] wrapper."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # If we get "Extra data", the file likely has bare objects: { ... }, { ... }
    # Wrap in array brackets and retry
    wrapped = f"[{text}]"
    try:
        return json.loads(wrapped)
    except json.JSONDecodeError:
        raise


async def load_faq_from_github():
    """
    Load FAQ data from GitHub.
    Primary: GitHub Contents API (same as rest of bot).
    Fallback: raw.githubusercontent.com direct fetch.
    """
    global FAQ_MAP
    import traceback

    # ── Method 1: GitHub Contents API (authenticated) ────────────────────────
    try:
        async with aiohttp.ClientSession() as session:
            raw_pages, _ = await github_read_json(session, FILE_FAQ)
        entries = await _parse_faq_pages(raw_pages)
        FAQ_MAP = entries
        max_id = max(entries.keys(), default=0)
        print(f"✅ Loaded {len(entries)} FAQ entries via GitHub API (1–{max_id})")
        return
    except Exception as e:
        print(f"⚠️ GitHub API FAQ load failed: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ── Method 2: Raw URL fallback (no auth needed) ─────────────────────────
    try:
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{FILE_FAQ}"
        async with aiohttp.ClientSession() as session:
            async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    print(f"⚠️ Raw FAQ fetch returned HTTP {r.status}")
                    return
                raw_text = await r.text()
                raw_pages = await _safe_json_loads(raw_text)
        entries = await _parse_faq_pages(raw_pages)
        FAQ_MAP = entries
        max_id = max(entries.keys(), default=0)
        print(f"✅ Loaded {len(entries)} FAQ entries via raw URL fallback (1–{max_id})")
    except Exception as e:
        print(f"⚠️ Raw FAQ fallback also failed: {type(e).__name__}: {e}")
        traceback.print_exc()


async def load_rules_from_github():
    """Load rules data from GitHub (same 2-method approach as FAQ)."""
    global RULES_MAP
    import traceback

    # ── Method 1: GitHub Contents API (authenticated) ────────────────────────
    try:
        async with aiohttp.ClientSession() as session:
            raw_pages, _ = await github_read_json(session, FILE_RULES)
        entries = await _parse_faq_pages(raw_pages)
        RULES_MAP = entries
        max_id = max(entries.keys(), default=0)
        print(f"✅ Loaded {len(entries)} Rules entries via GitHub API (1–{max_id})")
        return
    except Exception as e:
        print(f"⚠️ GitHub API Rules load failed: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ── Method 2: Raw URL fallback (no auth needed) ─────────────────────────
    try:
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{FILE_RULES}"
        async with aiohttp.ClientSession() as session:
            async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    print(f"⚠️ Raw Rules fetch returned HTTP {r.status}")
                    return
                raw_text = await r.text()
                raw_pages = await _safe_json_loads(raw_text)
        entries = await _parse_faq_pages(raw_pages)
        RULES_MAP = entries
        max_id = max(entries.keys(), default=0)
        print(f"✅ Loaded {len(entries)} Rules entries via raw URL fallback (1–{max_id})")
    except Exception as e:
        print(f"⚠️ Raw Rules fallback also failed: {type(e).__name__}: {e}")
        traceback.print_exc()

# ── Proxy Config ───────────────────────────────────────────────────────────────

_PROXY_HOST = os.environ.get("PROXY_HOST")
_PROXY_PORT = os.environ.get("PROXY_PORT")
_PROXY_USER = os.environ.get("PROXY_USER")
_PROXY_PASS = os.environ.get("PROXY_PASS")
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0)) or None
OWNER_ID = 612532963938271232  # receives proxy startup/switch DMs



# ── AniList monitor ────────────────────────────────────────────────────────────
FILE_ANILIST_STATUS = "anilist_status.json"  # persisted in main repo, same fields as YML
_al_status:    str | None = None   # 'up'/'down' — loaded from file on start
_al_down_since: int | None = None  # unix timestamp of when it went down
_al_sha:       str | None = None   # github file sha for writes

ANILIST_WEBHOOKS = {
    "anymex":      os.environ.get("ANILIST_WEBHOOK_ANYMEX"),
    "animestream": os.environ.get("ANILIST_WEBHOOK_ANIMESTREAM"),
    "shonenx":     os.environ.get("ANILIST_WEBHOOK_SHONENX"),
    "azyx":        os.environ.get("ANILIST_WEBHOOK_AZYX"),
}
ANILIST_ROLES = {
    "anymex":      os.environ.get("ANILIST_ROLE_ANYMEX"),
    "animestream": os.environ.get("ANILIST_ROLE_ANIMESTREAM"),
    "shonenx":     os.environ.get("ANILIST_ROLE_SHONENX"),
    "azyx":        os.environ.get("ANILIST_ROLE_AZYX"),
}

# ── Private userdata repo ──────────────────────────────────────────────────────
USERDATA_REPO = "clients-userdata"
USERDATA_BRANCH = "main"

def _short_reason(text: str, limit: int = 80) -> str:
    """Return a truncated reason for log embeds."""
    if not text:
        return "N/A"
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."

# ── Language name map (ISO 639-1 → readable name) ────────────────────────────
_LANG_NAMES = {
    "af":"Afrikaans","sq":"Albanian","am":"Amharic","ar":"Arabic","hy":"Armenian",
    "az":"Azerbaijani","eu":"Basque","be":"Belarusian","bn":"Bengali","bs":"Bosnian",
    "bg":"Bulgarian","ca":"Catalan","zh":"Chinese","hr":"Croatian","cs":"Czech",
    "da":"Danish","nl":"Dutch","eo":"Esperanto","et":"Estonian","fi":"Finnish",
    "fr":"French","gl":"Galician","ka":"Georgian","de":"German","el":"Greek",
    "gu":"Gujarati","ht":"Haitian Creole","he":"Hebrew","hi":"Hindi","hu":"Hungarian",
    "is":"Icelandic","id":"Indonesian","ga":"Irish","it":"Italian","ja":"Japanese",
    "kn":"Kannada","kk":"Kazakh","km":"Khmer","ko":"Korean","ku":"Kurdish",
    "ky":"Kyrgyz","lo":"Lao","lv":"Latvian","lt":"Lithuanian","mk":"Macedonian",
    "ms":"Malay","ml":"Malayalam","mt":"Maltese","mr":"Marathi","mn":"Mongolian",
    "ne":"Nepali","no":"Norwegian","fa":"Persian","pl":"Polish","pt":"Portuguese",
    "pa":"Punjabi","ro":"Romanian","ru":"Russian","sr":"Serbian","si":"Sinhala",
    "sk":"Slovak","sl":"Slovenian","so":"Somali","es":"Spanish","sw":"Swahili",
    "sv":"Swedish","tl":"Filipino","tg":"Tajik","ta":"Tamil","te":"Telugu",
    "th":"Thai","tr":"Turkish","uk":"Ukrainian","ur":"Urdu","uz":"Uzbek",
    "vi":"Vietnamese","cy":"Welsh","xh":"Xhosa","yi":"Yiddish","zu":"Zulu",
}

async def _translate_reason(session: aiohttp.ClientSession, text: str) -> str:
    """
    Translate reason to English using Google Translate (free endpoint).
    If already English or translation fails, returns the original text unchanged.
    Stores as:
        Translated: <english text>
        Original (<Language>): <original text>
    If already English, returns the original text as-is (no labels).
    """
    if not text or not text.strip():
        return text
    try:
        detect_url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx&sl=auto&tl=en&dt=t&q=" +
            urllib.parse.quote(text, safe='')
        )
        async with session.get(
            detect_url,
            timeout=aiohttp.ClientTimeout(total=15),
            proxy=None,  # Don't use proxy for Google Translate — avoid proxy failures
        ) as resp:
            if resp.status != 200:
                print(f"⚠️ [Translate] API returned status {resp.status} for: {text[:80]}...")
                return text
            data = await resp.json(content_type=None)
            detected_lang = data[2] if len(data) > 2 and data[2] else None

            # Collect translated segments
            translated_parts = []
            if data and data[0]:
                for segment in data[0]:
                    if segment and segment[0]:
                        translated_parts.append(segment[0])
            translated = "".join(translated_parts).strip()

            # If no translation segments were returned, return original
            if not translated:
                return text

            # If translation result is identical to original, it was already English
            if translated.lower() == text.lower():
                return text

            # If detected as English but translation differs (e.g. mixed-language text),
            # still apply the translation
            lang_name = _LANG_NAMES.get(detected_lang, detected_lang.upper()) if detected_lang else "Unknown"
            print(f"✅ [Translate] {detected_lang or '?'} → en: {translated[:80]}...")
            return f"Translated: {translated}\nOriginal ({lang_name}): {text}"
    except Exception as e:
        print(f"❌ [Translate] Failed for \"{text[:80]}...\": {type(e).__name__}: {e}")
        return text




def _log_reason_fields(embed, stored_reason: str, label: str = "Reason") -> None:
    """
    Add reason field(s) to a Discord embed.
    If the stored_reason contains translated + original parts, splits them
    into two separate embed fields for clarity.
    Otherwise adds a single field with the full reason (up to 1024 chars).
    """
    if not stored_reason:
        embed.add_field(name=label, value="N/A", inline=False)
        return
    if stored_reason.startswith("Translated: ") and "\nOriginal (" in stored_reason:
        parts = stored_reason.split("\nOriginal (", 1)
        translated_part = parts[0]  # "Translated: <text>"
        original_part = "Original (" + parts[1]  # "Original (Language): <text>"
        embed.add_field(name=f"{label} (Translated)", value=translated_part[:1024], inline=False)
        embed.add_field(name=f"{label} (Original)", value=original_part[:1024], inline=False)
    else:
        embed.add_field(name=label, value=stored_reason[:1024], inline=False)


def _ids_line(**kwargs) -> str:
    """Build a compact IDs string from keyword args, skipping None/falsy values.
    Usage: _ids_line(AL=123, MAL=456, Simkl=None, DC=987654321)
    Returns: 'AL:123 · MAL:456 · DC:987654321'
    """
    parts = [f"{k}:{v}" for k, v in kwargs.items() if v]
    return " · ".join(parts) if parts else "N/A"


ENV_PROXY_URL = (
    f"http://{_PROXY_USER}:{_PROXY_PASS}@{_PROXY_HOST}:{_PROXY_PORT}"
    if all([_PROXY_HOST, _PROXY_PORT, _PROXY_USER, _PROXY_PASS])
    else (
        f"http://{_PROXY_HOST}:{_PROXY_PORT}"
        if all([_PROXY_HOST, _PROXY_PORT])
        else None
    )
)

# ── Proxy System ───────────────────────────────────────────────────────────────
# Flow:
#   1. Bot starts immediately using ENV proxy (no delay, no searching)
#   2. On ready: load stored proxies from private GitHub repo (proxies.json)
#   3. Background: fetch + properly validate free proxies, rank by speed
#   4. Once best free proxy confirmed → switch to it + save to GitHub
#   5. On next restart: load saved proxies from GitHub, skip slow fetch if fresh
#
# ProxyScrape v4 JSON API — returns rich metadata (alive, uptime, timeout, protocol)
_PROXYSCRAPE_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=protocolipport&format=json"
)

# ProxyDB — HTML table scrape for HTTP/HTTPS proxies (fallback/supplement source)
_PROXYDB_URLS = [
    "https://proxydb.net/?protocol=http&anonlvl=1&anonlvl=2&anonlvl=3",   # HTTP
    "https://proxydb.net/?protocol=https&anonlvl=1&anonlvl=2&anonlvl=3",  # HTTPS
]

# Minimum quality thresholds for a proxy to be stored/used
_PROXY_MIN_UPTIME    = 80.0   # % uptime required
_PROXY_MAX_TIMEOUT   = 2000   # ms average timeout allowed
_PROXY_PROTOCOLS     = {"http", "https"}

FILE_PROXIES = "proxies.json"          # stored in private userdata repo
_PROXY_TEST_URLS = [
    "https://discord.com/api/v10/gateway",            # Discord API
    "https://cdn.discordapp.com/embed/avatars/0.png", # Discord CDN
]
_PROXY_CHECK_CONCURRENCY = 50          # concurrent validation workers
_PROXY_PASSES = 2                      # rounds — proxy must pass ALL test URLs each round
_PROXY_PASS_TIMEOUT = 6               # seconds per individual test
_PROXY_CACHE_MAX_AGE = 300            # treat cache stale after 5 min

_proxy_list: list[str] = []           # current working pool, sorted fastest-first
_current_proxy: str | None = None     # proxy actively in use
_env_proxy_failed = False             # True once ENV proxy is confirmed dead
_proxy_fail_count = 0                 # consecutive failures mid-session

FILE_LOG_QUEUE = "log_queue.json"  # stored in private userdata repo
FILE_LAST_REPOPULATED = "last_repopulated.json"  # stored in private userdata repo

_log_queue: list[dict] = []  # in-memory queue of serialized embeds


def _embed_to_dict(embed: discord.Embed) -> dict:
    """Serialize a discord.Embed to a plain dict for JSON storage."""
    d: dict = {"title": embed.title, "color": embed.color.value if embed.color else 0, "fields": []}
    if embed.description:
        d["description"] = embed.description
    for field in embed.fields:
        d["fields"].append({"name": field.name, "value": field.value, "inline": field.inline})
    return d


def _dict_to_embed(d: dict) -> discord.Embed:
    """Deserialize a plain dict back to a discord.Embed."""
    embed = discord.Embed(
        title=d.get("title"),
        description=d.get("description"),
        color=d.get("color", 0),
    )
    for field in d.get("fields", []):
        embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", True))
    return embed


async def _persist_log_queue():
    """Save current in-memory queue to GitHub so it survives crashes."""
    try:
        async with aiohttp.ClientSession() as session:
            _, sha = await github_read_json(session, FILE_LOG_QUEUE, repo=USERDATA_REPO, branch=USERDATA_BRANCH)
            await github_write_json(
                session, FILE_LOG_QUEUE, _log_queue, sha,
                "log: update pending queue",
                repo=USERDATA_REPO, branch=USERDATA_BRANCH,
            )
    except Exception as e:
        print(f"⚠️ Failed to persist log queue: {e}")


async def _load_log_queue():
    """Load any previously saved queue from GitHub on startup."""
    global _log_queue
    try:
        async with aiohttp.ClientSession() as session:
            data, _ = await github_read_json(session, FILE_LOG_QUEUE, repo=USERDATA_REPO, branch=USERDATA_BRANCH)
            if isinstance(data, list) and data:
                _log_queue = data
                print(f"📥 Loaded {len(_log_queue)} pending log(s) from GitHub")
    except Exception as e:
        print(f"⚠️ Failed to load log queue: {e}")



async def _send_log(embed: discord.Embed):
    """Send a log embed to LOG_CHANNEL_ID. Fire-and-forget, never blocks the caller."""
    if not LOG_CHANNEL_ID:
        return

    async def _do_send():
        try:
            ch = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
            if ch:
                await ch.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Failed to send log embed: {type(e).__name__}: {e}")

    asyncio.create_task(_do_send())


# ── GitHub proxy store helpers ─────────────────────────────────────────────────

async def read_proxies(session: aiohttp.ClientSession) -> tuple:
    """Read proxies.json from private repo. Returns (data_dict, sha)."""
    # github_read_json is defined later but that's fine — called at runtime
    return await github_read_json(session, FILE_PROXIES, repo=USERDATA_REPO, branch=USERDATA_BRANCH)


async def write_proxies(session: aiohttp.ClientSession, data: dict, sha, msg: str) -> bool:
    """Write proxies.json to private repo."""
    return await github_write_json(session, FILE_PROXIES, data, sha, msg, repo=USERDATA_REPO, branch=USERDATA_BRANCH)


# ── Proxy fetching, filtering and testing ─────────────────────────────────────

async def _fetch_proxyscrape(session: aiohttp.ClientSession) -> list[str]:
    """
    Fetch from ProxyScrape v4 JSON API and pre-filter by quality metadata.
    Only keeps proxies that are alive, have high uptime, and low avg timeout.
    Returns list of proxy URL strings sorted by timeout (fastest first).
    """
    try:
        async with session.get(_PROXYSCRAPE_URL, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                print(f"⚠️ [ProxyScrape] Bad status {resp.status}")
                return []
            data = await resp.json(content_type=None)
    except Exception as e:
        print(f"⚠️ [ProxyScrape] Failed to fetch: {e}")
        return []

    proxies_data = data.get("proxies", [])
    filtered = [
        p for p in proxies_data
        if p.get("alive")
        and p.get("uptime", 0) >= _PROXY_MIN_UPTIME
        and p.get("average_timeout", 99999) <= _PROXY_MAX_TIMEOUT
        and p.get("protocol", "").lower() in _PROXY_PROTOCOLS
    ]
    filtered.sort(key=lambda p: p.get("average_timeout", 99999))
    result = [p["proxy"] for p in filtered if p.get("proxy")]
    print(f"✅ [ProxyScrape] {len(proxies_data)} total → {len(result)} passed filter (alive, uptime≥{_PROXY_MIN_UPTIME}%, timeout≤{_PROXY_MAX_TIMEOUT}ms)")
    return result


async def _fetch_proxydb(session: aiohttp.ClientSession) -> list[str]:
    """
    Scrape ProxyDB HTML table for HTTP/HTTPS proxies.
    Parses the IP:port table rows and returns proxy URL strings.
    Only fetches the first page (~30 proxies per protocol) as a supplement.
    """
    result: list[str] = []
    for url in _PROXYDB_URLS:
        protocol = "https" if "protocol=https" in url else "http"
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                if resp.status != 200:
                    print(f"⚠️ [ProxyDB] Bad status {resp.status} for {url}")
                    continue
                html = await resp.text()
        except Exception as e:
            print(f"⚠️ [ProxyDB] Fetch error for {url}: {e}")
            continue

        # Each proxy row has IP and port inside <td>...<a>...</a>...</td> cells
        td_values = re.findall(r'<td[^>]*>\s*<a[^>]*>\s*([^<]+?)\s*</a>', html)
        proxies_found = 0
        i = 0
        while i + 1 < len(td_values):
            ip_candidate = td_values[i].strip()
            port_candidate = td_values[i + 1].strip()
            if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip_candidate) and port_candidate.isdigit():
                result.append(f"{protocol}://{ip_candidate}:{port_candidate}")
                proxies_found += 1
                i += 2
            else:
                i += 1
        print(f"✅ [ProxyDB] Scraped {proxies_found} {protocol.upper()} proxies")

    return result


async def _fetch_and_filter_proxies(session: aiohttp.ClientSession) -> list[str]:
    """
    Fetch from ProxyScrape (JSON) + ProxyDB (HTML scrape), merge, deduplicate.
    ProxyScrape results come first (pre-sorted by speed/metadata).
    ProxyDB results are appended as supplemental candidates.
    All proxies then go through multi-pass Discord validation in _background_proxy_finder.
    """
    # Run both sources concurrently
    proxyscrape_result, proxydb_result = await asyncio.gather(
        _fetch_proxyscrape(session),
        _fetch_proxydb(session),
        return_exceptions=True,
    )

    ps_proxies: list[str] = proxyscrape_result if isinstance(proxyscrape_result, list) else []
    pd_proxies: list[str] = proxydb_result if isinstance(proxydb_result, list) else []

    # Merge: ProxyDB first (priority), ProxyScrape after, deduplicated
    seen: set[str] = set()
    combined: list[str] = []
    for p in pd_proxies + ps_proxies:
        if p not in seen:
            seen.add(p)
            combined.append(p)

    print(f"✅ [ProxyFetch] Combined: {len(pd_proxies)} ProxyDB (priority) + {len(ps_proxies)} ProxyScrape = {len(combined)} unique candidates")
    return combined


async def _verify_proxy(proxy: str | None) -> tuple[bool, float]:
    """
    Ping a proxy against both Discord URLs.
    Returns (is_alive, avg_latency_seconds).
    Called before rotating to confirm a proxy is actually dead, not a false alarm.
    """
    if not proxy:
        return False, 0.0
    try:
        latencies = []
        async with aiohttp.ClientSession() as session:
            for _ in range(_PROXY_PASSES):
                for url in _PROXY_TEST_URLS:
                    t = time.monotonic()
                    async with session.get(
                        url, proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=_PROXY_PASS_TIMEOUT),
                        ssl=False,
                    ) as resp:
                        if resp.status not in (200, 401):
                            return False, 0.0
                        latencies.append(time.monotonic() - t)
        avg = sum(latencies) / len(latencies) if latencies else 0.0
        return True, avg
    except Exception:
        return False, 0.0


async def _test_proxy_passes(session: aiohttp.ClientSession, proxy: str, sem: asyncio.Semaphore) -> tuple[str, float] | None:
    """Validate a single proxy with multi-pass testing. Returns (proxy, avg_latency) or None."""
    async with sem:
        latencies = []
        for _ in range(_PROXY_PASSES):
            for url in _PROXY_TEST_URLS:
                try:
                    t = time.monotonic()
                    async with session.get(
                        url, proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=_PROXY_PASS_TIMEOUT),
                        ssl=False,
                    ) as resp:
                        if resp.status not in (200, 401):
                            return None
                        latencies.append(time.monotonic() - t)
                except Exception:
                    return None
        avg = sum(latencies) / len(latencies)
        return (proxy, avg)


# ── Background proxy finder (runs every 5 min, updates GitHub repo) ──────────────

_best_proxy_lock: asyncio.Lock | None = None  # initialized in main()


async def _background_proxy_finder():
    """
    Runs entirely in the background after bot is online.
    Every 5 minutes:
      1. Fetch ProxyDB + ProxyScrape concurrently and merge candidates (ProxyDB prioritised)
      2. Multi-pass validate the merged list against Discord
      3. Save top 50 to proxies.json in private GitHub repo
      4. Switch bot to fastest proxy only if current one is confirmed dead
    """
    global _proxy_list, _current_proxy

    while True:
        try:
            print("🔍 [ProxyFinder] Fetching fresh proxy list...")
            async with aiohttp.ClientSession() as session:

                # Step 1: Fetch + pre-filter by metadata
                candidates = await _fetch_and_filter_proxies(session)
                if not candidates:
                    print("⚠️ [ProxyFinder] No candidates after filtering — reloading GitHub pool as fallback")
                    # Bug fix: don't just sleep with an empty pool; reload saved proxies
                    # so the pool stays populated even during fetch blips.
                    try:
                        fb_saved, _ = await read_proxies(session)
                        fb_proxies: list[str] = fb_saved.get("proxies", []) if isinstance(fb_saved, dict) else []
                        if fb_proxies:
                            _proxy_list = fb_proxies
                            print(f"✅ [ProxyFinder] Reloaded {len(_proxy_list)} proxies from GitHub as fallback")
                        else:
                            print("⚠️ [ProxyFinder] GitHub pool also empty — pool stays as-is")
                    except Exception as fb_e:
                        print(f"⚠️ [ProxyFinder] GitHub fallback reload failed: {fb_e}")
                    await asyncio.sleep(300)
                    continue

                # Step 2: Multi-pass validate against Discord
                sem = asyncio.Semaphore(_PROXY_CHECK_CONCURRENCY)
                test_results = await asyncio.gather(
                    *[_test_proxy_passes(session, p, sem) for p in candidates],
                    return_exceptions=True,
                )

            working = [(p, lat) for r in test_results if isinstance(r, tuple) for p, lat in [r]]
            if not working:
                print("⚠️ [ProxyFinder] No proxies passed Discord validation — keeping current")
                await asyncio.sleep(300)
                continue

            working.sort(key=lambda x: x[1])
            sorted_proxies = [p for p, _ in working]
            best_proxy, best_latency = working[0]
            print(f"✅ [ProxyFinder] {len(sorted_proxies)} proxies validated. Best: {best_proxy} ({best_latency:.2f}s)")

            _proxy_list = sorted_proxies

            # Step 3: Save to GitHub
            try:
                async with aiohttp.ClientSession() as session:
                    _, sha = await read_proxies(session)
                    payload = {
                        "proxies": sorted_proxies[:50],
                        "best": best_proxy,
                        "best_latency": round(best_latency, 3),
                        "count": len(sorted_proxies),
                        "saved_at": time.time(),
                    }
                    ok = await write_proxies(session, payload, sha, f"proxy: refresh pool ({len(sorted_proxies)} working)")
                    if ok:
                        print(f"✅ [ProxyFinder] Saved {len(sorted_proxies)} proxies to GitHub")
                    else:
                        print("⚠️ [ProxyFinder] Failed to save to GitHub")
            except Exception as e:
                print(f"⚠️ [ProxyFinder] GitHub save error: {e}")

            # Step 4: Only switch if current proxy is confirmed dead
            if best_proxy != _current_proxy:
                alive, _ = await _verify_proxy(_current_proxy)
                if not alive:
                    print(f"🔄 [ProxyFinder] Current proxy dead — switching to {best_proxy}")
                    await _do_proxy_switch(best_proxy, sorted_proxies, reason="current proxy dead, switching to best")
                else:
                    print(f"✅ [ProxyFinder] Current proxy still alive — not switching")

        except Exception as e:
            print(f"⚠️ [ProxyFinder] Error: {e}")

        print("⏳ [ProxyFinder] Next run in 5 minutes")
        await asyncio.sleep(300)


async def _dm_owner(embed: discord.Embed):
    """Send an embed to the owner's DM. Silently ignores failures."""
    try:
        user = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
        dm = user.dm_channel or await user.create_dm()
        await dm.send(embed=embed)
    except Exception as e:
        print(f"⚠️ [OwnerDM] Failed to send DM: {e}")


async def _do_proxy_switch(new_proxy: str, pool: list[str], reason: str = ""):
    """Switch the bot to a new proxy and log it. Does NOT close the session."""
    global _current_proxy
    async with _best_proxy_lock:
        old = _current_proxy
        if new_proxy == old:
            return
        _current_proxy = new_proxy
        bot.http.proxy = new_proxy
        print(f"🚀 Proxy switched: {old or 'ENV/direct'} → {new_proxy} ({reason})")
        embed = discord.Embed(title="🚀 Proxy Switched", color=0x2ecc71)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Old", value=old or "ENV / direct", inline=False)
        embed.add_field(name="New", value=new_proxy, inline=False)
        embed.add_field(name="Pool Size", value=str(len(pool)), inline=True)
        asyncio.create_task(_dm_owner(embed))

def get_proxy() -> str | None:
    """Return the best available proxy. Pool first (skipping current dead proxy), ENV as fallback."""
    global _current_proxy, _env_proxy_failed
    if _proxy_list:
        # Bug fix: skip _current_proxy itself in case the dead proxy hasn't been removed
        # from the list yet (e.g. startup retry loop calls get_proxy before removal).
        for candidate in _proxy_list:
            if candidate != _current_proxy:
                _current_proxy = candidate
                return _current_proxy
        # All pool entries are the same as current — just return first
        _current_proxy = _proxy_list[0]
        return _current_proxy
    if ENV_PROXY_URL and not _env_proxy_failed:
        _current_proxy = ENV_PROXY_URL
        return _current_proxy
    _current_proxy = None
    return None


async def handle_proxy_failure(reason: str = "unknown"):
    """Called when current proxy may have failed. Verifies before rotating."""
    global _proxy_fail_count, _env_proxy_failed, _proxy_list

    # Session closed = discord.py is mid-reconnect, not a real proxy failure
    if "Session is closed" in str(reason):
        return

    _proxy_fail_count += 1
    print(f"⚠️ Proxy failure #{_proxy_fail_count} ({reason}) — verifying proxy before rotating...")

    # Confirm the proxy is actually dead before dumping it
    alive, _ = await _verify_proxy(_current_proxy)
    if alive:
        print(f"✅ Proxy verified still alive — ignoring false alarm ({reason})")
        return

    print(f"❌ Proxy confirmed dead — rotating")
    if ENV_PROXY_URL and _current_proxy == ENV_PROXY_URL and not _env_proxy_failed:
        _env_proxy_failed = True
        print("⚠️ ENV proxy marked as failed")

    if _current_proxy and _current_proxy in _proxy_list:
        _proxy_list.remove(_current_proxy)

    new_proxy = get_proxy()
    bot.http.proxy = new_proxy
    # No bot.http.close() — causes Session is closed cascade

    print(f"🔄 Rotated to: {new_proxy or 'direct'}")
    embed = discord.Embed(title="⚠️ Proxy Failed — Rotated", color=0xe67e22)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="New Proxy", value=new_proxy or "direct", inline=False)
    embed.add_field(name="Pool Remaining", value=str(len(_proxy_list)), inline=True)
    asyncio.create_task(_dm_owner(embed))



# ── AniList status monitor ─────────────────────────────────────────────────────
# Mirrors YML logic exactly:
#   - On start       : read anilist_status.json from repo → get previous state
#   - Every 1 min    : hit AniList GraphQL (same query as YML)
#   - up → down      : send DOWN webhook to all servers, save state to repo
#   - down → up      : send UP webhook (with downtime duration), save state
#   - no change      : do nothing, no messages, no noise
#   - first run + up : silent, just save state so next restart knows
# State file: { "status": "up"/"down", "down_since": <unix ts or null> }

async def _al_load_state():
    """On bot start: load previous AniList state from repo so restarts never false-alert."""
    global _al_status, _al_down_since, _al_sha
    try:
        async with aiohttp.ClientSession() as session:
            data, sha = await github_read_json(session, FILE_ANILIST_STATUS)
            if isinstance(data, dict) and "status" in data:
                _al_status     = data["status"]
                _al_down_since = data.get("down_since")
                _al_sha        = sha
                print(f"[AniList] Loaded state from repo: {_al_status}")
            else:
                print("[AniList] No state file yet — will create on first change")
    except Exception as e:
        print(f"[AniList] Could not load state: {e}")


async def _al_save_state(status: str, down_since, session: aiohttp.ClientSession):
    """Save state to repo. Same fields as YML artifact: { status, down_since }."""
    global _al_sha
    import datetime as _dt
    state = {
        "status":     status,
        "down_since": down_since,
        "updated_at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    ok = await github_write_json(
        session, FILE_ANILIST_STATUS, state, _al_sha,
        f"anilist-monitor: {status}",
    )
    if ok:
        _, new_sha = await github_read_json(session, FILE_ANILIST_STATUS)
        _al_sha = new_sha


async def _al_send(is_down: bool, short_err: str, duration_str: str | None):
    """Fire embed to all configured server webhooks."""
    import datetime as _dt
    now_iso = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    if is_down:
        embed = {
            "title":       "\U0001f534 AniList is DOWN",
            "description": f"**{short_err}**\nCheck AniList Discord for updates.",
            "color":       16729156,
            "footer":      {"text": "AniList Monitor"},
            "timestamp":   now_iso,
        }
    else:
        embed = {
            "title":       "\U0001f7e2 AniList is back UP",
            "description": f"Was down for **{duration_str}**.",
            "color":       4521096,
            "footer":      {"text": "AniList Monitor"},
            "timestamp":   now_iso,
        }

    async def _post(session, server):
        url  = ANILIST_WEBHOOKS.get(server)
        role = ANILIST_ROLES.get(server)
        if not url:
            return
        payload = {"embeds": [embed]}
        if role:
            payload["content"] = f"<@&{role}>"
        try:
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                print(f"[AniList] {server}: HTTP {r.status}")
        except Exception as e:
            print(f"[AniList] {server} failed: {e}")

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            *[_post(session, s) for s in ANILIST_WEBHOOKS],
            return_exceptions=True,
        )


@tasks.loop(minutes=1)
async def anilist_monitor():
    """
    Check AniList every 1 min — same logic as the YML workflow.
    Webhooks fire only on actual status transitions, not every check.
    State is persisted in repo so bot restarts never cause false alerts.
    """
    global _al_status, _al_down_since

    # ── Hit AniList GraphQL (exact same query as YML) ────────────────────────
    status      = "up"
    status_code = None
    error_msg   = ""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://graphql.anilist.co/",
                json={"query": "{ Media(id:1) { id } }"},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                status_code = resp.status
                try:
                    body   = await resp.json(content_type=None)
                    errors = body.get("errors") or []
                    # Only trigger on exact AniList disabled response:
                    # HTTP 403 + errors[0].status == 403 + "disabled" in message
                    if (
                        errors
                        and status_code == 403
                        and errors[0].get("status") == 403
                        and "disabled" in errors[0].get("message", "").lower()
                    ):
                        status    = "down"
                        error_msg = errors[0]["message"].strip()
                except Exception:
                    pass  # not a valid JSON response, ignore

    except Exception:
        pass  # network blip / timeout — not a 403, ignore

    # ── Only act on change (same as YML prev != current logic) ───────────────
    if _al_status == status:
        return

    prev       = _al_status
    _al_status = status
    now_ts     = int(time.time())

    # ── up → down ────────────────────────────────────────────────────────────
    if status == "down" and prev != "down":
        _al_down_since = now_ts
        # Cut at 'disabled' if present, else first period — avoids cutting mid-word
        _em = error_msg.strip()
        if 'disabled' in _em.lower():
            _idx = _em.lower().index('disabled') + len('disabled')
            short = _em[:_idx].strip()
        else:
            short = _em.split('.')[0].strip()[:80]
        short_err = f"{short} ({status_code})" if status_code else short or "Unknown error"
        await _al_send(is_down=True, short_err=short_err, duration_str=None)
        async with aiohttp.ClientSession() as session:
            await _al_save_state("down", _al_down_since, session)

    # ── down → up ────────────────────────────────────────────────────────────
    elif status == "up" and prev == "down":
        if _al_down_since:
            dur     = now_ts - _al_down_since
            hrs     = dur // 3600
            mins    = (dur % 3600) // 60
            secs    = dur % 60
            dur_str = f"{hrs}h {mins}m {secs}s" if hrs > 0 else f"{mins}m {secs}s"
        else:
            dur_str = "Unknown"
        _al_down_since = None
        await _al_send(is_down=False, short_err="", duration_str=dur_str)
        async with aiohttp.ClientSession() as session:
            await _al_save_state("up", None, session)

    # ── first ever check + already up → silent, just save state ─────────────
    elif prev is None and status == "up":
        async with aiohttp.ClientSession() as session:
            await _al_save_state("up", None, session)

@tasks.loop(minutes=1)
async def proxy_health_check():
    """Ping current proxy every 1 min. Verify + rotate if dead."""
    if not _current_proxy:
        return
    alive, latency = await _verify_proxy(_current_proxy)
    if alive:
        print(f"✅ [HealthCheck] Proxy alive ({latency:.2f}s): {_current_proxy}")
    else:
        print(f"❌ [HealthCheck] Proxy dead: {_current_proxy} — rotating")
        await handle_proxy_failure(reason="health check: proxy dead")
# ── Bot startup ────────────────────────────────────────────────────────────────

async def start_bot_with_proxy():
    global _current_proxy, _env_proxy_failed, _proxy_list

    # Startup proxy priority:
    #   0. ALWAYS seed _proxy_list from proxies.json (GitHub) first — so the full
    #      validated pool of up to 50 proxies is available from the very first moment,
    #      regardless of which source ends up being used for _current_proxy.
    #      (Bug fix: previously pool was only populated on the fallback path, leaving
    #       it at whatever ProxyDB scraped (often 1–5 entries) when ProxyDB succeeded.)
    #   1. ProxyDB — pick a fresh active proxy for _current_proxy.
    #   2. ENV proxy — fallback if ProxyDB finds nothing.
    #   3. First alive proxy from the already-seeded pool — last resort.

    # ── Step 0: Seed the full pool from GitHub ─────────────────────────────────
    try:
        async with aiohttp.ClientSession() as session:
            saved, _ = await read_proxies(session)
            saved_proxies_boot: list[str] = saved.get("proxies", []) if isinstance(saved, dict) else []
            saved_at_boot: float = saved.get("saved_at", 0) if isinstance(saved, dict) else 0
            age_boot = time.time() - saved_at_boot
            if saved_proxies_boot:
                _proxy_list = saved_proxies_boot
                print(f"✅ [Startup] Seeded pool from GitHub: {len(_proxy_list)} proxies ({age_boot/60:.0f}min old)")
            else:
                print("⚠️ [Startup] proxies.json empty or missing — pool starts empty")
    except Exception as e:
        print(f"⚠️ [Startup] Could not load proxies.json for pool seed: {e}")

    # ── Step 1: Try ProxyDB ────────────────────────────────────────────────────
    try:
        async with aiohttp.ClientSession() as session:
            proxydb_candidates = await _fetch_proxydb(session)
        if proxydb_candidates:
            print(f"🔍 [Startup] Verifying ProxyDB candidates ({len(proxydb_candidates)} found)...")
            for p in proxydb_candidates:
                alive, lat = await _verify_proxy(p)
                if alive:
                    _current_proxy = p
                    # Merge ProxyDB candidates into the front of the pool (deduplicated)
                    existing = set(_proxy_list)
                    new_entries = [x for x in proxydb_candidates if x not in existing]
                    _proxy_list = new_entries + _proxy_list
                    print(f"✅ [Startup] Using ProxyDB proxy: {_current_proxy} ({lat:.2f}s) | pool={len(_proxy_list)}")
                    break
            else:
                raise ValueError("No ProxyDB proxy passed verification")
        else:
            raise ValueError("ProxyDB returned no candidates")
    except Exception as e:
        print(f"⚠️ [Startup] ProxyDB failed ({e}) — trying ENV proxy...")

        # ── Step 2: Try ENV proxy ──────────────────────────────────────────────
        if ENV_PROXY_URL:
            alive, lat = await _verify_proxy(ENV_PROXY_URL)
            if alive:
                _current_proxy = ENV_PROXY_URL
                print(f"✅ [Startup] Using ENV proxy: {_current_proxy} ({lat:.2f}s) | pool={len(_proxy_list)}")
            else:
                _env_proxy_failed = True
                print(f"⚠️ [Startup] ENV proxy is dead — picking from saved pool...")
                picked = False
                for p in _proxy_list:
                    alive, lat = await _verify_proxy(p)
                    if alive:
                        _current_proxy = p
                        print(f"✅ [Startup] Using saved proxy: {_current_proxy} ({lat:.2f}s) | pool={len(_proxy_list)}")
                        picked = True
                        break
                if not picked:
                    _current_proxy = None
                    print("⚠️ [Startup] All proxy sources failed — running direct (no proxy)")
        else:
            # No ENV proxy configured — pick from saved pool
            picked = False
            for p in _proxy_list:
                alive, lat = await _verify_proxy(p)
                if alive:
                    _current_proxy = p
                    print(f"✅ [Startup] Using saved proxy: {_current_proxy} ({lat:.2f}s) | pool={len(_proxy_list)}")
                    picked = True
                    break
            if not picked:
                _current_proxy = None
                print("⚠️ [Startup] All proxy sources failed — running direct (no proxy)")

    bot.http.proxy = _current_proxy

    # DM owner with startup proxy info
    startup_embed = discord.Embed(title="🟢 Bot Starting", color=0x3498db)
    startup_embed.add_field(name="Proxy", value=_current_proxy or "direct (no proxy)", inline=False)
    asyncio.create_task(_dm_owner(startup_embed))

    retry_count = 0
    while True:
        try:
            await bot.start(DISCORD_TOKEN)
            break
        except discord.errors.HTTPException as e:
            if e.status == 429:
                retry_after = None
                try:
                    retry_after = float(e.response.headers.get("Retry-After", 0)) or None
                except Exception:
                    pass
                retry_after = retry_after or min(60 * (2 ** retry_count), 600)
                retry_count += 1
                print(f"⚠️ Rate limited (attempt {retry_count}). Waiting {retry_after:.0f}s...")
                if _proxy_list:
                    new_proxy = _proxy_list[0]
                    bot.http.proxy = new_proxy
                    _current_proxy = new_proxy
                    print(f"🔄 Switched proxy after 429: {new_proxy}")
                    rl_embed = discord.Embed(title="⚠️ Rate Limited — Proxy Switched", color=0xe74c3c)
                    rl_embed.add_field(name="Wait", value=f"{retry_after:.0f}s", inline=True)
                    rl_embed.add_field(name="Attempt", value=str(retry_count), inline=True)
                    rl_embed.add_field(name="New Proxy", value=new_proxy, inline=False)
                    asyncio.create_task(_dm_owner(rl_embed))
                await asyncio.sleep(retry_after)
                continue
            raise
        except (aiohttp.ClientHttpProxyError, aiohttp.ClientProxyConnectionError,
                aiohttp.ClientConnectorError, OSError, RuntimeError) as e:
            # Session is closed = discord.py mid-reconnect, not a proxy failure
            if "Session is closed" in str(e):
                await asyncio.sleep(3)
                continue
            retry_count += 1
            old = _current_proxy
            if retry_count > 20:
                print("❌ Too many proxy failures — falling back to direct connection")
                bot.http.proxy = None
                _current_proxy = None
                retry_count = 0
            else:
                if _proxy_list and _current_proxy in _proxy_list:
                    _proxy_list.remove(_current_proxy)
                if _proxy_list:
                    _current_proxy = _proxy_list[0]
                elif ENV_PROXY_URL and not _env_proxy_failed and _current_proxy != ENV_PROXY_URL:
                    _current_proxy = ENV_PROXY_URL
                else:
                    _env_proxy_failed = True
                    _current_proxy = None
                bot.http.proxy = _current_proxy
            print(f"⚠️ Proxy failed ({old}): {e} — rotating to {_current_proxy or 'direct'}")
            # No bot.http.close() here
            await asyncio.sleep(3)
            continue
GITHUB_OWNER = "Shebyyy"
GITHUB_REPO = "AnymeX-Preview"
GITHUB_BRANCH = "beta"
WORKFLOW_FILE = "beta_manual.yml"

STABLE_OWNER = "RyanYuuki"
STABLE_REPO = "AnymeX"
STABLE_BRANCH = "main"

GITHUB_API = "https://api.github.com"
ANILIST_API = "https://graphql.anilist.co"
MAL_API = "https://api.myanimelist.net/v2"
SIMKL_API = "https://api.simkl.com"
SIMKL_CLIENT_ID = os.environ.get("SIMKL_CLIENT_ID")
SIMKL_CLIENT_SECRET = os.environ.get("SIMKL_CLIENT_SECRET", "")
SIMKL_ENCRYPT_KEY = os.environ.get("SIMKL_ENCRYPT_KEY")  # Fernet key — run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# ── OAuth Config ──────────────────────────────────────────────────────────────────
# Register apps at:
#   AniList: https://anilist.co/settings/developer
#   MAL:     https://myanimelist.net/apiconfig
#   Simkl:   https://simkl.com/apps
ANILIST_CLIENT_ID = os.environ.get("ANILIST_CLIENT_ID", "")
ANILIST_CLIENT_SECRET = os.environ.get("ANILIST_CLIENT_SECRET", "")
MAL_CLIENT_ID = os.environ.get("MAL_CLIENT_ID", "")
MAL_CLIENT_SECRET = os.environ.get("MAL_CLIENT_SECRET", "")

# Base URL for OAuth callbacks (your bot's public URL, e.g. https://anymex-preview-bot.onrender.com)
OAUTH_BASE_URL = os.environ.get("OAUTH_BASE_URL", f"http://localhost:{PORT}")

# In-memory store for pending OAuth states: {state_string: {"discord_id": str, "service": str, "created": float}}
_oauth_pending: dict[str, dict] = {}

# In-memory store for completed OAuth results: {state_string: {"success": bool, "service": str, "username": str, ...}}
_oauth_results: dict[str, dict] = {}

# Max time (seconds) a user has to complete OAuth after clicking the link
OAUTH_EXPIRY = 600  # 10 minutes

# ── Shared token encryption (works for any service) ──────────────────────────────
# Falls back to SIMKL_ENCRYPT_KEY for backward compat, or uses a dedicated key
OAUTH_ENCRYPT_KEY = os.environ.get("OAUTH_ENCRYPT_KEY") or SIMKL_ENCRYPT_KEY


def _oauth_encrypt_token(token: str) -> str | None:
    """Encrypt an OAuth access token for safe storage in GitHub JSON."""
    if not OAUTH_ENCRYPT_KEY:
        print("[OAuth encrypt] No encryption key configured — cannot encrypt token")
        return None
    try:
        f = Fernet(OAUTH_ENCRYPT_KEY.encode())
        return f.encrypt(token.encode()).decode()
    except Exception as e:
        print(f"[OAuth encrypt] failed: {e}")
        return None


def _oauth_decrypt_token(encrypted: str) -> str | None:
    """Decrypt a stored OAuth access token."""
    if not OAUTH_ENCRYPT_KEY or not encrypted:
        return None
    try:
        f = Fernet(OAUTH_ENCRYPT_KEY.encode())
        return f.decrypt(encrypted.encode()).decode()
    except Exception as e:
        print(f"[OAuth decrypt] failed: {e}")
        return None


# ── PKCE helpers for MAL ─────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge for MAL (plain method only).
    MAL does NOT support S256 — challenge must equal verifier directly."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = verifier  # plain method: challenge = verifier (no hashing)
    return verifier, challenge


# ── State management ──────────────────────────────────────────────────────────────

def _create_oauth_state(discord_id: int, service: str, discord_user: discord.User | discord.Member | None = None) -> str:
    """Create a unique OAuth state, store it, and return it."""
    state = secrets.token_urlsafe(32)
    data = {
        "discord_id": str(discord_id),
        "service": service,
        "created": time.time(),
    }
    if discord_user:
        data["discord_username"] = discord_user.name
        data["discord_display_name"] = discord_user.display_name
        data["discord_avatar"] = str(discord_user.display_avatar.url) if discord_user.display_avatar else None
    _oauth_pending[state] = data
    return state


def _consume_oauth_state(state: str) -> dict | None:
    """Pop and return a pending OAuth state. Returns None if invalid/expired."""
    data = _oauth_pending.pop(state, None)
    if not data:
        return None
    if time.time() - data["created"] > OAUTH_EXPIRY:
        return None
    return data


# ── HTML callback pages ──────────────────────────────────────────────────────────

def _oauth_success_html(service: str, username: str, avatar_url: str | None = None) -> str:
    """Return a nice 'Auth Completed' HTML page."""
    service_icons = {
        "anilist": "🎌",
        "mal": "🦊",
        "simkl": "🎬",
    }
    icon = service_icons.get(service, "✅")
    service_label = {
        "anilist": "AniList",
        "mal": "MyAnimeList",
        "simkl": "Simkl",
    }.get(service, service)

    avatar_html = ""
    if avatar_url:
        avatar_html = f'<img src="{avatar_url}" alt="Avatar" style="width:80px;height:80px;border-radius:50%;object-fit:cover;border:3px solid #2EA043;margin-bottom:16px;">'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Authorization Successful</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%);
        color: #c9d1d9;
        display: flex; align-items: center; justify-content: center;
        min-height: 100vh; padding: 20px;
    }}
    .card {{
        background: #21262d; border: 1px solid #30363d; border-radius: 16px;
        padding: 40px; text-align: center; max-width: 400px; width: 100%;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }}
    .icon {{ font-size: 64px; margin-bottom: 16px; }}
    .badge {{
        display: inline-block; background: #2EA043; color: white;
        padding: 4px 16px; border-radius: 20px; font-size: 14px; font-weight: 600;
        margin-bottom: 12px;
    }}
    h2 {{ color: #f0f6fc; margin-bottom: 8px; font-size: 24px; }}
    .username {{ color: #58a6ff; font-size: 20px; font-weight: 600; margin-bottom: 16px; }}
    .service-tag {{
        display: inline-block; background: #1f2937; border: 1px solid #374151;
        padding: 6px 14px; border-radius: 8px; font-size: 13px; color: #9ca3af;
    }}
    .footer {{
        margin-top: 24px; padding-top: 16px; border-top: 1px solid #30363d;
        color: #484f58; font-size: 13px;
    }}
    .checkmark {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 48px; height: 48px; border-radius: 50%; background: #2EA043;
        margin-bottom: 16px;
    }}
    .checkmark svg {{ width: 28px; height: 28px; }}
</style>
</head>
<body>
<div class="card">
    {avatar_html}
    <div class="checkmark">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
    </div>
    <div class="badge">Authorization Complete</div>
    <h2>✅ Linked!</h2>
    <div class="username">{username}</div>
    <div class="service-tag">{icon} {service_label}</div>
    <div class="footer">
        You can close this tab and return to Discord.<br>
        Your account has been linked successfully.
    </div>
</div>
</body>
</html>"""


def _oauth_failure_html(service: str, reason: str = "Authorization failed or was cancelled.") -> str:
    """Return a failure HTML page."""
    service_label = {
        "anilist": "AniList",
        "mal": "MyAnimeList",
        "simkl": "Simkl",
    }.get(service, service)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Authorization Failed</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%);
        color: #c9d1d9; display: flex; align-items: center; justify-content: center;
        min-height: 100vh; padding: 20px;
    }}
    .card {{
        background: #21262d; border: 1px solid #30363d; border-radius: 16px;
        padding: 40px; text-align: center; max-width: 400px; width: 100%;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h2 {{ color: #f85149; margin-bottom: 12px; font-size: 22px; }}
    .reason {{ color: #8b949e; font-size: 15px; margin-bottom: 20px; line-height: 1.5; }}
    .service-tag {{
        display: inline-block; background: #1f2937; border: 1px solid #374151;
        padding: 6px 14px; border-radius: 8px; font-size: 13px; color: #9ca3af;
    }}
    .footer {{
        margin-top: 20px; padding-top: 16px; border-top: 1px solid #30363d;
        color: #484f58; font-size: 13px;
    }}
</style>
</head>
<body>
<div class="card">
    <div class="icon">❌</div>
    <h2>Authorization Failed</h2>
    <div class="reason">{reason}</div>
    <div class="service-tag">{service_label}</div>
    <div class="footer">
        You can close this tab and try again in Discord.
    </div>
</div>
</body>
</html>"""


# ── GitHub JSON file paths ──────────────────────────────────────────────────────
FILE_ANIME = "community_anime.json"
FILE_MANGA = "community_manga.json"
FILE_SHOWS = "community_shows.json"
FILE_MOVIES = "community_movies.json"
FILE_USERS = "users.json"
FILE_TIMEZONES = "timezones.json"
FILE_PREFIXES = "prefixes.json"
FILE_SERVER_CFG = "server_config.json"  # stores allowed_roles per server
FILE_VOTES = "votes.json"               # upvote/downvote records per media item
FILE_FAQ = "faq.json"
FILE_RULES = "rules.json"
FILE_ADMINS = "admins.json"  # stored in private userdata repo alongside users.json
FILE_BANNED = "banned.json"  # stored in private userdata repo alongside users.json


DEFAULT_PREFIXES = ["?"]

# ── Permission Helpers ─────────────────────────────────────────────────────────


async def get_allowed_roles(guild_id: str) -> list:
    """Return list of allowed role IDs for this guild."""
    async with aiohttp.ClientSession() as session:
        all_cfg, _ = await github_read_json(session, FILE_SERVER_CFG)
    return all_cfg.get(guild_id, {}).get("allowed_roles", [])


def has_allowed_role():
    """Check if user has an allowed role OR is an administrator."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        allowed = await get_allowed_roles(str(interaction.guild_id))
        user_role_ids = {role.id for role in interaction.user.roles}
        if allowed and user_role_ids & set(allowed):
            return True
        await interaction.response.send_message(
            "❌ You don't have a role allowed to use this command.", ephemeral=True
        )
        return False

    return app_commands.check(predicate)


def has_allowed_role_prefix():
    """Check if user has an allowed role OR is an administrator (prefix commands)."""

    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        allowed = await get_allowed_roles(str(ctx.guild.id))
        user_role_ids = {role.id for role in ctx.author.roles}
        if allowed and user_role_ids & set(allowed):
            return True
        await ctx.send("❌ You don't have a role allowed to use this command.")
        return False

    return commands.check(predicate)


# ── Intents & Bot ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True  # required for prefix commands
intents.members = True

# In-memory prefix cache (loaded on startup)
_prefix_cache = ["?"]


async def get_prefix(bot, message):
    return _prefix_cache


bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# ── /config_role ───────────────────────────────────────────────────────────────



# ── /switchproxy ────────────────────────────────────────────────────────────────


@bot.tree.command(
    name="switchproxy",
    description="Manually switch to the next proxy (Admin only)",
)
@app_commands.default_permissions(administrator=True)
async def switchproxy_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    global _proxy_list
    old = _current_proxy

    # Always pull fresh proxy list from GitHub so manually added proxies are seen
    try:
        async with aiohttp.ClientSession() as session:
            saved, _ = await read_proxies(session)
            fresh = saved.get("proxies", []) if isinstance(saved, dict) else []
            if fresh:
                _proxy_list = fresh
                print(f"🔄 [switchproxy] Refreshed proxy list from GitHub: {len(fresh)} proxies")
    except Exception as e:
        print(f"⚠️ [switchproxy] Could not refresh from GitHub: {e}")

    # Build candidate list — skip current, append ENV as last resort
    candidates = [p for p in _proxy_list if p != _current_proxy]
    if ENV_PROXY_URL and ENV_PROXY_URL != _current_proxy and ENV_PROXY_URL not in candidates:
        candidates.append(ENV_PROXY_URL)

    if not candidates:
        await interaction.followup.send("⚠️ No other proxy available to switch to.", ephemeral=True)
        return

    # Test each candidate in order — use same URLs/timeout as health check
    async def _quick_test(proxy: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                for url in _PROXY_TEST_URLS:
                    async with session.get(
                        url,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=_PROXY_PASS_TIMEOUT),
                        ssl=False,
                    ) as resp:
                        if resp.status not in (200, 401):
                            return False
            return True
        except Exception:
            return False

    await interaction.followup.send(
        f"🔍 Testing {len(candidates)} candidate(s)...", ephemeral=True
    )

    chosen = None
    failed = 0
    for proxy in candidates:
        print(f"🔍 [switchproxy] Testing {proxy}...")
        if await _quick_test(proxy):
            chosen = proxy
            print(f"✅ [switchproxy] {proxy} passed")
            break
        else:
            failed += 1
            print(f"❌ [switchproxy] {proxy} failed")

    if not chosen:
        await interaction.followup.send(
            f"❌ All {failed} candidate(s) failed the test — proxy not switched.", ephemeral=True
        )
        return

    await _do_proxy_switch(chosen, _proxy_list, reason=f"manual by {interaction.user}")

    new = _current_proxy
    embed = discord.Embed(title="🔄 Proxy Switched", color=0x2ecc71)
    embed.add_field(name="Old", value=old or "None", inline=False)
    embed.add_field(name="New (tested ✅)", value=new or "None (direct)", inline=False)
    embed.add_field(name="Skipped (failed)", value=str(failed), inline=True)
    embed.add_field(name="Pool Size", value=str(len(_proxy_list)), inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── /proxyscan ───────────────────────────────────────────────────────────────────


@bot.tree.command(
    name="proxyscan",
    description="Fetch, test all free proxies and save the best ones to GitHub (Admin only)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    save="Save valid proxies to GitHub after scanning (default: True)",
    switch="Switch to the fastest proxy found if current is dead (default: True)",
)
async def proxyscan_cmd(
    interaction: discord.Interaction,
    save: bool = True,
    switch: bool = True,
):
    """
    Admin command: manually trigger a full free-proxy scan.
    1. Fetches candidates from ProxyScrape + ProxyDB concurrently.
    2. Multi-pass validates every candidate against Discord URLs.
    3. Optionally saves top-50 results to proxies.json in GitHub.
    4. Optionally switches the bot to the fastest found proxy (only if current is dead).
    Responds ephemerally with a live progress update, then a final results embed.
    """
    await interaction.response.defer(ephemeral=True)

    # ── Step 1: Fetch candidates ──────────────────────────────────────────────
    await interaction.followup.send(
        "🔍 **Step 1/3** — Fetching proxy candidates from ProxyScrape + ProxyDB…",
        ephemeral=True,
    )

    try:
        async with aiohttp.ClientSession() as session:
            candidates = await _fetch_and_filter_proxies(session)
    except Exception as e:
        await interaction.followup.send(
            f"❌ Failed to fetch proxy candidates: `{e}`", ephemeral=True
        )
        return

    if not candidates:
        await interaction.followup.send(
            "⚠️ No proxy candidates survived the metadata filter. Try again later.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ **{len(candidates)}** candidates fetched.\n"
        f"🧪 **Step 2/3** — Running multi-pass Discord validation "
        f"({_PROXY_CHECK_CONCURRENCY} concurrent workers, {_PROXY_PASSES} pass(es), "
        f"{_PROXY_PASS_TIMEOUT}s timeout each)…",
        ephemeral=True,
    )

    # ── Step 2: Validate candidates ───────────────────────────────────────────
    sem = asyncio.Semaphore(_PROXY_CHECK_CONCURRENCY)
    tasks = [
        asyncio.create_task(_test_proxy_passes(session, p, sem))
        for p in candidates
    ]
    # Use a fresh session for all validation tasks
    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(_PROXY_CHECK_CONCURRENCY)
        tasks = [
            asyncio.create_task(_test_proxy_passes(session, p, sem))
            for p in candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    valid: list[tuple[str, float]] = [
        r for r in results if isinstance(r, tuple)
    ]
    valid.sort(key=lambda x: x[1])  # fastest first

    if not valid:
        await interaction.followup.send(
            f"❌ None of the {len(candidates)} candidates passed Discord validation.",
            ephemeral=True,
        )
        return

    sorted_proxies = [p for p, _ in valid]
    best_proxy, best_lat = valid[0]
    top5_lines = "\n".join(
        f"`{i+1}.` `{p}` — {lat*1000:.0f} ms"
        for i, (p, lat) in enumerate(valid[:5])
    )

    # ── Step 3: Save to GitHub ────────────────────────────────────────────────
    save_status = "⏭️ Skipped (save=False)"
    if save:
        await interaction.followup.send(
            f"💾 **Step 3/3** — Saving top {min(50, len(sorted_proxies))} proxies to GitHub…",
            ephemeral=True,
        )
        try:
            async with aiohttp.ClientSession() as session:
                _, sha = await read_proxies(session)
                payload = {
                    "proxies": sorted_proxies[:50],
                    "saved_at": time.time(),
                    "saved_by": str(interaction.user),
                }
                ok = await write_proxies(
                    session, payload, sha,
                    f"proxyscan: {len(valid)} valid proxies by {interaction.user}",
                )
            if ok:
                save_status = f"✅ Saved top {min(50, len(sorted_proxies))} to GitHub"
                # Update the in-memory pool too
                global _proxy_list
                _proxy_list = sorted_proxies[:50]
            else:
                save_status = "⚠️ GitHub write returned False — not saved"
        except Exception as e:
            save_status = f"❌ GitHub save failed: `{_short_reason(str(e))}`"
    else:
        save_status = "⏭️ Skipped (save=False)"

    # ── Step 4: Optionally switch proxy ───────────────────────────────────────
    switch_status = "⏭️ Skipped (switch=False)"
    if switch:
        alive, _ = await _verify_proxy(_current_proxy)
        if not alive:
            await _do_proxy_switch(
                best_proxy, sorted_proxies,
                reason=f"proxyscan by {interaction.user}",
            )
            switch_status = f"✅ Switched to fastest: `{best_proxy}`"
        else:
            switch_status = f"✅ Current proxy still alive — not switching"

    # ── Final results embed ───────────────────────────────────────────────────
    embed = discord.Embed(title="🔎 Proxy Scan Complete", color=0x2ecc71)
    embed.add_field(name="Candidates Fetched", value=str(len(candidates)), inline=True)
    embed.add_field(name="Passed Validation", value=str(len(valid)), inline=True)
    embed.add_field(name="Failed", value=str(len(candidates) - len(valid)), inline=True)
    embed.add_field(name="Fastest Proxy", value=f"`{best_proxy}` — {best_lat*1000:.0f} ms", inline=False)
    embed.add_field(name="Top 5", value=top5_lines, inline=False)
    embed.add_field(name="GitHub Save", value=save_status, inline=False)
    embed.add_field(name="Proxy Switch", value=switch_status, inline=False)
    embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(
    name="config_role",
    description="Add or remove a role from the allowed roles list (Admin only)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="add or remove", role="Role to configure")
@app_commands.choices(
    action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ]
)
async def config_role(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    role: discord.Role = None,
):
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    async with aiohttp.ClientSession() as session:
        all_cfg, sha = await github_read_json(session, FILE_SERVER_CFG)
        cfg = all_cfg.get(guild_id, {})
        roles = cfg.get("allowed_roles", [])

        if action.value == "list":
            if not roles:
                msg = "No allowed roles configured."
            else:
                msg = "**Allowed roles:**\n" + "\n".join(f"<@&{r}>" for r in roles)
            await interaction.followup.send(msg, ephemeral=True)
            return

        if not role:
            await interaction.followup.send("❌ Please provide a role.", ephemeral=True)
            return

        if action.value == "add":
            if role.id in roles:
                await interaction.followup.send(f"⚠️ {role.mention} is already allowed.", ephemeral=True)
                return
            roles.append(role.id)
            msg = f"✅ Added {role.mention} to allowed roles."
        else:
            if role.id not in roles:
                await interaction.followup.send(f"❌ {role.mention} is not in allowed roles.", ephemeral=True)
                return
            roles.remove(role.id)
            msg = f"✅ Removed {role.mention} from allowed roles."

        cfg["allowed_roles"] = roles
        all_cfg[guild_id] = cfg
        await github_write_json(session, FILE_SERVER_CFG, all_cfg, sha, f"Update allowed_roles for guild {guild_id}")

    await interaction.followup.send(msg, ephemeral=True)



# ── Health check server (keeps Render awake) ───────────────────────────────────


API_SECRET = os.environ.get("API_SECRET")  # set this in Render env vars


async def health(request):
    return web.Response(text="✅ Bot is running!")


def _check_auth(request):
    """Return True if the request carries a valid API_SECRET."""
    if not API_SECRET:
        return True  # no secret configured → open (not recommended for prod)
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET}"


MAL_BACKUP_BASE = "https://raw.githubusercontent.com/bal-mackup/mal-backup/refs/heads/master"


async def _malbackup_mal_to_anilist(media_type: str, mal_id: int) -> int | None:
    url = f"{MAL_BACKUP_BASE}/mal/{media_type}/{mal_id}.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return None
                data = await r.json(content_type=None)
                ani_id = data.get("aniId")
                return int(ani_id) if ani_id else None
    except Exception:
        return None


async def _malbackup_anilist_to_mal(media_type: str, anilist_id: int) -> int | None:
    url = f"{MAL_BACKUP_BASE}/anilist/{media_type}/{anilist_id}.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return None
                data = await r.json(content_type=None)
                mal_id = data.get("malId")
                return int(mal_id) if mal_id else None
    except Exception:
        return None


async def _api_check_media(request, media_type: str):
    """GET /api/check/{type}/{id}?id_type=anilist|mal|simkl&anilist_user_id=N&mal_user_id=N&simkl_user_id=N
    Returns the full entry if already in the list, or {exists: false}.
    Also returns is_admin: true if the caller's user ID matches any admin in admins.json.
    """
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        item_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid id in URL"}, status=400)

    id_type = request.rel_url.query.get("id_type", "anilist").lower()

    # Optional caller identity for admin check
    req_anilist_id = request.rel_url.query.get("anilist_user_id")
    req_mal_id     = request.rel_url.query.get("mal_user_id")
    req_simkl_id   = request.rel_url.query.get("simkl_user_id")

    if media_type in ("anime", "manga"):
        filepath = FILE_ANIME if media_type == "anime" else FILE_MANGA
        async with aiohttp.ClientSession() as session:
            entries, _ = await github_read_json(session, filepath)
            admins, _  = await read_admins(session)
        if id_type == "mal":
            entry = next((e for e in entries if e.get("mal_id") == item_id), None)
        else:
            entry = next((e for e in entries if e.get("anilist_id") == item_id), None)
    else:
        filepath = FILE_SHOWS if media_type == "show" else FILE_MOVIES
        async with aiohttp.ClientSession() as session:
            entries, _ = await github_read_json(session, filepath)
            admins, _  = await read_admins(session)
        entry = next((e for e in entries if e.get("simkl_id") == item_id), None)

    # Check if the caller is a bot admin by matching their service user ID
    is_admin = False
    for rec in admins.values():
        if req_anilist_id and str(rec.get("anilist_user_id", "")) == str(req_anilist_id):
            is_admin = True
            break
        if req_mal_id and str(rec.get("mal_user_id", "")) == str(req_mal_id):
            is_admin = True
            break
        if req_simkl_id and str(rec.get("simkl_user_id", "")) == str(req_simkl_id):
            is_admin = True
            break

    if entry:
        return web.json_response({"exists": True, "entry": entry, "is_admin": is_admin})
    return web.json_response({"exists": False, "is_admin": is_admin})


async def api_check_anime(request): return await _api_check_media(request, "anime")
async def api_check_manga(request): return await _api_check_media(request, "manga")
async def api_check_show(request): return await _api_check_media(request, "show")
async def api_check_movie(request): return await _api_check_media(request, "movie")


async def _api_add_media(request, media_type: str):
    """Shared handler for POST /api/add_anime and POST /api/add_manga.
    Accepts anilist_id or mal_id as primary — cross-references via mal-backup repo.
    All user fields are optional; the richer the caller sends, the better the snapshot.
    """
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    def _s(key):
        return (body.get(key) or "").strip() or None

    anilist_id      = body.get("anilist_id")
    mal_id          = body.get("mal_id")
    reason          = (body.get("reason") or "").strip()
    author          = _s("author")

    anilist_user_id = body.get("anilist_user_id")
    anilist_username = _s("anilist_username")
    anilist_avatar  = _s("anilist_avatar")

    mal_user_id     = body.get("mal_user_id")
    mal_username    = _s("mal_username")
    mal_avatar      = _s("mal_avatar")

    simkl_user_id   = body.get("simkl_user_id")
    simkl_username  = _s("simkl_username")
    simkl_avatar    = _s("simkl_avatar")

    discord_id      = body.get("discord_id")
    discord_username = _s("discord_username")
    discord_avatar  = _s("discord_avatar")

    if not reason:
        return web.json_response({"error": "Missing required field: reason"}, status=400)
    if len(reason) < 30:
        return web.json_response({"error": "Reason must be at least 30 characters"}, status=400)
    if len(reason) > 700:
        return web.json_response({"error": "Reason must be at most 700 characters"}, status=400)
    if not anilist_id and not mal_id:
        return web.json_response({"error": "Provide at least one of: anilist_id, mal_id"}, status=400)
    if not any([anilist_user_id, mal_user_id, simkl_user_id, anilist_username, mal_username, simkl_username]):
        return web.json_response({"error": "Provide at least one user identifier (anilist_user_id, mal_user_id, simkl_user_id, or a username)"}, status=400)
    if anilist_id is not None and not isinstance(anilist_id, int):
        return web.json_response({"error": "anilist_id must be an integer"}, status=400)
    if mal_id is not None and not isinstance(mal_id, int):
        return web.json_response({"error": "mal_id must be an integer"}, status=400)

    mb_type = "anime" if media_type == "ANIME" else "manga"
    mal_data = None  # Jikan fallback data

    # ── Resolve anilist_id ↔ mal_id cross-reference ──────────────────────────
    # Priority: AniList idMal lookup → mal-backup repo (fallback)
    if anilist_id is None and mal_id is not None:
        # Try AniList's own idMal field first (most reliable)
        async with aiohttp.ClientSession() as session:
            al_by_mal = await fetch_anilist_by_mal(session, mal_id, media_type)
        if al_by_mal:
            anilist_id = al_by_mal.get("id")
            print(f"✅ Resolved MAL ID {mal_id} → AniList ID {anilist_id} via idMal lookup")
        else:
            # Fallback to mal-backup repo
            anilist_id = await _malbackup_mal_to_anilist(mb_type, mal_id)
            if anilist_id:
                print(f"✅ Resolved MAL ID {mal_id} → AniList ID {anilist_id} via mal-backup")
            else:
                print(f"⚠️ Could not resolve MAL ID {mal_id} to AniList — will try Jikan fallback")

    if mal_id is None and anilist_id is not None:
        mal_id = await _malbackup_anilist_to_mal(mb_type, anilist_id)

    async with aiohttp.ClientSession() as session:
        media = None
        if anilist_id:
            media = await fetch_anilist(session, anilist_id, media_type)
            if not media:
                anilist_id = None

        if media:
            titles = media["title"]
            title = titles.get("english") or titles.get("romaji") or titles.get("native") or "Unknown"
            if mal_id is None:
                mal_id = media.get("idMal")
            score = media.get("averageScore") or "N/A"
            poster = media.get("coverImage", {}).get("large", "")
            nsfw = bool(media.get("isAdult") or False)
        elif mal_id:
            # ── Jikan fallback: fetch from MAL when not on AniList ───────────
            mal_data = await fetch_mal_jikan(session, mal_id, media_type)
            if mal_data:
                title = mal_data["title"]
                poster = mal_data["poster"]
                score = mal_data["score"]
                nsfw = mal_data["nsfw"]
                print(f"✅ Fetched MAL data via Jikan for MAL ID {mal_id}: {title}")
            else:
                title = f"MAL ID {mal_id}"
                score = "N/A"
                poster = ""
                nsfw = False
                print(f"⚠️ Jikan also failed for MAL ID {mal_id} — storing with minimal data")
        else:
            title = "Unknown"
            score = "N/A"
            poster = ""
            nsfw = False

        # Try users.json first for a full enriched snapshot
        users_data, _ = await read_users(session)
        identity_index = _build_identity_index(users_data)
        admins, _ = await read_admins(session)
        matched_profile = None
        for _discord_id, p in users_data.items():
            if anilist_user_id and p.get("anilist_user_id") == anilist_user_id:
                matched_profile = p
                break
            if mal_user_id and p.get("mal_user_id") == mal_user_id:
                matched_profile = p
                break
            if simkl_user_id and p.get("simkl_user_id") == simkl_user_id:
                matched_profile = p
                break

        if matched_profile:
            user_snapshot = _build_user_snapshot(matched_profile)
        else:
            # Build snapshot entirely from caller-supplied fields — no users.json needed
            user_snapshot = {
                "discord": {
                    "id": discord_id,
                    "username": discord_username,
                    "avatar": discord_avatar,
                },
                "anilist": {
                    "id": anilist_user_id,
                    "username": anilist_username,
                    "avatar": anilist_avatar,
                },
                "mal": {
                    "id": mal_user_id,
                    "username": mal_username,
                    "avatar": mal_avatar,
                },
                "simkl": {
                    "id": simkl_user_id,
                    "username": simkl_username,
                    "avatar": simkl_avatar,
                },
            }

        _mark_admin_flag(user_snapshot, admins)

        resolved_author = (
            author
            or user_snapshot.get("anilist", {}).get("username")
            or user_snapshot.get("mal", {}).get("username")
            or user_snapshot.get("simkl", {}).get("username")
            or user_snapshot.get("discord", {}).get("username")
            or "Unknown"
        )

        stored_reason = await _translate_reason(session, reason)

        new_reason_obj = {
            "discord_id": str(discord_id) if discord_id else None,
            "discord_username": discord_username,
            "user": user_snapshot,
            "author": resolved_author,
            "text": stored_reason,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA
        entries, sha = await github_read_json(session, filepath)

        # ── Upsert: if entry already exists, append reason instead of 409 ──────
        existing_idx = None
        if anilist_id:
            existing_idx = next((i for i, e in enumerate(entries) if e.get("anilist_id") == anilist_id), None)
        if existing_idx is None and mal_id:
            existing_idx = next((i for i, e in enumerate(entries) if e.get("mal_id") == mal_id), None)

        if existing_idx is not None:
            existing = entries[existing_idx]
            # Migrate legacy single reason into reasons[] if needed
            if "reasons" not in existing:
                first = {
                    "discord_id": existing.get("added_by_discord_id"),
                    "discord_username": existing.get("user", {}).get("discord", {}).get("username"),
                    "user": existing.get("user", {}),
                    "author": existing.get("author"),
                    "text": existing.get("reason", ""),
                    "added_at": None,
                }
                existing["reasons"] = [first]

            # Check this user hasn't already added a reason (cross-service identity match)
            _has_duplicate = any(
                _user_ids_overlap(user_snapshot, str(discord_id) if discord_id else None, r, identity_index)
                for r in existing["reasons"]
            )
            if _has_duplicate:
                return web.json_response(
                    {"error": "You already have a reason on this entry. Use /api/edit_reason to update it.", "title": existing["title"]},
                    status=409,
                )

            existing["reasons"].append(new_reason_obj)
            entries[existing_idx] = existing
            ok = await github_write_json(
                session, filepath, entries, sha,
                f"feat: add reason for '{existing['title']}' by {resolved_author} (API)",
            )
            upserted = True
            entry = existing
        else:
            # Brand new entry
            entry = {
                "anilist_id": anilist_id,
                "mal_id": mal_id,
                "title": title,
                "author": resolved_author,
                "reason": stored_reason,
                "reasons": [new_reason_obj],
                "user": user_snapshot,
                "added_by_discord_id": str(discord_id) if discord_id else None,
                "poster": poster,
                "score": score,
                "nsfw": nsfw,
            }
            entries.append(entry)
            ok = await github_write_json(
                session, filepath, entries, sha,
                f"feat: add {title} to community {media_type.lower()} by {resolved_author} (API)",
            )
            upserted = False

    if ok:
        if upserted:
            log_embed = discord.Embed(title=f"➕ Reason Added to {media_type.title()} via API", color=0x5865F2)
        else:
            log_embed = discord.Embed(title=f"📥 New {media_type.title()} Added via API", color=0x2EA043)
        log_embed.add_field(name="Title", value=entry.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Score", value=str(entry.get("score", "N/A")), inline=True)
        log_embed.add_field(name="Author", value=resolved_author, inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), DC=entry.get("added_by_discord_id")), inline=False)
        _log_reason_fields(log_embed, stored_reason)
        if entry.get("poster"):
            log_embed.set_thumbnail(url=entry["poster"])
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        status = 200 if upserted else 201
        return web.json_response({"success": True, "upserted": upserted, "entry": entry}, status=status)
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_add_anime(request):
    return await _api_add_media(request, "ANIME")

async def api_add_manga(request):
    return await _api_add_media(request, "MANGA")


async def _api_add_simkl(request, media_type: str):
    """Shared handler for POST /api/add_show and POST /api/add_movie.
    All user fields are optional; the richer the caller sends, the better the snapshot.
    """
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    def _s(key):
        return (body.get(key) or "").strip() or None

    simkl_id        = body.get("simkl_id")
    reason          = (body.get("reason") or "").strip()
    author          = _s("author")

    simkl_user_id   = body.get("simkl_user_id")
    simkl_username  = _s("simkl_username")
    simkl_avatar    = _s("simkl_avatar")

    anilist_user_id = body.get("anilist_user_id")
    anilist_username = _s("anilist_username")
    anilist_avatar  = _s("anilist_avatar")

    mal_user_id     = body.get("mal_user_id")
    mal_username    = _s("mal_username")
    mal_avatar      = _s("mal_avatar")

    discord_id      = body.get("discord_id")
    discord_username = _s("discord_username")
    discord_avatar  = _s("discord_avatar")

    missing = [k for k, v in [("simkl_id", simkl_id), ("reason", reason)] if not v]
    if missing:
        return web.json_response({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)
    if len(reason) < 30:
        return web.json_response({"error": "Reason must be at least 30 characters"}, status=400)
    if len(reason) > 700:
        return web.json_response({"error": "Reason must be at most 700 characters"}, status=400)

    if not isinstance(simkl_id, int):
        return web.json_response({"error": "simkl_id must be an integer"}, status=400)

    if not SIMKL_CLIENT_ID:
        return web.json_response({"error": "SIMKL_CLIENT_ID not configured on server"}, status=500)

    if media_type == "show":
        media = await _simkl_fetch_show(simkl_id)
    else:
        media = await _simkl_fetch_movie(simkl_id)

    if not media:
        return web.json_response(
            {"error": f"Could not find {media_type} with simkl_id={simkl_id} on Simkl"},
            status=404,
        )

    title = media.get("title") or media.get("en_title") or f"Simkl ID {simkl_id}"
    poster_url = _simkl_poster(media)
    score = media.get("ratings", {}).get("simkl", {}).get("rating") or "N/A"
    genres = ", ".join(media.get("genres", [])[:4]) or "N/A"
    year = media.get("year") or ""
    _adult_certs = {"NC-17", "X", "TV-MA", "R18", "18+", "AO"}
    certification = (media.get("certification") or "").upper().strip()
    nsfw = certification in _adult_certs
    simkl_url = f"https://simkl.com/{media_type}s/{simkl_id}"

    async with aiohttp.ClientSession() as session:
        users_data, _ = await read_users(session)
        identity_index = _build_identity_index(users_data)
        admins, _ = await read_admins(session)

    matched_profile = None
    for _discord_id, p in users_data.items():
        if simkl_user_id and p.get("simkl_user_id") == simkl_user_id:
            matched_profile = p
            break
        if simkl_username and p.get("simkl_username", "").lower() == simkl_username.lower():
            matched_profile = p
            break
        if anilist_user_id and p.get("anilist_user_id") == anilist_user_id:
            matched_profile = p
            break
        if mal_user_id and p.get("mal_user_id") == mal_user_id:
            matched_profile = p
            break

    if matched_profile:
        user_snapshot = _build_user_snapshot(matched_profile)
        resolved_author = (
            author
            or matched_profile.get("author_name")
            or matched_profile.get("simkl_username")
            or matched_profile.get("anilist_username")
            or matched_profile.get("mal_username")
            or "Unknown"
        )
    else:
        # Build snapshot entirely from caller-supplied fields — no users.json needed
        user_snapshot = {
            "discord": {
                "id": discord_id,
                "username": discord_username,
                "avatar": discord_avatar,
            },
            "anilist": {
                "id": anilist_user_id,
                "username": anilist_username,
                "avatar": anilist_avatar,
            },
            "mal": {
                "id": mal_user_id,
                "username": mal_username,
                "avatar": mal_avatar,
            },
            "simkl": {
                "id": simkl_user_id,
                "username": simkl_username,
                "avatar": simkl_avatar,
            },
        }
        resolved_author = (
            author
            or simkl_username
            or anilist_username
            or mal_username
            or discord_username
            or "Unknown"
        )

    _mark_admin_flag(user_snapshot, admins)

    async with aiohttp.ClientSession() as _tr_session:
        stored_reason = await _translate_reason(_tr_session, reason)

    new_reason_obj = {
        "discord_id": str(discord_id) if discord_id else None,
        "discord_username": discord_username,
        "user": user_snapshot,
        "author": resolved_author,
        "text": stored_reason,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    filepath = FILE_SHOWS if media_type == "show" else FILE_MOVIES

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
        existing_idx = next((i for i, e in enumerate(entries) if e.get("simkl_id") == simkl_id), None)

        if existing_idx is not None:
            existing = entries[existing_idx]
            # Migrate legacy single reason into reasons[] if needed
            if "reasons" not in existing:
                first = {
                    "discord_id": existing.get("added_by_discord_id"),
                    "discord_username": existing.get("user", {}).get("discord", {}).get("username"),
                    "user": existing.get("user", {}),
                    "author": existing.get("author"),
                    "text": existing.get("reason", ""),
                    "added_at": None,
                }
                existing["reasons"] = [first]

            # Check this user hasn't already added a reason (cross-service identity match)
            _has_duplicate = any(
                _user_ids_overlap(user_snapshot, str(discord_id) if discord_id else None, r, identity_index)
                for r in existing["reasons"]
            )
            if _has_duplicate:
                return web.json_response(
                    {"error": "You already have a reason on this entry. Use /api/edit_reason to update it.", "title": existing["title"]},
                    status=409,
                )

            existing["reasons"].append(new_reason_obj)
            entries[existing_idx] = existing
            ok = await github_write_json(
                session, filepath, entries, sha,
                f"feat: add reason for '{existing['title']}' by {resolved_author} (API)",
            )
            upserted = True
            entry = existing
        else:
            entry = {
                "simkl_id": simkl_id,
                "title": title,
                "year": year,
                "author": resolved_author,
                "reason": stored_reason,
                "reasons": [new_reason_obj],
                "user": user_snapshot,
                "added_by_discord_id": str(discord_id) if discord_id else None,
                "poster": poster_url or "",
                "score": score,
                "genres": genres,
                "simkl_url": simkl_url,
                "nsfw": nsfw,
            }
            entries.append(entry)
            ok = await github_write_json(
                session, filepath, entries, sha,
                f"feat: add {title} to community {media_type} by {resolved_author} (API)",
            )
            upserted = False

    if ok:
        if upserted:
            log_embed = discord.Embed(title=f"➕ Reason Added to {media_type.title()} via API", color=0x5865F2)
        else:
            log_embed = discord.Embed(title=f"📥 New {media_type.title()} Added via API", color=0x2EA043)
        log_embed.add_field(name="Title", value=entry.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Score", value=str(entry.get("score", "N/A")), inline=True)
        log_embed.add_field(name="Author", value=resolved_author, inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(Simkl=entry.get("simkl_id"), DC=entry.get("added_by_discord_id")), inline=False)
        _log_reason_fields(log_embed, stored_reason)
        if entry.get("poster"):
            log_embed.set_thumbnail(url=entry["poster"])
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        status = 200 if upserted else 201
        return web.json_response({"success": True, "upserted": upserted, "entry": entry}, status=status)
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_add_show(request):
    return await _api_add_simkl(request, "show")


async def api_add_movie(request):
    return await _api_add_simkl(request, "movie")


# ══════════════════════════════════════════════════════════════════════════════
# OAuth Callback Handlers
# ══════════════════════════════════════════════════════════════════════════════

async def _oauth_save_profile(discord_id: str, service: str, profile_data: dict, access_token: str, extra_fields: dict | None = None) -> bool:
    """Save/update a user's OAuth-linked profile in users.json. Returns True on success."""
    encrypted = _oauth_encrypt_token(access_token)
    if not encrypted:
        print(f"[OAuth save] Failed to encrypt {service} token for {discord_id}")
        return False

    async with aiohttp.ClientSession() as session:
        users, sha = await read_users(session)
        existing = users.get(discord_id, {})

        # Merge new fields into existing
        merged = {**existing}
        merged.update(extra_fields or {})
        merged[f"{service}_token"] = encrypted
        merged.update(profile_data)

        users[discord_id] = merged
        ok = await write_users(
            session, users, sha,
            f"link: {service} OAuth for discord:{discord_id}",
        )

        # If this user is also a bot admin, sync their linked account info into admins.json
        if ok:
            await _sync_admin_from_user(session, discord_id, merged, source=f"{service} OAuth")

        return ok


# ── AniList OAuth (authorization code flow) ─────────────────────────────────────

async def _anilist_exchange_code(code: str) -> dict | None:
    """Exchange AniList authorization code for access token."""
    if not ANILIST_CLIENT_ID:
        print("[AniList OAuth] ANILIST_CLIENT_ID not configured")
        return None

    payload = {
        "grant_type": "authorization_code",
        "client_id": ANILIST_CLIENT_ID,
        "redirect_uri": f"{OAUTH_BASE_URL}/oauth/anilist/callback",
        "code": code,
    }
    if ANILIST_CLIENT_SECRET:
        payload["client_secret"] = ANILIST_CLIENT_SECRET

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://anilist.co/api/v2/oauth/token",
                json=payload,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[AniList OAuth] token exchange failed: status={r.status} body={body[:300]}")
                    return None
                return await r.json()
    except Exception as e:
        print(f"[AniList OAuth] token exchange exception: {e}")
        return None


async def anilist_callback(request):
    """AniList redirects here with ?code=xxx."""
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")

    if error:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("anilist", f"Authorization denied: {error}"),
        )

    if not code or not state:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("anilist", "Missing authorization code. Try again."),
        )

    pending = _consume_oauth_state(state)
    if not pending:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("anilist", "Invalid or expired session. Run /link_anilist in Discord again."),
        )

    discord_id = pending["discord_id"]

    # Exchange code for token
    token_data = await _anilist_exchange_code(code)
    if not token_data:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("anilist", "Failed to exchange authorization code for token."),
        )

    access_token = token_data["access_token"]

    # Fetch the authenticated user profile using the token
    query = """
    query {
        Viewer {
            id name avatar { large }
            bannerImage siteUrl about
            statistics {
                anime { count meanScore minutesWatched episodesWatched }
                manga { count chaptersRead volumesRead }
            }
        }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return web.Response(
                        content_type="text/html",
                        text=_oauth_failure_html("anilist", f"AniList API returned {r.status}"),
                    )
                data = await r.json()
            viewer = data.get("data", {}).get("Viewer")
            if not viewer:
                return web.Response(
                    content_type="text/html",
                    text=_oauth_failure_html("anilist", "Could not fetch your AniList profile after authorization."),
                )
    except Exception as e:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("anilist", f"AniList request failed: {e}"),
        )

    stats = viewer.get("statistics", {})
    anime_stats = stats.get("anime", {})
    manga_stats = stats.get("manga", {})

    profile_data = {
        "anilist_user_id": viewer["id"],
        "anilist_username": viewer["name"],
        "anilist_url": viewer.get("siteUrl"),
        "anilist_avatar": viewer.get("avatar", {}).get("large"),
        "anilist_banner": viewer.get("bannerImage"),
        "anilist_about": (viewer.get("about") or "")[:300],
        "anilist_anime_count": anime_stats.get("count"),
        "anilist_manga_count": manga_stats.get("count"),
        "anilist_mean_score": anime_stats.get("meanScore"),
        "anilist_minutes_watched": anime_stats.get("minutesWatched"),
        "anilist_chapters_read": manga_stats.get("chaptersRead"),
    }

    ok = await _oauth_save_profile(
        discord_id, "anilist", profile_data, access_token,
        extra_fields={
            "discord_id": pending.get("discord_id"),
            "discord_username": pending.get("discord_username"),
            "discord_display_name": pending.get("discord_display_name"),
            "discord_avatar": pending.get("discord_avatar"),
        },
    )
    if not ok:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("anilist", "Failed to save profile. Try again."),
        )

    # Store result for Discord followup
    _oauth_results[state] = {
        "success": True,
        "service": "anilist",
        "discord_id": discord_id,
        "username": viewer["name"],
        "user_id": viewer["id"],
        "avatar": viewer.get("avatar", {}).get("large"),
        "anime_count": anime_stats.get("count"),
        "manga_count": manga_stats.get("count"),
        "mean_score": anime_stats.get("meanScore"),
    }

    return web.Response(
        content_type="text/html",
        text=_oauth_success_html("anilist", viewer["name"], viewer.get("avatar", {}).get("large")),
    )


# ── MAL OAuth ───────────────────────────────────────────────────────────────────

# Store PKCE verifiers temporarily: {state: code_verifier}
_mal_pkce_store: dict[str, str] = {}


async def mal_callback(request):
    """MAL redirects here with ?code=xxx&state=xxx."""
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")

    if error:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("mal", f"Authorization denied: {error}"),
        )

    if not code or not state:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("mal", "Missing authorization code. Try again."),
        )

    pending = _consume_oauth_state(state)
    if not pending:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("mal", "Invalid or expired session. Run /link_mal in Discord again."),
        )

    discord_id = pending["discord_id"]
    verifier = _mal_pkce_store.pop(state, None)

    # Exchange code for token
    token_data = await _mal_exchange_code(code, verifier)
    if not token_data:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("mal", "Failed to exchange authorization code for token."),
        )

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")

    # Fetch user profile
    profile = await _mal_fetch_authenticated_user(access_token)
    if not profile:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("mal", "Failed to fetch your MAL profile after authorization."),
        )

    encrypted_token = _oauth_encrypt_token(access_token)
    encrypted_refresh = _oauth_encrypt_token(refresh_token) if refresh_token else None

    profile_data = {
        "mal_user_id": profile["id"],
        "mal_username": profile["username"],
        "mal_url": profile["url"],
        "mal_avatar": profile["avatar"],
        "mal_anime_completed": profile.get("anime_completed"),
        "mal_anime_mean_score": profile.get("anime_mean_score"),
        "mal_manga_completed": profile.get("manga_completed"),
        "mal_manga_mean_score": profile.get("manga_mean_score"),
    }
    if encrypted_token:
        profile_data["mal_token"] = encrypted_token
    if encrypted_refresh:
        profile_data["mal_refresh_token"] = encrypted_refresh

    ok = await _oauth_save_profile(
        discord_id, "mal", profile_data, access_token,
        extra_fields={
            "discord_id": pending.get("discord_id"),
            "discord_username": pending.get("discord_username"),
            "discord_display_name": pending.get("discord_display_name"),
            "discord_avatar": pending.get("discord_avatar"),
        },
    )
    if not ok:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("mal", "Failed to save profile. Try again."),
        )

    # Store result for Discord followup
    _oauth_results[state] = {
        "success": True,
        "service": "mal",
        "discord_id": discord_id,
        "username": profile["username"],
        "user_id": profile["id"],
        "avatar": profile["avatar"],
        "anime_completed": profile.get("anime_completed"),
        "manga_completed": profile.get("manga_completed"),
    }

    return web.Response(
        content_type="text/html",
        text=_oauth_success_html("mal", profile["username"], profile["avatar"]),
    )


async def _mal_exchange_code(code: str, code_verifier: str | None) -> dict | None:
    """Exchange MAL authorization code for access token."""
    if not MAL_CLIENT_ID or not MAL_CLIENT_SECRET:
        print("[MAL OAuth] MAL_CLIENT_ID or MAL_CLIENT_SECRET not configured")
        return None

    payload = {
        "client_id": MAL_CLIENT_ID,
        "client_secret": MAL_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"{OAUTH_BASE_URL}/oauth/mal/callback",
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://myanimelist.net/v1/oauth2/token",
                data=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[MAL OAuth] token exchange failed: status={r.status} body={body[:300]}")
                    return None
                return await r.json()
    except Exception as e:
        print(f"[MAL OAuth] token exchange exception: {e}")
        return None


async def _mal_fetch_authenticated_user(access_token: str) -> dict | None:
    """Fetch MAL user profile using OAuth token. Returns user dict or None with error details logged."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{MAL_API}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "anime_statistics,manga_statistics"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[MAL OAuth] fetch user failed: status={r.status} body={body[:300]}")
                    return None
                data = await r.json()
    except Exception as e:
        print(f"[MAL OAuth] fetch user exception: {e}")
        return None

    anime_stats = data.get("anime_statistics") or {}
    manga_stats = data.get("manga_statistics") or {}
    return {
        "id": data.get("id"),
        "username": data.get("name"),
        "url": f"https://myanimelist.net/profile/{data.get('name', '')}",
        "avatar": data.get("picture"),
        "anime_completed": anime_stats.get("num_items_completed"),
        "anime_mean_score": anime_stats.get("mean_score"),
        "manga_completed": manga_stats.get("num_items_completed") if manga_stats else None,
        "manga_mean_score": manga_stats.get("mean_score") if manga_stats else None,
    }


# ── Simkl OAuth (redirect flow) ─────────────────────────────────────────────────

async def simkl_callback(request):
    """Simkl redirects here with ?code=xxx&state=xxx."""
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")

    if error:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", f"Authorization denied: {error}"),
        )

    if not code or not state:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", "Missing authorization code. Try again."),
        )

    pending = _consume_oauth_state(state)
    if not pending:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", "Invalid or expired session. Run /link_simkl in Discord again."),
        )

    discord_id = pending["discord_id"]

    # Exchange code for token via Simkl OAuth token endpoint (POST, JSON body)
    if not SIMKL_CLIENT_ID or not SIMKL_CLIENT_SECRET:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", "Simkl integration is not fully configured (missing client_id or client_secret)."),
        )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.simkl.com/oauth/token",
                json={
                    "code": code,
                    "client_id": SIMKL_CLIENT_ID,
                    "client_secret": SIMKL_CLIENT_SECRET,
                    "redirect_uri": f"{OAUTH_BASE_URL}/oauth/simkl/callback",
                    "grant_type": "authorization_code",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[Simkl OAuth] token exchange failed: status={r.status} body={body[:300]}")
                    return web.Response(
                        content_type="text/html",
                        text=_oauth_failure_html("simkl", f"Token exchange failed (status {r.status})."),
                    )
                data = await r.json()
                access_token = data.get("access_token")
                if not access_token:
                    return web.Response(
                        content_type="text/html",
                        text=_oauth_failure_html("simkl", "No access token received."),
                    )

        # Fetch Simkl user profile
        simkl_profile = await _simkl_fetch_user_with_token(access_token)
        if not simkl_profile:
            return web.Response(
                content_type="text/html",
                text=_oauth_failure_html("simkl", "Authorized but failed to fetch your Simkl profile."),
            )
    except Exception as e:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", f"Request failed: {e}"),
        )

    encrypted = _simkl_encrypt_token(access_token) if SIMKL_ENCRYPT_KEY else _oauth_encrypt_token(access_token)
    if not encrypted:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", "Failed to encrypt your token. Contact admin."),
        )

    # Save to users.json
    async with aiohttp.ClientSession() as session:
        users, sha = await read_users(session)
        existing = users.get(discord_id, {})
        # Save Discord identity from the OAuth state
        if pending.get("discord_username"):
            existing["discord_username"] = pending["discord_username"]
        if pending.get("discord_display_name"):
            existing["discord_display_name"] = pending["discord_display_name"]
        if pending.get("discord_avatar"):
            existing["discord_avatar"] = pending["discord_avatar"]
        if pending.get("discord_id"):
            existing["discord_id"] = pending["discord_id"]
        existing["simkl_username"] = simkl_profile["username"]
        existing["simkl_user_id"] = simkl_profile["user_id"]
        existing["simkl_avatar"] = simkl_profile["avatar_url"]
        existing["simkl_token"] = encrypted
        users[discord_id] = existing
        ok = await write_users(
            session, users, sha,
            f"link: Simkl OAuth redirect for discord:{discord_id}",
        )
        # Sync admin if applicable
        if ok:
            await _sync_admin_from_user(session, discord_id, existing, source="Simkl OAuth redirect")

    if not ok:
        return web.Response(
            content_type="text/html",
            text=_oauth_failure_html("simkl", "Failed to save profile. Try again."),
        )

    _oauth_results[state] = {
        "success": True,
        "service": "simkl",
        "discord_id": discord_id,
        "username": simkl_profile["username"],
        "user_id": simkl_profile["user_id"],
        "avatar": simkl_profile["avatar_url"],
    }

    return web.Response(
        content_type="text/html",
        text=_oauth_success_html("simkl", simkl_profile["username"], simkl_profile["avatar_url"]),
    )


# ── OAuth status check (for Discord bot to poll) ────────────────────────────────

async def oauth_status(request):
    """GET /api/oauth/status?state=xxx — Discord bot polls this to check if OAuth completed."""
    state = request.query.get("state")
    if not state:
        return web.json_response({"status": "pending"}, status=400)
    result = _oauth_results.pop(state, None)
    if result:
        return web.json_response(result)
    return web.json_response({"status": "pending"})


# ══════════════════════════════════════════════════════════════════════════════
# Ownership helper — matches on ALL linked IDs
# ══════════════════════════════════════════════════════════════════════════════

def _entry_owned_by(entry: dict, discord_id: str, profile: dict | None = None) -> bool:
    """
    Return True if this discord user owns this entry.
    Checks (in order):
      1. added_by_discord_id field (fastest, for new entries)
      2. entry.user.discord.id
      3. entry.user.anilist.id  vs  profile.anilist_user_id
      4. entry.user.mal.id      vs  profile.mal_user_id
      5. entry.user.simkl.id    vs  profile.simkl_user_id
      6. entry.user.simkl.username vs profile.simkl_username
    """
    # 1. Flat field stamp (new entries)
    if entry.get("added_by_discord_id") and str(entry["added_by_discord_id"]) == str(discord_id):
        return True

    u = entry.get("user", {})

    # 2. Discord ID inside snapshot
    snap_discord_id = u.get("discord", {}).get("id")
    if snap_discord_id and str(snap_discord_id) == str(discord_id):
        return True

    if not profile:
        return False

    # 3. AniList ID
    snap_al = u.get("anilist", {}).get("id")
    prof_al = profile.get("anilist_user_id")
    if snap_al and prof_al and snap_al == prof_al:
        return True

    # 4. MAL ID
    snap_mal = u.get("mal", {}).get("id")
    prof_mal = profile.get("mal_user_id")
    if snap_mal and prof_mal and snap_mal == prof_mal:
        return True

    # 5. Simkl user ID
    snap_simkl_id = u.get("simkl", {}).get("id")
    prof_simkl_id = profile.get("simkl_user_id")
    if snap_simkl_id and prof_simkl_id and snap_simkl_id == prof_simkl_id:
        return True

    # 6. Simkl username (case-insensitive)
    snap_simkl_uname = (u.get("simkl", {}).get("username") or "").lower()
    prof_simkl_uname = (profile.get("simkl_username") or "").lower()
    if snap_simkl_uname and prof_simkl_uname and snap_simkl_uname == prof_simkl_uname:
        return True

    return False


def _entry_owned_by_api(entry: dict, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_username) -> bool:
    """
    Ownership check for API callers who may not have a users.json profile.
    Checks all provided IDs against the entry's user snapshot + added_by_discord_id.
    """
    u = entry.get("user", {})

    if req_discord_id:
        if entry.get("added_by_discord_id") and str(entry["added_by_discord_id"]) == str(req_discord_id):
            return True
        if str(u.get("discord", {}).get("id", "")) == str(req_discord_id):
            return True

    if req_anilist_id and u.get("anilist", {}).get("id") == req_anilist_id:
        return True

    if req_mal_id and u.get("mal", {}).get("id") == req_mal_id:
        return True

    if req_simkl_id and u.get("simkl", {}).get("id") == req_simkl_id:
        return True

    if req_simkl_username and (u.get("simkl", {}).get("username") or "").lower() == req_simkl_username.lower():
        return True

    return False

def _find_reason_idx(reasons: list, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_username, identity_index: dict | None = None):
    """
    Find the index of the reason in reasons[] that belongs to the calling user.
    Uses cross-service identity matching: collects ALL IDs from both the incoming
    request and each stored reason, enriches via identity_index (from users.json),
    and checks for any overlap. This handles the case where a user added a reason
    via AniList and later tries to edit/delete via MAL (or vice versa).
    """
    # Build incoming identity set from all provided IDs
    incoming_ids: set[str] = set()
    if req_discord_id:
        incoming_ids.add(str(req_discord_id))
    if req_anilist_id:
        incoming_ids.add(str(req_anilist_id))
    if req_mal_id:
        incoming_ids.add(str(req_mal_id))
    if req_simkl_id:
        incoming_ids.add(str(req_simkl_id))
    if req_simkl_username:
        incoming_ids.add(req_simkl_username.lower())
    incoming_ids.discard("")
    incoming_ids.discard("None")

    # Enrich via users.json index
    if identity_index:
        enriched_incoming = set(incoming_ids)
        for sid in incoming_ids:
            if sid in identity_index:
                enriched_incoming |= identity_index[sid]
        incoming_ids = enriched_incoming

    for i, r in enumerate(reasons):
        # Collect stored IDs from this reason
        stored_ids = _collect_identity_ids(r.get("user", {}), r.get("discord_id"))
        # Enrich stored IDs via users.json index
        if identity_index:
            enriched_stored = set(stored_ids)
            for sid in stored_ids:
                if sid in identity_index:
                    enriched_stored |= identity_index[sid]
            stored_ids = enriched_stored

        if incoming_ids & stored_ids:
            return i
    return None


def _find_reason_by_any_id(reasons: list, raw_id: str):
    """
    Find a reason in reasons[] by matching raw_id against ANY identity field.
    Looks directly in the entry's own data — no users.json needed.
    Matches: discord_id, discord.id, anilist.id, mal.id, simkl.id, simkl.username
    """
    for i, r in enumerate(reasons):
        u = r.get("user", {})
        # discord_id (flat field)
        if str(r.get("discord_id") or "") == str(raw_id):
            return i
        # discord.id (snapshot)
        if str(u.get("discord", {}).get("id") or "") == str(raw_id):
            return i
        # anilist.id
        if str(u.get("anilist", {}).get("id") or "") == str(raw_id):
            return i
        # mal.id
        if str(u.get("mal", {}).get("id") or "") == str(raw_id):
            return i
        # simkl.id
        if str(u.get("simkl", {}).get("id") or "") == str(raw_id):
            return i
        # simkl.username (case-insensitive)
        if (u.get("simkl", {}).get("username") or "").lower() == str(raw_id).lower():
            return i
    return None



# ══════════════════════════════════════════════════════════════════════════════
# /edit_reason  (slash)
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# /edit_reason  (slash)
# ══════════════════════════════════════════════════════════════════════════════

async def _edit_reason_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete that shows ALL entries (not just the user's own) for convenience."""
    mt = None
    for opt in (interaction.data or {}).get("options", []):
        if opt.get("name") == "media_type":
            mt = opt.get("value")
    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(mt, FILE_ANIME)
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, filepath)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    id_key = "simkl_id" if mt in ("show", "movie") else "anilist_id"
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e[id_key]))
        for e in filtered[:25]
        if e.get(id_key)
    ]


@bot.tree.command(name="edit_reason", description="Edit the reason for your entry (owner or bot admin only)")
@app_commands.describe(
    media_type="Which list to edit",
    title="Search for your entry",
    new_reason="The updated reason (30–700 characters)",
)
@app_commands.choices(media_type=[
    app_commands.Choice(name="Anime",   value="anime"),
    app_commands.Choice(name="Manga",   value="manga"),
    app_commands.Choice(name="TV Show", value="show"),
    app_commands.Choice(name="Movie",   value="movie"),
])
@app_commands.autocomplete(title=_edit_reason_autocomplete)
async def edit_reason(
    interaction: discord.Interaction,
    media_type: app_commands.Choice[str],
    title: str,
    new_reason: str,
):
    await interaction.response.defer(ephemeral=True)
    await _handle_edit_reason(interaction, media_type.value, title, new_reason)


async def _handle_edit_reason(
    interaction: discord.Interaction,
    media_type: str,
    title_or_id: str,
    new_reason: str,
):
    new_reason = new_reason.strip()
    if len(new_reason) < 30:
        await interaction.followup.send("❌ Reason must be at least **30 characters**.", ephemeral=True)
        return
    if len(new_reason) > 700:
        await interaction.followup.send(f"❌ Reason must be at most **700 characters** (yours is {len(new_reason)}).", ephemeral=True)
        return

    discord_id = str(interaction.user.id)
    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(media_type)
    id_key = "simkl_id" if media_type in ("show", "movie") else "anilist_id"

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
        users, _ = await read_users(session)
        admins, _ = await read_admins(session)

    profile = users.get(discord_id)
    admin = str(discord_id) in admins

    # Find entry
    if title_or_id.isdigit():
        idx = next((i for i, e in enumerate(entries) if str(e.get(id_key, "")) == title_or_id), None)
    else:
        idx = next((i for i, e in enumerate(entries) if title_or_id.lower() in e.get("title", "").lower()), None)

    if idx is None:
        await interaction.followup.send("❌ Entry not found.", ephemeral=True)
        return

    entry = entries[idx]

    if not admin and not _entry_owned_by(entry, discord_id, profile):
        await interaction.followup.send(
            "❌ You can only edit reasons for entries **you added**.",
            ephemeral=True,
        )
        return

    # Migrate legacy single reason into reasons[] if needed
    if "reasons" not in entry:
        first = {
            "discord_id": entry.get("added_by_discord_id"),
            "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
            "user": entry.get("user", {}),
            "author": entry.get("author"),
            "text": entry.get("reason", ""),
            "added_at": None,
        }
        entries[idx]["reasons"] = [first]
        entry = entries[idx]

    reasons = entry.get("reasons", [])

    # Find this user's reason slot
    reason_idx = next((i for i, r in enumerate(reasons) if str(r.get("discord_id") or "") == discord_id), None)

    # Admins editing someone else's entry: edit slot 0 as fallback
    if reason_idx is None and admin:
        reason_idx = 0

    if reason_idx is None:
        await interaction.followup.send(
            "❌ You don't have a reason on this entry.",
            ephemeral=True,
        )
        return

    old_reason = reasons[reason_idx].get("text", "")

    async with aiohttp.ClientSession() as _tr_session:
        stored_new_reason = await _translate_reason(_tr_session, new_reason)

    entries[idx]["reasons"][reason_idx]["text"] = stored_new_reason
    entries[idx]["reasons"][reason_idx]["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if reason_idx == 0:
        entries[idx]["reason"] = stored_new_reason

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha,
            f"edit: reason for '{entry['title']}' by {interaction.user} ({'admin' if admin else 'owner'})",
        )

    if ok:
        embed = discord.Embed(title="✅ Reason Updated", color=0x2EA043)
        embed.add_field(name="Entry", value=entry["title"], inline=False)
        embed.add_field(name="Old Reason", value=old_reason[:1024] or "*(empty)*", inline=False)
        _log_reason_fields(embed, stored_new_reason, label="New Reason")
        if admin and not _entry_owned_by(entry, discord_id, profile):
            embed.set_footer(text="✏️ Edited as bot admin")
        log_embed = discord.Embed(title="✏️ Reason Edited", color=0xF1C40F)
        log_embed.add_field(name="Entry", value=entry["title"], inline=True)
        log_embed.add_field(name="Edited by", value=f"{interaction.user.mention} (`{interaction.user}`) — {'admin' if admin else 'owner'}", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), Simkl=entry.get("simkl_id"), DC=interaction.user.id), inline=False)
        log_embed.add_field(name="Old Reason", value=old_reason[:1024] or "*(empty)*", inline=False)
        _log_reason_fields(log_embed, stored_new_reason, label="New Reason")
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="❌ Failed to save to GitHub", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /delete_entry  (slash)
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="delete_entry", description="Delete your own entry from any list (owner or bot admin only)")
@app_commands.describe(
    media_type="Which list to delete from",
    title="Search for your entry",
)
@app_commands.choices(media_type=[
    app_commands.Choice(name="Anime",   value="anime"),
    app_commands.Choice(name="Manga",   value="manga"),
    app_commands.Choice(name="TV Show", value="show"),
    app_commands.Choice(name="Movie",   value="movie"),
])
@app_commands.autocomplete(title=_edit_reason_autocomplete)
async def delete_entry(
    interaction: discord.Interaction,
    media_type: app_commands.Choice[str],
    title: str,
):
    await interaction.response.defer(ephemeral=True)
    await _handle_delete_entry(interaction, media_type.value, title)


async def _handle_delete_entry(
    interaction: discord.Interaction,
    media_type: str,
    title_or_id: str,
):
    discord_id = str(interaction.user.id)
    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(media_type)
    id_key = "simkl_id" if media_type in ("show", "movie") else "anilist_id"

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
        users, _ = await read_users(session)
        admins, _ = await read_admins(session)

    profile = users.get(discord_id)
    admin = str(discord_id) in admins

    if title_or_id.isdigit():
        idx = next((i for i, e in enumerate(entries) if str(e.get(id_key, "")) == title_or_id), None)
    else:
        idx = next((i for i, e in enumerate(entries) if title_or_id.lower() in e.get("title", "").lower()), None)

    if idx is None:
        await interaction.followup.send("❌ Entry not found.", ephemeral=True)
        return

    entry = entries[idx]

    if not admin and not _entry_owned_by(entry, discord_id, profile):
        await interaction.followup.send(
            "❌ You can only delete entries **you added**.",
            ephemeral=True,
        )
        return

    # Non-admins: don't delete — send a log request for admins to action
    if not admin:
        id_key = "simkl_id" if media_type in ("show", "movie") else "anilist_id"
        entry_id_val = entry.get(id_key, "N/A")
        p = _prefix_cache[0]
        # Show the user's linked service IDs so admins can identify them
        user_al = profile.get("anilist_user_id") if profile else None
        user_mal = profile.get("mal_user_id") if profile else None
        user_simkl = profile.get("simkl_user_id") if profile else None
        user_simkl_uname = profile.get("simkl_username") if profile else None
        # Pick the best identifier for the admin command
        admin_target = discord_id  # default
        if user_al: admin_target = str(user_al)
        elif user_mal: admin_target = str(user_mal)
        elif user_simkl: admin_target = str(user_simkl)
        elif user_simkl_uname: admin_target = user_simkl_uname
        log_embed = discord.Embed(
            title="🗑️ Deletion Requested by Owner",
            description=(
                f"{interaction.user.mention} has requested their entry be deleted.\n"
                f"**Admins:** please review and use the command below to confirm."
            ),
            color=0xF0A500,
        )
        log_embed.add_field(name="Title", value=entry.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Type", value=media_type.title(), inline=True)
        log_embed.add_field(name="Media IDs", value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), Simkl=entry.get("simkl_id")), inline=False)
        log_embed.add_field(name="User IDs", value=_ids_line(AL=user_al, MAL=user_mal, Simkl=user_simkl, DC=interaction.user.id), inline=False)
        log_embed.add_field(name="Reason", value=_short_reason(entry.get("reason")), inline=False)
        log_embed.add_field(
            name="Admin Command to Delete",
            value=f"`{p}delete_entry {media_type} {entry_id_val}`",
            inline=False,
        )
        log_embed.set_footer(text=f"Requested by {interaction.user} ({interaction.user.id})")
        await _send_log(log_embed)

        notify_embed = discord.Embed(
            title="📬 Deletion Request Submitted",
            description=(
                f"Your request to delete **{entry.get('title', 'this entry')}** has been sent to the admins.\n"
                "They will review and delete it using the admin command."
            ),
            color=0x5865F2,
        )
        await interaction.followup.send(embed=notify_embed, ephemeral=True)
        return

    # Admin path: delete immediately
    removed = entries.pop(idx)

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha,
            f"remove: '{removed['title']}' deleted by {interaction.user} (admin)",
        )

    if ok:
        embed = discord.Embed(title="🗑️ Entry Deleted", color=0xDA3633)
        embed.add_field(name="Title", value=removed["title"], inline=True)
        embed.add_field(name="Type", value=media_type.title(), inline=True)
        embed.set_footer(text="🛡️ Deleted as bot admin")
        log_embed = discord.Embed(title="🗑️ Entry Deleted by Admin", color=0xDA3633)
        log_embed.add_field(name="Title", value=removed["title"], inline=True)
        log_embed.add_field(name="Type", value=media_type.title(), inline=True)
        log_embed.add_field(name="Deleted by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_embed.add_field(name="Media IDs", value=_ids_line(AL=removed.get("anilist_id"), MAL=removed.get("mal_id"), Simkl=removed.get("simkl_id")), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(removed.get("reason")), inline=False)
        if removed.get("poster"):
            log_embed.set_thumbnail(url=removed["poster"])
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="❌ Failed to delete from GitHub", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /delete_reason  (slash — admin only)
# ══════════════════════════════════════════════════════════════════════════════


async def _delete_reason_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    mt = None
    for opt in (interaction.data or {}).get("options", []):
        if opt.get("name") == "media_type":
            mt = opt.get("value")
    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(mt, FILE_ANIME)
    id_key = "simkl_id" if mt in ("show", "movie") else "anilist_id"
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, filepath)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=f"{e['title'][:80]} ({len(e.get('reasons', []))} reasons)", value=str(e[id_key]))
        for e in filtered[:25]
        if e.get(id_key)
    ]


async def _user_autocomplete_for_delete_reason(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete that shows users who have reasons on a specific entry."""
    mt = None
    title_val = None
    for opt in (interaction.data or {}).get("options", []):
        if opt.get("name") == "media_type":
            mt = opt.get("value")
        if opt.get("name") == "title":
            title_val = opt.get("value")
    if not mt or not title_val:
        return []
    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(mt, FILE_ANIME)
    id_key = "simkl_id" if mt in ("show", "movie") else "anilist_id"
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, filepath)
    entry = next((e for e in entries if str(e.get(id_key, "")) == title_val), None)
    if not entry:
        return []
    reasons = entry.get("reasons", [])
    if not reasons:
        return []
    results = []
    for r in reasons:
        u = r.get("user", {})
        al_uname = u.get("anilist", {}).get("username") or ""
        al_id = u.get("anilist", {}).get("id") or ""
        mal_uname = u.get("mal", {}).get("username") or ""
        mal_id = u.get("mal", {}).get("id") or ""
        simkl_uname = u.get("simkl", {}).get("username") or ""
        simkl_id = u.get("simkl", {}).get("id") or ""
        dc_id = r.get("discord_id") or u.get("discord", {}).get("id") or ""
        label = al_uname or mal_uname or simkl_uname or str(dc_id)
        # Show which service IDs are available
        ids_parts = []
        if al_id:
            ids_parts.append(f"AL:{al_id}")
        if mal_id:
            ids_parts.append(f"MAL:{mal_id}")
        if simkl_id:
            ids_parts.append(f"Simkl:{simkl_id}")
        if dc_id:
            ids_parts.append(f"DC:{dc_id}")
        ids_str = " | ".join(ids_parts)
        display = f"{label} ({ids_str})" if ids_str else label
        if current.lower() in display.lower():
            results.append(app_commands.Choice(name=display[:100], value=str(dc_id or al_id or mal_id or simkl_id or simkl_uname or "")))
    return results[:25]


@bot.tree.command(name="delete_reason", description="Delete a specific user's reason from an entry (admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    media_type="Which list to search",
    title="Search for the entry",
    user="Select the user whose reason to delete",
)
@app_commands.choices(media_type=[
    app_commands.Choice(name="Anime",   value="anime"),
    app_commands.Choice(name="Manga",   value="manga"),
    app_commands.Choice(name="TV Show", value="show"),
    app_commands.Choice(name="Movie",   value="movie"),
])
@app_commands.autocomplete(title=_delete_reason_autocomplete, user=_user_autocomplete_for_delete_reason)
async def delete_reason(
    interaction: discord.Interaction,
    media_type: app_commands.Choice[str],
    title: str,
    user: str,
):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)

    async with aiohttp.ClientSession() as session:
        admins, _ = await read_admins(session)

    if discord_id not in admins:
        await interaction.followup.send("❌ This command is for bot admins only.", ephemeral=True)
        return

    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map[media_type.value]
    id_key = "simkl_id" if media_type.value in ("show", "movie") else "anilist_id"

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)

    idx = next((i for i, e in enumerate(entries) if str(e.get(id_key, "")) == title), None)
    if idx is None:
        await interaction.followup.send(f"❌ No {media_type.value} entry with ID `{title}` found.", ephemeral=True)
        return

    entry = entries[idx]

    # Migrate legacy single reason if needed
    if "reasons" not in entry:
        first = {
            "discord_id": entry.get("added_by_discord_id"),
            "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
            "user": entry.get("user", {}),
            "author": entry.get("author"),
            "text": entry.get("reason", ""),
            "added_at": None,
        }
        entries[idx]["reasons"] = [first]
        entry = entries[idx]

    reasons = entry.get("reasons", [])

    # Find the reason by matching raw_id against the entry's own data
    reason_idx = _find_reason_by_any_id(reasons, user)

    # Build display labels from the matched reason's data
    req_discord_id = None
    req_anilist_id = None
    req_mal_id = None
    req_simkl_id = None
    req_simkl_uname = None
    if reason_idx is not None:
        mu = reasons[reason_idx].get("user", {})
        req_discord_id = reasons[reason_idx].get("discord_id") or mu.get("discord", {}).get("id")
        req_anilist_id = mu.get("anilist", {}).get("id")
        req_mal_id = mu.get("mal", {}).get("id")
        req_simkl_id = mu.get("simkl", {}).get("id")
        req_simkl_uname = mu.get("simkl", {}).get("username")

    resolved_label = str(req_discord_id or req_anilist_id or req_mal_id or req_simkl_id or req_simkl_uname or user)
    resolved_mention = f"<@{req_discord_id}>" if req_discord_id else resolved_label

    if reason_idx is None:
        await interaction.followup.send(f"❌ No reason found for `{user}` on **{entry.get('title')}**.", ephemeral=True)
        return

    deleted_reason = reasons[reason_idx]
    entries[idx]["reasons"].pop(reason_idx)

    entry_deleted = False
    if not entries[idx]["reasons"]:
        entries.pop(idx)
        entry_deleted = True
    else:
        entries[idx]["reason"] = entries[idx]["reasons"][0].get("text", "")

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha,
            f"remove: reason for '{entry['title']}' ({resolved_label}) by {interaction.user} (admin)",
        )

    if ok:
        embed = discord.Embed(title="🗑️ Reason Deleted", color=0xDA3633)
        embed.add_field(name="Entry", value=entry["title"], inline=True)
        embed.add_field(name="User", value=resolved_mention, inline=True)
        embed.add_field(name="Deleted Reason", value=_short_reason(deleted_reason.get("text")), inline=False)
        if entry_deleted:
            embed.add_field(name="⚠️ Entry Also Removed", value="No reasons remained — full entry deleted.", inline=False)
        embed.set_footer(text="🛡️ Actioned as bot admin")

        log_embed = discord.Embed(title="🗑️ Reason Deleted by Admin", color=0xDA3633)
        log_embed.add_field(name="Entry", value=entry["title"], inline=True)
        log_embed.add_field(name="Deleted by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_embed.add_field(name="Target User", value=f"{resolved_mention} (`{resolved_label}`)", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=req_anilist_id, MAL=req_mal_id, Simkl=req_simkl_id, DC=req_discord_id), inline=False)
        log_embed.add_field(name="Deleted Reason", value=_short_reason(deleted_reason.get("text")), inline=False)
        if entry_deleted:
            log_embed.add_field(name="⚠️ Entry Also Removed", value="No reasons remained — full entry deleted.", inline=False)
        if entry.get("poster"):
            log_embed.set_thumbnail(url=entry["poster"])
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="❌ Failed to delete from GitHub", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Admin management slash commands
# /admin_add  /admin_remove  /admin_list
# Requires Discord server administrator permission
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="admin_add", description="Add a bot admin (Discord admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(user="User to make a bot admin", role="Admin role level")
@app_commands.choices(role=[
    app_commands.Choice(name="admin",      value="admin"),
    app_commands.Choice(name="superadmin", value="superadmin"),
])
async def admin_add(
    interaction: discord.Interaction,
    user: discord.User,
    role: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id != OWNER_ID:
        await interaction.followup.send("❌ Only the bot owner can add admins.", ephemeral=True)
        return

    role_value = role.value if role else "admin"
    target_id = str(user.id)

    async with aiohttp.ClientSession() as session:
        admins, sha = await read_admins(session)

        if target_id in admins:
            await interaction.followup.send(
                f"⚠️ {user.mention} is already a bot admin (`{admins[target_id].get('role', 'admin')}`).",
                ephemeral=True,
            )
            return

        # Pull existing profile from users.json to include AniList/MAL/Simkl info
        users, _ = await read_users(session)
        profile = users.get(target_id, {})

        admins[target_id] = {
            "discord_id": target_id,
            "discord_username": user.name,
            "discord_display_name": user.display_name,
            "discord_avatar": str(user.display_avatar.url) if user.display_avatar else None,
            # AniList
            "anilist_user_id": profile.get("anilist_user_id"),
            "anilist_username": profile.get("anilist_username"),
            "anilist_avatar": profile.get("anilist_avatar"),
            # MAL
            "mal_user_id": profile.get("mal_user_id"),
            "mal_username": profile.get("mal_username"),
            "mal_avatar": profile.get("mal_avatar"),
            # Simkl
            "simkl_user_id": profile.get("simkl_user_id"),
            "simkl_username": profile.get("simkl_username"),
            "simkl_avatar": profile.get("simkl_avatar"),
            "role": role_value,
            "added_by": str(interaction.user.id),
            "added_by_username": interaction.user.name,
            "added_at": time.time(),
        }

        ok = await write_admins(session, admins, sha, f"admin: add {user.name} as {role_value} by {interaction.user.name}")

        if ok:
            await _sync_admin_flags_all_community(session, admins)

    if ok:
        embed = discord.Embed(title="✅ Bot Admin Added", color=0x2EA043)
        embed.add_field(name="User", value=f"{user.mention} (`{user.name}`)", inline=True)
        embed.add_field(name="Role", value=f"`{role_value}`", inline=True)
        embed.add_field(name="Added by", value=interaction.user.mention, inline=True)
        if user.display_avatar:
            embed.set_thumbnail(url=user.display_avatar.url)
        log_embed = discord.Embed(title="🛡️ Bot Admin Added", color=0x2EA043)
        log_embed.add_field(name="New Admin", value=f"{user.mention} (`{user.name}`)", inline=True)
        log_embed.add_field(name="Role", value=f"`{role_value}`", inline=True)
        log_embed.add_field(name="Added by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        if user.display_avatar:
            log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id}")
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="❌ Failed to save to GitHub", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="admin_remove", description="Remove a bot admin (Discord admin only)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(user="User to remove from bot admins")
async def admin_remove(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)

    if interaction.user.id != OWNER_ID:
        await interaction.followup.send("❌ Only the bot owner can remove admins.", ephemeral=True)
        return

    target_id = str(user.id)

    async with aiohttp.ClientSession() as session:
        admins, sha = await read_admins(session)

        if target_id not in admins:
            await interaction.followup.send(f"❌ {user.mention} is not a bot admin.", ephemeral=True)
            return

        removed_record = admins.pop(target_id)
        ok = await write_admins(session, admins, sha, f"admin: remove {user.name} by {interaction.user.name}")

        if ok:
            await _sync_admin_flags_all_community(session, admins)

    if ok:
        embed = discord.Embed(title="✅ Bot Admin Removed", color=0xDA3633)
        embed.add_field(name="User", value=f"{user.mention} (`{user.name}`)", inline=True)
        embed.add_field(name="Was Role", value=f"`{removed_record.get('role', 'admin')}`", inline=True)
        log_embed = discord.Embed(title="🛡️ Bot Admin Removed", color=0xDA3633)
        log_embed.add_field(name="Removed Admin", value=f"{user.mention} (`{user.name}`)", inline=True)
        log_embed.add_field(name="Was Role", value=f"`{removed_record.get('role', 'admin')}`", inline=True)
        log_embed.add_field(name="Removed by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        if user.display_avatar:
            log_embed.set_thumbnail(url=user.display_avatar.url)
        log_embed.set_footer(text=f"User ID: {user.id}")
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="❌ Failed to save to GitHub", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="admin_list", description="List all bot admins")
async def admin_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        admins, _ = await read_admins(session)

    if not admins:
        await interaction.followup.send(
            embed=discord.Embed(title="🛡️ Bot Admins", description="No bot admins configured yet.", color=0x0078D4),
            ephemeral=True,
        )
        return

    embed = discord.Embed(title="🛡️ Bot Admins", color=0x0078D4)
    from datetime import datetime
    for discord_id, rec in admins.items():
        name = rec.get("discord_display_name") or rec.get("discord_username") or f"User {discord_id}"
        role = rec.get("role", "admin")
        added_by = rec.get("added_by_username") or rec.get("added_by", "unknown")
        added_at = rec.get("added_at")
        ts = f"<t:{int(added_at)}:R>" if added_at else "unknown"
        embed.add_field(
            name=f"{'👑' if role == 'superadmin' else '🛡️'} {name}",
            value=f"Role: `{role}` | ID: `{discord_id}`\nAdded by: `{added_by}` | {ts}",
            inline=False,
        )

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# API — edit reason
# PATCH /api/edit_reason/{type}/{id}
# Body: { "reason": "...", "discord_id": 123, "anilist_user_id": 456,
#         "mal_user_id": 789, "simkl_user_id": 101, "simkl_username": "..." }
# At least one user identifier required, or bearer token with admin flag.
# ══════════════════════════════════════════════════════════════════════════════

async def _api_edit_reason(request, media_type: str):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        item_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid id in URL"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    def _s(key):
        return (body.get(key) or "").strip() or None

    new_reason       = (body.get("reason") or "").strip()
    req_discord_id   = body.get("discord_id")
    req_anilist_id   = body.get("anilist_user_id")
    req_mal_id       = body.get("mal_user_id")
    req_simkl_id     = body.get("simkl_user_id")
    req_simkl_uname  = _s("simkl_username")
    discord_username = _s("discord_username")
    discord_avatar   = _s("discord_avatar")
    anilist_username = _s("anilist_username")
    anilist_avatar   = _s("anilist_avatar")
    mal_username     = _s("mal_username")
    mal_avatar       = _s("mal_avatar")
    simkl_avatar     = _s("simkl_avatar")
    api_admin        = bool(body.get("admin", False))

    if not new_reason:
        return web.json_response({"error": "Missing required field: reason"}, status=400)
    if len(new_reason) < 30:
        return web.json_response({"error": "Reason must be at least 30 characters"}, status=400)
    if len(new_reason) > 700:
        return web.json_response({"error": "Reason must be at most 700 characters"}, status=400)
    if not api_admin and not any([req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname]):
        return web.json_response(
            {"error": "Provide at least one user identifier: discord_id, anilist_user_id, mal_user_id, simkl_user_id, or simkl_username"},
            status=400,
        )

    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(media_type)
    id_key = "simkl_id" if media_type in ("show", "movie") else "anilist_id"

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
        admins, _    = await read_admins(session)
        users_data, _ = await read_users(session)

    idx = next((i for i, e in enumerate(entries) if e.get(id_key) == item_id), None)
    if idx is None:
        return web.json_response({"error": f"No {media_type} with {id_key}={item_id} found."}, status=404)

    entry = entries[idx]

    # Migrate legacy single reason into reasons[] if needed
    if "reasons" not in entry:
        first = {
            "discord_id": entry.get("added_by_discord_id"),
            "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
            "user": entry.get("user", {}),
            "author": entry.get("author"),
            "text": entry.get("reason", ""),
            "added_at": None,
        }
        entries[idx]["reasons"] = [first]
        entry = entries[idx]

    reasons = entry.get("reasons", [])

    # ── Resolve user snapshot from users.json if possible ───────────────────────
    identity_index = _build_identity_index(users_data)
    matched_profile = None
    for _did, p in users_data.items():
        if req_anilist_id and p.get("anilist_user_id") == req_anilist_id:
            matched_profile = p; break
        if req_mal_id and p.get("mal_user_id") == req_mal_id:
            matched_profile = p; break
        if req_simkl_id and p.get("simkl_user_id") == req_simkl_id:
            matched_profile = p; break
        if req_simkl_uname and (p.get("simkl_username") or "").lower() == req_simkl_uname.lower():
            matched_profile = p; break
        if req_discord_id and str(p.get("discord_id") or "") == str(req_discord_id):
            matched_profile = p; break

    if matched_profile:
        user_snapshot = _build_user_snapshot(matched_profile)
        _mark_admin_flag(user_snapshot, admins)
        resolved_author = (
            matched_profile.get("author_name")
            or matched_profile.get("anilist_username")
            or matched_profile.get("mal_username")
            or matched_profile.get("simkl_username")
            or matched_profile.get("discord_username")
            or "Unknown"
        )
        # Enrich req ids from matched profile so _find_reason_idx has the best chance
        req_discord_id  = req_discord_id  or matched_profile.get("discord_id")
        req_anilist_id  = req_anilist_id  or matched_profile.get("anilist_user_id")
        req_mal_id      = req_mal_id      or matched_profile.get("mal_user_id")
        req_simkl_id    = req_simkl_id    or matched_profile.get("simkl_user_id")
        req_simkl_uname = req_simkl_uname or matched_profile.get("simkl_username")
    else:
        user_snapshot = {
            "discord":  {"id": req_discord_id,  "username": discord_username,  "avatar": discord_avatar},
            "anilist":  {"id": req_anilist_id,   "username": anilist_username,  "avatar": anilist_avatar},
            "mal":      {"id": req_mal_id,        "username": mal_username,      "avatar": mal_avatar},
            "simkl":    {"id": req_simkl_id,      "username": req_simkl_uname,   "avatar": simkl_avatar},
        }
        resolved_author = anilist_username or mal_username or req_simkl_uname or discord_username or "Unknown"

    # ── Determine admin status by matching any service ID against admins.json ──
    is_admin = False
    if api_admin:
        for rec in admins.values():
            if req_anilist_id and str(rec.get("anilist_user_id", "")) == str(req_anilist_id):
                is_admin = True; break
            if req_mal_id and str(rec.get("mal_user_id", "")) == str(req_mal_id):
                is_admin = True; break
            if req_simkl_id and str(rec.get("simkl_user_id", "")) == str(req_simkl_id):
                is_admin = True; break
            if req_discord_id and str(rec.get("discord_id", "")) == str(req_discord_id):
                is_admin = True; break

    # ── Find which reason slot belongs to this caller ────────────────────────────
    if is_admin:
        target_discord_id = body.get("target_discord_id")
        if target_discord_id:
            reason_idx = _find_reason_idx(reasons, target_discord_id, None, None, None, None, identity_index)
        else:
            reason_idx = _find_reason_idx(reasons, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname, identity_index)
        if reason_idx is None and reasons:
            reason_idx = 0  # admin fallback: first slot
    else:
        reason_idx = _find_reason_idx(reasons, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname, identity_index)

    if reason_idx is None:
        return web.json_response({"error": "You don't have a reason on this entry."}, status=404)

    old_reason = reasons[reason_idx].get("text", "")

    async with aiohttp.ClientSession() as _tr_session:
        stored_new_reason = await _translate_reason(_tr_session, new_reason)

    entries[idx]["reasons"][reason_idx]["text"] = stored_new_reason
    entries[idx]["reasons"][reason_idx]["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Sync top-level reason field with first slot
    if reason_idx == 0:
        entries[idx]["reason"] = stored_new_reason

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha,
            f"edit: reason for '{entry['title']}' by {resolved_author} via API ({'admin' if is_admin else 'owner'})",
        )

    if ok:
        log_embed = discord.Embed(title=f"✏️ Reason Edited via API — {media_type.title()}", color=0xF1C40F)
        log_embed.add_field(name="Title", value=entry["title"], inline=True)
        log_embed.add_field(name="Editor", value=f"<@{req_discord_id}> (`{req_discord_id}`)" if req_discord_id else resolved_author, inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), Simkl=entry.get("simkl_id"), DC=req_discord_id), inline=False)
        log_embed.add_field(name="Old Reason", value=old_reason[:1024] or "*(empty)*", inline=False)
        _log_reason_fields(log_embed, stored_new_reason, label="New Reason")
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        return web.json_response({
            "success": True,
            "title": entry["title"],
            "old_reason": old_reason,
            "new_reason": stored_new_reason,
        })
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_edit_reason_anime(request):  return await _api_edit_reason(request, "anime")
async def api_edit_reason_manga(request):  return await _api_edit_reason(request, "manga")
async def api_edit_reason_show(request):   return await _api_edit_reason(request, "show")
async def api_edit_reason_movie(request):  return await _api_edit_reason(request, "movie")


# ══════════════════════════════════════════════════════════════════════════════
# API — delete reason from reasons[]
# DELETE /api/delete_reason/{type}/{id}
# Body: same identity fields as edit_reason
# Non-admins: posts a log request for admins to action (same pattern as delete_entry)
# Admins:     removes immediately
# ══════════════════════════════════════════════════════════════════════════════

async def _api_delete_reason(request, media_type: str):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        item_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid id in URL"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    def _s(key):
        return (body.get(key) or "").strip() or None

    req_discord_id   = body.get("discord_id")
    req_anilist_id   = body.get("anilist_user_id")
    req_mal_id       = body.get("mal_user_id")
    req_simkl_id     = body.get("simkl_user_id")
    req_simkl_uname  = _s("simkl_username")
    api_admin        = bool(body.get("admin", False))

    if not api_admin and not any([req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname]):
        return web.json_response(
            {"error": "Provide at least one user identifier: discord_id, anilist_user_id, mal_user_id, simkl_user_id, or simkl_username"},
            status=400,
        )

    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(media_type)
    id_key = "simkl_id" if media_type in ("show", "movie") else "anilist_id"

    async with aiohttp.ClientSession() as session:
        entries, sha  = await github_read_json(session, filepath)
        admins, _     = await read_admins(session)
        users_data, _ = await read_users(session)

    idx = next((i for i, e in enumerate(entries) if e.get(id_key) == item_id), None)
    if idx is None:
        return web.json_response({"error": f"No {media_type} with {id_key}={item_id} found."}, status=404)

    entry = entries[idx]

    # Migrate legacy single reason into reasons[] if needed
    if "reasons" not in entry:
        first = {
            "discord_id": entry.get("added_by_discord_id"),
            "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
            "user": entry.get("user", {}),
            "author": entry.get("author"),
            "text": entry.get("reason", ""),
            "added_at": None,
        }
        entries[idx]["reasons"] = [first]
        entry = entries[idx]

    reasons = entry.get("reasons", [])

    # ── Resolve full identity from users.json to maximise match coverage ─────────
    identity_index = _build_identity_index(users_data)
    matched_profile = None
    for _did, p in users_data.items():
        if req_anilist_id and p.get("anilist_user_id") == req_anilist_id:
            matched_profile = p; break
        if req_mal_id and p.get("mal_user_id") == req_mal_id:
            matched_profile = p; break
        if req_simkl_id and p.get("simkl_user_id") == req_simkl_id:
            matched_profile = p; break
        if req_simkl_uname and (p.get("simkl_username") or "").lower() == req_simkl_uname.lower():
            matched_profile = p; break
        if req_discord_id and str(p.get("discord_id") or "") == str(req_discord_id):
            matched_profile = p; break

    if matched_profile:
        req_discord_id  = req_discord_id  or matched_profile.get("discord_id")
        req_anilist_id  = req_anilist_id  or matched_profile.get("anilist_user_id")
        req_mal_id      = req_mal_id      or matched_profile.get("mal_user_id")
        req_simkl_id    = req_simkl_id    or matched_profile.get("simkl_user_id")
        req_simkl_uname = req_simkl_uname or matched_profile.get("simkl_username")
        resolved_author = (
            matched_profile.get("anilist_username")
            or matched_profile.get("mal_username")
            or matched_profile.get("simkl_username")
            or matched_profile.get("discord_username")
            or "Unknown"
        )
    else:
        resolved_author = req_simkl_uname or str(req_discord_id or "Unknown")

    # ── Determine admin status by matching any service ID against admins.json ──
    is_admin = False
    if api_admin:
        for rec in admins.values():
            if req_anilist_id and str(rec.get("anilist_user_id", "")) == str(req_anilist_id):
                is_admin = True; break
            if req_mal_id and str(rec.get("mal_user_id", "")) == str(req_mal_id):
                is_admin = True; break
            if req_simkl_id and str(rec.get("simkl_user_id", "")) == str(req_simkl_id):
                is_admin = True; break
            if req_discord_id and str(rec.get("discord_id", "")) == str(req_discord_id):
                is_admin = True; break

    # ── Find the reason slot to delete ──────────────────────────────────────────
    if is_admin:
        target_discord_id = body.get("target_discord_id")
        if target_discord_id:
            reason_idx = _find_reason_idx(reasons, target_discord_id, None, None, None, None, identity_index)
        else:
            reason_idx = _find_reason_idx(reasons, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname, identity_index)
        if reason_idx is None and reasons:
            reason_idx = 0  # admin fallback: first slot
    else:
        reason_idx = _find_reason_idx(reasons, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname, identity_index)

    if reason_idx is None:
        return web.json_response({"error": "You don't have a reason on this entry."}, status=404)

    target_reason = reasons[reason_idx]
    p_prefix = _prefix_cache[0]

    # ── Non-admin: post a deletion request to the log channel ───────────────────
    if not is_admin:
        requester_label = f"<@{req_discord_id}> (`{req_discord_id}`)" if req_discord_id else resolved_author
        log_embed = discord.Embed(
            title="🗑️ Reason Deletion Requested via API (Owner)",
            description=(
                "An owner requested their reason be removed from an entry.\n"
                "**Admins:** please review and use the command below to confirm."
            ),
            color=0xF0A500,
        )
        log_embed.add_field(name="Title",        value=entry.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Type",         value=media_type.title(),       inline=True)
        log_embed.add_field(name="Requested by", value=requester_label,          inline=True)
        log_embed.add_field(name="IDs",          value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), Simkl=entry.get("simkl_id"), DC=req_discord_id), inline=False)
        log_embed.add_field(name="User IDs",      value=_ids_line(AL=req_anilist_id, MAL=req_mal_id, Simkl=req_simkl_id, DC=req_discord_id), inline=False)
        log_embed.add_field(name="Reason to Delete", value=_short_reason(target_reason.get("text")), inline=False)
        log_embed.add_field(name="Reasons Remaining After", value=str(len(reasons) - 1), inline=True)
        log_embed.add_field(
            name="Action",
            value=f"Use `/delete_reason` with media_type={media_type}, then search the entry title, then select the user.",
            inline=False,
        )
        if entry.get("poster"):
            log_embed.set_thumbnail(url=entry["poster"])
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        return web.json_response({
            "success": False,
            "pending": True,
            "message": "Deletion request submitted. An admin will review and action it.",
            "title": entry.get("title"),
            id_key: item_id,
        })

    # ── Admin: delete the reason immediately ────────────────────────────────────
    entries[idx]["reasons"].pop(reason_idx)

    entry_deleted = False
    if not entries[idx]["reasons"]:
        entries.pop(idx)
        entry_deleted = True
    else:
        entries[idx]["reason"] = entries[idx]["reasons"][0].get("text", "")

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha,
            f"remove: reason for '{entry['title']}' ({resolved_author}) by admin via API",
        )

    if ok:
        log_embed = discord.Embed(
            title=f"🗑️ Reason Deleted via API (Admin) — {media_type.title()}",
            color=0xDA3633,
        )
        log_embed.add_field(name="Title",       value=entry["title"], inline=True)
        log_embed.add_field(name="Deleted by",  value=f"<@{req_discord_id}> (`{req_discord_id}`)" if req_discord_id else "API Key", inline=True)
        log_embed.add_field(name="Target User", value=resolved_author, inline=True)
        log_embed.add_field(name="Media IDs",   value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), Simkl=entry.get("simkl_id")), inline=False)
        log_embed.add_field(name="User IDs",    value=_ids_line(AL=req_anilist_id, MAL=req_mal_id, Simkl=req_simkl_id, DC=req_discord_id), inline=False)
        log_embed.add_field(name="Deleted Reason", value=_short_reason(target_reason.get("text")), inline=False)
        if entry_deleted:
            log_embed.add_field(name="\u26a0\ufe0f Entry Also Removed", value="No reasons remained — full entry deleted.", inline=False)
        if entry.get("poster"):
            log_embed.set_thumbnail(url=entry["poster"])
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        return web.json_response({
            "success": True,
            "entry_deleted": entry_deleted,
            "title": entry["title"],
            id_key: item_id,
        })
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_delete_reason_anime(request):  return await _api_delete_reason(request, "anime")
async def api_delete_reason_manga(request):  return await _api_delete_reason(request, "manga")
async def api_delete_reason_show(request):   return await _api_delete_reason(request, "show")
async def api_delete_reason_movie(request):  return await _api_delete_reason(request, "movie")


# ══════════════════════════════════════════════════════════════════════════════
# API — delete entry
# DELETE /api/delete/{type}/{id}
# Body: same identity fields as edit_reason
# ══════════════════════════════════════════════════════════════════════════════

async def _api_delete_entry(request, media_type: str):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        item_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid id in URL"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    req_discord_id   = body.get("discord_id")
    req_anilist_id   = body.get("anilist_user_id")
    req_mal_id       = body.get("mal_user_id")
    req_simkl_id     = body.get("simkl_user_id")
    req_simkl_uname  = (body.get("simkl_username") or "").strip() or None
    api_admin        = bool(body.get("admin", False))

    if not api_admin and not any([req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname]):
        return web.json_response(
            {"error": "Provide at least one user identifier: discord_id, anilist_user_id, mal_user_id, simkl_user_id, or simkl_username"},
            status=400,
        )

    filepath_map = {"anime": FILE_ANIME, "manga": FILE_MANGA, "show": FILE_SHOWS, "movie": FILE_MOVIES}
    filepath = filepath_map.get(media_type)
    id_key = "simkl_id" if media_type in ("show", "movie") else "anilist_id"

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, filepath)
        admins, _ = await read_admins(session)
        users_data, _ = await read_users(session)

    idx = next((i for i, e in enumerate(entries) if e.get(id_key) == item_id), None)
    if idx is None:
        return web.json_response({"error": f"No {media_type} with {id_key}={item_id} found."}, status=404)

    entry = entries[idx]

    # ── Resolve full identity from users.json to maximise match coverage ─────────
    matched_profile = None
    for _did, p in users_data.items():
        if req_anilist_id and p.get("anilist_user_id") == req_anilist_id:
            matched_profile = p; break
        if req_mal_id and p.get("mal_user_id") == req_mal_id:
            matched_profile = p; break
        if req_simkl_id and p.get("simkl_user_id") == req_simkl_id:
            matched_profile = p; break
        if req_simkl_uname and (p.get("simkl_username") or "").lower() == req_simkl_uname.lower():
            matched_profile = p; break
        if req_discord_id and str(p.get("discord_id") or "") == str(req_discord_id):
            matched_profile = p; break

    if matched_profile:
        req_discord_id  = req_discord_id  or matched_profile.get("discord_id")
        req_anilist_id  = req_anilist_id  or matched_profile.get("anilist_user_id")
        req_mal_id      = req_mal_id      or matched_profile.get("mal_user_id")
        req_simkl_id    = req_simkl_id    or matched_profile.get("simkl_user_id")
        req_simkl_uname = req_simkl_uname or matched_profile.get("simkl_username")

    # ── Determine admin status by matching any service ID against admins.json ──
    is_admin = False
    if api_admin:
        for rec in admins.values():
            if req_anilist_id and str(rec.get("anilist_user_id", "")) == str(req_anilist_id):
                is_admin = True; break
            if req_mal_id and str(rec.get("mal_user_id", "")) == str(req_mal_id):
                is_admin = True; break
            if req_simkl_id and str(rec.get("simkl_user_id", "")) == str(req_simkl_id):
                is_admin = True; break
            if req_discord_id and str(rec.get("discord_id", "")) == str(req_discord_id):
                is_admin = True; break

    if not is_admin and not _entry_owned_by_api(
        entry, req_discord_id, req_anilist_id, req_mal_id, req_simkl_id, req_simkl_uname
    ):
        return web.json_response({"error": "You do not own this entry."}, status=403)

    # Non-admins via API: don't delete — log a request for admins to action
    if not is_admin:
        p = _prefix_cache[0]
        requester = f"discord:{req_discord_id}" if req_discord_id else (
            f"anilist:{req_anilist_id}" if req_anilist_id else (
            f"mal:{req_mal_id}" if req_mal_id else (
            f"simkl:{req_simkl_uname or req_simkl_id}")))
        log_embed = discord.Embed(
            title="Deletion Requested via API (Owner)",
            description=(
                f"An owner requested their entry be deleted via the API.\n"
                f"**Admins:** please review and use the command below to confirm."
            ),
            color=0xF0A500,
        )
        log_embed.add_field(name="Title", value=entry.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Type", value=media_type.title(), inline=True)
        log_embed.add_field(name="Score", value=str(entry.get("score", "N/A")), inline=True)
        log_embed.add_field(name="Requested by", value=f"<@{req_discord_id}> (`{req_discord_id}`)" if req_discord_id else requester, inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=entry.get("anilist_id"), MAL=entry.get("mal_id"), Simkl=entry.get("simkl_id"), DC=req_discord_id), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(entry.get("reason")), inline=False)
        log_embed.add_field(name="Admin Command", value=f"`{p}delete_entry {media_type} {item_id}`", inline=False)
        if entry.get("poster"):
            log_embed.set_thumbnail(url=entry["poster"])
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        return web.json_response({
            "success": False,
            "pending": True,
            "message": "Deletion request submitted. An admin will review and action it.",
            "title": entry.get("title"),
            id_key: item_id,
        })

    # Admin path: delete immediately
    removed = entries.pop(idx)

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, filepath, entries, sha,
            f"remove: '{removed['title']}' deleted via API (admin)",
        )

    if ok:
        log_embed = discord.Embed(title="🗑️ Entry Deleted via API (Admin)", color=0xDA3633)
        log_embed.add_field(name="Title", value=removed["title"], inline=True)
        log_embed.add_field(name="Type", value=media_type.title(), inline=True)
        log_embed.add_field(name="Deleted by", value=f"<@{req_discord_id}> (`{req_discord_id}`)" if req_discord_id else "API Key", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=removed.get("anilist_id"), MAL=removed.get("mal_id"), Simkl=removed.get("simkl_id"), DC=req_discord_id), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(removed.get("reason")), inline=False)
        if removed.get("poster"):
            log_embed.set_thumbnail(url=removed["poster"])
        log_embed.set_footer(text="Source: API")
        await _send_log(log_embed)
        return web.json_response({"success": True, "deleted": {"title": removed["title"], id_key: item_id}})
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_delete_anime(request):  return await _api_delete_entry(request, "anime")
async def api_delete_manga(request):  return await _api_delete_entry(request, "manga")
async def api_delete_show(request):   return await _api_delete_entry(request, "show")
async def api_delete_movie(request):  return await _api_delete_entry(request, "movie")


# ══════════════════════════════════════════════════════════════════════════════
# API — admin management
# GET    /api/admins
# POST   /api/admins/add     body: { "discord_id": ..., "discord_username": ..., "role": "admin"|"superadmin", "added_by": ... }
# DELETE /api/admins/remove  body: { "discord_id": ... }
# ══════════════════════════════════════════════════════════════════════════════

async def api_is_admin(request):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    anilist_user_id = body.get("anilist_user_id")
    mal_user_id = body.get("mal_user_id")
    simkl_user_id = body.get("simkl_user_id")
    anilist_username = body.get("anilist_username")
    mal_username = body.get("mal_username")
    simkl_username = body.get("simkl_username")

    async with aiohttp.ClientSession() as session:
        admins, _ = await read_admins(session)

    for discord_id, rec in admins.items():
        if anilist_user_id and rec.get("anilist_user_id") == anilist_user_id:
            return web.json_response({"is_admin": True, "discord_id": discord_id, "role": rec.get("role")})
        if mal_user_id and rec.get("mal_user_id") == mal_user_id:
            return web.json_response({"is_admin": True, "discord_id": discord_id, "role": rec.get("role")})
        if simkl_user_id and rec.get("simkl_user_id") == simkl_user_id:
            return web.json_response({"is_admin": True, "discord_id": discord_id, "role": rec.get("role")})
        if anilist_username and rec.get("anilist_username") == anilist_username:
            return web.json_response({"is_admin": True, "discord_id": discord_id, "role": rec.get("role")})
        if mal_username and rec.get("mal_username") == mal_username:
            return web.json_response({"is_admin": True, "discord_id": discord_id, "role": rec.get("role")})
        if simkl_username and rec.get("simkl_username") == simkl_username:
            return web.json_response({"is_admin": True, "discord_id": discord_id, "role": rec.get("role")})

    return web.json_response({"is_admin": False})


async def api_get_admins(request):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    async with aiohttp.ClientSession() as session:
        admins, _ = await read_admins(session)
    # Strip sensitive internal fields before returning
    safe = {
        did: {
            "discord_id": rec.get("discord_id"),
            "discord_username": rec.get("discord_username"),
            "discord_display_name": rec.get("discord_display_name"),
            "discord_avatar": rec.get("discord_avatar"),
            "role": rec.get("role", "admin"),
            "added_at": rec.get("added_at"),
        }
        for did, rec in admins.items()
    }
    return web.json_response({"admins": safe, "count": len(safe)})


async def api_admin_add(request):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    discord_id = str(body.get("discord_id", "")).strip()
    discord_username = (body.get("discord_username") or "").strip()
    role = (body.get("role") or "admin").strip()
    added_by = str(body.get("added_by", "API")).strip()

    if not discord_id:
        return web.json_response({"error": "discord_id is required"}, status=400)
    if role not in ("admin", "superadmin"):
        return web.json_response({"error": "role must be 'admin' or 'superadmin'"}, status=400)

    async with aiohttp.ClientSession() as session:
        admins, sha = await read_admins(session)
        if discord_id in admins:
            return web.json_response({"error": "User is already an admin", "role": admins[discord_id].get("role")}, status=409)

        # Try to fetch fresh Discord info from bot cache
        try:
            discord_user = await bot.fetch_user(int(discord_id))
            display_name = discord_user.display_name
            username = discord_user.name
            avatar = str(discord_user.display_avatar.url) if discord_user.display_avatar else None
        except Exception:
            display_name = discord_username
            username = discord_username
            avatar = None

        # Pull AniList/MAL/Simkl info from users.json if the user has a profile
        users, _ = await read_users(session)
        profile = users.get(discord_id, {})

        admins[discord_id] = {
            "discord_id": discord_id,
            "discord_username": username or discord_username,
            "discord_display_name": display_name or discord_username,
            "discord_avatar": avatar,
            # AniList
            "anilist_user_id": profile.get("anilist_user_id"),
            "anilist_username": profile.get("anilist_username"),
            "anilist_avatar": profile.get("anilist_avatar"),
            # MAL
            "mal_user_id": profile.get("mal_user_id"),
            "mal_username": profile.get("mal_username"),
            "mal_avatar": profile.get("mal_avatar"),
            # Simkl
            "simkl_user_id": profile.get("simkl_user_id"),
            "simkl_username": profile.get("simkl_username"),
            "simkl_avatar": profile.get("simkl_avatar"),
            "role": role,
            "added_by": added_by,
            "added_at": time.time(),
        }
        ok = await write_admins(session, admins, sha, f"admin: add {discord_id} as {role} via API")

        if ok:
            await _sync_admin_flags_all_community(session, admins)

    if ok:
        log_embed = discord.Embed(title="🛡️ Admin Added (API)", color=0x2EA043)
        log_embed.add_field(name="User", value=f"`{username or discord_username}` (`{discord_id}`)", inline=True)
        log_embed.add_field(name="Role", value=f"`{role}`", inline=True)
        log_embed.add_field(name="Added by", value=added_by, inline=True)
        await _send_log(log_embed)
        return web.json_response({"success": True, "discord_id": discord_id, "role": role}, status=201)
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def api_admin_remove(request):
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    discord_id = str(body.get("discord_id", "")).strip()
    if not discord_id:
        return web.json_response({"error": "discord_id is required"}, status=400)

    async with aiohttp.ClientSession() as session:
        admins, sha = await read_admins(session)
        if discord_id not in admins:
            return web.json_response({"error": "User is not an admin"}, status=404)
        admins.pop(discord_id)
        ok = await write_admins(session, admins, sha, f"admin: remove {discord_id} via API")

        if ok:
            await _sync_admin_flags_all_community(session, admins)

    if ok:
        log_embed = discord.Embed(title="🗑️ Admin Removed (API)", color=0xDA3633)
        log_embed.add_field(name="Discord ID", value=f"`{discord_id}`", inline=True)
        await _send_log(log_embed)
        return web.json_response({"success": True, "discord_id": discord_id})
    return web.json_response({"error": "Failed to write to GitHub"}, status=500)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    # ── OAuth callbacks ──────────────────────────────────────────────────────────
    app.router.add_get("/oauth/anilist/callback", anilist_callback)
    app.router.add_get("/oauth/mal/callback", mal_callback)
    app.router.add_get("/oauth/simkl/callback", simkl_callback)
    app.router.add_get("/api/oauth/status", oauth_status)
    # ── media add ──────────────────────────────────────────────────────────────
    app.router.add_post("/api/add_anime", api_add_anime)
    app.router.add_post("/api/add_manga", api_add_manga)
    app.router.add_post("/api/add_show", api_add_show)
    app.router.add_post("/api/add_movie", api_add_movie)
    # ── check if item already in list ──────────────────────────────────────────
    app.router.add_get("/api/check/anime/{id}", api_check_anime)
    app.router.add_get("/api/check/manga/{id}", api_check_manga)
    app.router.add_get("/api/check/show/{id}", api_check_show)
    app.router.add_get("/api/check/movie/{id}", api_check_movie)
    # ── voting ─────────────────────────────────────────────────────────────────
    app.router.add_post("/api/vote/anime/{anilist_id}", api_vote_anime)
    app.router.add_post("/api/vote/manga/{anilist_id}", api_vote_manga)
    app.router.add_post("/api/vote/show/{anilist_id}", api_vote_show)
    app.router.add_post("/api/vote/movie/{anilist_id}", api_vote_movie)
    app.router.add_get("/api/votes/anime/{anilist_id}", api_get_votes_anime)
    app.router.add_get("/api/votes/manga/{anilist_id}", api_get_votes_manga)
    app.router.add_get("/api/votes/show/{anilist_id}", api_get_votes_show)
    app.router.add_get("/api/votes/movie/{anilist_id}", api_get_votes_movie)
    app.router.add_get("/api/votes/leaderboard", api_leaderboard)
    # ── edit reason ────────────────────────────────────────────────────────────
    app.router.add_patch("/api/edit_reason/anime/{id}", api_edit_reason_anime)
    app.router.add_patch("/api/edit_reason/manga/{id}", api_edit_reason_manga)
    app.router.add_patch("/api/edit_reason/show/{id}",  api_edit_reason_show)
    app.router.add_patch("/api/edit_reason/movie/{id}", api_edit_reason_movie)
    # ── delete reason ──────────────────────────────────────────────────────────
    app.router.add_delete("/api/delete_reason/anime/{id}", api_delete_reason_anime)
    app.router.add_delete("/api/delete_reason/manga/{id}", api_delete_reason_manga)
    app.router.add_delete("/api/delete_reason/show/{id}",  api_delete_reason_show)
    app.router.add_delete("/api/delete_reason/movie/{id}", api_delete_reason_movie)
    # ── delete entry ───────────────────────────────────────────────────────────
    app.router.add_delete("/api/delete/anime/{id}", api_delete_anime)
    app.router.add_delete("/api/delete/manga/{id}", api_delete_manga)
    app.router.add_delete("/api/delete/show/{id}",  api_delete_show)
    app.router.add_delete("/api/delete/movie/{id}", api_delete_movie)
    # ── admin management ───────────────────────────────────────────────────────
    app.router.add_get("/api/admins",          api_get_admins)
    app.router.add_post("/api/admins/add",     api_admin_add)
    app.router.add_delete("/api/admins/remove", api_admin_remove)
    app.router.add_post("/api/is_admin",       api_is_admin)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"✅ Health server running on port {PORT}")


# ── GitHub helpers ─────────────────────────────────────────────────────────────


def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def github_read_json(session: aiohttp.ClientSession, filepath: str, *, repo: str | None = None, branch: str | None = None) -> tuple:
    """Read a JSON file from GitHub. Returns (parsed_data, sha)."""
    _repo = repo or GITHUB_REPO
    _branch = branch or GITHUB_BRANCH
    async with session.get(
        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{_repo}/contents/{filepath}?ref={_branch}",
        headers=gh_headers(),
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        if r.status == 404:
            dict_files = (
                FILE_USERS,
                FILE_TIMEZONES,
                FILE_SERVER_CFG,
                FILE_VOTES,
            )
            list_files = (FILE_ANIME, FILE_MANGA, FILE_SHOWS, FILE_MOVIES)
            if filepath in dict_files:
                default = {}
            elif filepath == FILE_PREFIXES:
                default = DEFAULT_PREFIXES[:]
            elif filepath in list_files:
                default = []
            else:
                default = {}
            return default, None
        data = await r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data["sha"]


async def github_write_json(
    session: aiohttp.ClientSession, filepath: str, data, sha, commit_msg: str, *, repo: str | None = None, branch: str | None = None
) -> bool:
    """Write/update a JSON file on GitHub. Returns True on success."""
    _repo = repo or GITHUB_REPO
    _branch = branch or GITHUB_BRANCH
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(
            json.dumps(data, indent=2, ensure_ascii=False).encode()
        ).decode(),
        "branch": _branch,
    }
    if sha:
        payload["sha"] = sha
    async with session.put(
        f"{GITHUB_API}/repos/{GITHUB_OWNER}/{_repo}/contents/{filepath}",
        headers=gh_headers(),
        json=payload,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as r:
        return r.status in (200, 201)


# ── Userdata convenience wrappers (private repo) ─────────────────────────────────
# All user data (users.json) is stored in the private repo for token security.


async def read_users(session: aiohttp.ClientSession) -> tuple:
    """Read users.json from the private userdata repo. Returns (data, sha)."""
    return await github_read_json(session, FILE_USERS, repo=USERDATA_REPO, branch=USERDATA_BRANCH)


async def write_users(session: aiohttp.ClientSession, users: dict, sha, commit_msg: str) -> bool:
    """Write users.json to the private userdata repo. Returns True on success."""
    return await github_write_json(session, FILE_USERS, users, sha, commit_msg, repo=USERDATA_REPO, branch=USERDATA_BRANCH)


# ── AniList helper ─────────────────────────────────────────────────────────────


async def fetch_anilist(session: aiohttp.ClientSession, media_id: int, media_type: str):
    query = """
    query ($id: Int, $type: MediaType) {
      Media(id: $id, type: $type) {
        id idMal
        title { romaji english native }
        coverImage { large }
        bannerImage
        averageScore
        genres
        isAdult
        status
        format
        episodes
        duration
        chapters
        volumes
        season
        seasonYear
        description(asHtml: false)
        studios(isMain: true) { nodes { name } }
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


async def fetch_anilist_by_mal(session: aiohttp.ClientSession, mal_id: int, media_type: str) -> dict | None:
    """Look up an AniList entry by its MAL ID using the idMal field.
    Returns the full AniList Media object if found, else None.
    This is the most reliable way to resolve MAL → AniList because it queries
    AniList's own database directly instead of relying on a third-party backup repo.
    """
    query = """
    query ($malId: Int, $type: MediaType) {
      Media(idMal: $malId, type: $type) {
        id idMal
        title { romaji english native }
        coverImage { large }
        bannerImage
        averageScore
        genres
        isAdult
        status
        format
        episodes
        duration
        chapters
        volumes
        season
        seasonYear
        description(asHtml: false)
        studios(isMain: true) { nodes { name } }
      }
    }
    """
    try:
        async with session.post(
            ANILIST_API,
            json={"query": query, "variables": {"malId": mal_id, "type": media_type}},
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status != 200:
                return None
            result = await r.json()
            return result.get("data", {}).get("Media")
    except Exception as e:
        print(f"⚠️ [AniList idMal lookup] Failed for MAL ID {mal_id}: {e}")
        return None


async def fetch_mal_jikan(session: aiohttp.ClientSession, mal_id: int, media_type: str) -> dict | None:
    """Fetch anime/manga data from Jikan API (no auth needed).
    Used as a fallback when an entry is not on AniList at all.
    Returns a normalized dict with title, poster, score, nsfw, etc.
    """
    endpoint = "anime" if media_type in ("ANIME", "anime") else "manga"
    url = f"https://api.jikan.moe/v4/{endpoint}/{mal_id}/full"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                print(f"⚠️ [Jikan] MAL {endpoint}/{mal_id} returned status {r.status}")
                return None
            result = await r.json()
            data = result.get("data")
            if not data:
                return None
            # Normalize Jikan response to a consistent format
            images = data.get("images", {}) or {}
            jpg_images = images.get("jpg", {}) or {}
            return {
                "title": data.get("title", f"MAL ID {mal_id}"),
                "poster": jpg_images.get("large_image_url", "") or jpg_images.get("image_url", ""),
                "score": data.get("score") or "N/A",
                "nsfw": bool(data.get("rating") and "hx" in str(data.get("rating", "")).lower()),
                "genres": ", ".join(g.get("name", "") for g in (data.get("genres") or [])),
                "synopsis": (data.get("synopsis") or "")[:500],
                "status": data.get("status"),
                "episodes": data.get("episodes"),
                "chapters": data.get("chapters"),
                "volumes": data.get("volumes"),
                "type": data.get("type"),
                "year": data.get("year"),
                "source": "MAL",
            }
    except Exception as e:
        print(f"⚠️ [Jikan] Failed for MAL ID {mal_id}: {e}")
        return None


async def fetch_anilist_batch(session: aiohttp.ClientSession, ids: list[int], media_type: str) -> dict[int, dict]:
    """Fetch up to 50 media items in one AniList request. Returns {id: media_dict}."""
    if not ids:
        return {}
    query = """
    query ($ids: [Int], $type: MediaType) {
      Page(perPage: 50) {
        media(id_in: $ids, type: $type) {
          id coverImage { large } averageScore isAdult
        }
      }
    }
    """
    try:
        async with session.post(
            ANILIST_API,
            json={"query": query, "variables": {"ids": ids, "type": media_type}},
            headers={"Content-Type": "application/json"},
        ) as r:
            if r.status != 200:
                return {}
            data = await r.json()
        results = data.get("data", {}).get("Page", {}).get("media", [])
        return {m["id"]: m for m in results}
    except Exception:
        return {}


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
        users, _ = await read_users(session)
    return users.get(discord_id)


def _build_user_snapshot(profile: dict) -> dict:
    return {
        "discord": {
            "id": profile.get("discord_id"),
            "username": profile.get("discord_username"),
            "avatar": profile.get("discord_avatar"),
        },
        "anilist": {
            "id": profile.get("anilist_user_id"),
            "username": profile.get("anilist_username"),
            "avatar": profile.get("anilist_avatar"),
        },
        "mal": {
            "id": profile.get("mal_user_id"),
            "username": profile.get("mal_username"),
            "avatar": profile.get("mal_avatar"),
        },
        "simkl": {
            "username": profile.get("simkl_username"),
            "id": profile.get("simkl_user_id"),
            "avatar": profile.get("simkl_avatar"),
        },
        "isAdmin": False,
    }


def _is_user_admin_in(admins: dict, user_snapshot: dict) -> bool:
    snap_ids = _collect_identity_ids(user_snapshot)
    for _discord_id, rec in admins.items():
        admin_ids: set[str] = set()
        if _discord_id:
            admin_ids.add(str(_discord_id))
        for key in ("anilist_user_id", "mal_user_id", "simkl_user_id"):
            if rec.get(key):
                admin_ids.add(str(rec[key]))
        admin_uname = (rec.get("simkl_username") or "").strip().lower()
        if admin_uname:
            admin_ids.add(admin_uname)
        if snap_ids & admin_ids:
            return True
    return False


async def _sync_admin_flags_in_entries(
    session: aiohttp.ClientSession,
    admins: dict,
    filepath: str,
    identity_index: dict[str, set[str]] | None = None,
):
    entries, sha = await github_read_json(session, filepath)
    if not isinstance(entries, list) or not entries:
        return
    changed = False
    for entry in entries:
        if entry.get("user") and isinstance(entry.get("user"), dict):
            new_val = _is_user_admin_in(admins, entry["user"])
            if entry["user"].get("isAdmin") != new_val:
                entry["user"]["isAdmin"] = new_val
                changed = True
        for reason in entry.get("reasons", []):
            if reason.get("user") and isinstance(reason.get("user"), dict):
                new_val = _is_user_admin_in(admins, reason["user"])
                if reason["user"].get("isAdmin") != new_val:
                    reason["user"]["isAdmin"] = new_val
                    changed = True
    if changed:
        await github_write_json(session, filepath, entries, sha, "auto-sync: update isAdmin flags")


async def _sync_admin_flags_all_community(session: aiohttp.ClientSession, admins: dict):
    users_data, _ = await read_users(session)
    identity_index = _build_identity_index(users_data)

    async def _sync_one(fp):
        try:
            await _sync_admin_flags_in_entries(session, admins, fp, identity_index)
            print(f"✅ isAdmin sync done for {fp}")
        except Exception as e:
            print(f"⚠️ isAdmin sync failed for {fp}: {e}")

    await asyncio.gather(*[_sync_one(fp) for fp in (FILE_ANIME, FILE_MANGA, FILE_SHOWS, FILE_MOVIES)])


def _mark_admin_flag(user_snapshot: dict, admins: dict):
    user_snapshot["isAdmin"] = _is_user_admin_in(admins, user_snapshot)


# ── Cross-service identity helpers ────────────────────────────────────────────


def _build_identity_index(users_data: dict) -> dict[str, set[str]]:
    """Create a reverse lookup: any known ID string → ALL IDs for that user.

    Used to resolve a user's complete identity when only one service ID is known.
    For example, if a user has anilist_user_id=12345 and mal_user_id=67890,
    the index maps "12345" → {"12345", "67890", ...} and "67890" → {"12345", "67890", ...}.
    """
    index: dict[str, set[str]] = {}
    for discord_id, p in users_data.items():
        ids: set[str] = set()
        if discord_id:
            ids.add(str(discord_id))
        for key in ("anilist_user_id", "mal_user_id", "simkl_user_id"):
            if p.get(key):
                ids.add(str(p[key]))
        simkl_uname = (p.get("simkl_username") or "").strip().lower()
        if simkl_uname:
            ids.add(simkl_uname)
        for one_id in ids:
            index.setdefault(one_id, ids)
    return index


def _collect_identity_ids(snapshot: dict, flat_discord_id: str | None = None) -> set[str]:
    """Collect ALL non-null identity values from a user snapshot.

    Extracts discord_id, anilist.id, mal.id, simkl.id, simkl.username
    from both the flat discord_id field and the nested user snapshot.
    """
    ids: set[str] = set()
    if flat_discord_id:
        ids.add(str(flat_discord_id))
    for svc in ("discord", "anilist", "mal", "simkl"):
        sid = snapshot.get(svc, {}).get("id")
        if sid:
            ids.add(str(sid))
    sname = snapshot.get("simkl", {}).get("username")
    if sname:
        ids.add(sname.lower())
    ids.discard("")
    ids.discard("None")
    return ids


def _enrich_identity_set(ids: set[str], identity_index: dict[str, set[str]]) -> set[str]:
    """Expand a set of identity IDs using the users.json identity index.

    If any ID in `ids` is found in the index, all linked IDs for that user
    are added to the result set. This resolves cross-service identity matches.
    """
    enriched = set(ids)
    for sid in ids:
        if sid in identity_index:
            enriched |= identity_index[sid]
    return enriched


def _user_ids_overlap(
    incoming_snapshot: dict,
    incoming_flat_discord_id: str | None,
    stored_reason: dict,
    identity_index: dict[str, set[str]] | None = None,
) -> bool:
    """Check if an incoming user and a stored reason belong to the same person.

    Collects ALL identity values from both sides, optionally enriches via
    users.json identity_index, then checks for any overlap.
    Returns True if the users match (duplicate), False otherwise.
    """
    incoming_ids = _collect_identity_ids(incoming_snapshot, incoming_flat_discord_id)
    stored_ids = _collect_identity_ids(stored_reason.get("user", {}), stored_reason.get("discord_id"))

    if identity_index:
        incoming_ids = _enrich_identity_set(incoming_ids, identity_index)
        stored_ids = _enrich_identity_set(stored_ids, identity_index)

    return bool(incoming_ids & stored_ids)


# ══════════════════════════════════════════════════════════════════════════════
# Admin records (admins.json in private userdata repo)
# Structure: { "discord_id": { "discord_id": str, "discord_username": str,
#              "discord_display_name": str, "discord_avatar": str,
#              "role": "superadmin"|"admin", "added_by": str, "added_at": float } }
# ══════════════════════════════════════════════════════════════════════════════

async def read_admins(session: aiohttp.ClientSession) -> tuple[dict, str | None]:
    """Read admins.json from the private userdata repo. Returns (data, sha)."""
    data, sha = await github_read_json(
        session, FILE_ADMINS, repo=USERDATA_REPO, branch=USERDATA_BRANCH
    )
    if not isinstance(data, dict):
        data = {}
    return data, sha


async def write_admins(
    session: aiohttp.ClientSession,
    admins: dict,
    sha: str | None,
    message: str,
) -> bool:
    return await github_write_json(
        session, FILE_ADMINS, admins, sha, message,
        repo=USERDATA_REPO, branch=USERDATA_BRANCH,
    )


async def is_bot_admin(discord_id: str | int) -> bool:
    """Return True if this Discord user is in admins.json."""
    async with aiohttp.ClientSession() as session:
        admins, _ = await read_admins(session)
    return str(discord_id) in admins


def _admin_snapshot(discord_user: discord.User | discord.Member) -> dict:
    """Build an admin record from a Discord user object."""
    return {
        "discord_id": str(discord_user.id),
        "discord_username": discord_user.name,
        "discord_display_name": discord_user.display_name,
        "discord_avatar": str(discord_user.display_avatar.url) if discord_user.display_avatar else None,
    }


async def _sync_admin_from_user(session: aiohttp.ClientSession, discord_id: str, user_profile: dict, source: str = "unknown"):
    """If discord_id is an admin, sync their service IDs from user_profile into admins.json."""
    try:
        admins, admins_sha = await read_admins(session)
        if discord_id not in admins:
            return  # not an admin, nothing to sync
        sync_fields = [
            ("anilist_user_id", "anilist_user_id"),
            ("anilist_username", "anilist_username"),
            ("anilist_avatar", "anilist_avatar"),
            ("mal_user_id", "mal_user_id"),
            ("mal_username", "mal_username"),
            ("mal_avatar", "mal_avatar"),
            ("simkl_user_id", "simkl_user_id"),
            ("simkl_username", "simkl_username"),
            ("simkl_avatar", "simkl_avatar"),
        ]
        changed = False
        rec = admins[discord_id]
        for admin_key, user_key in sync_fields:
            val = user_profile.get(user_key)
            if val is not None and rec.get(admin_key) != val:
                rec[admin_key] = val
                changed = True
        if changed:
            await write_admins(session, admins, admins_sha, f"sync: {source} for admin {discord_id}")
    except Exception as e:
        print(f"⚠️ Failed to sync admin profile from {source}: {e}")


# ── AniList autocomplete search helpers ────────────────────────────────────────


async def _anilist_search(query_str: str, media_type: str) -> list:
    """Search AniList for anime/manga, returns list of (id, idMal, display_title)."""
    query = """
    query ($search: String, $type: MediaType) {
      Page(perPage: 25) {
        media(search: $search, type: $type, sort: POPULARITY_DESC) {
          id idMal title { romaji english }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"search": query_str, "type": media_type}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        results = data.get("data", {}).get("Page", {}).get("media", [])
        out = []
        for m in results:
            title = m["title"].get("english") or m["title"].get("romaji") or "Unknown"
            out.append({"id": m["id"], "idMal": m.get("idMal"), "title": title})
        return out
    except Exception:
        return []


async def _anilist_user_search(query_str: str) -> list:
    """Search AniList users, returns list with full profile info."""
    query = """
    query ($search: String) {
      Page(perPage: 25) {
        users(search: $search) {
          id name
          avatar { large }
          bannerImage
          siteUrl
          about
          statistics {
            anime { count meanScore minutesWatched episodesWatched }
            manga { count chaptersRead volumesRead }
          }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"search": query_str}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        return data.get("data", {}).get("Page", {}).get("users", [])
    except Exception:
        return []


async def _anilist_fetch_user_by_id(user_id: int) -> dict | None:
    """Fetch full AniList user profile by ID."""
    query = """
    query ($id: Int) {
      User(id: $id) {
        id name
        avatar { large }
        bannerImage
        siteUrl
        about
        statistics {
          anime { count meanScore minutesWatched episodesWatched }
          manga { count chaptersRead volumesRead }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"id": user_id}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return data.get("data", {}).get("User")
    except Exception:
        return None


async def _anilist_fetch_user_by_name(username: str) -> dict | None:
    """Fetch exact AniList user profile by username. Returns None if not found."""
    query = """
    query ($name: String) {
      User(name: $name) {
        id name
        avatar { large }
        bannerImage
        siteUrl
        about
        statistics {
          anime { count meanScore minutesWatched episodesWatched }
          manga { count chaptersRead volumesRead }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API,
                json={"query": query, "variables": {"name": username}},
                headers={"Content-Type": "application/json"},
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return data.get("data", {}).get("User")
    except Exception:
        return None


async def _mal_get_user_id(mal_username: str) -> int | None:
    """Fetch MAL user ID from username via Jikan API (no auth needed)."""
    profile = await _mal_fetch_full_profile(mal_username)
    return profile.get("mal_id") if profile else None


async def _mal_fetch_username_by_id(mal_id: int) -> str | None:
    """Fetch MAL username from user ID via Jikan API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.jikan.moe/v4/users/userbyid/{mal_id}",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        return data.get("data", {}).get("username")
    except Exception:
        return None


async def _mal_fetch_full_profile(mal_username: str) -> dict | None:
    """Fetch full MAL user profile via Jikan API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.jikan.moe/v4/users/{mal_username}/full",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        d = data.get("data", {})
        if not d:
            return None
        return {
            "mal_id": d.get("mal_id"),
            "username": d.get("username"),
            "url": d.get("url"),
            "image_url": d.get("images", {}).get("jpg", {}).get("image_url"),
            "about": (d.get("about") or "")[:300],
            "anime_stats": {
                "days_watched": d.get("statistics", {}).get("anime", {}).get("days_watched"),
                "mean_score": d.get("statistics", {}).get("anime", {}).get("mean_score"),
                "watching": d.get("statistics", {}).get("anime", {}).get("watching"),
                "completed": d.get("statistics", {}).get("anime", {}).get("completed"),
                "total_entries": d.get("statistics", {}).get("anime", {}).get("total_entries"),
            },
            "manga_stats": {
                "days_read": d.get("statistics", {}).get("manga", {}).get("days_read"),
                "mean_score": d.get("statistics", {}).get("manga", {}).get("mean_score"),
                "reading": d.get("statistics", {}).get("manga", {}).get("reading"),
                "completed": d.get("statistics", {}).get("manga", {}).get("completed"),
                "total_entries": d.get("statistics", {}).get("manga", {}).get("total_entries"),
            },
        }
    except Exception:
        return None


# ── Simkl token encryption ─────────────────────────────────────────────────────


def _simkl_encrypt_token(token: str) -> str | None:
    """Encrypt a Simkl access token for safe storage in GitHub JSON."""
    if not SIMKL_ENCRYPT_KEY:
        print("[Simkl encrypt] SIMKL_ENCRYPT_KEY not set — cannot encrypt token")
        return None
    try:
        f = Fernet(SIMKL_ENCRYPT_KEY.encode())
        return f.encrypt(token.encode()).decode()
    except Exception as e:
        print(f"[Simkl encrypt] failed: {e}")
        return None


def _simkl_decrypt_token(encrypted: str) -> str | None:
    """Decrypt a stored Simkl access token for use in API calls."""
    if not SIMKL_ENCRYPT_KEY or not encrypted:
        return None
    try:
        f = Fernet(SIMKL_ENCRYPT_KEY.encode())
        return f.decrypt(encrypted.encode()).decode()
    except Exception as e:
        print(f"[Simkl decrypt] failed: {e}")
        return None


# ── Simkl helpers ───────────────────────────────────────────────────────────────


async def _simkl_fetch_user_with_token(access_token: str) -> dict | None:
    """Fetch authenticated Simkl user profile. Returns username, user_id, avatar_url."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/users/settings",
                headers={
                    "simkl-api-key": SIMKL_CLIENT_ID,
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[Simkl user settings] status={r.status} body={body[:200]}")
                    return None
                data = await r.json()
                print(f"[Simkl user settings] raw={str(data)[:500]}")
                # /users/settings response shape:
                # {"account": {"id": 123, ...}, "user": {"name": "...", "avatar": "..."}}
                account = data.get("account") or {}
                user = data.get("user") or data
                # ID is under account.id
                user_id = account.get("id") or user.get("user_id") or user.get("id")
                avatar_raw = user.get("avatar")
                if avatar_raw:
                    if avatar_raw.startswith("http"):
                        avatar_url = avatar_raw
                    else:
                        avatar_url = f"https://simkl.in/avatars/{avatar_raw}/{avatar_raw}_100.jpg"
                elif user_id:
                    avatar_url = f"https://simkl.in/avatars/{user_id}/{user_id}_100.jpg"
                else:
                    avatar_url = None
                return {
                    "username": user.get("name") or user.get("username"),
                    "user_id": user_id,
                    "avatar_url": avatar_url,
                }
    except Exception as e:
        print(f"[Simkl user settings] exception: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# /link_anilist — OAuth redirect flow
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="link_anilist", description="Link your AniList account via OAuth (supports private profiles)")
async def link_anilist(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not ANILIST_CLIENT_ID:
        await interaction.followup.send(
            "❌ AniList OAuth is not configured on this bot. Set `ANILIST_CLIENT_ID` env var.",
            ephemeral=True,
        )
        return

    if not OAUTH_ENCRYPT_KEY:
        await interaction.followup.send(
            "❌ Token encryption key is not configured. Contact the bot admin.",
            ephemeral=True,
        )
        return

    state = _create_oauth_state(interaction.user.id, "anilist", interaction.user)
    auth_url = (
        f"https://anilist.co/api/v2/oauth/authorize"
        f"?client_id={ANILIST_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={OAUTH_BASE_URL}/oauth/anilist/callback"
        f"&state={state}"
    )

    embed = discord.Embed(
        title="🎌 Link your AniList Account",
        description=(
            "**1.** Click the button below to open AniList\n"
            "**2.** Authorize the app on AniList\n"
            "**3.** You'll be redirected back — just wait for confirmation\n\n"
            f"⏳ Link expires in **{OAUTH_EXPIRY // 60} minutes**.\n"
            "✅ Works with **private** profiles too!"
        ),
        color=0x2E51A2,
    )
    embed.set_footer(text="Waiting for you to authorize on AniList...")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="🔗 Open AniList Auth",
        url=auth_url,
        style=discord.ButtonStyle.link,
    ))
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # Poll for result
    deadline = time.time() + OAUTH_EXPIRY
    while time.time() < deadline:
        await asyncio.sleep(5)
        # Check our in-memory results
        result = _oauth_results.pop(state, None)
        if result:
            if result.get("success"):
                embed = discord.Embed(title="✅ AniList Linked!", color=0x2EA043)
                embed.add_field(name="Username", value=result["username"] or "Unknown", inline=True)
                embed.add_field(name="AniList ID", value=f"`{result.get('user_id')}`", inline=True)
                if result.get("anime_count") is not None:
                    embed.add_field(name="Anime", value=f"{result['anime_count']} watched", inline=True)
                if result.get("manga_count") is not None:
                    embed.add_field(name="Manga", value=f"{result['manga_count']} read", inline=True)
                if result.get("mean_score") is not None:
                    embed.add_field(name="Mean Score", value=f"{result['mean_score']}/100", inline=True)
                if result.get("avatar"):
                    embed.set_thumbnail(url=result["avatar"])
                embed.set_footer(text="Token encrypted and stored. Works with private profiles!")
                await interaction.followup.send(embed=embed, ephemeral=True)
                log_embed = discord.Embed(title="🔗 Account Linked — AniList", color=0x2E51A2)
                log_embed.add_field(name="Discord", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
                log_embed.add_field(name="AniList Username", value=result["username"], inline=True)
                log_embed.add_field(name="AniList ID", value=f"`{result.get('user_id')}`", inline=True)
                if result.get("anime_count") is not None:
                    log_embed.add_field(name="Anime", value=str(result["anime_count"]), inline=True)
                if result.get("manga_count") is not None:
                    log_embed.add_field(name="Manga", value=str(result["manga_count"]), inline=True)
                if result.get("avatar"):
                    log_embed.set_thumbnail(url=result["avatar"])
                log_embed.set_footer(text=f"Discord ID: {interaction.user.id}")
                await _send_log(log_embed)
            else:
                await interaction.followup.send(
                    f"❌ AniList linking failed: {result.get('error', 'Unknown error')}",
                    ephemeral=True,
                )
            return

    _oauth_pending.pop(state, None)
    await interaction.followup.send(
        f"⏰ Authorization timed out after {OAUTH_EXPIRY // 60} minutes. Run `/link_anilist` again.",
        ephemeral=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# /link_mal — OAuth redirect flow with PKCE
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="link_mal", description="Link your MyAnimeList account via OAuth (supports private profiles)")
async def link_mal(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not MAL_CLIENT_ID or not MAL_CLIENT_SECRET:
        await interaction.followup.send(
            "❌ MAL OAuth is not configured on this bot. Set `MAL_CLIENT_ID` and `MAL_CLIENT_SECRET` env vars.",
            ephemeral=True,
        )
        return

    if not OAUTH_ENCRYPT_KEY:
        await interaction.followup.send(
            "❌ Token encryption key is not configured. Contact the bot admin.",
            ephemeral=True,
        )
        return

    state = _create_oauth_state(interaction.user.id, "mal", interaction.user)
    verifier, challenge = _generate_pkce()
    _mal_pkce_store[state] = verifier

    auth_url = (
        f"https://myanimelist.net/v1/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={MAL_CLIENT_ID}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=plain"
        f"&redirect_uri={OAUTH_BASE_URL}/oauth/mal/callback"
        f"&state={state}"
    )

    embed = discord.Embed(
        title="🦊 Link your MyAnimeList Account",
        description=(
            "**1.** Click the button below to open MAL\n"
            "**2.** Authorize the app on MyAnimeList\n"
            "**3.** You'll be redirected — done!\n\n"
            f"⏳ Link expires in **{OAUTH_EXPIRY // 60} minutes**.\n"
            "✅ Works with **private** profiles too!"
        ),
        color=0x2E51A2,
    )
    embed.set_footer(text="Waiting for you to authorize on MAL...")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="🔗 Open MAL Auth",
        url=auth_url,
        style=discord.ButtonStyle.link,
    ))
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # Poll for result
    deadline = time.time() + OAUTH_EXPIRY
    while time.time() < deadline:
        await asyncio.sleep(5)
        result = _oauth_results.pop(state, None)
        if result:
            if result.get("success"):
                embed = discord.Embed(title="✅ MAL Linked!", color=0x2EA043)
                embed.add_field(name="Username", value=result["username"] or "Unknown", inline=True)
                embed.add_field(name="MAL ID", value=f"`{result.get('user_id')}`", inline=True)
                if result.get("anime_completed") is not None:
                    embed.add_field(name="Anime Completed", value=str(result["anime_completed"]), inline=True)
                if result.get("manga_completed") is not None:
                    embed.add_field(name="Manga Completed", value=str(result["manga_completed"]), inline=True)
                if result.get("avatar"):
                    embed.set_thumbnail(url=result["avatar"])
                embed.set_footer(text="Token encrypted and stored. Works with private profiles!")
                await interaction.followup.send(embed=embed, ephemeral=True)
                log_embed = discord.Embed(title="🔗 Account Linked — MAL", color=0xE74C3C)
                log_embed.add_field(name="Discord", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
                log_embed.add_field(name="MAL Username", value=result["username"], inline=True)
                log_embed.add_field(name="MAL ID", value=f"`{result.get('user_id')}`", inline=True)
                if result.get("anime_completed") is not None:
                    log_embed.add_field(name="Anime Completed", value=str(result["anime_completed"]), inline=True)
                if result.get("manga_completed") is not None:
                    log_embed.add_field(name="Manga Completed", value=str(result["manga_completed"]), inline=True)
                if result.get("avatar"):
                    log_embed.set_thumbnail(url=result["avatar"])
                log_embed.set_footer(text=f"Discord ID: {interaction.user.id}")
                await _send_log(log_embed)
            else:
                await interaction.followup.send(
                    f"❌ MAL linking failed: {result.get('error', 'Unknown error')}",
                    ephemeral=True,
                )
            return

    _oauth_pending.pop(state, None)
    _mal_pkce_store.pop(state, None)
    await interaction.followup.send(
        f"⏰ Authorization timed out after {OAUTH_EXPIRY // 60} minutes. Run `/link_mal` again.",
        ephemeral=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# /link_simkl — OAuth redirect flow (replaces old PIN flow)
# ══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="link_simkl", description="Link your Simkl account via OAuth")
async def link_simkl(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not SIMKL_CLIENT_ID or not SIMKL_CLIENT_SECRET:
        await interaction.followup.send("❌ Simkl OAuth is not configured. Set `SIMKL_CLIENT_ID` and `SIMKL_CLIENT_SECRET` env vars.", ephemeral=True)
        return

    if not OAUTH_ENCRYPT_KEY:
        await interaction.followup.send("❌ Token encryption key is not configured. Contact the bot admin.", ephemeral=True)
        return

    state = _create_oauth_state(interaction.user.id, "simkl", interaction.user)
    auth_url = (
        f"https://simkl.com/oauth/authorize"
        f"?client_id={SIMKL_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={OAUTH_BASE_URL}/oauth/simkl/callback"
        f"&state={state}"
    )

    embed = discord.Embed(
        title="🎬 Link your Simkl Account",
        description=(
            "**1.** Click the button below to open Simkl\n"
            "**2.** Authorize the app on Simkl\n"
            "**3.** You'll be redirected — done!\n\n"
            f"⏳ Link expires in **{OAUTH_EXPIRY // 60} minutes**."
        ),
        color=0x1DB954,
    )
    embed.set_footer(text="Waiting for you to authorize on Simkl...")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="🔗 Open Simkl Auth",
        url=auth_url,
        style=discord.ButtonStyle.link,
    ))
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # Poll for result
    deadline = time.time() + OAUTH_EXPIRY
    while time.time() < deadline:
        await asyncio.sleep(5)
        result = _oauth_results.pop(state, None)
        if result:
            if result.get("success"):
                embed = discord.Embed(title="✅ Simkl Linked!", color=0x2EA043)
                embed.add_field(name="Username", value=result["username"] or "Unknown", inline=True)
                embed.add_field(name="Simkl ID", value=f"`{result.get('user_id')}`", inline=True)
                if result.get("avatar"):
                    embed.set_thumbnail(url=result["avatar"])
                embed.set_footer(text="Your token is encrypted and stored securely.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                log_embed = discord.Embed(title="🔗 Account Linked — Simkl", color=0x1DB954)
                log_embed.add_field(name="Discord", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
                log_embed.add_field(name="Simkl Username", value=result["username"], inline=True)
                log_embed.add_field(name="Simkl ID", value=f"`{result.get('user_id')}`", inline=True)
                if result.get("avatar"):
                    log_embed.set_thumbnail(url=result["avatar"])
                log_embed.set_footer(text=f"Discord ID: {interaction.user.id}")
                await _send_log(log_embed)
            else:
                await interaction.followup.send(
                    f"❌ Simkl linking failed: {result.get('error', 'Unknown error')}",
                    ephemeral=True,
                )
            return

    _oauth_pending.pop(state, None)
    await interaction.followup.send(
        f"⏰ Authorization timed out after {OAUTH_EXPIRY // 60} minutes. Run `/link_simkl` again.",
        ephemeral=True,
    )

# ── Simkl helper functions ─────────────────────────────────────────────────────


async def _simkl_fetch_user(simkl_username: str) -> dict | None:
    """
    Fetch a Simkl user's public profile using /search/users (works with client_id only, no OAuth).
    Avatar URL format per Simkl docs: https://simkl.in/avatars/{hash}/{hash}_100.jpg
    """
    if not SIMKL_CLIENT_ID:
        print(f"[Simkl fetch user] SIMKL_CLIENT_ID is not set — cannot fetch user {simkl_username!r}")
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/search/users",
                params={"q": simkl_username, "client_id": SIMKL_CLIENT_ID, "limit": 5},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"[Simkl fetch user] status={r.status} for {simkl_username!r} — body: {body[:200]}")
                    return None
                data = await r.json()
                print(f"[Simkl fetch user] raw response for {simkl_username!r}: {str(data)[:300]}")

                # /search/users returns a list — find exact username match (case-insensitive)
                users = data if isinstance(data, list) else data.get("users", [])
                user = None
                for u in users:
                    if (u.get("name") or u.get("username") or "").lower() == simkl_username.lower():
                        user = u
                        break
                # fallback to first result if no exact match
                if not user and users:
                    user = users[0]

                if not user:
                    print(f"[Simkl fetch user] no results found for {simkl_username!r}")
                    return None

                user_id = user.get("id")
                avatar_raw = user.get("avatar")

                if avatar_raw:
                    if avatar_raw.startswith("http"):
                        avatar_url = avatar_raw
                    else:
                        avatar_url = f"https://simkl.in/avatars/{avatar_raw}/{avatar_raw}_100.jpg"
                elif user_id:
                    avatar_url = f"https://simkl.in/avatars/{user_id}/{user_id}_100.jpg"
                else:
                    avatar_url = None

                result = {
                    "username": user.get("name") or user.get("username") or simkl_username,
                    "user_id": user_id,
                    "avatar_url": avatar_url,
                }
                print(f"[Simkl fetch user] parsed → {result}")
                return result
    except Exception as e:
        print(f"[Simkl fetch user] exception for {simkl_username!r}: {e}")
        return None


# Keep old name as alias
_simkl_verify_user = _simkl_fetch_user


async def _simkl_search_tv(query_str: str) -> list:
    """Search Simkl TV shows via /search/tv."""
    if not SIMKL_CLIENT_ID:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/search/tv",
                params={"q": query_str, "client_id": SIMKL_CLIENT_ID, "limit": 25},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    print(f"[Simkl /search/tv] status={r.status} query={query_str!r}")
                    return []
                data = await r.json()
                return data if isinstance(data, list) else data.get("results", [])
    except Exception as e:
        print(f"[Simkl /search/tv] exception: {e}")
        return []


async def _simkl_search_movies(query_str: str) -> list:
    """Search Simkl movies via /search/movies."""
    if not SIMKL_CLIENT_ID:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/search/movie",
                params={"q": query_str, "client_id": SIMKL_CLIENT_ID, "limit": 25},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    print(f"[Simkl /search/movies] status={r.status} query={query_str!r}")
                    return []
                data = await r.json()
                return data if isinstance(data, list) else data.get("results", [])
    except Exception as e:
        print(f"[Simkl /search/movies] exception: {e}")
        return []


async def _simkl_fetch_show(simkl_id: int) -> dict | None:
    """Fetch full TV show details from Simkl."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/tv/{simkl_id}",
                params={"extended": "full", "client_id": SIMKL_CLIENT_ID},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                body = await r.text()
                print(f"[Simkl fetch show] id={simkl_id} status={r.status} body={body[:300]}")
                if r.status != 200:
                    return None
                import json
                return json.loads(body)
    except Exception as e:
        print(f"[Simkl fetch show] exception id={simkl_id}: {e}")
        return None


async def _simkl_fetch_movie(simkl_id: int) -> dict | None:
    """Fetch full movie details from Simkl."""
    if not SIMKL_CLIENT_ID:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SIMKL_API}/movies/{simkl_id}",
                params={"extended": "full", "client_id": SIMKL_CLIENT_ID},
                headers={"simkl-api-key": SIMKL_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                body = await r.text()
                print(f"[Simkl fetch movie] id={simkl_id} status={r.status} body={body[:300]}")
                if r.status != 200:
                    return None
                import json
                return json.loads(body)
    except Exception as e:
        print(f"[Simkl fetch movie] exception id={simkl_id}: {e}")
        return None


def _simkl_poster(simkl_data: dict) -> str | None:
    """Extract poster URL from Simkl media data."""
    poster = simkl_data.get("poster")
    if poster:
        return f"https://simkl.in/posters/{poster}_m.jpg"
    return None


# ── Autocomplete functions ─────────────────────────────────────────────────────


async def anime_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _anilist_search(current, "ANIME")
    return [
        app_commands.Choice(
            name=f"{r['title'][:90]} (AL:{r['id']} MAL:{r['idMal'] or '?'})",
            value=str(r["id"]),
        )
        for r in results
    ][:25]


async def manga_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _anilist_search(current, "MANGA")
    return [
        app_commands.Choice(
            name=f"{r['title'][:90]} (AL:{r['id']} MAL:{r['idMal'] or '?'})",
            value=str(r["id"]),
        )
        for r in results
    ][:25]


async def show_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _simkl_search_tv(current)
    choices = []
    for r in results[:25]:
        # Simkl may return ids nested under "ids" dict or directly as "simkl_id"
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        title = r.get("title", "Unknown")
        year = r.get("year", "")
        if simkl_id:
            label = f"{title[:90]} ({year})" if year else title[:100]
            choices.append(app_commands.Choice(name=label, value=str(simkl_id)))
    return choices


async def movie_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not current or len(current) < 2:
        return []
    results = await _simkl_search_movies(current)
    choices = []
    for r in results[:25]:
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        title = r.get("title", "Unknown")
        year = r.get("year", "")
        if simkl_id:
            label = f"{title[:90]} ({year})" if year else title[:100]
            choices.append(app_commands.Choice(name=label, value=str(simkl_id)))
    return choices


# ── on ready ───────────────────────────────────────────────────────────────────


@bot.event
async def on_disconnect():
    """Fires when bot loses connection — could be a dead proxy."""
    print("⚠️ Bot disconnected from Discord.")
    if _current_proxy:
        # Dont immediately rotate — discord.py will try to reconnect by itself first.
        # Only rotate if health check also fails.
        print("⚠️ Will verify proxy on next health check cycle.")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        # ── 0. Register persistent views so buttons survive bot restarts ─────────
        # These views handle button clicks on messages that were sent before restart.
        # CancelBuildView is registered per-message in the build commands via
        # bot.add_view(view, message_id=msg.id), but we also register a fallback.
        try:
            bot.add_view(CancelBuildView(run_id=0, label="Cancel Build"))
            print("✅ Persistent CancelBuildView registered")
        except Exception as e:
            print(f"⚠️ Failed to register persistent CancelBuildView: {e}")

        # ── 1. Flush any logs queued/persisted before bot was ready ──────────────
        if LOG_CHANNEL_ID:
            try:
                ch = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
                if ch and _log_queue:
                    print(f"📤 Flushing {len(_log_queue)} queued log embeds...")
                    while _log_queue:
                        await ch.send(embed=_dict_to_embed(_log_queue.pop(0)))
                    await _persist_log_queue()
            except Exception as e:
                print(f"⚠️ Failed to flush log queue: {type(e).__name__}: {e}")

        # ── 3. Send startup log to owner DM ──────────────────────────────────────
        import datetime
        try:
            embed = discord.Embed(title="🟢 Bot Started", color=0x2ecc71)
            embed.add_field(name="Logged in as", value=str(bot.user), inline=False)
            embed.add_field(name="Active Proxy", value=_current_proxy or "None (direct connection)", inline=False)
            embed.add_field(name="Proxy Pool", value=f"{len(_proxy_list)} proxies loaded" if _proxy_list else "No proxy pool", inline=False)
            embed.timestamp = datetime.datetime.utcnow()
            asyncio.create_task(_dm_owner(embed))
            print("✅ Startup DM queued to owner")
        except Exception as e:
            print(f"⚠️ Startup DM failed: {type(e).__name__}: {e}")

        import asyncio

        # ── 4. Start proxy tasks ──────────────────────────────────────────────────
        if not proxy_health_check.is_running():
            proxy_health_check.start()
        asyncio.create_task(_al_load_state())
        if not anilist_monitor.is_running():
            anilist_monitor.start()
            print("✅ AniList monitor started (1 min interval)")
        asyncio.create_task(_background_proxy_finder())

        # ── 5. Heavy init in background — never blocks commands ───────────────────
        async def _bg_init():
            # ── Slash command sync ────────────────────────────────────────────────
            # Only sync when FORCE_SYNC=1 is set — commands stay registered between restarts.
            force_sync = os.environ.get("FORCE_SYNC", "").strip() == "1"
            if force_sync and not getattr(bot, "_synced", False):
                try:
                    await bot.tree.sync()
                    bot._synced = True
                    print("✅ Slash commands synced (FORCE_SYNC=1)")
                except Exception as e:
                    print(f"⚠️ Failed to sync slash commands: {e}")
            else:
                print("ℹ️ Skipping tree.sync() — set FORCE_SYNC=1 to re-sync after adding commands.")

            # ── One-time init: ensure JSON files exist on GitHub ─────────────────
            # Only runs if INIT_DONE flag is not set in env. After first successful
            # run, set INIT_DONE=1 in your environment so this never runs again.
            if os.environ.get("INIT_DONE", "").strip() != "1":
                try:
                    print("🔄 First-time init: ensure_json_files...")
                    await ensure_json_files()
                    print("✅ ensure_json_files done. Set INIT_DONE=1 in env to skip this on future restarts.")
                except Exception as e:
                    print(f"⚠️ ensure_json_files failed: {e}")
            else:
                print("ℹ️ Skipping ensure_json_files (INIT_DONE=1)")

            # ── Always: load FAQ into memory (single fast read) ──────────────────
            try:
                print("🔄 Loading FAQ from GitHub...")
                await load_faq_from_github()
            except Exception as e:
                print(f"⚠️ load_faq_from_github failed: {e}")

            # ── Always: load Rules into memory ────────────────────────────────────
            try:
                print("🔄 Loading Rules from GitHub...")
                await load_rules_from_github()
            except Exception as e:
                print(f"⚠️ load_rules_from_github failed: {e}")

            # ── Repopulator: run if 7 days have passed since last run ─────────────
            # Checks last_repopulated.json in private repo.
            # This means deploys/restarts never cause an unnecessary full API sweep.
            try:
                async with aiohttp.ClientSession() as session:
                    ran = await _maybe_run_repopulator(session, triggered_by="startup check")
                    if not ran:
                        print("ℹ️ Repopulator skipped — not 7 days yet")
            except Exception as e:
                print(f"⚠️ Startup repopulator check failed: {e}")

            # ── Start weekly check loop ───────────────────────────────────────────
            if not weekly_repopulator.is_running():
                weekly_repopulator.start()
                print("✅ Weekly repopulator loop started")

            # ── Start mute/timeout expiry task ────────────────────────────────
            asyncio.create_task(moderation._mute_expiry_task())
            print("✅ Mute/timeout expiry task started")

        async def _bg_init_safe():
            try:
                await asyncio.wait_for(_bg_init(), timeout=120)
            except asyncio.TimeoutError:
                print("⚠️ _bg_init timed out after 120s — bot is still running normally")
            except Exception as e:
                print(f"⚠️ _bg_init crashed: {e}")

        asyncio.create_task(_bg_init_safe())

    except Exception as e:
        print(f"❌ on_ready crashed: {type(e).__name__}: {e}")

async def ensure_json_files():
    """Auto-create all required JSON files on GitHub if they don't exist."""
    global _prefix_cache
    files = {
        FILE_USERS: {},
        FILE_TIMEZONES: {},
        FILE_ANIME: [],
        FILE_MANGA: [],
        FILE_SHOWS: [],
        FILE_MOVIES: [],
        FILE_PREFIXES: DEFAULT_PREFIXES[:],
        FILE_SERVER_CFG: {},
        FILE_VOTES: {},
    }

    async def _ensure_one(session, filepath, default):
        data, sha = await github_read_json(session, filepath)
        if sha is None:
            await github_write_json(session, filepath, default, None, f"init: create {filepath}")
            print(f"✅ Created {filepath} on GitHub")
        else:
            print(f"✅ {filepath} already exists")
        return filepath, data, sha

    async with aiohttp.ClientSession() as session:
        # Read + create all main repo files in parallel
        results = await asyncio.gather(
            *[_ensure_one(session, fp, default) for fp, default in files.items()],
            return_exceptions=True,
        )
        # Load prefixes from results (avoid a second read)
        for r in results:
            if isinstance(r, tuple) and r[0] == FILE_PREFIXES:
                prefixes = r[1]
                _prefix_cache[:] = (
                    prefixes if isinstance(prefixes, list) and prefixes else DEFAULT_PREFIXES[:]
                )
                break
        else:
            # Fallback: re-fetch if not found in results
            prefixes, _ = await github_read_json(session, FILE_PREFIXES)
            _prefix_cache[:] = (
                prefixes if isinstance(prefixes, list) and prefixes else DEFAULT_PREFIXES[:]
            )

    # Also ensure FILE_USERS and FILE_ADMINS exist in the private userdata repo (parallel)
    async def _ensure_users(session):
        users_data, users_sha = await read_users(session)
        if users_sha is None:
            await write_users(session, {}, None, f"init: create {FILE_USERS} in userdata repo")
            print(f"✅ Created {FILE_USERS} in userdata repo")
        else:
            print(f"✅ {FILE_USERS} already exists in userdata repo")

    async def _ensure_admins(session):
        admins_data, admins_sha = await read_admins(session)
        if admins_sha is None:
            await write_admins(session, {}, None, f"init: create {FILE_ADMINS} in userdata repo")
            print(f"✅ Created {FILE_ADMINS} in userdata repo")
        else:
            print(f"✅ {FILE_ADMINS} already exists in userdata repo")

    async def _ensure_banned(session):
        banned_data, banned_sha = await moderation.read_banned(session)
        if banned_sha is None:
            await moderation.write_banned(session, {}, None, f"init: create {FILE_BANNED} in userdata repo")
            print(f"✅ Created {FILE_BANNED} in userdata repo")
        else:
            print(f"✅ {FILE_BANNED} already exists in userdata repo")

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(_ensure_users(session), _ensure_admins(session), _ensure_banned(session), return_exceptions=True)

    print(f"✅ Active prefixes: {_prefix_cache}")


# ══════════════════════════════════════════════════════════════════════════════
# /myprofile
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="myprofile", description="View your saved profile")
async def myprofile(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        users, _ = await read_users(session)

    profile = users.get(str(interaction.user.id))
    if not profile:
        await interaction.followup.send(
            "❌ No profile found. Link an account first using `/link_anilist`, `/link_mal`, or `/link_simkl`!", ephemeral=True
        )
        return

    embed = discord.Embed(title=f"👤 {profile.get('author_name', interaction.user.display_name)}'s Profile", color=0x0078D4)

    # ── AniList section ──────────────────────────────────────────────────────
    al_id = profile.get("anilist_user_id")
    al_name = profile.get("anilist_username")
    al_url = profile.get("anilist_url")
    al_avatar = profile.get("anilist_avatar")
    al_anime = profile.get("anilist_anime_count")
    al_manga = profile.get("anilist_manga_count")
    al_score = profile.get("anilist_mean_score")
    al_minutes = profile.get("anilist_minutes_watched")
    al_chapters = profile.get("anilist_chapters_read")

    if al_id:
        al_link = f"[{al_name}]({al_url})" if al_url else (al_name or str(al_id))
        embed.add_field(name="🔵 AniList", value=al_link, inline=True)
        embed.add_field(name="AL ID", value=f"`{al_id}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        stats_lines = []
        if al_anime is not None:
            stats_lines.append(f"Anime: **{al_anime}** | Score: **{al_score or 'N/A'}**")
        if al_minutes is not None:
            days = round(al_minutes / 1440, 1)
            stats_lines.append(f"Days Watched: **{days}**")
        if al_manga is not None:
            stats_lines.append(f"Manga: **{al_manga}** | Chapters: **{al_chapters or 'N/A'}**")
        if stats_lines:
            embed.add_field(name="AniList Stats", value="\n".join(stats_lines), inline=False)
    else:
        embed.add_field(name="🔵 AniList", value="*Not linked*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    # ── MAL section ───────────────────────────────────────────────────────────
    mal_id = profile.get("mal_user_id")
    mal_name = profile.get("mal_username")
    mal_url = profile.get("mal_url")
    mal_avatar = profile.get("mal_avatar")
    mal_anime_done = profile.get("mal_anime_completed")
    mal_anime_score = profile.get("mal_anime_mean_score")
    mal_manga_done = profile.get("mal_manga_completed")
    mal_manga_score = profile.get("mal_manga_mean_score")

    if mal_id:
        mal_link = f"[{mal_name}]({mal_url})" if mal_url else (mal_name or str(mal_id))
        embed.add_field(name="🔴 MAL", value=mal_link, inline=True)
        embed.add_field(name="MAL ID", value=f"`{mal_id}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        mal_stats_lines = []
        if mal_anime_done is not None:
            mal_stats_lines.append(f"Anime Completed: **{mal_anime_done}** | Score: **{mal_anime_score or 'N/A'}**")
        if mal_manga_done is not None:
            mal_stats_lines.append(f"Manga Completed: **{mal_manga_done}** | Score: **{mal_manga_score or 'N/A'}**")
        if mal_stats_lines:
            embed.add_field(name="MAL Stats", value="\n".join(mal_stats_lines), inline=False)
    else:
        embed.add_field(name="🔴 MAL", value="*Not linked*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Avatar: prefer AniList, fallback to MAL
    avatar = al_avatar or mal_avatar
    if avatar:
        embed.set_thumbnail(url=avatar)

    embed.set_footer(text="Use /link_anilist, /link_mal, or /link_simkl to update your profile.")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Confirm/Cancel view
# ══════════════════════════════════════════════════════════════════════════════


class ConfirmView(discord.ui.View):
    def __init__(self, entry: dict, filepath: str, media_type: str, cover_url: str):
        super().__init__(timeout=None)
        self.entry = entry
        self.filepath = filepath
        self.media_type = media_type
        self.cover_url = cover_url

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success, custom_id="confirm_anime:confirm")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        self.stop()

        async with aiohttp.ClientSession() as session:
            entries, sha = await github_read_json(session, self.filepath)
            upserted = False
            existing_idx = next(
                (i for i, e in enumerate(entries) if e.get("anilist_id") == self.entry["anilist_id"]),
                None,
            )

            if existing_idx is not None:
                # Entry exists — check if this user already has a reason on it
                existing = entries[existing_idx]
                if "reasons" not in existing:
                    first = {
                        "discord_id": existing.get("added_by_discord_id"),
                        "discord_username": existing.get("user", {}).get("discord", {}).get("username"),
                        "user": existing.get("user", {}),
                        "author": existing.get("author"),
                        "text": existing.get("reason", ""),
                        "added_at": None,
                    }
                    existing["reasons"] = [first]
                    entries[existing_idx] = existing

                # Check duplicate using _find_reason_by_any_id (matches any ID field)
                dup_idx = _find_reason_by_any_id(
                    existing["reasons"], str(interaction.user.id)
                )
                if dup_idx is not None:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="⚠️ Already contributed",
                            description=f"You already have a reason on **{self.entry['title']}**. Use `/edit_reason` to update it.",
                            color=0xFFA500,
                        ),
                        ephemeral=True,
                    )
                    return

                # Append this user's reason to existing entry
                new_reason = self.entry["reasons"][0]
                existing["reasons"].append(new_reason)
                entries[existing_idx] = existing
                upserted = True
            else:
                # Brand new entry
                entries.append(self.entry)

            ok = await github_write_json(
                session,
                self.filepath,
                entries,
                sha,
                f"feat: {'add reason' if upserted else 'add'} {self.entry['title']} to community {self.media_type} by {self.entry['author']}",
            )

        if ok:
            if upserted:
                embed = discord.Embed(
                    title=f"➕ Reason Added to {self.media_type.title()}!", color=0x5865F2
                )
            else:
                embed = discord.Embed(
                    title=f"🎉 Added to community {self.media_type}!", color=0x2EA043
                )
            embed.add_field(name="Title", value=self.entry["title"], inline=True)
            u = self.entry.get("user", {})
            al = u.get("anilist", {})
            author_display = (al.get("username") or u.get("mal", {}).get("username") or "Unknown")
            embed.add_field(name="Author", value=author_display, inline=True)
            embed.add_field(name="Reason", value=_short_reason(self.entry.get("reason")), inline=False)
            if self.cover_url:
                embed.set_thumbnail(url=self.cover_url)
            log_title = f"➕ Reason Added to {self.media_type.title()}" if upserted else f"📥 New {self.media_type.title()} Added"
            log_embed = discord.Embed(title=log_title, color=0x5865F2 if upserted else 0x2EA043)
            log_embed.add_field(name="Title", value=self.entry["title"], inline=True)
            log_embed.add_field(name="Score", value=str(self.entry.get("score", "N/A")), inline=True)
            log_embed.add_field(name="Added by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
            log_embed.add_field(name="IDs", value=_ids_line(AL=self.entry.get("anilist_id"), MAL=self.entry.get("mal_id"), DC=interaction.user.id), inline=False)
            _log_reason_fields(log_embed, self.entry.get("reason", ""))
            if self.cover_url:
                log_embed.set_thumbnail(url=self.cover_url)
            await _send_log(log_embed)
        else:
            embed = discord.Embed(title="❌ Failed to commit to GitHub", color=0xDA3633)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="confirm_anime:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("Cancelled.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Shared add logic
# ══════════════════════════════════════════════════════════════════════════════


async def handle_add(interaction, anilist_id: int, reason: str, media_type: str):
    from datetime import datetime
    await interaction.response.defer()

    reason = reason.strip()
    if len(reason) < 30:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Reason too short",
                description="Your reason must be at least **30 characters**. Tell the community why this deserves more attention!",
                color=0xFF4444,
            ),
            ephemeral=True,
        )
        return
    if len(reason) > 700:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Reason too long",
                description=f"Your reason must be at most **700 characters** (yours is {len(reason)}).",
                color=0xFF4444,
            ),
            ephemeral=True,
        )
        return

    async with aiohttp.ClientSession() as session:
        users, _ = await read_users(session)
        admins, _ = await read_admins(session)
        profile = users.get(str(interaction.user.id))

        if not profile:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ Profile not set up",
                    description="Link your accounts first using `/link_anilist`, `/link_mal`, or `/link_simkl`!",
                    color=0xFFA500,
                ),
                ephemeral=True,
            )
            return

        media = await fetch_anilist(session, anilist_id, media_type)
        mal_data = None

        # ── Jikan fallback when AniList doesn't have this entry ───────────
        if not media:
            mal_id_guess = None
            # Try resolving AniList ID → MAL ID via mal-backup to attempt Jikan
            mb_type = "anime" if media_type == "ANIME" else "manga"
            mal_id_guess = await _malbackup_anilist_to_mal(mb_type, anilist_id)
            if mal_id_guess:
                mal_data = await fetch_mal_jikan(session, mal_id_guess, media_type)

    if not media and not mal_data:
        await interaction.followup.send("❌ Could not fetch info from AniList or MAL.", ephemeral=True)
        return

    # ── Build entry data from either AniList or Jikan ─────────────────────
    if media:
        titles = media["title"]
        title = titles.get("english") or titles.get("romaji") or titles.get("native") or "Unknown"
        cover_url = media.get("coverImage", {}).get("large", "")
        score = media.get("averageScore") or "N/A"
        genres = ", ".join(media.get("genres", [])[:4]) or "N/A"
        mal_id = media.get("idMal")
    else:
        # Using Jikan (MAL) fallback data
        title = mal_data["title"]
        cover_url = mal_data["poster"]
        score = mal_data["score"]
        genres = mal_data.get("genres", "N/A")
        mal_id = await _malbackup_anilist_to_mal("anime" if media_type == "ANIME" else "manga", anilist_id) or None

    # Build AniList and MAL links
    type_path = "anime" if media_type == "ANIME" else "manga"
    anilist_url = f"https://anilist.co/{type_path}/{anilist_id}"
    mal_url = f"https://myanimelist.net/{type_path}/{mal_id}" if mal_id else "N/A"

    author = profile.get("author_name") or profile.get("author") or interaction.user.display_name

    user_snapshot = _build_user_snapshot(profile)
    _mark_admin_flag(user_snapshot, admins)

    # ── Extract detailed fields from either AniList or Jikan data ──────────
    if media:
        episodes = media.get("episodes")
        duration = media.get("duration")
        chapters = media.get("chapters")
        volumes = media.get("volumes")
        status = media.get("status")
        fmt = media.get("format")
        season = media.get("season")
        season_year = media.get("seasonYear")
        description = (media.get("description") or "")[:500]
        studios = [s["name"] for s in (media.get("studios", {}).get("nodes") or [])]
        entry_genres = media.get("genres", [])
        entry_nsfw = bool(media.get("isAdult") or False)
    else:
        # Jikan fallback — some fields won't be available
        episodes = mal_data.get("episodes")
        duration = None
        chapters = mal_data.get("chapters")
        volumes = mal_data.get("volumes")
        status = mal_data.get("status")
        fmt = mal_data.get("type")
        season = None
        season_year = mal_data.get("year")
        description = (mal_data.get("synopsis") or "")[:500]
        studios = []
        entry_genres = genres if isinstance(genres, list) else [g.strip() for g in (genres or "N/A").split(",") if g.strip()]
        entry_nsfw = mal_data.get("nsfw", False)

    async with aiohttp.ClientSession() as _tr_session:
        stored_reason = await _translate_reason(_tr_session, reason)

    reason_obj = {
        "discord_id": str(interaction.user.id),
        "discord_username": interaction.user.name,
        "user": user_snapshot,
        "author": author,
        "text": stored_reason,
        "added_at": datetime.utcnow().isoformat() + "Z",
        "edited_at": None,
    }

    entry = {
        "anilist_id": anilist_id,
        "mal_id": mal_id,
        "title": title,
        "author": author,
        "reason": stored_reason,
        "reasons": [reason_obj],
        "user": user_snapshot,
        "added_by_discord_id": str(interaction.user.id),
        "poster": cover_url,
        "score": score,
        "genres": entry_genres,
        "nsfw": entry_nsfw,
        "status": status,
        "format": fmt,
        "episodes": episodes,
        "duration": duration,
        "chapters": chapters,
        "volumes": volumes,
        "season": season,
        "season_year": season_year,
        "description": description,
        "studios": studios,
    }

    filepath = FILE_ANIME if media_type == "ANIME" else FILE_MANGA

    # Build preview embed — show profile links for the submitter
    al_uid = user_snapshot["anilist"]["id"]
    al_uname = user_snapshot["anilist"]["username"]
    mal_uid = user_snapshot["mal"]["id"]
    mal_uname = user_snapshot["mal"]["username"]

    al_profile_link = (
        f"[{al_uname}](https://anilist.co/user/{al_uname})" if al_uid and al_uname
        else (f"ID `{al_uid}`" if al_uid else "Not linked")
    )
    mal_profile_link = (
        f"[{mal_uname}](https://myanimelist.net/profile/{mal_uname})" if mal_uid and mal_uname
        else (f"ID `{mal_uid}`" if mal_uid else "Not linked")
    )

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"*Confirm to add to `{filepath}`*",
        color=0x0078D4,
    )
    preview.add_field(name="AniList", value=f"[Link]({anilist_url}) (ID: `{anilist_id}`)", inline=True)
    preview.add_field(name="MAL", value=f"[Link]({mal_url}) (ID: `{mal_id or '?'}`)", inline=True)
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Genres", value=genres, inline=True)
    if fmt:
        preview.add_field(name="Format", value=fmt, inline=True)
    if status:
        preview.add_field(name="Status", value=status.replace("_", " ").title(), inline=True)
    if episodes:
        preview.add_field(name="Episodes", value=str(episodes), inline=True)
    if duration:
        preview.add_field(name="Ep. Duration", value=f"{duration} min", inline=True)
    if chapters:
        preview.add_field(name="Chapters", value=str(chapters), inline=True)
    if season and season_year:
        preview.add_field(name="Season", value=f"{season.title()} {season_year}", inline=True)
    if studios:
        preview.add_field(name="Studio", value=", ".join(studios[:2]), inline=True)
    preview.add_field(name="Author", value=author, inline=True)
    preview.add_field(name="AniList Profile", value=al_profile_link, inline=True)
    preview.add_field(name="MAL Profile", value=mal_profile_link, inline=True)
    preview.add_field(name="Reason", value=stored_reason, inline=False)
    if cover_url:
        preview.set_thumbnail(url=cover_url)
    preview.set_footer(text="Click ✅ to confirm or ❌ to cancel.")

    view = ConfirmView(entry=entry, filepath=filepath, media_type=media_type.lower(), cover_url=cover_url)
    await interaction.followup.send(embed=preview, view=view)


# ══════════════════════════════════════════════════════════════════════════════
# /add_anime
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_anime", description="Add a community anime to the list")
@app_commands.describe(
    title="Search for the anime (type to get suggestions)",
    reason="Why do you recommend this?",
)
@app_commands.autocomplete(title=anime_autocomplete)
async def add_anime(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select an anime from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_add(interaction, int(title), reason, "ANIME")


# ══════════════════════════════════════════════════════════════════════════════
# /add_manga
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_manga", description="Add a community manga to the list")
@app_commands.describe(
    title="Search for the manga (type to get suggestions)",
    reason="Why do you recommend this?",
)
@app_commands.autocomplete(title=manga_autocomplete)
async def add_manga(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select a manga from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_add(interaction, int(title), reason, "MANGA")


# ══════════════════════════════════════════════════════════════════════════════
# Simkl add handler (shows & movies)
# ══════════════════════════════════════════════════════════════════════════════


async def handle_simkl_add(
    interaction: discord.Interaction,
    simkl_id: int,
    reason: str,
    media_type: str,  # "show" or "movie"
):
    from datetime import datetime
    await interaction.response.defer()

    reason = reason.strip()
    if len(reason) < 30:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Reason too short",
                description="Your reason must be at least **30 characters**. Tell the community why this deserves more attention!",
                color=0xFF4444,
            ),
            ephemeral=True,
        )
        return
    if len(reason) > 700:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ Reason too long",
                description=f"Your reason must be at most **700 characters** (yours is {len(reason)}).",
                color=0xFF4444,
            ),
            ephemeral=True,
        )
        return

    discord_id = str(interaction.user.id)

    async with aiohttp.ClientSession() as session:
        users, _ = await read_users(session)
        admins, _ = await read_admins(session)

    profile = users.get(discord_id)
    if not profile:
        await interaction.followup.send(
            "❌ You need to link an account first using `/link_anilist`, `/link_mal`, or `/link_simkl` before adding content.", ephemeral=True
        )
        return

    # Fetch media from Simkl
    if media_type == "show":
        media = await _simkl_fetch_show(simkl_id)
    else:
        media = await _simkl_fetch_movie(simkl_id)

    if not media:
        await interaction.followup.send(
            f"❌ Could not fetch {media_type} details from Simkl (ID: {simkl_id}).",
            ephemeral=True,
        )
        return

    title = media.get("title") or media.get("en_title") or f"Simkl ID {simkl_id}"
    poster_url = _simkl_poster(media)
    score = media.get("ratings", {}).get("simkl", {}).get("rating") or "N/A"
    genres = ", ".join(media.get("genres", [])[:4]) or "N/A"
    year = media.get("year") or ""

    # Simkl has no isAdult flag — derive nsfw from certification rating
    _adult_certs = {"NC-17", "X", "TV-MA", "R18", "18+", "AO"}
    certification = (media.get("certification") or "").upper().strip()
    nsfw = certification in _adult_certs

    author = profile.get("author_name") or interaction.user.display_name
    user_snapshot = _build_user_snapshot(profile)
    _mark_admin_flag(user_snapshot, admins)

    filepath = FILE_SHOWS if media_type == "show" else FILE_MOVIES
    simkl_url = f"https://simkl.com/{media_type}s/{simkl_id}"

    async with aiohttp.ClientSession() as _tr_session:
        stored_reason = await _translate_reason(_tr_session, reason)

    reason_obj = {
        "discord_id": str(interaction.user.id),
        "discord_username": interaction.user.name,
        "user": user_snapshot,
        "author": author,
        "text": stored_reason,
        "added_at": datetime.utcnow().isoformat() + "Z",
        "edited_at": None,
    }

    entry = {
        "simkl_id": simkl_id,
        "title": title,
        "year": year,
        "author": author,
        "reason": stored_reason,
        "reasons": [reason_obj],
        "user": user_snapshot,
        "added_by_discord_id": str(interaction.user.id),
        "poster": poster_url or "",
        "score": score,
        "genres": genres,
        "simkl_url": simkl_url,
        "nsfw": nsfw,
    }

    preview = discord.Embed(
        title=f"📋 Preview — {title}",
        description=f"*Confirm to add to the community {media_type} list*",
        color=0x9B59B6,
    )
    preview.add_field(name="Simkl", value=f"[Link]({simkl_url}) (ID: `{simkl_id}`)", inline=True)
    preview.add_field(name="Year", value=str(year) if year else "N/A", inline=True)
    preview.add_field(name="Score", value=f"`{score}`", inline=True)
    preview.add_field(name="Genres", value=genres, inline=True)
    preview.add_field(name="Author", value=author, inline=True)
    preview.add_field(name="Reason", value=stored_reason, inline=False)
    if poster_url:
        preview.set_thumbnail(url=poster_url)
    preview.set_footer(text="Click ✅ to confirm or ❌ to cancel.")

    view = SimklConfirmView(entry=entry, filepath=filepath, media_type=media_type, poster_url=poster_url)
    await interaction.followup.send(embed=preview, view=view)


class SimklConfirmView(discord.ui.View):
    def __init__(self, entry: dict, filepath: str, media_type: str, poster_url: str | None):
        super().__init__(timeout=None)
        self.entry = entry
        self.filepath = filepath
        self.media_type = media_type
        self.poster_url = poster_url

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.green, custom_id="confirm_simkl:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        async with aiohttp.ClientSession() as session:
            entries, sha = await github_read_json(session, self.filepath)
            upserted = False
            existing_idx = next(
                (i for i, e in enumerate(entries) if e.get("simkl_id") == self.entry["simkl_id"]),
                None,
            )

            if existing_idx is not None:
                # Entry exists — check if this user already has a reason on it
                existing = entries[existing_idx]
                if "reasons" not in existing:
                    first = {
                        "discord_id": existing.get("added_by_discord_id"),
                        "discord_username": existing.get("user", {}).get("discord", {}).get("username"),
                        "user": existing.get("user", {}),
                        "author": existing.get("author"),
                        "text": existing.get("reason", ""),
                        "added_at": None,
                    }
                    existing["reasons"] = [first]
                    entries[existing_idx] = existing

                dup_idx = _find_reason_by_any_id(
                    existing["reasons"], str(interaction.user.id)
                )
                if dup_idx is not None:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="⚠️ Already contributed",
                            description=f"You already have a reason on **{self.entry['title']}**. Use `/edit_reason` to update it.",
                            color=0xFFA500,
                        ),
                        ephemeral=True,
                    )
                    self.stop()
                    return

                # Append this user's reason to existing entry
                new_reason = self.entry["reasons"][0]
                existing["reasons"].append(new_reason)
                entries[existing_idx] = existing
                upserted = True
            else:
                entries.append(self.entry)

            ok = await github_write_json(
                session,
                self.filepath,
                entries,
                sha,
                f"feat: {'add reason' if upserted else 'add'} {self.entry['title']} to community {self.media_type} by {self.entry['author']}",
            )

        if ok:
            if upserted:
                embed = discord.Embed(
                    title=f"➕ Reason Added to {self.media_type.title()}!",
                    description=self.entry.get("reason"),
                    color=0x5865F2,
                )
            else:
                embed = discord.Embed(
                    title=f"✅ Added — {self.entry['title']}",
                    description=self.entry.get("reason"),
                    color=0x2EA043,
                )
            if self.poster_url:
                embed.set_thumbnail(url=self.poster_url)
            log_title = f"➕ Reason Added to {self.media_type.title()}" if upserted else f"📥 New {self.media_type.title()} Added"
            log_embed = discord.Embed(title=log_title, color=0x5865F2 if upserted else 0x2EA043)
            log_embed.add_field(name="Title", value=self.entry["title"], inline=True)
            log_embed.add_field(name="Score", value=str(self.entry.get("score", "N/A")), inline=True)
            log_embed.add_field(name="Added by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
            log_embed.add_field(name="IDs", value=_ids_line(Simkl=self.entry.get("simkl_id"), DC=interaction.user.id), inline=False)
            _log_reason_fields(log_embed, self.entry.get("reason", ""))
            if self.poster_url:
                log_embed.set_thumbnail(url=self.poster_url)
            await _send_log(log_embed)
        else:
            embed = discord.Embed(title="❌ Failed to save to GitHub", color=0xDA3633)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(embed=embed)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red, custom_id="confirm_simkl:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("❌ Cancelled.", ephemeral=True)
        self.stop()


# ══════════════════════════════════════════════════════════════════════════════
# /add_show
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_show", description="Add a community TV show to the list")
@app_commands.describe(
    title="Search for the TV show (type to get suggestions)",
    reason="Why do you recommend this?",
)
@app_commands.autocomplete(title=show_autocomplete)
async def add_show(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select a TV show from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_simkl_add(interaction, int(title), reason, "show")


# ══════════════════════════════════════════════════════════════════════════════
# /add_movie
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="add_movie", description="Add a community movie to the list")
@app_commands.describe(
    title="Search for the movie (type to get suggestions)",
    reason="Why do you recommend this?",
)
@app_commands.autocomplete(title=movie_autocomplete)
async def add_movie(interaction: discord.Interaction, title: str, reason: str):
    if not title.isdigit():
        await interaction.response.send_message(
            "❌ Please select a movie from the dropdown suggestions.", ephemeral=True
        )
        return
    await handle_simkl_add(interaction, int(title), reason, "movie")


# ══════════════════════════════════════════════════════════════════════════════
# /list_anime — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_anime", description="View the community anime list")
async def list_anime(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_ANIME)

    if not entries:
        embed = discord.Embed(
            title="Anime List", description="No anime added yet.", color=0x0066FF
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0x0066FF,
        )
        u = entry.get("user", {})
        al = u.get("anilist", {})
        author_display = al.get("username") or u.get("mal", {}).get("username") or "Unknown"
        embed.add_field(
            name="Author", value=author_display, inline=True
        )
        embed.add_field(
            name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True
        )
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_manga — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_manga", description="View the community manga list")
async def list_manga(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MANGA)

    if not entries:
        embed = discord.Embed(
            title="Manga List", description="No manga added yet.", color=0xFF6B6B
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0xFF6B6B,
        )
        u = entry.get("user", {})
        al = u.get("anilist", {})
        author_display = al.get("username") or u.get("mal", {}).get("username") or "Unknown"
        embed.add_field(
            name="Author", value=author_display, inline=True
        )
        embed.add_field(
            name="Score", value=f"{entry.get('score', 'N/A')}/100", inline=True
        )
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_shows
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_shows", description="View the community TV shows list")
async def list_shows(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_SHOWS)

    if not entries:
        embed = discord.Embed(
            title="TV Shows List", description="No shows added yet.", color=0x9B59B6
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0x9B59B6,
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Year", value=str(entry.get("year", "N/A")), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}", inline=True)
        if entry.get("simkl_url"):
            embed.add_field(name="Simkl", value=f"[Link]({entry['simkl_url']})", inline=True)
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
        embed.set_footer(text=f"{i}/{len(entries)}")
        embeds.append(embed)

    await interaction.followup.send(embeds=embeds[:10])


# ══════════════════════════════════════════════════════════════════════════════
# /list_movies
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="list_movies", description="View the community movies list")
async def list_movies(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MOVIES)

    if not entries:
        embed = discord.Embed(
            title="Movies List", description="No movies added yet.", color=0xE67E22
        )
        await interaction.followup.send(embed=embed)
        return

    embeds = []
    for i, entry in enumerate(entries, 1):
        embed = discord.Embed(
            title=entry.get("title", "Unknown"),
            description=entry.get("reason", "No reason"),
            color=0xE67E22,
        )
        embed.add_field(name="Author", value=entry.get("author", "Unknown"), inline=True)
        embed.add_field(name="Year", value=str(entry.get("year", "N/A")), inline=True)
        embed.add_field(name="Score", value=f"{entry.get('score', 'N/A')}", inline=True)
        if entry.get("simkl_url"):
            embed.add_field(name="Simkl", value=f"[Link]({entry['simkl_url']})", inline=True)
        if entry.get("poster"):
            embed.set_thumbnail(url=entry["poster"])
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
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No anime matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_ANIME, entries, sha, f"Remove anime: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(
            title="Removed", description=removed.get("title"), color=0x2EA043
        )
        log_embed = discord.Embed(title="🗑️ Entry Removed — Anime", color=0xDA3633)
        log_embed.add_field(name="Title", value=removed.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Removed by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=removed.get("anilist_id"), MAL=removed.get("mal_id"), DC=interaction.user.id), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(removed.get("reason")), inline=False)
        if removed.get("poster"):
            log_embed.set_thumbnail(url=removed["poster"])
        await _send_log(log_embed)
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
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No manga matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_MANGA, entries, sha, f"Remove manga: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(
            title="Removed", description=removed.get("title"), color=0x2EA043
        )
        log_embed = discord.Embed(title="🗑️ Entry Removed — Manga", color=0xDA3633)
        log_embed.add_field(name="Title", value=removed.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Removed by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(AL=removed.get("anilist_id"), MAL=removed.get("mal_id"), DC=interaction.user.id), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(removed.get("reason")), inline=False)
        if removed.get("poster"):
            log_embed.set_thumbnail(url=removed["poster"])
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /remove_show — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_show", description="Remove a TV show from the list")
@app_commands.describe(search_term="Title or Simkl ID")
@has_allowed_role()
async def remove_show(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_SHOWS)

    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit() and str(entry.get("simkl_id")) == search_term:
            found_index = i
            break
        elif search_term.lower() in entry.get("title", "").lower():
            found_index = i
            break

    if found_index is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No show matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_SHOWS, entries, sha, f"Remove show: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(title="Removed", description=removed.get("title"), color=0x2EA043)
        log_embed = discord.Embed(title="🗑️ Entry Removed — Show", color=0xDA3633)
        log_embed.add_field(name="Title", value=removed.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Removed by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(Simkl=removed.get("simkl_id"), DC=interaction.user.id), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(removed.get("reason")), inline=False)
        if removed.get("poster"):
            log_embed.set_thumbnail(url=removed["poster"])
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /remove_movie — Restricted
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(name="remove_movie", description="Remove a movie from the list")
@app_commands.describe(search_term="Title or Simkl ID")
@has_allowed_role()
async def remove_movie(interaction: discord.Interaction, search_term: str):
    await interaction.response.defer(ephemeral=True)

    async with aiohttp.ClientSession() as session:
        entries, sha = await github_read_json(session, FILE_MOVIES)

    found_index = None
    for i, entry in enumerate(entries):
        if search_term.isdigit() and str(entry.get("simkl_id")) == search_term:
            found_index = i
            break
        elif search_term.lower() in entry.get("title", "").lower():
            found_index = i
            break

    if found_index is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Not Found",
                description=f"No movie matching `{search_term}`",
                color=0xDA3633,
            ),
            ephemeral=True,
        )
        return

    removed = entries.pop(found_index)
    async with aiohttp.ClientSession() as session:
        success = await github_write_json(
            session, FILE_MOVIES, entries, sha, f"Remove movie: {removed.get('title')}"
        )

    if success:
        embed = discord.Embed(title="Removed", description=removed.get("title"), color=0x2EA043)
        log_embed = discord.Embed(title="🗑️ Entry Removed — Movie", color=0xDA3633)
        log_embed.add_field(name="Title", value=removed.get("title", "N/A"), inline=True)
        log_embed.add_field(name="Removed by", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
        log_embed.add_field(name="IDs", value=_ids_line(Simkl=removed.get("simkl_id"), DC=interaction.user.id), inline=False)
        log_embed.add_field(name="Entry Reason", value=_short_reason(removed.get("reason")), inline=False)
        if removed.get("poster"):
            log_embed.set_thumbnail(url=removed["poster"])
        await _send_log(log_embed)
    else:
        embed = discord.Embed(title="Failed to Remove", color=0xDA3633)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# /build
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM_CHOICES = [
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="android", value="android"),
    app_commands.Choice(name="linux", value="linux"),
    app_commands.Choice(name="windows", value="windows"),
    app_commands.Choice(name="macos", value="macos"),
    app_commands.Choice(name="ios", value="ios"),
    app_commands.Choice(name="android + linux + ios", value="android,linux,ios"),
    app_commands.Choice(name="android + ios", value="android,ios"),
    app_commands.Choice(name="android + windows", value="android,windows"),
    app_commands.Choice(name="android + linux", value="android,linux"),
    app_commands.Choice(name="android + macos", value="android,macos"),
    app_commands.Choice(name="linux + windows", value="linux,windows"),
    app_commands.Choice(name="linux + macos", value="linux,macos"),
    app_commands.Choice(name="windows + macos", value="windows,macos"),
    app_commands.Choice(name="ios + macos", value="ios,macos"),
]
BUILD_TYPE_CHOICES = [
    app_commands.Choice(name="alpha", value="alpha"),
    app_commands.Choice(name="stable", value="stable"),
]

# ══════════════════════════════════════════════════════════════════════════════
# NOTE: Discord Components V2 Status
# ══════════════════════════════════════════════════════════════════════════════
# Discord introduced Components V2 (IS_COMPONENTS_V2 flag = 1 << 15) which adds
# new component types: TextDisplay, Thumbnail, MediaGallery, File, Separator,
# Section, and Container. This allows buttons/images inside "embeds" (containers),
# eliminates the side color bar, and enables side-by-side thumbnails + text.
#
# HOWEVER, discord.py does NOT yet support Components V2 natively as of v2.5.x.
# See: https://github.com/Rapptz/discord.py/issues/10192
#
# Until discord.py adds V2 support, we use the **persistent View** pattern:
#   - timeout=None  → buttons never expire during runtime
#   - custom_id     → buttons are identifiable and re-registerable on restart
#   - bot.add_view() → registers views on startup so old buttons still work
#
# When discord.py adds V2 support, the ConfirmView/SimklConfirmView can be
# migrated to use Container components for a cleaner look.
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Persistent Cancel Build View — works across bot restarts
# ══════════════════════════════════════════════════════════════════════════════
# All cancel buttons share a single custom_id pattern: cancel_build:{run_id}
# When clicked, we parse the run_id from the custom_id to cancel the correct build.
# A mapping of custom_id → {run_id, label} is kept in memory so the handler
# knows which build to cancel even after a bot restart (re-populated from GitHub).
# ══════════════════════════════════════════════════════════════════════════════

_active_builds: dict[str, dict] = {}  # custom_id → {"run_id": int, "label": str}

class CancelBuildView(discord.ui.View):
    """
    Persistent cancel-build button that never expires.
    The run_id is encoded in the button's custom_id so it survives bot restarts.
    """
    def __init__(self, run_id: int, label: str = "Cancel Build"):
        super().__init__(timeout=None)
        self.run_id = run_id
        self._label = label
        # Set a unique custom_id for this specific build run
        cid = f"cancel_build:{run_id}"
        self.cancel_button.custom_id = cid
        self.cancel_button.label = label
        # Track in global mapping for persistence
        _active_builds[cid] = {"run_id": run_id, "label": label}

    @discord.ui.button(label="Cancel Build", style=discord.ButtonStyle.red, custom_id="cancel_build:0")
    async def cancel_button(
        self,
        button_interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        # Parse run_id from the custom_id (format: cancel_build:{run_id})
        cid = button.custom_id
        run_id = self.run_id
        # Also try parsing from custom_id as fallback (in case of persistent view)
        if not run_id and cid.startswith("cancel_build:"):
            try:
                run_id = int(cid.split(":")[1])
            except (ValueError, IndexError):
                pass

        await button_interaction.response.defer()
        button.disabled = True
        button.label = "Cancelling…"
        await button_interaction.message.edit(view=self)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{run_id}/cancel",
                headers=gh_headers(),
            ) as r:
                if r.status == 202:
                    button.label = "Cancelled"
                    await button_interaction.message.edit(view=self)
                    await button_interaction.followup.send(
                        embed=discord.Embed(title="✅ Build cancelled", color=0x2EA043),
                        ephemeral=True,
                    )
                    # Remove from active builds tracking
                    _active_builds.pop(cid, None)
                else:
                    button.disabled = False
                    button.label = self._label
                    await button_interaction.message.edit(view=self)
                    await button_interaction.followup.send(
                        embed=discord.Embed(title="❌ Failed to cancel build", color=0xDA3633),
                        ephemeral=True,
                    )


@bot.tree.command(name="build", description="Trigger the AnymeX-Preview build workflow")
@app_commands.describe(
    platforms="Platforms to build",
    build_type="Build type",
    pr_numbers="PR numbers (comma-separated)",
    tag_override="Version tag override",
)
@app_commands.choices(platforms=PLATFORM_CHOICES, build_type=BUILD_TYPE_CHOICES)
@has_allowed_role()
async def build(
    interaction: discord.Interaction,
    platforms: app_commands.Choice[str],
    build_type: app_commands.Choice[str],
    pr_numbers: str = "",
    tag_override: str = "",
):
    await interaction.response.defer()

    discord_user_id = str(interaction.user.id)

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "platforms": platforms.value,
            "build_type": build_type.value,
            "pr_numbers": pr_numbers,
            "tag_override": tag_override,
            "triggered_by": discord_user_id,
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
            headers=gh_headers(),
            json=payload,
        ) as r:
            status = r.status
            body = await r.text()

    if status == 204:
        embed = discord.Embed(title="Build Triggered!", color=0x2EA043)
        embed.add_field(
            name="Repo", value=f"`{GITHUB_OWNER}/{GITHUB_REPO}`", inline=True
        )
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="Build Type", value=f"`{build_type.value}`", inline=True)
        embed.add_field(name="Platforms", value=f"`{platforms.value}`", inline=True)
        if pr_numbers:
            embed.add_field(name="PRs", value=pr_numbers, inline=True)
        embed.add_field(
            name="Tag",
            value=f"`{tag_override}`" if tag_override else "Auto-detect",
            inline=True,
        )
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        embed.description = "Build started — fetching run link…"

        # Retry loop: GitHub takes a few seconds to register the new run
        run_id = None
        run_url = None
        async with aiohttp.ClientSession() as session:
            for _ in range(6):  # try up to ~12 seconds
                await asyncio.sleep(2)
                async with session.get(
                    f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=1&branch={GITHUB_BRANCH}",
                    headers=gh_headers(),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        runs = data.get("workflow_runs", [])
                        if runs and runs[0].get("status") in ("queued", "in_progress"):
                            run_id = runs[0]["id"]
                            run_url = runs[0]["html_url"]
                            break

        embed.add_field(
            name="View Run",
            value=f"[Open Run]({run_url})" if run_url else f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)",
            inline=False,
        )

        if run_id:
            embed.description = "Build started — click below to cancel if needed"

            view = CancelBuildView(run_id, label="Cancel Build")
            msg = await interaction.followup.send(embed=embed, view=view)
            bot.add_view(view, message_id=msg.id)
        else:
            embed.description = "Build started"
            await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Failed to Trigger Build",
            description=f"**Status:** `{status}`\n```{body[:1000]}```",
            color=0xDA3633,
        )
        await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /create_tag
# ══════════════════════════════════════════════════════════════════════════════

# ── Tag suggestion helpers ────────────────────────────────────────────────────

def _parse_beta_tag(tag: str) -> tuple[tuple[int, int, int], int | None] | None:
    """
    Parse a beta tag like v3.0.6-beta or v3.0.6+12-beta.
    Returns ((major, minor, patch), build_number_or_None) or None if not parseable.
    """
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?-beta$", tag)
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    build = int(m.group(4)) if m.group(4) is not None else None
    return (major, minor, patch), build


def _parse_stable_tag(tag: str) -> tuple[int, int, int] | None:
    """
    Parse a stable tag like v3.0.6.
    Returns (major, minor, patch) or None if not parseable.
    """
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


async def _fetch_latest_release_tag(session: aiohttp.ClientSession, owner: str, repo: str) -> str | None:
    """Fetch the tag name of the latest GitHub release for owner/repo."""
    try:
        async with session.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest",
            headers=gh_headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                return None
            data = await r.json()
            return data.get("tag_name")
    except Exception:
        return None


def _suggest_next_beta_tag(stable_tag: str | None, beta_tag: str | None) -> str | None:
    """
    Given the latest stable tag (Ryan's repo) and latest beta tag (Sheby's repo),
    return the suggested next beta tag.

    Rules:
    - Ryan ahead of beta base  → ryan_version-beta          (e.g. v3.0.7-beta)
    - Ryan == beta base, no build number on beta → version+1-beta (e.g. v3.0.7+1-beta)
    - Ryan == beta base, beta has build number   → increment build (e.g. v3.0.6+13-beta)
    - Beta base ahead of Ryan  → increment beta build number  (e.g. v3.0.8+16-beta)
    """
    stable = _parse_stable_tag(stable_tag) if stable_tag else None
    beta_parsed = _parse_beta_tag(beta_tag) if beta_tag else None

    # No stable tag available — just increment beta if possible
    if stable is None:
        if beta_parsed is None:
            return None
        (ma, mi, pa), build = beta_parsed
        next_build = (build or 0) + 1
        return f"v{ma}.{mi}.{pa}+{next_build}-beta"

    # No beta tag yet — use stable version as base
    if beta_parsed is None:
        ma, mi, pa = stable
        return f"v{ma}.{mi}.{pa}-beta"

    (b_ma, b_mi, b_pa), build = beta_parsed
    s_ma, s_mi, s_pa = stable

    stable_ver = (s_ma, s_mi, s_pa)
    beta_base  = (b_ma, b_mi, b_pa)

    if stable_ver > beta_base:
        # Ryan is ahead — start fresh beta on stable version
        return f"v{s_ma}.{s_mi}.{s_pa}-beta"

    if stable_ver == beta_base:
        if build is None:
            # Beta is at e.g. v3.0.7-beta → suggest v3.0.7+1-beta
            return f"v{b_ma}.{b_mi}.{b_pa}+1-beta"
        else:
            # Beta is at e.g. v3.0.6+12-beta → suggest v3.0.6+13-beta
            return f"v{b_ma}.{b_mi}.{b_pa}+{build + 1}-beta"

    # Beta base is ahead of stable — just increment build
    next_build = (build or 0) + 1
    return f"v{b_ma}.{b_mi}.{b_pa}+{next_build}-beta"


async def _create_tag_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for the tag parameter of /create_tag."""
    async with aiohttp.ClientSession() as session:
        stable_tag, beta_tag = await asyncio.gather(
            _fetch_latest_release_tag(session, "RyanYuuki", "AnymeX"),
            _fetch_latest_release_tag(session, GITHUB_OWNER, GITHUB_REPO),
        )

    suggestion = _suggest_next_beta_tag(stable_tag, beta_tag)
    choices: list[app_commands.Choice[str]] = []

    if suggestion:
        label = suggestion
        if stable_tag or beta_tag:
            parts = []
            if stable_tag:
                parts.append(f"stable: {stable_tag}")
            if beta_tag:
                parts.append(f"beta: {beta_tag}")
            label = f"{suggestion}  ({', '.join(parts)})"
        choices.append(app_commands.Choice(name=label, value=suggestion))

    # If the user is typing something, also offer what they've typed so far
    if current and current != suggestion:
        choices.append(app_commands.Choice(name=current, value=current))

    return choices[:25]


@bot.tree.command(
    name="create_tag", description="Create a new Git tag on the beta branch"
)
@app_commands.describe(tag="Tag name — autocomplete will suggest the next beta version", message="Tag message (optional, defaults to tag name)")
@app_commands.autocomplete(tag=_create_tag_autocomplete)
@has_allowed_role()
async def create_tag(interaction: discord.Interaction, tag: str, message: str = ""):
    await interaction.response.defer()
    if not message:
        message = tag

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            status = r.status
            ref_data = await r.json()
        if status != 200:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Branch not found",
                    description=ref_data.get("message"),
                    color=0xDA3633,
                )
            )
            return

        sha = ref_data["object"]["sha"]
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/tags",
            headers=gh_headers(),
            json={"tag": tag, "message": message, "object": sha, "type": "commit"},
        ) as r:
            status = r.status
            tag_data = await r.json()
        if status not in (200, 201):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Tag creation failed",
                    description=tag_data.get("message"),
                    color=0xDA3633,
                )
            )
            return

        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs",
            headers=gh_headers(),
            json={"ref": f"refs/tags/{tag}", "sha": tag_data["sha"]},
        ) as r:
            status = r.status
            ref_result = await r.json()

    if status in (200, 201):
        embed = discord.Embed(title="🏷️ Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Branch", value=f"`{GITHUB_BRANCH}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        embed.add_field(name="Message", value=message, inline=False)
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
    else:
        embed = discord.Embed(
            title="❌ Ref creation failed",
            description=ref_result.get("message"),
            color=0xDA3633,
        )
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /delete_tag — Restricted
# ══════════════════════════════════════════════════════════════════════════════


async def _delete_tag_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /delete_tag — lists existing beta tags from the repo."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/tags?per_page=25",
                headers=gh_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return []
                tags = await r.json()
        except Exception:
            return []

    choices = []
    for t in tags:
        name = t.get("name", "")
        if not current or current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))

    if current and not any(c.value == current for c in choices):
        choices.append(app_commands.Choice(name=current, value=current))

    return choices[:25]


@bot.tree.command(name="delete_tag", description="Delete a Git tag, its release, and cancel any running build.yml")
@app_commands.describe(tag="Tag name to delete — autocomplete shows existing tags")
@app_commands.autocomplete(tag=_delete_tag_autocomplete)
@has_allowed_role()
async def delete_tag(interaction: discord.Interaction, tag: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs/tags/{tag}",
            headers=gh_headers(),
        ) as r:
            tag_status = r.status

        release_status = 404
        if tag_status in (200, 204):
            async with session.delete(
                f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag}",
                headers=gh_headers(),
            ) as r:
                release_status = r.status

        # Cancel any running build.yml on the beta branch
        # Tag creation auto-triggers build.yml via GitHub Actions on:push:tags
        cancel_status = None
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/build.yml/runs?per_page=5&branch={GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            if r.status == 200:
                runs_data = await r.json()
                for run in runs_data.get("workflow_runs", []):
                    if run.get("status") in ("in_progress", "queued", "waiting", "requested"):
                        run_id = run["id"]
                        async with session.post(
                            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs/{run_id}/cancel",
                            headers=gh_headers(),
                        ) as cr:
                            cancel_status = cr.status
                        break  # cancel the first active one

    if tag_status in (200, 204):
        embed = discord.Embed(title="🗑️ Beta Tag Deleted!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(
            name="Release",
            value="Deleted" if release_status in (200, 204) else "Not found",
            inline=True,
        )
        if cancel_status == 202:
            embed.add_field(name="Build", value="✅ Cancelled running build.yml", inline=False)
        else:
            embed.add_field(name="Build", value="No running build.yml found", inline=False)
    else:
        embed = discord.Embed(
            title="❌ Failed to Delete",
            description=f"Tag `{tag}` not found",
            color=0xDA3633,
        )

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /create_stable_tag + /delete_stable_tag — Stable release tagging (RyanYuuki/AnymeX)
# ══════════════════════════════════════════════════════════════════════════════

def _suggest_stable_tags(latest: str | None) -> list[tuple[str, str]]:
    """
    Given the latest stable tag (e.g. v3.0.9), return up to 4 suggestions:
      - major bump:  v(X+1).0.0
      - minor bump:  vX.(Y+1).0
      - patch bump:  vX.Y.(Z+1)
      - hotfix:      vX.Y.Z-hotfix
    Returns list of (value, label) tuples.
    """
    if not latest:
        return [("v1.0.0", "v1.0.0  (first release)")]

    parsed = _parse_stable_tag(latest)
    if not parsed:
        return []

    ma, mi, pa = parsed
    return [
        (f"v{ma+1}.0.0",        f"v{ma+1}.0.0  (major bump)"),
        (f"v{ma}.{mi+1}.0",     f"v{ma}.{mi+1}.0  (minor bump)"),
        (f"v{ma}.{mi}.{pa+1}",  f"v{ma}.{mi}.{pa+1}  (patch bump)"),
        (f"v{ma}.{mi}.{pa}-hotfix", f"v{ma}.{mi}.{pa}-hotfix  (hotfix)"),
    ]


async def _create_stable_tag_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /create_stable_tag — suggests major/minor/patch/hotfix."""
    async with aiohttp.ClientSession() as session:
        latest = await _fetch_latest_release_tag(session, STABLE_OWNER, STABLE_REPO)

    suggestions = _suggest_stable_tags(latest)
    choices: list[app_commands.Choice[str]] = []

    for value, label in suggestions:
        if not current or current.lower() in value.lower():
            choices.append(app_commands.Choice(name=label, value=value))

    # Always include what the user is typing if it doesn't match any suggestion
    if current and not any(s[0] == current for s in suggestions):
        choices.append(app_commands.Choice(name=current, value=current))

    return choices[:25]


@bot.tree.command(
    name="create_stable_tag", description="Create a new stable release tag on RyanYuuki/AnymeX"
)
@app_commands.describe(
    tag="Tag name — autocomplete suggests next version",
    message="Tag message (optional, defaults to tag name)",
)
@app_commands.autocomplete(tag=_create_stable_tag_autocomplete)
@has_allowed_role()
async def create_stable_tag(interaction: discord.Interaction, tag: str, message: str = ""):
    await interaction.response.defer()
    if not message:
        message = tag

    async with aiohttp.ClientSession() as session:
        # Get latest commit SHA on stable branch
        async with session.get(
            f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/git/ref/heads/{STABLE_BRANCH}",
            headers=gh_headers(),
        ) as r:
            status = r.status
            ref_data = await r.json()
        if status != 200:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Branch not found",
                    description=ref_data.get("message"),
                    color=0xDA3633,
                )
            )
            return

        sha = ref_data["object"]["sha"]

        # Create annotated tag object
        async with session.post(
            f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/git/tags",
            headers=gh_headers(),
            json={"tag": tag, "message": message, "object": sha, "type": "commit"},
        ) as r:
            status = r.status
            tag_data = await r.json()
        if status not in (200, 201):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Tag creation failed",
                    description=tag_data.get("message"),
                    color=0xDA3633,
                )
            )
            return

        # Create the ref pointing to the tag object
        async with session.post(
            f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/git/refs",
            headers=gh_headers(),
            json={"ref": f"refs/tags/{tag}", "sha": tag_data["sha"]},
        ) as r:
            status = r.status
            ref_result = await r.json()

    if status in (200, 201):
        embed = discord.Embed(title="🏷️ Stable Tag Created!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Repo", value=f"`{STABLE_OWNER}/{STABLE_REPO}`", inline=True)
        embed.add_field(name="Branch", value=f"`{STABLE_BRANCH}`", inline=True)
        embed.add_field(name="SHA", value=f"`{sha[:7]}`", inline=True)
        embed.add_field(name="Message", value=message, inline=False)
        embed.set_footer(text=f"Created by {interaction.user.display_name}")
    else:
        embed = discord.Embed(
            title="❌ Ref creation failed",
            description=ref_result.get("message"),
            color=0xDA3633,
        )
    await interaction.followup.send(embed=embed)


# ── Stable tag autocomplete for delete ────────────────────────────────────────

async def _delete_stable_tag_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /delete_stable_tag — lists recent stable tags."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/tags?per_page=10",
                headers=gh_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return []
                tags = await r.json()
        except Exception:
            return []

    choices = []
    for t in tags:
        name = t.get("name", "")
        if not current or current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))

    if current and not any(c.value == current for c in choices):
        choices.append(app_commands.Choice(name=current, value=current))

    return choices[:25]


@bot.tree.command(name="delete_stable_tag", description="Delete a stable Git tag, its release, and cancel any running build.yml")
@app_commands.describe(tag="Tag name to delete")
@app_commands.autocomplete(tag=_delete_stable_tag_autocomplete)
@has_allowed_role()
async def delete_stable_tag(interaction: discord.Interaction, tag: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/git/refs/tags/{tag}",
            headers=gh_headers(),
        ) as r:
            tag_status = r.status

        release_status = 404
        if tag_status in (200, 204):
            async with session.delete(
                f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/releases/tags/{tag}",
                headers=gh_headers(),
            ) as r:
                release_status = r.status

        # Cancel any running build.yml on the stable branch
        # Tag creation auto-triggers build.yml via GitHub Actions on:push:tags
        cancel_status = None
        async with session.get(
            f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/actions/workflows/build.yml/runs?per_page=5&branch={STABLE_BRANCH}",
            headers=gh_headers(),
        ) as r:
            if r.status == 200:
                runs_data = await r.json()
                for run in runs_data.get("workflow_runs", []):
                    if run.get("status") in ("in_progress", "queued", "waiting", "requested"):
                        run_id = run["id"]
                        async with session.post(
                            f"{GITHUB_API}/repos/{STABLE_OWNER}/{STABLE_REPO}/actions/runs/{run_id}/cancel",
                            headers=gh_headers(),
                        ) as cr:
                            cancel_status = cr.status
                        break  # cancel the first active one

    if tag_status in (200, 204):
        embed = discord.Embed(title="🗑️ Stable Tag Deleted!", color=0x2EA043)
        embed.add_field(name="Tag", value=f"`{tag}`", inline=True)
        embed.add_field(name="Repo", value=f"`{STABLE_OWNER}/{STABLE_REPO}`", inline=True)
        embed.add_field(
            name="Release",
            value="Deleted" if release_status in (200, 204) else "Not found",
            inline=True,
        )
        if cancel_status == 202:
            embed.add_field(name="Build", value="✅ Cancelled running build.yml", inline=False)
        else:
            embed.add_field(name="Build", value="No running build.yml found", inline=False)
    else:
        embed = discord.Embed(
            title="❌ Failed to Delete",
            description=f"Tag `{tag}` not found in `{STABLE_OWNER}/{STABLE_REPO}`",
            color=0xDA3633,
        )

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /latest_run — Restricted (only beta_manual.yml)
# ══════════════════════════════════════════════════════════════════════════════


@bot.tree.command(
    name="latest_run",
    description="Check the latest beta_manual.yml run and cancel if running",
)
@has_allowed_role()
async def latest_run(interaction: discord.Interaction):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/beta_manual.yml/runs?per_page=1&branch={GITHUB_BRANCH}",
            headers=gh_headers(),
        ) as r:
            if r.status != 200:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Error fetching runs", color=0xDA3633)
                )
                return
            data = await r.json()

    if not data.get("workflow_runs"):
        await interaction.followup.send(
            embed=discord.Embed(title="❌ No runs found", color=0xDA3633)
        )
        return

    run = data["workflow_runs"][0]
    run_id = run["id"]
    conclusion = run.get("conclusion") or "in_progress"

    EMOJI_MAP = {
        "success": "✅",
        "failure": "❌",
        "cancelled": "🚫",
        "in_progress": "⏳",
    }
    emoji = EMOJI_MAP.get(conclusion, "❓")
    color = (
        0x2EA043
        if conclusion == "success"
        else (0xDA3633 if conclusion == "failure" else 0xFFA500)
    )

    embed = discord.Embed(title=f"{emoji} {run['name']}", color=color)
    embed.add_field(name="Status", value=f"`{conclusion}`", inline=True)
    embed.add_field(name="Branch", value=f"`{run['head_branch']}`", inline=True)
    embed.add_field(name="Run #", value=f"`{run['run_number']}`", inline=True)
    embed.add_field(name="Link", value=f"[View Run]({run['html_url']})", inline=False)

    # Add cancel button if still running
    if conclusion == "in_progress":
        embed.description = "Running - click button to cancel"
        embed.set_footer(text=f"Run ID: {run_id}")

        view = CancelBuildView(run_id, label="Cancel Run")
        msg = await interaction.followup.send(embed=embed, view=view)
        bot.add_view(view, message_id=msg.id)
    else:
        await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# PREFIX COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


def is_admin(ctx):
    return ctx.author.guild_permissions.administrator


# ── ?help ─────────────────────────────────────────────────────────────────────


@bot.command(name="help")
async def prefix_help(ctx, command_name: str = None):
    prefixes = _prefix_cache
    p = prefixes[0] if prefixes else "?"

    if command_name:
        help_map = {
            "link_anilist": f"`{p}link_anilist <username>` — (Slash only) Link your AniList account via OAuth.",
            "link_mal": f"`{p}link_mal <username>` — (Slash only) Link your MAL account via OAuth.",
            "link_simkl": f"`{p}link_simkl` — (Slash only) Link your Simkl account via OAuth.",
            "myprofile": f"`{p}myprofile`\nView your saved profile.",
            "setprefix": f"`{p}setprefix add <prefix>` — Add a prefix\n`{p}setprefix remove <prefix>` — Remove a prefix\n`{p}setprefix list` — Show active prefixes\n*(Admin only)*",
        }
        info = help_map.get(command_name.lower())
        if info:
            embed = discord.Embed(
                title=f"📖 Help: {command_name}", description=info, color=0x0066FF
            )
        else:
            embed = discord.Embed(
                title="❌ Unknown command",
                description=f"No help found for `{command_name}`.",
                color=0xDA3633,
            )
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="📖 AnymeX-Preview Bot",
        description=f"Active prefixes: `{'`, `'.join(prefixes)}`\nUse `{p}help <command>` for details.\nAll features are available via **slash commands** (`/`).",
        color=0x0066FF,
    )
    embed.add_field(name="👤 Profile", value="`/myprofile` `/link_anilist` `/link_mal` `/link_simkl`", inline=False)
    embed.add_field(
        name="🎬 Community Recommendations",
        value="`/add_anime` `/add_manga` `/add_show` `/add_movie` `/list_anime` `/list_manga` `/list_shows` `/list_movies` `/remove_anime` `/remove_manga` `/remove_show` `/remove_movie` `/vote_anime` `/vote_manga` `/vote_show` `/vote_movie` `/edit_reason` `/delete_entry` `/delete_reason`",
        inline=False,
    )
    embed.add_field(
        name="🔨 Build / GitHub",
        value="`/build` `/create_tag` `/delete_tag` `/latest_run`",
        inline=False,
    )
    embed.add_field(
        name="🔍 Search",
        value="`/anime_search` `/manga_search` `/show_search` `/movie_search` `/anilist_profile` `/character_search` `/staff_search` `/airing_schedule` `/seasonal_anime`",
        inline=False,
    )
    embed.add_field(name="⚙️ Admin", value=f"`{p}setprefix` `/admin_add` `/admin_remove` `/admin_list`", inline=False)
    await ctx.send(embed=embed)


# ── ?setprefix ────────────────────────────────────────────────────────────────


@bot.command(name="setprefix")
async def prefix_setprefix(ctx, action: str = None, new_prefix: str = None):
    if not is_admin(ctx):
        await ctx.send(embed=discord.Embed(title="❌ Admin only", color=0xDA3633))
        return

    if action is None or action.lower() not in ("add", "remove", "list"):
        await ctx.send(
            embed=discord.Embed(
                title="Usage",
                description=f"`{_prefix_cache[0]}setprefix add <prefix>`\n`{_prefix_cache[0]}setprefix remove <prefix>`\n`{_prefix_cache[0]}setprefix list`",
                color=0x0066FF,
            )
        )
        return

    async with aiohttp.ClientSession() as session:
        prefixes, sha = await github_read_json(session, FILE_PREFIXES)
        if not isinstance(prefixes, list):
            prefixes = DEFAULT_PREFIXES[:]

        if action.lower() == "list":
            await ctx.send(
                embed=discord.Embed(
                    title="⚙️ Active Prefixes",
                    description="\n".join(f"`{p}`" for p in prefixes),
                    color=0x0066FF,
                )
            )
            return

        if not new_prefix:
            await ctx.send("❌ Please provide a prefix.")
            return

        if action.lower() == "add":
            if new_prefix in prefixes:
                await ctx.send(
                    embed=discord.Embed(
                        title="⚠️ Already exists",
                        description=f"`{new_prefix}` is already a prefix.",
                        color=0xFFA500,
                    )
                )
                return
            if len(new_prefix) > 5:
                await ctx.send("❌ Prefix must be 5 characters or less.")
                return
            prefixes.append(new_prefix)
            ok = await github_write_json(
                session, FILE_PREFIXES, prefixes, sha, f"Add prefix: {new_prefix}"
            )
            if ok:
                _prefix_cache[:] = prefixes
                await ctx.send(
                    embed=discord.Embed(
                        title="✅ Prefix Added",
                        description=f"Added `{new_prefix}`\nActive: {', '.join(f'`{p}`' for p in prefixes)}",
                        color=0x2EA043,
                    )
                )
            else:
                await ctx.send(
                    embed=discord.Embed(title="❌ Failed to save", color=0xDA3633)
                )

        elif action.lower() == "remove":
            if new_prefix not in prefixes:
                await ctx.send(
                    embed=discord.Embed(
                        title="❌ Not found",
                        description=f"`{new_prefix}` is not an active prefix.",
                        color=0xDA3633,
                    )
                )
                return
            if len(prefixes) == 1:
                await ctx.send(
                    "❌ Can't remove the last prefix — add another one first."
                )
                return
            prefixes.remove(new_prefix)
            ok = await github_write_json(
                session, FILE_PREFIXES, prefixes, sha, f"Remove prefix: {new_prefix}"
            )
            if ok:
                _prefix_cache[:] = prefixes
                await ctx.send(
                    embed=discord.Embed(
                        title="✅ Prefix Removed",
                        description=f"Removed `{new_prefix}`\nActive: {', '.join(f'`{p}`' for p in prefixes)}",
                        color=0x2EA043,
                    )
                )
            else:
                await ctx.send(
                    embed=discord.Embed(title="❌ Failed to save", color=0xDA3633)
                )


# ANILIST INTEGRATION (SLASH)
# ══════════════════════════════════════════════════════════════════════════════


async def _anilist_query(
    session: aiohttp.ClientSession, query: str, variables: dict
) -> dict:
    async with session.post(
        ANILIST_API,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
    ) as r:
        if r.status != 200:
            return {}
        return (await r.json()).get("data", {})


ANILIST_SEARCH_QUERY = """
query ($search: String, $type: MediaType) {
  Media(search: $search, type: $type, sort: POPULARITY_DESC) {
    id title { romaji english native }
    coverImage { large }
    averageScore status episodes chapters
    genres description(asHtml: false)
    siteUrl startDate { year month day }
  }
}
"""
ANILIST_CHARACTER_QUERY = """
query ($search: String) {
  Character(search: $search) {
    id name { full native }
    image { large }
    description(asHtml: false)
    siteUrl
    media(perPage: 3) { nodes { title { romaji } siteUrl } }
  }
}
"""
ANILIST_STAFF_QUERY = """
query ($search: String) {
  Staff(search: $search) {
    id name { full native }
    image { large }
    description(asHtml: false)
    siteUrl primaryOccupations
  }
}
"""
ANILIST_SCHEDULE_QUERY = """
query ($page: Int) {
  Page(page: $page, perPage: 10) {
    airingSchedules(notYetAired: true, sort: TIME) {
      airingAt episode
      media { title { romaji } siteUrl }
    }
  }
}
"""
ANILIST_SEASON_QUERY = """
query ($season: MediaSeason, $year: Int) {
  Page(perPage: 10) {
    media(season: $season, seasonYear: $year, sort: POPULARITY_DESC, type: ANIME) {
      title { romaji }
      averageScore episodes status
      genres siteUrl
      coverImage { large }
    }
  }
}
"""
ANILIST_USER_QUERY = """
query ($name: String) {
  User(name: $name) {
    id name avatar { large }
    siteUrl
    statistics { anime { count meanScore minutesWatched } manga { count chaptersRead } }
  }
}
"""


@bot.tree.command(name="anime_search", description="Search for an anime on AniList")
@app_commands.describe(title="Anime title to search")
async def anime_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(
            session, ANILIST_SEARCH_QUERY, {"search": title, "type": "ANIME"}
        )
    media = data.get("Media")
    if not media:
        await interaction.followup.send("❌ Anime not found.")
        return
    t = media["title"]
    embed = discord.Embed(
        title=t.get("english") or t.get("romaji") or "Unknown",
        url=media.get("siteUrl", ""),
        color=0x0066FF,
    )
    embed.add_field(name="Romaji", value=t.get("romaji", "—"), inline=True)
    embed.add_field(
        name="Score", value=f"{media.get('averageScore','N/A')}/100", inline=True
    )
    embed.add_field(name="Status", value=media.get("status", "—"), inline=True)
    embed.add_field(name="Episodes", value=str(media.get("episodes", "?")), inline=True)
    embed.add_field(
        name="Genres", value=", ".join(media.get("genres", [])[:4]) or "—", inline=True
    )
    desc = (media.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Description", value=desc, inline=False)
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="manga_search", description="Search for a manga on AniList")
@app_commands.describe(title="Manga title to search")
async def manga_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(
            session, ANILIST_SEARCH_QUERY, {"search": title, "type": "MANGA"}
        )
    media = data.get("Media")
    if not media:
        await interaction.followup.send("❌ Manga not found.")
        return
    t = media["title"]
    embed = discord.Embed(
        title=t.get("english") or t.get("romaji") or "Unknown",
        url=media.get("siteUrl", ""),
        color=0xFF6B6B,
    )
    embed.add_field(
        name="Score", value=f"{media.get('averageScore','N/A')}/100", inline=True
    )
    embed.add_field(name="Chapters", value=str(media.get("chapters", "?")), inline=True)
    embed.add_field(name="Status", value=media.get("status", "—"), inline=True)
    embed.add_field(
        name="Genres", value=", ".join(media.get("genres", [])[:4]) or "—", inline=True
    )
    desc = (media.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Description", value=desc, inline=False)
    if media.get("coverImage", {}).get("large"):
        embed.set_thumbnail(url=media["coverImage"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="show_search", description="Search for a TV show on Simkl")
@app_commands.describe(title="TV show title to search")
@app_commands.autocomplete(title=show_autocomplete)
async def show_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    # If selected from autocomplete, title is the simkl_id — fetch details directly
    if title.isdigit():
        media = await _simkl_fetch_show(int(title))
        if not media:
            await interaction.followup.send("❌ Could not fetch show details from Simkl.", ephemeral=True)
            return
        embed = _build_simkl_embed(media, "show")
        await interaction.followup.send(embed=embed)
        return
    # Free-text search — return top results as a list
    results = await _simkl_search_tv(title)
    if not results:
        await interaction.followup.send("❌ No TV shows found on Simkl.", ephemeral=True)
        return
    embed = discord.Embed(title=f"🔍 Simkl TV Show Results: {title}", color=0x9B59B6)
    for r in results[:8]:
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        show_title = r.get("title", "Unknown")
        year = r.get("year", "")
        url = f"https://simkl.com/tv/{simkl_id}" if simkl_id else ""
        score = r.get("ratings", {}).get("simkl", {}).get("rating", "N/A")
        genres = ", ".join(r.get("genres", [])[:3]) or "—"
        val = f"Year: {year} | Score: {score} | {genres}"
        if url:
            val += f"\n[Simkl]({url})"
        embed.add_field(name=show_title, value=val, inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="movie_search", description="Search for a movie on Simkl")
@app_commands.describe(title="Movie title to search")
@app_commands.autocomplete(title=movie_autocomplete)
async def movie_search(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    # If selected from autocomplete, title is the simkl_id — fetch details directly
    if title.isdigit():
        media = await _simkl_fetch_movie(int(title))
        if not media:
            await interaction.followup.send("❌ Could not fetch movie details from Simkl.", ephemeral=True)
            return
        embed = _build_simkl_embed(media, "movie")
        await interaction.followup.send(embed=embed)
        return
    # Free-text search — return top results as a list
    results = await _simkl_search_movies(title)
    if not results:
        await interaction.followup.send("❌ No movies found on Simkl.", ephemeral=True)
        return
    embed = discord.Embed(title=f"🔍 Simkl Movie Results: {title}", color=0xE67E22)
    for r in results[:8]:
        ids = r.get("ids", {})
        simkl_id = ids.get("simkl_id") or ids.get("simkl") or r.get("simkl_id") or r.get("id")
        movie_title = r.get("title", "Unknown")
        year = r.get("year", "")
        url = f"https://simkl.com/movies/{simkl_id}" if simkl_id else ""
        score = r.get("ratings", {}).get("simkl", {}).get("rating", "N/A")
        genres = ", ".join(r.get("genres", [])[:3]) or "—"
        val = f"Year: {year} | Score: {score} | {genres}"
        if url:
            val += f"\n[Simkl]({url})"
        embed.add_field(name=movie_title, value=val, inline=False)
    await interaction.followup.send(embed=embed)


def _build_simkl_embed(media: dict, media_type: str) -> discord.Embed:
    """Build a rich embed for a single Simkl show or movie."""
    title = media.get("title") or media.get("en_title") or "Unknown"
    ids = media.get("ids", {})
    simkl_id = ids.get("simkl_id") or ids.get("simkl") or media.get("simkl_id") or media.get("id")
    url = f"https://simkl.com/{media_type}s/{simkl_id}" if simkl_id else ""
    color = 0x9B59B6 if media_type == "show" else 0xE67E22

    embed = discord.Embed(title=title, url=url, color=color)
    year = media.get("year", "")
    if year:
        embed.add_field(name="Year", value=str(year), inline=True)
    score = media.get("ratings", {}).get("simkl", {}).get("rating", "N/A")
    embed.add_field(name="Score", value=str(score), inline=True)
    status = media.get("status", "")
    if status:
        embed.add_field(name="Status", value=status.replace("_", " ").title(), inline=True)
    if media_type == "show":
        ep_count = media.get("total_episodes") or media.get("ep_count", "")
        if ep_count:
            embed.add_field(name="Episodes", value=str(ep_count), inline=True)
        runtime = media.get("runtime", "")
        if runtime:
            embed.add_field(name="Runtime", value=f"{runtime} min/ep", inline=True)
    else:
        runtime = media.get("runtime", "")
        if runtime:
            embed.add_field(name="Runtime", value=f"{runtime} min", inline=True)
    genres = ", ".join(media.get("genres", [])[:5]) or "—"
    embed.add_field(name="Genres", value=genres, inline=False)
    overview = (media.get("overview") or media.get("description") or "")[:512]
    if overview:
        embed.add_field(name="Overview", value=overview, inline=False)
    poster = _simkl_poster(media)
    if poster:
        embed.set_thumbnail(url=poster)
    return embed



@app_commands.describe(username="AniList username")
async def anilist_profile(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_USER_QUERY, {"name": username})
    user = data.get("User")
    if not user:
        await interaction.followup.send("❌ AniList user not found.")
        return
    stats = user.get("statistics", {})
    a, m = stats.get("anime", {}), stats.get("manga", {})
    embed = discord.Embed(
        title=user["name"], url=user.get("siteUrl", ""), color=0x0066FF
    )
    embed.add_field(name="Anime Watched", value=str(a.get("count", 0)), inline=True)
    embed.add_field(name="Mean Score", value=str(a.get("meanScore", "—")), inline=True)
    embed.add_field(
        name="Days Watched",
        value=f"{round(a.get('minutesWatched',0)/1440,1)}d",
        inline=True,
    )
    embed.add_field(name="Manga Read", value=str(m.get("count", 0)), inline=True)
    embed.add_field(
        name="Chapters Read", value=str(m.get("chaptersRead", 0)), inline=True
    )
    if user.get("avatar", {}).get("large"):
        embed.set_thumbnail(url=user["avatar"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="character_search",
    description="Search for an anime/manga character on AniList",
)
@app_commands.describe(name="Character name")
async def character_search(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_CHARACTER_QUERY, {"search": name})
    char = data.get("Character")
    if not char:
        await interaction.followup.send("❌ Character not found.")
        return
    cn = char["name"]
    embed = discord.Embed(
        title=cn.get("full", "—"), url=char.get("siteUrl", ""), color=0x0066FF
    )
    if cn.get("native"):
        embed.add_field(name="Native", value=cn["native"], inline=True)
    appeared_in = [n["title"]["romaji"] for n in char.get("media", {}).get("nodes", [])]
    if appeared_in:
        embed.add_field(name="Appears In", value="\n".join(appeared_in), inline=False)
    desc = (char.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Description", value=desc, inline=False)
    if char.get("image", {}).get("large"):
        embed.set_thumbnail(url=char["image"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="staff_search", description="Search for anime staff on AniList")
@app_commands.describe(name="Staff member name")
async def staff_search(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_STAFF_QUERY, {"search": name})
    staff = data.get("Staff")
    if not staff:
        await interaction.followup.send("❌ Staff not found.")
        return
    sn = staff["name"]
    embed = discord.Embed(
        title=sn.get("full", "—"), url=staff.get("siteUrl", ""), color=0x0066FF
    )
    if sn.get("native"):
        embed.add_field(name="Native", value=sn["native"], inline=True)
    if staff.get("primaryOccupations"):
        embed.add_field(
            name="Occupations",
            value=", ".join(staff["primaryOccupations"]),
            inline=True,
        )
    desc = (staff.get("description") or "").replace("<br>", " ")[:512]
    if desc:
        embed.add_field(name="Bio", value=desc, inline=False)
    if staff.get("image", {}).get("large"):
        embed.set_thumbnail(url=staff["image"]["large"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="airing_schedule", description="View upcoming airing anime schedule"
)
async def airing_schedule(interaction: discord.Interaction):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(session, ANILIST_SCHEDULE_QUERY, {"page": 1})
    schedules = data.get("Page", {}).get("airingSchedules", [])
    if not schedules:
        await interaction.followup.send("❌ No upcoming episodes found.")
        return
    from datetime import datetime, timezone

    embed = discord.Embed(title="📅 Upcoming Airing Schedule", color=0x0066FF)
    for s in schedules[:10]:
        dt = datetime.fromtimestamp(s["airingAt"], tz=timezone.utc)
        media = s.get("media", {})
        title = media.get("title", {}).get("romaji", "Unknown")
        embed.add_field(
            name=f"Ep {s['episode']} — {title}",
            value=f"<t:{s['airingAt']}:R>",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="seasonal_anime", description="View seasonal anime list")
@app_commands.describe(
    season="Season (WINTER/SPRING/SUMMER/FALL)", year="Year (e.g. 2025)"
)
@app_commands.choices(
    season=[
        app_commands.Choice(name="Winter", value="WINTER"),
        app_commands.Choice(name="Spring", value="SPRING"),
        app_commands.Choice(name="Summer", value="SUMMER"),
        app_commands.Choice(name="Fall", value="FALL"),
    ]
)
async def seasonal_anime(
    interaction: discord.Interaction, season: app_commands.Choice[str], year: int
):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        data = await _anilist_query(
            session, ANILIST_SEASON_QUERY, {"season": season.value, "year": year}
        )
    shows = data.get("Page", {}).get("media", [])
    if not shows:
        await interaction.followup.send("❌ No anime found for that season.")
        return
    embed = discord.Embed(title=f"🌸 {season.name} {year} Anime", color=0x0066FF)
    for s in shows:
        t = s["title"]["romaji"]
        score = s.get("averageScore", "?")
        eps = s.get("episodes", "?")
        embed.add_field(name=t, value=f"Score: {score}/100 | Eps: {eps}", inline=False)
    await interaction.followup.send(embed=embed)



# ══════════════════════════════════════════════════════════════════════════════
# Profile Repopulator — refreshes user info in users.json, all entry JSONs (anime, manga, shows, movies)
# ══════════════════════════════════════════════════════════════════════════════

# Channel ID to post weekly/startup repopulator reports (set via env var)
REPOPULATOR_CHANNEL_ID = int(os.environ.get("REPOPULATOR_CHANNEL_ID", 0))


async def _maybe_run_repopulator(session: aiohttp.ClientSession, triggered_by: str = "system") -> bool:
    """
    Run the repopulator only if 7 days have passed since the last run.
    Reads/writes last_repopulated.json in the private repo.
    Returns True if it ran, False if skipped.
    """
    SEVEN_DAYS = 7 * 24 * 3600

    # Read last run time from private repo
    try:
        data, sha = await github_read_json(session, FILE_LAST_REPOPULATED, repo=USERDATA_REPO, branch=USERDATA_BRANCH)
        last_run = data.get("last_run", 0) if isinstance(data, dict) else 0
    except Exception:
        last_run = 0
        sha = None

    now = time.time()
    elapsed = now - last_run
    if elapsed < SEVEN_DAYS:
        remaining_hours = (SEVEN_DAYS - elapsed) / 3600
        print(f"ℹ️ Repopulator skipped — last run {elapsed/3600:.1f}h ago, next run in {remaining_hours:.1f}h")
        return False

    # 7 days passed — run it
    print(f"🔄 Repopulator running ({triggered_by}) — last run {elapsed/3600:.1f}h ago")
    result = await run_repopulator(triggered_by=triggered_by)
    print(f"✅ Repopulator done: {result}")

    # Save current time
    try:
        payload = {"last_run": now, "triggered_by": triggered_by}
        await github_write_json(
            session, FILE_LAST_REPOPULATED, payload, sha,
            f"chore: update last_repopulated ({triggered_by})",
            repo=USERDATA_REPO, branch=USERDATA_BRANCH,
        )
    except Exception as e:
        print(f"⚠️ Failed to save last_repopulated.json: {e}")

    # Post result to repopulator channel
    channel = bot.get_channel(REPOPULATOR_CHANNEL_ID)
    if channel:
        try:
            embed = _build_repopulator_embed(result, "🔄 Profile Sync Complete")
            await channel.send(embed=embed)
        except Exception:
            pass

    return True


async def run_repopulator(triggered_by: str = "system") -> dict:
    """
    Re-fetches every user's AniList + MAL + Simkl profile and updates:
      - users.json             (full profile refresh)
      - admins.json            (sync service IDs from users.json)
      - community_anime.json  (user snapshots, poster, score, nsfw, format migration)
      - community_manga.json  (same)
      - community_shows.json  (same)
      - community_movies.json (same)

    Returns a result dict with counts for reporting.
    """
    result = {
        "users_updated": 0,
        "users_skipped": 0,
        "users_failed": 0,
        "admins_updated": 0,
        "anime_entries_updated": 0,
        "manga_entries_updated": 0,
        "show_entries_updated": 0,
        "movie_entries_updated": 0,
        "triggered_by": triggered_by,
    }

    async with aiohttp.ClientSession() as session:
        # ── Step 1: Load all data at once ─────────────────────────────────────
        users, users_sha = await read_users(session)
        anime_entries, anime_sha = await github_read_json(session, FILE_ANIME)
        manga_entries, manga_sha = await github_read_json(session, FILE_MANGA)
        show_entries, show_sha = await github_read_json(session, FILE_SHOWS)
        movie_entries, movie_sha = await github_read_json(session, FILE_MOVIES)

        if not users:
            result["note"] = "No users found in users.json — nothing to repopulate."
            return result

        # ── Step 2: Refresh each user's profile ───────────────────────────────
        # Build a lookup: anilist_user_id → refreshed profile data
        # and:            mal_user_id     → refreshed profile data
        al_id_to_profile: dict[int, dict] = {}
        mal_id_to_profile: dict[int, dict] = {}
        simkl_uname_to_profile: dict[str, dict] = {}

        for discord_id, profile in users.items():
            al_id = profile.get("anilist_user_id")
            mal_uname = profile.get("mal_username")
            refreshed = False

            # -- AniList refresh --
            if al_id:
                try:
                    al_data = await _anilist_fetch_user_by_id(al_id)
                    if al_data:
                        profile["anilist_username"] = al_data.get("name")
                        profile["anilist_url"] = al_data.get("siteUrl")
                        profile["anilist_avatar"] = (al_data.get("avatar") or {}).get("large")
                        profile["anilist_banner"] = al_data.get("bannerImage")
                        profile["anilist_about"] = (al_data.get("about") or "")[:300]
                        stats = al_data.get("statistics") or {}
                        a_stats = stats.get("anime") or {}
                        m_stats = stats.get("manga") or {}
                        profile["anilist_anime_count"] = a_stats.get("count")
                        profile["anilist_manga_count"] = m_stats.get("count")
                        profile["anilist_mean_score"] = a_stats.get("meanScore")
                        profile["anilist_minutes_watched"] = a_stats.get("minutesWatched")
                        profile["anilist_chapters_read"] = m_stats.get("chaptersRead")
                        al_id_to_profile[al_id] = profile
                        refreshed = True
                    else:
                        # Account gone — keep old data, still register lookup
                        if al_id:
                            al_id_to_profile[al_id] = profile
                except Exception:
                    if al_id:
                        al_id_to_profile[al_id] = profile

            # -- MAL refresh --
            mal_id = profile.get("mal_user_id")
            if mal_id:
                # If username is missing, resolve it from the ID first
                if not mal_uname:
                    mal_uname = await _mal_fetch_username_by_id(mal_id)
                    if mal_uname:
                        profile["mal_username"] = mal_uname
                try:
                    mal_data = await _mal_fetch_full_profile(mal_uname) if mal_uname else None
                    if mal_data:
                        profile["mal_username"] = mal_data.get("username", mal_uname)
                        profile["mal_url"] = mal_data.get("url")
                        profile["mal_avatar"] = mal_data.get("image_url")
                        profile["mal_about"] = mal_data.get("about")
                        a = mal_data.get("anime_stats") or {}
                        m = mal_data.get("manga_stats") or {}
                        profile["mal_anime_completed"] = a.get("completed")
                        profile["mal_anime_mean_score"] = a.get("mean_score")
                        profile["mal_manga_completed"] = m.get("completed")
                        profile["mal_manga_mean_score"] = m.get("mean_score")
                        mal_id_to_profile[mal_id] = profile
                        refreshed = True
                    else:
                        if mal_id:
                            mal_id_to_profile[mal_id] = profile
                except Exception:
                    if mal_id:
                        mal_id_to_profile[mal_id] = profile

            # -- Simkl refresh --
            simkl_token_enc = profile.get("simkl_token")
            simkl_uname = profile.get("simkl_username")
            if simkl_token_enc:
                try:
                    access_token = _simkl_decrypt_token(simkl_token_enc)
                    if access_token:
                        simkl_data = await _simkl_fetch_user_with_token(access_token)
                        if simkl_data:
                            profile["simkl_username"] = simkl_data["username"]
                            profile["simkl_user_id"] = simkl_data["user_id"]
                            profile["simkl_avatar"] = simkl_data["avatar_url"]
                            refreshed = True
                            if simkl_data["username"]:
                                simkl_uname_to_profile[simkl_data["username"].lower()] = profile
                        else:
                            print(f"[Repopulator] Simkl token fetch failed for discord_id={discord_id}")
                            if simkl_uname:
                                simkl_uname_to_profile[simkl_uname.lower()] = profile
                    else:
                        print(f"[Repopulator] Simkl token decrypt failed for discord_id={discord_id}")
                        if simkl_uname:
                            simkl_uname_to_profile[simkl_uname.lower()] = profile
                except Exception as e:
                    print(f"[Repopulator] Simkl exception for discord_id={discord_id}: {e}")
                    if simkl_uname:
                        simkl_uname_to_profile[simkl_uname.lower()] = profile
            elif simkl_uname:
                # No token yet (old profile before OAuth) — still register for entry matching
                simkl_uname_to_profile[simkl_uname.lower()] = profile

            if refreshed:
                result["users_updated"] += 1
            else:
                result["users_skipped"] += 1

            users[discord_id] = profile

        # ── Helper: match a user snapshot by any service ID ───────────────────
        admins, admins_sha = await read_admins(session)

        def _match_profile(u: dict):
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")
            if al_uid and al_uid in al_id_to_profile:
                return al_id_to_profile[al_uid]
            if mal_uid and mal_uid in mal_id_to_profile:
                return mal_id_to_profile[mal_uid]
            if simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                return simkl_uname_to_profile[simkl_uname.lower()]
            return None

        # ── Step 3: Update anime entries ──────────────────────────────────────
        anime_ids = [e["anilist_id"] for e in anime_entries]
        anime_media_map = await fetch_anilist_batch(session, anime_ids, "ANIME")

        for entry in anime_entries:
            changed = False

            # Migrate legacy single-reason entries into reasons[] array
            if "reasons" not in entry:
                first = {
                    "discord_id": entry.get("added_by_discord_id"),
                    "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
                    "user": entry.get("user", {}),
                    "author": entry.get("author"),
                    "text": entry.get("reason", ""),
                    "added_at": None,
                }
                entry["reasons"] = [first]
                changed = True

            # Update top-level user snapshot
            matched = _match_profile(entry.get("user", {}))
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                changed = True

            # Update per-reason user snapshots inside reasons[]
            for reason in entry.get("reasons", []):
                r_user = reason.get("user", {})
                r_matched = _match_profile(r_user)
                if r_matched:
                    reason["user"] = _build_user_snapshot(r_matched)
                    _mark_admin_flag(reason["user"], admins)
                    changed = True

            media = anime_media_map.get(entry["anilist_id"])
            if media:
                entry["poster"] = media.get("coverImage", {}).get("large")
                entry["score"] = media.get("averageScore")
                entry["nsfw"] = media.get("isAdult", False)
                changed = True
            else:
                print(f"⚠️ AniList returned no data for anime {entry['anilist_id']} ({entry.get('title')})")

            if changed:
                result["anime_entries_updated"] += 1

        # ── Step 4: Update manga entries ──────────────────────────────────────
        manga_ids = [e["anilist_id"] for e in manga_entries]
        manga_media_map = await fetch_anilist_batch(session, manga_ids, "MANGA")

        for entry in manga_entries:
            changed = False

            # Migrate legacy single-reason entries into reasons[] array
            if "reasons" not in entry:
                first = {
                    "discord_id": entry.get("added_by_discord_id"),
                    "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
                    "user": entry.get("user", {}),
                    "author": entry.get("author"),
                    "text": entry.get("reason", ""),
                    "added_at": None,
                }
                entry["reasons"] = [first]
                changed = True

            matched = _match_profile(entry.get("user", {}))
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                changed = True

            for reason in entry.get("reasons", []):
                r_user = reason.get("user", {})
                r_matched = _match_profile(r_user)
                if r_matched:
                    reason["user"] = _build_user_snapshot(r_matched)
                    _mark_admin_flag(reason["user"], admins)
                    changed = True

            media = manga_media_map.get(entry["anilist_id"])
            if media:
                entry["poster"] = media.get("coverImage", {}).get("large")
                entry["score"] = media.get("averageScore")
                entry["nsfw"] = media.get("isAdult", False)
                changed = True
            else:
                print(f"⚠️ AniList returned no data for manga {entry['anilist_id']} ({entry.get('title')})")

            if changed:
                result["manga_entries_updated"] += 1

        # ── Step 4b: Update show entries ──────────────────────────────────────
        _adult_certs = {"NC-17", "X", "TV-MA", "R18", "18+", "AO"}
        for entry in show_entries:
            changed = False

            # Migrate legacy single-reason entries into reasons[] array
            if "reasons" not in entry:
                first = {
                    "discord_id": entry.get("added_by_discord_id"),
                    "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
                    "user": entry.get("user", {}),
                    "author": entry.get("author"),
                    "text": entry.get("reason", ""),
                    "added_at": None,
                }
                entry["reasons"] = [first]
                changed = True

            matched = _match_profile(entry.get("user", {}))
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                changed = True

            for reason in entry.get("reasons", []):
                r_user = reason.get("user", {})
                r_matched = _match_profile(r_user)
                if r_matched:
                    reason["user"] = _build_user_snapshot(r_matched)
                    _mark_admin_flag(reason["user"], admins)
                    changed = True

            simkl_id = entry.get("simkl_id")
            if simkl_id:
                media = await _simkl_fetch_show(simkl_id)
                if media:
                    certification = (media.get("certification") or "").upper().strip()
                    entry["nsfw"] = certification in _adult_certs
                    entry["poster"] = _simkl_poster(media) or entry.get("poster", "")
                    entry["score"] = media.get("ratings", {}).get("simkl", {}).get("rating") or entry.get("score", "N/A")
                    changed = True
                else:
                    print(f"⚠️ Simkl returned no data for show {simkl_id} ({entry.get('title')})")

            if changed:
                result["show_entries_updated"] += 1

        # ── Step 4c: Update movie entries ─────────────────────────────────────
        for entry in movie_entries:
            changed = False

            # Migrate legacy single-reason entries into reasons[] array
            if "reasons" not in entry:
                first = {
                    "discord_id": entry.get("added_by_discord_id"),
                    "discord_username": entry.get("user", {}).get("discord", {}).get("username"),
                    "user": entry.get("user", {}),
                    "author": entry.get("author"),
                    "text": entry.get("reason", ""),
                    "added_at": None,
                }
                entry["reasons"] = [first]
                changed = True

            matched = _match_profile(entry.get("user", {}))
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                changed = True

            for reason in entry.get("reasons", []):
                r_user = reason.get("user", {})
                r_matched = _match_profile(r_user)
                if r_matched:
                    reason["user"] = _build_user_snapshot(r_matched)
                    _mark_admin_flag(reason["user"], admins)
                    changed = True

            simkl_id = entry.get("simkl_id")
            if simkl_id:
                media = await _simkl_fetch_movie(simkl_id)
                if media:
                    certification = (media.get("certification") or "").upper().strip()
                    entry["nsfw"] = certification in _adult_certs
                    entry["poster"] = _simkl_poster(media) or entry.get("poster", "")
                    entry["score"] = media.get("ratings", {}).get("simkl", {}).get("rating") or entry.get("score", "N/A")
                    changed = True
                else:
                    print(f"⚠️ Simkl returned no data for movie {simkl_id} ({entry.get('title')})")

            if changed:
                result["movie_entries_updated"] += 1

        # ── Step 5: Sync admins.json from users.json ─────────────────────────
        admins, admins_sha = await read_admins(session)
        admins_changed = False
        for discord_id, admin_rec in admins.items():
            user_profile = users.get(discord_id)
            if not user_profile:
                continue
            updated = False
            # Fill in any missing service IDs from users.json
            sync_fields = [
                ("anilist_user_id", "anilist_user_id"),
                ("anilist_username", "anilist_username"),
                ("anilist_avatar", "anilist_avatar"),
                ("mal_user_id", "mal_user_id"),
                ("mal_username", "mal_username"),
                ("mal_avatar", "mal_avatar"),
                ("simkl_user_id", "simkl_user_id"),
                ("simkl_username", "simkl_username"),
                ("simkl_avatar", "simkl_avatar"),
            ]
            for admin_key, user_key in sync_fields:
                user_val = user_profile.get(user_key)
                admin_val = admin_rec.get(admin_key)
                # Update if user has it and admin doesn't, or if user's value is fresher (non-None vs None)
                if user_val is not None and (admin_val is None or admin_val != user_val):
                    admin_rec[admin_key] = user_val
                    updated = True
            if updated:
                admins_changed = True
                result["admins_updated"] += 1
        # ── Step 6: Write all files in parallel ───────────────────────────────
        write_tasks = [
            write_users(session, users, users_sha, f"chore: repopulate user profiles ({triggered_by})"),
            github_write_json(session, FILE_ANIME, anime_entries, anime_sha, f"chore: sync anime entry usernames ({triggered_by})"),
            github_write_json(session, FILE_MANGA, manga_entries, manga_sha, f"chore: sync manga entry usernames ({triggered_by})"),
            github_write_json(session, FILE_SHOWS, show_entries, show_sha, f"chore: sync show entry usernames ({triggered_by})"),
            github_write_json(session, FILE_MOVIES, movie_entries, movie_sha, f"chore: sync movie entry usernames ({triggered_by})"),
        ]
        if admins_changed:
            write_tasks.append(write_admins(session, admins, admins_sha, f"chore: sync admin profiles from users.json ({triggered_by})"))
        await asyncio.gather(*write_tasks, return_exceptions=True)

    return result


def _build_repopulator_embed(result: dict, title: str) -> discord.Embed:
    """Build a nice embed from repopulator result dict."""
    embed = discord.Embed(title=title, color=0x2EA043)
    embed.add_field(
        name="👥 Users",
        value=(
            f"✅ Updated: **{result['users_updated']}**\n"
            f"⏭️ Skipped: **{result['users_skipped']}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="📺 Anime Entries",
        value=f"🔄 Synced: **{result['anime_entries_updated']}**",
        inline=True,
    )
    embed.add_field(
        name="📖 Manga Entries",
        value=f"🔄 Synced: **{result['manga_entries_updated']}**",
        inline=True,
    )
    embed.add_field(
        name="🎬 Show Entries",
        value=f"🔄 Synced: **{result.get('show_entries_updated', 0)}**",
        inline=True,
    )
    embed.add_field(
        name="🎥 Movie Entries",
        value=f"🔄 Synced: **{result.get('movie_entries_updated', 0)}**",
        inline=True,
    )
    embed.add_field(
        name="🛡️ Admins Synced",
        value=f"🔄 Updated: **{result.get('admins_updated', 0)}**",
        inline=True,
    )
    if result.get("note"):
        embed.add_field(name="ℹ️ Note", value=result["note"], inline=False)
    embed.set_footer(text=f"Triggered by: {result.get('triggered_by', 'system')}")
    return embed


# ── Weekly task (runs every Sunday at midnight UTC) ────────────────────────────

@tasks.loop(hours=1)  # Check every hour — actual run gated by 7-day timestamp
async def weekly_repopulator():
    try:
        async with aiohttp.ClientSession() as session:
            ran = await _maybe_run_repopulator(session, triggered_by="weekly scheduler")
            if not ran:
                pass  # Not time yet — logged inside _maybe_run_repopulator
    except Exception as e:
        print(f"⚠️ Weekly repopulator check failed: {e}")

@weekly_repopulator.before_loop
async def before_weekly_repopulator():
    await bot.wait_until_ready()


# ── Slash command: /repopulate ─────────────────────────────────────────────────

@bot.tree.command(
    name="repopulate",
    description="Refresh all user profiles and sync entries (anime, manga, shows, movies) [Admin]",
)
@app_commands.default_permissions(administrator=True)
async def repopulate(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🔄 Repopulator Started",
            description=(
                "Refreshing user profiles & syncing entries...\n"
                "📁 users.json, anime, manga, shows, movies\n"
                "This may take a moment. I'll send a follow-up when done!"
            ),
            color=0x0078D4,
        )
    )

    try:
        triggered_by = f"{interaction.user.display_name} (manual)"
        result = await run_repopulator(triggered_by=triggered_by)

        # Update last_repopulated.json so the weekly scheduler knows this counts
        try:
            async with aiohttp.ClientSession() as session:
                _, sha = await github_read_json(session, FILE_LAST_REPOPULATED, repo=USERDATA_REPO, branch=USERDATA_BRANCH)
                await github_write_json(
                    session, FILE_LAST_REPOPULATED,
                    {"last_run": time.time(), "triggered_by": triggered_by},
                    sha, f"chore: update last_repopulated ({triggered_by})",
                    repo=USERDATA_REPO, branch=USERDATA_BRANCH,
                )
        except Exception as e:
            print(f"⚠️ Failed to update last_repopulated.json after manual run: {e}")

        embed = _build_repopulator_embed(result, "✅ Repopulator Complete")
    except Exception as e:
        embed = discord.Embed(
            title="❌ Repopulator Failed",
            description=f"An error occurred:\n```{e}```",
            color=0xDA3633,
        )

    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# Voting System — upvote/downvote for community anime & manga
# ══════════════════════════════════════════════════════════════════════════════

import time

# In-memory rate limit store: { "discord_id:vote_key" -> timestamp_of_last_vote }
# Resets on bot restart — intentional, lightweight, no DB needed
_vote_rate_limit: dict[str, float] = {}
# Action counter: { "discord_id:vote_key" -> int }
# First 2 actions (vote + 1 undo) are free, then cooldown kicks in
_vote_action_count: dict[str, int] = {}
VOTE_COOLDOWN_SECONDS = 300  # 5 minutes per user per item (after free undo is used)
VOTE_FREE_ACTIONS = 2  # vote + 1 undo before cooldown applies


def _vote_key(media_type: str, anilist_id: int) -> str:
    """Canonical key used in votes.json and rate limit store."""
    return f"{media_type}:{anilist_id}"


def _check_vote_rate_limit(discord_id: str, vote_key: str) -> float | None:
    """
    Returns None if allowed, or seconds remaining on cooldown if blocked.

    Logic:
      - First 2 actions (vote + undo/switch) are always free.
      - After that, a cooldown of VOTE_COOLDOWN_SECONDS is enforced.
      - Once the cooldown expires, the counter resets for another free pair.
    Also cleans up expired entries to keep memory tidy.
    """
    rl_key = f"{discord_id}:{vote_key}"
    now = time.monotonic()

    # Clean up old entries
    if rl_key in _vote_rate_limit and rl_key not in _vote_action_count:
        del _vote_rate_limit[rl_key]

    action_count = _vote_action_count.get(rl_key, 0)

    # First N actions are always free
    if action_count < VOTE_FREE_ACTIONS:
        return None

    # After free actions, enforce cooldown
    last = _vote_rate_limit.get(rl_key)
    if last is not None:
        elapsed = now - last
        if elapsed < VOTE_COOLDOWN_SECONDS:
            return VOTE_COOLDOWN_SECONDS - elapsed
        # Cooldown expired → reset counter for another free pair
        _vote_action_count[rl_key] = 0
        return None

    return None


def _stamp_vote_rate_limit(discord_id: str, vote_key: str):
    """Record that this user just voted on this item."""
    rl_key = f"{discord_id}:{vote_key}"
    _vote_rate_limit[rl_key] = time.monotonic()
    _vote_action_count[rl_key] = _vote_action_count.get(rl_key, 0) + 1


async def _cast_vote(
    voter_id: str,
    display_name: str,
    media_type: str,
    anilist_id: int,
    direction: str,  # "up" or "down"
) -> dict:
    """
    Core vote logic. voter_id is the AniList user ID (or MAL user ID prefixed
    with 'mal:') of the person voting — NOT a Discord ID.
    Returns a result dict: { success, upvotes, downvotes, action, title }
    action is one of: "added_up", "added_down", "switched_to_up",
                      "switched_to_down", "removed_up", "removed_down"
    """
    vote_key = _vote_key(media_type, anilist_id)

    async with aiohttp.ClientSession() as session:
        votes, votes_sha = await github_read_json(session, FILE_VOTES)
        if media_type == "anime":
            media_file = FILE_ANIME
        elif media_type == "manga":
            media_file = FILE_MANGA
        elif media_type == "show":
            media_file = FILE_SHOWS
        else:
            media_file = FILE_MOVIES
        entries, _ = await github_read_json(session, media_file)

    # For shows/movies the "anilist_id" param is actually simkl_id
    if media_type in ("show", "movie"):
        entry = next((e for e in entries if e.get("simkl_id") == anilist_id), None)
    else:
        entry = next((e for e in entries if e.get("anilist_id") == anilist_id), None)
    if not entry:
        return {"success": False, "error": f"No {media_type} with AniList ID {anilist_id} found in the list."}

    title = entry.get("title", str(anilist_id))

    record = votes.get(vote_key, {
        "media_type": media_type,
        "anilist_id": anilist_id,
        "title": title,
        "upvotes": [],
        "downvotes": [],
        "total_upvotes": 0,
        "total_downvotes": 0,
    })

    upvotes: list = record.get("upvotes", [])
    downvotes: list = record.get("downvotes", [])

    action = ""
    if direction == "up":
        if voter_id in upvotes:
            upvotes.remove(voter_id)
            action = "removed_up"
        else:
            upvotes.append(voter_id)
            if voter_id in downvotes:
                downvotes.remove(voter_id)
                action = "switched_to_up"
            else:
                action = "added_up"
    else:  # down
        if voter_id in downvotes:
            downvotes.remove(voter_id)
            action = "removed_down"
        else:
            downvotes.append(voter_id)
            if voter_id in upvotes:
                upvotes.remove(voter_id)
                action = "switched_to_down"
            else:
                action = "added_down"

    record["upvotes"] = upvotes
    record["downvotes"] = downvotes
    record["total_upvotes"] = len(upvotes)
    record["total_downvotes"] = len(downvotes)
    record["title"] = title
    votes[vote_key] = record

    async with aiohttp.ClientSession() as session:
        ok = await github_write_json(
            session, FILE_VOTES, votes, votes_sha,
            f"vote: {display_name} {action} {media_type} '{title}' (id:{anilist_id})"
        )

    if not ok:
        return {"success": False, "error": "Failed to save vote to GitHub."}

    return {
        "success": True,
        "action": action,
        "title": title,
        "upvotes": len(upvotes),
        "downvotes": len(downvotes),
        "net": len(upvotes) - len(downvotes),
    }


def _vote_action_text(action: str) -> str:
    return {
        "added_up": "✅ Upvoted",
        "added_down": "❌ Downvoted",
        "switched_to_up": "🔄 Switched to upvote",
        "switched_to_down": "🔄 Switched to downvote",
        "removed_up": "↩️ Upvote removed",
        "removed_down": "↩️ Downvote removed",
    }.get(action, "Voted")


async def _handle_vote_interaction(
    interaction: discord.Interaction,
    media_type: str,
    anilist_id_str: str,
    direction: str,
):
    """Shared slash command handler for voting."""
    await interaction.response.defer(ephemeral=True)

    if not anilist_id_str.isdigit():
        await interaction.followup.send("❌ Please select an item from the dropdown.", ephemeral=True)
        return

    anilist_id = int(anilist_id_str)
    discord_id = str(interaction.user.id)

    # Resolve the voter's AniList or MAL ID from their profile
    async with aiohttp.ClientSession() as session:
        users, _ = await read_users(session)
    profile = users.get(discord_id)

    if not profile:
        await interaction.followup.send(
            "❌ You need to link an account first using `/link_anilist`, `/link_mal`, or `/link_simkl` before voting.",
            ephemeral=True,
        )
        return

    al_id = profile.get("anilist_user_id")
    mal_id = profile.get("mal_user_id")
    simkl_uname = profile.get("simkl_username")

    if al_id:
        voter_id = f"al:{al_id}"
        display_name = profile.get("anilist_username") or interaction.user.display_name
    elif mal_id:
        voter_id = f"mal:{mal_id}"
        display_name = profile.get("mal_username") or interaction.user.display_name
    elif simkl_uname:
        voter_id = f"simkl:{simkl_uname}"
        display_name = simkl_uname
    else:
        await interaction.followup.send(
            "❌ Your profile has no linked AniList, MAL, or Simkl account. Use `/link_anilist`, `/link_mal`, or `/link_simkl` to link one.",
            ephemeral=True,
        )
        return

    vote_key = _vote_key(media_type, anilist_id)

    # Rate limit check (keyed on voter_id, not discord_id)
    cooldown = _check_vote_rate_limit(voter_id, vote_key)
    if cooldown is not None:
        mins = int(cooldown // 60)
        secs = int(cooldown % 60)
        await interaction.followup.send(
            f"⏳ You've used your free undo. Try again in **{mins}m {secs}s**.",
            ephemeral=True,
        )
        return

    result = await _cast_vote(voter_id, display_name, media_type, anilist_id, direction)

    if not result["success"]:
        await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
        return

    _stamp_vote_rate_limit(voter_id, vote_key)

    action_text = _vote_action_text(result["action"])
    color = 0x2EA043 if "up" in result["action"] else (0xDA3633 if "down" in result["action"] else 0x888888)

    embed = discord.Embed(
        title=f"{action_text} — {result['title']}",
        color=color,
    )
    embed.add_field(name="👍 Upvotes", value=f"**{result['upvotes']}**", inline=True)
    embed.add_field(name="👎 Downvotes", value=f"**{result['downvotes']}**", inline=True)
    embed.add_field(name="📊 Net", value=f"**{result['net']:+d}**", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

    log_embed = discord.Embed(title=f"🗳️ Vote — {media_type.title()}", color=color)
    log_embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
    log_embed.add_field(name="Action", value=action_text, inline=True)
    log_embed.add_field(name="Title", value=result["title"], inline=True)
    log_embed.add_field(name="👍 Up", value=str(result["upvotes"]), inline=True)
    log_embed.add_field(name="👎 Down", value=str(result["downvotes"]), inline=True)
    log_embed.add_field(name="📊 Net", value=f"{result['net']:+d}", inline=True)
    await _send_log(log_embed)


# ── Autocomplete for existing list entries ─────────────────────────────────────

async def _existing_anime_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_ANIME)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["anilist_id"]))
        for e in filtered[:25]
    ]


async def _existing_manga_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MANGA)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["anilist_id"]))
        for e in filtered[:25]
    ]


async def _existing_show_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_SHOWS)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["simkl_id"]))
        for e in filtered[:25]
    ]


async def _existing_movie_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with aiohttp.ClientSession() as session:
        entries, _ = await github_read_json(session, FILE_MOVIES)
    filtered = [e for e in entries if current.lower() in e.get("title", "").lower()]
    return [
        app_commands.Choice(name=e["title"][:100], value=str(e["simkl_id"]))
        for e in filtered[:25]
    ]


# ── /vote_anime ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_anime", description="Upvote or downvote a community anime")
@app_commands.describe(
    title="Search for the anime in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_anime_autocomplete)
async def vote_anime(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "anime", title, direction.value)


# ── /vote_manga ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_manga", description="Upvote or downvote a community manga")
@app_commands.describe(
    title="Search for the manga in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_manga_autocomplete)
async def vote_manga(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "manga", title, direction.value)


# ── /vote_show ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_show", description="Upvote or downvote a community TV show")
@app_commands.describe(
    title="Search for the show in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_show_autocomplete)
async def vote_show(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "show", title, direction.value)


# ── /vote_movie ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_movie", description="Upvote or downvote a community movie")
@app_commands.describe(
    title="Search for the movie in the list",
    direction="Upvote or downvote",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="👍 Upvote", value="up"),
    app_commands.Choice(name="👎 Downvote", value="down"),
])
@app_commands.autocomplete(title=_existing_movie_autocomplete)
async def vote_movie(
    interaction: discord.Interaction,
    title: str,
    direction: app_commands.Choice[str],
):
    await _handle_vote_interaction(interaction, "movie", title, direction.value)


# ── /vote_stats ────────────────────────────────────────────────────────────────

@bot.tree.command(name="vote_stats", description="See vote leaderboard for anime, manga, shows or movies")
@app_commands.describe(media_type="Which list to show")
@app_commands.choices(media_type=[
    app_commands.Choice(name="Anime", value="anime"),
    app_commands.Choice(name="Manga", value="manga"),
    app_commands.Choice(name="TV Shows", value="show"),
    app_commands.Choice(name="Movies", value="movie"),
])
async def vote_stats(interaction: discord.Interaction, media_type: app_commands.Choice[str]):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        votes, _ = await github_read_json(session, FILE_VOTES)

    # Filter by media type and sort by net score desc
    relevant = [
        v for k, v in votes.items()
        if v.get("media_type") == media_type.value
    ]
    relevant.sort(key=lambda v: v.get("total_upvotes", 0) - v.get("total_downvotes", 0), reverse=True)

    if not relevant:
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"No votes yet for {media_type.name}",
                description="Be the first to vote using `/vote_anime` or `/vote_manga`!",
                color=0x0078D4,
            )
        )
        return

    emoji = {"anime": "📺", "manga": "📖", "show": "🎬", "movie": "🎥"}.get(media_type.value, "📺")
    label = {"anime": "Anime", "manga": "Manga", "show": "TV Shows", "movie": "Movies"}.get(media_type.value, media_type.name)
    embed = discord.Embed(
        title=f"{emoji} {label} Vote Leaderboard",
        color=0x0078D4,
    )

    medals = ["🥇", "🥈", "🥉"]
    prev_net = None
    dense_rank = 0
    for i, v in enumerate(relevant[:10]):
        up = v.get("total_upvotes", 0)
        down = v.get("total_downvotes", 0)
        net = up - down
        # Dense ranking: same score = same rank, no gaps
        if net != prev_net:
            dense_rank += 1
            prev_net = net
        prefix = medals[dense_rank - 1] if dense_rank <= 3 else f"`#{dense_rank}`"
        embed.add_field(
            name=f"{prefix} {v.get('title', '?')}",
            value=f"👍 {up}  👎 {down}  📊 **{net:+d}**",
            inline=False,
        )

    embed.set_footer(text=f"Showing top {min(len(relevant), 10)} of {len(relevant)} entries")
    await interaction.followup.send(embed=embed)


# ── /my_votes ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="my_votes", description="See all your votes")
async def my_votes(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    discord_id = str(interaction.user.id)

    async with aiohttp.ClientSession() as session:
        users, _ = await read_users(session)
        votes, _ = await github_read_json(session, FILE_VOTES)

    profile = users.get(discord_id)
    if not profile:
        await interaction.followup.send(
            "❌ No profile found. Link an account first using `/link_anilist`, `/link_mal`, or `/link_simkl`!", ephemeral=True
        )
        return

    al_id = profile.get("anilist_user_id")
    mal_id = profile.get("mal_user_id")
    voter_id = f"al:{al_id}" if al_id else (f"mal:{mal_id}" if mal_id else None)

    if not voter_id:
        await interaction.followup.send(
            "❌ Your profile has no linked AniList or MAL account.", ephemeral=True
        )
        return

    my_up = []
    my_down = []
    for key, v in votes.items():
        if voter_id in v.get("upvotes", []):
            my_up.append(f"👍 **{v.get('title', key)}** ({v.get('media_type', '?')})")
        elif voter_id in v.get("downvotes", []):
            my_down.append(f"👎 **{v.get('title', key)}** ({v.get('media_type', '?')})")

    embed = discord.Embed(title=f"🗳️ {interaction.user.display_name}'s Votes", color=0x0078D4)

    if my_up:
        embed.add_field(name="👍 Upvoted", value="\n".join(my_up[:15]), inline=False)
    if my_down:
        embed.add_field(name="👎 Downvoted", value="\n".join(my_down[:15]), inline=False)
    if not my_up and not my_down:
        embed.description = "You haven't voted on anything yet!\nUse `/vote_anime`, `/vote_manga`, `/vote_show`, or `/vote_movie` to get started."

    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Voting API endpoints
# POST /api/vote/anime/{anilist_id}   body: { "anilist_user_id": int } or { "mal_user_id": int }, "direction": "up"/"down"
# POST /api/vote/manga/{anilist_id}
# GET  /api/votes/anime/{anilist_id}
# GET  /api/votes/manga/{anilist_id}
# GET  /api/votes/leaderboard?type=anime|manga&limit=10
# ══════════════════════════════════════════════════════════════════════════════

async def api_vote_handler(request, media_type: str):
    """POST /api/vote/{media_type}/{media_id}
    Body: { "anilist_user_id": int } OR { "mal_user_id": int }, plus "direction": "up"/"down"
    Supports looking up entry by anilist_id or mal_id via "id_type": "anilist" | "mal"
    """
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        media_id = int(request.match_info["anilist_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid media_id in URL"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    al_uid = body.get("anilist_user_id")
    mal_uid = body.get("mal_user_id")
    simkl_uid = body.get("simkl_user_id")
    display_name = str(body.get("display_name", "API User")).strip()
    direction = str(body.get("direction", "")).strip().lower()
    id_type = str(body.get("id_type", "anilist")).strip().lower()  # "anilist", "mal", or "simkl"

    if not al_uid and not mal_uid and not simkl_uid:
        return web.json_response({"error": "Provide at least one of: anilist_user_id, mal_user_id, simkl_user_id"}, status=400)
    if direction not in ("up", "down"):
        return web.json_response({"error": "direction must be 'up' or 'down'"}, status=400)
    if id_type not in ("anilist", "mal", "simkl"):
        return web.json_response({"error": "id_type must be 'anilist', 'mal', or 'simkl'"}, status=400)

    if al_uid:
        voter_id = f"al:{al_uid}"
    elif mal_uid:
        voter_id = f"mal:{mal_uid}"
    else:
        voter_id = f"simkl:{simkl_uid}"

    # Resolve anilist_id from the media_id — if id_type is "mal", look up by mal_id
    async with aiohttp.ClientSession() as session:
        if media_type == "anime":
            media_file = FILE_ANIME
        elif media_type == "manga":
            media_file = FILE_MANGA
        elif media_type == "show":
            media_file = FILE_SHOWS
        else:
            media_file = FILE_MOVIES
        entries, _ = await github_read_json(session, media_file)

    if media_type in ("show", "movie"):
        # For shows/movies, the URL param is simkl_id
        entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
    elif id_type == "mal":
        entry = next((e for e in entries if e.get("mal_id") == media_id), None)
    elif id_type == "simkl":
        entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
    else:
        entry = next((e for e in entries if e.get("anilist_id") == media_id), None)

    if not entry:
        return web.json_response(
            {"error": f"No {media_type} with {id_type}_id={media_id} found in the list."},
            status=404,
        )

    # For show/movie entries the canonical ID is simkl_id; reuse the anilist_id param name for the vote key
    anilist_id = entry.get("simkl_id") if media_type in ("show", "movie") else entry["anilist_id"]
    vote_key = _vote_key(media_type, anilist_id)
    cooldown = _check_vote_rate_limit(voter_id, vote_key)
    if cooldown is not None:
        return web.json_response(
            {"error": "Rate limited", "retry_after_seconds": round(cooldown, 1)},
            status=429,
        )

    result = await _cast_vote(voter_id, display_name, media_type, anilist_id, direction)
    if not result["success"]:
        status = 404 if "found" in result.get("error", "") else 500
        return web.json_response({"error": result["error"]}, status=status)

    _stamp_vote_rate_limit(voter_id, vote_key)

    action_text = _vote_action_text(result["action"])
    color = 0x2EA043 if "up" in result["action"] else (0xDA3633 if "down" in result["action"] else 0x888888)
    log_embed = discord.Embed(title=f"🗳️ Vote (API) — {media_type.title()}", color=color)
    log_embed.add_field(name="User", value=f"`{display_name}` (`{voter_id}`)", inline=True)
    log_embed.add_field(name="Action", value=action_text, inline=True)
    log_embed.add_field(name="Title", value=result["title"], inline=True)
    log_embed.add_field(name="👍 Up", value=str(result["upvotes"]), inline=True)
    log_embed.add_field(name="👎 Down", value=str(result["downvotes"]), inline=True)
    log_embed.add_field(name="📊 Net", value=f"{result['net']:+d}", inline=True)
    await _send_log(log_embed)

    return web.json_response(result, status=200)


async def api_get_votes(request, media_type: str):
    """GET /api/votes/{media_type}/{media_id}?id_type=anilist|mal|simkl&anilist_user_id=X&mal_user_id=X&simkl_user_id=X"""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        media_id = int(request.match_info["anilist_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid media_id in URL"}, status=400)

    id_type = request.rel_url.query.get("id_type", "anilist").lower()
    if id_type not in ("anilist", "mal", "simkl"):
        return web.json_response({"error": "id_type must be 'anilist', 'mal', or 'simkl'"}, status=400)

    # Resolve voter_id from optional query params to determine user_vote
    al_uid = request.rel_url.query.get("anilist_user_id")
    mal_uid = request.rel_url.query.get("mal_user_id")
    simkl_uid = request.rel_url.query.get("simkl_user_id")
    voter_id = None
    if al_uid:
        voter_id = f"al:{al_uid}"
    elif mal_uid:
        voter_id = f"mal:{mal_uid}"
    elif simkl_uid:
        voter_id = f"simkl:{simkl_uid}"

    async with aiohttp.ClientSession() as session:
        votes, _ = await github_read_json(session, FILE_VOTES)
        # Resolve anilist_id if mal/simkl id_type provided
        if id_type == "mal" and media_type in ("anime", "manga"):
            media_file = FILE_ANIME if media_type == "anime" else FILE_MANGA
            entries, _ = await github_read_json(session, media_file)
            entry = next((e for e in entries if e.get("mal_id") == media_id), None)
            if not entry:
                return web.json_response({"error": f"No {media_type} with mal_id={media_id} found."}, status=404)
            anilist_id = entry["anilist_id"]
        elif id_type == "simkl":
            media_file = FILE_SHOWS if media_type == "show" else FILE_MOVIES
            entries, _ = await github_read_json(session, media_file)
            entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
            if not entry:
                return web.json_response({"error": f"No {media_type} with simkl_id={media_id} found."}, status=404)
            anilist_id = entry["simkl_id"]
        elif media_type in ("show", "movie"):
            media_file = FILE_SHOWS if media_type == "show" else FILE_MOVIES
            entries, _ = await github_read_json(session, media_file)
            entry = next((e for e in entries if e.get("simkl_id") == media_id), None)
            if not entry:
                return web.json_response({"error": f"No {media_type} with simkl_id={media_id} found."}, status=404)
            anilist_id = entry["simkl_id"]
        else:
            anilist_id = media_id

    vote_key = _vote_key(media_type, anilist_id)
    record = votes.get(vote_key)
    if not record:
        return web.json_response({
            "media_type": media_type,
            "anilist_id": anilist_id,
            "total_upvotes": 0,
            "total_downvotes": 0,
            "net": 0,
            "user_vote": None,
        })

    # Determine user_vote from voter_id
    user_vote = None
    if voter_id:
        upvoters = record.get("upvotes", [])
        downvoters = record.get("downvotes", [])
        if voter_id in upvoters:
            user_vote = "up"
        elif voter_id in downvoters:
            user_vote = "down"

    return web.json_response({
        "media_type": media_type,
        "anilist_id": anilist_id,
        "title": record.get("title"),
        "total_upvotes": record.get("total_upvotes", 0),
        "total_downvotes": record.get("total_downvotes", 0),
        "net": record.get("total_upvotes", 0) - record.get("total_downvotes", 0),
        "user_vote": user_vote,
    })


async def api_leaderboard(request):
    """GET /api/votes/leaderboard?type=anime|manga&limit=10"""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    media_type = request.rel_url.query.get("type", "anime").lower()
    if media_type not in ("anime", "manga", "show", "movie"):
        return web.json_response({"error": "type must be 'anime', 'manga', 'show', or 'movie'"}, status=400)
    try:
        limit = min(int(request.rel_url.query.get("limit", 10)), 50)
    except ValueError:
        limit = 10

    async with aiohttp.ClientSession() as session:
        votes, _ = await github_read_json(session, FILE_VOTES)

    relevant = [
        v for k, v in votes.items() if v.get("media_type") == media_type
    ]
    relevant.sort(
        key=lambda v: v.get("total_upvotes", 0) - v.get("total_downvotes", 0),
        reverse=True,
    )

    leaderboard = []
    prev_net = None
    dense_rank = 0
    for i, v in enumerate(relevant[:limit]):
        net = v.get("total_upvotes", 0) - v.get("total_downvotes", 0)
        if net != prev_net:
            dense_rank += 1
            prev_net = net
        leaderboard.append({
            "rank": dense_rank,
            "anilist_id": v.get("anilist_id"),
            "title": v.get("title"),
            "total_upvotes": v.get("total_upvotes", 0),
            "total_downvotes": v.get("total_downvotes", 0),
            "net": net,
        })

    return web.json_response({
        "media_type": media_type,
        "leaderboard": leaderboard,
    })


# Route shims
async def api_vote_anime(request): return await api_vote_handler(request, "anime")
async def api_vote_manga(request): return await api_vote_handler(request, "manga")
async def api_vote_show(request): return await api_vote_handler(request, "show")
async def api_vote_movie(request): return await api_vote_handler(request, "movie")
async def api_get_votes_anime(request): return await api_get_votes(request, "anime")
async def api_get_votes_manga(request): return await api_get_votes(request, "manga")
async def api_get_votes_show(request): return await api_get_votes(request, "show")
async def api_get_votes_movie(request): return await api_get_votes(request, "movie")


@bot.tree.command(
    name="fix_discord_info",
    description="Backfill missing Discord info for all users and entries (Admin only)",
)
@app_commands.default_permissions(administrator=True)
async def fix_discord_info(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🔧 Fixing Discord Info...",
            description="Fetching Discord profiles for all users. This will take a moment.",
            color=0x0078D4,
        )
    )

    async with aiohttp.ClientSession() as session:
        users, users_sha = await read_users(session)
        admins, _ = await read_admins(session)
        anime_entries, anime_sha = await github_read_json(session, FILE_ANIME)
        manga_entries, manga_sha = await github_read_json(session, FILE_MANGA)
        show_entries, show_sha = await github_read_json(session, FILE_SHOWS)
        movie_entries, movie_sha = await github_read_json(session, FILE_MOVIES)

        fixed_users = 0
        failed_users = 0

        # Step 1: update discord info in users.json using bot.fetch_user
        for discord_id, profile in users.items():
            try:
                user = await bot.fetch_user(int(discord_id))
                profile["discord_id"] = user.id
                profile["discord_username"] = user.name
                profile["discord_display_name"] = user.display_name
                profile["discord_avatar"] = str(user.display_avatar.url) if user.display_avatar else None
                fixed_users += 1
                print(f"✅ Updated discord info for {user.name} ({discord_id})")
            except Exception as e:
                failed_users += 1
                print(f"⚠️ Failed to fetch Discord user {discord_id}: {e}")
            await asyncio.sleep(0.5)

        # Build lookups: anilist_user_id -> profile, mal_user_id -> profile, simkl_username -> profile
        al_id_to_profile = {}
        mal_id_to_profile = {}
        simkl_uname_to_profile = {}
        for profile in users.values():
            al_id = profile.get("anilist_user_id")
            mal_id = profile.get("mal_user_id")
            simkl_uname = profile.get("simkl_username")
            if al_id:
                al_id_to_profile[al_id] = profile
            if mal_id:
                mal_id_to_profile[mal_id] = profile
            if simkl_uname:
                simkl_uname_to_profile[simkl_uname.lower()] = profile

        # Step 2: update anime entries
        anime_updated = 0
        for entry in anime_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                anime_updated += 1

        # Step 3: update manga entries
        manga_updated = 0
        for entry in manga_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                manga_updated += 1

        # Step 3b: update show entries
        show_updated = 0
        for entry in show_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            elif simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                matched = simkl_uname_to_profile[simkl_uname.lower()]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                show_updated += 1

        # Step 3c: update movie entries
        movie_updated = 0
        for entry in movie_entries:
            u = entry.get("user", {})
            al_uid = u.get("anilist", {}).get("id")
            mal_uid = u.get("mal", {}).get("id")
            simkl_uname = u.get("simkl", {}).get("username")
            matched = None
            if al_uid and al_uid in al_id_to_profile:
                matched = al_id_to_profile[al_uid]
            elif mal_uid and mal_uid in mal_id_to_profile:
                matched = mal_id_to_profile[mal_uid]
            elif simkl_uname and simkl_uname.lower() in simkl_uname_to_profile:
                matched = simkl_uname_to_profile[simkl_uname.lower()]
            if matched:
                entry["user"] = _build_user_snapshot(matched)
                _mark_admin_flag(entry["user"], admins)
                movie_updated += 1

        # Step 4: write all files in parallel
        await asyncio.gather(
            write_users(session, users, users_sha, "fix: backfill discord info for all users"),
            github_write_json(session, FILE_ANIME, anime_entries, anime_sha, "fix: sync discord info in anime entries"),
            github_write_json(session, FILE_MANGA, manga_entries, manga_sha, "fix: sync discord info in manga entries"),
            github_write_json(session, FILE_SHOWS, show_entries, show_sha, "fix: sync discord info in show entries"),
            github_write_json(session, FILE_MOVIES, movie_entries, movie_sha, "fix: sync discord info in movie entries"),
            return_exceptions=True,
        )

    embed = discord.Embed(title="✅ Discord Info Fixed!", color=0x2EA043)
    embed.add_field(
        name="👥 Users",
        value=f"✅ Fixed: **{fixed_users}**\n❌ Failed: **{failed_users}**",
        inline=True,
    )
    embed.add_field(name="📺 Anime Entries", value=f"🔄 Updated: **{anime_updated}**", inline=True)
    embed.add_field(name="📖 Manga Entries", value=f"🔄 Updated: **{manga_updated}**", inline=True)
    embed.add_field(name="🎬 Show Entries", value=f"🔄 Updated: **{show_updated}**", inline=True)
    embed.add_field(name="🎥 Movie Entries", value=f"🔄 Updated: **{movie_updated}**", inline=True)
    await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /faq — slash command with autocomplete search
# ══════════════════════════════════════════════════════════════════════════════

async def _faq_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete callback: fuzzy-match FAQ titles as the user types."""
    choices: list[app_commands.Choice[str]] = []
    query = current.lower().strip()

    for faq_id, entry in FAQ_MAP.items():
        title_lower = entry["title"].lower()
        # Exact prefix match first
        if query and title_lower.startswith(query):
            choices.append(
                app_commands.Choice(
                    name=f"#{faq_id} {entry['title'][:80]}",
                    value=str(faq_id),
                )
            )
        # Then substring match
        elif query and query in title_lower:
            choices.append(
                app_commands.Choice(
                    name=f"#{faq_id} {entry['title'][:80]}",
                    value=str(faq_id),
                )
            )
        # No query = show all
        elif not query:
            choices.append(
                app_commands.Choice(
                    name=f"#{faq_id} {entry['title'][:80]}",
                    value=str(faq_id),
                )
            )

    # Discord limits to 25 choices
    return choices[:25]


@bot.tree.command(name="faq", description="Search and send an FAQ answer")
@app_commands.describe(
    query="Type to search FAQ titles (or pick a number)",
    user="Optional: mention/tag a user with the FAQ",
    message_url="Optional: Discord message URL to reply to (replies to that message & tags author)",
    message_id="Optional: Discord message ID to reply to in this channel",
)
@app_commands.autocomplete(query=_faq_autocomplete)
async def faq_slash(
    interaction: discord.Interaction,
    query: str,
    user: discord.User | None = None,
    message_url: str | None = None,
    message_id: str | None = None,
):
    """Send a FAQ embed. Works with autocomplete selection or a direct number.

    Optional params:
      - user:       pings that user alongside the embed
      - message_url: bot replies to that message and pings its author
    """
    # If the user selected from autocomplete, query will be the FAQ id as string
    if query.isdigit():
        faq_num = int(query)
        faq = FAQ_MAP.get(faq_num)
    else:
        # Try matching by partial title
        faq_num = None
        query_lower = query.lower().strip()
        for fid, entry in FAQ_MAP.items():
            if query_lower in entry["title"].lower():
                faq_num = fid
                faq = entry
                break

    if not faq or faq_num is None:
        await interaction.response.send_message(
            "❌ No matching FAQ found. Use the autocomplete dropdown to pick one.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"❓ FAQ #{faq_num} — {faq['title']}",
        description=faq["description"],
        color=0x6A5ACD,
    )
    embed.set_footer(text="AnymeX • Frequently Asked Questions")

    # ── Determine send target: message_url > message_id > user mention > plain send ──
    target_msg = None
    if message_url:
        # Parse Discord message URL: https://discord.com/channels/GUILD_ID/CHANNEL_ID/MESSAGE_ID
        url_match = re.search(r"/channels/\d+/(\d+)/(\d+)", message_url)
        if url_match:
            channel_id = int(url_match.group(1))
            msg_id = int(url_match.group(2))
            try:
                channel = interaction.guild.get_channel(channel_id)
                if channel is None:
                    channel = interaction.client.get_channel(channel_id)
                if channel:
                    target_msg = await channel.fetch_message(msg_id)
            except (discord.HTTPException, discord.Forbidden, AttributeError):
                pass
    elif message_id and message_id.strip().isdigit():
        # Fetch message by ID from the current channel
        try:
            target_msg = await interaction.channel.fetch_message(int(message_id.strip()))
        except (discord.HTTPException, discord.Forbidden, AttributeError):
            pass

    # Defer since we may need to fetch messages (network call)
    await interaction.response.defer(ephemeral=False)

    if target_msg is not None:
        # Reply to the referenced message and ping its author
        try:
            content = None
            # If user param is also set, include that ping too
            if user and user.id != target_msg.author.id:
                content = f"{user.mention} {target_msg.author.mention}"
            elif user:
                content = user.mention
            await target_msg.reply(embed=embed, content=content, mention_author=bool(content))
        except discord.HTTPException:
            # Fallback: send normally in the interaction channel
            mention = user.mention if user else None
            await interaction.followup.send(content=mention, embed=embed)
            return
        # Delete the deferred "thinking" response since we replied to the target message
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
    elif user:
        # Just ping the specified user, no reply
        await interaction.followup.send(content=user.mention, embed=embed)
    else:
        # Plain send, no pings
        await interaction.followup.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# /rules — slash command with autocomplete search
# ══════════════════════════════════════════════════════════════════════════════

async def _rules_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete callback: fuzzy-match rule titles as the user types."""
    choices: list[app_commands.Choice[str]] = []
    query = current.lower().strip()

    for rule_id, entry in RULES_MAP.items():
        title_lower = entry["title"].lower()
        if query and title_lower.startswith(query):
            choices.append(
                app_commands.Choice(
                    name=f"#{rule_id} {entry['title'][:80]}",
                    value=str(rule_id),
                )
            )
        elif query and query in title_lower:
            choices.append(
                app_commands.Choice(
                    name=f"#{rule_id} {entry['title'][:80]}",
                    value=str(rule_id),
                )
            )
        elif not query:
            choices.append(
                app_commands.Choice(
                    name=f"#{rule_id} {entry['title'][:80]}",
                    value=str(rule_id),
                )
            )

    return choices[:25]


@bot.tree.command(name="rules", description="Search and send a server rule")
@app_commands.describe(
    query="Type to search rule titles (or pick a number)",
    user="Optional: mention/tag a user with the rule",
    message_url="Optional: Discord message URL to reply to",
    message_id="Optional: Discord message ID to reply to in this channel",
)
@app_commands.autocomplete(query=_rules_autocomplete)
async def rules_slash(
    interaction: discord.Interaction,
    query: str,
    user: discord.User | None = None,
    message_url: str | None = None,
    message_id: str | None = None,
):
    if query.isdigit():
        rule_num = int(query)
        rule = RULES_MAP.get(rule_num)
    else:
        rule_num = None
        query_lower = query.lower().strip()
        for rid, entry in RULES_MAP.items():
            if query_lower in entry["title"].lower():
                rule_num = rid
                rule = entry
                break

    if not rule or rule_num is None:
        await interaction.response.send_message(
            "❌ No matching rule found. Use the autocomplete dropdown to pick one.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"📜 Rule #{rule_num} — {rule['title']}",
        description=rule["description"],
        color=0x01CBE6,
    )
    embed.set_footer(text="AnymeX • Server Rules")

    target_msg = None
    if message_url:
        url_match = re.search(r"/channels/\d+/(\d+)/(\d+)", message_url)
        if url_match:
            channel_id = int(url_match.group(1))
            msg_id = int(url_match.group(2))
            try:
                channel = interaction.guild.get_channel(channel_id)
                if channel is None:
                    channel = interaction.client.get_channel(channel_id)
                if channel:
                    target_msg = await channel.fetch_message(msg_id)
            except (discord.HTTPException, discord.Forbidden, AttributeError):
                pass
    elif message_id and message_id.strip().isdigit():
        # Fetch message by ID from the current channel
        try:
            target_msg = await interaction.channel.fetch_message(int(message_id.strip()))
        except (discord.HTTPException, discord.Forbidden, AttributeError):
            pass

    await interaction.response.defer(ephemeral=False)

    if target_msg is not None:
        try:
            content = None
            if user and user.id != target_msg.author.id:
                content = f"{user.mention} {target_msg.author.mention}"
            elif user:
                content = user.mention
            await target_msg.reply(embed=embed, content=content, mention_author=bool(content))
        except discord.HTTPException:
            mention = user.mention if user else None
            await interaction.followup.send(content=mention, embed=embed)
            return
        # Delete the deferred "thinking" response since we replied to the target message
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
    elif user:
        await interaction.followup.send(content=user.mention, embed=embed)
    else:
        await interaction.followup.send(embed=embed)


@bot.event
async def on_message(message: discord.Message):
    # ── FAQ handler (legacy support channel mode) ────────────────────────────
    # Kept for backward compat: in the support channel, "faq #N" with a reply/mention
    # still works as before. The new !faqN prefix and /faq slash cmd are preferred.
    if (
        not message.author.bot
        and SUPPORT_CHANNEL_ID
        and message.channel.id == SUPPORT_CHANNEL_ID
        and (message.reference is not None or len(message.mentions) > 0)
    ):
        faq_match = re.search(r"\bfaq\s*#?(\d+)\b", message.content, re.IGNORECASE)
        if faq_match and not re.match(r"^!(?:faq|log)\d+$", message.content.strip(), re.IGNORECASE):
            # Only trigger if NOT a !faqN prefix (that's handled by faq_trigger)
            faq_num = int(faq_match.group(1))
            faq = FAQ_MAP.get(faq_num)

            # Delete the triggering message to keep the channel clean
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            if faq:
                embed = discord.Embed(
                    title=f"❓ FAQ #{faq_num} — {faq['title']}",
                    description=faq["description"],
                    color=0x6A5ACD,
                )
                embed.set_footer(text="AnymeX • Frequently Asked Questions")

                if message.reference is not None:
                    # Reply mode — ping the author of the original message
                    try:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                        await ref_msg.reply(embed=embed, mention_author=True)
                    except discord.HTTPException:
                        await message.channel.send(embed=embed)
                else:
                    # Mention mode — ping all mentioned users
                    mentions = " ".join(u.mention for u in message.mentions)
                    await message.channel.send(content=mentions, embed=embed)
            else:
                await message.channel.send(
                    f"⚠️ FAQ **#{faq_num}** not found. Valid range: 1–{max(FAQ_MAP.keys(), default=0)}.",
                    delete_after=8,
                )
            return  # skip process_commands for this message

    # ── Hi trigger ──────────────────────────────────────────────────────────────
    # NOTE: hi_trigger.setup() registers its own on_message listener via bot.listen(),
    # so we do NOT call hi_trigger._handle() here — that would cause double-processing.
    # If hi_trigger.setup() is NOT called (module missing), this is a no-op.

    # ── Source/extension trigger ────────────────────────────────────────────────
    # NOTE: source_trigger.setup() also registers its own on_message listener,
    # so no direct call needed here either.



# /sheby_build  — trigger sheby_alpha_manual.yml (clones Shebyyy/AnymeX)
# ══════════════════════════════════════════════════════════════════════════════

SHEBY_WORKFLOW_FILE = "sheby_alpha_manual.yml"
SHEBY_SOURCE_REPO   = "Shebyyy/AnymeX"         # repo whose branches are listed


async def _fetch_sheby_branches() -> list[str]:
    """Return all branch names from Shebyyy/AnymeX via GitHub API."""
    branches: list[str] = []
    page = 1
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                f"{GITHUB_API}/repos/{SHEBY_SOURCE_REPO}/branches?per_page=100&page={page}",
                headers=gh_headers(),
            ) as r:
                if r.status != 200:
                    break
                data = await r.json()
                if not data:
                    break
                branches.extend(b["name"] for b in data)
                if len(data) < 100:
                    break
                page += 1
    return branches


async def _sheby_branch_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        all_branches = await _fetch_sheby_branches()
    except Exception:
        all_branches = ["main"]

    filtered = [b for b in all_branches if current.lower() in b.lower()]
    # Discord allows max 25 choices
    return [app_commands.Choice(name=b, value=b) for b in filtered[:25]]


@bot.tree.command(name="sheby_build", description="Trigger a build from Shebyyy/AnymeX on a chosen branch")
@app_commands.describe(
    source_branch="Branch to clone from Shebyyy/AnymeX",
    platforms="Platforms to build",
    build_type="Build type",
    pr_numbers="PR numbers (comma-separated)",
    tag_override="Version tag override",
)
@app_commands.autocomplete(source_branch=_sheby_branch_autocomplete)
@app_commands.choices(platforms=PLATFORM_CHOICES, build_type=BUILD_TYPE_CHOICES)
@has_allowed_role()
async def sheby_build(
    interaction: discord.Interaction,
    source_branch: str,
    platforms: app_commands.Choice[str],
    build_type: app_commands.Choice[str],
    pr_numbers: str = "",
    tag_override: str = "",
):
    await interaction.response.defer()

    discord_user_id = str(interaction.user.id)

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "source_branch": source_branch,
            "platforms": platforms.value,
            "build_type": build_type.value,
            "pr_numbers": pr_numbers,
            "tag_override": tag_override,
            "triggered_by": discord_user_id,
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{SHEBY_WORKFLOW_FILE}/dispatches",
            headers=gh_headers(),
            json=payload,
        ) as r:
            status = r.status
            body = await r.text()

    if status == 204:
        embed = discord.Embed(title="🔨 Sheby Build Triggered!", color=0x2EA043)
        embed.add_field(name="Source Repo",   value=f"`{SHEBY_SOURCE_REPO}`",   inline=True)
        embed.add_field(name="Branch",        value=f"`{source_branch}`",       inline=True)
        embed.add_field(name="Build Type",    value=f"`{build_type.value}`",    inline=True)
        embed.add_field(name="Platforms",     value=f"`{platforms.value}`",     inline=True)
        if pr_numbers:
            embed.add_field(name="PRs", value=pr_numbers, inline=True)
        embed.add_field(
            name="Tag",
            value=f"`{tag_override}`" if tag_override else "Auto-detect",
            inline=True,
        )
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        embed.description = "Build started — fetching run link…"

        run_id = None
        run_url = None
        async with aiohttp.ClientSession() as session:
            for _ in range(6):
                await asyncio.sleep(2)
                async with session.get(
                    f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{SHEBY_WORKFLOW_FILE}/runs?per_page=1&branch={GITHUB_BRANCH}",
                    headers=gh_headers(),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        runs = data.get("workflow_runs", [])
                        if runs and runs[0].get("status") in ("queued", "in_progress"):
                            run_id = runs[0]["id"]
                            run_url = runs[0]["html_url"]
                            break

        embed.add_field(
            name="View Run",
            value=f"[Open Run]({run_url})" if run_url else f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)",
            inline=False,
        )

        if run_id:
            embed.description = "Build started — click below to cancel if needed"

            view = CancelBuildView(run_id, label="Cancel Build")
            msg = await interaction.followup.send(embed=embed, view=view)
            bot.add_view(view, message_id=msg.id)
        else:
            embed.description = "Build started"
            await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Failed to Trigger Sheby Build",
            description=f"**Status:** `{status}`\n```{body[:1000]}```",
            color=0xDA3633,
        )
        await interaction.followup.send(embed=embed)

FORK_WORKFLOW_FILE = "fork_build_manual.yml"
FORK_PARENT_REPO   = "RyanYuuki/AnymeX"   # whose forks are listed


async def _fetch_anymex_forks() -> list[str]:
    """Return all fork full_names (owner/repo) of RyanYuuki/AnymeX via GitHub API."""
    forks: list[str] = []
    page = 1
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                f"{GITHUB_API}/repos/{FORK_PARENT_REPO}/forks?per_page=100&page={page}&sort=newest",
                headers=gh_headers(),
            ) as r:
                if r.status != 200:
                    break
                data = await r.json()
                if not data:
                    break
                forks.extend(f["full_name"] for f in data)
                if len(data) < 100:
                    break
                page += 1
    return forks


async def _fetch_fork_branches(fork_repo: str) -> list[str]:
    """Return all branch names from a given fork repo via GitHub API."""
    branches: list[str] = []
    page = 1
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                f"{GITHUB_API}/repos/{fork_repo}/branches?per_page=100&page={page}",
                headers=gh_headers(),
            ) as r:
                if r.status != 200:
                    break
                data = await r.json()
                if not data:
                    break
                branches.extend(b["name"] for b in data)
                if len(data) < 100:
                    break
                page += 1
    return branches


async def _fork_repo_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        all_forks = await _fetch_anymex_forks()
    except Exception:
        all_forks = [FORK_PARENT_REPO]

    filtered = [f for f in all_forks if current.lower() in f.lower()]
    return [app_commands.Choice(name=f, value=f) for f in filtered[:25]]


async def _fork_branch_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    # Read whichever fork the user has typed so far
    fork_repo = interaction.namespace.fork_repo or FORK_PARENT_REPO
    try:
        all_branches = await _fetch_fork_branches(fork_repo)
    except Exception:
        all_branches = ["main"]

    filtered = [b for b in all_branches if current.lower() in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in filtered[:25]]


@bot.tree.command(name="fork_build", description="Trigger a build from any fork of RyanYuuki/AnymeX")
@app_commands.describe(
    fork_repo="Fork repo to build from (e.g. someuser/AnymeX)",
    source_branch="Branch to clone from the selected fork",
    platforms="Platforms to build",
    build_type="Build type",
    tag_override="Version tag override",
)
@app_commands.autocomplete(fork_repo=_fork_repo_autocomplete, source_branch=_fork_branch_autocomplete)
@app_commands.choices(platforms=PLATFORM_CHOICES, build_type=BUILD_TYPE_CHOICES)
@has_allowed_role()
async def fork_build(
    interaction: discord.Interaction,
    fork_repo: str,
    source_branch: str,
    platforms: app_commands.Choice[str],
    build_type: app_commands.Choice[str],
    tag_override: str = "",
):
    await interaction.response.defer()

    discord_user_id = str(interaction.user.id)

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "source_repo": fork_repo,
            "source_branch": source_branch,
            "platforms": platforms.value,
            "build_type": build_type.value,
            "tag_override": tag_override,
            "triggered_by": discord_user_id,
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{FORK_WORKFLOW_FILE}/dispatches",
            headers=gh_headers(),
            json=payload,
        ) as r:
            status = r.status
            body = await r.text()

    if status == 204:
        embed = discord.Embed(title="🔨 Fork Build Triggered!", color=0x2EA043)
        embed.add_field(name="Source Repo",   value=f"`{fork_repo}`",         inline=True)
        embed.add_field(name="Branch",        value=f"`{source_branch}`",     inline=True)
        embed.add_field(name="Build Type",    value=f"`{build_type.value}`",  inline=True)
        embed.add_field(name="Platforms",     value=f"`{platforms.value}`",   inline=True)
        embed.add_field(
            name="Tag",
            value=f"`{tag_override}`" if tag_override else "Auto-detect",
            inline=True,
        )
        embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        embed.description = "Build started — fetching run link…"

        run_id = None
        run_url = None
        async with aiohttp.ClientSession() as session:
            for _ in range(6):
                await asyncio.sleep(2)
                async with session.get(
                    f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{FORK_WORKFLOW_FILE}/runs?per_page=1&branch={GITHUB_BRANCH}",
                    headers=gh_headers(),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        runs = data.get("workflow_runs", [])
                        if runs and runs[0].get("status") in ("queued", "in_progress"):
                            run_id = runs[0]["id"]
                            run_url = runs[0]["html_url"]
                            break

        embed.add_field(
            name="View Run",
            value=f"[Open Run]({run_url})" if run_url else f"[GitHub Actions](https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/actions)",
            inline=False,
        )

        if run_id:
            embed.description = "Build started — click below to cancel if needed"

            view = CancelBuildView(run_id, label="Cancel Build")
            msg = await interaction.followup.send(embed=embed, view=view)
            bot.add_view(view, message_id=msg.id)
        else:
            embed.description = "Build started"
            await interaction.followup.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Failed to Trigger Fork Build",
            description=f"**Status:** `{status}`\n```{body[:1000]}```",
            color=0xDA3633,
        )
        await interaction.followup.send(embed=embed)

# ── /translate command ────────────────────────────────────────────────────────
# Scans all 4 community JSONs in the repo, finds any reason text that hasn't
# been translated yet, runs _translate_reason on each one, and writes it back
# to GitHub — exactly the same as how edit_reason updates entries.

@bot.tree.command(
    name="translate",
    description="Scan all community lists and auto-translate any untranslated reasons to English",
)
@has_allowed_role()
async def translate_cmd(interaction: discord.Interaction):
    await interaction.response.defer()

    filepath_map = {
        "anime": FILE_ANIME,
        "manga": FILE_MANGA,
        "show":  FILE_SHOWS,
        "movie": FILE_MOVIES,
    }

    total_updated = 0
    summary_lines = []

    async with aiohttp.ClientSession() as session:
        for list_name, filepath in filepath_map.items():
            try:
                entries, sha = await github_read_json(session, filepath)
            except Exception as e:
                summary_lines.append(f"⚠️ Could not read `{filepath}`: {e}")
                continue

            if not isinstance(entries, list) or not entries:
                continue

            dirty = False  # only write back if something actually changed

            for entry in entries:
                reasons = entry.get("reasons", [])

                # Also handle legacy entries that only have a top-level "reason" string
                if not reasons and entry.get("reason"):
                    reasons = [{"text": entry["reason"]}]
                    entry["reasons"] = reasons

                for reason_obj in reasons:
                    original_text = reason_obj.get("text", "")
                    if not original_text:
                        continue
                    # Skip if already translated
                    if original_text.startswith("Translated: "):
                        continue

                    translated_text = await _translate_reason(session, original_text)

                    # _translate_reason returns the original unchanged if already English
                    if translated_text == original_text:
                        print(f"  ⏭️ [{list_name}] Skipped (already English or translation identical): {original_text[:60]}...")
                        continue

                    print(f"  ✅ [{list_name}] Translated: {original_text[:60]}... → {translated_text[:60]}...")
                    reason_obj["text"] = translated_text
                    reason_obj["translated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    dirty = True
                    total_updated += 1

                # Keep top-level "reason" field in sync with first reason (same as edit_reason)
                if dirty and entry.get("reasons"):
                    entry["reason"] = entry["reasons"][0].get("text", "")

            if dirty:
                ok = await github_write_json(
                    session, filepath, entries, sha,
                    f"translate: auto-translate untranslated reasons in {list_name}",
                )
                if ok:
                    summary_lines.append(f"✅ `{list_name}` — updated")
                else:
                    summary_lines.append(f"❌ `{list_name}` — write failed")
            else:
                summary_lines.append(f"☑️ `{list_name}` — nothing to translate")

    embed = discord.Embed(
        title="🌐 Auto-Translate Complete",
        description="\n".join(summary_lines) or "Nothing processed.",
        color=0x2EA043 if total_updated > 0 else 0x95a5a6,
    )
    embed.add_field(name="Reasons Updated", value=str(total_updated), inline=True)
    embed.set_footer(text=f"Run by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)


async def main():
    global _best_proxy_lock
    _best_proxy_lock = asyncio.Lock()  # must be created inside async context

    # Register moderation commands AFTER all referenced functions are defined
    import moderation
    moderation.setup(
        bot,
        github_read_json_fn=github_read_json,
        github_write_json_fn=github_write_json,
        userdata_repo=USERDATA_REPO,
        userdata_branch=USERDATA_BRANCH,
        read_users_fn=read_users,
        is_bot_admin_fn=is_bot_admin,
        send_log_fn=_send_log,
    )

    import hi_trigger
    hi_trigger.setup(bot)

    import ai_trigger
    ai_trigger.setup(bot)

    import source_trigger
    source_trigger.setup(bot)

    import trap_trigger
    trap_trigger.setup(
        bot,
        github_read_json_fn=github_read_json,
        github_write_json_fn=github_write_json,
        userdata_repo=USERDATA_REPO,
        userdata_branch=USERDATA_BRANCH,
    )

    import faq_trigger
    faq_trigger.setup(bot, get_faq_fn=lambda: FAQ_MAP)

    import rules_trigger
    rules_trigger.setup(bot, get_rules_fn=lambda: RULES_MAP)

    await start_health_server()
    # Load log queue in background — don't delay bot connect for a GitHub call
    asyncio.create_task(_load_log_queue())
    await start_bot_with_proxy()


if __name__ == "__main__":
    asyncio.run(main())


# ══════════════════════════════════════════════════════════════════════════════
