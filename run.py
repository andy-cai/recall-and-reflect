"""Launch Recall & Reflect locally and open it in your browser.

    python run.py
"""

import sys
import threading
import webbrowser

if sys.version_info < (3, 10):
    sys.exit("Recall & Reflect needs Python 3.10 or newer (found "
             f"{sys.version.split()[0]}). Install a current Python from python.org; "
             "on Windows, delete the venv folder and run run.bat again.")

import uvicorn

from app.config import HOST, PORT


def _open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    threading.Timer(1.4, _open_browser).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False, log_level="info")
