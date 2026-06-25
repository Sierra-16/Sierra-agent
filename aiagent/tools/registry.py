import json
class ToolEntry:
    __slots__ = ("name", "description", "parameters", "handler")
    def __init__(self, name, description, parameters, handler):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, description, parameters, handler):
        self._tools[name] = ToolEntry(name, description, parameters, handler)

    def unregister(self, name):
        self._tools.pop(name, None)

    def unregister_prefix(self, prefix):
        for name in list(self._tools):
            if name.startswith(prefix):
                self.unregister(name)

    def names(self):
        return list(self._tools)

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
