# 研究记录：OpenClaw × Codex 双机会话监管系统

## 决策摘要

| 主题 | 结论 | 依据（PRD） |
|------|------|-------------|
| 控制面边界 | B 通过 A-Control-Agent 访问 Codex 能力，不暴露任意 shell | §4.3、§13.2 |
| 通信 | 内网 HTTPS + Token；A 机服务不暴露公网 | §13.1 |
| 卡顿信号 | 无 transcript/无文件变更/无测试输出增长组合判断 | §5.2、§8.1 |
| 审批 | 四级模型 L0–L3；L3 不得自动通过 | §7、§17.2 |

## 风险与开放项

- Codex app-server 实际事件字段名需在对接时以官方/现场文档为准，本阶段以 PRD 抽象为准。
- OpenClaw 与 Watchdog 的调用方式（独立 agent / 路由）由部署环境决定，本仓库交付 HTTP API 与配置样例。

## 参考资料

- `openclaw-codex-watchdog-prd.md`（V1.0，权威需求）
