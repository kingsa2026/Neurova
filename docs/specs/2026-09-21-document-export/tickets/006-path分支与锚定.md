# 006 path 分支与工作区锚定

**Blocked by**: 001

## 目标
`write_pdf(..., path="reports/月报.pdf")` 落在 agent 工作区内并可被 `file_read` 读回；
越界路径被拒。

## 涉及层
- [ ] 工具层：`path` 给定 → 相对锚定 `_workspace_base()`（与 `file_write` 同口径），
      `..` 与绝对路径逃逸拒绝；父目录不存在时创建
- [ ] 工具层：`path` 缺省 → 保持 001 的 generations 行为，两分支响应字段不同但都带
      `bytes/pages/font/warnings`
- [ ] 测试：`tests/unit/tools/test_write_pdf.py`

## 验收标准
- 相对路径出件后 `file_read` 能读到同一文件且 `%PDF` 头一致
- `path="../../evil.pdf"` → `error`，磁盘上不产生该文件
- 写在工作区根之外（绝对路径逃逸）→ `error`
- 不给 `path` 时仍返回 `download_url`，给了 `path` 时返回 `file_path`（不互相冒充）
- 落盘失败（只读目录等）→ `error` 带原因，不返回半个成功响应
