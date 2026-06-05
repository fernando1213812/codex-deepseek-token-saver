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

## Subagent Use

Only spawn subagents when the current tool policy permits it and the user has
asked for delegation or parallel work. Give subagents bounded DeepSeek draft
tasks with disjoint write paths. The parent agent must audit the result.

## Final Report Template

Include:

- Route: DeepSeek / hybrid / GPT-5.5.
- DeepSeek tokens used: total, prompt, completion.
- Estimated Codex tokens saved.
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
