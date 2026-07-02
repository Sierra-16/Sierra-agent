from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auxiliary_config import model_supports_vision


ENV_REF_RE = re.compile(r"\$\{env:([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class ConfigIssue:
    path: str
    message: str
    hint: str = ""


class StartupConfigError(RuntimeError):
    def __init__(self, issues: list[ConfigIssue]):
        self.issues = issues
        super().__init__(format_config_issues(issues))


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise StartupConfigError([
            ConfigIssue(
                str(config_path),
                "找不到 config.json。",
                "复制 config.example.json 为 config.json，然后填写模型、搜索和 MCP 的真实配置。",
            )
        ])

    try:
        with config_path.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as exc:
        raise StartupConfigError([
            ConfigIssue(
                str(config_path),
                f"JSON 格式错误：第 {exc.lineno} 行第 {exc.colno} 列。",
                exc.msg,
            )
        ]) from exc

    if not isinstance(config, dict):
        raise StartupConfigError([
            ConfigIssue(str(config_path), "配置根节点必须是 JSON object。")
        ])
    return config


def load_and_validate_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    config = load_config(path)
    validate_startup_config(config)
    return resolve_env_refs(config)


def validate_startup_config(config: dict[str, Any]) -> None:
    issues: list[ConfigIssue] = []
    models = config.get("models")
    if not isinstance(models, dict) or not models:
        issues.append(ConfigIssue("models", "至少需要配置一个模型。"))
    else:
        active_model = str(config.get("active_model") or "").strip()
        if not active_model:
            issues.append(ConfigIssue("active_model", "必须指定当前启用的模型 key。"))
        elif active_model not in models:
            issues.append(
                ConfigIssue(
                    "active_model",
                    f"模型 '{active_model}' 不存在。",
                    f"可用模型：{', '.join(sorted(models))}",
                )
            )
        else:
            _validate_model(config, active_model, issues)

    _validate_search(config, issues)
    _validate_auxiliary(config, issues)
    _validate_vector_memory(config, issues)
    _validate_mcp_servers(config, issues)

    if issues:
        raise StartupConfigError(issues)


def validate_model_config(config: dict[str, Any], model_key: str) -> None:
    issues: list[ConfigIssue] = []
    models = config.get("models")
    if not isinstance(models, dict) or model_key not in models:
        issues.append(ConfigIssue("models", f"模型 '{model_key}' 不存在。"))
    else:
        _validate_model(config, model_key, issues)

    if issues:
        raise StartupConfigError(issues)


def format_config_issues(issues: list[ConfigIssue]) -> str:
    lines = ["Sierra 启动检查失败："]
    for issue in issues:
        lines.append(f"- {issue.path}: {issue.message}")
        if issue.hint:
            lines.append(f"  建议：{issue.hint}")
    lines.append("")
    lines.append("请修改 config.json 后重新启动 Sierra。")
    return "\n".join(lines)


def resolve_env_refs(value: Any) -> Any:
    """Return a copy with $NAME and ${env:NAME} strings resolved from the environment."""
    if isinstance(value, dict):
        return {key: resolve_env_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_env_refs(item) for item in value]
    if not isinstance(value, str):
        return value
    return ENV_REF_RE.sub(
        lambda match: os.environ.get(match.group(1) or match.group(2), ""),
        value,
    )


def _validate_model(config: dict[str, Any], model_key: str, issues: list[ConfigIssue]) -> None:
    model = config.get("models", {}).get(model_key)
    path = f"models.{model_key}"
    if not isinstance(model, dict):
        issues.append(ConfigIssue(path, "模型配置必须是 object。"))
        return

    _require_text(model.get("name"), f"{path}.name", "模型名称不能为空。", issues)
    _require_text(model.get("base_url"), f"{path}.base_url", "base_url 不能为空。", issues)
    _require_secret(model.get("api_key"), f"{path}.api_key", "模型 API key 未配置。", issues)


def _validate_search(config: dict[str, Any], issues: list[ConfigIssue]) -> None:
    search = config.get("search")
    if search is None:
        return
    if not isinstance(search, dict):
        issues.append(ConfigIssue("search", "搜索配置必须是 object。"))
        return

    backend = str(search.get("backend") or "serpapi").strip().lower()
    if backend not in {"serpapi", "bing", "bocha", "duckduckgo"}:
        issues.append(
            ConfigIssue(
                "search.backend",
                f"不支持的搜索后端 '{backend}'。",
                "可用值：serpapi, bing, bocha, duckduckgo",
            )
        )
        return
    if backend != "duckduckgo":
        _require_secret(
            search.get("api_key"),
            "search.api_key",
            f"{backend} 搜索 API key 未配置。",
            issues,
        )


def _validate_auxiliary(config: dict[str, Any], issues: list[ConfigIssue]) -> None:
    auxiliary = config.get("auxiliary")
    if auxiliary is None:
        return
    if not isinstance(auxiliary, dict):
        issues.append(ConfigIssue("auxiliary", "辅助能力配置必须是 object。"))
        return

    for name, capability in auxiliary.items():
        path = f"auxiliary.{name}"
        if not isinstance(capability, dict):
            issues.append(ConfigIssue(path, "辅助能力配置必须是 object。"))
            continue

        if not _config_bool(capability.get("enabled"), default=False):
            continue

        provider = str(capability.get("provider") or "main").strip().lower()
        if not provider:
            issues.append(ConfigIssue(f"{path}.provider", "provider 不能为空。"))
            continue

        if not _auxiliary_uses_model_credentials(provider, capability):
            _validate_optional_secret_reference(capability, path, issues)
            continue

        if str(name) == "vision" and provider == "auto":
            active_model_key = str(config.get("active_model") or "").strip()
            active_model = (
                (config.get("models") or {}).get(active_model_key)
                if isinstance(config.get("models"), dict)
                else {}
            )
            if model_supports_vision(active_model if isinstance(active_model, dict) else {}):
                continue
            capability = dict(capability)
            fallback = capability.get("fallback")
            if isinstance(fallback, dict):
                capability = {**capability, **fallback}
                capability.pop("fallback", None)
            capability["provider"] = str(capability.get("fallback_provider") or "openai_compatible")
            provider = str(capability.get("provider") or "openai_compatible").strip().lower()

        credentials_model_key = str(capability.get("credentials_model") or "").strip()
        if provider in {"auto", "main", "model"} and not credentials_model_key:
            credentials_model_key = str(config.get("active_model") or "").strip()

        credentials_model = {}
        if credentials_model_key:
            models = config.get("models", {})
            if isinstance(models, dict):
                credentials_model = models.get(credentials_model_key) or {}
            if not isinstance(credentials_model, dict) or not credentials_model:
                issues.append(
                    ConfigIssue(
                        f"{path}.credentials_model",
                        f"凭据模型 '{credentials_model_key}' 不存在。",
                    )
                )
                credentials_model = {}

        if provider in {"openai_compatible", "custom"}:
            _require_text(
                capability.get("model") or credentials_model.get("name"),
                f"{path}.model",
                "辅助模型名称不能为空。",
                issues,
            )

        base_url = capability.get("base_url") or credentials_model.get("base_url")
        _require_text(
            base_url,
            f"{path}.base_url",
            "辅助能力 base_url 不能为空。",
            issues,
            hint="可以直接配置 base_url，或通过 credentials_model 复用 models 中的连接信息。",
        )

        _validate_auxiliary_api_key(config, capability, credentials_model, credentials_model_key, path, issues)


def _validate_auxiliary_api_key(
    config: dict[str, Any],
    capability: dict[str, Any],
    credentials_model: dict[str, Any],
    credentials_model_key: str,
    path: str,
    issues: list[ConfigIssue],
) -> None:
    key_sources = [
        (f"{path}.api_key", capability.get("api_key")),
    ]
    env_name = str(capability.get("api_key_env") or "").strip()
    if env_name:
        key_sources.append((f"env.{env_name}", os.environ.get(env_name)))
    if credentials_model:
        key_sources.append((
            f"models.{credentials_model_key}.api_key",
            credentials_model.get("api_key"),
        ))
    elif not capability.get("credentials_model") and config.get("active_model"):
        active = str(config.get("active_model") or "")
        model = (config.get("models") or {}).get(active) if isinstance(config.get("models"), dict) else {}
        if isinstance(model, dict):
            key_sources.append((f"models.{active}.api_key", model.get("api_key")))

    has_valid_key = False
    for source_path, value in key_sources:
        if _secret_is_present(value):
            has_valid_key = True
            break
        if value:
            _append_secret_issue(value, source_path, "辅助能力 API key 未配置。", issues)

    if not has_valid_key:
        issues.append(
            ConfigIssue(
                f"{path}.api_key",
                "辅助能力 API key 未配置。",
                "配置 api_key、api_key_env，或 credentials_model 指向一个已配置 API key 的模型。",
            )
        )


def _validate_optional_secret_reference(
    capability: dict[str, Any],
    path: str,
    issues: list[ConfigIssue],
) -> None:
    if capability.get("api_key"):
        _require_secret(capability.get("api_key"), f"{path}.api_key", "辅助能力 API key 未配置。", issues)
    env_name = str(capability.get("api_key_env") or "").strip()
    if env_name and not os.environ.get(env_name):
        issues.append(
            ConfigIssue(
                f"{path}.api_key_env",
                f"引用的环境变量未设置：{env_name}。",
                "先设置环境变量，或关闭该能力。",
            )
        )


def _auxiliary_uses_model_credentials(provider: str, capability: dict[str, Any]) -> bool:
    return (
        provider in {"auto", "main", "model", "openai_compatible", "custom"}
        or bool(capability.get("credentials_model"))
        or bool(capability.get("base_url"))
    )


def _validate_vector_memory(config: dict[str, Any], issues: list[ConfigIssue]) -> None:
    memory = config.get("memory")
    if not isinstance(memory, dict):
        return
    vector = memory.get("vector")
    if not isinstance(vector, dict) or vector.get("enabled", False) is not True:
        return
    embedding = vector.get("embedding")
    if not isinstance(embedding, dict):
        issues.append(ConfigIssue("memory.vector.embedding", "启用向量记忆时必须配置 embedding。"))
        return

    provider = str(embedding.get("provider") or "openai_compatible").strip()
    if provider != "openai_compatible":
        issues.append(
            ConfigIssue(
                "memory.vector.embedding.provider",
                f"暂不支持的 embedding provider '{provider}'。",
                "当前只支持 openai_compatible。",
            )
        )
        return

    _require_text(
        embedding.get("model"),
        "memory.vector.embedding.model",
        "embedding 模型名称不能为空。",
        issues,
    )
    _validate_embedding_endpoint(config, embedding, issues)


def _validate_embedding_endpoint(
    config: dict[str, Any],
    embedding: dict[str, Any],
    issues: list[ConfigIssue],
) -> None:
    credentials_model_key = str(embedding.get("credentials_model") or "").strip()
    credentials_model = {}
    if credentials_model_key:
        models = config.get("models", {})
        if isinstance(models, dict):
            credentials_model = models.get(credentials_model_key) or {}
        if not isinstance(credentials_model, dict) or not credentials_model:
            issues.append(
                ConfigIssue(
                    "memory.vector.embedding.credentials_model",
                    f"凭据模型 '{credentials_model_key}' 不存在。",
                )
            )
            credentials_model = {}

    base_url = embedding.get("base_url") or credentials_model.get("base_url")
    _require_text(
        base_url,
        "memory.vector.embedding.base_url",
        "embedding base_url 不能为空。",
        issues,
        hint="可以直接配置 base_url，或通过 credentials_model 复用某个模型的 base_url。",
    )

    has_valid_key = False
    key_sources = [
        ("memory.vector.embedding.api_key", embedding.get("api_key")),
    ]
    env_name = str(embedding.get("api_key_env") or "").strip()
    if env_name:
        key_sources.append((f"env.{env_name}", os.environ.get(env_name)))
    if credentials_model:
        key_sources.append((
            f"models.{credentials_model_key}.api_key",
            credentials_model.get("api_key"),
        ))

    for path, value in key_sources:
        if _secret_is_present(value):
            has_valid_key = True
            break
        if value:
            _append_secret_issue(value, path, "embedding API key 未配置。", issues)

    if not has_valid_key:
        issues.append(
            ConfigIssue(
                "memory.vector.embedding.api_key",
                "embedding API key 未配置。",
                "配置 api_key，或 api_key_env，或 credentials_model 指向一个已配置 API key 的模型。",
            )
        )


def _validate_mcp_servers(config: dict[str, Any], issues: list[ConfigIssue]) -> None:
    servers = config.get("mcpServers")
    if servers is None:
        return
    if not isinstance(servers, dict):
        issues.append(ConfigIssue("mcpServers", "MCP 配置必须是 object。"))
        return

    for name, server in servers.items():
        path = f"mcpServers.{name}"
        if not isinstance(server, dict):
            issues.append(ConfigIssue(path, "MCP server 配置必须是 object。"))
            continue
        if server.get("enabled", True) is False:
            continue

        transport = str(server.get("type") or ("streamablehttp" if server.get("url") else "stdio"))
        transport = transport.lower().replace("_", "").replace("-", "")
        if transport in {"streamablehttp", "http"}:
            _require_text(server.get("url"), f"{path}.url", "HTTP MCP server 必须配置 url。", issues)
            headers = server.get("headers")
            if isinstance(headers, dict):
                for header_name, value in headers.items():
                    _require_secret(
                        value,
                        f"{path}.headers.{header_name}",
                        "MCP header 中的凭据未配置。",
                        issues,
                    )
            continue

        _require_text(server.get("command"), f"{path}.command", "stdio MCP server 必须配置 command。", issues)
        env = server.get("env")
        if isinstance(env, dict):
            for env_key, value in env.items():
                _require_secret(
                    value,
                    f"{path}.env.{env_key}",
                    "MCP env 中的凭据未配置。",
                    issues,
                )


def _require_text(
    value: Any,
    path: str,
    message: str,
    issues: list[ConfigIssue],
    hint: str = "",
) -> None:
    if _text_is_present(value):
        return
    issues.append(ConfigIssue(path, message, hint))


def _require_secret(
    value: Any,
    path: str,
    message: str,
    issues: list[ConfigIssue],
) -> None:
    if _secret_is_present(value):
        return
    _append_secret_issue(value, path, message, issues)


def _config_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)


def _append_secret_issue(value: Any, path: str, message: str, issues: list[ConfigIssue]) -> None:
    raw = "" if value is None else str(value).strip()
    if not raw:
        issues.append(ConfigIssue(path, message))
        return

    missing_envs = _missing_env_refs(raw)
    if missing_envs:
        issues.append(
            ConfigIssue(
                path,
                f"引用的环境变量未设置：{', '.join(missing_envs)}。",
                "先设置环境变量，或改成真实 key。",
            )
        )
        return

    if _looks_like_placeholder(raw):
        issues.append(
            ConfigIssue(
                path,
                "仍是示例占位值。",
                "把 YOUR_... / TOKEN / API_KEY 这类占位值替换成真实配置。",
            )
        )
        return

    issues.append(ConfigIssue(path, message))


def _text_is_present(value: Any) -> bool:
    raw = "" if value is None else str(value).strip()
    return bool(raw) and not _looks_like_placeholder(raw) and not _missing_env_refs(raw)


def _secret_is_present(value: Any) -> bool:
    raw = "" if value is None else str(value).strip()
    return bool(raw) and not _looks_like_placeholder(raw) and not _missing_env_refs(raw)


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().upper()
    if not normalized:
        return True
    markers = (
        "YOUR_",
        "YOUR-",
        "YOUR ",
        "REPLACE_",
        "CHANGE_ME",
        "CHANGEME",
        "TODO",
        "TOKEN_HERE",
        "API_KEY_HERE",
    )
    return any(marker in normalized for marker in markers)


def _missing_env_refs(value: str) -> list[str]:
    missing: list[str] = []
    for match in ENV_REF_RE.finditer(value):
        env_name = match.group(1) or match.group(2)
        if env_name and not os.environ.get(env_name):
            missing.append(env_name)
    return sorted(set(missing))
