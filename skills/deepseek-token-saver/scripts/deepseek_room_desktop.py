#!/usr/bin/env python3
"""Native desktop shell for the visual DeepSeek/Reasonix room console."""

from __future__ import annotations

import argparse
import atexit
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any
from urllib.request import urlopen
import webbrowser


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_room_server as room_server  # noqa: E402


APP_NAME = "Reasonix Room Console"
DEFAULT_WIDTH = 1460
DEFAULT_HEIGHT = 940
SETTINGS_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
LOG_PATH = SETTINGS_DIR / "desktop.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the native desktop room console.")
    parser.add_argument("--host", default=room_server.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=room_server.DEFAULT_PORT)
    parser.add_argument("--workspace-root", help="Workspace the Reasonix room should operate in.")
    parser.add_argument("--room-home", help="Override the room history directory.")
    parser.add_argument("--title", default=APP_NAME)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--message-limit", type=int, default=room_server.DEFAULT_MESSAGE_LIMIT)
    parser.add_argument("--event-limit", type=int, default=room_server.DEFAULT_EVENT_LIMIT)
    parser.add_argument("--browser-fallback", action="store_true", help="Open the app in the default browser instead of a native window.")
    parser.add_argument("--pick-workspace", action="store_true", help="Prompt to choose a workspace even if one is already remembered.")
    parser.add_argument("--debug", action="store_true", help="Enable webview debug tools when available.")
    return parser.parse_args()


def resource_root() -> Path:
    bundled = os.environ.get("RESOURCEPATH")
    if bundled:
        return Path(bundled).expanduser().resolve()
    return SCRIPT_DIR.parents[2]


def load_settings() -> dict[str, Any]:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict[str, Any]) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def log_line(message: str) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def prompt_for_workspace(initial: Path | None = None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    selected = filedialog.askdirectory(
        title="Choose a workspace for Reasonix Room Console",
        initialdir=str(initial or Path.home()),
        mustexist=True,
    )
    root.destroy()
    return Path(selected).expanduser().resolve() if selected else None


def default_workspace_root(root_dir: Path, *, force_pick: bool = False) -> Path:
    if os.environ.get("DEEPSEEK_WORKSPACE_ROOT"):
        return Path(os.environ["DEEPSEEK_WORKSPACE_ROOT"]).expanduser().resolve()
    settings = load_settings()
    remembered = settings.get("workspace_root")
    if remembered and not force_pick:
        path = Path(str(remembered)).expanduser().resolve()
        if path.exists():
            return path
    if getattr(sys, "frozen", False) or os.environ.get("RESOURCEPATH"):
        picked = prompt_for_workspace(Path.home()) if (force_pick or not remembered) else None
        if picked is None and remembered:
            path = Path(str(remembered)).expanduser().resolve()
            if path.exists():
                return path
        if picked is None:
            raise SystemExit("A workspace folder is required to launch the desktop app.")
        save_settings({"workspace_root": str(picked)})
        return picked
    return root_dir


def default_room_home(workspace_root: Path) -> Path:
    if os.environ.get("DEEPSEEK_ROOM_HOME"):
        return Path(os.environ["DEEPSEEK_ROOM_HOME"]).expanduser().resolve()
    return workspace_root / ".deepseek-token-saver" / "rooms"


def start_server(args: argparse.Namespace, root_dir: Path) -> tuple[room_server.RoomDashboardServer, threading.Thread, str]:
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace_root(root_dir, force_pick=args.pick_workspace)
    room_home = Path(args.room_home).expanduser().resolve() if args.room_home else default_room_home(workspace_root)
    room_home.mkdir(parents=True, exist_ok=True)
    server_args = argparse.Namespace(
        host=args.host,
        port=args.port,
        room_home=str(room_home),
        workspace_root=str(workspace_root),
        static_dir=str(root_dir / "dashboard"),
        asset_dir=str(root_dir / "assets"),
        message_limit=args.message_limit,
        event_limit=args.event_limit,
        json=False,
    )
    port = room_server.ensure_port(args.host, args.port)
    server = room_server.RoomDashboardServer((args.host, port), room_server.Handler, server_args)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://{args.host}:{port}"
    wait_for_server(url)
    return server, worker, url


def wait_for_server(url: str, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(f"{url}/api/health", timeout=0.8) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Room server failed to start at {url}")


def stop_server(server: room_server.RoomDashboardServer) -> None:
    if getattr(server, "_desktop_stopped", False):
        return
    setattr(server, "_desktop_stopped", True)
    try:
        server.shutdown()
    finally:
        server.server_close()


def launch_browser(url: str) -> int:
    webbrowser.open(url)
    print(f"{APP_NAME} is running at {url}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


def launch_native_window(url: str, args: argparse.Namespace) -> int:
    try:
        import webview
    except Exception:
        return launch_browser(url)
    webview.create_window(
        title=args.title,
        url=url,
        width=max(1180, args.width),
        height=max(760, args.height),
        min_size=(1100, 720),
        background_color="#0c1015",
        text_select=True,
    )
    webview.start(debug=args.debug)
    return 0


def main() -> int:
    args = parse_args()
    root_dir = resource_root()
    try:
        log_line(f"launch root={root_dir} browser_fallback={args.browser_fallback} pick_workspace={args.pick_workspace}")
        server, worker, url = start_server(args, root_dir)
        atexit.register(stop_server, server)
        log_line(f"server_started url={url}")
        if args.browser_fallback:
            return launch_browser(url)
        return launch_native_window(url, args)
    except Exception as exc:
        log_line(f"launch_failed error={exc!r}")
        raise
    finally:
        if "server" in locals():
            stop_server(server)
            worker.join(timeout=2.0)
            log_line("server_stopped")


if __name__ == "__main__":
    raise SystemExit(main())
