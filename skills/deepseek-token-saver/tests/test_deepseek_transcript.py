import json
import tempfile
import unittest
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_transcript as transcript


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


class DeepSeekTranscriptTest(unittest.TestCase):
    def test_render_agent_includes_transcript_review_and_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agents" / "worker"
            write_json(root / "profile.json", {"agent_id": "worker", "role": "implementer"})
            append_jsonl(root / "transcript.jsonl", {"timestamp": "t1", "role": "user", "phase": "implement", "content": "Build a thing."})
            append_jsonl(
                root / "transcript.jsonl",
                {
                    "timestamp": "t2",
                    "role": "assistant",
                    "phase": "implement",
                    "content": "Candidate code.",
                    "finish_reason": "stop",
                    "response_chars": 15,
                },
            )
            append_jsonl(root / "reflections.jsonl", {"timestamp": "t3", "review_status": "accepted", "lesson": "Verified."})
            append_jsonl(root / "memory.jsonl", {"timestamp": "t4", "role": "codex-review", "content": "Keep quality gates."})
            append_jsonl(
                root / "events.jsonl",
                {
                    "timestamp": "t5",
                    "event": "call",
                    "usage": {"total_tokens": 3},
                    "log_entry": {"estimated_codex_tokens_saved": 2},
                },
            )

            markdown = transcript.render_agent(root, max_chars=100, include_full=False)
            self.assertIn("DeepSeek Worker Transcript - worker", markdown)
            self.assertIn("Build a thing.", markdown)
            self.assertIn("Review 1: accepted", markdown)
            self.assertIn("Keep quality gates.", markdown)
            self.assertIn("estimated_codex_tokens_saved", markdown)

    def test_render_room_includes_messages_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rooms" / "demo-room"
            write_json(root / "state.json", {"room_id": "demo-room", "status": "needs-review", "round": 1})
            append_jsonl(
                root / "messages.jsonl",
                {"id": "msg-0001", "timestamp": "t1", "role": "user", "agent_id": "human", "type": "task", "content": "Build it."},
            )
            append_jsonl(
                root / "messages.jsonl",
                {
                    "id": "msg-0002",
                    "timestamp": "t2",
                    "role": "writer",
                    "agent_id": "writer",
                    "type": "candidate",
                    "content": "Candidate.",
                    "metadata": {"usage": {"total_tokens": 3}},
                },
            )
            append_jsonl(
                root / "events.jsonl",
                {
                    "event": "reasonix_execution",
                    "timestamp": "t3",
                    "phase": "execution",
                    "model": "deepseek-v4-pro",
                    "artifact_path": "/tmp/artifact.md",
                    "transcript_path": "/tmp/transcript.jsonl",
                },
            )

            markdown = transcript.render_room(root, max_chars=100, include_full=False)
            self.assertIn("Agent Room Transcript - demo-room", markdown)
            self.assertIn("msg-0001 user human / task", markdown)
            self.assertIn("Build it.", markdown)
            self.assertIn("needs-review", markdown)
            self.assertIn("/tmp/transcript.jsonl", markdown)

    def test_select_single_agent_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent_home = Path(tmp) / "agents"
            room_home = Path(tmp) / "rooms"
            (agent_home / "worker").mkdir(parents=True)
            (agent_home / "worker" / "transcript.jsonl").write_text("", encoding="utf-8")
            args = type("Args", (), {"agent_id": None, "room_id": None, "all": False, "latest": False})
            self.assertEqual(transcript.select_exports(args, agent_home, room_home), [("agent", agent_home / "worker")])

    def test_multiple_sources_require_explicit_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent_home = Path(tmp) / "agents"
            room_home = Path(tmp) / "rooms"
            (agent_home / "worker").mkdir(parents=True)
            (room_home / "room").mkdir(parents=True)
            (agent_home / "worker" / "transcript.jsonl").write_text("", encoding="utf-8")
            (room_home / "room" / "messages.jsonl").write_text("", encoding="utf-8")
            args = type("Args", (), {"agent_id": None, "room_id": None, "all": False, "latest": False})
            with self.assertRaises(ValueError):
                transcript.select_exports(args, agent_home, room_home)


if __name__ == "__main__":
    unittest.main()
