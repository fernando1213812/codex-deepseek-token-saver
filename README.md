<p align="center">
  <img src="assets/icon.svg" alt="Codex DeepSeek Token Saver" width="128" height="128">
</p>

# Codex DeepSeek Token Saver

[English](README.md) | [简体中文](README.zh-CN.md)

Current version: **v2.4.0**. See [changelog](docs/changelog.md).

Delegate low-risk Codex work to DeepSeek, log DeepSeek token usage, and estimate
how many Codex tokens were saved. GPT-5.5 stays responsible for review and final
correctness.

This project is for agents that want to use cheap long-context model calls for
drafting, batching, and exploration without letting those calls make final
decisions.

## Why

DeepSeek can be very inexpensive for large context and process-heavy work.
Codex/GPT-5.5 should still handle final review, safety checks, and correctness
gates. This repo provides a small standard-library Python CLI plus a Codex skill
that makes that split explicit.

## What's New In v2.4

- Add `deepseek_room_server.py`, a visual room dashboard with live SSE updates,
  room history, timeline view, jobs, events, transcripts, and artifacts.
- Add `deepseek_room_desktop.py`, a native Mac desktop shell that opens the
  room console in a pywebview window and remembers the selected workspace.
- Add `scripts/build_mac_app.sh` plus generated icon tooling so the console can
  be packaged as a Mac `.app`.
- Redesign the dashboard into a chat-client layout inspired by QQ/WeChat:
  room list on the left, live conversation in the center, operational
  inspector on the right.
- Keep the v2.3 Reasonix orchestrator flow, including mandatory multi-agent
  execution, self-review, and Codex final audit.

## Routing Policy

Detailed policy: [English](docs/routing-policy.md) | [简体中文](docs/routing-policy.zh-CN.md)

Use DeepSeek for:

- Brainstorming, outlines, rewrites, summaries, extraction, translation.
- Bounded boilerplate, candidate helper code, examples, test-data drafts.
- Batch or non-urgent work where slower completion is acceptable.

Use GPT-5.5 for:

- Final answers, final review, publish/release/deploy decisions.
- Security, credentials, auth, destructive actions, production changes.
- High-risk or correctness-critical verification.

Use hybrid mode when DeepSeek drafts and GPT-5.5 audits.

## Quick Start

Store a DeepSeek API key in macOS Keychain:

```sh
read -s DEEPSEEK_API_KEY
security add-generic-password -U -a "$USER" -s codex-deepseek-api-key -w "$DEEPSEEK_API_KEY"
unset DEEPSEEK_API_KEY
```

Run a draft task:

```sh
python3 deepseek_delegate.py \
  --phase draft \
  --out work/draft.md \
  "Draft three options for a small CLI README."
```

Check routing without calling DeepSeek:

```sh
python3 deepseek_delegate.py --route-only --phase final "Review this release plan"
```

The CLI logs JSONL entries to `.deepseek-token-saver/calls.jsonl` by default.

Run a persistent DeepSeek worker:

```sh
python3 deepseek_agent.py \
  --agent-id codex-deepseek-worker \
  --phase implement \
  --workflow-id calculator \
  --task-id draft-main-code \
  --min-response-chars 2000 \
  --out work/deepseek-draft.py \
  "Draft a bounded candidate implementation for Codex review."
```

Run an Agent Room writer/reviewer loop:

```sh
python3 deepseek_room.py init --room-id calculator-room

python3 deepseek_room.py writer \
  --room-id calculator-room \
  --writer-id codex-deepseek-room-writer \
  --reviewer-id codex-gpt-5.5-reviewer \
  --prompt "Build the candidate implementation."

python3 deepseek_room.py review \
  --room-id calculator-room \
  --status needs-rework \
  --feedback "Rejected: add keyboard handling and tests."

python3 deepseek_room.py writer --room-id calculator-room
```

Run the full Codex orchestrator + Reasonix body room flow:

```sh
python3 deepseek_reasonix.py \
  --room-id overnight-room \
  --skill-name deepseek-token-saver \
  --skill-name diagnose \
  --skill-brief "Codex already routed this as a low-risk implementation task. DeepSeek/Reasonix should do the bulk of the drafting, but Codex will still test and perform final review." \
  --image-brief-file work/ui-brief.md \
  "Create the room, force multi-agent Reasonix execution, and return a Codex-ready candidate."
```

This flow is designed for "one instruction in, cheap multi-agent execution in
the room, Codex final review out" while keeping Codex's token share low.

Run the visual room server in a browser:

```sh
python3 deepseek_room_server.py --host 127.0.0.1 --port 8765
```

Launch the native Mac desktop shell:

```sh
python3 deepseek_room_desktop.py
```

Build the Mac `.app` bundle:

```sh
sh scripts/build_mac_app.sh
```

The frozen desktop app stores its remembered workspace and startup log in
`~/Library/Application Support/Reasonix Room Console/`.

Export the latest readable worker or room transcript:

```sh
python3 deepseek_transcript.py \
  --latest \
  --out work/deepseek-transcript.md
```

Scaffold the Reasonix room without calling the API:

```sh
python3 deepseek_reasonix.py \
  --room-id overnight-room \
  --dry-run \
  "Create the room and prompts only."
```

## Example Output

```text
Route: deepseek
Reason: low-risk non-final drafting/batch work is suitable for DeepSeek.
Review: GPT-5.5 must audit before final use.
DeepSeek tokens: 742 total (129 prompt, 613 completion)
Estimated Codex tokens saved: 519
```

The savings number is intentionally approximate. It estimates how many Codex
tokens would likely have been spent if Codex performed the draft work directly,
then applies a configurable ratio. Use `--savings-ratio` or
`DEEPSEEK_CODEX_SAVINGS_RATIO` to tune it.

## Install As A Codex Skill

Copy the bundled skill into your Codex skills folder:

```sh
sh scripts/install_skill.sh
```

Restart Codex so the skill metadata is loaded.

## Safety

- Do not paste API keys into chat, screenshots, GitHub issues, or commits.
- Revoke any exposed API key immediately.
- DeepSeek output is draft material only.
- GPT-5.5 must audit final code, final answers, and public publishing steps.
- Durable DeepSeek memory should only store Codex-reviewed lessons, never raw
  secrets or unverified transcripts.

## Development

Run local checks:

```sh
sh scripts/preflight.sh
```

## License

MIT
