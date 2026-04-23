# Plan：064-feishu-direct-delivery-runtime

1. 冻结 `WI-064` owner 边界与 formal docs。
2. 先写红测，锁定 Feishu outbound transport 与 app wiring 真值。
3. 实现 Feishu direct delivery client 与 transport 选择逻辑。
4. 跑 delivery / control-plane 受影响回归。
5. 回写 `ai_sdlc` 状态，并交给两个常驻对抗专家复审。
