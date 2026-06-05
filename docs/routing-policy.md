# Routing Policy

[English](routing-policy.md) | [简体中文](routing-policy.zh-CN.md)

The core rule is simple: DeepSeek can spend cheap tokens during the process;
GPT-5.5 owns review and final correctness.

## DeepSeek

Use DeepSeek when the work is low-risk, non-final, and easy to review:

- Drafting text or code candidates.
- Generating alternatives or examples.
- Summarizing or extracting from long inputs.
- Batch transformations.
- Slow background work where latency is acceptable.

## Default Skill Activation

For Codex skill routing, activate `deepseek-token-saver` by default for most
project-shaped work when DeepSeek can produce a candidate and Codex can inspect,
test, edit, or reject it. This includes small apps, websites, prototypes,
helper scripts, tests, docs, research summaries, issue breakdowns, refactor
drafts, examples, and batch edits.

Do not auto-activate when the user explicitly opts out, the request is a tiny
direct command, the work involves secrets/auth/destructive production changes,
or the turn requires high-stakes final judgment.

## GPT-5.5

Use GPT-5.5 when the work is high-risk or final:

- Final answer to the user.
- Final code review or merge decision.
- Security, auth, credentials, payments, legal, medical, destructive actions.
- Public posting, release, deployment, or GitHub publishing confirmation.

## Hybrid

Hybrid means:

1. DeepSeek produces a candidate.
2. Codex/GPT-5.5 reviews the candidate.
3. Codex edits, tests, and verifies before presenting it as final.

This is the default for implementation tasks.

## Token Accounting

DeepSeek API usage is recorded when the API returns `usage`.
If usage is missing, the script estimates tokens from text length.

Estimated Codex tokens saved:

```text
deepseek_total_tokens * savings_ratio
```

The default `savings_ratio` is `0.70`. It is a rough planning metric, not an
accounting bill.
