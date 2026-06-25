import json
import os
import tempfile
import unittest

from aiagent.skills.evaluation import (
    evaluate_skill_selections,
    load_skill_evaluation_cases,
)


class SkillEvaluationTests(unittest.TestCase):
    def test_selection_metrics_include_misses_and_unexpected_skills(self):
        cases = [
            {
                "id": "travel",
                "query": "plan travel",
                "expected_skills": ["travel-planning"],
                "forbidden_skills": ["debug"],
            },
            {
                "id": "review",
                "query": "review code",
                "expected_skills": ["code-review"],
                "forbidden_skills": [],
            },
        ]
        observations = {
            "plan travel": {
                "observed": True,
                "skills": {"travel-planning", "debug"},
            },
            "review code": {"observed": True, "skills": set()},
        }

        report = evaluate_skill_selections(
            cases,
            observations,
            offered_skill_names={"travel-planning", "code-review"},
        )

        self.assertEqual(report["trace_coverage"], 1.0)
        self.assertEqual(report["precision"], 0.5)
        self.assertEqual(report["recall"], 0.5)
        self.assertEqual(report["exact_match_rate"], 0.0)
        self.assertEqual(report["forbidden_hits"], 1)
        self.assertEqual(report["index_coverage"], 1.0)

    def test_unobserved_cases_do_not_distort_selection_precision(self):
        cases = [{
            "id": "travel",
            "query": "plan travel",
            "expected_skills": ["travel-planning"],
            "forbidden_skills": [],
        }]

        report = evaluate_skill_selections(
            cases,
            {"plan travel": {"observed": False, "skills": set()}},
            offered_skill_names=set(),
        )

        self.assertEqual(report["trace_coverage"], 0.0)
        self.assertIsNone(report["precision"])
        self.assertIsNone(report["recall"])
        self.assertEqual(report["index_missing_skills"], ["travel-planning"])

    def test_fixture_loader_validates_duplicate_ids(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = os.path.join(temp_dir.name, "cases.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"cases": [
                {"id": "same", "query": "one", "expected_skills": ["debug"]},
                {"id": "same", "query": "two", "expected_skills": ["debug"]},
            ]}, file)

        with self.assertRaisesRegex(ValueError, "Duplicate case id"):
            load_skill_evaluation_cases(path)

    def test_project_fixture_loads(self):
        cases = load_skill_evaluation_cases(
            os.path.join("tests", "fixtures", "skill_selection_cases.json")
        )

        self.assertEqual(len(cases), 10)
        self.assertEqual(cases[0]["expected_skills"], ["travel-planning"])


if __name__ == "__main__":
    unittest.main()
