# Changelog

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
