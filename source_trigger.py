# ══════════════════════════════════════════════════════════════════════════════
# source_trigger.py  —  Auto-send guide link when someone mentions sources/extensions
# ══════════════════════════════════════════════════════════════════════════════

import re
import unicodedata
import aiohttp
import discord

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

GUIDE_URL       = "https://anymex-extensions.vercel.app/guides"
EXTENSIONS_API  = "https://anymex-extensions.vercel.app/api/extensions"

# Only reply in this channel (set to None to reply everywhere)
ALLOWED_CHANNEL_ID = 1496732120511414332

# Ignore these roles — bot won't reply to members who have any of these roles
IGNORE_ROLE_IDS = {
    1496743097395314829,   # Owner
    1496743497091252254,   # Admin
    1496581599557582950,   # Mod
    1497134255954726912,   # Nub dev
}

# Ignore these members — bot won't reply to them regardless of roles
IGNORE_USER_IDS = {
    826730448688250890,   # bakabakaidiot
    1331083395614380090,  # devta.exe
}

# Cooldown per channel (seconds) — prevents spam
COOLDOWN_SECONDS = 30

# ─────────────────────────────────────────────────────────────────────────────
# Keyword patterns
# ─────────────────────────────────────────────────────────────────────────────

# Words that indicate someone is asking about sources
_SOURCE_KEYWORDS_RAW = re.compile(
    r"\b(source|sources|src|sauce)\b",
    re.IGNORECASE,
)

# Context-aware check — exclude "source code", "open source", etc.
def _is_asking_about_sources(text: str) -> bool:
    """Check if someone is asking about AnymeX sources (not source code / open source)."""
    if not _SOURCE_KEYWORDS_RAW.search(text):
        return False
    if re.search(r"\b(open[\s-]*source|source[\s-]*code|source[\s-]*file|source[\s-]*of|source[\s-]*repo(?:sitory)?|source[\s-]*is[\s-]*on)\b", text, re.IGNORECASE):
        return False
    return True

# Words that indicate someone is asking about extensions
_EXTENSION_KEYWORDS = re.compile(
    r"\b(extension|extensions|ext|addon|add-on|add-ons|plugin|plugins|repo|repos|repository)\b",
    re.IGNORECASE,
)

# Question patterns — "how to add", "where to find", etc.
_QUESTION_PATTERNS = re.compile(
    r"\b(how\s+(to|do|can)|where\s+(to|is|are|can|do)|where's|can\s+i|want\s+to|need\s+to|looking\s+for|help\s+(me\s+)?(?:add|find|get))\b",
    re.IGNORECASE,
)

# Problem/complaint patterns — "not working", "broken", "can't play", etc.
_PROBLEM_KEYWORDS = re.compile(
    r"\b("
    r"not\s+working|isn't\s+working|isnt\s+working|doesn't\s+work|doesnt\s+work|won't\s+work|wont\s+work|"
    r"not\s+loading|won't\s+load|wont\s+load|doesn't\s+load|doesnt\s+load|"
    r"broken|broke|down|dead|crashed|crash|"
    r"can't\s+(?:play|watch|stream|load|open|access|find|use|install|download)|cant\s+(?:play|watch|stream|load|open|access|find|use|install|download)|"
    r"no\s+(?:source|sources|extension|extensions|video|episodes|results|content)|"
    r"empty|blank|nothing\s+(?:shows|shows\s+up|works|plays)|"
    r"error|fail|failed|"
    r"stopped\s+working|keep\s+(?:getting|showing)|"
    r"not\s+(?:showing|playing|loading|found|available|supported)|"
    r"missing|disappeared|gone|"
    r"how\s+do\s+i\s+(?:fix|add|get|use|install|download)|"
    r"can't\s+install|cant\s+install|unable\s+to\s+(?:install|download|add|use|find|load)|"
    r"can't\s+download|cant\s+download|"
    r"not\s+installed|not\s+found|"
    r"doesn't\s+show|doesnt\s+show|"
    r"how\s+to\s+(?:install|download|add|setup|set\s+up|use)"
    r")\b",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Extension name matching (fuzzy)
# ─────────────────────────────────────────────────────────────────────────────

_ext_names: list[str] = []
_ext_names_lower: list[str] = []
_ext_last_fetch: float = 0
_EXT_CACHE_TTL = 30 * 60  # 30 minutes


def _normalize_for_match(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase, strip separators, normalize unicode."""
    text = text.lower().strip()
    text = re.sub(r"[\s\-_.:;!?,'\"()\\/\[\]{}]", "", text)
    text = unicodedata.normalize("NFKC", text)
    return text


async def _fetch_extension_names() -> list[str]:
    """Fetch all extension names from the API (cached for 30 min)."""
    global _ext_names, _ext_names_lower, _ext_last_fetch
    import time

    if _ext_names and time.time() - _ext_last_fetch < _EXT_CACHE_TTL:
        return _ext_names

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                EXTENSIONS_API,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    names = set()
                    for ext in data:
                        name = ext.get("name", "").strip()
                        if name and len(name) >= 3:
                            names.add(name)
                    _ext_names = sorted(names)
                    _ext_names_lower = [_normalize_for_match(n) for n in _ext_names]
                    _ext_last_fetch = time.time()
                    print(f"[source_trigger] Loaded {len(_ext_names)} extension names from API")
    except Exception as e:
        print(f"[source_trigger] Failed to fetch extensions: {e}")

    return _ext_names


def _find_matching_extension(text: str) -> str | None:
    """Check if text contains any known extension name (with fuzzy matching)."""
    if not _ext_names:
        return None

    normalized_text = _normalize_for_match(text)

    # Substring match against normalized names
    for i, norm_name in enumerate(_ext_names_lower):
        if len(norm_name) >= 4 and norm_name in normalized_text:
            return _ext_names[i]

    # Check original words for closer match
    words = re.findall(r"\b[\w\-]+\b", text.lower())
    for word in words:
        norm_word = _normalize_for_match(word)
        if len(norm_word) < 3:
            continue

        # Exact match
        for i, norm_name in enumerate(_ext_names_lower):
            if norm_name == norm_word:
                return _ext_names[i]

        # Fuzzy: prefix match (catches "animepah" → "animepahe")
        if len(norm_word) >= 5:
            for i, norm_name in enumerate(_ext_names_lower):
                if norm_name.startswith(norm_word) or norm_word.startswith(norm_name):
                    return _ext_names[i]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Cooldown tracker
# ─────────────────────────────────────────────────────────────────────────────

_last_triggered: dict[int, float] = {}  # channel_id → timestamp


def _is_on_cooldown(channel_id: int) -> bool:
    import time
    now = time.time()
    last = _last_triggered.get(channel_id, 0)
    if now - last < COOLDOWN_SECONDS:
        return True
    _last_triggered[channel_id] = now
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Core logic  —  ALWAYS sends only the guide link
# ─────────────────────────────────────────────────────────────────────────────

_bot = None


async def _handle(message: discord.Message):
    if message.author.bot:
        return

    # Skip ignored members
    if message.author.id in IGNORE_USER_IDS:
        return

    # Skip members with ignored roles
    if IGNORE_ROLE_IDS and message.member:
        if any(role.id in IGNORE_ROLE_IDS for role in message.member.roles):
            return

    # Only reply in the allowed channel
    if ALLOWED_CHANNEL_ID and message.channel.id != ALLOWED_CHANNEL_ID:
        return

    content = message.content
    if not content or len(content) < 3:
        return

    # Make sure extension names are loaded
    await _fetch_extension_names()

    # Check what the message is about
    has_source_kw = _is_asking_about_sources(content)
    has_ext_kw = bool(_EXTENSION_KEYWORDS.search(content))
    is_question = bool(_QUESTION_PATTERNS.search(content))
    matched_ext = _find_matching_extension(content)

    # Check if message has a problem/complaint keyword
    has_problem = bool(_PROBLEM_KEYWORDS.search(content))

    # Decide whether to trigger — everything sends the guide link
    should_trigger = False
    match_reason = ""

    if has_source_kw:
        should_trigger = True
        match_reason = "mentioned sources"
    elif has_ext_kw:
        should_trigger = True
        match_reason = "mentioned extensions"
    elif matched_ext and (is_question or has_problem):
        # Named a specific extension + asking or reporting a problem
        should_trigger = True
        match_reason = f"asked about extension: {matched_ext}"
    elif matched_ext:
        # Just named an extension — only trigger on short messages
        if len(content.split()) <= 5:
            should_trigger = True
            match_reason = f"mentioned extension: {matched_ext}"
    elif has_problem and (has_source_kw or has_ext_kw or matched_ext):
        # Problem + source/ext context (already covered above, but just in case)
        should_trigger = True
        match_reason = "reported a problem with sources/extensions"
    elif has_problem and not has_source_kw and not has_ext_kw:
        # Problem keyword alone — trigger if it seems AnymeX-related
        # Only respond if the message is short-ish (likely about the app, not random conversation)
        if len(content.split()) <= 10:
            should_trigger = True
            match_reason = "reported a problem (likely source-related)"
    elif is_question and not has_source_kw and not has_ext_kw:
        # Question pattern alone ("how to add?", "where to download?") — short messages likely about the app
        if len(content.split()) <= 8:
            should_trigger = True
            match_reason = "asked a question (likely source-related)"

    if not should_trigger:
        return

    # Cooldown check
    if _is_on_cooldown(message.channel.id):
        return

    print(f"[source_trigger] Triggered by {message.author} in #{message.channel}: {match_reason}")

    # Always just the guide link
    response = f"📖 <{GUIDE_URL}>"

    try:
        await message.reply(response, mention_author=False)
        print(f"[source_trigger] Sent guide link ✅")
    except Exception as e:
        print(f"[source_trigger] Failed to reply: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

def setup(bot: discord.Client):
    global _bot
    _bot = bot

    @bot.listen("on_message")
    async def on_message_source(message: discord.Message):
        await _handle(message)

    # Pre-fetch extension names on startup
    @bot.listen("on_ready")
    async def on_ready_source():
        await _fetch_extension_names()

    print("✅ source_trigger loaded — watching for source/extension mentions (guide link only)")
