# D19 第二环重扫 —— 2026-10-21

> 本档补 §6-360 自纠②的欠账：上一把尺的候选谓词是"闭包内的 importers 全是门面"，
> 于是**被死岛读**的下游模块连被审的资格都没有（11 档只是已扫出的下限）。本批把"读者是否活"
> **递归进候选构造**，用不动点算死集；只读，不改一行代码。
> **2026-10-21 撤回重做（§6-373）**：用户裁定撤回 §6-371 与本档候选的裁删，按教义 7
> 「取长补短后退役」重做；本档保留为**候选地图**，不是删除清单。
> **2026-10-21 组三处置（§6-380）**：`agent_self` / `memory_stream` 已退役——生产读者 0，
> 显式放弃可持久化核心指令/心跳任务表与独立记忆事件流（live 事件面是 `core.event_bus`）。
> `security` / `temporal_reasoner` **保留待裁**：前者是全仓唯一 Fernet 记忆加密、永久遗忘与
> 记忆审计（`test_memoryCipherFailFast.py` 有守卫）；后者被
> `tests/unit/knowledge/test_conflict_single_implementation.py` 明写为“时序关系级唯一实现、
> 不在 017 删”。三态票与影响面见台账 §6-380。

## 1. 方法（与上一把尺的差别）

- 节点：`neurova/cognitive_layers/memory_layer/` 下 84 个 `.py`（不含 `__init__.py` 门面）。
- 边：模块级 import 图，取 `ast_scan.parsedModules` + `resolveImportModule`，与组件表同一取数口。
- 种子：**没有生产读者**的节点（`outsideLive` 只算 `neurova/` 内非 `__init__.py` 的读者；
  测试读者不算活）。⇒ 零读者与"仅测试"一起入种子。
- 迭代：一个节点若没有 `outsideLive` 读者、且它的**全部层内读者都已在死集**，则加入死集；
  重复到不动点。
- 门面口径：只由 `__init__.py` 读到的模块**不**算活——这正是 D19 的"门面把死岛拖上启动路径"。
- 边界（明写）：模块级取数，不证符号级"导出了但没人用"、不证动态 `importlib` 装载；
  本档只把候选收窄到可逐档复核的面，**不据此直接删码**。

## 2. 读数

不动点：**15 档 / 7198 行**。其中：

- **已知零读者 5 档**（Z1–Z4、Z6，已有五字段档案，直接沿用）：
  `proactive_question.py` 940、`explainability.py` 646、`relation_mixin.py` 400、
  `forgetting_recovery_storage_mixin.py` 347、`modules/emotion_conduction_module.py` 233。
- **不是死岛 2 档**：
  - `pollution_purge.py` 349：测试支撑/运维工具（默认预报、先归档再删），仅测试引用；
    它是**工具**不是产品能力，建议保留（若要收干净，另议移到 `tests/`/`scripts/`，不按死码删）。
  - `temporal_knowledge_graph.py` 449：经 `neurova/agent/tkg_retriever_adapter.py` 接到
    `chat_pipeline.py:300` 的检索链，**在役**；模块级图把它误当门面读者，符号级复核排掉。
- **新候选 8 档 / 3834 行**（本档的主体，均未动码）：

| 文件 | 行 | 层外活读/门面/层内/测试 | 能力（读实现） | 现役替代（初核） | 建议 |
|---|---:|---|---|---|---|
| `security.py` | 809 | 0 / 1 / 0 / 2 | 敏感信息检测、加密存储、被遗忘权、审计日志 | `neurova/security/` 有安全面，但未证覆盖敏感检测/加密/遗忘权；加密链 §6-34 曾判"从未被调用" | 需人裁（倾向删） |
| `vector_search.py` | 726 | 0 / 1 / 0 / 2 | 纯 Python TF-IDF 索引、持久化、缓存 | 在役 `UnifiedVectorStore`（ONNX）＋`NeurovaRecallEngine` | 删（需确认无外部按名取用） |
| `agent_self.py` | 524 | 0 / 1 / 0 / 0 | `AgentSelfManager`：核心指令、心跳任务、DB 存储 | 全仓无同名消费者；`Agent` 侧未接 | 删 |
| `memory_stream.py` | 235 | 0 / 1 / 0 / 1 | 记忆操作实时流、订阅/导出 | 全仓无同名消费者；事件面另有 `EventBus` | 删 |
| `temporal_reasoner.py` | 636 | 0 / 0 / 0 / 1 | 时序关系提取、传递推理、时序矛盾、约束、排序 | `temporal_knowledge_graph` 是**事实存储**，不是这五类推理；无等价替代 | 需人裁 |
| `vector_index_manager.py` | 431 | 0 / 0 / 0 / 1 | 增量同步、异步索引更新、索引生命周期 | `knowledge/vector_index.py` 自述"VectorIndexManager 闲置"；`UnifiedVectorStore` 有索引 | 删 |
| `memory_index.py` | 277 | 0 / 0 / 0 / 2 | 索引/查询深度模块 | `storage.py:161` 已有同名 `MemoryIndex`，本档是其外的第二份 | 删（双源） |
| `memory_record_store.py` | 196 | 0 / 0 / 0 / 1 | 纯 CRUD 深度模块 | `storage.py`/`manager.py` 已承担 CRUD；无生产读者 | 删（双源） |

## 3. 关键证据（逐档初核）

- `security.py`：公开面 `MemorySecurity` 只在 `neurova/memory/__init__.py:60/127` 出现；
  `neurova/security/cognitive_security.py` 的 `MemorySecurityGuard` 是另一个类，不是它的消费者。
- `vector_search.py`：`VectorSearch` 只在 `neurova/memory/__init__.py:44/121` 出现；
  测试两处仅验可导入/初始化；在役召回链走 `UnifiedVectorStore`。
- `agent_self.py`：`AgentSelfManager` 只在 `neurova/memory/__init__.py:38/122` 出现；
  全仓无实例化、无测试引用。
- `memory_stream.py`：`MemoryStream` 只在 `neurova/memory/__init__.py:51/124` 出现；
  一个测试引用；无生产读者。
- `temporal_reasoner.py`：`TemporalReasoner` 在自身文件外零命中；一个测试引用。
- `vector_index_manager.py`：`VectorIndexManager` 在自身文件外只出现在
  `neurova/knowledge/vector_index.py` 的注释（"闲置"）；一个测试引用。
- `memory_index.py`：`storage.py:161` 定义同名 `MemoryIndex`；本档的类只在测试里被用；
  两处同名类不是同一份实现（**双源**）。
- `memory_record_store.py`：`MemoryRecordStore` 在自身文件外零命中；一个测试引用；
  其 CRUD 与 `storage.py` 重叠。
- `temporal_knowledge_graph.py`：`TKGRetrieverAdapter` 在 `chat_pipeline.py:35/300` 接入
  检索链——**在役**，不进候选。
- `pollution_purge.py`：docstring 自述"默认只预报不落手、先归档再删"；两个测试；
  是测试/运维工具，不按死码删。

## 4. 处置建议（等拍板，本批不动码）

1. **裁"删"的 6 档**：`vector_search`、`agent_self`、`memory_stream`、`vector_index_manager`、
   `memory_index`、`memory_record_store`——初核无现役消费者或有明确双源/替代；删除前逐档补
   五字段档案，并同批退役 `neurova/memory/__init__.py` 的再导出行与专用测试。
2. **需人裁 2 档**：`security`（敏感检测/加密/遗忘权是否有产品承诺）、`temporal_reasoner`
   （五类时序推理是否要保留；TKG 不是等价替代）。
3. **保留 1 档**：`pollution_purge`（测试/运维工具；若要归位，另批移到 `tests/` 或 `scripts/`）。
4. **排除 1 档**：`temporal_knowledge_graph`（在役，`TKGRetrieverAdapter` 已接）。

**不可逆点**：六档"删"里 `security`/`temporal_reasoner` 的独有能力若裁删，重新实现要从
敏感模式/加密/遗忘权与五类时序推理重写；`memory_index`/`memory_record_store` 是双源，
删前要先确认 `storage.py` 那份覆盖同一语义（本档只做了同名/职责初核，未逐符号比对）。
**影响面**：全部在 `memory_layer/` 与 `neurova/memory/__init__.py` 门面，不动召回链；
删除后组件表零读者/仅测试计数会再降。

## 5. 复算命令

```bash
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe - <<'PY'
# 见本档 §1：84 节点、15 死、7198 行；门面读者不计活
import ast, sys
from pathlib import Path
sys.path.insert(0, 'tests'); sys.path.insert(0, '.')
from tests import ast_scan
# …按 §1 的种子/迭代规则复算；读数写进台账 §6-372
PY
```
