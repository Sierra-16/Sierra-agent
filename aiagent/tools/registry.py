import json
class ToolEntry:
    __slots__ = (
        "name",
        "description",
        "parameters",
        "handler",
        "toolset",
        "emoji",
        "max_result_size_chars",
    )

    def __init__(
        self,
        name,
        description,
        parameters,
        handler,
        toolset="core",
        emoji="",
        max_result_size_chars=None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.toolset = toolset
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(
        self,
        name,
        description,
        parameters,
        handler,
        toolset="core",
        emoji="",
        max_result_size_chars=None,
    ):
        self._tools[name] = ToolEntry(
            name,
            description,
            parameters,
            handler,
            toolset=toolset,
            emoji=emoji,
            max_result_size_chars=max_result_size_chars,
        )

    def unregister(self, name):
        self._tools.pop(name, None)

    def unregister_prefix(self, prefix):
        for name in list(self._tools):
            if name.startswith(prefix):
                self.unregister(name)

    def names(self):
        return list(self._tools)

    def get_entry(self, name):
        return self._tools.get(name)

    def get_max_result_size(self, name, default=None):
        entry = self.get_entry(name)
        if entry is not None and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        return default

    def get_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            }
            for tool in self._tools.values()
        ]
    
    def execute(self, name, arguments):
        if name not in self._tools:
            return json.dumps({"error": f"未知工具: {name}"})
        try:
            return self._tools[name].handler(**arguments)
        except Exception as e:
            return json.dumps({"error": str(e)})
       
    
registry = ToolRegistry()
