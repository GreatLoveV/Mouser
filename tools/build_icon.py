"""Builds web/mouser.ico from web/icon.svg (Windows shortcut and tray icon).

Each size is rendered separately by headless Chrome or Edge, so small sizes are
rasterized at their own resolution. Frames up to 64 px are stored as classic
32-bit bitmaps (what the tray and old APIs expect); 128 and 256 px as PNG.
Standard library only.

    python tools/build_icon.py [--preview DIR]   # --preview also keeps the PNGs
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "web", "icon.svg")
ICO = os.path.join(ROOT, "web", "mouser.ico")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def browser() -> str:
    for p in (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
              r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"):
        p = os.path.expandvars(p)
        if os.path.isfile(p):
            return p
    sys.exit("Chrome or Edge is needed to render the icon")


def render(size: int, workdir: str) -> bytes:
    svg = open(SVG, encoding="utf-8").read()
    html = os.path.join(workdir, f"icon{size}.html")
    out = os.path.join(workdir, f"icon{size}.png")
    with open(html, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><style>html,body{{margin:0;background:transparent}}svg{{display:block;width:{size}px;height:{size}px}}</style>{svg}")
    subprocess.run([browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--user-data-dir={os.path.join(workdir, 'profile')}", "--default-background-color=00000000",
                    f"--window-size={size},{size}", f"--screenshot={out}", "file:///" + html.replace("\\", "/")],
                   check=True, capture_output=True, timeout=60)
    return open(out, "rb").read()


def png_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Minimal PNG decoder for 8-bit RGBA / RGB, non-interlaced (what Chrome writes)."""
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or interlace:
                raise ValueError("unsupported PNG layout")
            bpp = 4 if ctype == 6 else 3
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    if bpp == 3:
        rows = [b"".join(r[i:i + 3] + b"\xff" for i in range(0, len(r), 3)) for r in rows]
    return w, h, b"".join(rows)


def dib(size: int, rgba: bytes) -> bytes:
    """32-bit BGRA bitmap with AND mask, bottom-up, as an .ico frame."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytearray()
    for y in range(size - 1, -1, -1):
        row = rgba[y * size * 4:(y + 1) * size * 4]
        for x in range(size):
            r, g, b, a = row[x * 4:x * 4 + 4]
            pixels += bytes((b, g, r, a))
    mask_stride = ((size + 31) // 32) * 4
    mask = bytes(mask_stride * size)  # alpha does the work; the AND mask stays clear
    return header + bytes(pixels) + mask


def main():
    keep = sys.argv[sys.argv.index("--preview") + 1] if "--preview" in sys.argv else None
    work = tempfile.mkdtemp(prefix="mouser-icon-")
    frames = []
    try:
        for s in SIZES:
            png = render(s, work)
            w, h, rgba = png_rgba(png)
            if (w, h) != (s, s):
                raise SystemExit(f"rendered {w}x{h}, wanted {s}x{s}")
            frames.append((s, png if s >= 128 else dib(s, rgba)))
            if keep:
                os.makedirs(keep, exist_ok=True)
                open(os.path.join(keep, f"icon-{s}.png"), "wb").write(png)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    body = b""
    for s, data in frames:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    with open(ICO, "wb") as f:
        f.write(out + body)
    print(f"wrote {ICO} ({len(frames)} sizes: {', '.join(str(s) for s, _ in frames)})")


if __name__ == "__main__":
    main()
