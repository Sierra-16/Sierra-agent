# Sierra Plugins

Sierra loads runtime extensions from this directory and from built-in plugins under
`aiagent/plugins/builtin/`.

Each plugin lives in its own folder:

```text
plugins/my-plugin/
  plugin.json
  provider.py
```

Minimal `plugin.json`:

```json
{
  "id": "demo.provider",
  "name": "Demo Provider",
  "kind": "provider",
  "version": "0.1.0",
  "description": "Adds a demo provider to Sierra.",
  "entrypoint": "register",
  "enabled_by_default": true,
  "capabilities": ["demo"]
}
```

Minimal `provider.py`:

```python
class DemoProvider:
    def status(self, config=None):
        return {"enabled": True, "available": True, "issues": []}


def register(context):
    context.register_provider(
        kind="demo",
        name="provider",
        factory=DemoProvider,
        title="Demo Provider",
    )
```

Use `config.json` to opt in or out:

```json
{
  "plugins": {
    "enabled": [],
    "disabled": [],
    "roots": ["plugins"],
    "config": {}
  }
}
```

Sierra exposes plugin status through `/plugins`, `/api/plugins`, and the Web
settings panel.
