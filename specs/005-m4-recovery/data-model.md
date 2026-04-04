# 数据模型补充

## handoff 响应

- `handoff_file`：绝对或仓库相对路径字符串
- `summary`：摘要正文（markdown）

## resume 请求

- `mode`：string
- `handoff_summary`：string（可与文件内容一致）

## 任务状态扩展

- `handoff_in_progress` | `resuming` | `running` 迁移与 PRD §6.1 一致
