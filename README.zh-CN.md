<p align="center">
  <img src="assets/icon.svg" alt="Codex DeepSeek Token Saver" width="128" height="128">
</p>

# Codex DeepSeek Token Saver

[English](README.md) | [简体中文](README.zh-CN.md)

当前版本：**v2.3.0**。参见 [更新日志](docs/changelog.md)。

把低风险、非最终阶段的 Codex 工作委托给 DeepSeek，记录 DeepSeek token 用量，并估算节省了多少 Codex token。GPT-5.5 仍然负责审核和最终正确性。

这个项目适合希望用便宜长上下文模型承担草稿、批处理和探索工作的 agent，同时避免让这些草稿模型做最终决策。

## 为什么需要它

DeepSeek 很适合承担大量上下文和过程型工作，成本很低。但 Codex/GPT-5.5 仍然应该负责最终审查、安全检查和正确性把关。

这个仓库提供一个只依赖 Python 标准库的小 CLI，以及一个 Codex skill，把“DeepSeek 负责过程，GPT-5.5 负责最终审核”的边界写清楚。

## v2.3 新增内容

- 新增 `deepseek_reasonix.py`，让 Codex 可以先建 Agent Room、写 orchestrator brief、生成 Reasonix skill pack，再让 Reasonix 跑执行和自审，最后交回 Codex 做最终审核。
- 新增 Reasonix body mode，强制至少启用 implementer、tester、critic 三类子智能体；较大任务还可以加 docs 子智能体。
- 新增 `--skill-name`、`--skill-brief`、`--image-brief`，让 Codex 能把已触发 skill 的摘要和图片文字说明传给不支持多模态的 DeepSeek/Reasonix。
- 扩展 transcript 导出，room 事件现在会显示 Reasonix 的 artifact path、prompt path 和 transcript path，便于追溯。

## 路由策略

详细策略：[English](docs/routing-policy.md) | [简体中文](docs/routing-policy.zh-CN.md)

适合用 DeepSeek：

- 头脑风暴、提纲、改写、总结、抽取、翻译。
- 有边界的样板代码、候选辅助函数、示例、测试数据草稿。
- 批处理或不着急的工作，允许慢一点完成。

必须用 GPT-5.5：

- 最终回答、最终代码审核、发布/上线/部署决策。
- 安全、凭据、认证、破坏性操作、生产环境变更。
- 高风险或正确性关键的验证。

混合模式适用于 DeepSeek 先产出草稿，再由 GPT-5.5 审核。

## 快速开始

把 DeepSeek API key 存到 macOS Keychain：

```sh
read -s DEEPSEEK_API_KEY
security add-generic-password -U -a "$USER" -s codex-deepseek-api-key -w "$DEEPSEEK_API_KEY"
unset DEEPSEEK_API_KEY
```

运行一个草稿任务：

```sh
python3 deepseek_delegate.py \
  --phase draft \
  --out work/draft.md \
  "Draft three options for a small CLI README."
```

只检查路由，不调用 DeepSeek：

```sh
python3 deepseek_delegate.py --route-only --phase final "Review this release plan"
```

CLI 默认把 JSONL 日志写入 `.deepseek-token-saver/calls.jsonl`。

运行持久 DeepSeek worker：

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

运行 Agent Room 写作/审查/打回循环：

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

运行完整的 Codex orchestrator + Reasonix body 流程：

```sh
python3 deepseek_reasonix.py \
  --room-id overnight-room \
  --skill-name deepseek-token-saver \
  --skill-name diagnose \
  --skill-brief "Codex 已把任务路由为低风险实现工作。DeepSeek/Reasonix 负责大部分过程输出，但 Codex 仍会测试并做最终审核。" \
  --image-brief-file work/ui-brief.md \
  "创建一个 room，强制多智能体 Reasonix 执行，然后返回可供 Codex 最终审核的候选结果。"
```

这个模式适合“用户给一句话，房间里跑便宜多智能体流程，Codex 最后把关”的场景，目标是把 Codex token 占比压低。

导出最新 worker 或 room 的可读聊天记录：

```sh
python3 deepseek_transcript.py \
  --latest \
  --out work/deepseek-transcript.md
```

只生成 room、prompt 和 Reasonix skill pack，不真正调用 API：

```sh
python3 deepseek_reasonix.py \
  --room-id overnight-room \
  --dry-run \
  "只把房间和 prompt 搭好。"
```

## 输出示例

```text
Route: deepseek
Reason: low-risk non-final drafting/batch work is suitable for DeepSeek.
Review: GPT-5.5 must audit before final use.
DeepSeek tokens: 742 total (129 prompt, 613 completion)
Estimated Codex tokens saved: 519
```

节省值是粗略估算。它先估计如果让 Codex 直接完成草稿工作可能消耗多少 token，再乘以可配置比例。可以用 `--savings-ratio` 或 `DEEPSEEK_CODEX_SAVINGS_RATIO` 调整。

## 安装为 Codex Skill

把内置 skill 复制到 Codex skills 文件夹：

```sh
sh scripts/install_skill.sh
```

然后重启 Codex，让 skill 元数据重新加载。

## 安全规则

- 不要把 API key 粘贴到聊天、截图、GitHub issue 或 commit 里。
- 任何暴露过的 API key 都应立即撤销。
- DeepSeek 输出只作为草稿材料。
- GPT-5.5 必须审核最终代码、最终回答和公开发布步骤。
- DeepSeek durable memory 只能写入 Codex 审核过的经验，不能写入原始密钥、隐私上下文或未经验证的 transcript。

## 开发

运行本地检查：

```sh
sh scripts/preflight.sh
```

## 许可证

MIT
