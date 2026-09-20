# 文档导出子系统（write_pdf）设计 2026-09-21

状态：设计已对齐，待拆工单。本文是目标态与边界的唯一事实源；实现按 §9 切片推进。

## 1. 起因

对第三方 Desktop Commander MCP 做过一次必要性评估：它的 25 个工具与 Neurova 原生
`file_read/file_write/file_edit/file_list/file_search/exec_command/computer_shell`
高度重叠，按其自带 README，`allowedDirectories` 只限文件不限终端，防逃逸靠命令
blocklist —— 挂进本项目等于把一类系统操作从现有治理面（四级裁决 + AppContainer/
bwrap/Seatbelt 沙箱 + 人工审批 + (server,tool) 持久授权）挪到一个更弱的闸上。
结论是不接，只补它真正强于原生的两点：分页式检索（已于 2026-09-21 落在
`file_search`/`file_list` 的 `offset`/`next_offset`）与 PDF 出件。

PDF 出件展开后不是"一个工具"，而是"文档导出子系统"：Markdown/HTML 双入口、图片
内嵌、表格、页眉页脚模板、前端预览。

## 2. 已定决定（含取舍理由）

| # | 决定 | 理由与代价 |
|---|---|---|
| D1 | reportlab 自绘 + 中间文档树，不走无头浏览器打印 | 纯 Python wheel，Win/Linux/CI 一致，可嵌真实 TTF，服务端不需要浏览器。代价：CSS 只能支持我们自己定义的子集，做不到像素级保真 |
| D2 | 模板 = 内置 3 套预设 + 逐次参数覆盖 | 不新建"用户可编辑模板"存储与管理面。代价：改模板要动代码 |
| D3 | 图片：本地路径 / generations 内文件名 / http(s) 远程经 `persist_media` | 复用已审计的出网通道，不开第二条下载路径。代价：`write_pdf` 同时属 file 与 network 两类权限 |
| D4 | 无中文字体时退回 reportlab 内置 CID 字体，但必须在响应里显式报告 | 环境覆盖优先；同时守住"不出看起来成功的破件"这条纪律 |
| D5 | 前端只做被动预览 + 下载，用浏览器原生 `<embed>` | 零新依赖。代价：Firefox/Linux 无内置查看器时表现为下载而非内嵌显示，故下载按钮是必备兜底而非可选项 |
| D6 | 不提供任何主动"导出为 PDF"入口（本批） | 入口位置是产品决策，未定之前不铺 N 个页面 |

## 3. 事实基线（可核）

- 全仓无 PDF 生成：仅 `neurova/attachment_parser.py:88 _extract_pdf`（pypdf 读）；
  `requirements.txt:32 pypdf`、`:29 python-docx` 都是只读用途；reportlab/fpdf/
  weasyprint/markdown/bs4 均未安装。
- 产物落盘与鉴权：`neurova/llm/generators/runtime.py:37 GENERATION_OUTPUT_DIR`
  = `data/generations`；访问收口为鉴权路由 `neurova/api/endpoints/generation.py:741`
  （文件名白名单 `[A-Za-z0-9._-]+` 在 `:738`，属主反查，`?access_token=` 支持）。
  清理 `neurova/llm/generators/retention.py`，`NEUROVA_GENERATION_RETENTION_DAYS`
  默认 0（关）。
- 远程媒体统一入口：`runtime.py:205 persist_media`，内含出网 SSRF 校验与
  `data:` URI 分支；调用方 `generation.py:218`、`aigc_studio/services.py:315`、
  `collaboration/neurflow/drama_nodes.py:651`。
- 中文字体探测已有单一口径：`neurova/core/ffmpeg.py:198 _cjk_font_candidates()`、
  `:226 has_cjk_font()`，其注释写明"无中文字体时静默输出方框即假成功"。
- 产物 kind 分派是两份对齐表：后端 `neurova/api/endpoints/artifacts_api.py:44`
  `_KIND_BY_EXT`，前端 `NeurUI/src/utils/artifacts.ts:19`（注释显式要求同步）；
  两处都没有 `pdf` → 今天的 PDF 产物掉进 `text` 面板，按文本渲染二进制。
- 前端 dock 面板范式：`NeurUI/src/components/chat/dock/RightDock.vue:18-26` 分发，
  面板在 `dock/panels/`，i18n 键 `dock.download`、`chat.artifactUnavailable` 已存在，
  资源标签凭证由 `NeurUI/src/utils/genFiles.ts:11 withFileToken()` 统一追加。
- 长输出翻页在本仓已有同款约定：`neurova/builtin_tools.py:351 browser_read` 的
  `session_id/can_continue/next_offset`。本设计的 `offset`/`next_offset` 与之同风格。
- 后端无可复用的通用 Markdown 解析器：`api/endpoints/memory/markdown.py` 那套是
  记忆专用格式，不通用。

## 4. 模块边界

四个新文件，每个只承担一件事，依赖方向单向：

```
tool_executor._execute_write_pdf      参数校验 / 路径锚定 / 远程图取回 / 错误映射
        ↓
neurova/document_sources.py           Markdown 子集、HTML 子集 → 中间文档树（纯函数）
neurova/document_model.py             中间文档树的数据类 + 归一化（纯，无 I/O，不 import reportlab）
        ↓
neurova/document_pdf.py               树 → reportlab flowables + 字体注册 + 模板预设 + 字节输出
                                      （唯一 import reportlab 处）
```

判定可测性的标准：`document_model` 与 `document_sources` 在没有 reportlab 的环境里
也必须能跑；`document_pdf` 的字体与降级路径必须能在不装字体的机器上被断言。

## 5. 工具契约

`write_pdf`（注册进 `builtin_tools.py` schema、`tool_executor` 分派表、
`skills/permissions.py:31` 分类表）

输入：
- `content`（Markdown 子集）或 `content_html`（HTML 子集），**二选一必填**，
  两者同给或都不给 → 结构化错误，不做优先级猜测。
- `title?`：文档标题，进 PDF 元数据与页眉。
- `path?`：给定则相对锚定 agent 工作区（与 `file_write` 同一 `_workspace_base`
  口径），`..` 拒绝；缺省落 `data/generations/<slug>-<hash8>.pdf`，文件名必须过
  `generation.py:738` 的白名单（ASCII slug + hash，中文标题不参与文件名）。
- `template?`：`blank` | `report`（默认，页眉标题 + 页脚页码与日期）| `cover`
  （首页封面）。
- 逐次覆盖：`header_text?`、`footer_text?`、`page_number?`（默认 true）、
  `margin_mm?`（默认 18）。

输出：`{ file_path | download_url, file_name, bytes, pages, font: {mode, name},
warnings[] }`。`download_url` 形态 `/api/v1/generation/files/<name>`。

## 6. 渲染面（子集边界写死，不做"尽量支持"）

- Markdown 子集：`#`–`######` 标题、段落、`-`/`*` 无序列表、`1.` 有序列表、
  `**粗体**`、`*斜体*`、`` `行内码` ``、围栏代码块（渲染为等宽段落，不做语法高亮）、
  `> 引用`、`---` 分隔线、GFM 管道表格、`![alt](src)`。
- HTML 子集：`h1`–`h6`、`p`、`ul/ol/li`、`table/thead/tbody/tr/th/td`、`img`、
  `b/strong/i/em/code/pre/br/hr`。子集之外的标签**丢弃并计入 warnings**（列出被丢
  标签名），不静默吞。`<script>`/`<style>`/`<link>` 一律丢，`href` 不进 PDF。
- 表格：跨页时重复表头（reportlab `Table(repeatRows=1)`）；单元格内换行按段落处理；
  列宽按内容自适应，超出页宽时缩字号一次，仍超出则 warning + 截断内容而不是溢出页面。
- 分页：显式 `\newpage` 不支持；标题不孤悬页尾（`KeepWithNext`）。
- 图片：内嵌上限 20 张、单图 20 MB，超限的图**跳过并 warning**（宁可少图，不出半张
  破图）；读取失败的图降级为 alt 文本 + warning。
- 空输入、纯空白输入 → 错误而非出一份空白 PDF。

## 7. 字体与降级

- `core/ffmpeg.py:198` 的探测函数提为公开 `find_cjk_font()`，烧录与 PDF 共用一处
  口径（本设计唯一要动的既有函数）。
- 顺序：显式 `font` 参数 > 探测到的系统 CJK TTF（`TTFont` 真嵌入）> reportlab
  `UnicodeCIDFont("STSong-Light")`。
- 走 CID 时 `font.mode = "cid"` 且 `warnings` 必带一条：该路径不嵌字体，阅读器缺
  CJK 字库时会显示方框，建议安装中文字体或显式指定 `font`。`has_cjk_font()` 的
  既有教训就是"先探测再决定，不出假成功"。
- reportlab 未安装：工具返回结构化错误（写明缺哪个包），服务启动与其它工具不受影响
  （可选依赖 try/except 惯例）。

## 8. 前端（被动预览片）

- `stores/rightDock.ts:19` 加 `'pdf'`；`utils/artifacts.ts:19` 与后端
  `artifacts_api.py:44` **同批**加 `pdf` 分支（两份表的分叉就是本仓反复出过的事故面）；
  `DOCK_ICONS` 加 pdf 图标。
- 新建 `dock/panels/PdfPreviewPanel.vue`：`<embed :src="withFileToken(url)">` +
  标题栏 + 下载按钮（复用 `dock.download`）+ 错误态（复用 `chat.artifactUnavailable`）。
  下载失败必须落到可见错误态，**不照抄** `ImagePreviewPanel.vue:95-102` 的
  `catch {}` 静默。
- `RightDock.vue:18-26` 分发链加一行。
- 面板测试落在 `src/components/__tests__/`（dock 下没有 `__tests__` 目录，现有面板
  测试在 `components/__tests__/dockPanels.revoke.test.ts`）。
- 新 i18n 键数量目标为 0；若必须新增，11 份 locale + `locale-consistency.test.ts`
  与 `locale-key-reference.test.ts` 同步。

## 9. 切片顺序（供拆工单）

1. **示踪弹**：Markdown → 单页 PDF 出件，schema/分派注册齐（权限先归 `file` 单类，
   多归属在第 7 片改），缺省落 generations 并回 `download_url`，CID 降级带 warning。
   判据按字体条件分两支：探测到 CJK 字体的环境断言 pypdf 抽回中文正文；无中文字体的
   环境（CI 即此态）只断言 `pages >= 1` + `font.mode == "cid"` + warning 在场，
   **不断言可抽取**（CID 不嵌字体，抽取本身不可靠，拿它当通过判据会造出一条假绿）。
2. 表格 + 跨页表头 + 列宽降级 warning。
3. 图片内嵌：本地/`generations`/远程经 `persist_media`，超限与失败的 warning 分支。
4. HTML 子集解析（与 1 同一条渲染出口，不另开路径）。
5. 模板预设与逐次覆盖（页眉/页脚/页码/封面/边距）。
6. `path` 参数分支与工作区锚定、穿越防护。
7. `permissions.py` 多归属改造（file + network），带不变量测试。
8. 前端 `pdf` kind 双表 + `PdfPreviewPanel` + 下载兜底。

第 1 片必须先红后绿，且不得为省事把 2-8 提前塞进第 1 片。

## 10. 测试矩阵

- 纯函数单测：`document_sources`（Markdown/HTML 子集 → 树的形状，含被丢标签
  warning）、`document_model`（归一化：空输入、嵌套列表、表格对齐）。
- 渲染单测：`document_pdf`（页数、表格跨页表头、图片数量上限、CID 降级 warning、
  reportlab 缺席错误）。断言以 pypdf 读回的**页数与结构**为准，不以"字节非空"为通过
  判据；"中文正文可抽回"只在嵌入字体路径断言（见 §9 第 1 片的字体条件分支）。
- 工具端到端：`_execute_write_pdf` 的 path 锚定、`..` 拒绝、缺省落 generations、
  文件名过 `generation.py:738` 白名单、远程图失败降级。
- 既有不变量：`_BUILTIN_SCHEMAS ⊆ 分派表`（`tests/unit/tools/test_builtin_tools_expansion.py`
  已在守）、工具描述预算（`tests/unit/context/test_tool_descriptions.py`）、
  `agent_core.py` 尺寸棘轮不受影响（本设计不写进 agent_core）。
- 前端：面板渲染与下载失败的可见错误态（vitest）、i18n 两守卫、`vue-tsc`。
- 回归：`scripts/ci/protected_tests.txt` 全量复跑，新用例逐文件单跑全绿后登记。

## 11. 不在本子系统范围

用户可编辑模板的存储与管理面；HTML 全保真（浏览器打印路线）；pdf.js 自建渲染与
缩略图；页脚页码之外的复杂母版；DOCX/EPUB 等其它出件格式；聊天消息/知识库/记忆页
的导出入口；`data/generations` 的保留策略调整（现默认关，属另一题）。
