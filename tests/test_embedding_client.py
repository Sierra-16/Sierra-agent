import unittest
from types import SimpleNamespace

from aiagent.memory.embedding import OpenAICompatibleEmbeddingClient


class FakeEmbeddingsAPI:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        data = [
            SimpleNamespace(index=index, embedding=[float(len(text)), 1.0])
            for index, text in enumerate(kwargs["input"])
        ]
        return SimpleNamespace(data=data)


class FakeOpenAIClient:
    def __init__(self):
        self.embeddings = FakeEmbeddingsAPI()


class EmbeddingClientTests(unittest.TestCase):
    def test_batches_requests_and_preserves_order(self):
        fake_client = FakeOpenAIClient()
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="embedding-test",
            dimensions=2,
            batch_size=2,
            client=fake_client,
        )

        vectors = client.embed(["a", "long", "xyz"])

        self.assertEqual(vectors, [[1.0, 1.0], [4.0, 1.0], [3.0, 1.0]])
        self.assertEqual(len(fake_client.embeddings.calls), 2)
        self.assertEqual(fake_client.embeddings.calls[0]["dimensions"], 2)
        self.assertEqual(fake_client.embeddings.calls[0]["encoding_format"], "float")

    def test_rejects_empty_input(self):
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="embedding-test",
            client=FakeOpenAIClient(),
        )

        with self.assertRaises(ValueError):
            client.embed([""])


if __name__ == "__main__":
    unittest.main()
