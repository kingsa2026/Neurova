# 004 HTML 子集入口

**Blocked by**: 001、002、003

> 为什么不止阻塞 001：HTML 子集里含 `table` 与 `img`，若不同批具备表格与图片渲染，
> 这张工单就会顺手再实现一遍出口 —— 那是分叉，不是切片。

## 目标
`content_html` 与 `content` 汇入同一棵中间树、同一条渲染出口，不另开第二条 PDF 路径。

## 涉及层
- [ ] 逻辑层：`document_sources.parse_html`（stdlib `html.parser`，零新依赖），
      子集见 spec §6：`h1`-`h6`/`p`/`ul`/`ol`/`li`/`table…`/`img`/`b`/`strong`/`i`/`em`/
      `code`/`pre`/`br`/`hr`
- [ ] 安全：`<script>`/`<style>`/`<link>`/`<a href>` 一律丢弃（`href` 不进 PDF），
      被丢标签名计入 `warnings`；嵌套畸形标签不崩
- [ ] 工具层：`content_html` 走此解析器，其余（落盘、字体、模板、图片）与 001 共用
- [ ] 测试：`tests/unit/document/test_document_sources.py`

## 验收标准
- 同一段内容分别以 Markdown 与 HTML 传入，pypdf 抽回的正文文本归一化后相等
- 含 `<script>alert(1)</script>` 的输入：PDF 出件、正文无该文本、`warnings` 点名被丢标签
- 未闭合 `<p>` 等畸形输入不抛异常
- `content` 与 `content_html` 同给 → 结构化错误（001 已定，不得在此放宽）
