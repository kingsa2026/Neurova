# 企业数据源接入与 MCP 形态方案（备稿 · 2026-11-19）

> **性质**：方案备稿（**只备不实施**，待拍板排期）。范围：把主流 ERP / MES / 进销存 / CRM 作为本体（ontology）数据源接入的路线选型、连接器与映射设计、内置 MCP 工具组、待拍板项与落地批次。
> **一句话结论**：**直连连接器继续作为本体数据源主路径，MCP 只做"接入面智能化"（内置只读工具组）；"外部 MCP server 作为源类型"挂台账缓办，等真实对端出现再立项。**

---

## 1. 背景与动机

### 1.1 行业接口图景（调研结论）

四类系统的数据接口形态高度收敛，横切差异主要在鉴权、数据模型与开放程度：

| 系统 | 主流接口形态 | 代表 |
| --- | --- | --- |
| ERP | REST/OData 为主，老系统 RFC/SOAP/IDoc | SAP（OData/RFC/IDoc）、金蝶 K3Cloud WebAPI、用友 YonBIP OpenAPI、Dynamics 365（OData v4）、Odoo（JSON-RPC）、Oracle NetSuite（REST/SuiteTalk） |
| MES | 分层：设备层 OPC UA/Modbus/MQTT；单据层 REST；数据层 SQL 直读/时序库 | 西门子 Opcenter、罗克韦尔、黑湖智造、新核云、摩尔元数 |
| 进销存 | REST + Webhook，电商开放平台约束强 | 聚水潭、旺店通、吉客云、金蝶精斗云、畅捷通 T+、管家婆 |
| CRM | REST API 成熟度最高，OAuth2 普及 | Salesforce（REST/Bulk/Streaming/Platform Events）、HubSpot、Zoho、销售易、纷享销客 |

共性工程问题（真正决定集成难度）：鉴权（OAuth2 / API Key / 时间戳签名）、限流分页、增量同步（updated_at 水位 / change log / 事件订阅）、幂等去重、单据状态机对齐、最终一致 + 对账。

### 1.2 本仓已有设施（不新造体系的基础）

- **连接器协议**：`neurova/knowledge/enterprise/protocols.py` —— `EnterpriseSourceAdapter` 四动词（describeSchema / fetchBatch / health / close），`ChangeBatch` / `SourceCursor` / `SourceHealth`。纪律钉死：真实连接器必须实现同一 Protocol、输出同一 ChangeBatch、经同一 admission 写口，**不得另造第二套摄取路径**（protocols.py 头注）。
- **工厂与摄取咽喉**：`registry.py` —— `buildAdapter` 唯一工厂（sourceType 白名单 + 变体闭集）；`EnterpriseIngestor.runOnceAsync` 拉取循环（游标成功后才推进、失败不推进、超批如实报 truncated）；`ingestBatch → applyMapping → admission` 唯一写口，逐条 finding、内容键幂等、断言溯源 `mediumRef=source:<id>:<cursor>`。
- **映射层**：`schema_mapping.py` —— R2RML 风格 JSON 描述符（subject 模板 / predicate termId / object kind 闭集），编译期一次判完；值变换闭集 `VALUE_TRANSFORMS`（upper/lower/trim/collapse_ws）与缺失策略 `MISSING_POLICIES`（keep/skip/report）。
- **已落连接器**：金蝶 + 用友 ERP REST（`connectors_erp.py`，凭据只进环境变量、429 具名退避、会话过期重登一次）；SQL 直连五驱动；文件四格式；湖仓三件（unity_catalog / snowflake / sap_odata）；通用 `http_pull`；聊天渠道。`event_stream` 显式缓办（registry.py:79）。
- **持续同步**：`sync_interval_seconds` + `registerIntervalSyncs`（registry.py:416）复用既有调度器，零新同步逻辑。
- **MCP 出向**：`mcp_ontology_server.py` 挂 `/v1/mcp`，双鉴权 fail-closed；工具面由 curated 名册收口（`ontology/mcp_surface.py`，新工具必须点名登记）；纪律"接线不是第二实现"——handler 只转交既有处理函数。
- **MCP 入向**：`knowledge/mcp_source.py` —— 外部 MCP server 作为**文本知识源**（call_tool → 文本拼装 → create_knowledge），不走本体事实链。

## 2. 目标与非目标

**目标**
1. 确立 ERP/MES/进销存/CRM 接入本体的主路径与扩展形态，避免平行体系。
2. 产出内置 MCP 工具组设计（形态 A），让 agent 能自主完成"看源 → 看 schema → 验映射 → 触发同步 → 核对准入"闭环。
3. 产出 `mcp_tool` 源类型预研结论（形态 B）与立项条件。
4. 列清待拍板项（各带影响面与推荐项），供决策。

**非目标（本备稿不做）**
- 不实施任何代码改动；不提交。
- 不在本轮落地 webhook / event_stream 推送（维持缓办原判）。
- 不做 MES 设备层时序数据入本体（见 §6 决策 6）。
- 不做复杂实体消解（跨系统同实体自动合并）——只预留最简声明位。

## 3. 路线对比结论（教义第 7 条：先比后合）

对比"直连连接器（现状主路径）" vs "以 MCP 形式做数据源"：

| 维度 | 直连连接器 | MCP 形式数据源 |
| --- | --- | --- |
| 数据契约 | Protocol + ChangeBatch，结构明确 | 外部工具返回形状无契约保障 |
| 语义映射 | R2RML 描述符 + 编译期校验 | 现有 mcp_source 链无本体映射 |
| 写入口径 | admission 唯一写口、幂等、断言溯源 | 文本链走 create_knowledge，不在事实链 |
| 可测性 | fake adapter + 映射校验 + 游标语义可单测 | 依赖远端 server 桩，schema 漂移不可控 |
| 集成成本 | 每源一次（O(厂商数)） | 理论 O(1)（登记即接） |
| 现实覆盖 | 金蝶/用友/SQL/文件/OData/HTTP 已落 | 厂商官方 MCP server 生态极早期 |
| 无 API 场景 | SQL 直读、文件交换可覆盖 | 做不到（对端必须提供 server） |
| 安全边界 | 凭据只进环境变量、默认关闸、审计内建 | 外部工具返回是**不可信输入**，有注入/污染面 |
| 实时性 | 游标水位 + interval 调度 | call_tool 拉取式，基本打平 |
| 故障定位 | 退避/重登/游标语义显式 | 传输/session/工具错误三层叠加 |

**裁定**：正确性、可测性、安全、当下覆盖面四项直连全占优；MCP 的集成成本优势被现实生态压制。**两者是互补不是重复**：直连解决"结构化业务数据进本体"，MCP 解决"接入过程智能化"与"外部能力生态"。主路径维持直连；MCP 按下文形态 A（先行）/ 形态 B（缓办）分层推进。

## 4. 形态 A：内置 MCP 工具组（推荐先行）

把连接器**能力**（读 + 触发）经既有 MCP server 面暴露给 agent；服务层零改动，handler 只转交 `EnterpriseIngestor` / registry 既有函数。

### 4.1 工具清单（拟新增 curated 名册条目）

| 工具名 | 转交到 | 语义 |
| --- | --- | --- |
| `ontology_source_list` | `EnterpriseIngestor.listConfigs` + `probeHealth` | 源清单 + 健康态；凭据字段脱敏回显 |
| `ontology_source_schema` | `adapter.describeSchema()` | 拉取前探源表/列形状 |
| `ontology_source_sync` | `runOnceAsync(tenantId, sourceId)` | 触发一轮拉取，返回 admitted/rejected/skipped/truncated/cursor |
| `ontology_mapping_check` | `validateDescriptor`（dry-run） | 映射描述符编译期试算，agent 自查映射 |

### 4.2 治理红线（随工具同步落地，不是后续补丁）

1. **管理动作不入 MCP**：saveConfig / deleteConfig / setEnabled / 改凭据 留在 REST 管理面 + admin 鉴权 + 人审。模型面只给"读"与"触发已存在配置"。
2. **租户从身份取**：tool handler 的 tenantId 必须来自调用凭据解析（复用 `mcp_ontology_server.py` 的 `_resolveIdentityFromHeaders` 同族规则）；descriptor 参数里的 tenantId 仅对内部服务身份生效。
3. **同步触发节流**：`ontology_source_sync` 加冷却窗口（参照 S15 冷却做法）+ 可选 agent 白名单；一轮最多 20 批 × 200 行的既有上限不变。
4. **溯源不变**：经 MCP 触发的摄取，`mediumRef` 仍为 `source:<id>:<cursor>`，`activityBasis` 注明 "via mcp"；审计链不因入口不同而断。
5. **凭据零回显**：list/schema 的返回体不含 credentialEnv 的值。

## 5. 形态 B：`mcp_tool` 源类型（预研，缓办）

**设想**：新增 sourceType `mcp_tool` —— `McpToolAdapter` 实现 `EnterpriseSourceAdapter`：`fetchBatch` 调外部 MCP 工具 → 归一为 ChangeBatch 行 → 走同一 `ingestBatch → applyMapping → admission`。`SOURCE_TYPES` 与 `VARIANT_CLOSED_SETS` 相应扩展（闭集纪律不变）。

**立项条件（满足其一才启动）**：
- 出现真实外部 MCP server 形态的业务数据源（某 SaaS 只出 MCP 不出 REST）；
- 需要聚合多个第三方 MCP 数据面且结构可映射为本体术语。

**立项时必须补**：
- **入模前净检闸**：外部工具返回内容先过脱敏/注入检（呼应 reference_x 对照报告 P1"入模前脱敏闸"），再进映射；文本型返回不直接进事实链。
- 与 `knowledge/mcp_source.py` 文本链的边界声明：文本知识归旧链，结构化事实归 enterprise 链；两链不混装、不互串写口。

## 6. 待拍板项（各带影响面与推荐）

| # | 决策 | 选项与影响 | 推荐 |
| --- | --- | --- | --- |
| 1 | 增量游标语义 | A. 维持页码/行水位（现状，全量分页，改动零）；B. updated_at 水位 + 业务键复合游标（协议不动，各 vendor 自编码 token；增量体验好，描述符需声明水位列）；C. webhook 推送（依赖 event_stream 立项，实时性最好，工程量最大） | **B**；C 随 event_stream 另案 |
| 2 | 实体对齐策略 | A. 外部 ID 直拼 subject（现状，同实体跨系统成多节点）；B. 命名空间前缀 + 描述符声明同义业务键列（最简对齐，映射层小改）；C. 独立 identity resolution 服务（重，另立项） | **B**；C 挂台账 |
| 3 | 值变换闭集扩展 | A. 不扩（映射表达力不足，业务字段适配会绕路）；B. 扩纯函数闭集：`epoch_to_iso` / `cents_to_yuan` / `enum_map` 等（函数进代码可测试，描述符只引用名，保持"映射无可执行逻辑"纪律） | **B**，随首批业务域按需加 |
| 4 | 变更准入语义 | A. 变更产生新断言（supersede 旧值，保历史）；B. 覆盖旧断言。影响：fact store 读侧（recall/图谱）是否默认取最新版本——若读侧不分辨会出现"同实体两地址并存" | **A**，但需先核实读侧取最新语义（动手前验证项） |
| 5 | `ontology_source_sync` 开放范围 | A. 全部 agent；B. agent 白名单 + 冷却；C. 仅 admin 身份可触发 | **B**（白名单 + 冷却） |
| 6 | MES 设备层数据 | A. 时序数据入本体（污染语义断言、量大）；B. 设备层数据走指标/时序面，本体只落"设备-工单-批次"静态关系与状态变更事件 | **B** |

## 7. 落地批次建议（拍板后展开为工单）

- **P0 打通样板**：金蝶销售订单端到端（源配置 → 映射描述符 → admission → 图谱/nl2sql 可查），验证映射表达力（决策 3 的变换需求由此导出）；同步落 `ontology_source_list` / `ontology_source_schema` 两只读工具（零风险验证 curated 名册 + 鉴权 + 租户链）。
- **P1 CRM 与增量**：OAuth2 鉴权半边（token 刷新）+ 第一个 CRM vendor（Salesforce 或销售易）；updated_at 水位复合游标（决策 1B）；`ontology_source_sync` 上线（白名单 + 冷却，决策 5）。
- **P2 进销存与自查**：进销存 http_pull 适配样板（含幂等业务键约定）；`ontology_mapping_check` 工具；webhook / event_stream 立项预研（只出报告）。
- **台账缓办**：`mcp_tool` 源类型（形态 B）、MES 设备层、identity resolution 服务、`knowledge/mcp_source` 与 enterprise 链的归并评估（若做须按先比后合走 §7 固定顺序）。

## 8. 风险与红线

1. **不另造第二套摄取路径**——一切新源类型/新入口必须落到 `EnterpriseSourceAdapter` Protocol + admission 唯一写口。
2. **凭据纪律**——描述符只存环境变量名；日志不落凭据与响应全文（`connectors_erp.py` 既有纪律全量沿用）。
3. **模型面最小化**——curated 名册收口，管理动作永不进 MCP 工具面。
4. **外部内容先净检再入模**——形态 B 的前置闸，不可后补。
5. **游标失败不推进**——沿用既有语义，避免静默丢数。
6. **每批先红后绿 + live-verify**——新 vendor 连接器以假 server 契约测试开路，真环境端到端验证收尾。

## 9. 执行记录

（待拍板后回填：批次、commit、红绿证据、live-verify 记录。）
