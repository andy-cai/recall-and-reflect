"""Application configuration.

Everything here is local-only by design. The app never talks to any remote
service except a *local* Ollama instance on this machine.
"""

import os
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE lines) so secrets like GEMINI_API_KEY can live
    in a git-ignored file instead of the shell environment. Real environment
    variables always win; this never overrides one."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

APP_NAME = "Recall & Reflect"
APP_VERSION = "0.1.0"

# --- Paths ---
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
DATA_DIR = ROOT_DIR / "data"
WEB_DIR = ROOT_DIR / "web"
SEEDS_DIR = ROOT_DIR / "seeds"

DATA_DIR.mkdir(exist_ok=True)

# DB path can be overridden (e.g. for tests) via RR_DB_PATH.
DB_PATH = Path(os.environ["RR_DB_PATH"]) if os.environ.get("RR_DB_PATH") else DATA_DIR / "recall.db"

# --- Server ---
HOST = "127.0.0.1"   # loopback only — not reachable from the network
PORT = 8765

# --- Ollama (local only) ---
OLLAMA_BASE_URL = "http://localhost:11434"

# Preferred local generation/grading model. Falls back to whatever local
# instruct model is installed if this exact tag is missing.
# qwen3:14b is the best all-round default for technical Q/A on a 12-16GB GPU;
# qwen3:30b-a3b (MoE) if you have 24GB+; phi4:14b is a strong STEM alternative.
DEFAULT_MODEL = "qwen3:14b"
EMBED_MODEL = "nomic-embed-text"

# --- Cloud assist (strictly opt-in) ---
# Used ONLY for per-click actions you explicitly invoke (e.g. "Improve with
# Gemini" on a card). Off by default; requires GEMINI_API_KEY (free tier at
# https://aistudio.google.com) AND the Settings toggle. Reviews, capture chat,
# and grading never touch the cloud.
# Google retires Gemini models roughly yearly (gemini-2.5-flash: shutdown
# 2026-10-16), so the live list comes from the API's models endpoint
# (cloud.available_models); these are only the preference order and the
# fallback when that listing can't be fetched. Replacement named by Google's
# deprecations page: gemini-3.5-flash.
CLOUD_DEFAULT_MODEL = "gemini-3.5-flash"
CLOUD_MODELS = ("gemini-3.5-flash", "gemini-3.5-flash-lite")
CLOUD_MODELS_TTL_S = 6 * 3600   # how long a fetched model list is trusted
CLOUD_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Default style for generated questions/answers — editable in Settings.
DEFAULT_GEN_STYLE = (
    "Root answers in the physics: name the governing equation, the physical "
    "mechanism behind it, and the condition where it breaks down. Prefer "
    "why/how/when-does-it-fail questions over definition recall. Use $...$ "
    "TeX for math."
)

# Models that run in Ollama's CLOUD are blocked: they would send your notes
# off-device, which violates the local-only promise. Any tag matching these
# substrings is refused. Ollama names them both ways ("gpt-oss:120b-cloud" and
# "gemma4:cloud"); /api/tags also marks them with remote_host / remote_model,
# which llm.local_models() checks too, so a future naming scheme can't slip by.
CLOUD_MODEL_MARKERS = ("-cloud", ":cloud", "cloud)")

OLLAMA_TIMEOUT = 180.0         # seconds for a full (non-stream) generation (cold model loads are slow)
OLLAMA_CONNECT_TIMEOUT = 4.0   # seconds to detect "is Ollama up?"
OLLAMA_KEEP_ALIVE = "30m"      # keep the model warm between interactions

# Context window requested on EVERY call (and the warm-up). Ollama's own default
# is only 4k on GPUs under 24 GB, which a Reflect transcript plus a reasoning
# trace can overflow, silently dropping the system prompt. One fixed value for
# both models on purpose: Ollama reloads a model whenever num_ctx changes, which
# would stall reviews. 8k fits an 8 GB laptop GPU with a 4-9B model; raise it
# with RR_NUM_CTX=16384 on a bigger card. App inputs are capped to fit within it.
OLLAMA_NUM_CTX = max(2048, int(os.environ.get("RR_NUM_CTX", "8192") or 8192))

# --- Spaced repetition defaults (overridable in Settings) ---
DEFAULT_DAILY_TARGET = 20
DEFAULT_DESIRED_RETENTION = 0.90   # FSRS target recall probability
DEFAULT_NEW_PER_DAY = 10           # max brand-new cards introduced per day

# --- Reminders ---
NOTIFY_CHECK_INTERVAL_MIN = 30
NOTIFY_COOLDOWN_MIN = 180
