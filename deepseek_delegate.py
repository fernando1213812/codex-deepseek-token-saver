#!/usr/bin/env python3
"""Convenience wrapper for the bundled skill script."""

from __future__ import annotations

from pathlib import Path
import runpy


SCRIPT = Path(__file__).parent / "skills" / "deepseek-token-saver" / "scripts" / "deepseek_delegate.py"


if __name__ == "__main__":
    runpy.run_path(str(SCRIPT), run_name="__main__")
