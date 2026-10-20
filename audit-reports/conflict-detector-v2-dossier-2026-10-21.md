# `conflict_detector_v2` 补档 —— 2026-10-21

> 本档是 §6-360 自纠①开出的欠账：上一批把该模块判活的两条证据（`conflict.py:260` 同名别名定义行、
> `neurova/memory/__init__.py:19` 聚合门面再导出）复算后均为伪命中。本批按死码口径补五字段档案，
> **只读，不改一行代码**。✅＝主会话当场复算；本档无 ◑ 条目。
> **后续裁定（2026-10-21）**：用户选乙——同属性异值判据并入 `conflict.py:judgeClauseConflict` 后退役 v2；
> 实施与证据见台账 §6-370。本档 §1 的「判定：需人裁」保留为当时快照。

## 0. 当次读数（写前现场取）

| 项 | 读数 | 取法 |
|---|---|---|
| 模块行数 | **265** | `wc -l` |
| 生产侧直读模块的档 | **0** | 组件表 `outsideReaders=0`；`importersOfModule` 单点复核：`neurova/` 内仅 `memory_layer/__init__.py:33`（相对形门面再导出） |
| 层内直读 | 1（门面） | 同上 |
| 测试直读 | 2 档 / 7 处 import | `tests/test_memory/test_moe_router.py:368/395/422`、`tests/unit/memory/test_memory_safety_net.py:23/130/139` |
| 聚合名消费者 | 0 | 全仓 `from neurova.cognitive_layers.memory_layer import ConflictDetector` 仅 `neurova/memory/__init__.py:19` 与 `tests/unit/memory/test_memory_safety_net.py:32` |
| 组件表状态 | **仅层内** | `scripts/ci/cognitive_component_table.py` 现读 |

## 1. 五字段档案

### A7 `neurova/cognitive_layers/memory_layer/conflict_detector_v2.py`（265 行）✅

- **原功能**（逐能力）：
  1. `detect(results)` 把一组检索结果切成**三分区**：冲突组 / 独立记忆 / 演进链，返回三值元组（`:50-114`）；
  2. **同属性不同取值**判矛盾：正则抽 `X 是/为 Y`、`X 使用/采用/用 Y`、`X 升级到/更新到/改为 Y` 三组属性（`:198-214`），同键异值即矛盾（`:169-184`）；
  3. **演进链**：相似度与实体重叠双阈值都过、且时间先后成立时串成链；无时间戳时**退回 id 字典序**（`:186-196`）；
  4. 相似度＝中文字符集＋英文词的 Jaccard（`:116-136`）；实体重叠＝中文连续段＋英文词＋专名首字母大写的 Jaccard（`:138-167`）；
  5. 冲突组带组级读数 `entity_overlap` / `semantic_similarity`（`ConflictGroup:19-27`），组按 `mem_a` 归属合并（`:235-252`）；
  6. 构造参数 `sim_threshold=0.8`、`entity_threshold=0.5`（`:39-48`）。
- **关键入口**：`ConflictGroup:19`、`ConflictDetector:30`、`detect:50`、`_is_contradictory:169`、`_extract_attributes:198`。
- **来历**：`2482c042`（2026-06-03「添加完整的项目核心文件」）批量引入——`git log --diff-filter=A` 唯一添加笔。
  **生产侧从未接线**：全史唯一消费者 `result_processor.py`（`:17` import、`:63` 实例化、`:100` 调 `detect`）本身
  只有测试 import；`git grep result_processor 0c333a76^ -- neurova/` 只命中它自己的定义与 `__main__` 演示（`:235`），
  `git log -S "from neurova.cognitive_layers.memory_layer.result_processor" --all -- neurova/` **零命中**。
  `0c333a76`（2026-09-21「温度衰减双实现收敛…清退 5 组死码」）删掉 `result_processor.py`，
  退役报告记「生产 0，逐个按类名复核」并把 MoE 检索面的真实消费方改指 `MoERetrieverAdapter`
  （`docs/05-reports/memory-temperature-convergence-2026-09-21.md:78,92`；后者现役于
  `neurova/agent/chat_pipeline.py:254`、`neurova/agent/memory_retrieval_chain.py:158`，不使用 v2）。
  ⇒ 文件级形态是「唯一消费者被摘」，但生产口径应写作「**引入即未接线**」——§6-360 那句
  「曾被消费后被摘」对生产是过宽的表述，本档就地收窄（原文不回改，指向本档）。
- **现役替代**：**部分缺**。
  - 已有：`conflict.py:122 judgeClauseConflict` 是记忆侧声明式单源判据，`LegacyConflictDetector:141`
    经 `agent_core.py:406-409` 装配、`agent_core.py:942` 起 `PostChatPipeline`，
    在 `post_chat_pipeline.py:2439-2490` 作**纯观测**运行（`blocking=False`，见
    `tests/unit/agent/test_conflict_detection_observation_only.py`）；`modules/conflict_module.py:136-143` 同源调用。
  - 缺：①同属性不同取值（probe：`项目使用 PostgreSQL 数据库` vs `项目使用 MySQL 数据库`
    → v2 报 `contradiction`，live `judgeClauseConflict` 返回 `None`）；②演进链（probe：Python 3.10 vs 3.12
    → v2 出一条链，live 无对应物）；③三分区／组级读数／注入文本这一段编排（原挂在已删的
    `ResultProcessor` 上）。反向也有盲区：v2 对「我喜欢咖啡／我不喜欢咖啡」因实体重叠为 0 直接跳过，
    报两条独立；live 判据命中 `negation_conflict`（两向 probe 均已跑）。
  - 同域第三份实现 `channels/conflict.py:25` 不构成替代：它按空格分词、要求共享词 ≥2，
    中文整句无空格 ⇒ 恒不触发；且它所在的 `channels/processor.py` 本身是 D19 A3 的死岛。
- **判定**：**需人裁** —— 全仓唯一实装且无现役替代；但生产侧从未接线，"要不要保留这项能力"属产品口径，
  不能按行数自行关掉。推荐路径见 §4（乙：把唯一缺的判据并进单源后退役；不推荐原样留着当第三份实现）。

## 2. 能力对照（当场 probe，主会话）

| 场景 | v2 `detect()` | live `judgeClauseConflict` | `channels/conflict.py` |
|---|---|---|---|
| PostgreSQL / MySQL 同属性异值 | 冲突组 `contradiction` | `None` | 中文无空格 ⇒ 不触发 |
| 我喜欢咖啡 / 我不喜欢咖啡 | 两条独立（实体重叠 0） | `negation_conflict` ✅ | 中文无空格 ⇒ 不触发 |
| Python 3.10 / 3.12 + 时间先后 | 演进链 `[v1, v2]` | 无此概念 | 无 |
| 无关两条 | 独立 | `None` | 不触发 |
| `version` 类型 | **从未产出**（`conflict_type` 只被赋 `contradiction`） | — | — |

## 3. 审计中发现的缺陷（单列，不折算成简化收益）

1. **文档声称三类冲突，实现只产出两类**：模块 docstring 与 `ConflictGroup:25` 注释写了
   `contradiction | evolution | version`，但全文件没有任何一处把 `conflict_type` 赋成 `"version"`
   （`grep -n version` 只有 `:25` 那一行）；probe 也确认 `version` 从不出现。
2. **测试自称「活跃版本」，断言只有形状**：`tests/unit/memory/test_memory_safety_net.py:22`
   写「活跃版本」，实际只断 import／初始化字段；同档 `:49-50` 的「死代码不被导入」断言以 `or True` 结尾＝恒真。
   该档来历是 `4a3c9380`（2026-09-04「移除 .gitignore 的 /tests/ 整目录忽略 — 809 个正式测试文件入库」）
   整批入库，不是一次评审过的保留决定——按死码口径不得当活证据。
3. **同域三份检测器并存**（`docs/specs/2026-09-21-memory-knowledge-foundation-audit.md:209` 已点名）：
   `LegacyConflictDetector`（在役、观测）、`conflict_detector_v2`（未接线）、`channels/conflict.py`（死岛内）。
   与教义第 6 条冲突；v2 是其中唯一还有独有能力的一份。
4. **参考层文档留了「保留」承诺**：`docs/01-architecture/cognitive-graph-one-step-design.md:62`
   写 `conflict_detector_v2.py # 保留（独立功能）`；该文档在 `docs/INDEX.md:88` 标「参考」，不是权威源，
   但若走退役需同步标注，否则又是一条「文档说有、代码没有」。

## 4. 处置路线与决策影响面（等拍板，本批不动码）

- **甲 · 直接删净**：删 265 行 ＋ `memory_layer/__init__.py:33` 再导出行 ＋ `neurova/memory/__init__.py:19`
  聚合导入；同批退役 9 个测试格（safety-net 6 格、moe_router 3 格）与其 import；重生成组件表。
  生产池净 **−265**；现役行为零变化（生产读者 0，A/B 预期零差集）。**永久失去**：同属性异值判据、
  演进链、三分区与组级读数。**不可逆点**：删除后要恢复得重写 `_extract_attributes` 与分组/链三段。
- **乙 · 先并判据再退役（推荐）**：把「同属性不同取值」这一支并进 `conflict.py:122 judgeClauseConflict`
  （返回第三类信号并带 `basis`），补三向测试（Postgres/MySQL 必中、Python 3.10/3.12 不得误报、
  无关对不得误报），再删 v2 与 9 个测试格。**能力保留、第三份实现消失、单源仍是 `judgeClauseConflict`**。
  代价：`post_chat_pipeline` 的观测面会变宽（冲突记录与 `/memory/stats` 读数可能增加，仍 `blocking=False`），
  这是**产品语义变化**，须先裁"要不要扩大观测面"。数据流：检索/落库后的记忆对 → 单源判据 → `record_conflicts`。
- **丙 · 原样留**：不动 265 行，只修 §3-2 的假「活跃版本」标签与 §3-1 的假三类声明，并登记为未接线。
  代价：第三份检测器继续以"独立功能"名义存在，下次审计还会把它当候选；不推荐。

**建议**：要能力 ⇒ 乙（取长补短＋接通＋退役，教义第 7 条一次走完）；不要能力 ⇒ 甲（一次退净，不留半成品）。
丙只适合"这一轮不想碰"时的登记态。

## 5. 复算命令（引用方须重跑，别抄本档数字）

```bash
wc -l neurova/cognitive_layers/memory_layer/conflict_detector_v2.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'scripts/ci')
from cognitive_component_table import componentRows
print([r for r in componentRows() if 'conflict_detector_v2' in r['path']])"
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'tests')
from ast_scan import importersOfModule; from pathlib import Path
print(importersOfModule(Path('.').resolve(), 'neurova.cognitive_layers.memory_layer.conflict_detector_v2'))"
```
