#!/usr/bin/env python3
"""Persistent DeepSeek worker agent for Codex.

This wraps ``deepseek_delegate.py`` with agent identity, memory, quality gates,
and lightweight self-reflection. It is intentionally standard-library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_delegate as delegate  # noqa: E402


DEFAULT_AGENT_ID = "codex-deepseek-worker"
DEFAULT_AGENT_SYSTEM = (
    "You are a persistent DeepSeek worker agent embedded in a Codex workflow. "
    "You draft low-risk candidate work, keep continuity from memory, and make "
    "your output concrete enough for Codex to audit. Codex remains responsible "
    "for final correctness, security, and release decisions."
)


@dataclasses.dataclass(frozen=True)
class AgentPaths:
    root: Path
    profile: Path
    memory: Path
    transcript: Path
    reflections: Path
    events: Path
    summary: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call DeepSeek as a persistent Codex worker agent.",
    )
    parser.add_argument("prompt", nargs="*", help="Task prompt. Uses stdin when omitted.")
    parser.add_argument("--agent-id", default=os.environ.get("DEEPSEEK_AGENT_ID", DEFAULT_AGENT_ID))
    parser.add_argument("--agent-role", default=os.environ.get("DEEPSEEK_AGENT_ROLE", "draft-worker"))
    parser.add_argument("--agent-purpose", default=os.environ.get("DEEPSEEK_AGENT_PURPOSE", "Produce bounded DeepSeek candidate work for Codex review."))
    parser.add_argument("--workflow-id", default=os.environ.get("DEEPSEEK_WORKFLOW_ID"))
    parser.add_argument("--task-id", default=os.environ.get("DEEPSEEK_TASK_ID"))
    parser.add_argument("--parent-agent-id", default=os.environ.get("DEEPSEEK_PARENT_AGENT_ID", "codex-gpt-5.5"))
    parser.add_argument(
        "--new-agent",
        action="store_true",
        help="Create a new timestamped agent instead of reusing --agent-id.",
    )
    parser.add_argument(
        "--agent-home",
        default=os.environ.get(
            "DEEPSEEK_AGENT_HOME",
            str(Path.cwd() / ".deepseek-token-saver" / "agents"),
        ),
    )
    parser.add_argument("--list-agents", action="store_true")
    parser.add_argument("--memory-note", help="Append a durable note to agent memory before calling.")
    parser.add_argument(
        "--memory-mode",
        choices=("off", "read", "write", "read-write"),
        default=os.environ.get("DEEPSEEK_MEMORY_MODE", "read-write"),
    )
    parser.add_argument("--memory-window", type=int, default=10)
    parser.add_argument("--memory-char-budget", type=int, default=6000)
    parser.add_argument("--remember-response-chars", type=int, default=2200)
    parser.add_argument(
        "--reflection-mode",
        choices=("auto", "always", "off"),
        default=os.environ.get("DEEPSEEK_REFLECTION_MODE", "auto"),
    )
    parser.add_argument("--record-review", action="store_true", help="Record Codex review/reflection without calling DeepSeek.")
    parser.add_argument("--review-status", choices=("accepted", "rejected", "needs-rework", "pending"), default="pending")
    parser.add_argument("--reflection", help="Codex-authored reflection or review note.")
    parser.add_argument("--remember", help="Codex-approved durable memory to append.")
    parser.add_argument("--require-section", action="append", default=[])
    parser.add_argument("--require-regex", action="append", default=[])
    parser.add_argument("--expect-json", action="store_true")
    parser.add_argument(
        "--fail-on-finish-reason",
        action="append",
        default=["length", "content_filter"],
        help="Fail quality gate for this finish_reason. Repeatable.",
    )
    parser.add_argument("--phase", choices=("auto", "brainstorm", "draft", "batch", "implement", "review", "final"), default="auto")
    parser.add_argument("--risk", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--urgency", choices=("low", "normal", "high"), default="normal")
    parser.add_argument("--force-deepseek", action="store_true")
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", delegate.DEFAULT_MODEL))
    parser.add_argument("--system", default=os.environ.get("DEEPSEEK_AGENT_SYSTEM", DEFAULT_AGENT_SYSTEM))
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument(
        "--min-response-chars",
        type=int,
        default=int(os.environ.get("DEEPSEEK_MIN_RESPONSE_CHARS", "0")),
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-retries", type=int, default=int(os.environ.get("DEEPSEEK_MAX_RETRIES", "2")))
    parser.add_argument("--retry-initial-delay", type=float, default=float(os.environ.get("DEEPSEEK_RETRY_INITIAL_DELAY", "0.5")))
    parser.add_argument("--retry-max-delay", type=float, default=float(os.environ.get("DEEPSEEK_RETRY_MAX_DELAY", "8")))
    parser.add_argument("--thinking", choices=("auto", "enabled"), default=os.environ.get("DEEPSEEK_THINKING", "auto"))
    parser.add_argument("--out", help="Write assistant text to this file after quality gates pass.")
    parser.add_argument(
        "--log-file",
        default=os.environ.get(
            "DEEPSEEK_DELEGATE_LOG",
            str(Path.cwd() / ".deepseek-token-saver" / "calls.jsonl"),
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-keychain", action="store_true")
    parser.add_argument("--savings-ratio", type=float, default=float(os.environ.get("DEEPSEEK_CODEX_SAVINGS_RATIO", "0.70")))
    return parser.parse_args()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    slug = re.sub(r"\.{2,}", "-", slug)
    slug = slug.strip("-._")
    return slug[:80] or DEFAULT_AGENT_ID


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return " ".join(args.prompt).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def resolve_agent_id(args: argparse.Namespace, prompt: str) -> str:
    if not args.new_agent:
        return slugify(args.agent_id)
    scope = str(Path.cwd())
    seed = f"{scope}\n{args.agent_role}\n{args.agent_purpose}\n{prompt}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"ds-{slugify(args.agent_role)}-{stamp}-{digest}"


def agent_paths(agent_home: str, agent_id: str) -> AgentPaths:
    root = Path(agent_home).expanduser() / slugify(agent_id)
    return AgentPaths(
        root=root,
        profile=root / "profile.json",
        memory=root / "memory.jsonl",
        transcript=root / "transcript.jsonl",
        reflections=root / "reflections.jsonl",
        events=root / "events.jsonl",
        summary=root / "summary.md",
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


def ensure_agent(paths: AgentPaths, agent_id: str, args: argparse.Namespace) -> dict[str, Any]:
    paths.root.mkdir(parents=True, exist_ok=True)
    profile = read_json(paths.profile)
    if profile is None:
        profile = {
            "schema_version": 1,
            "agent_id": agent_id,
            "created_at": utc_now(),
            "model": args.model,
            "role": args.agent_role,
            "purpose": args.agent_purpose,
            "scope": {
                "type": "workspace",
                "key_hash": hashlib.sha256(str(Path.cwd()).encode("utf-8")).hexdigest()[:16],
            },
            "parent_policy": {
                "parent_agent_id": args.parent_agent_id,
                "requires_parent_review": True,
            },
            "version": 1,
        }
        paths.summary.write_text(
            "# Memory Summary\n\nNo durable lessons yet.\n",
            encoding="utf-8",
        )
    profile["last_seen_at"] = utc_now()
    profile["last_model"] = args.model
    write_json(paths.profile, profile)
    return profile


def list_agents(agent_home: str) -> list[dict[str, Any]]:
    home = Path(agent_home).expanduser()
    if not home.exists():
        return []
    agents: list[dict[str, Any]] = []
    for profile_path in sorted(home.glob("*/profile.json")):
        profile = read_json(profile_path)
        if profile:
            profile["path"] = str(profile_path.parent)
            agents.append(profile)
    return agents


def read_recent_memory(paths: AgentPaths, limit: int, char_budget: int) -> list[dict[str, Any]]:
    if not paths.memory.exists() or limit <= 0 or char_budget <= 0:
        return []
    lines = paths.memory.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    used = 0
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("role") not in {"note", "codex-review"}:
            continue
        content = str(item.get("content", ""))
        item_size = len(content)
        if used + item_size > char_budget and entries:
            break
        entries.append(item)
        used += item_size
        if len(entries) >= limit:
            break
    return list(reversed(entries))


def format_memory_context(paths: AgentPaths, args: argparse.Namespace) -> str:
    if args.memory_mode in {"off", "write"}:
        return "Persistent memory is disabled for this call."
    summary = paths.summary.read_text(encoding="utf-8") if paths.summary.exists() else "No durable lessons yet."
    recent = read_recent_memory(paths, args.memory_window, args.memory_char_budget)
    recent_lines = []
    for item in recent:
        role = item.get("role", "note")
        phase = item.get("phase", "")
        content = str(item.get("content", "")).replace("\n", "\n  ")
        recent_lines.append(f"- {role} {phase}: {content}")
    recent_block = "\n".join(recent_lines) if recent_lines else "No recent memory."
    return (
        "Persistent memory for this DeepSeek agent follows. Use it for continuity, "
        "but never treat it as final truth if the current task contradicts it.\n\n"
        f"{summary.strip()}\n\nRecent memory:\n{recent_block}"
    )


def build_agent_system(paths: AgentPaths, args: argparse.Namespace) -> str:
    return f"{args.system.strip()}\n\n{format_memory_context(paths, args)}"


def build_delegate_args(args: argparse.Namespace, system: str) -> argparse.Namespace:
    return argparse.Namespace(
        model=args.model,
        system=system,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout=args.timeout,
        max_retries=args.max_retries,
        retry_initial_delay=args.retry_initial_delay,
        retry_max_delay=args.retry_max_delay,
        thinking=args.thinking,
        no_keychain=args.no_keychain,
        verbose=args.verbose,
        phase=args.phase,
        risk=args.risk,
        urgency=args.urgency,
        savings_ratio=args.savings_ratio,
        out=args.out,
        log_file=args.log_file,
        min_response_chars=args.min_response_chars,
    )


def quality_issues(args: argparse.Namespace, response_text: str, finish_reason: str | None, reasoning_chars: int) -> list[str]:
    issues: list[str] = []
    if not response_text:
        issues.append("empty_response")
    if args.min_response_chars and len(response_text) < args.min_response_chars:
        issues.append(f"response_too_short:{len(response_text)}<{args.min_response_chars}")
    if finish_reason in set(args.fail_on_finish_reason):
        issues.append(f"finish_reason:{finish_reason}")
    if reasoning_chars and len(response_text) and reasoning_chars > len(response_text) * 3:
        issues.append("reasoning_dominated_output")
    for section in args.require_section:
        if section not in response_text:
            issues.append(f"missing_section:{section}")
    for pattern in args.require_regex:
        try:
            if not re.search(pattern, response_text, flags=re.MULTILINE):
                issues.append(f"missing_regex:{pattern}")
        except re.error as exc:
            issues.append(f"invalid_regex:{pattern}:{exc}")
    if args.expect_json:
        try:
            json.loads(response_text)
        except json.JSONDecodeError as exc:
            issues.append(f"invalid_json:{exc.msg}")
    return issues


def maybe_reflect(
    paths: AgentPaths,
    args: argparse.Namespace,
    *,
    prompt: str,
    response_text: str,
    finish_reason: str | None,
    reasoning_chars: int,
    issues: list[str],
) -> None:
    if args.reflection_mode == "off":
        return
    if args.reflection_mode == "auto" and not issues:
        return
    reflection = {
        "timestamp": utc_now(),
        "phase": args.phase,
        "status": "needs_attention" if issues else "completed",
        "issues": issues,
        "finish_reason": finish_reason,
        "reasoning_chars": reasoning_chars,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
        "response_chars": len(response_text),
        "lesson": (
            "Increase max_tokens, lower hidden reasoning, or tighten quality gates before handing output to Codex."
            if issues
            else "Call satisfied current quality gates; keep Codex review before final use."
        ),
    }
    append_jsonl(paths.reflections, reflection)


def update_memory(
    paths: AgentPaths,
    args: argparse.Namespace,
    *,
    prompt: str,
    response_text: str,
    finish_reason: str | None,
    reasoning_chars: int,
    issues: list[str],
) -> None:
    append_jsonl(
        paths.transcript,
        {
            "timestamp": utc_now(),
            "role": "user",
            "phase": args.phase,
            "content": delegate.redact_secrets(prompt),
        },
    )
    remembered = response_text[: max(0, args.remember_response_chars)]
    append_jsonl(
        paths.transcript,
        {
            "timestamp": utc_now(),
            "role": "assistant",
            "phase": args.phase,
            "content": delegate.redact_secrets(remembered),
            "response_chars": len(response_text),
            "finish_reason": finish_reason,
            "reasoning_chars": reasoning_chars,
            "quality_issues": issues,
            "workflow_id": args.workflow_id,
            "task_id": args.task_id,
        },
    )


def record_review(paths: AgentPaths, args: argparse.Namespace, agent_id: str) -> None:
    if args.remember and args.memory_mode not in {"off", "read"}:
        append_jsonl(
            paths.memory,
            {
                "timestamp": utc_now(),
                "role": "codex-review",
                "phase": "review",
                "content": delegate.redact_secrets(args.remember),
                "workflow_id": args.workflow_id,
                "task_id": args.task_id,
                "review_status": args.review_status,
            },
        )
    if args.reflection:
        append_jsonl(
            paths.reflections,
            {
                "timestamp": utc_now(),
                "workflow_id": args.workflow_id,
                "task_id": args.task_id,
                "review_status": args.review_status,
                "reviewer": args.parent_agent_id,
                "lesson": delegate.redact_secrets(args.reflection),
            },
        )
    append_jsonl(
        paths.events,
        {
            "timestamp": utc_now(),
            "agent_id": agent_id,
            "event": "record_review",
            "workflow_id": args.workflow_id,
            "task_id": args.task_id,
            "review_status": args.review_status,
        },
    )


def main() -> int:
    args = parse_args()
    if args.list_agents:
        agents = list_agents(args.agent_home)
        if args.json:
            print(json.dumps({"agents": agents}, ensure_ascii=False, indent=2))
        else:
            for agent in agents:
                print(f"{agent.get('agent_id')}  {agent.get('last_seen_at')}  {agent.get('path')}")
        return 0

    prompt = read_prompt(args)
    if not prompt and not args.memory_note and not args.record_review:
        print("No prompt provided.", file=sys.stderr)
        return 1

    agent_id = resolve_agent_id(args, prompt or args.memory_note or "")
    paths = agent_paths(args.agent_home, agent_id)
    profile = ensure_agent(paths, agent_id, args)

    if args.memory_note:
        if args.memory_mode not in {"off", "read"}:
            append_jsonl(
                paths.memory,
                {
                    "timestamp": utc_now(),
                    "role": "note",
                    "phase": "memory",
                    "content": delegate.redact_secrets(args.memory_note),
                    "workflow_id": args.workflow_id,
                    "task_id": args.task_id,
                },
            )
        append_jsonl(paths.events, {"timestamp": utc_now(), "event": "memory_note", "agent_id": agent_id})
        if not prompt:
            print(f"Remembered note for agent {agent_id}: {paths.root}")
            return 0

    if args.record_review:
        record_review(paths, args, agent_id)
        print(f"Recorded Codex review for agent {agent_id}: {paths.root}")
        return 0

    decision = delegate.infer_route(prompt, args.phase, args.risk, args.urgency)
    if decision.route == "gpt-5.5" and not args.force_deepseek:
        envelope = {
            "agent_id": agent_id,
            "agent_path": str(paths.root),
            "decision": dataclasses.asdict(decision),
            "response": "",
        }
        print(json.dumps(envelope, ensure_ascii=False, indent=2) if args.json else "Route stayed with GPT-5.5; not calling DeepSeek.")
        return 0

    if args.force_deepseek and decision.route == "gpt-5.5":
        decision = delegate.RouteDecision(
            "hybrid",
            "forced DeepSeek worker call; Codex review remains required.",
            True,
        )

    delegate_args = build_delegate_args(args, build_agent_system(paths, args))
    try:
        result = delegate.call_deepseek(delegate_args, prompt)
    except RuntimeError as exc:
        append_jsonl(
            paths.events,
            {
                "timestamp": utc_now(),
                "agent_id": agent_id,
                "event": "api_error",
                "error": delegate.redact_secrets(str(exc)),
            },
        )
        print(delegate.redact_secrets(str(exc)), file=sys.stderr)
        return 2

    response_text = delegate.extract_message(result)
    finish_reason = delegate.extract_finish_reason(result)
    reasoning_chars = delegate.extract_reasoning_chars(result)
    usage = delegate.usage_summary(result, prompt, response_text)
    request_metadata = delegate.request_meta(result)
    issues = quality_issues(args, response_text, finish_reason, reasoning_chars)

    output_written = False
    if not issues and args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(response_text, encoding="utf-8")
        output_written = True

    entry = delegate.log_call(
        args=delegate_args,
        prompt=prompt,
        decision=decision,
        response_text=response_text,
        usage=usage,
        finish_reason=finish_reason,
        reasoning_chars=reasoning_chars,
        request_metadata={**request_metadata, "agent_id": agent_id},
        quality_status="fail" if issues else "pass",
        quality_issues=issues,
        output_written=output_written,
    )
    append_jsonl(
        paths.events,
        {
            "timestamp": utc_now(),
            "agent_id": agent_id,
            "event": "call",
            "workflow_id": args.workflow_id,
            "task_id": args.task_id,
            "quality_issues": issues,
            "usage": usage,
            "request": request_metadata,
            "log_entry": entry,
        },
    )
    update_memory(
        paths,
        args,
        prompt=prompt,
        response_text=response_text,
        finish_reason=finish_reason,
        reasoning_chars=reasoning_chars,
        issues=issues,
    )
    maybe_reflect(
        paths,
        args,
        prompt=prompt,
        response_text=response_text,
        finish_reason=finish_reason,
        reasoning_chars=reasoning_chars,
        issues=issues,
    )

    if issues:
        print(
            "DeepSeek agent response failed quality gate: " + ", ".join(issues),
            file=sys.stderr,
        )
        if args.raw:
            print(delegate.redact_secrets(json.dumps(result, ensure_ascii=False, indent=2)))
        return 4

    envelope: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_path": str(paths.root),
        "profile": profile,
        "decision": dataclasses.asdict(decision),
        "model": args.model,
        "usage": usage,
        "estimated_codex_tokens_saved": entry["estimated_codex_tokens_saved"],
        "finish_reason": finish_reason,
        "reasoning_chars": reasoning_chars,
        "quality_issues": issues,
        "workflow_id": args.workflow_id,
        "task_id": args.task_id,
        "parent_agent_id": args.parent_agent_id,
        "request": request_metadata,
        "response": response_text,
    }
    if args.raw:
        envelope["raw"] = json.loads(delegate.redact_secrets(json.dumps(result, ensure_ascii=False)))

    if args.json:
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
    else:
        print(f"Agent: {agent_id}")
        print(f"Agent memory: {paths.root}")
        delegate.print_text_result(decision, response_text, entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
