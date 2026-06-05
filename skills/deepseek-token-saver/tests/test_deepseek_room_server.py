import argparse
import json
import tempfile
import unittest
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_room as room
import deepseek_room_server as server_mod


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


class DeepSeekRoomServerTest(unittest.TestCase):
    def make_args(self, tmp):
        return argparse.Namespace(
            host="127.0.0.1",
            port=0,
            room_home=str(Path(tmp) / "rooms"),
            workspace_root=str(Path(tmp) / "workspace"),
            static_dir=str(Path(tmp) / "dashboard"),
            asset_dir=str(Path(tmp) / "assets"),
            message_limit=50,
            event_limit=50,
            json=False,
        )

    def test_normalize_string_list_accepts_commas_and_newlines(self):
        values = server_mod.normalize_string_list("deepseek-token-saver, diagnose\nhuashu-design")
        self.assertEqual(values, ["deepseek-token-saver", "diagnose", "huashu-design"])

    def test_collect_transcripts_parses_jsonl_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript_dir = Path(tmp) / "reasonix" / "transcripts"
            append_jsonl(transcript_dir / "round-01.jsonl", {"event": "tool_call", "tool": "run_command"})
            append_jsonl(transcript_dir / "round-01.jsonl", {"role": "assistant", "type": "message", "content": "done"})
            transcripts = server_mod.collect_transcripts(transcript_dir)
            self.assertEqual(len(transcripts), 1)
            self.assertEqual(transcripts[0]["entries"][0]["label"], "tool_call")

    def test_room_payload_includes_artifacts_events_and_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            args = self.make_args(tmp)
            server = object.__new__(server_mod.RoomDashboardServer)
            server.args = args
            server.room_home = Path(args.room_home)
            server.workspace_root = workspace
            server.static_dir = Path(args.static_dir)
            server.asset_dir = Path(args.asset_dir)
            server.message_limit = args.message_limit
            server.event_limit = args.event_limit
            server.jobs = server_mod.JobStore()

            paths = room.room_paths(Path(tmp) / "rooms", "demo-room")
            room.ensure_room(paths, "demo-room", "Demo Room")
            room.append_message(
                paths,
                role="user",
                agent_id="human",
                message_type="task",
                content="Build a room UI.",
            )
            append_jsonl(paths.events, {"timestamp": "t1", "event": "reasonix_execution_started"})
            (paths.artifacts / "draft.md").parent.mkdir(parents=True, exist_ok=True)
            (paths.artifacts / "draft.md").write_text("draft artifact", encoding="utf-8")
            transcript_dir = paths.root / "reasonix" / "transcripts"
            append_jsonl(transcript_dir / "round-01.jsonl", {"event": "tool_call", "tool": "run_command"})

            job = server.jobs.create(
                room_id="demo-room",
                title="Demo",
                command=["python3", "deepseek_reasonix.py"],
                prompt="Build a room UI.",
            )
            server.jobs.update(job.job_id, status="running")

            payload = server.room_payload("demo-room")
            self.assertEqual(payload["room"]["title"], "Demo Room")
            self.assertEqual(payload["messages"][0]["content"], "Build a room UI.")
            self.assertEqual(payload["events"][0]["event"], "reasonix_execution_started")
            self.assertEqual(payload["artifacts"][0]["name"], "draft.md")
            self.assertEqual(payload["transcripts"][0]["name"], "round-01.jsonl")
            self.assertEqual(payload["jobs"][0]["status"], "running")


if __name__ == "__main__":
    unittest.main()
