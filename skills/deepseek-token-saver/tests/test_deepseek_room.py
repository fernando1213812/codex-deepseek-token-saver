import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_room as room


class DeepSeekRoomTest(unittest.TestCase):
    def make_writer_args(self, tmp, **overrides):
        defaults = dict(
            room_id="demo-room",
            room_home=str(Path(tmp) / "rooms"),
            title=None,
            json=False,
            writer_id="writer",
            reviewer_id="reviewer",
            requester_id="human",
            agent_home=str(Path(tmp) / "agents"),
            task_id=None,
            prompt=None,
            prompt_file=None,
            out=None,
            phase="implement",
            max_tokens=100,
            temperature=0.2,
            min_response_chars=10,
            max_context_chars=8000,
            require_section=[],
            require_regex=[],
            expect_json=False,
            thinking="auto",
            force_deepseek=False,
            no_keychain=True,
            log_file=str(Path(tmp) / "calls.jsonl"),
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def make_review_args(self, tmp, **overrides):
        defaults = dict(
            room_id="demo-room",
            room_home=str(Path(tmp) / "rooms"),
            title=None,
            json=False,
            reviewer_id="reviewer",
            writer_id="writer",
            agent_home=str(Path(tmp) / "agents"),
            status="needs-rework",
            feedback="Fix the missing keyboard path.",
            feedback_file=None,
            reviewer_model="gpt-5.5",
            record_to_writer_memory=False,
            remember=None,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_slugify_blocks_path_traversal(self):
        self.assertEqual(room.slugify("../bad room"), "bad-room")
        self.assertEqual(room.slugify(""), "agent-room")

    def test_append_task_and_rejected_review_drive_retry_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = room.room_paths(Path(tmp) / "rooms", "demo-room")
            state = room.ensure_room(paths, "demo-room", "Demo")
            self.assertEqual(state["status"], "open")

            task = room.append_message(
                paths,
                role="user",
                agent_id="human",
                message_type="task",
                content="Build a clickable calculator.",
            )
            candidate = room.append_message(
                paths,
                role="writer",
                agent_id="writer",
                message_type="candidate",
                content="Only a screenshot, no event handlers.",
            )
            review = room.append_message(
                paths,
                role="reviewer",
                agent_id="reviewer",
                message_type="review",
                content="Rejected: it cannot click or type.",
                metadata={"review_status": "needs-rework"},
            )
            room.update_state(
                paths,
                {
                    "latest_task_message_id": task["id"],
                    "latest_writer_message_id": candidate["id"],
                    "latest_review_message_id": review["id"],
                    "status": "needs-rework",
                },
            )

            prompt = room.build_writer_prompt(
                room_id="demo-room",
                prompt="",
                messages=room.read_jsonl(paths.messages),
                max_context_chars=4000,
            )
            self.assertIn("Build a clickable calculator.", prompt)
            self.assertIn("Rejected: it cannot click or type.", prompt)
            self.assertIn("Reviewer feedback overrides", prompt)
            self.assertIn("Previous candidate excerpt", prompt)

    def test_review_command_changes_state_to_needs_rework(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = room.room_paths(Path(tmp) / "rooms", "demo-room")
            room.ensure_room(paths, "demo-room")
            room.append_message(
                paths,
                role="writer",
                agent_id="writer",
                message_type="candidate",
                content="candidate",
            )
            room.update_state(paths, {"latest_writer_message_id": "msg-0001", "status": "needs-review"})

            code = room.command_review(self.make_review_args(tmp))
            self.assertEqual(code, 0)
            state = room.read_json(paths.state)
            self.assertEqual(state["status"], "needs-rework")
            messages = room.read_jsonl(paths.messages)
            self.assertEqual(messages[-1]["metadata"]["review_status"], "needs-rework")

    def test_writer_command_records_deepseek_candidate_without_real_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope = {
                "agent_id": "writer",
                "task_id": "round-01",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                "estimated_codex_tokens_saved": 2,
                "finish_reason": "stop",
                "reasoning_chars": 0,
                "quality_issues": [],
                "response": "Candidate implementation with event handlers.",
            }
            completed = subprocess.CompletedProcess(
                args=["deepseek_agent.py"],
                returncode=0,
                stdout=json.dumps(envelope),
                stderr="",
            )
            with mock.patch("deepseek_room.subprocess.run", return_value=completed):
                code = room.command_writer(self.make_writer_args(tmp, prompt="Build a calculator."))

            self.assertEqual(code, 0)
            paths = room.room_paths(Path(tmp) / "rooms", "demo-room")
            state = room.read_json(paths.state)
            self.assertEqual(state["status"], "needs-review")
            self.assertEqual(state["round"], 1)
            messages = room.read_jsonl(paths.messages)
            self.assertEqual(messages[-1]["role"], "writer")
            self.assertIn("event handlers", messages[-1]["content"])
            self.assertEqual(messages[-1]["metadata"]["usage"]["total_tokens"], 3)

    def test_writer_command_does_not_accept_routed_away_empty_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope = {
                "agent_id": "writer",
                "decision": {
                    "route": "gpt-5.5",
                    "reason": "review/final phases must stay with GPT-5.5.",
                    "requires_gpt55_review": False,
                },
                "response": "",
            }
            completed = subprocess.CompletedProcess(
                args=["deepseek_agent.py"],
                returncode=0,
                stdout=json.dumps(envelope),
                stderr="",
            )
            with mock.patch("deepseek_room.subprocess.run", return_value=completed):
                code = room.command_writer(self.make_writer_args(tmp, prompt="Review-ish prompt."))

            self.assertEqual(code, 3)
            paths = room.room_paths(Path(tmp) / "rooms", "demo-room")
            state = room.read_json(paths.state)
            self.assertEqual(state["status"], "writer-routed-away")
            messages = room.read_jsonl(paths.messages)
            self.assertEqual([message["role"] for message in messages], ["user"])


if __name__ == "__main__":
    unittest.main()
