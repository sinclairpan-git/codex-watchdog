# Tasks: 079 State Resume Pack Canonical Sync

- [x] T791 审查 `WI-078` closeout 后遗留的顶层 state resume pack 漂移，并 formalize `WI-079` 的 contract 与状态入口。
- [x] T792 写失败测试，锁定顶层 `.ai-sdlc/state/resume-pack.yaml` stale pointer 与 CLI constraint gate 语义。
- [x] T793 实现顶层 state resume pack reconciliation validator，并接入 `ai_sdlc verify constraints` 主入口。
- [x] T794 把顶层 `.ai-sdlc/state/resume-pack.yaml` 同步到当前 active `WI-079` truth，清理实际漂移。
- [x] T795 跑 targeted verification、同步状态并完成 `WI-079` closeout。
