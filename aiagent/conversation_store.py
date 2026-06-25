from datetime import datetime
import os
import json
import tempfile
class ConversationStore:
    def __init__(self,storage_dir="conversations"):
        if not os.path.isabs(storage_dir):
            storage_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", storage_dir))
        self.storage_dir = storage_dir
        self.index_path = os.path.join(storage_dir, "index.json")
        os.makedirs(storage_dir, exist_ok=True)
        if not os.path.exists(self.index_path):
            self._save_index({})

    def _save_index(self, index):
        self._atomic_json_write(self.index_path, index)

    def _load_index(self):
        with open(self.index_path, "r", encoding="utf-8") as f:
            return json.load(f)
        
    def new_id(self):
        return datetime.now().strftime("%Y%m%d%H%M%S%f")
    
    def save(self, conv_id, messages, usage=None, title=""):
        # 1. 写消息文件
        msg_path = os.path.join(self.storage_dir, f"{conv_id}.json")
        self._atomic_json_write(
            msg_path,
            {"messages": messages, "usage": usage},
        )
        
        # 2. 更新 index
        index = self._load_index()
        now = datetime.now().timestamp()
        if conv_id not in index:
            index[conv_id] = {"title": title, "created": now, "updated": now}
        else:
            index[conv_id]["updated"] = now
            if title:
                index[conv_id]["title"] = title
        
        # 3. 写回 index
        self._save_index(index)

    def _atomic_json_write(self, path, value):
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".sierra-",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def load(self, conv_id):
        msg_path = os.path.join(self.storage_dir, f"{conv_id}.json")
        if not os.path.exists(msg_path):
            return [], {}
        with open(msg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", []), data.get("usage", {})
    
    def list_all(self):
        index = self._load_index()
        result = []
        for conv_id, meta in index.items():
            result.append({
                "id": conv_id,
                "title": meta.get("title", ""),
                "created": meta.get("created", 0),
                "updated": meta.get("updated", 0),
            })
        # 按更新时间倒序，最近的在前面
        result.sort(key=lambda x: x["updated"], reverse=True)
        return result
