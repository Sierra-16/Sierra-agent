import math
from abc import ABC, abstractmethod

from openai import OpenAI


class EmbeddingClient(ABC):
    """Convert text into vectors without exposing a vendor to memory providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in the same order they were provided."""

    def embed_one(self, text: str) -> list[float]:
        vectors = self.embed([text])
        if len(vectors) != 1:
            raise ValueError("Embedding provider returned an unexpected result count")
        return vectors[0]

    def close(self) -> None:
        """Release network resources when needed."""


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int | None = None,
        batch_size: int = 10,
        timeout: float = 20.0,
        client=None,
    ):
        if not base_url:
            raise ValueError("Embedding base_url is required")
        if not api_key:
            raise ValueError("Embedding api_key is required")
        if not model:
            raise ValueError("Embedding model is required")

        self.model = model
        self.dimensions = int(dimensions) if dimensions else None
        self.batch_size = max(1, int(batch_size))
        self._owns_client = client is None
        self.client = client or OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=2,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        cleaned = [str(text or "").strip() for text in texts]
        if not cleaned or any(not text for text in cleaned):
            raise ValueError("Embedding input cannot be empty")

        vectors = []
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start:start + self.batch_size]
            kwargs = {
                "model": self.model,
                "input": batch,
                "encoding_format": "float",
            }
            if self.dimensions:
                kwargs["dimensions"] = self.dimensions
            response = self.client.embeddings.create(**kwargs)
            data = sorted(response.data, key=lambda item: item.index)
            if len(data) != len(batch):
                raise ValueError("Embedding provider returned an unexpected result count")
            vectors.extend(self._validate_vector(item.embedding) for item in data)
        return vectors

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self.client, "close", None)
            if callable(close):
                close()

    def _validate_vector(self, vector) -> list[float]:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("Embedding provider returned an invalid vector")
        if self.dimensions and len(values) != self.dimensions:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimensions}, got {len(values)}"
            )
        return values
