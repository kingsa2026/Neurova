# CUA Phase 3 主体立项：SOM 视觉复活 / MCP 双层导出 / 附身授权与动作审计

> **交付状态（2026-09-12 实施）**：R3-4a 桌面动作审计 ✅（`security/desktop_audit.py` + 分发咽喉点 + `/governance/desktop-audit`，12 测绿）；R3-4b profile 附身授权 ✅（`security/profile_grant.py` fail-closed 门 + 审批铸造钩子 + `/governance/profile-grants`，12 测绿）；R3-3 双层 MCP 导出 ✅（`mcp_server.py` 工具面 computer_* + agent 面 run_computer_task，默认关 `NEUROVA_CUA_MCP_EXPORT`，7 测绿）；R3-1 SOM ✅（`computer_use/som.py` 确定性检测器+稳定编号+id2xy，`computer_som_snapshot`/`computer_click_mark` 两工具，纪律段阶梯更新，吸收清理删 vision*.py 三模块+失效集成测试，12 测绿 + 真机 60 区域探测过）。详见 [[neurova-cua-phase3-rs-implementation]]。

> 立项日期：2026-09-12
> 来源：docs/Neurova_CUA升级方案_2026-09-12.md 第 5 节（远期选项，独立立项，不在本批）
> 性质：能力扩展立项（非缺陷修复）——净 LOC 为正，验收看能力可达 + 不回归既有 Phase 0-2 行为
> 前置：Phase 0-2 已交付（ActionResult 契约 / 观察优先协议 / desktop_uia 语义层 / 五档点击递降链 / 截图元数据 / CUA 使用纪律段 R3-5 已完成）
> 关联代码：neurova/computer_use/（vision*.py、action_result.py、actions.py、desktop_uia.py）；neurova/tool_layers/mcp_server.py；neurova/computer_use/camofox_server_backend.py、camofox_supervisor.py；neurova/security/governance.py

---

## 0. 立项范围与已完成项

本节把方案第 5 节的 R3-1/3/4 拆为可独立排期、独立验收的三张工单；R3-2 已并入远程会话平面立项（另见 `docs/Neurova_CUA_远程会话平面立项_2026-09-12.md`）；R3-5 已于 2026-09-12 收口（`neurova/context/rules_sections.py::build_computer_use_rules_section`，17/17 测试绿），本立项书不再列。

三张工单**互不依赖，可并行或按触发条件各自择机**——这正是"远期选项"的含义：没有共同前置，谁先撞到真实需求谁先开工。

---

## 1. R3-1 — SOM 视觉复活（Set-of-Marks 编号标注）

### 1.1 现状（2026-09-12 实测锚点）

- `neurova/computer_use/vision.py / vision_lite.py / vision_basic.py` 三个视觉模块**全链零生产消费方**（grep 除自身目录外无任何 import），已在模块头挂 R1-6 弃用注记"禁止新代码引用"（`vision.py:11`）。
- 当前桌面语义完全来自 **UIA（desktop_uia.py）**：控件树快照 + 按 index 语义操作。对有 a11y 树的 Win32/UWP/Chromium 应用覆盖良好。
- **盲区**：自绘 UI（游戏、Canvas/WebGL、部分 Electron、远程桌面像素流、Photoshop 类画布）不暴露 UIA 树 → dom_snapshot 返回空/稀薄 → 只剩像素兜底 computer_click，回到"盲猜坐标"。

### 1.2 问题定性（为什么要独立立项）

| # | 触发场景 | 现状缺口 |
|---|---|---|
| S1 | 无 a11y 目标的桌面任务（游戏/自绘 UI/远程桌面） | 只能像素兜底，成功率低、无稳定寻址 |
| S2 | dom_snapshot 稀薄时缺中间档 | UIA→像素 之间没有"视觉标注"过渡 |

**非触发（不要顺手做）**：只要目标应用有可靠 UIA 树，dom_snapshot 严格优于 SOM（结构化、无推理成本、坐标精确）——SOM 不是替代，是补最后一档。

### 1.3 目标与非目标

**目标**
1. OmniParser 式 **SOM 管线**：截图 → 可交互区域检测（YOLOv8 图标 + OCR 文本框）→ 在原图上画**编号标注框** → 回传编号标注图给 VLM + `id2xy` 映射表（id→中心坐标）。
2. Agent 在快照稀薄轮用 SOM 图：看编号图说话 → `computer_click_mark(id=N)` → 后端 id2xy 解成像素坐标走既有点击链（复用 R0-2 坐标换算 + 五档递降）。
3. 吸收 `vision*.py`：把其中可复用的 YOLO/OCR 加载逻辑并入新 SOM 模块，删除三份旧实现（净减）。
4. **历史截图一致性**：同一会话内编号跨轮稳定（对同一界面重复标注返回相同 id），防"上一轮说 3 号按钮，这一轮 3 号变了"。

**非目标**
- 不改 UIA 主链（dom_snapshot 仍是第一优先）。
- 不追求实时视频流标注（按需截图标注）。
- 模型权重下载沿用现有 ModelScope/hf-mirror 三引擎机制，不新造下载器。

### 1.4 方案草案（分三阶段）

**阶段 1：SOM 核心 + id2xy（2-3 天）**
- 新 `neurova/computer_use/som.py`：`mark_screenshot(png_bytes) -> {annotated_png_b64, marks:[{id, bbox, center, label}], id2xy}`。检测器优先级：可选 ONNX 图标模型（本地已有 YOLO 栈）→ 退化到纯 OCR 文本框 + 轮廓启发式（vision_basic 的轻量路径移植）。
- 编号跨轮稳定：以 `hash(center_grid + role + normalized_label)` 为 id 种子，同界面命中同 id（TDD 红测：同图两次标注 id 一致）。
- 验收：单测覆盖 id2xy 往返（标注图上的 id ↔ 屏幕点）、编号稳定、无 OCR 依赖时的降级路径。

**阶段 2：工具面接入（1 天）**
- 新工具 `computer_dom_snapshot` 的姊妹：`computer_som_snapshot`（返回编号图 base64 + marks 摘要）；`computer_click_mark(index=N)` 复用 actions 点击链。
- builtin_tools 描述接入既有阶梯："dom_snapshot 稀薄（节点数 < 阈值）时才 som_snapshot"。
- **纪律段同步**：`build_computer_use_rules_section` 阶梯补 SOM 档（观察→UIA 语义→**SOM 视觉语义**→像素兜底）。
- 验收：工具 schema 契约测试（能力台账同型机械校验）。

**阶段 3：吸收清理 + 评测（1 天）**
- 迁移 vision*.py 可复用件，删三份旧模块。
- 评测台（R2 交付的 simulated 基座）补一个"自绘 UI"假桌面用例：只给 SOM 图，agent 须点中目标编号（reward==1.0 行为断言）。
- 全量回归：tests/unit/computer_use/ 基线差分零新增。

### 1.5 风险与缓解

| 风险 | 缓解 |
|---|---|
| YOLO/OCR 依赖体积与启动慢 | 懒加载 + 缺权重时降级到 OCR-only；沿用现有模型下载门控 |
| 编号图占上下文（base64 大） | 复用既有图像留存策略（keep last N image rounds）；标注图按需生成非每轮 |
| VLM 对编号图识别不稳 | simulated 评测先验；不稳则回退像素兜底（既有下限不破） |

### 1.6 触发条件（何时真正开工）
真实出现"无 UIA 树的可交互桌面"任务需求时启动；否则三份 vision 保持弃用注记挂账，不占排期。

---

## 2. R3-3 — CUA 双层 MCP 导出

### 2.1 现状（2026-09-12 实测锚点）
- `neurova/tool_layers/mcp_server.py` 已有协议无关核心：`list_tools()`（:38）/ `call_tool()`（:82），当前导出的是 **skill**（`_call_skill`）。
- `computer_*` 工具（screenshot/click/type/scroll/dom_snapshot/click_element/set_value/shell）目前**只走内部 tool_executor 直调**，未对任何外部 MCP 客户端暴露。
- 记忆在案：另一线程正在重构 MCP 模块（已删 mcp_client_manager.py），tool_layers API 面存在鉴权/隔离历史问题（升级审计 P0）。

### 2.2 问题定性
外部 agent 生态（任意 MCP 客户端）若想复用 Neurova 的 computer-use 能力，当前无入口。但**桌面动作是高权限、有副作用的对外操作**，裸导出 = RCE 面。

### 2.3 目标与非目标
**目标**
1. **工具面 MCP**：`list_tools` 追加 `computer_*` 全量 schema，`call_tool` 路由到既有 tool_executor dispatch（不复制实现）。
2. **Agent 面 MCP**：单个粗粒度工具 `run_computer_task(goal)` → 内部起一轮 agent 循环（复用 ChatPipeline），面向"把整台机器当工具"的外部编排。
3. **导出即受治理**：经 MCP 进来的 computer_* 调用**必须走与内部完全相同的 governance/approval 闸门 + ActionResult 回执**，且身份隔离沿用 ContextVar `_current_user_id`（见 mcp_server.py:123）。默认关，白名单开。

**非目标**
- 不在 MCP 层重写任何桌面动作逻辑（单一实现源）。
- 不导出绕过审批的"快速通道"。

### 2.4 方案草案（依赖 MCP 重构收口后）
1. 前置：等 MCP 模块重构线程合入（记忆 `neurova-mcp-revamp-neurflow-readapt`），本工单开工前 rebase。
2. 注册表：computer_* 工具描述复用 builtin_tools 单一来源（禁复制 schema）。
3. 鉴权：MCP 传输层接入 S-08 全局鉴权白名单（`NEUROVA_GLOBAL_AUTH`），computer 工具默认 DENY，显式 grant 才导出。
4. 审计：每次导出调用落动作审计（见 R3-4）。
5. TDD：契约测试——外部 MCP `call_tool("computer_click")` 触达的审批/隔离/ActionResult 与内部直调逐字节等价；未 grant 时 403。

### 2.5 风险
| 风险 | 缓解 |
|---|---|
| 高权限动作对外暴露 | 默认关 + 白名单 + 全量治理闸门；导出仅"同一已认证用户自己的会话" |
| 与并行 MCP 重构冲突 | 开工前 rebase + 契约对齐评审 |

---

## 3. R3-4 — camofox 附身授权 + 桌面动作审计

### 3.1 现状（2026-09-12 实测锚点）
- `camofox_server_backend.py / camofox_supervisor.py` 提供登录态浏览器隔离；camofox 用户 profile 携带**真实网站登录态**。
- 治理审计：`governance.py / governance_settings.py` 管 RSI 阶段与规则门控，**尚无桌面动作级审计存储**。
- 缺口：agent 可用带登录态的 profile 以用户身份对外操作（发帖/下单），无"使用前显式授权"；桌面动作无审计留痕。

### 3.2 目标与非目标
**目标**
1. **附身授权**：camofox 登录态 profile 被某次任务引用**前**，向用户显式弹 grant（复用 approval 状态机），记录"用户 X 于时刻 T 授权 agent 以其 profile 操作站点 Y"，可作用域限定（本次任务/本次会话/长期）。
2. **动作审计**：所有 `computer_*` 动作（本地+远程+MCP 导出）落**元数据白名单审计**——时间、用户、工具名、目标窗口/URL host、ActionResult 的 effect/route/delivery/refusal_code、耗时。**永不存截图 base64、永不存键入文本内容**（隐私红线）。
3. 审计可查询（按用户/时间/工具/host/是否需人工），前端接现有错误上报/审计看板形态。

**非目标**
- 不做键入内容回放（隐私 > 可观测）。
- 不新增独立审计栈，复用现有 JSON/SQLite 持久化模式。

### 3.3 方案草案
1. 授权：`security/approval` 状态机加 `profile_grant` 决策类型；调用点在 profile 绑定处（camofox_backend 取 profile 前），fail-closed（无 grant 即拒，不静默降级）。
2. 审计：`neurova/security/desktop_audit.py` 新模块，SQLite 表 `desktop_action_audit`，写入点在 ActionResult 生成后统一 choke point（一处写，覆盖三入口：tool_executor/actions/mcp_server）。
3. 隐私白名单：字段级 allowlist（机械测试：截图/键入文本永远不是列）。
4. TDD：grant 未授→动作拒；grant 作用域到期→拒；审计行不含任何图像/文本内容列；三入口各产一条审计。

### 3.4 风险
| 风险 | 缓解 |
|---|---|
| 审计表膨胀 | 元数据行小；滚动 TTL + 归档，沿用现有清理心智 |
| grant 疲劳（频繁弹窗） | 作用域可选"本会话"减少打断；敏感 host 才强制"本次" |

---

## 4. 排期与优先级建议

| 工单 | 优先级 | 前置 | 触发即开工 |
|---|---|---|---|
| R3-4 附身授权+审计 | **最高**（安全/合规，且 R3-3 导出依赖它兜底） | 无 | 若已有 camofox 对外操作或 MCP 外部接入 |
| R3-3 MCP 双层导出 | 中 | MCP 重构合入 + R3-4 审计 | 外部 agent 生态需求出现 |
| R3-1 SOM 视觉 | 低（最重投入） | 无（依赖已就绪的 actions/坐标链） | 无 UIA 树桌面任务真实出现 |

依赖链：`R3-4 → R3-3`（导出必须先有审计护栏）；`R3-1` 独立。三者均与已交付 Phase 0-2 无冲突，属纯增量（符合"只提升不下降"约束）。

## 5. 验收总则
- 每张工单独立 TDD（先红后绿），带防回归用例。
- 合入前跑 tests/unit/computer_use + tests/unit/security + tests/unit/api 基线，零新增失败。
- 不破坏 R3-5 纪律段：任何新工具接入须同步更新 `build_computer_use_rules_section` 阶梯。
