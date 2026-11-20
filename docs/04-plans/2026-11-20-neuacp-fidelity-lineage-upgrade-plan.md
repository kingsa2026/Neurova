# neuacp 接入层保真与归因升级方案（参照系 O §6.11 借鉴清单 v2 落地）

> 日期：2026-11-20。
> 来源：`docs/08-research/reference_o_vs_neurova_acp_access_comparison_2026-11-20.md` §6.11
> （借鉴清单 v2，五条）与 §6.2/§6.4/§6.7/§6.8 代码级对照。
> 上游：`docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md`（P0+P1+P2 已落地）。
> 定位：本方案是 neuacp 接入层的**保真/归因/能力声明升级**，不改 ACP 协议路线、
> 不改审批链语义、不扩接入对象（Trae 维持暂不接入、C3 远程 HTTP 维持挂起）。
> 状态：**待拍板 D-A…D-D（§8）后开工**；任务卡 F1–F5，两波次并行 + 串行收口。

---

## 0. 结论摘要

1. 五卡全部落在 neuacp 既有切口上：能力声明进 `catalog.py`、打开前拒绝接
   `_resolveExternalMember` 与名册写门两个闸；全序与一手留痕 = H-4 账本补 `seq`
   + 新增逐 run 帧 JSONL；保真纪律修 plugin 执行体的两处"推断"并加双层脱敏；
   同构桩 = 新增 `NeuacpScriptedExecutor` 与真执行体共用一套契约测试；谱系归因 =
   事件/帧统一携带 `lineage`（tenant/team/agentPath/trace）。
2. 新增文件 3 个：`neurova/agent/neuacp/frame_log.py`、`neurova/agent/neuacp/redaction.py`、
   `neurova/agent/neuacp/scripted_executor.py`；核心改动集中 `swarm_event_log.py`、
   `catalog.py`、`swarm.py`、`acp_client.py`、`plugin_executor.py`、`acp_member.py`、
   `teams_api.py`、`external_agents_api.py`。
3. 与参照系 O 的"records/events 双层"同构对位：H-4 账本是**治理投影**（正文不进，
   纪律不变），帧账本是**一手事实流**（原生帧脱敏后全量留痕、可游标回放）——
   两条流各司其职，不构成重复体系（§4）。
4. 待拍板四项（§8）：帧正文是否留痕（D-A）、plugin 无 result 帧的语义（D-B）、
   帧读面开放范围（D-C）、能力违规配置期是否硬拒（D-D）。

## 1. 背景与范围

### 1.1 来源与动机

参照系 O 对比（v2 源码走读）给出五条可借鉴项（对比报告 §6.11）：能力声明+打开前
拒绝；控制与事实同流全序+一手事件流留痕；事件保真纪律（不推断、native 留痕脱敏）；
内核级同构桩；租户/归属归因进事件流。这五条共同补强 neuacp 当前最弱的三维：
事件保真（7）、能力声明（5）、归因缺失。登录令牌经手面一项对比报告已判定
"本仓凭据面同向、已对齐"，不入本方案。

### 1.2 目标

| 卡 | 借鉴项 | 一句话目标 |
|----|--------|-----------|
| F1 | 能力声明+打开前拒绝 | 每家 runtime 显式声明支持面，不支持的组合在**开进程前**结构化拒绝 |
| F2 | 控制与事实同流全序 | H-4 账本补每 run 单调 `seq`；chunk/permission/控制事件与工具事实同账本可判先后；新增一手帧留痕与游标回放 |
| F3 | 事件保真纪律 | 结果只在 runtime 明确报告时落账（删推断兜底）；原生帧双层脱敏后留痕 |
| F4 | 内核级同构桩 | 假执行体与真执行体实现同一协议、产出同构帧流，上层语义回归无二进制化 |
| F5 | 谱系归因进事件流 | 事件与帧携带 `lineage`（tenant/team/agentPath/depth/trace），支撑跨会话归因 |

### 1.3 非目标（红线）

- 不接 Trae、不做 ACP 远程 HTTP transport（C3 待上游定稿）。
- 不改 ACP v1 协议层行为（`acp_client.py` 帧格式/握手/fail-closed 语义不变，只加留痕钩子）。
- 不改审批链 L0/L1/L2 语义与租户红线（§6.4 既有判定点全部保持）。
- 不引入参照系 O 的 SDK 库形态、自研协议或 Node 运行时（对比报告 §5 不照搬清单）。
- H-4 账本"正文不进账本"纪律不变（帧账本才承载原文，见 §4 分工）。

## 2. 现状与断点（file:line 实证，2026-11-20 现读）

| # | 断点 | 证据 |
|---|------|------|
| 1 | catalog 只有 installed 探测，无能力声明；不支持的组合要到开进程后甚至运行中才暴露 | `catalog.py:14-82`（预设仅 kind/transport/command/origin）、`catalog.py:93-113`（probeTool 仅 which） |
| 2 | spawn 前校验只有 开关/租户/命令非空/kind 已知，无能力校验 | `swarm.py:2088-2127` |
| 3 | H-4 账本无 `seq`，只有 causation 链；多写者（泵线程镜像/主任务）先后只能靠文件序 | `swarm_event_log.py:35-54`（record 无 seq） |
| 4 | content/reasoning chunk 不入任何账本，只广播 WS——"取消是否先于某段产出"不可判定 | `swarm.py:2698-2721`（emitter 仅 `_broadcast`） |
| 5 | 无一手帧留痕：ACP JSON-RPC 帧 / plugin NDJSON 行消费后即弃，审计无原文 | `acp_client.py:274-295`（pump 直派发）、`plugin_executor.py:84-107`（行循环直解析） |
| 6 | plugin 执行体两处推断：`stop_reason` 恒 `"end_of_turn"`（非 runtime 报告）；无 result 帧时用累积 chunk 拼成结果 | `plugin_executor.py:105-116` |
| 7 | 事件/帧无租户与谱系：record 只有 `subagent_id`；`SubAgentRun` 无 `tenant_id`/`parent_subagent_id` | `swarm_event_log.py:41-48`、`swarm.py:330-415` |
| 8 | permission 裁决结果不入账本（审批单在 approval_chain，run 账本无对应事件） | `acp_member.py:95-129`（asker 只返回 dict）、`acp_executor.py:207-223` |
| 9 | 测试桩只有黑盒 wire 桩（真子进程），上层（adapter/账本/投影）回归依赖二进制 | `tests/unit/agent/neuacp/fake_acp_agent.py`、`fake_zcode_cli.py` |

## 3. 设计（按卡）

### 3.1 F1 能力声明与打开前拒绝

**数据形态**（`catalog.py`，每条 CATALOG 预设新增 `capabilities`，单一事实源）：

```python
"capabilities": {
    "transports": ("stdio", "ssh"),      # 机制上 ssh 是通用命令包装（ssh_transport.resolveSpawnCommand）
    "permission_modes": ("chain", "auto"),  # plugin 家 = ("chain",)——无运行中审批交互，auto 无意义
    "streaming": True,                   # ACP update 流 / plugin NDJSON 均为流式
    "resume": False,                     # zcode=True（--resume 有官方口径）；其余 False
    "session_reuse": True,               # plugin=False（每 prompt 一进程）
}
```

**新函数**（`catalog.py`）：

- `capabilitiesFor(tool: str) -> dict`：未知工具返回空声明的保守档（只给 stdio/chain）。
- `refuseExecutorSpec(spec: dict) -> list[str]`：返回全部违规原因（空列表=放行）。
  校验项：`tool` 已知（填了 tool 时）；`kind` 与目录一致；`transport ∈ transports`；
  `permission_mode ∈ permission_modes`；`remote` 仅随 `transport="ssh"` 出现。

**双闸接线**（配置期挡误配、派活期兜底 fail-closed）：

1. 配置期：`teams_api.py:399` 组装 `executor_spec` 后调 `refuseExecutorSpec`，
   非空 → `HTTPException(422, detail=原因列表)`。
2. 派活期（权威闸）：`swarm.py:2100` 租户校验通过后、构造执行体（:2110）**之前**
   调 `refuseExecutorSpec(spec)`，非空 → `return None, "能力不支持：..."`。
   保证即使名册经旧数据/旁路写入，也不会为不支持的组合开进程
   （"refused before anything opens"）。
3. 管理面：`external_agents_api.py` 的 catalog 响应透出 `capabilities`
   （前端下拉可据此预判，测试连接前即可提示）。

**测试**（先红）：`test_catalog.py` 增 `test_everyPresetDeclaresCapabilities`、
`test_refuseExecutorSpecMatrix`；`test_swarm_external_member.py` 增
`test_unsupportedTransportRefusedBeforeSpawn`（spy 执行体构造器，断言未实例化）；
teams_api 测试增 422 用例。

### 3.2 F2 全序事件流与一手帧留痕

**H-4 账本补 `seq`**（`swarm_event_log.py`）：

- `appendRunEvent(..., lineage: Optional[dict] = None)` 增参（F5 共用签名）。
- record 增 `"seq"`：per-path 单调递增（进程内计数缓存，首次遇该 path 时从文件
  尾部回扫最大 seq 初始化；写入仍在既有全局锁内，天然全序）。旧文件无 seq 行
  容错（读侧按缺省 -1 处理，新事件从最大值续起）。
- record 增 `"lineage"`（可空 dict）。

**新增帧账本**（`neurova/agent/neuacp/frame_log.py`）：

```python
def appendFrame(subagentId: str, direction: str, frame: dict, *, lineage: dict | None = None) -> int
def readFrames(subagentId: str, afterSeq: int = 0, limit: int = 1000) -> list[dict]
```

- 落盘 `<数据根>/swarm_runs/<subagentId>.frames.jsonl`（与 H-4 同目录、独立文件）。
- record：`{"seq", "direction": "in"|"out"|"observed", "frame": <脱敏后原生帧>, "lineage", "occurred_at"}`。
- `frame` 是 wire 原文（ACP JSON-RPC 消息 / plugin NDJSON 行解析出的 dict）——
  **永不合成、永不推断**：超限/不可解码行记 `{"undecodable": true, "length": n}`
  诚实标记，不猜测内容。
- 写失败 fail-open（debug 日志，不阻断泵线程）。
- `subagentId` 键由执行体在 `start(ctx)` 时从 `ctx.metadata["subagent_id"]` 取
  （F5 注入）；未绑定（如管理面 /test 握手）不落帧，避免无主留痕。

**挂点**（全部为观察钩子，不改协议行为）：

- `acp_client.py`：`__init__` 增 `frame_key` + `setFrameKey(key)`；
  `_sendFrame`（:258）成功写出后 `appendFrame("out", message)`——我们发的
  request/notify（含 `session/cancel`）进同流；`_pumpStdout`（:274）解析成功后
  `appendFrame("in", message)`；进程退出观察点（`_failClosed`/terminate 路径）
  `appendFrame("observed", {"type": "exited", "exit_code": ...})`——退出是观测
  事实，绝不伪造成 `turn_ended`。
- `plugin_executor.py`：prompt 拉起后 `appendFrame("out", {"type": "argv", "command": ...})`
  （命令不含凭据——凭据走 env 白名单 `child_env.py`）；行循环解析成功
  `appendFrame("in", message)`；`proc.wait()` 后 `appendFrame("observed", {"type": "exited", ...})`。

**chunk/permission 进治理账本**（`swarm.py` / `acp_member.py`）：

- `_make_emitter`（swarm.py:2698）的 emitter 内同步
  `_logRunEvent(run, "member_chunk", {"chunk_type": ..., "length": len(data)})`
  ——只记元数据不记正文（H-4 纪律不变）。自此 chunk、tool_call、permission、
  cancelled、terminal 同账本同 seq，"取消是否先于某段产出/某次工具调用"可判定。
- `acp_member.py` `_approvalPermissionAsker` 拿到裁决后
  `logEvent(run, "permission_decided", {"action", "approved", "pending", "denied"})`
  （补 §2 断点 8）；帧侧请求（in）与应答（out）天然留痕。

**读面**：`SwarmManager.runFrames(subagentId, afterSeq)`（镜像 `runEvents`，swarm.py:1171
形态）；`external_agents_api.py` 增 admin 门 `GET /v1/external-agents/runs/{subagent_id}/frames?after_seq=`
（含同租户校验，404 语义按既有口径）。范围见待拍板 D-C。

**测试**（先红）：并发写 seq 严格递增；frames 中 `out(session/cancel)` 的 seq 可与
`in(tool_call)` 比先后；不可解码行 honest marker；frame_key 未设不落盘；脱敏在落盘前生效。

### 3.3 F3 事件保真与凭据脱敏

**新增 `neurova/agent/neuacp/redaction.py`**（双层，对位参照系两级脱敏）：

```python
CREDENTIAL_FIELD_RE = re.compile(
    r"(api[_-]?key|apikey|token|secret|password|passwd|authorization|"
    r"credential|private[_-]?key|access[_-]?key|personal[_-]?access)", re.I)

def redactFrame(frame: dict) -> dict:
    """深拷贝脱敏：结构级=字段名命中→"[redacted]"；值级=复用记忆层 SENSITIVE_RULES。"""
```

- 值级规则**复用** `neurova/cognitive_layers/memory_layer/security.py` 的
  `SENSITIVE_RULES`/`sanitizeSensitive`（单一事实源，不另造第二套正则；惰性 import，
  导入失败退化为仅结构级并 warning）。
- 接点：`frame_log.appendFrame` 写盘前必经 `redactFrame`；
  `acp_member._mirrorToolCall`（acp_member.py:149）进账本/轨迹的 `tool_call`
  载荷同样过 `redactFrame`（工具参数可能夹带密钥）。

**plugin 执行体保真修正**（`plugin_executor.py:105-116`，先红）：

- 删除 `text = result_text or "".join(accumulated)` 的推断兜底：无
  `type:"result"` 帧 = runtime 未报告结果 = **诚实失败**
  `raise NeuacpError("plugin CLI ended without result frame")`。部分产出不丢——
  chunk 已实时经 emitter 进 `contentBuffer`，失败交接链路（swarm P2 机制）照常
  取尾部作部分报告。
- `stop_reason="end_of_turn"` 仅在 result 帧在场时成立（raise 路径无值）；
  `NeuacpExecResult.raw` 回填 result 帧原文（脱敏后），不再恒 `None`。
- 非零退出维持诚实失败（现有 `exit_code not in (0, None)` 分支），退出码先进
  frames 流（`observed/exited`）再抛错。

**测试**（先红）：`test_plugin_executor.py` 增 `test_missingResultFrameFailsHonestly`
（现实现会返回拼接文本=红）；`test_redaction.py`（嵌套 api_key 字段、`sk-` 值形态、
数组内对象逐层脱敏、非凭据字段原样保留）；mirror 载荷脱敏用例。

### 3.4 F4 内核级同构桩（scripted executor）

**新增 `neurova/agent/neuacp/scripted_executor.py`**：

- `NeuacpScriptedExecutor(command, script: list[dict])` 实现与
  `NeuacpStdioExecutor`/`NeuacpPluginExecutor` **同一协议**
  （`executor.py:36-49`：start/prompt/cancel/close + `setToolCallHandler` +
  `attachProcessPool`（no-op）+ `setFrameKey`）。
- 剧本步骤（声明式）：`{"emit": ["content"|"reasoning", text]}`、
  `{"tool_call": {...}}`、`{"request_permission": {...}}`（经注入 asker 同步裁决）、
  `{"result": {...}}`、`{"crash": reason}`、`{"exit_code": n}`、`{"sleep": s}`。
- 每步以与真执行体**同构**的帧写 frame_log（direction in/out 同真执行体）；
  `member_session_id`/`subagent_id` 语义与真执行体一致。
- 定位：测试与确定性回归支撑（放 neuacp 包内、注释注明测试支撑用途）；
  既有 wire 桩保留（它们测传输层本身），scripted 桩测传输层**之上**的全部语义。

**契约测试**（同构性证据，先红）：`tests/unit/agent/neuacp/test_executor_contract.py`
——同一份剧本分别驱动 `NeuacpStdioExecutor(挂 fake_acp_agent)` 与
`NeuacpScriptedExecutor(同剧本)`，断言可观测结局一致：返回 text、stop_reason、
H-4 事件序列、frames 流形状。adapter 语义回归（permission deny → 中止形态、
cancel 时序、crash → 诚实失败）全部改跑 scripted 桩，无二进制。

### 3.5 F5 谱系归因进事件流

**run 模型**（`swarm.py:330-415` `SubAgentRun` 增字段）：

- `tenant_id: str = ""`（spawn 时刻经 `_currentTenantId()` 读一次；`:2423` 的
  `openSubagentRun(tenantId=...)` 改吃 `run.tenant_id`——spawn 时刻单源，运行中不重读）。
- `parent_subagent_id: str = ""`（member 内递归派生处显式传父 `run.subagent_id`；
  顶层派生为空）。
- `agent_path` 不落存储字段，事件写入时沿 `parent_subagent_id` 上溯现算
  （内存 run 优先、H-4 账本兜底；限深 16、访问集防环）。

**lineage 组装与注入**：

- `_logRunEvent`（swarm.py:1157）统一组装
  `lineage = {"tenant_id", "team_id", "project_id", "room_id", "depth",
  "parent_subagent_id", "agent_path", "trace_id", "parent_trace_id"}` 传入
  `appendRunEvent`——全部事件（含 member_chunk/permission_decided/tool_call）
  自动携带。
- `NeuacpMemberAdapter.chat`（acp_member.py:180）向 `NeuacpSessionContext.metadata`
  注入 `{"subagent_id": run.subagent_id, "lineage": ...}`；执行体 `start` 时
  `setFrameKey(metadata["subagent_id"])` 并把 lineage 透传给 `appendFrame`。
- 广播载荷 `subagent_started`（swarm.py:2438-2460）增 `tenant_id`/
  `parent_subagent_id`/`agent_path`（前端可选消费，不强制适配）。

**测试**（先红）：递归 spawn 后子 run 事件 `lineage.agent_path == [parent_id, child_id]`；
frames record 带 lineage；`openSubagentRun` 收到的是 spawn 时刻租户
（monkeypatch `_currentTenantId` 在运行期变更，断言台账行仍为 spawn 时刻值）。

## 4. 数据形态与单一事实源对照

**双流分工**（对位参照系 records/events 双层，不构成重复体系）：

| 流 | 文件 | 角色 | 内容纪律 |
|----|------|------|----------|
| H-4 治理账本 | `<数据根>/swarm_runs/<id>.events.jsonl` | 生命周期/治理投影（状态机回放、审批、候选、档案聚合消费它） | 正文不进（task/chunk 只留摘要与长度） |
| 帧账本（新） | `<数据根>/swarm_runs/<id>.frames.jsonl` | 一手事实流（审计回放、时序判定、契约测试共用） | 原生帧脱敏后全量留痕；永不合成/推断 |

**复用单源清单**：脱敏值级规则=`memory_layer/security.SENSITIVE_RULES`（不新造正则）；
能力声明=`catalog.CATALOG` 唯一出处；租户=`currentUserTenantId`（spawn 时刻一次）；
帧/事件同目录同 JSONL 形态（`dataPath("swarm_runs")`）；seq 语义两条流各自独立
单调（流内全序，跨流不比较）。

## 5. 实施计划（波次/文件独占地图）

延续"三并行子代理分线 + 主会话统一提交"方法论，按文件独占面防撞：

**波次 1（并行三线）**：

| 线 | 卡 | 独占文件 | 产出 |
|----|----|----------|------|
| 甲 | F2+F3 底座 | `swarm_event_log.py`、`neuacp/frame_log.py`(新)、`neuacp/redaction.py`(新)、`neuacp/acp_client.py`、`neuacp/plugin_executor.py` + 各测试 | seq/lineage 签名、帧账本、脱敏、执行体挂点、plugin 保真红转绿 |
| 乙 | F1 | `neuacp/catalog.py`、`api/endpoints/teams_api.py`、`api/endpoints/external_agents_api.py`(仅 catalog 响应段) + 测试 | 能力声明 + 双闸 + 422 |
| 丙 | F4 | `neuacp/scripted_executor.py`(新) + `test_executor_contract.py` | 同构桩与契约测试（协议已稳定可先行；frame_log 未合入期以局部替身对齐） |

**波次 2（并行两线）**：

| 线 | 卡 | 独占文件 | 产出 |
|----|----|----------|------|
| 丁 | F5+F2/F3 接线 | `swarm.py`、`neuacp/acp_member.py` + 测试 | run 增字段、lineage 组装、emitter 镜像、permission_decided、双闸接点、广播补字段 |
| 戊 | F2 读面 | `api/endpoints/external_agents_api.py`(frames 端点段) + 测试 | frames 读端点（admin+同租户） |

**波次 3（主会话串行收口）**：合并回归（`tests/unit/agent` + `tests/unit/api`
全量 A/B 零新增失败）→ live-verify 9527（真后端 + wire 桩全链：建队→加外部成员→
dispatch→核验 frames/seq/lineage/capability 拒绝/脱敏落盘；启动日志 `[ERROR]=0`
且 `/v1/providers` 注册行在）→ 文档回填（本方案 §9、ACP 主方案 §12 补行）。

**提交纪律**：每卡独立 `--only` 提交、附红→绿实测与净 LOC 声明；新增测试文件
先 `git add` 再 `--only`；共享文件（`swarm.py`）只归线丁，禁裸 amend。

## 6. 测试与验收

- 每卡先红后绿，红灯用例名见 §3 各卡；共享文件 A/B 自证（patch 法）。
- 契约测试（F4）参数化 wire 桩与 scripted 桩双跑，断言同构。
- 回归门：`tests/unit/agent/neuacp/` 全量 + `test_swarm_external_member.py` +
  `tests/unit/api`（含 authSurface：新增 `/runs/{id}/frames` 路由后**必须重跑
  `scripts/generate_api_auth_surface.py --write`**）零新增失败。
- live-verify 清单（波次 3）：① 不支持组合（如 plugin+auto）建队派活被结构化拒绝
  且无进程拉起；② 正常派活后 frames.jsonl 存在、seq 严格递增、cancel 与 chunk
  先后可判定；③ lineage 三字段（tenant/team/agent_path）落事件与帧；④ 含
  `api_key` 形态的帧落盘为 `[redacted]`；⑤ plugin 桩无 result 帧时 run failed
  且部分产出随失败交接可见。

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 帧留痕磁盘放大（每 run 全量原生帧） | 帧体已有 1MiB fail-closed 上限；超限/不可解码记 honest marker；留存治理沿用 swarm_runs 目录既有策略；D-A 若裁"只留元数据"则进一步降级 |
| 泵线程同步写盘引入延迟 | append 与 H-4 同锁粒度的追加写（短临界区）；fail-open 不阻断泵；不做缓冲重排（保序优先） |
| 脱敏漏配泄露凭据 | 结构级字段名单 + 值级正则双层；测试钉死样本；值级规则复用记忆层单源随其升级 |
| seq 初始化回扫大文件 | 仅进程内每 path 一次，且从文件尾倒读；旧文件无 seq 行容错 |
| 兼容性：读方依赖旧 record 形态 | 新字段均为可选增列；`readRunEvents`/`runEvents` 消费方按缺省值容错（增量断言测试覆盖） |
| 能力声明与真机行为漂移（如某家新版支持了 resume） | 声明是"本仓已验证支持面"，放宽=改 catalog 一处+测试；`/test` 连接探测可实通信道校验 |

## 8. 待拍板项（影响面均已列，推荐项置首）

| # | 问题 | 选项与影响 | 推荐 |
|---|------|-----------|------|
| D-A | 帧账本是否留 chunk/工具结果**正文**？ | ①留正文（脱敏前置）：回放/审计完整，代价=磁盘占用与隐私面扩大；②只留元数据（type/length/seq）：磁盘小、隐私面小，但帧流不可完整回放，保真目标打折 | ① 留正文（脱敏前置）——帧账本的存在意义即一手事实 |
| D-B | plugin 无 `result` 帧时的语义？ | ①诚实失败（raise，部分产出走失败交接）：符合"不推断"；②降级拼接累积文本+`inferred` 标记：成功率好看但结果来源失真 | ① 诚实失败 |
| D-C | frames 读面范围？ | ①新端点 `/v1/external-agents/runs/{id}/frames`（admin 门+同租户）：独立读面清晰；②并入既有 run events 读面合并输出：少一个端点但两流混载 | ① 独立端点（两流分工在 §4，读面同构分工） |
| D-D | 能力违规在名册配置期是否 422 硬拒？ | ①双闸（配置期 422 + 派活期拒绝）：误配最早暴露；②仅派活期拒：名册写入宽容，兼容手工改名册文件的运维路径 | ① 双闸 |

## 9. 执行记录

（开工后逐卡回填：提交号、红→绿实测、净 LOC、live-verify 证据。）
