from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDES = (
    ".git/",
    ".hg/",
    ".svn/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.pyc",
    "node_modules/",
    "tui/node_modules/",
    "dist/",
    "build/",
    ".next/",
    ".cache/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".env",
    ".env.*",
    "config.json",
    "config.local.json",
    "conversations/",
    "logs/",
    "tasks/",
    "memory/*.sqlite3",
    "memory/*.sqlite3-wal",
    "memory/*.sqlite3-shm",
    "memory/USER.md",
    "memory/MEMORY.md",
    "*.log",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.7z",
    "*.mp4",
    "*.mov",
    "*.mkv",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
)

_COMMIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{4,64}$")


@dataclass
class CheckpointResult:
    taken: bool
    reason: str = ""
    commit: str = ""
    error: str = ""


class CheckpointManager:
    """Transparent workspace snapshots using a shadow git store.

    This follows Hermes' shape: the model never sees this as a tool. The agent
    calls `new_turn()` once per user turn and `ensure_checkpoint()` before
    file-mutating tools. A directory is snapshotted at most once per turn.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_dir: str,
        path: str = "checkpoints/store",
        max_snapshots: int = 20,
        max_files: int = 30_000,
        timeout_seconds: int = 30,
    ):
        self.enabled = bool(enabled)
        self.base_dir = Path(base_dir).resolve()
        self.store = Path(path if os.path.isabs(path) else self.base_dir / path)
        self.max_snapshots = max(1, int(max_snapshots or 20))
        self.max_files = max(1, int(max_files or 30_000))
        self.timeout_seconds = max(5, min(120, int(timeout_seconds or 30)))
        self._checkpointed_dirs: set[str] = set()
        self._git_available: bool | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any] | None, *, base_dir: str) -> "CheckpointManager | None":
        config = config if isinstance(config, dict) else {}
        if config.get("enabled", False) is not True:
            return None
        return cls(
            enabled=True,
            base_dir=base_dir,
            path=config.get("path", "checkpoints/store"),
            max_snapshots=config.get("max_snapshots", 20),
            max_files=config.get("max_files", 30_000),
            timeout_seconds=config.get("timeout_seconds", 30),
        )

    def new_turn(self) -> None:
        self._checkpointed_dirs.clear()

    def ensure_checkpoint(self, working_dir: str, reason: str = "auto") -> CheckpointResult:
        if not self.enabled:
            return CheckpointResult(False, reason=reason)
        if self._git_available is None:
            self._git_available = shutil.which("git") is not None
        if not self._git_available:
            return CheckpointResult(False, reason=reason, error="git not found")

        root = Path(working_dir or ".").resolve()
        if not root.is_dir() or _too_broad(root):
            return CheckpointResult(False, reason=reason, error=f"invalid checkpoint root: {root}")

        key = str(root)
        if key in self._checkpointed_dirs:
            return CheckpointResult(False, reason=reason)
        self._checkpointed_dirs.add(key)

        try:
            return self._take(root, reason)
        except Exception as exc:
            return CheckpointResult(False, reason=reason, error=str(exc))

    def list_checkpoints(self, working_dir: str, limit: int | None = None) -> list[dict[str, Any]]:
        root = Path(working_dir or ".").resolve()
        if not (self.store / "HEAD").exists():
            return []
        ref = _ref_name(root)
        ok, stdout, _ = self._git(
            root,
            ["log", ref, "--format=%H|%h|%aI|%s", "-n", str(limit or self.max_snapshots)],
            allowed_returncodes={128},
        )
        if not ok or not stdout:
            return []
        checkpoints = []
        for line in stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                checkpoints.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "timestamp": parts[2],
                    "reason": parts[3],
                })
        return checkpoints

    def restore(
        self,
        working_dir: str,
        commit_hash: str,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Restore a workspace, or one relative file, to a checkpoint."""
        hash_error = _validate_commit_hash(commit_hash)
        if hash_error:
            return {"success": False, "error": hash_error}

        root = Path(working_dir or ".").resolve()
        if not root.is_dir() or _too_broad(root):
            return {"success": False, "error": f"invalid checkpoint root: {root}"}

        if file_path:
            path_error = _validate_file_path(file_path, root)
            if path_error:
                return {"success": False, "error": path_error}

        if not (self.store / "HEAD").exists():
            return {"success": False, "error": "no checkpoints exist for this directory"}

        ok_type, object_type, err = self._git(root, ["cat-file", "-t", commit_hash])
        if not ok_type or object_type != "commit":
            return {
                "success": False,
                "error": f"checkpoint '{commit_hash}' not found",
                "debug": err or None,
            }

        self._take(root, f"pre-rollback snapshot (restoring to {commit_hash[:8]})")

        index_file = self._index_path(root)
        restore_target = file_path or "."
        ok, _, err = self._git(
            root,
            ["checkout", commit_hash, "--", restore_target],
            index_file=index_file,
        )
        if not ok:
            return {
                "success": False,
                "error": f"restore failed: {err}",
                "debug": err or None,
            }

        ok_reason, reason, _ = self._git(root, ["log", "--format=%s", "-1", commit_hash])
        result = {
            "success": True,
            "restored_to": commit_hash[:8],
            "reason": reason if ok_reason and reason else "unknown",
            "directory": str(root),
        }
        if file_path:
            result["file"] = file_path
        return result

    def _take(self, root: Path, reason: str) -> CheckpointResult:
        if _count_files(root, self.max_files) > self.max_files:
            return CheckpointResult(False, reason=reason, error="workspace too large")

        init_error = self._init_store()
        if init_error:
            return CheckpointResult(False, reason=reason, error=init_error)

        index_file = self._index_path(root)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        ref = _ref_name(root)

        ok_ref, parent, _ = self._git(
            root,
            ["rev-parse", "--verify", ref + "^{commit}"],
            allowed_returncodes={128},
            index_file=index_file,
        )
        has_parent = ok_ref and bool(parent)
        if has_parent:
            self._git(root, ["read-tree", parent], index_file=index_file, allowed_returncodes={128})
        elif index_file.exists():
            index_file.unlink()

        ok, _, err = self._git(root, ["add", "-A"], index_file=index_file)
        if not ok:
            return CheckpointResult(False, reason=reason, error=err)

        if has_parent:
            ok_diff, _, _ = self._git(
                root,
                ["diff-index", "--cached", "--quiet", parent],
                allowed_returncodes={1},
                index_file=index_file,
            )
            if ok_diff:
                return CheckpointResult(False, reason=reason)
        else:
            ok_ls, files, _ = self._git(root, ["ls-files", "--cached"], index_file=index_file)
            if ok_ls and not files.strip():
                return CheckpointResult(False, reason=reason)

        ok_tree, tree, err = self._git(root, ["write-tree"], index_file=index_file)
        if not ok_tree or not tree:
            return CheckpointResult(False, reason=reason, error=err)

        commit_args = ["commit-tree", tree, "-m", reason]
        if has_parent:
            commit_args = ["commit-tree", tree, "-p", parent, "-m", reason]
        ok_commit, commit, err = self._git(root, commit_args, index_file=index_file)
        if not ok_commit or not commit:
            return CheckpointResult(False, reason=reason, error=err)

        update_args = ["update-ref", ref, commit]
        if has_parent:
            update_args.append(parent)
        ok_update, _, err = self._git(root, update_args)
        if not ok_update:
            return CheckpointResult(False, reason=reason, error=err)

        self._write_project_meta(root)
        self._prune(root, ref)
        return CheckpointResult(True, reason=reason, commit=commit)

    def _init_store(self) -> str:
        self.store.mkdir(parents=True, exist_ok=True)
        (self.store / "indexes").mkdir(exist_ok=True)
        (self.store / "projects").mkdir(exist_ok=True)

        if not (self.store / "HEAD").exists():
            env = _isolated_git_env()
            result = subprocess.run(
                ["git", "init", "--bare", str(self.store)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                env=env,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return result.stderr.strip() or "git init failed"
            self._git(self.base_dir, ["config", "user.email", "sierra@local"])
            self._git(self.base_dir, ["config", "user.name", "Sierra Checkpoint"])
            self._git(self.base_dir, ["config", "commit.gpgsign", "false"])
            info_dir = self.store / "info"
            info_dir.mkdir(exist_ok=True)
            (info_dir / "exclude").write_text(
                "\n".join(DEFAULT_EXCLUDES) + "\n",
                encoding="utf-8",
            )
        return ""

    def _index_path(self, root: Path) -> Path:
        return self.store / "indexes" / _project_hash(root)

    def _write_project_meta(self, root: Path) -> None:
        meta_path = self.store / "projects" / f"{_project_hash(root)}.json"
        payload = {"workdir": str(root), "updated_at": time.time()}
        meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _prune(self, root: Path, ref: str) -> None:
        # Keep pruning conservative for now. Listing is bounded by
        # `max_snapshots`; destructive history rewriting can be added later
        # with the same care Hermes gives its shared store GC.
        return

    def _git(
        self,
        root: Path,
        args: list[str],
        *,
        allowed_returncodes: set[int] | None = None,
        index_file: Path | None = None,
    ) -> tuple[bool, str, str]:
        env = _isolated_git_env()
        env["GIT_DIR"] = str(self.store)
        env["GIT_WORK_TREE"] = str(root)
        if index_file is not None:
            env["GIT_INDEX_FILE"] = str(index_file)
        else:
            env.pop("GIT_INDEX_FILE", None)

        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        allowed_returncodes = allowed_returncodes or set()
        ok = result.returncode == 0
        if not ok and result.returncode in allowed_returncodes:
            return False, result.stdout.strip(), result.stderr.strip()
        return ok, result.stdout.strip(), result.stderr.strip()


def _isolated_git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_NAMESPACE"):
        env.pop(key, None)
    return env


def _project_hash(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _ref_name(root: Path) -> str:
    return f"refs/sierra/{_project_hash(root)}"


def _validate_commit_hash(commit_hash: str) -> str | None:
    if not commit_hash or not str(commit_hash).strip():
        return "empty commit hash"
    commit_hash = str(commit_hash).strip()
    if commit_hash.startswith("-"):
        return f"invalid commit hash: {commit_hash!r}"
    if not _COMMIT_HASH_RE.match(commit_hash):
        return f"invalid commit hash: {commit_hash!r}"
    return None


def _validate_file_path(file_path: str, root: Path) -> str | None:
    raw = str(file_path or "").strip()
    if not raw:
        return "empty file path"
    path = Path(raw)
    if path.is_absolute():
        return f"file path must be relative: {raw!r}"
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return f"file path escapes the workspace: {raw!r}"
    return None


def _too_broad(root: Path) -> bool:
    home = Path.home().resolve()
    return root == Path(root.anchor).resolve() or root == home


def _count_files(root: Path, stop_after: int) -> int:
    count = 0
    try:
        for path in root.rglob("*"):
            if _is_skipped_path(root, path):
                continue
            if path.is_file():
                count += 1
                if count > stop_after:
                    break
    except OSError:
        return stop_after + 1
    return count


def _is_skipped_path(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return True
    parts = set(rel.split("/"))
    return any(part in {".git", ".venv", "venv", "node_modules", "__pycache__"} for part in parts)
