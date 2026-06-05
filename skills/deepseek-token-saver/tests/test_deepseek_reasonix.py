import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_reasonix as reasonix
import deepseek_room as room


class DeepSeekReasonixTest(unittest.TestCase):
    def make_args(self, tmp, **overrides):
        defaults = dict(
            prompt=["Build a small dashboard."],
            prompt_file=None,
            room_id="reasonix-room",
            room_home=str(Path(tmp) / "rooms"),
            title="Reasonix Room",
            workspace_root=str(Path(tmp) / "workspace"),
            requester_id="human",
            orchestrator_id="codex-orchestrator",
            reasonix_agent_id="reasonix-body",
            self_reviewer_id="reasonix-self-reviewer",
            reasonix_model="deepseek-v4-pro",
            subagent_model="pro",
            effort="high",
            budget_usd=None,
            target_codex_share=0.10,
            skill_name=["deepseek-token-saver", "diagnose"],
            skill_brief="Codex already routed this as a low-risk implementation task.",
            skill_brief_file=None,
            image_brief="The screenshot shows a compact analytics dashboard with filters on top.",
            image_brief_file=None,
            max_context_chars=4000,
            allow_command=["python3"],
            skip_self_review=False,
            dry_run=False,
            print_main_prompt=False,
            no_keychain=True,
            json=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_runtime_scaffold_writes_config_and_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = room.room_paths(Path(tmp) / "rooms", "reasonix-room")
            room.ensure_room(paths, "reasonix-room")
            runtime = reasonix.reasonix_paths(paths)
            config = reasonix.ensure_reasonix_runtime(
                runtime,
                workspace_root=Path(tmp) / "workspace",
                subagent_model="pro",
                allow_commands=["python3"],
            )
            self.assertTrue(runtime.config.exists())
            self.assertTrue((runtime.skills / "codex-room-critic.md").exists())
            self.assertIn("skills", config)
            self.assertIn("python3", config["projects"][str(Path(tmp) / "workspace")]["shellAllowed"])

    def test_execution_prompt_mentions_multi_agent_and_image_brief(self):
        prompt = reasonix.build_execution_prompt(
            room_id="demo-room",
            user_task="Implement the settings page.",
            skill_summary="Codex skill summary here.",
            image_brief="A settings panel with tabs and toggle rows.",
            messages=[{"id": "msg-0001", "role": "user", "agent_id": "human", "type": "task", "content": "Implement it."}],
            max_context_chars=3000,
        )
        self.assertIn("Execution Plan", prompt)
        self.assertIn("Codex skill summary here.", prompt)
        self.assertIn("A settings panel with tabs and toggle rows.", prompt)
        self.assertIn("Recent room transcript", prompt)

    def test_dry_run_creates_room_and_reasonix_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            code = reasonix.command_run(self.make_args(tmp, workspace_root=str(workspace), dry_run=True))
            self.assertEqual(code, 0)
            paths = room.room_paths(Path(tmp) / "rooms", "reasonix-room")
            state = room.read_json(paths.state)
            self.assertEqual(state["status"], "reasonix-ready")
            self.assertEqual(state["reasonix_runtime"]["model"], "deepseek-v4-pro")
            messages = room.read_jsonl(paths.messages)
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[1]["type"], "orchestrator-brief")

    def test_run_records_execution_and_self_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            execution = reasonix.ReasonixRunResult(
                returncode=0,
                stdout="## Work Completed\nImplemented the dashboard.\n",
                stderr="",
                transcript_path=Path(tmp) / "execution.jsonl",
                prompt_path=Path(tmp) / "execution.md",
                system_path=Path(tmp) / "execution.system.md",
            )
            self_review = reasonix.ReasonixRunResult(
                returncode=0,
                stdout="## Verdict\nNeeds one more test.\n",
                stderr="",
                transcript_path=Path(tmp) / "self-review.jsonl",
                prompt_path=Path(tmp) / "self-review.md",
                system_path=Path(tmp) / "self-review.system.md",
            )
            with mock.patch("deepseek_reasonix.read_api_key", return_value="sk-test"), mock.patch(
                "deepseek_reasonix.run_reasonix_task",
                side_effect=[execution, self_review],
            ):
                code = reasonix.command_run(self.make_args(tmp, workspace_root=str(workspace)))

            self.assertEqual(code, 0)
            paths = room.room_paths(Path(tmp) / "rooms", "reasonix-room")
            state = room.read_json(paths.state)
            self.assertEqual(state["status"], "needs-codex-review")
            self.assertEqual(state["latest_artifact_path"].endswith("round-01-reasonix-execution.md"), True)
            messages = room.read_jsonl(paths.messages)
            self.assertEqual(messages[-2]["type"], "candidate")
            self.assertEqual(messages[-1]["type"], "self-review")
            self.assertIn("Implemented the dashboard", messages[-2]["content"])
            self.assertIn("Needs one more test", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
