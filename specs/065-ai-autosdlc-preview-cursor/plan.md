# Plan：065-ai-autosdlc-preview-cursor

1. 冻结 `WI-065` owner 边界与 formal docs。
2. 先写红测，锁定 `ai-autosdlc-cursor` 的 stage-aware packet 与 goal conflict 降级语义。
3. 实现 preview contract 输入输出模型与 `MemoryHubService.ai_autosdlc_cursor()`。
4. 跑 `Memory Hub` / `Goal Contract` 相关 targeted 回归。
5. 回写 `ai_sdlc` 状态，并交给两个常驻对抗专家复审。
