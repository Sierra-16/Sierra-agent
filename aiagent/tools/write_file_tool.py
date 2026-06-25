from .registry import registry
import json
import os

WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "要写入的文件路径，如 'e:/xxxx/main.py'"
        },
        "content": {
            "type": "string",
            "description": "要写入文件的内容"
        }
    },
    "required": ["file_path", "content"]
}

def write_file(file_path: str, content: str) -> str:
    try:
        # 1. 目录不存在就创建
        dir_path = os.path.dirname(os.path.abspath(file_path))
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # 2. 写文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # 3. 返回成功
        return json.dumps({"file_path": file_path, "written": len(content), "status": "ok"})
    except PermissionError:
        return json.dumps({"error": f"没有权限写入: {file_path}"})
    except Exception as e:
        return json.dumps({"error": str(e)})
    

registry.register(
    name="write_file",
    description="将内容写入指定路径的文件",
    parameters=WRITE_FILE_SCHEMA,
    handler=write_file
)