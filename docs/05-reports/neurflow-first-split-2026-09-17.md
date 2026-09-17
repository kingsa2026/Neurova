# Neurflow 首批拆分记录（2026-09-17）

## 范围与决策

已完成 Phase0 路由/结构守卫及两个低耦合域的原文搬移：

- `neurova/api/endpoints/neurflow_stores.py`：stores CRUD、连接测试/刷新、OAuth，9 条路由。
- `neurova/api/endpoints/neurflow_triggers.py`：webhook 装配工厂、入站、trigger CRUD/fire、delivery 查询和重试，9 条路由。
- 聚合器在原位显式 include：stores 最前；trigger 前六条在原 trigger 段；delivery retry 三条仍在末尾。后两段在同一叶子中分别使用 router/deliveries_router，避免跨过 versions/checkpoint/otel 改变优先级。
- 不引入 DomainSpec 框架、不 exec、不共享 globals。叶子调用时导入 `neurflow_api as api`，读取已存在的 patch 接缝；函数/模型/常量均显式 reexport。
- 高耦合域 **未拆**：workflow CRUD/ownership、执行与调试、节点、版本/checkpoint、workflow-agent 桥接、OTel 等保留原位。事件录制器与 workflow-agent/webhook provider 装配仍由聚合器完成。

选择简单 include 而非框架，是因为只有两个叶子，触发器有两段注册位置。若未来决定放弃聚合器 patch 兼容，应先迁移消费方及测试，再移除动态接缝；本次不先行破坏兼容。

## 不变量与隔离

- 65 条有序 method/path/name、operation ID、endpoint 签名、装饰器参数和 docstring 快照一致；`{node_type:path}` greedy 顺序不变。
- `_get_storage` 保留主控先行修复：函数属性 `_instance` 缓存，首次实例化动态读取底层 `storage.NeurflowStorage`。未改动 `test_storage_binding.py`，未删除 conftest 双 patch。
- `_get_store_manager`、OAuth helper、`_get_storage`、`get_workflow_executor`、`_get_retry_service`、webhook 限流缓存等调用时 patch 实际命中；`get_dag_validator/get_node_registry/get_agent_instance/_DEBUG_SESSIONS` 公私接口保留。
- OAuth 仍先创建 pending store、写 state；callback 仍先 pop/校验 state、换 token、更新凭据并重定向。测试使用 mock token exchange 或底层 HTTP mock，不请求真实平台。使用既有 autouse 临时库隔离和测试自建 FastAPI，不启动业务 app/真实服务。
- 92 个原有函数/类经 AST 对照一致（只归一化新增调用时 `api` 别名及 deliveries router 名）。无原业务分支删除、吞错新增或默认值降级。
- 现有 knowledge/growth 结构守卫 10 条通过且未修改；Neurflow 专属守卫允许调用时 aggregator import，禁止模块顶层反向 import 与叶子互相 import。

## TDD 与回归证据

原文备份及所有输出位于：
`E:/AppData/Local/Temp/neurflow-first-split-bx04deer/`

| 文件 | 结果 |
| --- | --- |
| `neurflow_api.baseline.py` | 搬移前 2381 行原文（含主控 storage 改动） |
| `baseline.txt` | 拆分前 stores/OAuth + tests/api/neurflow：66 passed |
| `red.txt` | 首版测试 3 failed，其中 unique_id 测试公式多一个下划线 |
| `red-guards.txt` | 修正测试公式后：1 passed（65 路由），2 failed（两叶子缺失）；随后才移动生产代码 |
| `green1.txt` | 移动后 2 passed / 1 failed：快照把 router 变量名误当契约；保持所有装饰器参数，仅明确识别 delivery 分段 router 名 |
| `green-domains.txt` | 初版 3 守卫 + 原 66 用例：69 passed |
| `regression-core.txt` | 扩展后的 8 契约/patch 守卫、存储/neurflow/trigger/ownership/store/agent consumer：202 passed |
| `regression-consumers.txt` | API、step-run、OTel、commerce、comfyui、注入及现有结构守卫：145 passed |
| `green-final.txt` | 最终 8 契约守卫 + 主控 storage binding：9 passed |
| `ast-equivalence.txt` | 92 个原函数/类等价检查及名称清单 |

不重复计算重叠项，精准回归覆盖 **413 个不同用例（66 + 202 + 145），全部通过**。最终守卫再次通过。`git diff --check -- neurova/api/endpoints/neurflow_api.py` 通过。

### 可复验命令（Git Bash，仓库根目录）

```bash
PY='E:/项目/Neurova/.venv/Scripts/python.exe'
$PY -m pytest tests/unit/neurflow/test_domain_split_contract.py tests/unit/neurflow/test_storage_binding.py -q --tb=short
$PY -m pytest tests/unit/collaboration/test_store_api.py tests/unit/collaboration/test_store_oauth.py tests/api/neurflow -q --tb=short
$PY -m pytest tests/unit/neurflow/test_domain_split_contract.py tests/unit/neurflow/test_storage_binding.py tests/unit/neurflow/test_storage.py tests/unit/neurflow/test_api.py tests/unit/neurflow/test_workflow_triggers.py tests/unit/neurflow/test_workflow_ownership.py tests/unit/neurflow/test_workflow_ownership_v2.py tests/unit/neurflow/test_trigger_bootstrap.py tests/unit/neurflow/test_cron_trigger.py tests/unit/workflow/test_trigger_contract.py tests/unit/agent/test_tool_workflow_agent.py tests/unit/collaboration/test_p0_7_workflow_hardening.py tests/unit/collaboration/test_store_connections.py tests/unit/collaboration/test_store_credentials_resolution.py -q --tb=short
$PY -m pytest tests/unit/api/test_endpoints_module_layering.py tests/unit/api/test_api_resource_leak_fixes.py tests/unit/api/test_background_task_reference.py tests/unit/api/test_canvas_definition_bridge_api.py tests/unit/api/test_custom_nodes_and_nl_origin.py tests/unit/api/test_execution_events_stream.py tests/unit/api/test_workflow_canvas_integration.py tests/unit/workflow/test_step_run.py tests/unit/core/test_otel_bridge.py tests/unit/collaboration/test_commerce_nodes_store.py tests/unit/collaboration/test_commerce_node_conditions.py tests/unit/collaboration/test_comfyui_api.py tests/unit/neurflow/test_drama_nodes_batch4.py tests/unit/neurflow/test_resolution_context_injection.py -q --tb=short
```

## LOC 去向

以本次搬移前、已含主控 storage 修复的实际源码为基线：

| 文件 | 行数 |
| --- | ---: |
| baseline neurflow_api.py | 2381 |
| 拆分后 neurflow_api.py | 1771（-610） |
| 新 neurflow_stores.py | 303 |
| 新 neurflow_triggers.py | 419 |
| 三生产文件合计 | 2493（净 +112） |
| 新 test_domain_split_contract.py | 157（测试不计生产 LOC） |
| 新 route_contract_snapshot.json | 522（测试快照不计生产 LOC） |

生产净增 112 行是显式 reexports/include、两叶子独立导入与 router 定义、调用时兼容 patch 接缝所需，未新增业务框架/业务分支。聚合器减小约 26%；本次为模块拆分，不声称运行性能提升。

## 已知限制 / 未完成项

- 全 tests/unit/neurflow 目录未重复运行：主控已报告 701 collected 后在 `test_approval_reply_mechanism.py` 30 秒超时，并用原实现 A/B 复现相同超时，登记为预存。本执行阶段未自行重复该 A/B，也不把全目录称为通过；原始 A/B 日志由主控持有。
- 本次精准相关回归无新增或预存失败；高耦合域后续拆分不属本次范围。
- 未 commit/push/stash，未回滚或修改其他工作树改动；只有本文为本任务新增文档，未修改其他既有文档。
