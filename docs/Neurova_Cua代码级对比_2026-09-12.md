# Neurova × trycua/cua 代码级对比报告

> 日期：2026-09-12
> 对象：[trycua/cua](https://github.com/trycua/cua)（下称 Cua，MIT，≈4,800 文件；Rust cua-driver + Python 单仓 SDK + Swift lume + Go fleet 后端 + cua-bench）
> 我方：`neurova/computer_use/` + 浏览器栈 + 治理链（同 [OpenComputerUse 对比报告](Neurova_OpenComputerUse代码级对比_2026-09-12.md) 的基线）
> 结论速览：**Cua 与 OCU 定位不同——OCU 是"一个桌面 CUA 工具面"，Cua 是"计算机使用基础设施全栈"（驱动/VM 池/云桌面/评测/训练）。对 Neurova 最有价值的不是它的工具面（OCU 已覆盖），而是四个工程范式：① ActionResult 封闭结果契约（诚实性协议化）；② 证据台账式的能力支持矩阵；③ agent 循环的回调管线（图片保留/预算/动作归一化）；④ 评测即任务环境（cua-bench，simulated 模式零 VM 可跑）。共提炼 14 条改进项，其中 6 条与 OCU 清单互补升级。**

---

## 1. Cua 全景速览

| 支柱 | 位置 | 是什么 |
|---|---|---|
| **cua-driver** | `libs/cua-driver/`（Rust） | 宿主机侧"后台"驱动：MCP over stdio，驱动原生 app **不抢焦点**；AX（语义）/PX（像素）双寻址；权限三模式 standard/bounded/unrestricted（deny-by-default，YAML+Rego 策略，启动期固化）；内嵌技能包（MCP skills 扩展分发）；加密"计算机历史"（元数据白名单，永不存截图/键入文本） |
| **python SDK** | `libs/python/`（≈107k 行） | `cua_computer`（Computer 客户端，VM 提供方 lume/lumier/docker/cloud/winsandbox）+ `computer_server`（**来宾内守护进程**：WS `/ws` + REST `/cmd` + MCP `/mcp` + PTY + playwright_exec，≈40 个 computer_* 工具）+ `cua_sandbox`（E2B 风格 SDK，12 种 transport）+ `cua_agent`（ComputerAgent 循环库）+ `cua_som`（OmniParser 视觉定位） |
| **VM 基建** | `libs/lume`、`lumier`、`qemu-docker`、`xfce` | Apple Virtualization.framework 本地 macOS/Linux VM（:7777）；Docker 化 macOS + noVNC；QEMU/KVM 容器跑 Windows/Linux/Android（QCOW2 overlay 秒级重置）；无 KVM 的 XFCE 容器（computer-server :8000） |
| **Fleet** | `libs/fleet/`（Go+Rust） | 多租户 K8s 云桌面控制面：预热池（WarmPool）+ 声明式 Claim，SDK 拿到即用 |
| **cua-bench** | `libs/cua-bench/`（259 文件） | 评测体系：任务=Python 环境目录（4 装饰器：tasks_config/setup_task/solve_task/evaluate_task），simulated 提供方（**Playwright HTML 桌面，零 VM 零 Docker**）+ native 提供方（真实 OS 容器）；轨迹导出 HF Dataset → GUI-R1/AgUVis 训练格式 → GRPO RL 训练环 |

## 2. 三方定位对比

| 维度 | Neurova | OCU | Cua |
|---|---|---|---|
| 形态 | 服务内嵌模块 + REST/WS + 前端面板 | 独立 MCP/CLI，单用户 | 基础设施全栈：驱动 SDK/VM/云/评测 |
| 桌面控制 | 全屏截图+pyautogui 盲点击 | a11y 树 + element index，非侵入 | a11y/UIA 语义 + PX 双寻址，后台投递 + **结构化拒绝码** |
| 浏览器 | Playwright/camofox 双后端（强） | 无 | driver 内嵌 browser 工具（CDP，可附已登录 profile） |
| 隔离 | 进程内沙箱（AppContainer 等） | 无（宿主机直跑） | **VM/容器级整机隔离**（Winsandbox 强制临时存储） |
| 动作结果 | success 布尔 + 元数据 | 降级文案（文本） | **封闭契约**：effect/route/delivery/evidence/escalation |
| 能力边界 | 代码即事实，无台账 | 文档纪律 | **证据台账**：delivered/refused/gap 逐格 fixture 证明 |
| 评测 | 无 | agent-smoke 场景 | **cua-bench**：奖励函数+轨迹导出+RL 训练 |
| 治理 | governance→sandbox→approval（强） | env 门控 | 权限三模式 + capability manifest + Rego |

## 3. Cua 独有的四个工程范式（OCU 没有的）

### 3.1 ActionResult 封闭契约 ⭐ 本报告最有价值单点
`libs/cua-driver/docs/action-result-contract.md`：0.15 版把两件事拆开——**动作做了什么**（ActionResult）与**后置条件是否满足**（VerifyStateOutput，由调用方定义、驱动只报告 satisfied/unsatisfied/unknown）。每个成功动作返回**封闭** `structuredContent`：

```json
{"effect":"confirmed","route":"accessibility","delivery":{"mode":"background"},
 "evidence":[{"kind":"value_readback"}]}
```

- `effect`: confirmed / partial / unverifiable / **suspected_noop** / refused
- `route`: accessibility / synthetic_events / global_input / dom / trusted_input
- `delivery.mode`: background / foreground / not_applicable / unknown
- `evidence`: value_readback / window_change（confirmed 必须带证据；refused 不得带 delivery/evidence）
- `escalation`: 升级阶梯（target: pixel/foreground/page/session + reason）

不变式由契约强制：`confirmed` 必须有可发布的 readback/window-change 证据。**OCU 的"诚实降级文案"在这里被形式化为机器可读协议**——agent 可以编程地知道"这次点击可能没生效（suspected_noop），该重新观察或升级路径"。

**Neurova 现状**：`BrowserResult`/computer 工具结果只有 `success: bool` + 数据字段，路由/投递模式/证据全无；`suspected_noop` 这类"动作执行了但可能没效果"状态完全不存在——假成功问题（camofox 静默失配）在这里有协议级解法。

### 3.2 动作支持台账（证据驱动的能力矩阵）
`libs/cua-driver/docs/action-support.md`：每个"平台 × harness（WPF/WinUI3/Electron/Tauri/WKWebView/GTK3…）× 动作 × AX/PX"格子都标注 delivered / refused（精确拒绝码）/ gap，且**必须由 fixture 拥有的状态变化 + 焦点/z 序/无输入泄漏 oracle + 录像证据**支撑，CI 按 CaseSpec 行跑（Windows 122/122、Linux X11 116/116、Sway 116/116 全过）。关键原则写在开头："A missing row is never evidence that an action is impossible."

**Neurova 现状**：能力边界散落在代码注释和 /status 占位字段（`vision_available: False` 硬编码），测试只验证"不崩"不验证"投递生效"。无须照搬全套（Cua 为此建了 GUI fixture 应用矩阵），但**按后端建立"投递路径 × 后果验证"的最小台账**（哪怕只是测试断言点击后 fixture 状态变了）就能消灭"假绿"。

### 3.3 Agent 循环的回调管线（直接可抄进 Neurova 聊天管线）
`cua_agent`（`libs/python/agent/`，~27k 行）的循环库模式：

- **`OperatorNormalizerCallback`**（`callbacks/operator_validator.py`，永远第一个装）：把模型产出的畸形动作归一化后才执行（`left_click`→`click`+button、`hotkey`→`keypress`…）。Neurova 的 `tool_executor` 对 LLM 产出参数是直接分发——同样需要"执行前归一化/校验层"（HTTP 侧已有 `extra="forbid"`，agent 侧没有）。
- **`ImageRetentionCallback`**（`callbacks/image_retention.py:40`）：历史里只保留最近 N 张截图，且**连同比对的 computer_call 和相邻 reasoning 项一起删**——上下文经济的正确姿势。Neurova 用"截图永不进上下文"的双通道设计（更强），但**对话里的历史截图管理没有等价物**（长对话图片轮的 token 累积问题）。
- **`BudgetManagerCallback`**（预算超限抛 `BudgetExceededError` 停止 run）+ 重试去重（litellm 内层重试强制 0，只留外层 `_predict_step_with_retry` 指数退避，`agent.py:974`）——与 Neurova 09-11 的 429 重试链设计互证（同构：内层关、外层统一退避）。
- **20+ 模型 loop 用正则注册表分发**（`@register_agent(models=..., priority=...)`，`decorators.py:13`），统一协议 `predict_step/predict_click/get_capabilities`。Neurova 的 `neurova/llm/` 路由是能力标记制；Cua 的"每个 provider 一个 loop 类 + 能力声明"契约值得在 reasoning 归一化（09-09 六件套）后续演进中参考。

### 3.4 评测即任务环境（cua-bench）
任务不是 JSON 而是可执行 Python 环境：`@cb.tasks_config / @cb.setup_task / @cb.solve_task / @cb.evaluate_task` 四装饰器（`cua_bench/decorators.py:22`），参考解（oracle）与评测器（奖励）都是代码——2048 示例的评测就是 `session.execute_javascript(pid, "window.__max_tile")` 读游戏状态归一化 0..1。**simulated 提供方（`computers/webtop.py`）用 Playwright 渲染 HTML 桌面、DOM 派发动作，零 VM 零 Docker 就能跑全套评测**。轨迹统一落 `{event_name, data_json, data_images, trajectory_id}` 行，可推 HF Hub、转 GUI-R1/AgUVis 训练格式、接 GRPO RL 环。

**对 Neurova 的意义**：OCU 报告 P2-1（桌面 fixture 测试 + agent-smoke）只到"场景冒烟"；cua-bench 展示了完整形态——**Neurova 自建 CUA 评测时，从 simulated（HTML 假桌面）起步，成本最低且能进 CI**；真实 OS 容器做第二轮。

## 4. Cua 其余可借鉴点（简）

1. **SOM/OmniParser 视觉定位闭环**（`som/` + `loops/omniparser.py`）：解析 → 编号标注图 → `id2xy` 映射 → 模型输出 `element_id` → 转回坐标 → **历史消息里的截图统一替换为标注图**保持 id 一致。这正是 Neurova 死代码 `vision.py`（YOLO+EasyOCR，同一血统）的"用法说明书"——OCU 报告 P1-6 的"接入"选项从此有了完整蓝图。
2. **Winsandbox 提供方强制临时存储**（`computer.py:245`）：一次性整机沙箱跑完即弃。Neurova 主战场是 Windows——给 agent 一个"一次性 Windows 桌面"选项与现有 AppContainer 形成两级隔离，比 VM 路线轻得多。
3. **来宾内 computer-server 守护进程**：单端口同时开 WS/REST/MCP/PTY，`UnavailableWithoutContainerMiddleware` 容器外禁用宿主面 + WS 首包 api-key 握手——若走 VM/容器路线，这是现成的来宾侧架构参考。
4. **computer history 隐私范式**：加密动作历史只存**元数据白名单**，永不存截图/键入文本/剪贴板/URL，`history_query` 权限门控只读回灌。Neurova 的动作审计日志（若做）照此边界。
5. **附身已登录浏览器 profile 需显式授权**（`--grant existing-profile`）：Neurova 的 camofox 保留登录态 profile，但没有对应授权仪式——治理链可加这条。
6. **坐标换算三件套确认**：服务端截图统一缩到 ≤1920 宽（LANCZOS），Anthropic loop 里 >1024 截图先缩、动作坐标再放大回去（`loops/anthropic.py:39` + `_scale_coordinate`），`to_screen_coordinates/to_screenshot_coordinates` 客户端映射。与 OCU 报告 P0-2（DPI 坐标链）同方向，证明该模式是行业共识。

## 5. Neurova 反超项（不变）

浏览器栈（Playwright/camofox 双后端 + generation 契约 + 分块读取——Cua 的 browser 工具反而较薄）、治理链完整度（Cua 权限模式强但无 approval 状态机/多段 shell 白名单）、多租户流式、截图双通道上下文经济性（**Cua 的截图进 LLM 上下文，靠 ImageRetention 兜底；Neurova 的 WS 旁路设计更优**）、PlanningTool。

## 6. 改进清单（含与 OCU 清单的合并视图）

### 新增项（本报告提出）
| # | 优先级 | 项 | 落地建议 |
|---|---|---|---|
| C-1 | **P1** | **ActionResult 封闭契约** | `BrowserResult`/computer 工具结果加 `route`（accessibility/app_post/global/camofox_ref/playwright_role）、`delivery`（background/foreground）、`effect`（confirmed/suspected_noop/refused）、`evidence` 字段；`suspected_noop` 用于"执行了但无验证手段"场景。与 OCU 清单 P1-1（降级诚实化）**合并实施**：P1-1 是内容要求，C-1 是协议载体 |
| C-2 | P1 | 执行前动作归一化层 | tool_executor 分发前对 LLM 产出做归一化/校验（学 OperatorNormalizer），HTTP 侧 `extra="forbid"` 经验推广到 agent 侧 |
| C-3 | P1 | 历史图片保留回调 | 长对话图片轮：保留最近 N 张，旧图连同其消息对的 reasoning 一并清理（学 ImageRetention 的"成对删除"细节） |
| C-4 | P2 | vision.py 复活走 SOM 路线 | OCU 清单 P1-6 的"接入"选项具体化：OmniParser 式 编号标注图 + id2xy + element_id 工具；标注图替换历史截图保一致性 |
| C-5 | P2 | simulated 评测起步 | 自建 CUA 评测：Playwright HTML 假桌面 + 奖励函数 + CI 内跑（学 cua-bench 四装饰器契约），升级 OCU 清单 P2-1 的 fixture 方案 |
| C-6 | P2 | Winsandbox 一次性桌面 | 评估 Windows Sandbox 提供方作为 agent 的"临时整机"选项（与 AppContainer 两级隔离）；参考 Cua 强制临时存储 |
| C-7 | P2 | 能力台账最小版 | 每个浏览器/桌面后端建"投递路径 × 后果验证"测试矩阵，断言 fixture 状态变化而非"不崩"；登记 refused 场景的精确拒绝码 |
| C-8 | P3 | 浏览器 profile 附身授权仪式 | camofox 保留登录态 → 使用前需显式 grant，纳入治理链 |
| C-9 | P3 | 动作审计历史（隐私边界版） | 只存元数据白名单（route/effect/目标角色），永不存截图/键入文本，只读查询端点 |

### 与 OCU 清单互证升级（不重复开项）
- **P0-1（桌面元素语义目标）**：Cua 的 AX/PX 双寻址 + 后台投递 + `background_unavailable/background_occluded` 精确拒绝码，给 Windows UIA 实现补充了**拒绝码词汇表**与"语义/像素寻址分离"的契约设计。
- **P0-2（DPI 坐标链）**：Cua 服务端 ≤1920 降采样 + Anthropic 1024 cap 回放大 + 客户端双向映射，是行业共识实现，直接照抄模式。
- **P1-3（观察预算）**：Cua 用回调管线做（ImageRetention/Budget），比参数化更解耦，可与 OCU P1-3 二选一或并用。
- **P2-4（CUA 导出 MCP）**：Cua 同时暴露 agent 面 MCP（run_cua_task）与工具面 MCP（in-VM 40 工具）双层，证明双层 MCP 是成熟形态。

### 不建议照搬
- **Fleet 云桌面/K8s 控制面/预热池**：Neurova 当前规模不需要整机池化 SaaS。
- **RL 训练环（GRPO/轨迹转训练格式）**：除非启动自研 grounding 模型，否则是过度工程；轨迹导出格式可先留接口。
- **全量 fixture GUI 矩阵**（Cua 为此维护数十个 fixture 应用 + CI 车队）：Neurova 用 C-7 最小版即可。
- **MCP skills 扩展内嵌分发**（SEP-2640 未上游定稿）：等协议稳定。

## 7. 三份研究合并后的路线图（一页版）

**桌面端**（P0 四项不变，OCU 报告为主）→ 元素语义目标 + DPI 坐标链 + 动作回传刷新 + scroll 根修；
**协议层**（本报告 C-1）→ ActionResult 封闭契约落地，route/effect/evidence 三字段先行，拒绝码词汇表采用 Cua 版；
**管线层**（C-2/C-3）→ 归一化层 + 图片保留回调；
**评测层**（C-5/C-7）→ simulated 假桌面 + 能力台账最小版；
**远期**（C-4/C-6/P2-4）→ SOM 视觉复活 / 一次性 Windows 桌面 / CUA 导出双层 MCP。
