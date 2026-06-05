#!/usr/bin/env python3
"""Convenience wrapper for the native desktop room console."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
SCRIPT = ROOT / "skills" / "deepseek-token-saver" / "scripts" / "deepseek_room_desktop.py"


if __name__ == "__main__":
    runpy.run_path(str(SCRIPT), run_name="__main__")
