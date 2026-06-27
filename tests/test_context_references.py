import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from aiagent.context_references import (
    parse_context_references,
    preprocess_context_references,
)
from aiagent.conversation_loop import run_conversation_loop
from aiagent.turn_context import build_turn_context


class ContextReferenceParsingTests(unittest.TestCase):
    def test_parse_file_folder_diff_and_url_references(self):
        refs = parse_context_references(
            "review @file:main.py:2-4 and @folder:aiagent plus @diff and @url:https://example.com/a"
        )

        self.assertEqual([ref.kind for ref in refs], ["file", "folder", "diff", "url"])
        self.assertEqual(refs[0].target, "main.py")
        self.assertEqual(refs[0].line_start, 2)
        self.assertEqual(refs[0].line_end, 4)
        self.assertEqual(refs[-1].target, "https://example.com/a")

    def test_parse_quoted_file_reference_with_spaces(self):
        refs = parse_context_references('read @file:"docs/my note.md":3')

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "docs/my note.md")
        self.assertEqual(refs[0].line_start, 3)


class ContextReferenceExpansionTests(unittest.TestCase):
    def test_file_reference_attaches_file_content_and_strips_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "note.txt").write_text("alpha\nbeta\ngamma", encoding="utf-8")

            result = preprocess_context_references(
                "explain @file:note.txt:2",
                workspace=tmpdir,
                context_window=4000,
            )

        self.assertTrue(result.expanded)
        self.assertEqual(result.message, "explain")
        self.assertIn("beta", result.context)
        self.assertNotIn("alpha", result.context)

    def test_folder_reference_attaches_listing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "pkg").mkdir()
            Path(tmpdir, "pkg", "a.py").write_text("print('a')", encoding="utf-8")

            result = preprocess_context_references(
                "summarize @folder:pkg",
                workspace=tmpdir,
                context_window=4000,
            )

        self.assertTrue(result.expanded)
        self.assertIn("a.py", result.context)

    def test_reference_outside_workspace_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outside = Path(tmpdir).parent / "outside-context-reference-test.txt"
            outside.write_text("secret", encoding="utf-8")
            self.addCleanup(lambda: outside.exists() and outside.unlink())

            result = preprocess_context_references(
                f"read @file:{outside}",
                workspace=tmpdir,
                context_window=4000,
            )

        self.assertTrue(result.expanded)
        self.assertNotIn("secret", result.context)
        self.assertIn("outside workspace", "\n".join(result.warnings))

    def test_url_reference_uses_fetcher(self):
        result = preprocess_context_references(
            "summarize @url:https://example.com",
            workspace=".",
            context_window=4000,
            url_fetcher=lambda url: f"content from {url}",
        )

        self.assertTrue(result.expanded)
        self.assertIn("content from https://example.com", result.context)

    @unittest.skipUnless(shutil.which("git"), "git is required for @diff")
    def test_diff_reference_attaches_git_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, check=True)
            Path(tmpdir, "a.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "a.txt"], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True)
            Path(tmpdir, "a.txt").write_text("one\ntwo\n", encoding="utf-8")

            result = preprocess_context_references(
                "summarize @diff",
                workspace=tmpdir,
                context_window=4000,
            )

        self.assertTrue(result.expanded)
        self.assertIn("+two", result.context)


class EmptyTools:
    def get_definitions(self):
        return []


class CaptureLLM:
    def __init__(self):
        self.messages = None

    def stream_chat(self, messages, tools, on_delta):
        self.messages = messages
        return {
            "content": "ok",
            "tool_calls": None,
            "usage": {"input": 3, "output": 1},
        }


class ReferenceAgent:
    def __init__(self, workspace):
        self.messages = []
        self.llm = CaptureLLM()
        self.tools = EmptyTools()
        self.memory_manager = None
        self.history_recall_config = {"enabled": False}
        self.system_prompt = "system"
        self.workspace = workspace
        self.context_window = 120000
        self.max_iterations = 2
        self.max_compress_tokens = 100000
        self.compression_enabled = True
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.conv_id = "c1"
        self.model = "test-model"

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def update_current_context(self, actual_tokens, estimated_tokens=0):
        self.current_context_tokens = actual_tokens or estimated_tokens

    def compress_messages(self, keep_tokens=None):
        return {"compressed": False}


class TurnContextReferenceTests(unittest.TestCase):
    def test_turn_context_replaces_current_user_message_for_model_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "note.txt").write_text("attached text", encoding="utf-8")
            agent = ReferenceAgent(tmpdir)

            context = build_turn_context(agent, "explain @file:note.txt")
            messages = context.build_messages([
                {"role": "user", "content": "explain @file:note.txt"}
            ])

        self.assertTrue(context.reference_context)
        self.assertIn("attached text", json.dumps(messages, ensure_ascii=False))
        self.assertEqual(messages[-1]["content"], "explain")

    def test_conversation_loop_does_not_persist_attached_file_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "note.txt").write_text("attached text", encoding="utf-8")
            agent = ReferenceAgent(tmpdir)
            statuses = []

            result = run_conversation_loop(
                agent,
                "explain @file:note.txt",
                on_status=statuses.append,
            )

        self.assertEqual(result, "ok")
        self.assertIn("attached text", json.dumps(agent.llm.messages, ensure_ascii=False))
        self.assertNotIn("attached text", json.dumps(agent.messages, ensure_ascii=False))
        self.assertEqual(agent.messages[0]["content"], "explain @file:note.txt")
        self.assertIn("context_references", [event["type"] for event in statuses])


if __name__ == "__main__":
    unittest.main()
