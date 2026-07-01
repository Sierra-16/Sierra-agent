from __future__ import annotations

import math
import os
import random
import shutil
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "web" / "public" / "brand"


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
        start = y * width
        row = bytearray([0])
        for r, g, b, a in pixels[start : start + width]:
            row.extend((r, g, b, a))
        rows.append(bytes(row))

    raw = b"".join(rows)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def fill_rect(pixels, width, height, x0, y0, x1, y1, color):
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(width, int(x1))
    y1 = min(height, int(y1))
    for y in range(y0, y1):
        base = y * width
        for x in range(x0, x1):
            pixels[base + x] = color


def fill_circle(pixels, width, height, cx, cy, radius, color):
    r2 = radius * radius
    for y in range(max(0, int(cy - radius)), min(height, int(cy + radius + 1))):
        base = y * width
        for x in range(max(0, int(cx - radius)), min(width, int(cx + radius + 1))):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                pixels[base + x] = color


def fill_ellipse(pixels, width, height, cx, cy, rx, ry, color):
    if rx <= 0 or ry <= 0:
        return
    for y in range(max(0, int(cy - ry)), min(height, int(cy + ry + 1))):
        base = y * width
        for x in range(max(0, int(cx - rx)), min(width, int(cx + rx + 1))):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                pixels[base + x] = color


def fill_polygon(pixels, width, height, points, color):
    min_y = max(0, int(min(y for _, y in points)))
    max_y = min(height - 1, int(max(y for _, y in points)))
    for y in range(min_y, max_y + 1):
        xs = []
        for i, (x1, y1) in enumerate(points):
            x2, y2 = points[(i + 1) % len(points)]
            if y1 == y2:
                continue
            if min(y1, y2) <= y < max(y1, y2):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for left, right in zip(xs[0::2], xs[1::2]):
            fill_rect(pixels, width, height, math.floor(left), y, math.ceil(right), y + 1, color)


def draw_tree(pixels, width, height, x, base_y, scale, color=(10, 42, 31, 255)):
    trunk = (76, 48, 25, 255)
    fill_rect(pixels, width, height, x - scale * 0.08, base_y - scale * 0.42, x + scale * 0.08, base_y, trunk)
    for i in range(4):
        top = base_y - scale * (0.45 + i * 0.22)
        half = scale * (0.42 - i * 0.055)
        fill_polygon(
            pixels,
            width,
            height,
            [(x, top - scale * 0.38), (x - half, top + scale * 0.22), (x + half, top + scale * 0.22)],
            color,
        )


def generate_background(path: Path) -> None:
    width, height = 1600, 900
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(height):
        sky = blend((8, 22, 45), (14, 55, 78), min(y / 520, 1))
        ground = blend((18, 40, 30), (8, 17, 13), min(max((y - 520) / 380, 0), 1))
        color = sky if y < 610 else ground
        for _ in range(width):
            pixels.append((*color, 255))

    rng = random.Random(42)
    for _ in range(120):
        x = rng.randrange(0, width)
        y = rng.randrange(18, 330)
        size = rng.choice([2, 2, 3, 4])
        color = rng.choice([(190, 224, 255, 255), (111, 174, 220, 255), (255, 240, 190, 255)])
        fill_rect(pixels, width, height, x, y, x + size, y + size, color)

    fill_circle(pixels, width, height, 560, 145, 54, (255, 229, 171, 255))
    fill_circle(pixels, width, height, 590, 130, 56, (9, 33, 59, 255))

    mountain_sets = [
        (430, 385, 250, (34, 66, 101, 255), (99, 130, 167, 255)),
        (760, 330, 340, (42, 79, 119, 255), (121, 151, 184, 255)),
        (1120, 365, 300, (28, 61, 93, 255), (88, 121, 155, 255)),
    ]
    for cx, top, half, body, snow in mountain_sets:
        fill_polygon(pixels, width, height, [(cx, top), (cx - half, 615), (cx + half, 615)], body)
        fill_polygon(pixels, width, height, [(cx, top), (cx - half * 0.22, top + 95), (cx + half * 0.18, top + 92)], snow)

    fill_rect(pixels, width, height, 0, 520, 1600, 650, (12, 48, 70, 255))
    for y in range(530, 645, 15):
        for x in range(0, width, 72):
            if (x + y) % 3:
                fill_rect(pixels, width, height, x, y, x + 38, y + 3, (37, 90, 112, 255))

    for x in range(60, 1550, 95):
        draw_tree(pixels, width, height, x, 575 + (x % 4) * 12, 120 + (x % 5) * 10, (7, 45, 32, 255))
    for x in range(10, 1600, 70):
        draw_tree(pixels, width, height, x, 700 + (x % 3) * 28, 170 + (x % 7) * 10, (5, 34, 25, 255))

    fill_polygon(pixels, width, height, [(1170, 330), (1000, 725), (1420, 725)], (131, 91, 53, 255))
    fill_polygon(pixels, width, height, [(1170, 330), (1090, 725), (1510, 725)], (88, 59, 38, 255))
    fill_rect(pixels, width, height, 1162, 330, 1180, 730, (91, 50, 22, 255))
    fill_rect(pixels, width, height, 1265, 405, 1340, 575, (34, 75, 45, 255))
    fill_rect(pixels, width, height, 1288, 440, 1318, 535, (179, 129, 36, 255))

    for r, alpha in [(190, 36), (130, 60), (80, 95), (45, 160)]:
        color = (255, 120, 24, alpha)
        fill_circle(pixels, width, height, 445, 710, r, color)
    fill_circle(pixels, width, height, 445, 710, 45, (255, 193, 55, 255))
    fill_polygon(pixels, width, height, [(430, 735), (452, 620), (472, 735)], (255, 118, 25, 255))
    fill_polygon(pixels, width, height, [(456, 735), (490, 650), (505, 735)], (255, 190, 51, 255))

    for x, y in [(80, 760), (1420, 695), (1500, 765), (650, 545)]:
        fill_rect(pixels, width, height, x, y, x + 22, y + 40, (39, 27, 17, 255))
        fill_rect(pixels, width, height, x + 4, y + 8, x + 18, y + 32, (249, 179, 56, 255))

    write_png(path, width, height, pixels)


def generate_avatar(path: Path) -> None:
    width, height = 512, 512
    transparent = (0, 0, 0, 0)
    pixels = [transparent for _ in range(width * height)]

    outline = (106, 65, 18, 255)
    hair_shadow = (174, 117, 19, 255)
    hair = (255, 214, 67, 255)
    hair_light = (255, 235, 119, 255)
    skin = (255, 205, 171, 255)
    skin_shadow = (235, 154, 119, 255)
    leaf_dark = (17, 85, 43, 255)
    leaf = (53, 149, 49, 255)
    leaf_light = (118, 196, 59, 255)
    gold = (224, 164, 43, 255)
    gem = (48, 199, 238, 255)
    eye_dark = (14, 74, 25, 255)
    eye = (69, 177, 42, 255)
    white = (255, 255, 245, 255)

    fill_ellipse(pixels, width, height, 256, 474, 144, 24, (0, 0, 0, 46))

    # Hair mass and ears.
    fill_ellipse(pixels, width, height, 256, 218, 178, 185, outline)
    fill_ellipse(pixels, width, height, 256, 214, 166, 174, hair_shadow)
    fill_ellipse(pixels, width, height, 256, 190, 156, 142, hair)
    fill_ellipse(pixels, width, height, 148, 298, 48, 142, hair_shadow)
    fill_ellipse(pixels, width, height, 364, 298, 48, 142, hair_shadow)
    fill_ellipse(pixels, width, height, 142, 292, 38, 130, hair)
    fill_ellipse(pixels, width, height, 370, 292, 38, 130, hair)

    fill_polygon(pixels, width, height, [(132, 210), (46, 165), (87, 256)], outline)
    fill_polygon(pixels, width, height, [(380, 210), (466, 165), (425, 256)], outline)
    fill_polygon(pixels, width, height, [(129, 213), (64, 178), (93, 242)], skin)
    fill_polygon(pixels, width, height, [(383, 213), (448, 178), (419, 242)], skin)
    fill_polygon(pixels, width, height, [(90, 203), (70, 188), (91, 223)], skin_shadow)
    fill_polygon(pixels, width, height, [(422, 203), (442, 188), (421, 223)], skin_shadow)

    # Face and bangs.
    fill_ellipse(pixels, width, height, 256, 242, 122, 126, outline)
    fill_ellipse(pixels, width, height, 256, 244, 113, 116, skin)
    for points in [
        [(150, 158), (205, 330), (236, 160)],
        [(210, 142), (248, 326), (274, 148)],
        [(268, 148), (304, 326), (362, 160)],
        [(194, 152), (138, 262), (154, 153)],
        [(324, 152), (374, 262), (360, 153)],
    ]:
        fill_polygon(pixels, width, height, points, outline)
    for points in [
        [(154, 157), (207, 308), (229, 160)],
        [(214, 144), (248, 302), (269, 150)],
        [(272, 151), (304, 306), (356, 162)],
        [(197, 154), (146, 246), (157, 154)],
        [(320, 154), (366, 246), (354, 154)],
    ]:
        fill_polygon(pixels, width, height, points, hair)

    fill_ellipse(pixels, width, height, 207, 255, 28, 42, outline)
    fill_ellipse(pixels, width, height, 305, 255, 28, 42, outline)
    fill_ellipse(pixels, width, height, 207, 257, 21, 32, eye_dark)
    fill_ellipse(pixels, width, height, 305, 257, 21, 32, eye_dark)
    fill_ellipse(pixels, width, height, 211, 268, 15, 20, eye)
    fill_ellipse(pixels, width, height, 309, 268, 15, 20, eye)
    fill_circle(pixels, width, height, 198, 242, 7, white)
    fill_circle(pixels, width, height, 296, 242, 7, white)
    fill_rect(pixels, width, height, 240, 312, 274, 319, outline)
    fill_rect(pixels, width, height, 246, 313, 268, 319, skin_shadow)

    # Crown leaves, gem, and body.
    fill_rect(pixels, width, height, 150, 148, 362, 158, gold)
    for x in [158, 188, 318, 348]:
        fill_ellipse(pixels, width, height, x, 146, 23, 12, leaf_dark)
        fill_ellipse(pixels, width, height, x + 3, 144, 18, 9, leaf)
    fill_polygon(pixels, width, height, [(238, 134), (256, 101), (274, 134), (256, 165)], outline)
    fill_polygon(pixels, width, height, [(243, 134), (256, 111), (269, 134), (256, 156)], gem)
    fill_circle(pixels, width, height, 250, 126, 5, white)

    fill_polygon(pixels, width, height, [(154, 374), (256, 326), (358, 374), (398, 480), (114, 480)], outline)
    fill_polygon(pixels, width, height, [(164, 377), (256, 335), (348, 377), (380, 468), (132, 468)], leaf_dark)
    fill_polygon(pixels, width, height, [(174, 386), (256, 344), (338, 386), (324, 462), (188, 462)], leaf)
    fill_polygon(pixels, width, height, [(211, 365), (256, 427), (301, 365)], leaf_light)
    fill_rect(pixels, width, height, 184, 390, 328, 404, gold)
    fill_polygon(pixels, width, height, [(241, 394), (256, 374), (271, 394), (256, 414)], gem)

    # Pixel highlights.
    fill_rect(pixels, width, height, 202, 112, 246, 124, hair_light)
    fill_rect(pixels, width, height, 292, 122, 344, 134, hair_light)
    fill_rect(pixels, width, height, 167, 426, 196, 438, leaf_light)
    fill_rect(pixels, width, height, 319, 426, 348, 438, leaf_light)

    write_png(path, width, height, pixels)


def main() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    background_source = BRAND_DIR / "ChatGPT Image 2026年6月25日 15_04_41.png"
    avatar_source = BRAND_DIR / "ChatGPT Image 2026年6月25日 14_51_55.png"
    if background_source.exists():
        shutil.copy2(background_source, BRAND_DIR / "sierra-camp-bg.png")
    else:
        generate_background(BRAND_DIR / "sierra-camp-bg.png")
    if avatar_source.exists():
        shutil.copy2(avatar_source, BRAND_DIR / "sierra-avatar.png")
        try:
            from make_sierra_avatar_transparent import main as make_avatar_transparent

            make_avatar_transparent()
        except Exception:
            pass
    else:
        generate_avatar(BRAND_DIR / "sierra-avatar.png")


if __name__ == "__main__":
    main()
