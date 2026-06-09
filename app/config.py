"""Application configuration.

Everything here is local-only by design. The app never talks to any remote
service except a *local* Ollama instance on this machine.
"""

import os
from pathlib import Path

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
DEFAULT_MODEL = "qwen2.5:7b"
EMBED_MODEL = "nomic-embed-text"

# Models that run in Ollama's CLOUD are blocked: they would send your notes
# off-device, which violates the local-only promise. Any tag matching these
# substrings is refused.
CLOUD_MODEL_MARKERS = ("-cloud", "cloud)")

OLLAMA_TIMEOUT = 90.0          # seconds for a full (non-stream) generation
OLLAMA_CONNECT_TIMEOUT = 4.0   # seconds to detect "is Ollama up?"
OLLAMA_KEEP_ALIVE = "30m"      # keep the model warm between interactions

# --- Spaced repetition defaults (overridable in Settings) ---
DEFAULT_DAILY_TARGET = 20
DEFAULT_DESIRED_RETENTION = 0.90   # FSRS target recall probability
DEFAULT_NEW_PER_DAY = 10           # max brand-new cards introduced per day

# --- Reminders ---
NOTIFY_CHECK_INTERVAL_MIN = 30
NOTIFY_COOLDOWN_MIN = 180
