import os
import tempfile
import unittest

from aiagent.skills.usage_store import SkillUsageStore


class SkillUsageStoreTests(unittest.TestCase):
    def make_store(self, **kwargs):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = SkillUsageStore(
            os.path.join(temp_dir.name, "skill_usage.sqlite3"),
            **kwargs,
        )
        self.addCleanup(store.close)
        return store

    def test_records_turns_events_and_aggregates_stats(self):
        store = self.make_store()
        workspace = os.path.abspath("workspace-a")
        first_turn = store.start_turn(
            user_query="plan a trip",
            conversation_id="c1",
            model="test",
            workspace=workspace,
        )
        store.record(
            turn_id=first_turn,
            skill_name="travel-planning",
            event_type="view",
            success=True,
            executed=True,
            duration_ms=12,
            workspace=workspace,
            user_query="plan a trip",
        )
        store.record(
            turn_id=first_turn,
            skill_name="travel-planning",
            event_type="script_run",
            success=False,
            executed=False,
            duration_ms=0,
            workspace=workspace,
            user_query="plan a trip",
            error="denied",
        )
        store.start_turn(
            user_query="just chat",
            conversation_id="c1",
            model="test",
            workspace=workspace,
        )

        stats = store.stats(workspace=workspace)

        self.assertEqual(stats["total_turns"], 2)
        self.assertEqual(stats["total_events"], 2)
        self.assertEqual(stats["turns_with_skills"], 1)
        self.assertEqual(stats["skill_load_rate"], 0.5)
        self.assertEqual(stats["success_rate"], 0.5)
        self.assertEqual(stats["skills"][0]["views"], 1)
        self.assertEqual(stats["skills"][0]["script_runs"], 1)
        self.assertEqual(stats["skills"][0]["denied"], 1)

    def test_evaluation_observes_turns_with_no_selected_skill(self):
        store = self.make_store()
        workspace = os.path.abspath("workspace-a")
        selected_turn = store.start_turn(
            user_query="review code",
            workspace=workspace,
        )
        store.record(
            turn_id=selected_turn,
            skill_name="code-review",
            event_type="view",
            success=True,
            executed=True,
            workspace=workspace,
            user_query="review code",
        )
        store.start_turn(user_query="plan travel", workspace=workspace)

        observations = store.evaluation_observations(
            ["review code", "plan travel", "not observed"],
            workspace=workspace,
        )

        self.assertTrue(observations["review code"]["observed"])
        self.assertEqual(observations["review code"]["skills"], {"code-review"})
        self.assertTrue(observations["plan travel"]["observed"])
        self.assertEqual(observations["plan travel"]["skills"], set())
        self.assertFalse(observations["not observed"]["observed"])

    def test_workspace_stats_are_isolated(self):
        store = self.make_store()
        first = os.path.abspath("workspace-a")
        second = os.path.abspath("workspace-b")
        first_turn = store.start_turn(user_query="one", workspace=first)
        second_turn = store.start_turn(user_query="two", workspace=second)
        store.record(
            turn_id=first_turn,
            skill_name="debug",
            event_type="view",
            success=True,
            executed=True,
            workspace=first,
        )
        store.record(
            turn_id=second_turn,
            skill_name="travel-planning",
            event_type="view",
            success=True,
            executed=True,
            workspace=second,
        )

        stats = store.stats(workspace=first)

        self.assertEqual(stats["total_turns"], 1)
        self.assertEqual(stats["skills"][0]["skill_name"], "debug")

    def test_query_storage_redacts_secrets_and_can_be_disabled(self):
        store = self.make_store()
        turn_id = store.start_turn(user_query="token=very-secret-value", workspace=".")
        store.record(
            turn_id=turn_id,
            skill_name="debug",
            event_type="view",
            success=True,
            executed=True,
            workspace=".",
            user_query="token=very-secret-value",
        )
        self.assertNotIn("very-secret-value", store.recent(1)[0].get("user_query", ""))

        disabled_queries = self.make_store(store_queries=False)
        disabled_queries.start_turn(user_query="private conversation", workspace=".")
        observations = disabled_queries.evaluation_observations(["private conversation"])
        self.assertFalse(observations["private conversation"]["observed"])

    def test_disabled_store_does_not_create_database(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = os.path.join(temp_dir.name, "disabled.sqlite3")
        store = SkillUsageStore(path, enabled=False)

        self.assertIsNone(store.start_turn(user_query="hello"))
        self.assertFalse(store.stats()["enabled"])
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
