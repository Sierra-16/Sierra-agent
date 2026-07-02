from __future__ import annotations

import copy
import os
from typing import Any


DEFAULT_AUXILIARY_CAPABILITIES: dict[str, dict[str, Any]] = {
    "vision": {
        "enabled": False,
        "provider": "auto",
        "timeout": 30,
        "max_tokens": 2048,
    },
    "web_extract": {
        "enabled": False,
        "provider": "main",
        "timeout": 30,
        "max_tokens": 2048,
    },
    "compression": {
        "enabled": False,
        "provider": "main",
        "timeout": 30,
        "max_tokens": 2048,
    },
    "title": {
        "enabled": False,
        "provider": "main",
        "timeout": 20,
        "max_tokens": 256,
    },
    "session_search": {
        "enabled": False,
        "provider": "main",
        "timeout": 30,
        "max_tokens": 1024,
    },
    "tts": {
        "enabled": False,
        "provider": "edge",
        "voice": "zh-CN-XiaoxiaoNeural",
        "format": "mp3",
    },
    "stt": {
        "enabled": False,
        "provider": "local",
        "model": "base",
        "language": "auto",
    },
    "image_generation": {
        "enabled": False,
        "provider": "openai_compatible",
        "timeout": 60,
    },
}


MODEL_BACKED_PROVIDERS = {
    "auto",
    "main",
    "model",
    "openai_compatible",
    "custom",
}


def resolve_auxiliary_config(app_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve auxiliary capability config without mutating the source config."""
    raw_auxiliary = app_config.get("auxiliary")
    if not isinstance(raw_auxiliary, dict):
        raw_auxiliary = {}

    names = set(DEFAULT_AUXILIARY_CAPABILITIES)
    names.update(str(name) for name in raw_auxiliary)

    resolved: dict[str, dict[str, Any]] = {}
    for name in sorted(names):
        resolved[name] = resolve_capability_config(app_config, name)
    return resolved


def resolve_capability_config(
    app_config: dict[str, Any],
    name: str,
    capability_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one capability's model credentials and environment key override."""
    default = copy.deepcopy(DEFAULT_AUXILIARY_CAPABILITIES.get(name, {}))
    raw_auxiliary = app_config.get("auxiliary")
    raw = {}
    if capability_config is not None:
        raw = capability_config
    elif isinstance(raw_auxiliary, dict) and isinstance(raw_auxiliary.get(name), dict):
        raw = raw_auxiliary.get(name, {})

    resolved = {**default, **copy.deepcopy(raw)}
    resolved["name"] = name
    resolved["enabled"] = _coerce_bool(resolved.get("enabled"), default=False)
    resolved["provider"] = str(resolved.get("provider") or default.get("provider") or "main").strip()

    if name == "vision":
        return _resolve_vision_config(app_config, resolved)

    provider = resolved["provider"].lower()
    if _is_model_backed(provider, resolved):
        fallback_model = None
        if provider in {"auto", "main", "model"}:
            fallback_model = str(app_config.get("active_model") or "").strip() or None
        resolved = resolve_model_credentials(
            app_config,
            resolved,
            default_model_key=fallback_model,
            fill_model_name=True,
        )
    else:
        resolved = _resolve_api_key_env(resolved)

    return resolved


def _resolve_vision_config(
    app_config: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    provider = str(config.get("provider") or "auto").strip().lower()
    active_model_key = str(app_config.get("active_model") or "").strip()
    active_model = _get_model_config(app_config, active_model_key)
    active_supports_vision = model_supports_vision(active_model)

    if provider in {"auto", "main", "model"} and active_supports_vision and active_model:
        resolved = copy.deepcopy(config)
        resolved["provider"] = "main"
        resolved["route"] = "main_model"
        resolved["supports_vision"] = True
        resolved["credentials_model"] = active_model_key
        resolved["model"] = active_model.get("name", "")
        resolved["base_url"] = active_model.get("base_url", "")
        resolved["api_key"] = active_model.get("api_key", "")
        return resolved

    if provider == "auto":
        fallback = config.get("fallback")
        if isinstance(fallback, dict):
            fallback_config = {**copy.deepcopy(config), **copy.deepcopy(fallback)}
            fallback_config.pop("fallback", None)
            fallback_config["provider"] = str(fallback_config.get("provider") or "openai_compatible").strip()
        else:
            fallback_config = copy.deepcopy(config)
            fallback_config["provider"] = str(
                fallback_config.get("fallback_provider")
                or "openai_compatible"
            ).strip()
        fallback_config["route"] = "auxiliary_vision"
        fallback_config["main_supports_vision"] = active_supports_vision
        return resolve_model_credentials(
            app_config,
            fallback_config,
            fill_model_name=True,
        )

    resolved = copy.deepcopy(config)
    resolved["route"] = "auxiliary_vision" if provider not in {"main", "model"} else "main_model"
    resolved["main_supports_vision"] = active_supports_vision
    if _is_model_backed(provider, resolved):
        default_model_key = active_model_key if provider in {"main", "model"} else None
        resolved = resolve_model_credentials(
            app_config,
            resolved,
            default_model_key=default_model_key,
            fill_model_name=True,
        )
    else:
        resolved = _resolve_api_key_env(resolved)
    return resolved


def resolve_model_credentials(
    app_config: dict[str, Any],
    provider_config: dict[str, Any],
    *,
    default_model_key: str | None = None,
    fill_model_name: bool = False,
) -> dict[str, Any]:
    """Reuse a configured chat model as a credential source for an auxiliary task."""
    resolved = copy.deepcopy(provider_config)
    credentials_model = str(resolved.get("credentials_model") or default_model_key or "").strip()
    model_config = _get_model_config(app_config, credentials_model)

    if model_config:
        resolved.setdefault("credentials_model", credentials_model)
        resolved.setdefault("base_url", model_config.get("base_url", ""))
        resolved.setdefault("api_key", model_config.get("api_key", ""))
        if fill_model_name and not str(resolved.get("model") or "").strip():
            resolved["model"] = model_config.get("name", "")

    resolved = _resolve_api_key_env(resolved)
    return resolved


def auxiliary_status(auxiliary_config: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted, UI/API-safe summary of resolved auxiliary capabilities."""
    capabilities = []
    for name, config in sorted((auxiliary_config or {}).items()):
        if not isinstance(config, dict):
            continue
        capabilities.append(redact_capability_config(config))
    enabled_count = sum(1 for item in capabilities if item.get("enabled"))
    return {
        "enabled_count": enabled_count,
        "total": len(capabilities),
        "capabilities": capabilities,
    }


def redact_capability_config(config: dict[str, Any]) -> dict[str, Any]:
    item = {
        "name": config.get("name", ""),
        "enabled": bool(config.get("enabled")),
        "provider": config.get("provider", ""),
        "route": config.get("route", ""),
        "model": config.get("model", ""),
        "credentials_model": config.get("credentials_model", ""),
        "base_url": config.get("base_url", ""),
        "timeout": config.get("timeout"),
        "max_tokens": config.get("max_tokens"),
        "voice": config.get("voice", ""),
        "language": config.get("language", ""),
        "supports_vision": config.get("supports_vision"),
        "main_supports_vision": config.get("main_supports_vision"),
    }
    api_key = str(config.get("api_key") or "")
    item["api_key_set"] = bool(api_key)
    item["api_key_preview"] = _secret_preview(api_key)
    return {key: value for key, value in item.items() if value not in ("", None)}


def _resolve_api_key_env(config: dict[str, Any]) -> dict[str, Any]:
    resolved = copy.deepcopy(config)
    env_name = str(resolved.get("api_key_env") or "").strip()
    if env_name and os.environ.get(env_name):
        resolved["api_key"] = os.environ[env_name]
    return resolved


def _get_model_config(app_config: dict[str, Any], model_key: str) -> dict[str, Any]:
    models = app_config.get("models")
    if not model_key or not isinstance(models, dict):
        return {}
    model = models.get(model_key)
    return model if isinstance(model, dict) else {}


def model_supports_vision(model_config: dict[str, Any] | None) -> bool:
    if not isinstance(model_config, dict):
        return False
    if _coerce_bool(model_config.get("supports_vision"), default=False):
        return True
    capabilities = model_config.get("capabilities")
    if isinstance(capabilities, dict):
        return _coerce_bool(capabilities.get("vision"), default=False)
    if isinstance(capabilities, list):
        return any(str(item).strip().lower() in {"vision", "image", "multimodal"} for item in capabilities)
    return False


def _is_model_backed(provider: str, config: dict[str, Any]) -> bool:
    return (
        provider in MODEL_BACKED_PROVIDERS
        or bool(config.get("credentials_model"))
        or bool(config.get("base_url"))
    )


def _coerce_bool(value: Any, *, default: bool) -> bool:
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


def _secret_preview(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-4:]}"
