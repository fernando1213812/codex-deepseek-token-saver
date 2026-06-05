---
name: deepseek-token-saver
description: Delegates low-risk, non-urgent Codex work to DeepSeek to save Codex tokens while keeping GPT-5.5 responsible for review and final correctness. Use when the user asks to use DeepSeek, save Codex tokens, compare cheap-model drafts, run background candidate generation, log token savings, or make subagents call DeepSeek for draft/research/batch work.
---

# DeepSeek Token Saver

Use this skill to route expendable process work to DeepSeek while preserving
GPT-5.5 as the reviewer and final decision maker.

## Routing Rule

Use DeepSeek for:

- Brainstorming, outlines, rewrites, summaries, extraction, translation, examples.
- Bounded helper code, boilerplate, candidate implementations, test-data drafts.
- Batch/non-urgent work where slower completion is acceptable.

Use GPT-5.5 for:

- Final answers, final code review, release/publish/deploy decisions.
- Security, credentials, auth, destructive actions, production changes.
- Ambiguous high-impact architecture or correctness-critical verification.

Use hybrid mode when DeepSeek can draft but GPT-5.5 must audit before use.

## Workflow

1. Classify the task phase and risk before calling DeepSeek.
2. Prefer `--phase draft`, `--phase brainstorm`, or `--phase batch` for pure DeepSeek work.
3. Use `--phase implement` for candidate code; then inspect, edit, run tests, and verify with GPT-5.5.
4. Never treat DeepSeek output as final. It is a draft artifact.
5. Report DeepSeek token usage and estimated Codex token savings in the final response.

## Command

Persistent DeepSeek worker agent (preferred when the user asks for DeepSeek to
act like an embedded sub-agent, retain memory, or reflect):

```sh
python3 skills/deepseek-token-saver/scripts/deepseek_agent.py \
  --agent-id codex-deepseek-worker \
  --phase implement \
  --workflow-id function-calculator \
  --task-id draft-main-code \
  --min-response-chars 3000 \
  --require-section "class" \
  --out work/deepseek-agent-output.py \
  "Draft the candidate implementation ..."
```

Record Codex review, durable memory, and reflection for that worker:

```sh
python3 skills/deepseek-token-saver/scripts/deepseek_agent.py \
  --agent-id codex-deepseek-worker \
  --record-review \
  --review-status accepted \
  --remember "Use deepseek-chat for visible code generation; keep quality gates." \
  --reflection "Outputs are only promoted to memory after Codex review."
```

List persistent DeepSeek workers:

```sh
python3 skills/deepseek-token-saver/scripts/deepseek_agent.py --list-agents
```

Agent Room orchestration (preferred when the user asks for multiple agents in
one channel, cheap writer + expensive reviewer loops, or "打回重做"):

```sh
python3 skills/deepseek-token-saver/scripts/deepseek_room.py init \
  --room-id calculator-room \
  --title "Calculator writer/reviewer room"

python3 skills/deepseek-token-saver/scripts/deepseek_room.py writer \
  --room-id calculator-room \
  --writer-id codex-deepseek-room-writer \
  --reviewer-id codex-gpt-5.5-reviewer \
  --prompt "Build a clickable Tkinter calculator matching the reference."

python3 skills/deepseek-token-saver/scripts/deepseek_room.py review \
  --room-id calculator-room \
  --status needs-rework \
  --feedback "Rejected: the Canvas buttons render but mouse/keyboard events are not bound."

python3 skills/deepseek-token-saver/scripts/deepseek_room.py writer \
  --room-id calculator-room
```

The room stores a shared transcript in
`.deepseek-token-saver/rooms/<room_id>/messages.jsonl`, state in `state.json`,
and candidate artifacts in `artifacts/`. A rejected reviewer message becomes
part of the next DeepSeek writer prompt. This is the local "same chat channel"
between agents; the parent Codex turn still owns final review and user-facing
answers.

Low-level one-shot delegate (use when memory/reflection are not needed):

From the repository or skill folder:

```sh
python3 skills/deepseek-token-saver/scripts/deepseek_delegate.py \
  --phase draft \
  --max-tokens 1800 \
  --out work/deepseek-draft.md \
  "Draft three implementation options for ..."
```

Dry-run routing:

```sh
python3 skills/deepseek-token-saver/scripts/deepseek_delegate.py \
  --route-only \
  --phase final \
  "Review this release plan"
```

The script reads `DEEPSEEK_API_KEY` first, then macOS Keychain service
`codex-deepseek-api-key`. It logs JSONL usage to
`.deepseek-token-saver/calls.jsonl` unless `DEEPSEEK_DELEGATE_LOG` or
`--log-file` overrides the path.

`deepseek_delegate.py` is the stateless API caller. It supports retry/backoff,
`Retry-After`, `--thinking enabled`, `finish_reason`/`reasoning_chars` logging,
and `--min-response-chars` quality gates. Keep it as the low-level transport
layer.

## Subagent Use

Only spawn Codex subagents when the current tool policy permits it and the user
has asked for subagents, delegation, or parallel agent work. A Codex subagent is
not DeepSeek itself; it should act as a DeepSeek worker runner by calling
`deepseek_agent.py`.

When the user asks for a DeepSeek sub-agent that is embedded in Codex, has
memory, or can reflect:

1. Spawn a Codex worker subagent if the multi-agent tool is available and the
   user explicitly asked for subagents/delegation.
2. Instruct that worker to call `deepseek_agent.py` with a stable `--agent-id`,
   `--workflow-id`, and `--task-id`.
3. Give it a bounded task and a disjoint output path.
4. Require it to report `agent_id`, memory path, quality gate status, usage, and
   files written.
5. The parent Codex agent must audit the output, run tests, and then record
   accepted lessons with `--record-review --remember --reflection`.

DeepSeek memory rules:

- Treat DeepSeek memory as local prompt context, not as a verified fact source.
- Only Codex-reviewed lessons should become durable memory.
- Ordinary prompts/responses are written to `transcript.jsonl`; only `note` and
  `codex-review` memory entries are injected into future prompts.
- DeepSeek self-reflection is a learning artifact, not a pass/fail verdict.
- Memory must stay bounded with `--memory-window` and `--memory-char-budget`.
- Do not store API keys, credentials, or sensitive private context in memory.

Quality gates:

- Use `--min-response-chars` for substantial code or document generation.
- Use `--require-section`, `--require-regex`, or `--expect-json` when shape
  matters.
- Fail and retry when `finish_reason=length` or reasoning dominates visible
  output.
- Never treat a passed DeepSeek quality gate as final approval; Codex review is
  still required.

If the multi-agent tool is not available, run `deepseek_agent.py` locally in the
parent thread and report that no separate Codex subagent could be spawned.

## Agent Room Use

When the user asks for multiple agents to collaborate in one chat/channel:

1. Have the senior Codex/GPT agent plan first. Produce the architecture,
   acceptance criteria, task boundaries, risk list, and reviewer rubric before
   spawning cheaper workers.
2. Split the plan into fine-grained agents with clear ownership. Prefer several
   narrow agents over one broad worker: implementation, UI, tests, docs,
   research, data shaping, migration, or verification as needed.
3. Create or reuse a `deepseek_room.py` room with a stable `--room-id`.
4. Let DeepSeek writer agents produce the main candidate work through the room,
   not by a
   loose one-shot call.
5. Spawn a Codex reviewer subagent when the tool policy permits it and the user
   explicitly asked for multi-agent work. Give the reviewer the latest artifact
   path and require an `accepted` or `needs-rework` verdict.
6. Record the reviewer verdict with `deepseek_room.py review`.
7. If the verdict is `needs-rework`, call `deepseek_room.py writer` again; it
   will inject the previous review and candidate excerpt into the next prompt.
8. Only record durable DeepSeek memory after Codex review. Use
   `--record-to-writer-memory --remember` on accepted reviews for reusable
   lessons.

This makes DeepSeek do the bulk of draft output while Codex audits and routes
the retry loop. Do not pretend the local room is a full Codex UI integration:
it is a file-backed channel that the parent Codex agent and subagents can share.

Default multi-agent roster when the task is large enough:

- `senior-planner` (Codex/GPT): owns architecture, task decomposition,
  acceptance criteria, sequencing, and risk register.
- `deepseek-implementer-*`: owns bounded code or content slices.
- `deepseek-researcher-*`: owns low-risk source gathering, comparisons,
  examples, or outline drafts.
- `deepseek-test-writer`: drafts targeted tests, fixtures, edge cases, and
  regression scenarios.
- `deepseek-doc-writer`: drafts README, usage notes, changelog, or handoff text.
- `codex-reviewer`: audits artifacts, tests, safety, UX, and final correctness;
  rejects work back into the room when needed.

Do not spawn many agents just for show. Use more agents when the plan naturally
has separable projects or workstreams. Each worker prompt must include owner,
inputs, output path, success criteria, and what not to touch.

## Final Report Template

Include:

- Route: DeepSeek / hybrid / GPT-5.5.
- Agent: agent_id, agent memory path, workflow_id/task_id when used.
- DeepSeek tokens used: total, prompt, completion.
- Estimated Codex tokens saved.
- Quality gates: pass/fail, finish_reason, reasoning_chars, retries/attempts.
- GPT-5.5 review or verification performed.
- Files changed and tests run.

## 中文说明

使用这个 skill 时，核心规则是：DeepSeek 负责低风险、非最终、可复核的过程工作；GPT-5.5 负责最终回答、最终审核和高风险决策。

适合交给 DeepSeek 的任务包括：

- 头脑风暴、提纲、改写、总结、抽取、翻译、示例。
- 有边界的辅助代码、样板代码、候选实现、测试数据草稿。
- 批处理或不着急的工作。

必须保留给 GPT-5.5 的任务包括：

- 最终回答、最终代码审核、release/publish/deploy 决策。
- 安全、凭据、认证、破坏性操作、生产环境变更。
- 高影响架构判断或正确性关键验证。

最终回复里要说明 DeepSeek 用了多少 token、估算节省了多少 Codex token，以及 GPT-5.5 做了哪些审核或验证。
