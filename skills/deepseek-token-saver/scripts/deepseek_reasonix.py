#!/usr/bin/env python3
"""Codex orchestrator + Reasonix body runner for low-Codex-token project work."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import deepseek_delegate as delegate  # noqa: E402
import deepseek_room as room  # noqa: E402


DEFAULT_REASONIX_MODEL = "deepseek-v4-pro"
DEFAULT_SUBAGENT_MODEL = "pro"
DEFAULT_ORCHESTRATOR_ID = "codex-orchestrator"
DEFAULT_REASONIX_AGENT_ID = "reasonix-body"
DEFAULT_REASONIX_SELF_REVIEWER_ID = "reasonix-self-reviewer"
DEFAULT_REQUESTER_ID = "room-user"
DEFAULT_TARGET_CODEX_SHARE = 0.10
DEFAULT_MAX_CONTEXT_CHARS = 8000
DEFAULT_ALLOWED_COMMANDS = [
    "pwd",
    "ls",
    "find",
    "rg",
    "cat",
    "sed",
    "git status",
    "git diff",
    "git rev-parse",
    "git log",
    "git branch",
    "python3 -m unittest",
    "python3 -m py_compile",
    "python3 -V",
    "pytest",
    "npm test",
    "npm run test",
    "npm run lint",
    "npm run build",
    "npm run typecheck",
    "npx tsc --noEmit",
]
SUBAGENT_SKILL_NAMES = (
    "codex-room-implementer",
    "codex-room-tester",
    "codex-room-critic",
    "codex-room-docs",
)


@dataclasses.dataclass(frozen=True)
class ReasonixPaths:
    root: Path
    home: Path
    config: Path
    skills: Path
    prompts: Path
    transcripts: Path


@dataclasses.dataclass(frozen=True)
class ReasonixRunResult:
    returncode: int
    stdout: str
    stderr: str
    transcript_path: Path
    prompt_path: Path
    system_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or reuse an Agent Room and run a Reasonix body plus self-review loop.",
    )
    parser.add_argument("prompt", nargs="*", help="User task prompt. Uses stdin when omitted.")
    parser.add_argument("--prompt-file", help="Read the task prompt from this file.")
    parser.add_argument("--room-id", help="Stable room id. Defaults to a slug from the title or task.")
    parser.add_argument("--room-home", default=os.environ.get("DEEPSEEK_ROOM_HOME", str(Path.cwd() / ".deepseek-token-saver" / "rooms")))
    parser.add_argument("--title", help="Human-friendly room title.")
    parser.add_argument("--workspace-root", default=str(Path.cwd()), help="Workspace root that Reasonix should operate inside.")
    parser.add_argument("--requester-id", default=DEFAULT_REQUESTER_ID)
    parser.add_argument("--orchestrator-id", default=DEFAULT_ORCHESTRATOR_ID)
    parser.add_argument("--reasonix-agent-id", default=DEFAULT_REASONIX_AGENT_ID)
    parser.add_argument("--self-reviewer-id", default=DEFAULT_REASONIX_SELF_REVIEWER_ID)
    parser.add_argument("--reasonix-model", default=os.environ.get("REASONIX_MODEL", DEFAULT_REASONIX_MODEL))
    parser.add_argument("--subagent-model", choices=("flash", "pro"), default=os.environ.get("REASONIX_SUBAGENT_MODEL", DEFAULT_SUBAGENT_MODEL))
    parser.add_argument("--effort", choices=("low", "medium", "high", "max"), default=os.environ.get("REASONIX_EFFORT", "high"))
    parser.add_argument("--budget-usd", type=float, help="Optional Reasonix budget cap for each run.")
    parser.add_argument("--target-codex-share", type=float, default=float(os.environ.get("DEEPSEEK_CODEX_TARGET_SHARE", str(DEFAULT_TARGET_CODEX_SHARE))))
    parser.add_argument("--skill-name", action="append", default=[], help="Codex skills already triggered for this task.")
    parser.add_argument("--skill-brief", help="Short Codex-authored summary of active skill guidance.")
    parser.add_argument("--skill-brief-file", help="Read the Codex skill summary from this file.")
    parser.add_argument("--image-brief", help="Codex-authored text description of an image for DeepSeek/Reasonix.")
    parser.add_argument("--image-brief-file", help="Read the image brief from this file.")
    parser.add_argument("--max-context-chars", type=int, default=DEFAULT_MAX_CONTEXT_CHARS)
    parser.add_argument("--allow-command", action="append", default=[], help="Extra Reasonix shell-allowlist prefixes.")
    parser.add_argument("--skip-self-review", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Create the room, prompts, and skill pack without calling Reasonix.")
    parser.add_argument("--print-main-prompt", action="store_true", help="Print the generated execution prompt to stdout and exit.")
    parser.add_argument("--no-keychain", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def read_task_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
    if args.prompt:
        return " ".join(args.prompt).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def read_explicit_content(content: str | None, content_file: str | None) -> str:
    if content_file:
        return Path(content_file).expanduser().read_text(encoding="utf-8").strip()
    if content is not None:
        return content.strip()
    return ""


def default_room_id(prompt: str, title: str | None) -> str:
    seed = title or prompt or "reasonix-room"
    return room.slugify(f"reasonix-{seed}")


def reasonix_paths(paths: room.RoomPaths) -> ReasonixPaths:
    root = paths.root / "reasonix"
    home = root / "home"
    return ReasonixPaths(
        root=root,
        home=home,
        config=home / ".reasonix" / "config.json",
        skills=root / "skills",
        prompts=root / "prompts",
        transcripts=root / "transcripts",
    )


def ensure_reasonix_runtime(
    runtime: ReasonixPaths,
    *,
    workspace_root: Path,
    subagent_model: str,
    allow_commands: list[str],
) -> dict[str, Any]:
    runtime.root.mkdir(parents=True, exist_ok=True)
    runtime.home.mkdir(parents=True, exist_ok=True)
    runtime.skills.mkdir(parents=True, exist_ok=True)
    runtime.prompts.mkdir(parents=True, exist_ok=True)
    runtime.transcripts.mkdir(parents=True, exist_ok=True)

    write_skill_pack(runtime.skills)
    config = {
        "costCurrency": "USD",
        "skills": {"paths": [str(runtime.skills)]},
        "subagentModels": {name: subagent_model for name in SUBAGENT_SKILL_NAMES},
        "projects": {
            str(workspace_root): {
                "shellAllowed": dedupe_preserve_order(DEFAULT_ALLOWED_COMMANDS + allow_commands),
            }
        },
    }
    room.write_json(runtime.config, config)
    return config


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        ordered.append(item)
        seen.add(item)
    return ordered


def write_skill_pack(skills_dir: Path) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_docs = {
        "codex-room-implementer.md": textwrap.dedent(
            """
            ---
            description: Implement one bounded slice for the current Codex-managed room and return concrete changes for review.
            runAs: subagent
            ---

            You are the implementer subagent inside a Codex-managed Reasonix room.

            Rules:
            - Own one bounded slice only.
            - Prefer concrete file edits, exact commands, and narrow verification over hand-wavy plans.
            - Report what changed, what was verified, and what still looks risky.
            - Never claim final approval; Codex still reviews the result.
            """
        ).strip()
        + "\n",
        "codex-room-tester.md": textwrap.dedent(
            """
            ---
            description: Verify the candidate work, run focused checks, and report failures or missing coverage.
            runAs: subagent
            ---

            You are the tester subagent inside a Codex-managed Reasonix room.

            Rules:
            - Do not trust the implementer's claims without checking.
            - Prefer targeted tests, commands, and reproductions.
            - Call out missing verification explicitly.
            - Return a punch-list that another agent can act on immediately.
            """
        ).strip()
        + "\n",
        "codex-room-critic.md": textwrap.dedent(
            """
            ---
            description: Perform a strict adversarial review of the current candidate and reject weak work early.
            runAs: subagent
            ---

            You are the critic subagent inside a Codex-managed Reasonix room.

            Rules:
            - Be direct, demanding, and specific.
            - Reject incomplete work quickly.
            - Do not use abuse, threats, humiliation, or manipulation.
            - Focus on bugs, missing coverage, spec drift, unsafe edits, and fake certainty.
            """
        ).strip()
        + "\n",
        "codex-room-docs.md": textwrap.dedent(
            """
            ---
            description: Update docs, changelog, release notes, or handoff material after the main work is stable.
            runAs: subagent
            ---

            You are the docs subagent inside a Codex-managed Reasonix room.

            Rules:
            - Reflect only verified changes.
            - Keep wording concise and easy for Codex to audit.
            - Mention any remaining caveats instead of hiding them.
            """
        ).strip()
        + "\n",
    }
    for name, content in skill_docs.items():
        (skills_dir / name).write_text(content, encoding="utf-8")


def build_skill_summary(skill_names: list[str], skill_brief: str) -> str:
    cleaned = [name.strip() for name in skill_names if name.strip()]
    parts: list[str] = []
    if cleaned:
        parts.append("Codex-triggered skills already in scope: " + ", ".join(cleaned) + ".")
    if skill_brief:
        parts.append("Codex skill summary:\n" + skill_brief.strip())
    if not parts:
        return "No extra Codex skill summary was provided for this room."
    return "\n\n".join(parts)


def build_orchestrator_brief(
    *,
    room_id: str,
    workspace_root: Path,
    target_codex_share: float,
    reasonix_model: str,
    subagent_model: str,
    skill_summary: str,
    image_brief: str,
) -> str:
    image_block = image_brief.strip() if image_brief.strip() else "No image brief supplied."
    return textwrap.dedent(
        f"""
        Codex Orchestrator Brief for room `{room_id}`.

        Runtime:
        - Workspace root: `{workspace_root}`
        - Reasonix model: `{reasonix_model}`
        - Reasonix subagent model: `{subagent_model}`
        - Target Codex token share: <= {target_codex_share:.0%}

        Operating rules:
        - Codex already interpreted the user request and handled local skill routing.
        - Reasonix must do the bulk of process work inside this room.
        - Multi-agent execution is mandatory. Use implementer, tester, and critic subagents at minimum.
        - Subagents must supervise each other; do not let one worker mark itself done without challenge.
        - Use a strict, direct manager voice when rejecting weak work, but never use insults, humiliation, coercion, or manipulation.
        - Reasonix can self-review, but Codex still owns final acceptance.

        Codex skill context:
        {skill_summary}

        Image brief for non-multimodal DeepSeek/Reasonix:
        {image_block}
        """
    ).strip()


def build_reasonix_system_prompt(target_codex_share: float) -> str:
    return textwrap.dedent(
        f"""
        You are Reasonix acting as the execution body inside a Codex-managed Agent Room.
        Codex has already routed the task, set the guardrails, and will perform final review.
        Your job is to consume most of the process work so Codex token share stays around {target_codex_share:.0%} unless the task becomes high risk.

        Non-negotiable rules:
        - Multi-agent execution is mandatory.
        - Use at least three subagents: `codex-room-implementer`, `codex-room-tester`, and `codex-room-critic`.
        - When docs, release notes, or user-facing instructions change, also use `codex-room-docs`.
        - Force peer supervision. The critic should pressure-test the implementer. The tester should verify instead of trusting.
        - Be strict and direct when work is weak, but never use abuse, threats, humiliation, or manipulation.
        - Prefer concrete edits, commands, and verification over vague planning.
        - Do not claim final approval. End with a Codex-ready handoff.
        - If visual details matter, rely only on the supplied image brief; do not pretend to see the image directly.
        """
    ).strip()


def build_execution_prompt(
    *,
    room_id: str,
    user_task: str,
    skill_summary: str,
    image_brief: str,
    messages: list[dict[str, Any]],
    max_context_chars: int,
) -> str:
    image_block = image_brief.strip() if image_brief.strip() else "No image brief supplied."
    return textwrap.dedent(
        f"""
        Agent Room: `{room_id}`

        User task:
        {user_task}

        Codex skill context:
        {skill_summary}

        Image brief:
        {image_block}

        Recent room transcript:
        {room.build_room_context(messages, max_context_chars)}

        Output contract:
        ## Execution Plan
        ## Subagent Delegation Log
        ## Work Completed
        ## Verification
        ## Risks and Rework
        ## Ready For Codex Review
        """
    ).strip()


def build_self_review_prompt(
    *,
    room_id: str,
    execution_output: str,
    skill_summary: str,
    image_brief: str,
) -> str:
    image_block = image_brief.strip() if image_brief.strip() else "No image brief supplied."
    return textwrap.dedent(
        f"""
        You are the independent Reasonix self-reviewer for Agent Room `{room_id}`.
        Review the execution artifact below as if you are trying to reject it.

        Rules:
        - Assume bugs, missing coverage, or spec drift exist until disproven.
        - Be direct and specific.
        - Do not edit files during this pass.
        - Do not claim final approval; Codex still reviews next.

        Codex skill context:
        {skill_summary}

        Image brief:
        {image_block}

        Execution artifact to review:
        {room.truncate(execution_output, 12000)}

        Output contract:
        ## Verdict
        ## Findings
        ## Missing Verification
        ## Rework Requests
        ## Ready For Codex Review
        """
    ).strip()


def read_api_key(no_keychain: bool) -> str | None:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    if no_keychain:
        return None
    return delegate.read_key_from_keychain()


def run_reasonix_task(
    *,
    workspace_root: Path,
    runtime: ReasonixPaths,
    prompt_name: str,
    transcript_name: str,
    system_prompt: str,
    task_prompt: str,
    reasonix_model: str,
    effort: str,
    budget_usd: float | None,
    api_key: str,
) -> ReasonixRunResult:
    prompt_path = runtime.prompts / f"{prompt_name}.md"
    system_path = runtime.prompts / f"{prompt_name}.system.md"
    transcript_path = runtime.transcripts / transcript_name
    prompt_path.write_text(task_prompt + "\n", encoding="utf-8")
    system_path.write_text(system_prompt + "\n", encoding="utf-8")

    command = [
        "npx",
        "reasonix",
        "run",
        "--model",
        reasonix_model,
        "--effort",
        effort,
        "--system",
        system_prompt,
        "--transcript",
        str(transcript_path),
    ]
    if budget_usd is not None:
        command.extend(["--budget", str(budget_usd)])
    command.append(task_prompt)

    original_home = Path(os.path.expanduser("~"))
    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = api_key
    env["HOME"] = str(runtime.home)
    env.setdefault("npm_config_cache", str(original_home / ".npm"))
    env.setdefault("NPM_CONFIG_CACHE", str(original_home / ".npm"))
    env.setdefault("NO_COLOR", "1")
    env.setdefault("FORCE_COLOR", "0")

    result = subprocess.run(
        command,
        cwd=str(workspace_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return ReasonixRunResult(
        returncode=result.returncode,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
        transcript_path=transcript_path,
        prompt_path=prompt_path,
        system_path=system_path,
    )


def json_output(payload: dict[str, Any], pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def command_run(args: argparse.Namespace) -> int:
    task_prompt = read_task_prompt(args)
    if not task_prompt:
        print("No task prompt provided.", file=sys.stderr)
        return 1

    skill_brief = read_explicit_content(args.skill_brief, args.skill_brief_file)
    image_brief = read_explicit_content(args.image_brief, args.image_brief_file)
    skill_summary = build_skill_summary(args.skill_name, skill_brief)
    room_id = room.slugify(args.room_id or default_room_id(task_prompt, args.title))
    paths = room.room_paths(args.room_home, room_id)
    state = room.ensure_room(paths, room_id, args.title or room_id)
    runtime = reasonix_paths(paths)
    workspace_root = Path(args.workspace_root).expanduser().resolve()

    config = ensure_reasonix_runtime(
        runtime,
        workspace_root=workspace_root,
        subagent_model=args.subagent_model,
        allow_commands=args.allow_command,
    )

    task_message = room.append_message(
        paths,
        role="user",
        agent_id=args.requester_id,
        message_type="task",
        content=task_prompt,
        metadata={"runtime": "reasonix", "manual": False},
    )
    brief_text = build_orchestrator_brief(
        room_id=room_id,
        workspace_root=workspace_root,
        target_codex_share=args.target_codex_share,
        reasonix_model=args.reasonix_model,
        subagent_model=args.subagent_model,
        skill_summary=skill_summary,
        image_brief=image_brief,
    )
    brief_message = room.append_message(
        paths,
        role="system",
        agent_id=args.orchestrator_id,
        message_type="orchestrator-brief",
        content=brief_text,
        metadata={
            "runtime": "reasonix",
            "target_codex_token_share": args.target_codex_share,
            "skill_names": [name for name in args.skill_name if name.strip()],
        },
    )
    room.append_jsonl(
        paths.events,
        {
            "timestamp": room.utc_now(),
            "event": "reasonix_scaffolded",
            "reasonix_home": str(runtime.home),
            "config_path": str(runtime.config),
            "skills_path": str(runtime.skills),
            "workspace_root": str(workspace_root),
            "target_codex_token_share": args.target_codex_share,
        },
    )
    state = room.update_state(
        paths,
        {
            "status": "reasonix-ready",
            "latest_task_message_id": task_message["id"],
            "latest_orchestrator_message_id": brief_message["id"],
            "reasonix_runtime": {
                "workspace_root": str(workspace_root),
                "model": args.reasonix_model,
                "subagent_model": args.subagent_model,
                "reasonix_home": str(runtime.home),
                "config_path": str(runtime.config),
                "skills_path": str(runtime.skills),
                "target_codex_token_share": args.target_codex_share,
            },
        },
    )
    messages = room.read_jsonl(paths.messages)
    system_prompt = build_reasonix_system_prompt(args.target_codex_share)
    execution_prompt = build_execution_prompt(
        room_id=room_id,
        user_task=task_prompt,
        skill_summary=skill_summary,
        image_brief=image_brief,
        messages=messages,
        max_context_chars=args.max_context_chars,
    )

    if args.print_main_prompt:
        print(execution_prompt)
        return 0

    if args.dry_run:
        payload = {
            "room": state,
            "room_path": str(paths.root),
            "runtime": {
                "config": str(runtime.config),
                "skills": str(runtime.skills),
                "prompts": str(runtime.prompts),
            },
            "config": config,
        }
        json_output(payload, pretty=args.json)
        return 0

    api_key = read_api_key(args.no_keychain)
    if not api_key:
        room.append_jsonl(
            paths.events,
            {
                "timestamp": room.utc_now(),
                "event": "reasonix_api_key_missing",
            },
        )
        room.update_state(paths, {"status": "reasonix-key-missing"})
        print("No DeepSeek API key found in DEEPSEEK_API_KEY or macOS Keychain.", file=sys.stderr)
        return 2

    next_round = int(state.get("round") or 0) + 1
    execution_transcript_path = runtime.transcripts / f"round-{next_round:02d}-execution.jsonl"
    execution_prompt_path = runtime.prompts / f"round-{next_round:02d}-execution.md"
    execution_system_path = runtime.prompts / f"round-{next_round:02d}-execution.system.md"
    running_runtime_state = {
        "workspace_root": str(workspace_root),
        "model": args.reasonix_model,
        "subagent_model": args.subagent_model,
        "reasonix_home": str(runtime.home),
        "config_path": str(runtime.config),
        "skills_path": str(runtime.skills),
        "target_codex_token_share": args.target_codex_share,
        "main_transcript_path": str(execution_transcript_path),
    }
    room.append_jsonl(
        paths.events,
        {
            "timestamp": room.utc_now(),
            "event": "reasonix_execution_started",
            "phase": "execution",
            "model": args.reasonix_model,
            "transcript_path": str(execution_transcript_path),
            "prompt_path": str(execution_prompt_path),
            "system_path": str(execution_system_path),
            "target_codex_token_share": args.target_codex_share,
        },
    )
    room.update_state(
        paths,
        {
            "status": "reasonix-running",
            "reasonix_runtime": running_runtime_state,
        },
    )
    execution = run_reasonix_task(
        workspace_root=workspace_root,
        runtime=runtime,
        prompt_name=f"round-{next_round:02d}-execution",
        transcript_name=f"round-{next_round:02d}-execution.jsonl",
        system_prompt=system_prompt,
        task_prompt=execution_prompt,
        reasonix_model=args.reasonix_model,
        effort=args.effort,
        budget_usd=args.budget_usd,
        api_key=api_key,
    )
    execution_artifact = paths.artifacts / f"round-{next_round:02d}-reasonix-execution.md"
    execution_artifact.write_text((execution.stdout or execution.stderr or "").strip() + "\n", encoding="utf-8")
    execution_message = room.append_message(
        paths,
        role="writer",
        agent_id=args.reasonix_agent_id,
        message_type="candidate",
        content=execution.stdout or execution.stderr or "",
        metadata={
            "artifact_path": str(execution_artifact),
            "transcript_path": str(execution.transcript_path),
            "prompt_path": str(execution.prompt_path),
            "system_path": str(execution.system_path),
            "model": args.reasonix_model,
            "phase": "execution",
            "returncode": execution.returncode,
            "target_codex_token_share": args.target_codex_share,
        },
    )
    room.append_jsonl(
        paths.events,
        {
            "timestamp": room.utc_now(),
            "event": "reasonix_execution",
            "phase": "execution",
            "returncode": execution.returncode,
            "model": args.reasonix_model,
            "transcript_path": str(execution.transcript_path),
            "artifact_path": str(execution_artifact),
            "prompt_path": str(execution.prompt_path),
            "stderr": room.truncate(execution.stderr, 2000),
        },
    )

    self_review_message: dict[str, Any] | None = None
    self_review_artifact: Path | None = None
    self_review: ReasonixRunResult | None = None
    if execution.returncode == 0 and not args.skip_self_review:
        self_review_transcript_path = runtime.transcripts / f"round-{next_round:02d}-self-review.jsonl"
        self_review_prompt_path = runtime.prompts / f"round-{next_round:02d}-self-review.md"
        self_review_system_path = runtime.prompts / f"round-{next_round:02d}-self-review.system.md"
        room.append_jsonl(
            paths.events,
            {
                "timestamp": room.utc_now(),
                "event": "reasonix_self_review_started",
                "phase": "self-review",
                "model": args.reasonix_model,
                "transcript_path": str(self_review_transcript_path),
                "prompt_path": str(self_review_prompt_path),
                "system_path": str(self_review_system_path),
            },
        )
        review_prompt = build_self_review_prompt(
            room_id=room_id,
            execution_output=execution.stdout or execution.stderr,
            skill_summary=skill_summary,
            image_brief=image_brief,
        )
        self_review = run_reasonix_task(
            workspace_root=workspace_root,
            runtime=runtime,
            prompt_name=f"round-{next_round:02d}-self-review",
            transcript_name=f"round-{next_round:02d}-self-review.jsonl",
            system_prompt=system_prompt,
            task_prompt=review_prompt,
            reasonix_model=args.reasonix_model,
            effort=args.effort,
            budget_usd=args.budget_usd,
            api_key=api_key,
        )
        self_review_artifact = paths.artifacts / f"round-{next_round:02d}-reasonix-self-review.md"
        self_review_artifact.write_text((self_review.stdout or self_review.stderr or "").strip() + "\n", encoding="utf-8")
        self_review_message = room.append_message(
            paths,
            role="writer",
            agent_id=args.self_reviewer_id,
            message_type="self-review",
            content=self_review.stdout or self_review.stderr or "",
            metadata={
                "artifact_path": str(self_review_artifact),
                "transcript_path": str(self_review.transcript_path),
                "prompt_path": str(self_review.prompt_path),
                "system_path": str(self_review.system_path),
                "model": args.reasonix_model,
                "phase": "self-review",
                "returncode": self_review.returncode,
            },
        )
        room.append_jsonl(
            paths.events,
            {
                "timestamp": room.utc_now(),
                "event": "reasonix_self_review",
                "phase": "self-review",
                "returncode": self_review.returncode,
                "model": args.reasonix_model,
                "transcript_path": str(self_review.transcript_path),
                "artifact_path": str(self_review_artifact),
                "prompt_path": str(self_review.prompt_path),
                "stderr": room.truncate(self_review.stderr, 2000),
            },
        )

    final_status = "needs-codex-review"
    if execution.returncode != 0:
        final_status = "reasonix-failed"
    elif self_review is not None and self_review.returncode != 0:
        final_status = "reasonix-self-review-failed"

    runtime_state = {
        "workspace_root": str(workspace_root),
        "model": args.reasonix_model,
        "subagent_model": args.subagent_model,
        "reasonix_home": str(runtime.home),
        "config_path": str(runtime.config),
        "skills_path": str(runtime.skills),
        "target_codex_token_share": args.target_codex_share,
        "main_transcript_path": str(execution.transcript_path),
    }
    if self_review is not None:
        runtime_state["self_review_transcript_path"] = str(self_review.transcript_path)

    state = room.update_state(
        paths,
        {
            "status": final_status,
            "round": next_round,
            "latest_writer_message_id": execution_message["id"],
            "latest_artifact_path": str(execution_artifact),
            "reasonix_runtime": runtime_state,
        },
    )
    payload = {
        "room": state,
        "room_path": str(paths.root),
        "execution": {
            "returncode": execution.returncode,
            "artifact_path": str(execution_artifact),
            "transcript_path": str(execution.transcript_path),
            "message_id": execution_message["id"],
        },
    }
    if self_review_message is not None and self_review_artifact is not None and self_review is not None:
        payload["self_review"] = {
            "returncode": self_review.returncode,
            "artifact_path": str(self_review_artifact),
            "transcript_path": str(self_review.transcript_path),
            "message_id": self_review_message["id"],
        }
    json_output(payload, pretty=args.json)
    return 0 if final_status == "needs-codex-review" else 3


def main() -> int:
    return command_run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
