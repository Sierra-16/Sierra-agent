from __future__ import annotations

from pathlib import Path

from make_sierra_avatar_transparent import (
    read_png,
    remove_edge_background,
    write_png,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "thinking.png"
TARGET = ROOT / "web" / "public" / "brand" / "sierra-thinking.png"


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source spritesheet: {SOURCE}")
    width, height, pixels = read_png(SOURCE)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    write_png(TARGET, width, height, remove_edge_background(width, height, pixels))
    print(f"wrote {TARGET} ({width}x{height})")


if __name__ == "__main__":
    main()
