"""Launch Recall & Reflect locally and open it in your browser.

    python run.py
"""

import threading
import webbrowser

import uvicorn

from app.config import HOST, PORT


def _open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    threading.Timer(1.4, _open_browser).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False, log_level="info")
