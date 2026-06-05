# Changelog

## v2.4.0 - 2026-06-06

Visual room console and desktop shell update.

- Add `deepseek_room_server.py`, a live SSE-backed room dashboard for browsing
  room history, message timelines, jobs, events, transcripts, and artifacts.
- Add a chat-client UI inspired by QQ/WeChat with searchable room history on
  the left, realtime room conversation in the center, and room inspection on
  the right.
- Add `deepseek_room_desktop.py`, a native pywebview-based Mac desktop shell
  that remembers the selected workspace and can fall back to the system
  browser.
- Add `scripts/build_mac_app.sh` and `scripts/generate_room_console_icon.py`
  so the visual room console can be packaged as a Mac `.app`.
- Add desktop-shell tests, update preflight compilation/syntax checks, and
  validate the frozen app by launching its embedded room server.

## v2.3.0 - 2026-06-06

Reasonix body orchestration update.

- Add `deepseek_reasonix.py`, a standard-library Codex orchestrator that
  creates or reuses an Agent Room, writes a Codex brief into the room, builds a
  temporary Reasonix skill pack, and runs both an execution pass and a strict
  self-review pass.
- Add mandatory multi-agent Reasonix guidance with implementer, tester, critic,
  and docs subagent roles plus explicit peer-supervision rules.
- Add `--skill-name`, `--skill-brief`, and `--image-brief` handoff fields so
  Codex can pass local skill routing context and image descriptions into the
  cheaper Reasonix body.
- Extend transcript export so room events can surface Reasonix artifact paths,
  transcript paths, prompt paths, model ids, and Codex token-share targets.
- Add unit tests for the Reasonix orchestrator and include the new wrapper and
  script in preflight compilation.

## v2.2.0 - 2026-06-06

Default activation and transcript export update.

- Make the Codex skill default-on for most low-risk project-shaped work where
  DeepSeek can draft a reviewable candidate and Codex/GPT can audit it.
- Add explicit non-trigger conditions for Codex-only requests, tiny direct
  commands, credentials/auth/secrets, destructive production work, high-stakes
  final judgment, and urgent turns.
- Add `deepseek_transcript.py`, a standard-library Markdown exporter for
  persistent worker transcripts and Agent Room message logs.
- Add transcript exporter tests and include the new script in preflight
  compilation.
- Update skill `agents/openai.yaml` metadata to reflect broader project-level
  auto-triggering and transcript export.

## v2.1.0 - 2026-06-05

Major orchestration update. This release keeps the original one-shot DeepSeek
delegate, then adds persistent agents and multi-agent room workflows.

- Add `deepseek_agent.py`, a persistent DeepSeek worker with identity, memory,
  transcript separation, reflection logs, Codex-reviewed memory promotion, and
  quality gates.
- Add `deepseek_room.py`, a file-backed Agent Room for cheap DeepSeek writer
  agents plus senior Codex/GPT reviewers, with `needs-rework` retry loops.
- Add planning-first multi-agent guidance: senior Codex/GPT plans architecture,
  task boundaries, acceptance criteria, and reviewer rubric before assigning
  narrow work to cheaper agents.
- Add shape and safety gates: minimum response length, required sections,
  required regexes, JSON expectations, finish reason checks, and hidden
  reasoning diagnostics.
- Add tests for the persistent worker, retry logging, room state transitions,
  routed-away empty responses, and reviewer feedback injection.

## v1.x

Initial release with one-shot DeepSeek delegation, routing policy, usage logs,
Codex token savings estimates, macOS Keychain support, and install/preflight
scripts.
