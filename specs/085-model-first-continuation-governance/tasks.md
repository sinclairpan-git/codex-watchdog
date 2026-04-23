# Tasks：085 Model First Continuation Governance

- [x] T851 formalize `WI-085` owner、spec/plan/tasks 与 `.ai-sdlc` active state，对齐当前 branch、checkpoint、resume-pack 与 project-state。
- [x] T852 冻结 `PCDI` authoritative snapshot contract、continuation decision v3 schema 与 project / branch / progress truth 输入面回归。
- [x] T853 实现 project-level execution state、pending approval hard gate、terminal suppression 与 fallback packet reuse invalidation，确保 non-active/approval-blocked 项目立即无条件失效旧 continuation identity、route、packet 与 replay 资格。
- [x] T854 实现 lineage / provenance 写面，强制记录 gate verdict、suppression reason、identity/token issuance / consume / invalidate、packet generation 与 replay invalidation，保证后续行为可审计、可回放。
- [x] T855 在硬门与 lineage 就位后实现 `ContinuationEligibilityGate`、`ContinuationRoutingGate`、`continuation_identity`、`branch_switch_token` 的单次消费状态机，明确 `issued / consumed / invalidated / consumed_at`，并对重复消费做 suppress。
- [x] T856 实现 operator control-plane projection，显式投影 `continuation_identity`、`identity_state`、`token_state`、`consumed_at`、`route_key`、`packet_id/hash`、`rendered_from_packet_id/hash`、`last_dispatch_result`、`suppression_reason`、`decision_source`、`snapshot_version` 与 unified advisory/dispatch cooldown。
- [x] T857 实现 `ContinuationPacket` 真值对象与 packet->markdown/adapter summary 的严格单向渲染契约，并把 runtime-side handoff markdown、Watchdog recovery/resume、adapter summary 全部切到 packet truth，禁止渲染结果回流为 `latest-summary`、`PCDI`、routing input、dedupe 输入或模型输入。
- [x] T858 跑 targeted runtime/integration/full verification，确认系统能正确区分 continue current branch / recover current branch / branch complete switch / project complete / await human / blocked，且已停止项目不再重复发 summary。
