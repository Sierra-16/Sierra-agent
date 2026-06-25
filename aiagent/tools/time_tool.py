from .registry import registry
import json
from datetime import datetime

TIME_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": []
}


def get_time() -> str:
    now = datetime.now()
    return json.dumps({"current_time": now.strftime("%Y-%m-%d %H:%M:%S")})


registry.register(
    name="get_time",
    description="获取当前时间",
    parameters=TIME_SCHEMA,
    handler=get_time
)