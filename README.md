<p align="center">
  <img src="assets/icon.svg" alt="Codex DeepSeek Token Saver" width="128" height="128">
</p>

# Codex DeepSeek Token Saver

[English](README.md) | [简体中文](README.zh-CN.md)

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

## Development

Run local checks:

```sh
sh scripts/preflight.sh
```

## License

MIT
