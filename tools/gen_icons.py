"""Generate the app icon set from one design — pure stdlib, no Pillow.

Design: deep-forest rounded square, an open ochre ring (the recall loop), and a
cream dot completing the gap (the memory coming back). Outputs:

    web/icons/icon-512.png, icon-192.png   (manifest / install-as-app)
    web/favicon.ico                        (browser tab)
    app.ico                                (Windows desktop shortcut)

Run after editing:  python tools/gen_icons.py
"""

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# palette (matches web/css/styles.css)
BG_TOP = (0x26, 0x34, 0x2A)
BG_BOT = (0x13, 0x1D, 0x16)
OCHRE = (0xD5, 0x9A, 0x52)
CREAM = (0xEC, 0xE3, 0xD1)

GAP_DEG = 38.0        # half-angle of the ring opening
GAP_AT = -45.0        # gap centered top-right


def smooth(d: float) -> float:
    """SDF -> coverage with ~1px antialias (d in pixels, negative = inside)."""
    if d <= -0.75:
        return 1.0
    if d >= 0.75:
        return 0.0
    t = (0.75 - d) / 1.5
    return t * t * (3 - 2 * t)


def ang_dist(a: float, b: float) -> float:
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return d


def render(size: int) -> bytes:
    s = size / 512.0
    cx = cy = size / 2.0
    corner = 112.0 * s
    half = 236.0 * s
    ring_r = 148.0 * s
    ring_w = 64.0 * s
    dot_r = 44.0 * s

    cap1_a = math.radians(GAP_AT - GAP_DEG)
    cap2_a = math.radians(GAP_AT + GAP_DEG)
    caps = [(cx + ring_r * math.cos(a), cy + ring_r * math.sin(a)) for a in (cap1_a, cap2_a)]
    dot_c = (cx + ring_r * math.cos(math.radians(GAP_AT)),
             cy + ring_r * math.sin(math.radians(GAP_AT)))

    rows = []
    for y in range(size):
        row = bytearray()
        t = y / size
        bg = tuple(round(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            # rounded-square silhouette (everything clips to this)
            qx = max(abs(px - cx) - (half - corner), 0.0)
            qy = max(abs(py - cy) - (half - corner), 0.0)
            sq_cov = smooth(math.hypot(qx, qy) - corner)
            if sq_cov == 0.0:
                row += b"\x00\x00\x00\x00"
                continue

            r, g, b = bg
            d = math.hypot(px - cx, py - cy)
            theta = math.degrees(math.atan2(py - cy, px - cx))

            # ring body (excluded inside the gap) + rounded caps
            arc_d = abs(d - ring_r) - ring_w / 2 if ang_dist(theta, GAP_AT) > GAP_DEG else 1e9
            for kx, ky in caps:
                arc_d = min(arc_d, math.hypot(px - kx, py - ky) - ring_w / 2)
            cov = smooth(arc_d)
            if cov > 0:
                r = r + (OCHRE[0] - r) * cov
                g = g + (OCHRE[1] - g) * cov
                b = b + (OCHRE[2] - b) * cov

            cov = smooth(math.hypot(px - dot_c[0], py - dot_c[1]) - dot_r)
            if cov > 0:
                r = r + (CREAM[0] - r) * cov
                g = g + (CREAM[1] - g) * cov
                b = b + (CREAM[2] - b) * cov

            row += bytes((round(r), round(g), round(b), round(255 * sq_cov)))
        rows.append(bytes(row))
    return b"".join(rows)


def to_png(rgba: bytes, size: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    stride = size * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def bmp_entry(rgba: bytes, size: int) -> bytes:
    """32-bit BGRA ICO bitmap (bottom-up) + empty AND mask."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         size * size * 4, 0, 0, 0, 0)
    stride = size * 4
    body = bytearray()
    for y in range(size - 1, -1, -1):
        row = rgba[y * stride:(y + 1) * stride]
        for x in range(size):
            r, g, b, a = row[x * 4:x * 4 + 4]
            body += bytes((b, g, r, a))
    mask_stride = ((size + 31) // 32) * 4
    return header + bytes(body) + b"\x00" * (mask_stride * size)


def to_ico(entries: list[tuple[int, bytes]]) -> bytes:
    """entries: [(size, payload)] where payload is PNG or ICO-BMP bytes."""
    out = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    body = b""
    for size, payload in entries:
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                           len(payload), offset)
        body += payload
        offset += len(payload)
    return out + body


def main() -> None:
    icons_dir = ROOT / "web" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    renders = {size: render(size) for size in (512, 192, 256, 48, 32, 16)}

    (icons_dir / "icon-512.png").write_bytes(to_png(renders[512], 512))
    (icons_dir / "icon-192.png").write_bytes(to_png(renders[192], 192))
    (ROOT / "web" / "favicon.ico").write_bytes(to_ico([
        (48, to_png(renders[48], 48)),
        (32, to_png(renders[32], 32)),
        (16, to_png(renders[16], 16)),
    ]))
    (ROOT / "app.ico").write_bytes(to_ico([
        (256, to_png(renders[256], 256)),       # PNG entry (Vista+)
        (48, bmp_entry(renders[48], 48)),
        (32, bmp_entry(renders[32], 32)),
        (16, bmp_entry(renders[16], 16)),
    ]))
    print("Wrote web/icons/icon-{512,192}.png, web/favicon.ico, app.ico")


if __name__ == "__main__":
    main()
