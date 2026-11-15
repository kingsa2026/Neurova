---
name: neurova-ontology-query
description: >-
  通过 Neurova 本体语义层查询业务含义、预检问题可答性、提交业务断言并
  （在已开闸的部署上）对已连接数据源做只读问数。适用于 MCP 或 REST 接入。
version: "0.1.0"
---

# Neurova 本体语义层查询技能

## 用途

让外部代理 harness 以受治理的方式使用 Neurova 的本体世界模型：先确认部署
就绪，再查业务词含义，先做覆盖度预检，然后才提问/提交断言。所有读写按
调用凭据的租户隔离。

## 前置

- 一个运行中的 Neurova 部署（后端 9527）；
- MCP 客户端（连 `<base>/v1/mcp`，服务令牌/API key/JWT 三选一）或
  已登录的 REST 会话。

## 指引（按序）

1. **就绪预检**：`ontology_readiness`（MCP）或
   `GET /api/v1/knowledge/ontology/readiness`（REST）。`knowledge_ready=false`
   时先登记术语/导入事实；`data_ready=false` 时先注册企业源并刷新 schema 目录。
2. **查业务词**：`ontology_query`（MCP）或 `GET /api/v1/knowledge/ontology/terms`。
   先弄清「订单」「收入」这类词在本部署里映射到什么，再提问。
3. **可答性预检**：`ontology_answerability`（MCP）或
   `POST /api/v1/knowledge/ontology/answerability`。coverage 低于阈值时
   **向用户澄清或换问法**，不要硬答。
4. **提交断言**（需要写）：`fact_submit`（MCP）。提交前先 `ontology_validate`
   自查；被逐字可核闸拒绝时按 finding 修改，不要绕闸。
5. **问数**（仅当部署开启）：`POST /api/v1/knowledge/enterprise/sources/{id}/nl2sql`。
   该能力默认关（`NEUROVA_NL2SQL_ENABLED`），403 时如实告知用户未开闸，不要重试。
   答案自带 SQL 与步骤；`status=refused` 表示目录覆盖不了或生成失败，如实转述。

## 边界与事实源

- **工具清单以 MCP handshake 实时返回为准**（curated 名册见仓内
  `neurova/knowledge/ontology/mcp_surface.py`）。本技能不复抄工具表；
  与 handshake 冲突时以 handshake 为准。
- MCP 侧除 `fact_submit`/`ontology_act` 外均为只读；写面走治理闸与审批流。
- 问数只读：生成 SQL 过只读校验与目录表白名单，行数强制收敛；不可答时
  诚实拒答（`status=refused` 带原因）。
- 多轮对话中同一业务词含义可能随租户/Agent 域不同而不同——不要跨域复用结论。

## 故障排查

- 401：凭据缺失或不成立（fail-closed）——检查三段凭据之一。
- 403（readiness/answerability 以外）：多数是治理动作权限不足或能力未开闸，
  详情看响应 `detail`，不要盲目重试。
- `ontology_query` 命中为空：先确认租户；本体按租户分区，跨租户不可见。
