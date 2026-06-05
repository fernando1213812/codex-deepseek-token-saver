import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_room_desktop as desktop


class DeepSeekRoomDesktopTest(unittest.TestCase):
    def test_default_room_home_uses_workspace(self):
        workspace = Path("/tmp/reasonix-workspace")
        self.assertEqual(
            desktop.default_room_home(workspace),
            workspace / ".deepseek-token-saver" / "rooms",
        )

    def test_default_workspace_root_prefers_settings_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_workspace = Path(tmp) / "workspace"
            fake_workspace.mkdir()
            with mock.patch.object(desktop, "load_settings", return_value={"workspace_root": str(fake_workspace)}):
                with mock.patch.object(sys, "frozen", False, create=True):
                    with mock.patch.dict(os.environ, {}, clear=False):
                        resolved = desktop.default_workspace_root(Path("/repo"))
            self.assertEqual(resolved, fake_workspace.resolve())

    def test_default_workspace_root_uses_repo_root_when_not_frozen(self):
        with mock.patch.object(desktop, "load_settings", return_value={}):
            with mock.patch.object(sys, "frozen", False, create=True):
                with mock.patch.dict(os.environ, {}, clear=False):
                    resolved = desktop.default_workspace_root(Path("/repo-root"))
        self.assertEqual(resolved, Path("/repo-root"))


if __name__ == "__main__":
    unittest.main()
