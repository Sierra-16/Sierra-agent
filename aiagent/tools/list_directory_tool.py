from .registry import registry
import json
import os
LIST_DIR_SCHEMA = {
    "type": "object",
    "properties": {
        "dir_path": {
            "type": "string",
            "description": "要列出的目录路径，不传则列出当前目录"
        }
    },
    "required": []  # 可选参数，不加 required
}

def list_directory(dir_path: str = ".") -> str:
    try:
        items = os.listdir(dir_path)
        files = []
        dirs = []
        for name in items:
            full = os.path.join(dir_path, name)
            if os.path.isdir(full):
                dirs.append(name + "/")
            else:
                size = os.path.getsize(full)
                files.append(f"{name} ({size} bytes)")
        return json.dumps({
            "dir_path": os.path.abspath(dir_path),
            "directories": dirs,
            "files": files,
            "total": len(items)
        })
    except FileNotFoundError:
        return json.dumps({"error": f"目录不存在: {dir_path}"})
    except Exception as e:
        return json.dumps({"error": str(e)})

registry.register(
    name="list_directory",
    description="列出指定目录中的文件和子目录",
    parameters=LIST_DIR_SCHEMA,
    handler=list_directory
)