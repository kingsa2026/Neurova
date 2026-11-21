# 参照系 ac（T3 Code）IDE 接入差距补齐实施计划

> 2026-11-21 细化。来源：`docs/08-research/reference_ac_ide_integration_gap_analysis_2026-11-21.md`
> （T3 IDE 接入支持范围专项对照，差距 G1–G5）。目标：把 T3 的「registry 零代码接入 + 真实
> transcript 回放契约 + 适配器方法面 + 多端连接运行时 + 权限两小项」落到本仓 neuacp/接入面，
> 不引 Effect 栈、不做编辑器插件/云中继/PTY 终端面。命名顺延：本计划代号沿用参照系 ac 序列。

## 0. 总览与分批

| 批 | 卡 | 内容 | 量级 | 依赖 | 需拍板 |
|---|---|---|---|---|---|
| 一 | G1 | ACP registry 零代码接入 | M | 无 | 是（D-1/D-2） |
| 一 | G2 | 真实 transcript 回放契约 | M | 无 | 是（D-3） |
| 二 | G3 | 适配器方法面收敛 | M | G2（回放网先在，重构才敢动） | 是（D-4） |
| 二 | G4 | 多端连接运行时单源 | S-M | 无 | 是（D-5） |
| 三 | G5 | 权限两小项 | S | 无 | 否 |
| 二 | G6 | ACP v2 全量适配（用户拍板升级：T3 已用 v2 证明可行） | L | G1 | 否 |

并行建议：批一两卡文件域互斥（G1 动 catalog/管理面，G2 动 tests 工具与回放管线）可并行；
批二两卡亦可并行；批三收尾。预计里程碑：批一消除 G1/G2 两大差距；批二收敛抽象与多端；批三补尾。

---

## 1. 分卡详规

### G1 · ACP registry 零代码接入（P0）

- **现状**：`neurova/agent/neuacp/catalog.py` 的 `CATALOG` 为**代码内写死的 8 家族预设**；新增一个
  规范内 ACP agent 需要改代码、加预设、跑测试。T3 用官方注册表
  `https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json` 发现 agent 并以 SHA-256
  校验安装（AcpRegistrySupport.ts:53），规范内 agent 零代码入册。
- **方案**：新增 `neurova/agent/neuacp/registry.py`：
  1. 拉取/缓存官方 registry JSON（requests/urllib，超时与体积上限；失败保留上次快照并如实标注
     `stale: true`，不静默用空表）；
  2. 把 registry 条目**归一成 catalog 条目形状**（command/transport/install_hint/capabilities 保守
     缺省），打 `source: "registry"` 标（预设为 `source: "preset"`）；
  3. `capabilitiesFor()`/`listCatalog()`/管理面 catalog 端点合并暴露「预设 + registry」两源，
     能力仍走保守缺省与 `BOOLEAN_CAPABILITY_DIMS` 单源；打开前双闸照走；
  4. 本地命令直配保留（管理员在名册里直接给 command，优先级最高）；
  5. **ACP 版本协商兼容（用户追加拍板）**：registry 条目声明各自 protocolVersion——客户端按
     条目声明版本选择握手语义（v1 全量保持；v2 处于 alpha，先做「识别 v2 条目+按声明版本协商」
     的兼容路径，v2 专属能力面待 spec 正式版另评，不做全量 v2 重写）。
- **接口契约**：`registry.refresh()` → `{entries, fetched_at, stale}`；`registry.entries()` → 归一后
  目录条目列表；catalog 合并顺序=本地直配 > 预设 > registry（同名冲突高优先级胜出并留痕）。
  安全边界：**只登记不安装**（install_hint 指引人工安装；下载安装是 D-2 拍板项）。
- **红绿判据**：`tests/unit/agent/neuacp/test_registry_onboarding.py`——registry 样本 JSON 解析→
  目录条目形状/保守能力缺省/同名优先级/stale 降级/网络失败 fail-closed；并有一条端到端：registry
  条目不经代码改动即可被 `listCatalog()` 与 `/test` 握手面发现。
- **live-verify**：真后端拉真 registry（网络可用时），断言至少发现一个本机可握手的 agent 并走通
  `/test`；网络不可用时验证 stale 降级路径。
- **量级** M；**依赖** 无。

### G2 · 真实 transcript 回放契约（P0）

- **现状**：外部 agent 接入的回归网=真握手 live-verify（三家 PASS）+ 假 agent 桩（fake_acp_agent
  等）。缺 T3 式「真实进程录制 transcript → 经真编排器回放断言」——协议细节回归（分帧/事件序/
  权限请求形状/取消时序）目前靠活体抽查，容易在重构时漏掉。
- **方案**：
  1. 录制脚本 `scripts/neuacp_record_fixture.py`（常驻工具，非临时脚本）：对指定家族（opencode/
     claude-code 适配器/codex 适配器）拉起真 CLI 子进程，按**共享场景脚本**驱动（initialize→
     session/new→prompt（短任务）→（如支持）权限请求→取消/结束），把双向帧按序落
     `tests/unit/agent/neuacp/replay_fixtures/<family>/<scenario>.json`（含方向/序号/载荷）；
  2. 回放器 `tests/unit/agent/neuacp/replay_harness.py`：把 fixture 帧喂给**真 NeuacpClient 管线**
     （真分帧/真 dispatch/真 frame_log/真脱敏），断言客户端行为（握手结果/事件回调序列/错误分类）；
  3. 共享场景集：handshake / prompt_end_of_turn / permission_request / cancel_mid_prompt /
     version_mismatch；每家特有差异单列；
  4. 「协议陷阱清单」写进 `docs/03-user-guide/` 同位的 neuacp 接入文档（或新建
     `docs/03-user-guide/neuacp-provider-pitfalls.md`，登记处同步）。
- **红绿判据**：`tests/unit/agent/neuacp/test_replay_contract.py`——三家 fixture 各回放握手+至少一个
  会话场景全绿；注入变异（调换两帧顺序/改一个字段类型/丢一帧）必须红（防“回放器恒真”）。
- **live-verify**：录制脚本对 opencode 真跑一次录制成功（本机已装 1.2.27；claude-code/codex 走
  npx 缓存适配器）。
- **量级** M；**依赖** 无。

### G3 · 适配器方法面收敛（P1）

- **现状**：外部成员的能力消费散在五结果决策（catalog.decideProviderTransition）、续跑
  （resumeFinishedRun）、审批链、检查点（scope）、steer 队列等处；没有 T3 式「一个 adapter 接口 +
  能力声明决定方法可用性」的收敛面。
- **方案**：新建 `neurova/agent/neuacp/adapter_surface.py`，定义本仓的**方法级适配器契约**
  （Protocol/dataclass），把既有机制映射为方法：`handoff`（→B2 交接工件）、`rollback`（→scope
  检查点）、`snapshot`（→事件账本/帧账本读取）、`steer`（→steer 队列）、`fork`（→候选制+重派）、
  `switch_model`（→五结果决策）；每个方法标注**所需能力维度**，能力不满足时抛
  `CapabilityNotDeclared`（fail-closed，不静默降级）。编排层（resumeFinishedRun 等）改为经该面
  调用，禁止绕过。**不引入 Effect、不改既有机制内部**——这是收敛面不是第二套实现。
- **红绿判据**：`tests/unit/agent/neuacp/test_adapter_surface.py`——能力声明齐全→方法可达且落到
  真机制；缺声明→CapabilityNotDeclared；绕过面直接调用的旧路径在白名单外被收敛（以源码断言
  或调用点改造为准）。
- **量级** M；**依赖** G2（回放网先在，收敛重构有回归保障）。
- **需拍板 D-4**：范围只覆盖外部成员（推荐，风险小）还是连内部 agent 一起收敛（面大，另评估）。

### G4 · 多端连接运行时单源（P1）

- **现状**：三端重连退避已有单源（`subscription_resume.reconnectBackoff`）；但「按需订阅（看一个
  线程不付全部线程的账）」「心跳/探活间隔」「断线重放窗口语义」分散在各端点与客户端。
- **方案**：新建 `neurova/api/connection_runtime.py` 单源：心跳间隔、重放窗口、订阅范围（scope=
  session/thread/全局）与按需订阅的**服务端语义**（订阅过滤器 + 只推范围内帧），并把既有
  mobile WS 账本/SSE 模板接上；三端客户端契约写成文档节（对齐退避单源做法）。不做云中继、
  不做离线推送（自托管 relay 为既定路线）。
- **红绿判据**：`tests/unit/api/test_connection_runtime.py`——订阅范围过滤（范围外帧不下发）、
  心跳/重放窗口单源取值、范围变更即生效。
- **量级** S-M；**依赖** 无。

### G5 · 权限两小项（P2）

- **现状**：外部成员的路径校验依赖命令 allowlist/危险命令检测，无 symlink 感知的逐级 realpath
  规约；“只暴露原生支持模式”未成文。
- **方案**：① 新增 `neurova/security/path_guard.py`：对目标路径做逐级 realpath 规约（每级遇到
  symlink 即解析），与允许根比对，**任何解析错误 fail-closed 拒绝**；接入外部成员的文件类参数
  校验点。② “只暴露原生支持模式”写入 neuacp 接入文档与 catalog 校验（permission_modes 声明
  之外的模式在打开前双闸拒绝），并补测试。
- **红绿判据**：`tests/unit/security/test_path_guard.py`（symlink 逃逸/解析错误/白名单外路径全拒）
  + catalog 侧「未声明模式拒绝」用例。
- **量级** S；**依赖** 无。

### G6 · ACP v2 全量适配（P1，用户拍板升级）

- **背景**：用户拍板「T3 已用 v2 证明可行，升级到 v2 适配」（覆盖此前「v2 仅协商备选」的口径）。
  官方 schema 实测（npx 缓存内 v1.21.0 vs v2.0.0-alpha.3）：225→218 定义、39 增/45 删/约 140 变——
  是完整重定形，不是小改。
- **我们方法子集的 v2 关键变化**（schema 实证）：
  - initialize：增必填 `info`(Implementation{name,version})；响应带 `authMethods`（v1 的独立
    authenticate 方法在 v2 移除，登录/登出改 LoginAuth/LogoutAuth）；
  - session/new→NewSession：必填 `cwd`(AbsolutePath)；响应 sessionId+configOptions+availableCommands；
  - session/load→ResumeSession：必填 sessionId+cwd，新增 `replayFrom`（协议级重放语义），响应无 sessionId（复用）；
  - session/prompt→Prompt：`prompt` 从字符串变**内容块数组**（ContentBlock：text/image/audio/resource…），
    响应从 stopReason 改为 `messageId`；
  - cancel：CancelNotification→CancelRequestNotification，按 `requestId` 取消（不再按 sessionId）；
  - request_permission：增 sessionId/title/options/subject（Command/ToolCall/Request 权限主体拆分）；
  - update 流：SessionUpdate 联合 24 分支（用户/agent/思考的 chunk 与消息、工具调用、终端、计划、
    可用命令、配置、成本与上下文窗口、压缩、unstable 扩展、other）。
- **方案**：新建 `neurova/agent/neuacp/codec_v2.py`（v2 编解码层）：
  1. **版本策略**：握手协商出整数版本后选 codec——v1 走既有代码路径（线上字节不变），v2 走
     codec_v2；codec 接口=（构造 initialize/new/resume/prompt/cancel/permission 应答的 params，
     解析响应与 update 流为内部事件模型）；
  2. **内部事件模型不变**：v2 的 24 分支 update 映射到本仓既有消费面（chunk→流式、工具调用→
     tool_call 镜像、计划→plan_update、消息→message、成本→usage、压缩→压缩事件；终端/unstable
     分支按「未知类型跳过」纪律先如实归档不消费）；
  3. **auth 变化**：v2 下 authMethods 随 initialize 下发，LoginAuth/LogoutAuth 按需实现（本仓外部
     成员现状多数免登，先做诚实透传：需要 auth 而未实现→显式 not_supported 错误）；
  4. v1 行为**逐字节保持**（既有测试与 G2 回放 fixture 全部继续通过）。
- **红绿判据**：`tests/unit/agent/neuacp/test_v2_codec.py` + `v2_strict_agent.py`（按 v2 schema 严格
  校验形状的假 agent）——v2 握手/新会话/续跑/prompt（内容块数组）/cancel(requestId)/权限请求/
  update 流映射逐项先红后绿；v1 回归（既有全部 neuacp 测试+G2 回放 fixture）零失败。
- **量级** L；**依赖** G1（版本协商已落地）。


---

## 2. 待拍板项汇总（已全部拍板：2026-11-21 用户确认「按建议来」）

| # | 卡 | 问题 | 选项与影响面 | 建议 |
|---|---|---|---|---|
| D-1 | G1 | registry 拉取策略 | 默认关+admin 手动刷新（网络面最小）vs 默认开+定时刷新（目录常新但出口流量/供应链面大） | 默认关+admin 手动刷新，失败 stale 降级 |
| D-2 | G1 | registry 安装边界 | 只登记不安装（人工按 install_hint 装）vs 允许下载安装到数据根（自动化高但供应链风险大） | 只登记不安装 |
| D-3 | G2 | 录制脚本归属 | 常驻进 scripts/（可重复录制，回归网可持续）vs 一次性手动录制即弃 | 常驻 scripts/，fixture 入 tests/ |
| D-4 | G3 | 收敛范围 | 仅外部成员（风险小）vs 内部 agent 一起收敛（统一但面大） | 仅外部成员先行 |
| D-5 | G4 | 三端落地范围 | 服务端语义+契约文档（移动端按文档跟进）vs 三端代码同批改（鸿蒙/安卓在各自工作树） | 服务端先行+契约文档，移动端另行排产 |

**拍板结果**：D-1～D-5 全部按建议值执行。另用户追加确认：**ACP v2 以「版本协商兼容」最小形式
纳入 G1**（registry 条目声明版本→按声明版本握手；v2 alpha 阶段不全量实现其能力面，正式版另评）；
registry 本身即 G1 卡本体，纳入升级。
**拍板更新（同日二次确认）**：用户拍板「T3 已用 v2 证明可行，升级到 v2 适配」——**升级为全量
适配，新增 G6 卡**（v2 编解码层+版本策略+update 流 24 分支映射，v1 逐字节保持），见 G6 节。

## 3. 明确不做 / 防扩 scope

1. 不引 Effect/不重写编排栈——收敛面是既有机制上的薄契约。
2. 不做编辑器插件、云中继、PTY 终端面（与 T3 对照结论一致：非本仓产品形态或已有既定路线）。
3. 不做 registry 自动下载安装（D-2 建议只登记；供应链风险不做默认开放）。
4. 不为凑方法数把没有真机制支撑的方法写进适配器面（能力不满足=显式不可用）。

## 4. 验收与复评

- 每卡：先红后绿（红灯实证输出进提交说明）+ 分域回归零新增失败 + live-verify（G1 真 registry、
  G2 真录制、G3–G5 真链路）。
- 全部完成后按评测报告 20 子项评分卡做**第三轮复评**（重点 C1 接入广度/C2 能力声明/E3 性能门），
  结果追加「复评记录三」。

---

## 执行记录（按卡补记）

| 卡 | 状态 | commit | 备注 |
|---|---|---|---|
| G1 | **已实施+live-verify** | 本笔提交 | registry.py（fetch 15s/5MiB 上限+UA 自报根修 CDN 403/解析归一/同 id 首个胜出/DCL 单例+stale 降级）+ catalog 合并视图（本地直配>预设>registry，defaultCommand/capabilitiesFor/refuseExecutorSpec/probeTool/listCatalog/probeToolHealth 全命中点改走）+ admin 刷新端点（默认关无定时）+ 条目版本透传握手；真拉官方 registry 46 agents 归一（23 npx/21 binary/2 uvx），真 create_app 刷新后 catalog 8→52 条、非 admin 403；18 例新测试，neuacp 全套 166 绿；顺带吸收 auth-surface 生成物预存漂移（swarm-queue 4 路由） |
| G2 | **已实施+live-verify** | 本笔提交 | scripts/neuacp_record_fixture.py 常驻录制（dogfood 真 NeuacpClient+真 frame_log 脱敏）+ replay_harness.py（ScriptedTransport flush 时点供帧保因果序——实测踩到 write 即可见的假序并修复）+ 10 份真机 fixture（opencode 全 4 场景/claude-code 2/codex 2/gemini-cli 未装如实缺失）+ test_replay_contract 51 用例（含 30 变异注入全红防恒真）+ README 9 条协议陷阱（protocolVersion 整数/真机字段 agentCapabilities/end_turn 词值/鉴权墙两形态等）；neuacp 全套 217 绿 |
| G6 | **已实施** | 本笔提交 | codec_v2.py（出站 6 类 params 构造+入站 24 分支 update 归一，缺关键字段 V2ProtocolError fail-closed）+ acp_client 版本策略（协商整数选 codec，v1 字面量原样）+ acp_executor 按 codec 分发（v1 分支逐字未动；_promptV2 以 state_update(idle) 为收口真源）+ v2_strict_agent 严格校验替身 + test_v2_codec 39 例；**中间红抓出真缺陷：_promptV2 事件循环内阻塞等 idle 卡死 cancel——根修 to_thread**；v1 回归 205 绿 |
| agentCapabilities 扫荡 | **已实施** | 本笔提交 | G2 录制实证真机握手能力字段=agentCapabilities（假 agent 误用 serverCapabilities）→ /test 唯一消费点改规范名优先+旧名兼容，两个测试桩与断言同步；强化断言暂存还原法实证红 |
| 回归 | **已验证** | 本笔提交 | 合并回归 neuacp 全套+external_agents+wire 契约：**293 passed, 2 skipped**（skip=既有未装 CLI 诚实跳过），零新增失败 |
| 复评三 | **已复评（部分达成，差距继续收窄）** | — | 对照 T3 当期主干 `2af43518`（2026-11-20 23:35 -0800；较二轮 `80871270` 前进 25 笔，以修复/projects 多仓特性/perf 为主，20 子项能力面无变化，T3 维持 91.8）完成第三轮 20 子项复评（验收节口径：重点 C1/C2/E3）：Neurova 85.25→**86.0**，净差 6.5→**5.8**。调分三项：**C1 8.5→9.0**（G1 registry 零代码接入——真拉 46 agents 归一、catalog 8→52、版本透传协商+G6 ACP v2 全量适配+G2 真机回放契约+agentCapabilities 规范名扫荡）、**D3 8.5→9.0**（G4 心跳/重放窗口/订阅范围单源+按需订阅账本语义+realtime_push 心跳收口）、**E2 8.0→8.5**（G2 真实 transcript 录制→真 NeuacpClient 管线回放+30 变异注入防恒真的回放兼容纪律）；其余 17 项维持——G3 方法面（adapter_surface 能力闸 fail-closed+steer/交接两处接线）按「接线广度」口径强化 C2 但四方法（rollback/fork/switchModel/snapshot）尚无编排侧调用方，C2 维持 9.0；B2 收敛面换道非新触发点不调分；G5 原生模式纪律经自证系既有覆盖确认，D2 不调分。16 落后（净尾差 11.5）/3 平（B4/D1/E1）/1 反超（A4 +1.0）；逐项证据与判定详见评测报告「## 复评记录三（2026-11-21，第三轮，T3 主干 2af43518）」节 |
