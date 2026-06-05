import argparse
import json
import tempfile
import unittest
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_agent as agent
import deepseek_delegate as delegate


class DeepSeekDelegateTest(unittest.TestCase):
    def test_retry_after_seconds(self):
        self.assertEqual(delegate.parse_retry_after({"retry-after": "2.5"}), 2.5)

    def test_retryable_http_statuses(self):
        self.assertTrue(delegate.should_retry_http(408))
        self.assertTrue(delegate.should_retry_http(429))
        self.assertTrue(delegate.should_retry_http(500))
        self.assertFalse(delegate.should_retry_http(400))

    def test_log_call_records_quality_and_output_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "calls.jsonl"
            args = argparse.Namespace(
                model="deepseek-chat",
                phase="draft",
                risk="low",
                urgency="normal",
                savings_ratio=0.7,
                out="candidate.md",
                log_file=str(log_file),
            )
            decision = delegate.RouteDecision("deepseek", "test", True)
            entry = delegate.log_call(
                args=args,
                prompt="prompt",
                decision=decision,
                response_text="response",
                usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                finish_reason="stop",
                reasoning_chars=0,
                request_metadata={"attempts": 1},
                quality_status="pass",
                output_written=True,
            )
            self.assertEqual(entry["quality_gate"]["status"], "pass")
            self.assertTrue(entry["output_written"])
            self.assertEqual(json.loads(log_file.read_text())["request"]["attempts"], 1)


class DeepSeekAgentTest(unittest.TestCase):
    def make_args(self, **overrides):
        defaults = dict(
            agent_id="worker",
            agent_role="draft-worker",
            agent_purpose="test worker",
            workflow_id=None,
            task_id=None,
            parent_agent_id="codex-gpt-5.5",
            new_agent=False,
            agent_home="",
            list_agents=False,
            memory_note=None,
            memory_mode="read-write",
            memory_window=10,
            memory_char_budget=6000,
            remember_response_chars=2200,
            reflection_mode="auto",
            record_review=False,
            review_status="pending",
            reflection=None,
            remember=None,
            require_section=[],
            require_regex=[],
            expect_json=False,
            fail_on_finish_reason=["length", "content_filter"],
            phase="draft",
            risk="low",
            urgency="normal",
            force_deepseek=False,
            model="deepseek-chat",
            system=agent.DEFAULT_AGENT_SYSTEM,
            max_tokens=100,
            min_response_chars=0,
            temperature=0.2,
            timeout=120,
            max_retries=0,
            retry_initial_delay=0.1,
            retry_max_delay=1,
            thinking="auto",
            out=None,
            log_file="",
            json=False,
            raw=False,
            verbose=False,
            no_keychain=True,
            savings_ratio=0.7,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_slugify_blocks_path_traversal(self):
        self.assertEqual(agent.slugify("../bad agent"), "bad-agent")
        self.assertEqual(agent.slugify(""), agent.DEFAULT_AGENT_ID)

    def test_record_review_writes_durable_memory_and_reflection(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.make_args(
                agent_home=tmp,
                remember="Codex-approved lesson.",
                reflection="Codex reflection.",
                review_status="accepted",
            )
            paths = agent.agent_paths(tmp, "worker")
            agent.ensure_agent(paths, "worker", args)
            agent.record_review(paths, args, "worker")
            memory = [json.loads(line) for line in paths.memory.read_text().splitlines()]
            reflections = [json.loads(line) for line in paths.reflections.read_text().splitlines()]
            self.assertEqual(memory[0]["role"], "codex-review")
            self.assertIn("Codex-approved", memory[0]["content"])
            self.assertEqual(reflections[0]["review_status"], "accepted")

    def test_recent_memory_excludes_transcript_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = agent.agent_paths(tmp, "worker")
            paths.root.mkdir(parents=True)
            for item in [
                {"role": "user", "content": "do not inject"},
                {"role": "assistant", "content": "do not inject either"},
                {"role": "codex-review", "content": "approved"},
            ]:
                agent.append_jsonl(paths.memory, item)
            recent = agent.read_recent_memory(paths, limit=10, char_budget=1000)
            self.assertEqual([item["content"] for item in recent], ["approved"])

    def test_quality_issues_cover_shape_finish_reason_and_json(self):
        args = self.make_args(
            min_response_chars=10,
            require_section=["Required"],
            require_regex=[r"ok-\d+"],
            expect_json=True,
        )
        issues = agent.quality_issues(args, "short", "length", reasoning_chars=100)
        self.assertIn("response_too_short:5<10", issues)
        self.assertIn("finish_reason:length", issues)
        self.assertIn("missing_section:Required", issues)
        self.assertIn(r"missing_regex:ok-\d+", issues)
        self.assertTrue(any(issue.startswith("invalid_json") for issue in issues))

    def test_update_memory_writes_transcript_not_durable_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = agent.agent_paths(tmp, "worker")
            args = self.make_args(agent_home=tmp)
            agent.update_memory(
                paths,
                args,
                prompt="prompt",
                response_text="response",
                finish_reason="stop",
                reasoning_chars=0,
                issues=[],
            )
            self.assertFalse(paths.memory.exists())
            self.assertTrue(paths.transcript.exists())


if __name__ == "__main__":
    unittest.main()
