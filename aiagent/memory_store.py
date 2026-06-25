import os
import tempfile


class MemoryStore:
    VALID_TARGETS = {"memory", "user"}

    def __init__(self, base_dir="memory", max_memory_chars=2200, max_user_chars=1375):
        if not os.path.isabs(base_dir):
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", base_dir))
        self.base_dir = base_dir
        self.memory_path = os.path.join(base_dir, "MEMORY.md")
        self.user_path = os.path.join(base_dir, "USER.md")
        self.max_memory_chars = max_memory_chars
        self.max_user_chars = max_user_chars
        
        os.makedirs(base_dir, exist_ok=True)
        for p in [self.memory_path, self.user_path]:
            if not os.path.exists(p):
                self._save_to_disk([], p)          # 创建空文件
        
        self.refresh()


    def _load_from_disk(self, path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
        return [line.strip() for line in lines if line.strip()]

    def _save_to_disk(self, entries, path):
        directory = os.path.dirname(path)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory,
                delete=False,
            ) as f:
                temp_path = f.name
                f.write("\n".join(entries) + "\n")
            os.replace(temp_path, path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def configure(self, max_memory_chars=None, max_user_chars=None):
        if max_memory_chars is not None:
            self.max_memory_chars = max(1, int(max_memory_chars))
        if max_user_chars is not None:
            self.max_user_chars = max(1, int(max_user_chars))
        return self

    @staticmethod
    def _normalize_entry(content):
        return " ".join(str(content or "").split())

    @staticmethod
    def _total_chars(entries):
        return sum(len(entry) for entry in entries)

    def _validate_target(self, target):
        if target not in self.VALID_TARGETS:
            return {"ok": False, "error": f"未知记忆类型: {target}"}
        return None
            
    def _get_limit(self, target):
        return self.max_memory_chars if target == "memory" else self.max_user_chars

    def _get_path(self, target):
        return self.user_path if target == "user" else self.memory_path

    def refresh(self):
        self._memory_snapshot = self._load_from_disk(self.memory_path)
        self._user_snapshot = self._load_from_disk(self.user_path)
        return self

    def get_entries(self, target):
        error = self._validate_target(target)
        if error:
            return []
        return self._load_from_disk(self._get_path(target))
    

    def add(self, content, target="memory"):
        error = self._validate_target(target)
        if error:
            return error

        content = self._normalize_entry(content)
        if not content:
            return {"ok": False, "error": "记忆内容为空"}

        path = self._get_path(target)
        limit = self._get_limit(target)
        entries = self._load_from_disk(path)

        if content in entries:
            self.refresh()
            return {"ok": True, "content": content, "duplicate": True}

        entries.append(content)
        
        total = self._total_chars(entries)
        if total > limit:
            return {
                "ok": False,
                "error": f"记忆已满 ({total}/{limit} 字符)。当前记忆:",
                "entries": entries[:-1],
            }
        
        self._save_to_disk(entries, path)
        self.refresh()
        return {"ok": True, "content": content}

    def replace(self, old_text, content, target="memory"):
        error = self._validate_target(target)
        if error:
            return error

        old_text = str(old_text or "").strip()
        content = self._normalize_entry(content)
        if not old_text:
            return {"ok": False, "error": "缺少要替换的旧记忆片段"}
        if not content:
            return {"ok": False, "error": "新记忆内容为空"}

        path = self._get_path(target)
        entries = self._load_from_disk(path)
        matches = [index for index, entry in enumerate(entries) if old_text in entry]
        if not matches:
            return {"ok": False, "error": f"没有记忆匹配: {old_text}"}
        if len(matches) > 1:
            return {
                "ok": False,
                "error": f"匹配到多条记忆，请提供更精确的 old_text: {old_text}",
                "matches": [entries[index] for index in matches],
            }

        index = matches[0]
        old_content = entries[index]
        if old_content == content:
            self.refresh()
            return {
                "ok": True,
                "changed": False,
                "content": content,
                "old_content": old_content,
            }

        if content in entries:
            entries.pop(index)
            deduplicated = True
        else:
            entries[index] = content
            deduplicated = False

        limit = self._get_limit(target)
        total = self._total_chars(entries)
        if total > limit:
            return {
                "ok": False,
                "error": f"替换后记忆将超出容量 ({total}/{limit} 字符)",
                "entries": self._load_from_disk(path),
            }

        self._save_to_disk(entries, path)
        self.refresh()
        return {
            "ok": True,
            "changed": True,
            "content": content,
            "old_content": old_content,
            "deduplicated": deduplicated,
        }

    def remove(self, keyword, target="memory", require_unique=False):
        error = self._validate_target(target)
        if error:
            return error

        keyword = str(keyword or "").strip()
        if not keyword:
            return {"ok": False, "error": "删除关键词为空"}

        path = self._get_path(target)
        entries = self._load_from_disk(path)
        matches = [entry for entry in entries if keyword in entry]
        if not matches:
            self.refresh()
            return {"ok": True, "removed": 0, "changed": False}
        if require_unique and len(matches) > 1:
            return {
                "ok": False,
                "error": f"匹配到多条记忆，拒绝自动删除: {keyword}",
                "matches": matches,
            }

        new_entries = [entry for entry in entries if keyword not in entry]
        removed = len(matches)
        self._save_to_disk(new_entries, path)
        self.refresh()
        return {
            "ok": True,
            "removed": removed,
            "changed": removed > 0,
            "removed_entries": matches,
        }


    def get_all_for_prompt(self):
        self.refresh()
        parts = []
        if self._memory_snapshot:
            parts.append("【关于项目】\n" + "\n".join(f"- {e}" for e in self._memory_snapshot))
        if self._user_snapshot:
            parts.append("【关于用户】\n" + "\n".join(f"- {e}" for e in self._user_snapshot))
        return "\n\n".join(parts) if parts else ""
