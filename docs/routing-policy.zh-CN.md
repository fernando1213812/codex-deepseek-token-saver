# 路由策略

[English](routing-policy.md) | [简体中文](routing-policy.zh-CN.md)

核心规则很简单：DeepSeek 可以在过程中消耗便宜 token；GPT-5.5 负责审核和最终正确性。

## DeepSeek

当任务低风险、非最终、容易复核时，用 DeepSeek：

- 起草文本或代码候选方案。
- 生成替代方案或示例。
- 对长输入做总结或抽取。
- 批量转换。
- 慢一点也没关系的后台工作。

## Skill 默认激活

对 Codex skill 路由来说，大部分项目型任务默认激活 `deepseek-token-saver`：
只要 DeepSeek 能先产出候选结果，而 Codex 能检查、测试、编辑或打回即可。典型场景包括小 app、网站、原型、辅助脚本、测试、文档、研究总结、issue 拆分、重构草稿、示例和批量编辑。

不要自动激活的场景包括：用户明确要求不用 DeepSeek、极短直接命令、密钥/auth/生产破坏性改动，以及需要高风险最终判断的任务。

## GPT-5.5

当任务高风险或处在最终阶段时，用 GPT-5.5：

- 给用户的最终回答。
- 最终代码审核或合并决策。
- 安全、认证、凭据、支付、法律、医疗、破坏性操作。
- 公开发布、release、部署或 GitHub 发布确认。

## 混合模式

混合模式表示：

1. DeepSeek 先产出候选结果。
2. Codex/GPT-5.5 审核候选结果。
3. Codex 编辑、测试、验证后，才能作为最终结果呈现。

实现类任务默认使用混合模式。

## Token 记账

如果 DeepSeek API 返回 `usage`，脚本会记录真实用量。
如果缺少 `usage`，脚本会根据文本长度估算 token。

估算节省的 Codex token：

```text
deepseek_total_tokens * savings_ratio
```

默认 `savings_ratio` 是 `0.70`。它只是一个粗略规划指标，不是账单。
