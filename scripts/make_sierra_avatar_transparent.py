from __future__ import annotations

import struct
import zlib
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "web" / "public" / "brand"
SOURCE = BRAND_DIR / "ChatGPT Image 2026年6月25日 14_51_55.png"
TARGET = BRAND_DIR / "sierra-avatar.png"


def _chunks(data: bytes):
    pos = 8
    while pos < len(data):
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + size]
        yield kind, chunk_data
        pos += 12 + size


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")

    width = height = color_type = bit_depth = None
    payload = bytearray()
    for kind, chunk_data in _chunks(data):
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif kind == b"IDAT":
            payload.extend(chunk_data)

    if width is None or height is None or bit_depth != 8 or color_type not in {2, 6}:
        raise ValueError("only 8-bit RGB/RGBA PNG files are supported")

    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(bytes(payload))
    rows: list[bytearray] = []
    pos = 0
    prev = bytearray(stride)
    bpp = channels
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos : pos + stride])
        pos += stride
        for i, value in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                row[i] = (value + left) & 0xFF
            elif filter_type == 2:
                row[i] = (value + up) & 0xFF
            elif filter_type == 3:
                row[i] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (value + _paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"unsupported PNG filter {filter_type}")
        rows.append(row)
        prev = row

    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for x in range(width):
            i = x * channels
            r, g, b = row[i], row[i + 1], row[i + 2]
            a = row[i + 3] if channels == 4 else 255
            pixels.append((r, g, b, a))
    return width, height, pixels


def write_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = bytearray([0])
        for r, g, b, a in pixels[y * width : (y + 1) * width]:
            row.extend((r, g, b, a))
        rows.append(bytes(row))
    raw = b"".join(rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def is_background(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    if a < 8:
        return True
    high = min(r, g, b) >= 218
    neutral = max(r, g, b) - min(r, g, b) <= 24
    return high and neutral


def remove_edge_background(width: int, height: int, pixels: list[tuple[int, int, int, int]]):
    visited = [False] * (width * height)
    queue: deque[int] = deque()

    def enqueue(index: int) -> None:
        if not visited[index] and is_background(pixels[index]):
            visited[index] = True
            queue.append(index)

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(height):
        enqueue(y * width)
        enqueue(y * width + width - 1)

    while queue:
        index = queue.popleft()
        x = index % width
        y = index // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                enqueue(ny * width + nx)

    result = list(pixels)
    for index, should_clear in enumerate(visited):
        if should_clear:
            r, g, b, _ = result[index]
            result[index] = (r, g, b, 0)
    return result


def main() -> None:
    source = SOURCE if SOURCE.exists() else TARGET
    width, height, pixels = read_png(source)
    pixels = remove_edge_background(width, height, pixels)
    write_png(TARGET, width, height, pixels)


if __name__ == "__main__":
    main()
