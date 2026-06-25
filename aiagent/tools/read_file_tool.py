from .registry import registry
import json
READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "要读取的文件路径，如 'e:/xxxx/main.py'"
        }
    },
    "required": ["file_path"]
}

def read_file(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 太长截断
        if len(content) > 5000:
            content = content[:5000] + f"\n...(内容已截断，共 {len(content)} 字)"
        return json.dumps({"file_path": file_path, "content": content})
    except FileNotFoundError:
        return json.dumps({"error": f"文件不存在: {file_path}"})
    except PermissionError:
        return json.dumps({"error": f"没有权限读取: {file_path}"})
    except Exception as e:
        return json.dumps({"error": str(e)})
    
registry.register(
    name="read_file",
    description="读取指定路径的文件内容",
    parameters=READ_FILE_SCHEMA,
    handler=read_file
)
