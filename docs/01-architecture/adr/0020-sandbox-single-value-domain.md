# ADR 0020: 沙箱值域唯一事实源（一套形态，两种承载能力）

- **Status**: Accepted
- **Date**: 2026-09-25
- **Decision Maker**: Issue #68 收口 · 前端契约差异末条裁决

## Context

`SandboxPage.vue` 是路由表内的真实页面，它描述的能力是**代码执行沙箱**：

- 列表卡片展示 `image` / `steps_count` / `created_at`；
- 执行区提交 `{command, language}`，语言取 `python` / `shell` / `javascript`；
- 新建弹窗提交 `{name, image, timeout}`；
- `commitSandbox(id)` 与 `deleteSandbox(id)` 不带 body。

而后端 `neurova/api/endpoints/sandbox.py` 实现的是**思维沙箱**：

- `POST /start` 要求 `agent_id` + `topic`（前端载荷 ⇒ 必 422）；
- 执行面是 `POST /{id}/step` 收 `{input, context}`——前端发的 `/{id}/execute`
  **从未注册过路由**（必 404）；
- `POST /{id}/commit` 强制 `conclusion` body（前端不传 ⇒ 必 422）。

同一个词「沙箱」被定义了两份：两份字段集、两份语义、两份状态机。前端页面三个动作
全部失败。这正是修复教义第 6 条要收口的形态——**一件事两处定义，必然逐版漂移**。

## Decision

**沙箱只有一套值域，两种能力是同一值域下的两种承载。**

session 形态唯一（字段即前端 `Sandbox` 接口的投影）：

| 字段 | 含义 |
|---|---|
| `id` | session id；`null` 是**保留 id** |
| `name` / `image` / `timeout` / `language` | 创建参数 |
| `steps` | 承载的执行/推理步骤；`steps_count = len(steps)`（不另存计数） |
| `status` | 有限枚举 `running / paused / committed / failed / timeout` |

两种承载：

1. **代码执行**：`POST /start` 带 `name`/`image`/`timeout` → 真 session（uuid）。
   执行面 `POST /{id}/execute` 收 `{command, language}`，真解释器跑真代码，
   镜像经白名单校验，超时是不可绕过的硬约束。
2. **思维沙箱**：`POST /start` 带 `agent_id`/`topic` → 挂在保留 id `null` 上
   （无容器承载）。执行面 `POST /null/step` 收 `{input, context}`。
   `null` 不可删除、不可执行代码：**它在值域里，但有一份限定能力面**。

关键设计：

1. **后端选择必须显形**。每次执行都自报 `backend` 与 `enforced`。
   `backend=auto`：Docker 可用则容器（跨平台真隔离），否则平台后端并如实回
   `enforced=false`（**不谎称隔离**）；`backend=docker`：不可用即显式报错，
   **不静默降级成裸跑**。前端把这些字段原样展示——「执行成功」不再等于「隔离生效」。
2. **语言是闭集**。`python` / `shell` / `javascript` 三值；
   集合外的语言显式 4xx（**不许当成 python 跑**）。
3. **镜像白名单**。用户选的镜像就是跑它的镜像；白名单外显式拒绝（不许收下再换一个跑）。
4. **执行后端复用既有隔离体系**。`neurova/sandbox/code_sandbox.py` 只做
   「有状态 session 承载 + 语言分派 + 诚实自报」，隔离能力来自 `exec_sandbox.py`，
   **不新造第二套隔离事实**。
5. **超时是硬约束**。`communicate(timeout=...)` 之外的兜底定时器到点无条件杀进程树
   ——解释器被包装器套一层时（venv 启动器、`sh -c`）不靠被监控方配合也能掐断。

## Consequences

**正向**
- 前端 6 个调用逐条命中真路由，清单第四节「前端调用 ↔ 后端注册」差集归零；
- 「隔离了没有」成为可审计读数（`backend` + `enforced` 随每次执行上报）；
- 降级、拒绝、超时都以**诚实形态**暴露，不抹成 200 成功（修复教义第 1/2 条）；
- 思维沙箱能力未丢失，收敛为保留 id 上的限定面，值域不分裂。

**负向 / 代价**
- `POST /start` 的请求体是两种承载的并集（只传描述字段按代码执行起）。
  代价是单次请求体字段较多；收益是前端只需一套类型，不会再长出第三份。
- session 存储当前是进程内内存态（与改前的思维沙箱一致）——重启即失。
  先例登记：会话持久化不在本单射程，需要时按同一值域补存储层，不另立形态。

**验证**
- `tests/unit/sandbox/test_code_execution_sandbox_contract.py`（26 条）：实现前
  **23 红**，实现后 **26 绿**。
- live-verify：真装配应用 19 条探活全达标（前端载荷 200 / 真 stdout 捕获 /
  exit_code 与非零退出 / stderr 分流 / 不支持语言 400 / 空命令 422 /
  超时 2s 掐断且 `timed_out=true` / 提交后执行 400 / 删除后 404 /
  白名单外镜像 400 / 思维面 `null` 步进 200、执行 400、删除 400）。
- A/B：`tests/unit/api` + `tests/unit/sandbox` + `tests/unit/security` 改动前后
  失败集合 17 行逐行相同（零新增）。

## References

- 问题来源：Issue #68 收口过程中复核发现的最后一条前端契约断链
  （`tests/unit/frontContractBaseline.txt` 原裁决「待接线」，本 ADR 落地后改判「已修」）
- 实现位置：`neurova/api/endpoints/sandbox.py`、`neurova/sandbox/code_sandbox.py`、
  `NeurUI/src/pages/SandboxPage.vue`、`NeurUI/src/api/modules/sandbox.ts`
- 既有隔离体系：`neurova/sandbox/exec_sandbox.py`（Bubblewrap / Seatbelt /
  AppContainer / 受限令牌 / 进程级，按平台探测）、`neurova/execution_layers/__init__.py`
- 同纪律先例：[ADR 0018 记忆分类词汇表唯一事实源](./0018-memory-classification-vocabulary.md)
