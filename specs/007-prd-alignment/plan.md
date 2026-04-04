---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 实施计划：007-prd-alignment

## 步骤

1. A 侧 `apply_steer` / `POST steer` 增加 `stuck_level`；Watchdog `post_steer` 与 `supervision` 传 `next_stuck_level`。
2. `handoff` 合并 `stuck_level: 4`。
3. `evaluate_stuck` 增加 `repo_recent_change_count`；`supervision` 在拉取任务后扫描 cwd。
4. `Settings.recover_auto_resume` + `recover_watchdog` 链式 `resume`。
5. 单测与 `config/examples` 更新；`research.md` 登记剩余偏差。
