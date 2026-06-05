#!/usr/bin/env python3
"""Export DeepSeek worker or Agent Room transcripts as readable Markdown."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


DEFAULT_ROOT = Path.cwd() / ".deepseek-token-saver"
DEFAULT_AGENT_HOME = DEFAULT_ROOT / "agents"
DEFAULT_ROOM_HOME = DEFAULT_ROOT / "rooms"


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    slug = re.sub(r"\.{2,}", "-", slug)
    slug = slug.strip("-._")
    return slug[:80] or "transcript"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def json_short(data: Any) -> str:
    if data in (None, {}, []):
        return ""
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    suffix = f"\n\n[...truncated; original {len(text)} chars...]"
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def fenced(text: str) -> str:
    max_ticks = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    ticks = "`" * max(3, max_ticks + 1)
    return f"{ticks}text\n{text}\n{ticks}"


def excerpt(text: str, *, limit: int, include_full: bool) -> str:
    content = text if include_full else truncate(text, limit)
    return fenced(html.unescape(content))


def format_metadata(items: list[tuple[str, Any]]) -> list[str]:
    lines: list[str] = []
    for key, value in items:
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {key}: `{json_short(value) if isinstance(value, (dict, list)) else value}`")
    return lines


def discover_agents(agent_home: Path) -> list[Path]:
    if not agent_home.exists():
        return []
    return sorted(
        path.parent for path in agent_home.glob("*/transcript.jsonl")
        if path.is_file()
    )


def discover_rooms(room_home: Path) -> list[Path]:
    if not room_home.exists():
        return []
    return sorted(
        path.parent for path in room_home.glob("*/messages.jsonl")
        if path.is_file()
    )


def latest_path(paths: list[Path], marker_name: str) -> Path | None:
    existing = [path for path in paths if (path / marker_name).exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: (path / marker_name).stat().st_mtime)


def render_agent(agent_root: Path, *, max_chars: int, include_full: bool) -> str:
    profile = read_json(agent_root / "profile.json") or {}
    transcript = read_jsonl(agent_root / "transcript.jsonl")
    reflections = read_jsonl(agent_root / "reflections.jsonl")
    memory = read_jsonl(agent_root / "memory.jsonl")
    events = read_jsonl(agent_root / "events.jsonl")

    agent_id = str(profile.get("agent_id") or agent_root.name)
    lines = [
        f"# DeepSeek Worker Transcript - {agent_id}",
        "",
        "## Source",
        "",
        f"- Agent root: `{agent_root}`",
        f"- Transcript: `{agent_root / 'transcript.jsonl'}`",
        f"- Reviews: `{agent_root / 'reflections.jsonl'}`",
        f"- Durable memory: `{agent_root / 'memory.jsonl'}`",
        f"- Events: `{agent_root / 'events.jsonl'}`",
        "",
        "## Profile",
        "",
    ]
    profile_lines = format_metadata(
        [
            ("agent_id", profile.get("agent_id")),
            ("role", profile.get("role")),
            ("purpose", profile.get("purpose")),
            ("model", profile.get("model")),
            ("last_model", profile.get("last_model")),
            ("created_at", profile.get("created_at")),
            ("last_seen_at", profile.get("last_seen_at")),
        ]
    )
    lines.extend(profile_lines or ["- No profile metadata found."])
    lines.extend(["", "## Transcript", ""])
    if not transcript:
        lines.append("_No transcript entries found._")
    for index, entry in enumerate(transcript, 1):
        role = entry.get("role", "message")
        timestamp = entry.get("timestamp", "")
        phase = entry.get("phase", "")
        lines.extend(
            [
                f"### {index}. {role} {phase}".strip(),
                "",
                *format_metadata(
                    [
                        ("timestamp", timestamp),
                        ("workflow_id", entry.get("workflow_id")),
                        ("task_id", entry.get("task_id")),
                        ("finish_reason", entry.get("finish_reason")),
                        ("reasoning_chars", entry.get("reasoning_chars")),
                        ("response_chars", entry.get("response_chars")),
                        ("quality_issues", entry.get("quality_issues")),
                    ]
                ),
                "",
                excerpt(str(entry.get("content", "")), limit=max_chars, include_full=include_full),
                "",
            ]
        )

    lines.extend(["## Codex Reviews", ""])
    if not reflections:
        lines.append("_No Codex review/reflection entries found._")
    for index, entry in enumerate(reflections, 1):
        lines.extend(
            [
                f"### Review {index}: {entry.get('review_status', entry.get('status', 'recorded'))}",
                "",
                *format_metadata(
                    [
                        ("timestamp", entry.get("timestamp")),
                        ("reviewer", entry.get("reviewer")),
                        ("workflow_id", entry.get("workflow_id")),
                        ("task_id", entry.get("task_id")),
                        ("issues", entry.get("issues")),
                        ("finish_reason", entry.get("finish_reason")),
                    ]
                ),
                "",
                excerpt(str(entry.get("lesson", "")), limit=max_chars, include_full=include_full),
                "",
            ]
        )

    lines.extend(["## Durable Memory", ""])
    if not memory:
        lines.append("_No durable memory entries found._")
    for index, entry in enumerate(memory, 1):
        lines.extend(
            [
                f"### Memory {index}: {entry.get('review_status', entry.get('role', 'note'))}",
                "",
                *format_metadata(
                    [
                        ("timestamp", entry.get("timestamp")),
                        ("role", entry.get("role")),
                        ("workflow_id", entry.get("workflow_id")),
                        ("task_id", entry.get("task_id")),
                    ]
                ),
                "",
                excerpt(str(entry.get("content", "")), limit=max_chars, include_full=include_full),
                "",
            ]
        )

    call_events = [event for event in events if event.get("event") == "call"]
    lines.extend(["## Usage Events", ""])
    if not call_events:
        lines.append("_No call events found._")
    for index, event in enumerate(call_events, 1):
        log_entry = event.get("log_entry") if isinstance(event.get("log_entry"), dict) else {}
        lines.extend(
            [
                f"### Call {index}",
                "",
                *format_metadata(
                    [
                        ("timestamp", event.get("timestamp")),
                        ("workflow_id", event.get("workflow_id")),
                        ("task_id", event.get("task_id")),
                        ("usage", event.get("usage")),
                        ("quality_issues", event.get("quality_issues")),
                        ("estimated_codex_tokens_saved", log_entry.get("estimated_codex_tokens_saved")),
                    ]
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_room(room_root: Path, *, max_chars: int, include_full: bool) -> str:
    state = read_json(room_root / "state.json") or {}
    messages = read_jsonl(room_root / "messages.jsonl")
    events = read_jsonl(room_root / "events.jsonl")
    room_id = str(state.get("room_id") or room_root.name)

    lines = [
        f"# Agent Room Transcript - {room_id}",
        "",
        "## Source",
        "",
        f"- Room root: `{room_root}`",
        f"- State: `{room_root / 'state.json'}`",
        f"- Messages: `{room_root / 'messages.jsonl'}`",
        f"- Events: `{room_root / 'events.jsonl'}`",
        "",
        "## State",
        "",
        *(
            format_metadata(
                [
                    ("room_id", state.get("room_id")),
                    ("title", state.get("title")),
                    ("status", state.get("status")),
                    ("round", state.get("round")),
                    ("created_at", state.get("created_at")),
                    ("updated_at", state.get("updated_at")),
                    ("latest_artifact_path", state.get("latest_artifact_path")),
                    ("agents", state.get("agents")),
                ]
            )
            or ["- No state metadata found."]
        ),
        "",
        "## Messages",
        "",
    ]
    if not messages:
        lines.append("_No room messages found._")
    for message in messages:
        title = (
            f"{message.get('id', 'msg')} "
            f"{message.get('role', 'role')} "
            f"{message.get('agent_id', 'agent')} / "
            f"{message.get('type', 'message')}"
        )
        lines.extend(
            [
                f"### {title}",
                "",
                *format_metadata(
                    [
                        ("timestamp", message.get("timestamp")),
                        ("metadata", message.get("metadata")),
                    ]
                ),
                "",
                excerpt(str(message.get("content", "")), limit=max_chars, include_full=include_full),
                "",
            ]
        )

    lines.extend(["## Events", ""])
    if not events:
        lines.append("_No room events found._")
    for index, event in enumerate(events, 1):
        lines.extend(
            [
                f"### Event {index}: {event.get('event', 'recorded')}",
                "",
                *format_metadata(
                    [
                        ("timestamp", event.get("timestamp")),
                        ("returncode", event.get("returncode")),
                        ("decision", event.get("decision")),
                    ]
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_listing(agent_home: Path, room_home: Path) -> str:
    agents = discover_agents(agent_home)
    rooms = discover_rooms(room_home)
    lines = ["# DeepSeek Transcript Sources", "", "## Agents", ""]
    if not agents:
        lines.append("- None")
    for root in agents:
        marker = root / "transcript.jsonl"
        modified = dt.datetime.fromtimestamp(marker.stat().st_mtime).isoformat(timespec="seconds")
        lines.append(f"- `{root.name}` modified `{modified}` path `{root}`")
    lines.extend(["", "## Rooms", ""])
    if not rooms:
        lines.append("- None")
    for root in rooms:
        marker = root / "messages.jsonl"
        modified = dt.datetime.fromtimestamp(marker.stat().st_mtime).isoformat(timespec="seconds")
        lines.append(f"- `{root.name}` modified `{modified}` path `{root}`")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export DeepSeek worker or Agent Room transcripts as readable Markdown.",
    )
    parser.add_argument("--agent-id", help="Export this persistent worker agent.")
    parser.add_argument("--room-id", help="Export this Agent Room.")
    parser.add_argument("--agent-home", default=os.environ.get("DEEPSEEK_AGENT_HOME", str(DEFAULT_AGENT_HOME)))
    parser.add_argument("--room-home", default=os.environ.get("DEEPSEEK_ROOM_HOME", str(DEFAULT_ROOM_HOME)))
    parser.add_argument("--out", help="Write Markdown to this path instead of stdout.")
    parser.add_argument("--max-chars", type=int, default=1400, help="Max visible chars per message excerpt.")
    parser.add_argument("--include-full", action="store_true", help="Do not truncate message content.")
    parser.add_argument("--latest", action="store_true", help="Export the latest room or agent transcript.")
    parser.add_argument("--all", action="store_true", help="Export every discovered room and agent transcript.")
    parser.add_argument("--list", action="store_true", help="List available rooms and agents.")
    return parser.parse_args()


def select_exports(args: argparse.Namespace, agent_home: Path, room_home: Path) -> list[tuple[str, Path]]:
    if args.agent_id and args.room_id:
        raise ValueError("Use either --agent-id or --room-id, not both.")
    if args.agent_id:
        root = agent_home / slugify(args.agent_id)
        if not (root / "transcript.jsonl").exists():
            raise ValueError(f"Agent transcript not found: {root / 'transcript.jsonl'}")
        return [("agent", root)]
    if args.room_id:
        root = room_home / slugify(args.room_id)
        if not (root / "messages.jsonl").exists():
            raise ValueError(f"Room transcript not found: {root / 'messages.jsonl'}")
        return [("room", root)]

    agents = discover_agents(agent_home)
    rooms = discover_rooms(room_home)
    if args.all:
        return [("room", root) for root in rooms] + [("agent", root) for root in agents]
    if args.latest:
        latest_room = latest_path(rooms, "messages.jsonl")
        latest_agent = latest_path(agents, "transcript.jsonl")
        candidates: list[tuple[str, Path, float]] = []
        if latest_room:
            candidates.append(("room", latest_room, (latest_room / "messages.jsonl").stat().st_mtime))
        if latest_agent:
            candidates.append(("agent", latest_agent, (latest_agent / "transcript.jsonl").stat().st_mtime))
        if not candidates:
            raise ValueError("No room or agent transcripts found.")
        source_type, root, _ = max(candidates, key=lambda item: item[2])
        return [(source_type, root)]
    all_sources = [("room", root) for root in rooms] + [("agent", root) for root in agents]
    if len(all_sources) == 1:
        return all_sources
    if not all_sources:
        raise ValueError("No room or agent transcripts found.")
    raise ValueError("Multiple transcripts found. Use --list, --latest, --all, --agent-id, or --room-id.")


def main() -> int:
    args = parse_args()
    agent_home = Path(args.agent_home).expanduser()
    room_home = Path(args.room_home).expanduser()

    if args.list:
        output = render_listing(agent_home, room_home)
    else:
        try:
            exports = select_exports(args, agent_home, room_home)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        docs: list[str] = []
        for source_type, root in exports:
            if source_type == "room":
                docs.append(render_room(root, max_chars=args.max_chars, include_full=args.include_full))
            else:
                docs.append(render_agent(root, max_chars=args.max_chars, include_full=args.include_full))
        output = "\n\n---\n\n".join(doc.rstrip() for doc in docs) + "\n"

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(str(out_path))
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
