# external_api.py 客户端拆分报告（2026-09-17）

## Scope

`neurova/collaboration/neurflow/external_api.py`（3299 行）按用户授权边界执行"守卫→拆分→验证→回归"：

- **迁出**（12 类 → `neurova/collaboration/neurflow/external_clients/` 11 个叶子 + 空 `__init__.py`）：
  `ImageGenClient`、`VideoGenClient`、`AmazonSPAPIClient`、`AmazonAdsClient`、
  `TaobaoTopClient`+`XianyuClient`（同 TOP 协议叶子）、`JdOpenClient`、`PddOpenClient`、
  `DouyinEcomClient`、`TikTokShopClient`、`Alibaba1688Client`、`XiaohongshuClient`。
- **保留在门面**：全部 HTTP helpers（`_http_post/_http_get/_http_get_text/_http_client`）、
  异常（`ExternalAPIError`）、全部常量与 KEY_NAMES、凭据解析 helpers、签名 helpers、
  工厂/单例状态（含 `_cn_client_instances` 与各 `get_*/reset_*`）、
  `CommercePlatformClient`、`PublishPlatformClient`、`_OpenGatewayClientBase`（先于叶子 import 就绪）。
- **依赖规则**：叶子对原全局依赖一律 `from .. import external_api as api` 动态读取
  （含 `api._http_post`、`api.resolve_api_key`、`api.logger`、`api.time` 等），
  无旧 helper 静态绑定、无 exec/globals、无代理/子类包装、无业务逻辑改动。
- **身份保持**：门面底部显式 reexport 同一类对象；叶子在类定义后将
  `X.__module__` 显式设回 `external_api`，方法 `__module__` 同步保留（pickle 身份经测试验证）。

## 测试

- 新增 `tests/unit/collaboration/test_external_api_split_contract.py`（27 项）：
  - 原导出/类方法签名/继承身份快照（`external_api_contract_snapshot.json`，拆分前从原文件冻结）；
  - 叶子模块结构（类清单、空 `__init__`、无 `from external_api import` 旧绑定、无 exec/eval/globals 调用）；
  - 导入后 patch 门面 `_http_post/_http_get` 真实命中叶子调用（VideoGenClient 全流程模拟，含
    `get_secret_store` 禁触断言）；
  - 全部 14 组 factory/reset 单一状态验证。
- TDD：结构断言先红（12 failed：叶子缺失）→ 搬移后全绿（27 passed）。
- 网络/凭据全 mock，无生产数据读写。

## 回归

命令与结果（共 411 passed，14.11s）：

```
.venv/Scripts/python.exe -m pytest \
  tests/unit/collaboration/test_external_api.py tests/unit/collaboration/test_amazon_sp_api.py \
  tests/unit/collaboration/test_cn_platform_clients.py tests/unit/collaboration/test_new_platform_clients.py \
  tests/unit/collaboration/test_external_api_store_creds.py tests/unit/collaboration/test_store_connections.py \
  tests/unit/collaboration/test_store_credentials_resolution.py tests/unit/collaboration/test_store_api.py \
  tests/unit/collaboration/test_store_oauth.py tests/unit/collaboration/test_commerce_nodes_store.py \
  tests/unit/collaboration/test_commerce_node_conditions.py \
  tests/unit/neurflow/test_commerce_nodes.py tests/unit/neurflow/test_commerce_nodes_cn.py \
  tests/unit/neurflow/test_commerce_nodes_amazon.py tests/unit/neurflow/test_ad_commerce_nodes.py \
  tests/unit/neurflow/test_drama_nodes.py tests/unit/neurflow/test_drama_nodes_batch4.py \
  tests/unit/neurflow/test_aigc_pipeline_batch4.py tests/unit/neurflow/test_api.py \
  tests/unit/collaboration/test_external_api_split_contract.py -q
```

基线（拆分前同名单）：平台直测 121 passed + 消费者 263 passed；拆分后 411 passed（含 27 项新契约），零降级、零 skip。

## LOC

| 文件 | 变化 |
| --- | --- |
| `external_api.py` | 3299 → 1432 行（git diff +14/-1881，全部为类体删除 + 底部 reexport 块） |
| `external_clients/`（新） | 11 叶 2080 行 + 空 `__init__`，类体搬移，仅自由名改写为 `api.*` |
| 本批生产代码净 LOC | +213（3512−3299），用于独立模块 imports、显式 reexport、保留类及方法的 `__module__` 元数据；测试和快照另计 |

## 限制（如实声明）

- 主控独立复跑 collaboration 整目录及上述 8 个 Neurflow 消费者文件：623 passed（16.72s）。随后补 11 个全新进程导入顺序用例，契约测试合计 38 passed（5.45s）。**未运行全项目套件**，不假称全项目绿。
- 独立审查确认 12 个移出类归一化 `api.*` 后 AST 等价，未发现局部变量误改、工厂状态复制或 patch 静态绑定。
- 导入顺序限制（P2，后续包初始化改造时必须处理）：当前父包预加载 facade，因此 11 个真实新进程 leaf-first 导入均通过；若绕过父包初始化单独加载叶子，leaf→facade→leaf 会产生循环导入。本批兼容入口仍为 `external_api`，不承诺绕过正常包初始化的独立叶子加载。未为了消除此限制扩大共享基类/工厂重构范围。
- 抽取脚本为一次性内联脚本，未落仓；叶子文件为生成物，类体与原文件逐行一致
  （仅全局名加 `api.` 前缀），后续维护以门面为契约源。
- `get_comfyui_client`/`_parse_size`/`_sleep` 等共享 helper 仍留门面，叶子经 `api.*` 读取。
- `NeurUI/src-tauri/resources|target` 下存在同名历史副本文件，未在本次范围（不修改其他文件）。

## 产物与备份

- 原文件备份：`E:\AppData\Local\Temp\extapi_backup\external_api.py.orig`（139,894 字节，与拆分前逐字节一致）
- 运行日志：`E:\AppData\Local\Temp\extapi_backup\{red,green,regression}.log`
- 未提交、未推送；本次未修改列表外任何文件。
