from .registry import registry
import json
import glob
import os

SEARCH_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "文件名匹配，如 '*.py' 搜当前目录，'**/*.py' 递归搜所有子目录"
        },
        "dir_path": {
            "type": "string",
            "description": "搜索的起始目录，不传则从当前目录开始"
        }
    },
    "required": ["pattern"]
}

def search_files(pattern: str, dir_path: str = ".") -> str:
    try:
        search_path = os.path.join(dir_path, pattern)
        matches = glob.glob(search_path, recursive=True)
        return json.dumps({
            "pattern": pattern,
            "dir_path": os.path.abspath(dir_path),
            "matches": matches,
            "total": len(matches)
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
    
registry.register(
    name="search_files",
    description="搜索匹配的文件，支持通配符，如 '*.py' 搜当前目录，'**/*.py' 递归搜所有子目录",
    parameters=SEARCH_FILES_SCHEMA,
    handler=search_files
)