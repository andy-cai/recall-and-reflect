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
CLOUD_DEFAULT_MODEL = "gemini-2.5-flash"
CLOUD_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite")
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
# substrings is refused.
CLOUD_MODEL_MARKERS = ("-cloud", "cloud)")

OLLAMA_TIMEOUT = 180.0         # seconds for a full (non-stream) generation (cold model loads are slow)
OLLAMA_CONNECT_TIMEOUT = 4.0   # seconds to detect "is Ollama up?"
OLLAMA_KEEP_ALIVE = "30m"      # keep the model warm between interactions

# --- Spaced repetition defaults (overridable in Settings) ---
DEFAULT_DAILY_TARGET = 20
DEFAULT_DESIRED_RETENTION = 0.90   # FSRS target recall probability
DEFAULT_NEW_PER_DAY = 10           # max brand-new cards introduced per day

# --- Reminders ---
NOTIFY_CHECK_INTERVAL_MIN = 30
NOTIFY_COOLDOWN_MIN = 180
