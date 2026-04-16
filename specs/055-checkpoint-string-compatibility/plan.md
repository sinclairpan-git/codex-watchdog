# Plan：055-checkpoint-string-compatibility

## 目标

把 `WI-055` 收敛为 checkpoint YAML 字符串兼容性的 repo-side closeout：修当前文件、修未来 serializer、加回归测试和 repo-local gate。

## 实施原则

1. 严格遵循 `ai_sdlc`：先 formalize scope，再写 red tests，再做最小实现，再回写 formal memory。
2. 055 只处理 checkpoint 时间字段兼容性，不扩展到其它规则面。
3. 先让失败原因直指 YAML datetime 提升，再做最小修补。

## 工作流

### Phase 1：冻结 055 formal scope

- 从外部框架剩余 warning 恢复 055 的正式边界；
- 建立 `spec/plan/tasks/log` 与 `.ai-sdlc/work-items/055-*`；
- 固定 055 不处理其它 `.ai-sdlc` 文件的格式重写。

### Phase 2：先写 red tests 锁定 checkpoint 字符串兼容性

- 写失败测试锁定当前 checkpoint 兼容性 validator；
- 写失败测试锁定 serializer 输出必须给 ISO 时间字段加引号；
- 观察外部真值在修复前的警告。

### Phase 3：实现最小 validator 与 serializer 修复

- 增加 checkpoint 字符串兼容性 validator；
- 修复 `scripts/reconcile_ai_sdlc_state.py` 的 YAML scalar 序列化；
- 修正当前 checkpoint。

### Phase 4：跑 targeted / smoke 验证

- 运行 targeted tests；
- 运行 repo-local CLI；
- 使用外部框架真值复核 checkpoint 警告是否消失。

### Phase 5：完成 formal closeout

- 运行 fresh verification；
- 更新执行日志、summary、checkpoint 与 project-state；
- 明确 `next_work_item_seq=56`。
