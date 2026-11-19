# agent-desktop 对照借鉴 · 可执行工单集（AD-1…AD-3）

> 2026-11-19 · 执行源唯一。上游输入：`vercel-labs/agent-desktop`（Rust，Apache-2.0，
> "Computer use CLI for AI agents"）对照研究——纯无障碍树路线（snapshot → ref → act →
> verify，无截图依赖），crates 分层 `core + PlatformAdapter → {macos AX, windows UIA,
> linux AT-SPI} + ffi`，CLI / C FFI / MCP stdio 三形态分发。
> 纪律依据 `AGENTS.md`：核心原则 4（基于事实）、修复教义第 2 条（净 LOC 默认 ≤ 0）、
> 第 3 条（先红后绿）、第 5 条（同根因全命中点扫荡）、第 6 条（单一事实源）、§2 断点条款
> （只写不读必须接线或删除）。

**编号空间声明**：本集 `AD-` 前缀，与 `2026-09-30-computer-use-repair-tickets.md`
（T-01…T-20）、`2026-10-02-computer-use-nonintrusive-tickets.md`（T-01…T-09）、
Issue #90 / #197 批次**不是同一编号空间**；跨文件引用一律带批次名。

## 0. 对照核实结论（先比后合的前提，均已逐行实证）

agent-desktop 的三项代表性设计 vs 本仓现状：

| agent-desktop 设计 | 本仓核实结论 | 结论 |
|---|---|---|
| 错误信封 `error.disposition.retry`（safe 才许重试） | **已落地**：`action_result.py:71-104` 的 retry 三值（reobserve/retry/never）+ `REFUSAL_RETRY_ADVICE` 全码映射 + `build()` refused 自动推导；`ToolExecutor._pixel_action_result`（tool_executor.py:2919）与沙箱/审核档拒绝路径均回灌模型；守卫 `tests/unit/computer_use/test_action_result_retry_contract.py` | **勿重复立项**；仅剩 AD-1 收尾 |
| 部分观察（partial observation：被切节点自标 completeness） | **缺口**：`desktop_uia.py:407-427` walk 对 `depth > max_depth` 静默剪枝，快照返回的 `truncated`（desktop_uia.py:122）只看节点数——depth 剪过的树照样报 `truncated=False`，模型会把残树当全貌 | **AD-2** |
| drill-down（`snapshot --root @ref` 从已观察元素下钻子树） | **缺口**：`computer_dom_snapshot`（builtin_tools.py:313）只有全量枚举，密集树只能反复调大 max_nodes 重全量 | **AD-3** |

另：本仓相对 agent-desktop 的既存优势不在本单范围——浏览器三后端（Playwright/Scrapling/camofox）、
SOM 视觉兜底、ActionResult 治理契约、远程会话平面（guest-agent/RDP/Sandbox/SSH）、前端观测面板。

## 1. 工单

### AD-1 `NEVER_RETRY_REFUSAL_CODES` 死码处置 + 台账补登 retry 语义 · 档 A · 无阻塞

**动机**：retry 三值语义（P1-2）已接线到模型可见面，但收尾不干净，两处残留：

1. `action_result.py:97-99` 的 `NEVER_RETRY_REFUSAL_CODES` 全仓**零消费**
   （`grep -rn NEVER_RETRY_REFUSAL_CODES neurova/ tests/` 仅命中定义行）——§2 意义上的
   只写不读断点。retry 语义的单一事实源是 `REFUSAL_RETRY_ADVICE`（build() 内部经
   `retry_advice_for` 消费）；消费方要封死非幂等盲重放，正路是读
   `action_result["retry"] == "never"`，不是再 import 一个派生集合。
2. `docs/CUA能力台账.md` 未登记 retry 语义（grep 零命中）——模型与 `/v1/computer/*`
   外部消费方能拿到 `action_result.retry`，台账却没有该词表的出处与口径。

**落点**：`neurova/computer_use/action_result.py:96-99`（删除 `NEVER_RETRY_REFUSAL_CODES`
及其注释）→ `docs/CUA能力台账.md`（补「retry 重试建议词表」小节：三值定义 + 全码映射表，
注明与 `REFUSAL_RETRY_ADVICE` 单源同步、守卫测试名）。

**红灯判据**：
1. 删除前实证断点：全仓 grep 该符号仅 `action_result.py:97` 一处（现状记录进提交说明）；
2. 删除后 `tests/unit/computer_use/` 全绿，且全仓 A/B（stash patch 法）零新增失败；
3. 台账补登后，`tests/e2e/cua_sim/test_capability_ledger.py` 仍绿；台账新增词表与
   `REFUSAL_RETRY_ADVICE` 逐码一致（人工核对 + 引用守卫测试名防两源漂移）；
4. 反向钉子：`test_action_result_retry_contract.py` 新增一断言——
   `REFUSAL_RETRY_ADVICE` 中 advice=="never" 的码集合非空（防将来把 never 清空使
   retry 语义退化）。

**净 LOC**：负（删 4 行 + 台账若干说明行；测试 +2）。

### AD-2 UIA 快照 depth 剪枝诚实上报 · 档 A · 无阻塞

**动机**：浏览器侧已有完整的截断诚实性纪律（`test_snapshot_truncation_honesty.py`：
规模字段必须进模型可见结果、未超限不加噪声字段、补救指引必须指向真实工具），桌面侧
`computer_dom_snapshot` 没有对齐。现状三处不诚实：

1. `walk`（desktop_uia.py:413-424）在 `depth > max_depth` 时直接 return，被剪子树
   无任何痕迹；`truncated`（:122）= `len(stored_elements) >= max_nodes`，depth 剪过的
   树返回 `truncated=False`——模型误以为看到全貌；
2. 被剪节点不自标（agent-desktop：每个被切节点知道自己被切，completeness 可从根走到边界）；
3. `max_depth` 参数给了模型「可控预算」的印象，实则截断结果不可见，等于盲赌。

**落点**：`neurova/computer_use/desktop_uia.py`
- `walk`（:407-427）：递归时统计 `observed_max_depth`、对 `depth == max_depth` 且
  仍有 children 的元素在 `el` 上标 `subtree_truncated: True`，返回
  `(elements, {"depth_truncated": bool, "observed_max_depth": int})`；
- `snapshot`（:83-125）：返回体在**确有剪枝时**追加 `depth_truncated` /
  `observed_max_depth`，并把 `truncated` 升义为「节点数或深度任一不完整」；
  完整树不带新字段（对齐浏览器侧「未超限就静」，防空上下文噪声）；
- `neurova/builtin_tools.py:316` `computer_dom_snapshot` description 补一句截断语义
  （`truncated/depth_truncated` 出现即须重观察或下钻，见 AD-3）；
- 测试：`tests/unit/computer_use/test_desktop_uia.py` 的 `FakeUIABackend.walk`
  （:60-62）现按 max_nodes 截断列表、不模拟 depth 剪枝——扩展 Fake 支持按
  max_depth 真剪，或新增 `test_desktop_uia_depth_honesty.py`。

**红灯判据**：
1. Fake 造 5 层深树，`snapshot(max_depth=2)`：断言现状返回 `truncated is False`
   且无 `depth_truncated`/`subtree_truncated` 字样 → 红灯实证「残树报全貌」；
2. 实现后同输入：`depth_truncated is True`、`observed_max_depth == 2`、
   depth-2 处仍有子代的元素带 `subtree_truncated`；无剪枝输入的结果体不出现新键；
3. 既有 `test_snapshot_budgets.py` / `test_snapshot_budget_honesty.py` /
   `test_desktop_uia.py` A/B 自证零新增失败（`truncated` 升义不得静默改既有断言）。

**净 LOC**：生产 +15 以内 / 删 0，测试 +40 左右；提交说明逐条列去向。

### AD-3 `computer_dom_snapshot` drill-down：按已快照元素下钻子树 · 档 A · 无阻塞

**动机**：密集树（浏览器内核应用、大型列表）在 max_nodes=400 预算下常被剪到关键区之外；
当前唯一补救是反复全量重快照并调大预算，token 与 UIA 枚举耗时双输。agent-desktop 的
drill-down（`snapshot --root @ref -i --compact`）证明「先骨架后下钻」是正确形态；本仓
AD-2 落地后，`subtree_truncated` 标记正好给模型指出「该从哪个元素下钻」。

**落点**：
- `neurova/computer_use/desktop_uia.py` `snapshot`（:83）加可选
  `root_index`/`root_runtime_id`：经 `_lookup_element`（:317）从当前 session 缓存定位
  元素（缓存元素保留 `_control` 私有键，可直接作 walk 根——以
  `{"_control": element["_control"]}` 伪窗口传给 `walk`，`walk` 签名不动）；
  root 元素不在当前缓存 → `refused ref_not_found`（对齐 agent-desktop「ref 归属
  snapshot，裸 ref 拒绝」）；
- 下钻结果**追加**进 `session["elements"]`（index 续接，不动既有元素 index；
  跳过 runtime_id 已存在的元素防重复），返回体带 `drilled_from`（root 的 index/
  runtime_id）与子树清单；`generation` 不递增（观察刷新非动作，与重复 snapshot 同口径）；
- `neurova/builtin_tools.py:317-325` schema 加 `root_index`/`root_runtime_id`
  参数与描述（下钻前先全量快照拿 root）；
- `neurova/tool_executor.py:7592-7606` `_execute_computer_dom_snapshot` 透传新参数；
- 测试：`tests/unit/computer_use/test_desktop_uia.py` 增 drill-down 组
  （Fake backend 支持 walk 指定根）。

**红灯判据**：
1. 现状：schema 无 `root_index`/`root_runtime_id`，传入即被忽略（返回仍是全量）→ 红；
2. 实现后：全量快照（预算内截断）→ 按某元素 `root_index` 下钻 → 返回仅该子树、
   新元素 index 续接、`click_element(runtime_id=新元素)` 可命中；
3. `root_index=99999`（缓存外）→ `refused ref_not_found` 且 `retry=reobserve`；
4. 同根因扫荡：`computer_click_element`/`computer_set_value` 已支持
   `runtime_id` 优先定位（builtin_tools.py:337,356），drill-down 新元素必须能走同一条
   `_lookup_element` 链，不得开第二套寻址（教义第 6 条）。

**净 LOC**：生产 +30 以内，测试 +50 左右。

## 2. 后置与待拍板（本批不展开）

| 项 | 说明 | 状态 |
|---|---|---|
| skeleton 折叠模式 | 密集树先只读「有名/可交互」骨架再下钻；浏览器侧 `foldSnapshotTree` 先例可平移 | P2 备选，AD-2/AD-3 落地后再评估 |
| macOS AX / Linux AT-SPI 桌面适配 | agent-desktop 实证三平台可走通；本仓桌面 GUI 仅 Windows（`availabilityDetail` 非 Windows 即 not-configured） | 大工程，需拍板立项 |
| CUA 独立 CLI/FFI/MCP 分发 | 让桌面能力脱离平台宿主被外部 agent（含 ACP 接入的外部编码代理）复用；本仓已有 `NEUROVA_CUA_MCP_EXPORT=1` MCP 导出 | 与 ACP 计划协同，待拍板 |
| 操作守则 skills 化 | 把「先观察后行动 / retry 纪律 / drill-down 用法」做成版本化内置技能（agent-desktop `skills get desktop` 同思路） | 依赖 AD-2/AD-3 落地后的词表定稿 |

## 3. 验证档说明

本机为 Windows：AD-1/AD-2/AD-3 均可走**档 A（本机活体）**——单测全绿 + 真后端
`computer_dom_snapshot → computer_click_element` 真链路自证（真窗口可用记事本/资源
管理器），证据进提交说明。`uiautomation` 为可选依赖（未入 requirements），活体验证前
先确认本机可导入，否则如实降级为档 B 并登记。

## 4. 执行记录（2026-11-19，全部完成）

| 单 | commit | 结果 |
|---|---|---|
| AD-1 | `d40f57a4c` | 删 `NEVER_RETRY_REFUSAL_CODES` 死码（-5）；台账补登 retry 词表（14 码全表）并顺带补齐 route 4 项/拒绝码 3 项（test_capability_ledger 两个预存失败转绿，15 passed）；新增反向钉子 test_never_advice_non_empty（retry 守卫 8 passed） |
| AD-2 | `a31d46ead` | walk 返回 (elements, stats)：depth_truncated/observed_max_depth，被切元素自标 subtree_truncated；snapshot truncated 升义、未超限不加键；computer_dom_snapshot 描述补截断语义。红灯 1 failed→绿灯 53 passed，全域 786 passed 零新增 |
| AD-3 | `e5bad7a07` | drill-down（root_index/root_runtime_id，ref 归属快照、index 续接、代次不递增、标记解除）；同签名扫荡 remote_backend + guest server。红灯 5 failed→绿灯 5 passed，全域 791 passed 零新增 |

**live-verify（真 UIA 活体，真窗口 `API资料.txt - Notepad`）**：max_depth=1 →
truncated=True / depth_truncated=True / observed_max_depth=1、7 元素自标被切；
root_index=1 下钻 → drilled_from={index:1, runtime_id:42.11339896}、子树 [7][8][9]
index 续接；max_depth=32 完整树 truncated=False 无噪声键；click_element("文件") →
success=True / route=uia / effect=confirmed。台账 desktop:uia 行 gap 已按此更新
（set_value 真机仍 gap）。验证期间临时安装 `uiautomation`（仅本机环境，未入 requirements）。

