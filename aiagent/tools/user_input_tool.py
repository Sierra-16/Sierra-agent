import json

from .registry import registry


REQUEST_USER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "需要用户回答的简短问题",
        },
        "options": {
            "type": "array",
            "description": "供用户选择的 2-3 个互斥选项；允许纯文本回答时可以为空",
            "items": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "简短选项名称",
                    },
                    "description": {
                        "type": "string",
                        "description": "该选项的影响或取舍",
                    },
                    "value": {
                        "type": "string",
                        "description": "返回给模型的稳定值；不传时使用 label",
                    },
                },
                "required": ["label"],
            },
            "maxItems": 3,
        },
        "allow_free_text": {
            "type": "boolean",
            "description": "是否允许用户直接输入其他需求，默认 true",
        },
    },
    "required": ["question"],
}


def request_user_input(question, options=None, allow_free_text=True):
    return json.dumps({
        "error": "request_user_input must be handled by the conversation loop",
        "question": question,
    }, ensure_ascii=False)


registry.register(
    name="request_user_input",
    description=(
        "当缺少的信息会实质影响计划或结果时，暂停当前任务并向用户提出一个问题。"
        "可提供 2-3 个互斥选项，也可以允许用户输入其他需求。"
        "不要用于无关紧要的问题，也不要重复询问已有答案。"
    ),
    parameters=REQUEST_USER_INPUT_SCHEMA,
    handler=request_user_input,
)
