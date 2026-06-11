"""Vendor KaTeX locally (one-time, needs internet).

Downloads the official KaTeX release and unpacks katex.min.css, katex.min.js
and the fonts into web/vendor/katex/, so math renders fully offline and the
app never touches a CDN. Run from the repo root:

    python tools/get_katex.py
"""

import io
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.16.11"
URL = f"https://github.com/KaTeX/KaTeX/releases/download/v{VERSION}/katex.tar.gz"
DEST = Path(__file__).resolve().parent.parent / "web" / "vendor" / "katex"
KEEP = ("katex/katex.min.css", "katex/katex.min.js", "katex/fonts/")


def main() -> None:
    print(f"Downloading KaTeX v{VERSION} …")
    with urllib.request.urlopen(URL, timeout=60) as resp:
        data = resp.read()
    DEST.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith(KEEP):
                continue
            rel = Path(member.name).relative_to("katex")
            out = DEST / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tar.extractfile(member).read())
            count += 1
    print(f"Done — {count} files in {DEST}. Math now renders offline.")


if __name__ == "__main__":
    main()
