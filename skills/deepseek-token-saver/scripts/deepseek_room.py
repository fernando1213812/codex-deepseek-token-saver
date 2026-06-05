#!/usr/bin/env python3
"""Agent Room orchestration for DeepSeek writer + Codex reviewer loops.

The room is intentionally small and file-backed. It gives several agents a
shared transcript, stores candidate artifacts, and turns reviewer rejection into
the next DeepSeek writer prompt. The expensive model still owns review/final
authority; DeepSeek owns draft generation.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEEPSEEK_AGENT_SCRIPT = SCRIPT_DIR / "deepseek_agent.py"
DEFAULT_ROOM_HOME = Path.cwd() / ".deepseek-token-saver" / "rooms"
DEFAULT_AGENT_HOME = Path.cwd() / ".deepseek-token-saver" / "agents"
DEFAULT_WRITER_ID = "codex-deepseek-room-writer"
DEFAULT_REVIEWER_ID = "codex-gpt-5.5-reviewer"
REJECT_STATUSES = {"rejected", "needs-rework"}


@dataclasses.dataclass(frozen=True)
class RoomPaths:
    root: Path
    state: Path
    messages: Path
    artifacts: Path
    events: Path


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    slug = re.sub(r"\.{2,}", "-", slug)
    slug = slug.strip("-._")
    return slug[:80] or "agent-room"


def room_paths(room_home: str | Path, room_id: str) -> RoomPaths:
    root = Path(room_home).expanduser() / slugify(room_id)
    return RoomPaths(
        root=root,
        state=root / "state.json",
        messages=root / "messages.jsonl",
        artifacts=root / "artifacts",
        events=root / "events.jsonl",
    )


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


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


def ensure_room(paths: RoomPaths, room_id: str, title: str | None = None) -> dict[str, Any]:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.artifacts.mkdir(parents=True, exist_ok=True)
    state = read_json(paths.state)
    if state is None:
        state = {
            "schema_version": 1,
            "room_id": slugify(room_id),
            "title": title or slugify(room_id),
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "status": "open",
            "round": 0,
            "agents": {
                "writer": DEFAULT_WRITER_ID,
                "reviewer": DEFAULT_REVIEWER_ID,
            },
            "latest_task_message_id": None,
            "latest_writer_message_id": None,
            "latest_review_message_id": None,
            "accepted_message_id": None,
            "latest_artifact_path": None,
        }
    if title:
        state["title"] = title
    state["updated_at"] = utc_now()
    write_json(paths.state, state)
    return state


def update_state(paths: RoomPaths, updates: dict[str, Any]) -> dict[str, Any]:
    state = read_json(paths.state) or {}
    state.update(updates)
    state["updated_at"] = utc_now()
    write_json(paths.state, state)
    return state


def next_message_id(paths: RoomPaths) -> str:
    return f"msg-{len(read_jsonl(paths.messages)) + 1:04d}"


def append_message(
    paths: RoomPaths,
    *,
    role: str,
    agent_id: str,
    message_type: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = {
        "id": next_message_id(paths),
        "timestamp": utc_now(),
        "role": role,
        "agent_id": agent_id,
        "type": message_type,
        "content": content,
        "metadata": metadata or {},
    }
    append_jsonl(paths.messages, message)
    return message


def read_cli_content(content: str | None, content_file: str | None = None) -> str:
    if content_file:
        return Path(content_file).expanduser().read_text(encoding="utf-8").strip()
    if content is not None:
        return content.strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 80)].rstrip() + "\n\n[...truncated for room context...]\n"


def latest_message(messages: list[dict[str, Any]], *, role: str | None = None, message_type: str | None = None) -> dict[str, Any] | None:
    for message in reversed(messages):
        if role and message.get("role") != role:
            continue
        if message_type and message.get("type") != message_type:
            continue
        return message
    return None


def latest_rejected_review(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "reviewer":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if metadata.get("review_status") in REJECT_STATUSES:
            return message
    return None


def build_room_context(messages: list[dict[str, Any]], max_context_chars: int) -> str:
    rendered: list[str] = []
    used = 0
    for message in reversed(messages):
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        block = (
            f"[{message.get('id')}] {message.get('role')} "
            f"{message.get('agent_id')} / {message.get('type')}\n"
            f"{content}\n"
        )
        if used + len(block) > max_context_chars and rendered:
            break
        rendered.append(block)
        used += len(block)
    return "\n".join(reversed(rendered)) or "No prior room messages."


def build_writer_prompt(
    *,
    room_id: str,
    prompt: str,
    messages: list[dict[str, Any]],
    max_context_chars: int,
) -> str:
    task_message = latest_message(messages, message_type="task")
    original_task = str(task_message.get("content", "")).strip() if task_message else ""
    latest_candidate = latest_message(messages, role="writer", message_type="candidate")
    rejected_review = latest_rejected_review(messages)

    task_block = prompt.strip() or original_task
    review_block = "No reviewer rejection yet."
    retry_rule = "This is a first-pass draft."
    if rejected_review:
        retry_rule = (
            "This is a rework round. Reviewer feedback overrides any earlier "
            "instruction that made the candidate intentionally incomplete."
        )
        review_block = str(rejected_review.get("content", "")).strip()
        if latest_candidate:
            review_block += "\n\nPrevious candidate excerpt:\n" + truncate(str(latest_candidate.get("content", "")), 1800)

    return textwrap.dedent(
        f"""
        You are the low-cost writer agent inside Codex Agent Room `{room_id}`.
        Produce the main candidate work. Codex/GPT reviewer will audit it.

        Rules:
        - Return concrete, usable output, not a plan unless the task asks for a plan.
        - If reviewer feedback exists, fix every named issue directly.
        - {retry_rule}
        - Do not claim the work is final or reviewed.
        - Keep secrets out of output and memory.

        Current task:
        {task_block}

        Latest reviewer feedback:
        {review_block}

        Recent room transcript:
        {build_room_context(messages, max_context_chars)}
        """
    ).strip()


def run_deepseek_writer(args: argparse.Namespace, paths: RoomPaths, state: dict[str, Any], prompt: str) -> tuple[int, dict[str, Any] | None, str, str]:
    next_round = int(state.get("round") or 0) + 1
    task_id = args.task_id or f"round-{next_round:02d}"
    artifact_path = Path(args.out).expanduser() if args.out else paths.artifacts / f"{task_id}.md"
    command = [
        sys.executable,
        str(DEEPSEEK_AGENT_SCRIPT),
        "--agent-id",
        args.writer_id,
        "--agent-role",
        "room-writer",
        "--agent-purpose",
        f"Low-cost writer inside Agent Room {state.get('room_id')}",
        "--parent-agent-id",
        args.reviewer_id,
        "--workflow-id",
        str(state.get("room_id") or args.room_id),
        "--task-id",
        task_id,
        "--agent-home",
        str(Path(args.agent_home).expanduser()),
        "--phase",
        args.phase,
        "--max-tokens",
        str(args.max_tokens),
        "--temperature",
        str(args.temperature),
        "--min-response-chars",
        str(args.min_response_chars),
        "--log-file",
        str(Path(args.log_file).expanduser()),
        "--out",
        str(artifact_path),
        "--json",
    ]
    for section in args.require_section:
        command.extend(["--require-section", section])
    for pattern in args.require_regex:
        command.extend(["--require-regex", pattern])
    if args.expect_json:
        command.append("--expect-json")
    if args.force_deepseek:
        command.append("--force-deepseek")
    if args.thinking != "auto":
        command.extend(["--thinking", args.thinking])
    if args.no_keychain:
        command.append("--no-keychain")
    command.append(prompt)

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    envelope: dict[str, Any] | None = None
    if result.stdout.strip():
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            envelope = None
    return result.returncode, envelope, result.stdout, result.stderr


def command_init(args: argparse.Namespace) -> int:
    paths = room_paths(args.room_home, args.room_id)
    state = ensure_room(paths, args.room_id, args.title)
    if args.json:
        print(json.dumps({"room": state, "path": str(paths.root)}, ensure_ascii=False, indent=2))
    else:
        print(f"Room: {state['room_id']}")
        print(f"Path: {paths.root}")
    return 0


def command_post(args: argparse.Namespace) -> int:
    paths = room_paths(args.room_home, args.room_id)
    state = ensure_room(paths, args.room_id, args.title)
    content = read_cli_content(args.content, args.content_file)
    if not content:
        print("No content provided.", file=sys.stderr)
        return 1
    message = append_message(
        paths,
        role=args.role,
        agent_id=args.agent_id,
        message_type=args.message_type,
        content=content,
        metadata={"manual": True},
    )
    updates: dict[str, Any] = {"status": state.get("status", "open")}
    if args.message_type == "task":
        updates["latest_task_message_id"] = message["id"]
        updates["status"] = "open"
    update_state(paths, updates)
    print(json.dumps({"message": message, "room_path": str(paths.root)}, ensure_ascii=False, indent=2) if args.json else message["id"])
    return 0


def command_writer(args: argparse.Namespace) -> int:
    paths = room_paths(args.room_home, args.room_id)
    state = ensure_room(paths, args.room_id, args.title)
    messages = read_jsonl(paths.messages)
    user_prompt = read_cli_content(args.prompt, args.prompt_file)
    if user_prompt:
        task_message = append_message(
            paths,
            role="user",
            agent_id=args.requester_id,
            message_type="task",
            content=user_prompt,
            metadata={"writer_round_request": True},
        )
        state = update_state(paths, {"latest_task_message_id": task_message["id"], "status": "open"})
        messages = read_jsonl(paths.messages)
    if not messages:
        print("No room task found. Pass --prompt or post a task first.", file=sys.stderr)
        return 1

    writer_prompt = build_writer_prompt(
        room_id=str(state.get("room_id") or args.room_id),
        prompt=user_prompt,
        messages=messages,
        max_context_chars=args.max_context_chars,
    )
    returncode, envelope, stdout, stderr = run_deepseek_writer(args, paths, state, writer_prompt)
    if returncode != 0 or envelope is None:
        append_jsonl(
            paths.events,
            {
                "timestamp": utc_now(),
                "event": "writer_failed",
                "returncode": returncode,
                "stdout": truncate(stdout, 2000),
                "stderr": truncate(stderr, 2000),
            },
        )
        update_state(paths, {"status": "writer-failed"})
        if stderr:
            print(stderr.strip(), file=sys.stderr)
        elif stdout:
            print(stdout.strip(), file=sys.stderr)
        else:
            print("DeepSeek writer failed without output.", file=sys.stderr)
        return returncode or 2

    response = str(envelope.get("response", "")).strip()
    decision = envelope.get("decision") if isinstance(envelope.get("decision"), dict) else {}
    if not response:
        route = decision.get("route")
        event = "writer_routed_away" if route == "gpt-5.5" else "writer_empty_response"
        append_jsonl(
            paths.events,
            {
                "timestamp": utc_now(),
                "event": event,
                "decision": decision,
                "envelope": {key: envelope.get(key) for key in ("agent_id", "workflow_id", "task_id")},
            },
        )
        update_state(paths, {"status": "writer-routed-away" if route == "gpt-5.5" else "writer-failed"})
        if route == "gpt-5.5":
            print(
                "DeepSeek writer routed away to GPT-5.5. Re-run with --force-deepseek "
                "when this is a low-risk draft room.",
                file=sys.stderr,
            )
            return 3
        print("DeepSeek writer returned an empty response.", file=sys.stderr)
        return 4
    task_id = str(envelope.get("task_id") or args.task_id or f"round-{int(state.get('round') or 0) + 1:02d}")
    artifact_path = Path(args.out).expanduser() if args.out else paths.artifacts / f"{task_id}.md"
    if artifact_path.exists() and not response:
        response = artifact_path.read_text(encoding="utf-8").strip()
    message = append_message(
        paths,
        role="writer",
        agent_id=str(envelope.get("agent_id") or args.writer_id),
        message_type="candidate",
        content=response,
        metadata={
            "artifact_path": str(artifact_path),
            "usage": envelope.get("usage", {}),
            "estimated_codex_tokens_saved": envelope.get("estimated_codex_tokens_saved", 0),
            "finish_reason": envelope.get("finish_reason"),
            "reasoning_chars": envelope.get("reasoning_chars", 0),
            "quality_issues": envelope.get("quality_issues", []),
            "task_id": task_id,
        },
    )
    state = update_state(
        paths,
        {
            "status": "needs-review",
            "round": int(state.get("round") or 0) + 1,
            "agents": {"writer": args.writer_id, "reviewer": args.reviewer_id},
            "latest_writer_message_id": message["id"],
            "latest_artifact_path": str(artifact_path),
        },
    )
    output = {"room": state, "message": message, "envelope": envelope, "room_path": str(paths.root)}
    print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else str(artifact_path))
    return 0


def command_review(args: argparse.Namespace) -> int:
    paths = room_paths(args.room_home, args.room_id)
    state = ensure_room(paths, args.room_id, args.title)
    feedback = read_cli_content(args.feedback, args.feedback_file)
    if not feedback:
        print("No review feedback provided.", file=sys.stderr)
        return 1
    message = append_message(
        paths,
        role="reviewer",
        agent_id=args.reviewer_id,
        message_type="review",
        content=feedback,
        metadata={
            "review_status": args.status,
            "reviewer_model": args.reviewer_model,
            "reviewed_writer_message_id": state.get("latest_writer_message_id"),
        },
    )
    updates: dict[str, Any] = {
        "latest_review_message_id": message["id"],
        "status": "accepted" if args.status == "accepted" else "needs-rework",
    }
    if args.status == "accepted":
        updates["accepted_message_id"] = state.get("latest_writer_message_id")
    state = update_state(paths, updates)

    if args.record_to_writer_memory:
        record_writer_review(args, paths, state, feedback)

    print(json.dumps({"room": state, "message": message, "room_path": str(paths.root)}, ensure_ascii=False, indent=2) if args.json else state["status"])
    return 0


def record_writer_review(args: argparse.Namespace, paths: RoomPaths, state: dict[str, Any], feedback: str) -> None:
    status = "accepted" if args.status == "accepted" else "needs-rework"
    command = [
        sys.executable,
        str(DEEPSEEK_AGENT_SCRIPT),
        "--agent-id",
        args.writer_id,
        "--agent-home",
        str(Path(args.agent_home).expanduser()),
        "--workflow-id",
        str(state.get("room_id") or args.room_id),
        "--task-id",
        str(state.get("latest_writer_message_id") or "review"),
        "--parent-agent-id",
        args.reviewer_id,
        "--record-review",
        "--review-status",
        status,
        "--reflection",
        feedback,
    ]
    if args.remember and status == "accepted":
        command.extend(["--remember", args.remember])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    append_jsonl(
        paths.events,
        {
            "timestamp": utc_now(),
            "event": "record_writer_review",
            "returncode": result.returncode,
            "stdout": truncate(result.stdout, 2000),
            "stderr": truncate(result.stderr, 2000),
        },
    )


def command_retry_prompt(args: argparse.Namespace) -> int:
    paths = room_paths(args.room_home, args.room_id)
    state = ensure_room(paths, args.room_id, args.title)
    messages = read_jsonl(paths.messages)
    if not latest_rejected_review(messages):
        print("No rejected review found; the room is not waiting for rework.", file=sys.stderr)
        return 1
    prompt = build_writer_prompt(
        room_id=str(state.get("room_id") or args.room_id),
        prompt="",
        messages=messages,
        max_context_chars=args.max_context_chars,
    )
    print(prompt)
    return 0


def command_show(args: argparse.Namespace) -> int:
    paths = room_paths(args.room_home, args.room_id)
    state = ensure_room(paths, args.room_id, args.title)
    messages = read_jsonl(paths.messages)
    payload = {
        "room": state,
        "room_path": str(paths.root),
        "messages": messages[-args.limit :],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Room {state.get('room_id')} [{state.get('status')}] round={state.get('round')} path={paths.root}")
    for message in payload["messages"]:
        content = str(message.get("content", "")).replace("\n", " ")
        print(
            f"{message.get('id')} {message.get('role')} "
            f"{message.get('agent_id')} {message.get('type')}: {truncate(content, 180)}"
        )
    return 0


def add_common_room_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--room-home", default=os.environ.get("DEEPSEEK_ROOM_HOME", str(DEFAULT_ROOM_HOME)))
    parser.add_argument("--title")
    parser.add_argument("--json", action="store_true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a file-backed DeepSeek/Codex Agent Room.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create or show an agent room.")
    add_common_room_args(init_parser)
    init_parser.set_defaults(func=command_init)

    post_parser = subparsers.add_parser("post", help="Post a manual message into the room.")
    add_common_room_args(post_parser)
    post_parser.add_argument("--role", choices=("user", "writer", "reviewer", "system"), default="user")
    post_parser.add_argument("--agent-id", default="human")
    post_parser.add_argument("--message-type", default="task")
    post_parser.add_argument("--content")
    post_parser.add_argument("--content-file")
    post_parser.set_defaults(func=command_post)

    writer_parser = subparsers.add_parser("writer", help="Ask the DeepSeek writer to produce/rewrite a candidate.")
    add_common_room_args(writer_parser)
    writer_parser.add_argument("--writer-id", default=DEFAULT_WRITER_ID)
    writer_parser.add_argument("--reviewer-id", default=DEFAULT_REVIEWER_ID)
    writer_parser.add_argument("--requester-id", default="room-user")
    writer_parser.add_argument("--agent-home", default=os.environ.get("DEEPSEEK_AGENT_HOME", str(DEFAULT_AGENT_HOME)))
    writer_parser.add_argument("--task-id")
    writer_parser.add_argument("--prompt")
    writer_parser.add_argument("--prompt-file")
    writer_parser.add_argument("--out")
    writer_parser.add_argument("--phase", choices=("auto", "brainstorm", "draft", "batch", "implement", "review", "final"), default="implement")
    writer_parser.add_argument("--max-tokens", type=int, default=2200)
    writer_parser.add_argument("--temperature", type=float, default=0.2)
    writer_parser.add_argument("--min-response-chars", type=int, default=300)
    writer_parser.add_argument("--max-context-chars", type=int, default=8000)
    writer_parser.add_argument("--require-section", action="append", default=[])
    writer_parser.add_argument("--require-regex", action="append", default=[])
    writer_parser.add_argument("--expect-json", action="store_true")
    writer_parser.add_argument("--thinking", choices=("auto", "enabled"), default="auto")
    writer_parser.add_argument("--force-deepseek", action="store_true")
    writer_parser.add_argument("--no-keychain", action="store_true")
    writer_parser.add_argument("--log-file", default=os.environ.get("DEEPSEEK_DELEGATE_LOG", str(Path.cwd() / ".deepseek-token-saver" / "calls.jsonl")))
    writer_parser.set_defaults(func=command_writer)

    review_parser = subparsers.add_parser("review", help="Record Codex reviewer feedback and accept/reject the latest candidate.")
    add_common_room_args(review_parser)
    review_parser.add_argument("--reviewer-id", default=DEFAULT_REVIEWER_ID)
    review_parser.add_argument("--writer-id", default=DEFAULT_WRITER_ID)
    review_parser.add_argument("--agent-home", default=os.environ.get("DEEPSEEK_AGENT_HOME", str(DEFAULT_AGENT_HOME)))
    review_parser.add_argument("--status", choices=("accepted", "rejected", "needs-rework"), required=True)
    review_parser.add_argument("--feedback")
    review_parser.add_argument("--feedback-file")
    review_parser.add_argument("--reviewer-model", default="gpt-5.5")
    review_parser.add_argument("--record-to-writer-memory", action="store_true")
    review_parser.add_argument("--remember")
    review_parser.set_defaults(func=command_review)

    retry_parser = subparsers.add_parser("retry-prompt", help="Print the prompt that will be sent to DeepSeek after a rejection.")
    add_common_room_args(retry_parser)
    retry_parser.add_argument("--max-context-chars", type=int, default=8000)
    retry_parser.set_defaults(func=command_retry_prompt)

    show_parser = subparsers.add_parser("show", help="Show room state and recent messages.")
    add_common_room_args(show_parser)
    show_parser.add_argument("--limit", type=int, default=8)
    show_parser.set_defaults(func=command_show)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
