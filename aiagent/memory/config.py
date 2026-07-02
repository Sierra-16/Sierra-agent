import copy

from ..auxiliary_config import resolve_model_credentials


def resolve_memory_config(app_config: dict) -> dict:
    """Resolve embedding credentials without duplicating secrets in config.json."""
    memory_config = copy.deepcopy(app_config.get("memory", {}))
    vector_config = memory_config.get("vector")
    if not isinstance(vector_config, dict):
        return memory_config

    embedding_config = vector_config.get("embedding")
    if not isinstance(embedding_config, dict):
        return memory_config

    vector_config["embedding"] = resolve_model_credentials(
        app_config,
        embedding_config,
    )

    return memory_config
