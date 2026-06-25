from .registry import registry
from ..memory_store import MemoryStore
import json


store = MemoryStore()

SAVE_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "要记住的内容"},
        "target": {
            "type": "string",
            "enum": ["memory", "user"],
            "description": "记忆类型：memory=项目相关，user=用户画像"
        }
    },
    "required": ["content", "target"]
}

DELETE_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "keyword": {"type": "string", "description": "要删除的记忆关键词，匹配包含该词的所有条目"}
    },
    "required": ["keyword"]
}


def save_memory(content, target):
    result = store.add(content, target)
    return json.dumps(result, ensure_ascii=False)

def delete_memory(keyword):
    result = store.remove(keyword)
    return json.dumps(result, ensure_ascii=False)


registry.register(
    name="save_memory",
    description="记住一条信息。target='memory'=项目相关，target='user'=用户画像",
    parameters=SAVE_MEMORY_SCHEMA,
    handler=save_memory
)

registry.register(
    name="delete_memory",
    description="删除包含指定关键词的记忆条目",
    parameters=DELETE_MEMORY_SCHEMA,
    handler=delete_memory
)