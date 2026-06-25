import json
import os
import tempfile
import unittest

from aiagent.memory.evaluation import (
    evaluate_rankings,
    load_recall_fixture,
    parse_thresholds,
    validate_recall_fixture,
)


class MemoryEvaluationTests(unittest.TestCase):
    def test_evaluate_rankings_calculates_retrieval_metrics(self):
        queries = [
            {"id": "q1", "relevant": ["a", "b"]},
            {"id": "q2", "relevant": ["c"]},
            {"id": "n1", "relevant": []},
        ]
        rankings = {
            "q1": ["a", "x", "b"],
            "q2": ["x", "c"],
            "n1": ["z", "y"],
        }

        result = evaluate_rankings(queries, rankings, k=2)

        self.assertAlmostEqual(result["recall"], 2 / 3)
        self.assertAlmostEqual(result["precision"], 2 / 6)
        self.assertEqual(result["hit_rate"], 1.0)
        self.assertEqual(result["mrr"], 0.75)
        self.assertEqual(result["negative_accuracy"], 0.0)
        self.assertEqual(result["average_returned"], 2.0)

    def test_evaluate_rankings_ignores_duplicate_results(self):
        result = evaluate_rankings(
            [{"id": "q1", "relevant": ["a"]}],
            {"q1": ["a", "a", "x"]},
            k=2,
        )

        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["average_returned"], 2.0)

    def test_parse_thresholds_sorts_and_deduplicates(self):
        self.assertEqual(parse_thresholds("0.5, 0.25,0.5"), [0.25, 0.5])

        with self.assertRaises(ValueError):
            parse_thresholds("")
        with self.assertRaises(ValueError):
            parse_thresholds("1.5")

    def test_fixture_rejects_unknown_relevant_memory(self):
        with self.assertRaisesRegex(ValueError, "unknown memories"):
            validate_recall_fixture({
                "memories": [{"key": "known", "user": "u"}],
                "queries": [{
                    "id": "q1",
                    "query": "question",
                    "relevant": ["missing"],
                }],
            })

    def test_load_fixture_reads_utf8_content(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = os.path.join(temp_dir.name, "fixture.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({
                "memories": [{"key": "m1", "user": "桂林"}],
                "queries": [{
                    "id": "q1",
                    "query": "去哪？",
                    "relevant": ["m1"],
                }],
            }, file, ensure_ascii=False)

        fixture = load_recall_fixture(path)

        self.assertEqual(fixture["memories"][0]["user"], "桂林")


if __name__ == "__main__":
    unittest.main()
