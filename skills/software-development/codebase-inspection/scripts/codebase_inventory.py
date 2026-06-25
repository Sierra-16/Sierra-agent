"""Print a dependency-free JSON inventory for a directory inside the workspace."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
MAX_FILES = 50_000


def main() -> int:
    workspace = Path.cwd().resolve()
    requested = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    target = (workspace / requested).resolve() if not requested.is_absolute() else requested.resolve()
    try:
        target.relative_to(workspace)
    except ValueError:
        print(json.dumps({"error": "target must stay inside the workspace"}))
        return 2
    if not target.is_dir():
        print(json.dumps({"error": f"directory not found: {requested}"}))
        return 2

    extensions: Counter[str] = Counter()
    top_level: Counter[str] = Counter()
    total_bytes = 0
    file_count = 0
    truncated = False

    for root, dirs, files in os.walk(target, followlinks=False):
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in EXCLUDED_DIRS and not name.startswith(".")
        )
        root_path = Path(root)
        for filename in sorted(files):
            path = root_path / filename
            if path.is_symlink():
                continue
            try:
                relative = path.relative_to(target)
                size = path.stat().st_size
            except (OSError, ValueError):
                continue
            extension = path.suffix.lower() or "[no extension]"
            extensions[extension] += 1
            top_level[relative.parts[0]] += 1
            total_bytes += size
            file_count += 1
            if file_count >= MAX_FILES:
                truncated = True
                break
        if truncated:
            break

    payload = {
        "root": str(target),
        "files": file_count,
        "bytes": total_bytes,
        "truncated": truncated,
        "extensions": dict(extensions.most_common()),
        "top_level": dict(top_level.most_common()),
        "excluded_directories": sorted(EXCLUDED_DIRS),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
