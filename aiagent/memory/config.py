import copy
import os


def resolve_memory_config(app_config: dict) -> dict:
    """Resolve embedding credentials without duplicating secrets in config.json."""
    memory_config = copy.deepcopy(app_config.get("memory", {}))
    vector_config = memory_config.get("vector")
    if not isinstance(vector_config, dict):
        return memory_config

    embedding_config = vector_config.get("embedding")
    if not isinstance(embedding_config, dict):
        return memory_config

    env_name = embedding_config.get("api_key_env")
    if env_name and os.environ.get(env_name):
        embedding_config["api_key"] = os.environ[env_name]

    credentials_model = embedding_config.get("credentials_model")
    model_config = app_config.get("models", {}).get(credentials_model, {})
    if isinstance(model_config, dict):
        embedding_config.setdefault("base_url", model_config.get("base_url", ""))
        embedding_config.setdefault("api_key", model_config.get("api_key", ""))

    return memory_config
