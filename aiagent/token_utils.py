import json

def estimate_tokens(messages, tools=None):
    total = 0
    for msg in messages:
        text = msg.get("content", "") or ""
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        # tool_calls 也要算
        if "tool_calls" in msg:
            text += json.dumps(msg["tool_calls"], ensure_ascii=False)
        total += len(text) * 1.5  # 中文场景取高一点安全
    if tools:
        total += len(json.dumps(tools, ensure_ascii=False)) * 1.5
    return int(total)
