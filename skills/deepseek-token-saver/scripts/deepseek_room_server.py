#!/usr/bin/env python3
"""Visual room server for DeepSeek/Reasonix orchestration."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_reasonix as reasonix  # noqa: E402
import deepseek_room as room  # noqa: E402


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MESSAGE_LIMIT = 160
DEFAULT_EVENT_LIMIT = 120
ROOT_DIR = SCRIPT_DIR.parents[2]
DEFAULT_STATIC_DIR = ROOT_DIR / "dashboard"
DEFAULT_ASSET_DIR = ROOT_DIR / "assets"
REASONIX_SCRIPT = SCRIPT_DIR / "deepseek_reasonix.py"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the visual Agent Room dashboard server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--room-home", default=os.environ.get("DEEPSEEK_ROOM_HOME", str(Path.cwd() / ".deepseek-token-saver" / "rooms")))
    parser.add_argument("--workspace-root", default=str(ROOT_DIR))
    parser.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR))
    parser.add_argument("--asset-dir", default=str(DEFAULT_ASSET_DIR))
    parser.add_argument("--message-limit", type=int, default=DEFAULT_MESSAGE_LIMIT)
    parser.add_argument("--event-limit", type=int, default=DEFAULT_EVENT_LIMIT)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def ensure_port(host: str, requested: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.2)
        if sock.connect_ex((host, requested)) != 0:
            return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


@dataclasses.dataclass
class JobRecord:
    job_id: str
    room_id: str
    title: str
    command: list[str]
    prompt: str
    status: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._jobs: dict[str, JobRecord] = {}

    def create(self, *, room_id: str, title: str, command: list[str], prompt: str) -> JobRecord:
        with self._lock:
            self._sequence += 1
            job_id = f"job-{self._sequence:04d}"
            record = JobRecord(
                job_id=job_id,
                room_id=room_id,
                title=title,
                command=command,
                prompt=prompt,
                status="queued",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self._jobs[job_id] = record
            return dataclasses.replace(record)

    def update(self, job_id: str, **changes: Any) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = utc_now()
            return dataclasses.replace(job)

    def list(self, room_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [dataclasses.replace(job) for job in self._jobs.values()]
        if room_id:
            jobs = [job for job in jobs if job.room_id == room_id]
        jobs.sort(key=lambda item: item.updated_at, reverse=True)
        return [job.to_dict() for job in jobs]

    def has_running_room_job(self, room_id: str) -> bool:
        with self._lock:
            return any(job.room_id == room_id and job.status in {"queued", "running"} for job in self._jobs.values())

    def room_version(self, room_id: str) -> str:
        jobs = self.list(room_id)
        if not jobs:
            return ""
        return "|".join(f"{job['job_id']}:{job['status']}:{job['updated_at']}" for job in jobs[:4])


class RoomDashboardServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler], args: argparse.Namespace):
        super().__init__(server_address, handler_cls)
        self.args = args
        self.room_home = Path(args.room_home).expanduser()
        self.workspace_root = Path(args.workspace_root).expanduser().resolve()
        self.static_dir = Path(args.static_dir).expanduser().resolve()
        self.asset_dir = Path(args.asset_dir).expanduser().resolve()
        self.message_limit = args.message_limit
        self.event_limit = args.event_limit
        self.jobs = JobStore()

    def room_ids(self) -> list[str]:
        if not self.room_home.exists():
            return []
        room_dirs = [path.parent for path in self.room_home.glob("*/state.json") if path.is_file()]
        room_dirs.sort(key=lambda item: (item / "state.json").stat().st_mtime, reverse=True)
        return [item.name for item in room_dirs]

    def room_summary(self, room_id: str) -> dict[str, Any] | None:
        paths = room.room_paths(self.room_home, room_id)
        state = room.read_json(paths.state)
        if state is None:
            return None
        messages = room.read_jsonl(paths.messages)
        events = room.read_jsonl(paths.events)
        latest_message = messages[-1] if messages else None
        return {
            "room_id": str(state.get("room_id") or room_id),
            "title": str(state.get("title") or room_id),
            "status": str(state.get("status") or "open"),
            "round": int(state.get("round") or 0),
            "updated_at": state.get("updated_at") or state.get("created_at"),
            "message_count": len(messages),
            "event_count": len(events),
            "latest_message_excerpt": room.truncate(str((latest_message or {}).get("content", "")).replace("\n", " "), 160),
            "jobs": self.jobs.list(room_id)[:3],
        }

    def rooms_payload(self) -> dict[str, Any]:
        rooms = [summary for room_id in self.room_ids() if (summary := self.room_summary(room_id))]
        return {
            "rooms": rooms,
            "config": {
                "workspace_root": str(self.workspace_root),
                "room_home": str(self.room_home),
            },
            "generated_at": utc_now(),
        }

    def room_payload(self, room_id: str) -> dict[str, Any]:
        paths = room.room_paths(self.room_home, room_id)
        state = room.read_json(paths.state)
        if state is None:
            raise FileNotFoundError(room_id)
        messages = room.read_jsonl(paths.messages)[-self.message_limit :]
        events = room.read_jsonl(paths.events)[-self.event_limit :]
        payload = {
            "room": state,
            "messages": messages,
            "events": events,
            "artifacts": collect_artifacts(paths.artifacts),
            "transcripts": collect_transcripts(paths.root / "reasonix" / "transcripts"),
            "jobs": self.jobs.list(room_id),
            "paths": {
                "root": str(paths.root),
                "state": str(paths.state),
                "messages": str(paths.messages),
                "events": str(paths.events),
                "artifacts": str(paths.artifacts),
            },
            "generated_at": utc_now(),
        }
        return payload

    def room_version(self, room_id: str) -> str:
        paths = room.room_paths(self.room_home, room_id)
        parts: list[str] = [self.jobs.room_version(room_id)]
        for path in (paths.state, paths.messages, paths.events):
            if path.exists():
                parts.append(f"{path.name}:{path.stat().st_mtime_ns}")
        transcript_root = paths.root / "reasonix" / "transcripts"
        if transcript_root.exists():
            for transcript in sorted(transcript_root.glob("*.jsonl")):
                parts.append(f"{transcript.name}:{transcript.stat().st_mtime_ns}")
        return "|".join(parts)


def collect_artifacts(artifact_dir: Path) -> list[dict[str, Any]]:
    if not artifact_dir.exists():
        return []
    files = [path for path in artifact_dir.iterdir() if path.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return [
        {
            "name": path.name,
            "path": str(path),
            "modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
            "size": path.stat().st_size,
            "excerpt": read_excerpt(path, 1200),
        }
        for path in files[:8]
    ]


def collect_transcripts(transcript_dir: Path) -> list[dict[str, Any]]:
    if not transcript_dir.exists():
        return []
    files = [path for path in transcript_dir.glob("*.jsonl") if path.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    result: list[dict[str, Any]] = []
    for path in files[:8]:
        lines = tail_lines(path, 24)
        result.append(
            {
                "name": path.name,
                "path": str(path),
                "modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
                "size": path.stat().st_size,
                "entries": [parse_transcript_line(line) for line in lines],
            }
        )
    return result


def parse_transcript_line(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return {"kind": "text", "text": line}
    if isinstance(data, dict):
        keys = ["type", "role", "kind", "event", "status", "name", "tool"]
        label = next((str(data[key]) for key in keys if data.get(key)), "entry")
        return {"kind": "json", "label": label, "data": data}
    return {"kind": "json", "label": "entry", "data": data}


def tail_lines(path: Path, limit: int) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def read_excerpt(path: Path, limit: int) -> str:
    try:
        if path.stat().st_size > 200_000:
            return f"[excerpt skipped for large file: {path.name}]"
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return room.truncate(text.strip(), limit)


class Handler(BaseHTTPRequestHandler):
    server: RoomDashboardServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "generated_at": utc_now()})
            return
        if parsed.path == "/api/rooms":
            self.send_json(self.server.rooms_payload())
            return
        if parsed.path.startswith("/api/rooms/") and parsed.path.endswith("/stream"):
            room_id = unquote(parsed.path.split("/")[3])
            self.stream_room(room_id)
            return
        if parsed.path.startswith("/api/rooms/"):
            room_id = unquote(parsed.path.split("/")[3])
            try:
                self.send_json(self.server.room_payload(room_id))
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND, "Room not found")
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        payload = self.read_json_body()
        if parsed.path == "/api/rooms":
            self.create_room(payload)
            return
        if parsed.path.startswith("/api/rooms/") and parsed.path.endswith("/reasonix"):
            room_id = unquote(parsed.path.split("/")[3])
            self.launch_reasonix(room_id, payload)
            return
        if parsed.path.startswith("/api/rooms/") and parsed.path.endswith("/review"):
            room_id = unquote(parsed.path.split("/")[3])
            self.add_review(room_id, payload)
            return
        if parsed.path.startswith("/api/rooms/") and parsed.path.endswith("/post"):
            room_id = unquote(parsed.path.split("/")[3])
            self.add_post(room_id, payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Body must be JSON")
            raise
        if not isinstance(data, dict):
            self.send_error(HTTPStatus.BAD_REQUEST, "Body must be a JSON object")
            raise ValueError("Invalid JSON body")
        return data

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def serve_static(self, path: str) -> None:
        route = "/" if path in {"", "/"} else path
        if route == "/":
            target = self.server.static_dir / "index.html"
        elif route.startswith("/assets/"):
            target = self.server.asset_dir / Path(route.removeprefix("/assets/")).name
        else:
            cleaned = Path(route.lstrip("/"))
            target = (self.server.static_dir / cleaned).resolve()
            if self.server.static_dir not in target.parents and target != self.server.static_dir:
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        mime, _ = mimetypes.guess_type(str(target))
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def create_room(self, payload: dict[str, Any]) -> None:
        title = str(payload.get("title") or "New Room").strip()
        room_id = room.slugify(str(payload.get("room_id") or f"reasonix-{title}"))
        paths = room.room_paths(self.server.room_home, room_id)
        state = room.ensure_room(paths, room_id, title)
        self.send_json({"room": state, "room_path": str(paths.root)}, status=201)

    def launch_reasonix(self, room_id: str, payload: dict[str, Any]) -> None:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            self.send_error(HTTPStatus.BAD_REQUEST, "Prompt is required")
            return
        if self.server.jobs.has_running_room_job(room_id):
            self.send_error(HTTPStatus.CONFLICT, "A job is already running for this room")
            return

        command = [
            sys.executable,
            str(REASONIX_SCRIPT),
            "--room-id",
            room_id,
            "--room-home",
            str(self.server.room_home),
            "--workspace-root",
            str(self.server.workspace_root),
            "--json",
        ]
        title = str(payload.get("title") or room_id).strip()
        if title:
            command.extend(["--title", title])
        for skill_name in normalize_string_list(payload.get("skill_names")):
            command.extend(["--skill-name", skill_name])
        skill_brief = str(payload.get("skill_brief") or "").strip()
        if skill_brief:
            command.extend(["--skill-brief", skill_brief])
        image_brief = str(payload.get("image_brief") or "").strip()
        if image_brief:
            command.extend(["--image-brief", image_brief])
        effort = str(payload.get("effort") or "").strip()
        if effort in {"low", "medium", "high", "max"}:
            command.extend(["--effort", effort])
        subagent_model = str(payload.get("subagent_model") or "").strip()
        if subagent_model in {"flash", "pro"}:
            command.extend(["--subagent-model", subagent_model])
        reasonix_model = str(payload.get("reasonix_model") or "").strip()
        if reasonix_model:
            command.extend(["--reasonix-model", reasonix_model])
        if bool(payload.get("skip_self_review")):
            command.append("--skip-self-review")
        command.append(prompt)

        job = self.server.jobs.create(room_id=room_id, title=title, command=command, prompt=prompt)
        worker = threading.Thread(
            target=run_reasonix_job,
            args=(self.server, job.job_id, command),
            daemon=True,
        )
        worker.start()
        self.send_json({"job": job.to_dict()}, status=202)

    def add_review(self, room_id: str, payload: dict[str, Any]) -> None:
        status = str(payload.get("status") or "needs-rework").strip()
        if status not in {"accepted", "rejected", "needs-rework"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid review status")
            return
        feedback = str(payload.get("feedback") or "").strip()
        if not feedback:
            self.send_error(HTTPStatus.BAD_REQUEST, "Feedback is required")
            return
        paths = room.room_paths(self.server.room_home, room_id)
        state = room.ensure_room(paths, room_id, str(payload.get("title") or room_id))
        message = room.append_message(
            paths,
            role="reviewer",
            agent_id=str(payload.get("reviewer_id") or "human-reviewer"),
            message_type="review",
            content=feedback,
            metadata={
                "review_status": status,
                "reviewer_model": str(payload.get("reviewer_model") or "human"),
                "reviewed_writer_message_id": state.get("latest_writer_message_id"),
                "manual": True,
            },
        )
        updates: dict[str, Any] = {
            "latest_review_message_id": message["id"],
            "status": "accepted" if status == "accepted" else "needs-rework",
        }
        if status == "accepted":
            updates["accepted_message_id"] = state.get("latest_writer_message_id")
        state = room.update_state(paths, updates)
        self.send_json({"room": state, "message": message})

    def add_post(self, room_id: str, payload: dict[str, Any]) -> None:
        content = str(payload.get("content") or "").strip()
        if not content:
            self.send_error(HTTPStatus.BAD_REQUEST, "Content is required")
            return
        role = str(payload.get("role") or "user").strip()
        agent_id = str(payload.get("agent_id") or "manual-user").strip()
        message_type = str(payload.get("message_type") or "note").strip()
        if role not in {"user", "writer", "reviewer", "system"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid role")
            return
        paths = room.room_paths(self.server.room_home, room_id)
        state = room.ensure_room(paths, room_id, str(payload.get("title") or room_id))
        message = room.append_message(
            paths,
            role=role,
            agent_id=agent_id,
            message_type=message_type,
            content=content,
            metadata={"manual": True},
        )
        updates: dict[str, Any] = {}
        if message_type == "task":
            updates["latest_task_message_id"] = message["id"]
            updates["status"] = "open"
        state = room.update_state(paths, updates) if updates else state
        self.send_json({"room": state, "message": message})

    def stream_room(self, room_id: str) -> None:
        try:
            _ = self.server.room_payload(room_id)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, "Room not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_version = ""
        heartbeat = 0
        try:
            while True:
                version = self.server.room_version(room_id)
                if version != last_version:
                    payload = {"room_id": room_id, "version": version, "generated_at": utc_now()}
                    self.wfile.write(f"event: sync\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_version = version
                else:
                    heartbeat += 1
                    if heartbeat >= 15:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        heartbeat = 0
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = [part.strip() for part in value.replace("\n", ",").split(",")]
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def run_reasonix_job(server: RoomDashboardServer, job_id: str, command: list[str]) -> None:
    server.jobs.update(job_id, status="running", started_at=utc_now())
    result = subprocess.run(
        command,
        cwd=str(server.workspace_root),
        capture_output=True,
        text=True,
        check=False,
    )
    server.jobs.update(
        job_id,
        status="succeeded" if result.returncode == 0 else "failed",
        finished_at=utc_now(),
        returncode=result.returncode,
        stdout=result.stdout[-24_000:],
        stderr=result.stderr[-12_000:],
    )


def main() -> int:
    args = parse_args()
    port = ensure_port(args.host, args.port)
    server = RoomDashboardServer((args.host, port), Handler, args)
    payload = {
        "url": f"http://{args.host}:{port}",
        "host": args.host,
        "port": port,
        "room_home": str(server.room_home),
        "workspace_root": str(server.workspace_root),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"Room dashboard server listening on {payload['url']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
