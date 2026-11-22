# 本体教程 2 · 规则与推理：前向链、溯因、反向链与解释

> 离线可跑的配套示例：`examples/ontology/example_2_rule_derivation.py`
> （注册传递规则 → 2 事实 → 前向链推出 → 解释生成 → 撤销前提 → 精确撤销验证）。

## 1. 这是什么

`ForwardChainingEngine`（`neurova/knowledge/ontology/rule_engine.py`）是
规则登记与求值的唯一入口。规则是作者刻意写下的工件：登记时一次判完形状、
变元与层序，坏规则进不了表。

一条规则 = **头（head）+ 正文（body）**：

- 头：`headPredicate` + 头主语变元（缺省 `X`）+ 可选头客体常量；
- 正文：原子列表，每个原子是
  `{"atom": 谓词, "subject": 变元, "object": 变元}`（肯定原子）或
  `{"not": 谓词, "subject": 变元, "object": 变元}`（分层否定原子）；
  条件类原子可把客体钉成常量：`{"atom": 谓词, "subject": "X", "objectConst": "..."}`。

推导出的事实**经写咽喉入库**（带血缘、置信、主体消解），不直插 SQL——
直插等于造出「没有主体消解、没有血缘、没有置信」的孤儿结论。

## 2. 三种规则形状

### 2.1 relay（接力链，缺省形状）

正原子按「上一跳客体 = 下一跳主体」接力，头客体取末原子客体。
传递推理就是它：

```python
import tempfile
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

store = KnowledgeFactStore(tempfile.mkdtemp() + "/kb.db")
OntologyTermRegistry(store).register("part_of", "relation", label="属于")

engine = ForwardChainingEngine(store)
engine.registerRule(
    "part_of_transitive", "part_of",
    [{"atom": "part_of", "subject": "X", "object": "Y"},
     {"atom": "part_of", "subject": "Y", "object": "Z"}],
    headSubjectVar="X")
```

正文最多 2 个正原子（缺省语言）；确需 3 原子接力链，登记时显式声明
`evaluationStrategy="rete_network"`（U5 放宽档，仅该档放行 3 原子）。

### 2.2 conjunction（同主体合取 ⇒ 条件类）

正原子共享头主语变元、客体全为常量；头谓词必须是类型断言 `is_a`，
头客体是常量 concept 术语。语义 = 同主体同时满足一组条件 ⇒ 它是某类：

```python
registry = OntologyTermRegistry(store)   # 规则是作者工件：谓词与结论类先登记
registry.register("hasRiskLevel", "relation", label="风险等级")
registry.register("is_unpatched", "relation", label="未打补丁")
registry.register("RiskyAsset", "concept", label="高风险资产")

# X hasRiskLevel high 且 X is_unpatched yes ⇒ X is_a RiskyAsset
engine.registerRule(
    "risky_asset", "is_a",
    [{"atom": "hasRiskLevel", "subject": "X", "objectConst": "high"},
     {"atom": "is_unpatched", "subject": "X", "objectConst": "yes"}],
    headSubjectVar="X", headObjectConst="RiskyAsset")
```

条件类的 authoring 闸（`_validateConditionClass`）要求：头谓词必须是 `is_a`、
头客体常量必须是已登记 concept、正文各原子谓词必须已登记、正/否原子主语
都钉在头变元上且客体为常量。条件类规则登记即对存量事实触发一次推导
（`_fireConditionClassAcrossAgents`）。

### 2.3 inverse（反向补边）

恰好 1 个正原子，头主语变元 = 正原子**客体**变元、头客体 = 正原子主语变元：

```python
registry.register("located_in", "relation", label="位于")
registry.register("hosts", "relation", label="承载")
# X located_in Y ⇒ Y hosts X（头主语取正原子客体变元 Y）
engine.registerRule(
    "located_in_inverse", "hosts",
    [{"atom": "located_in", "subject": "X", "object": "Y"}],
    headSubjectVar="Y")
```

术语表上声明 `inverseOf`/`symmetric`/`transitive` 后，`ensureAutoRules()`
会自动生成同语义的 `auto_*` 规则（B8）——手工再登记一份就是两个事实源，
不要重复写。

### 2.4 分层否定

`{"not": 谓词, ...}` 原子做「不存在更优说法」式判定；规则图经否定形成
循环时分层无解，登记直接拒绝（`RuleError: 规则 ... 经由否定形成循环`）。
分层号（`stratification_level`）决定求值顺序：先算低层，再算依赖它的否定层。

## 3. 前向链：写入即推理

生产链路上，事实经写咽喉（`productionAdmissionGate(...).admit(...)`）落库后，
段 3 后半自动 `fireFor(agentId, predicate)`——只点燃 body 依赖该谓词的规则，
到不动点为止。批量重算用 `fireAll(agentId=..., tenantId=...)`（semi-naive
增量：首轮全量，此后只点燃与上一轮 delta 相交的规则）。

推导结论的可见性由**物化档位**（`materialization`）决定：

- `observe`（缺省）：结论只在解释链/审计里可见，检索主路按观察态排除；
- `enforce`：结论即便全局灰度关闭也进检索主路（带 `via_derived` 标注）。

多条规则共同推出同一结论时按保守侧处理：任一来源是 observe 就不进主路。

## 4. 溯因、反向链与解释生成

```python
from neurova.knowledge.ontology.abduction import explainGoal
from neurova.knowledge.ontology.backward_chaining import proveGoal
from neurova.knowledge.ontology.explanation import explainDerivation

# ① 解释生成：沿推导账本回溯「这条结论怎么来的」（中文模板，纯只读）
report = explainDerivation(store, derived_fact_id)
print(report["text"])
# 例：结论 螺丝A part_of 整机X 由规则 part_of_transitive
#     从前提 主板M part_of 整机X、螺丝A part_of 主板M 推出

# ② 溯因：目标三元组 → 匹配 head 的规则递归展开，产出解释树 + 缺失前提清单
goal = explainGoal(store, "螺丝A", "part_of", "整机X", agentId="default")
print(goal["satisfied"], goal["missing"])   # 只读不写事实——解释是候选不是断言

# ③ 反向链：目标可否被证明（事实或规则链），返回证明树
proof = proveGoal(store, "螺丝A", "part_of", "整机X", agentId="default")
```

三者都是**只读面**：不写事实、不落台账。深度上限
（`NEUROVA_ONTOLOGY_EXPLAIN_DEPTH`，缺省 32）与分支上限
（`MAX_ABDUCTION_BRANCHES=50`）超限时显式截断并记入 `missing`
（reason=cycle/depth/分支上限截断），不静默。

## 5. 常见错误

- **原子接不上**：relay 形状要求 `positive[i]["object"] == positive[i+1]["subject"]`
  （同一个变元字母），接不上登记即拒。
- **正文超 2 个正原子**：缺省语言是三元组接力片段；更长链条拆成多条规则
  逐层推，或显式 `evaluationStrategy="rete_network"`（最多 3 原子）。
- **条件类头谓词不是 `is_a`**：conjunction 形状的头必须走结构层固定的
  类型断言谓词，且 `headObjectConst` 必须是已登记 concept——规则是作者
  工件，术语未登记就建规则直接拒。
- **`headObjectConst` 用在非 conjunction 形状**：该参数只属于条件类。
- **否定成环**：`A ⇐ not B`、`B ⇐ not A` 这类规则分层无解，登记即拒。
- **绕过咽喉自插推导事实**：引擎不接 `gateFactory` 时求值会显式报错
  （`推理未接咽喉写入口`）——推导事实必须带血缘入库。
- **改版不清账**：同 `ruleId` 换 `version` 重登记时，旧版结论由账本
  `retractRuleVersion` 自动撤销；自己绕开版本号原地改 body，两版规则会
  各推一套同时对外。

## 6. 边界与诚实声明

- **不是完整 OWL RL / SWRL 推理机**：本引擎覆盖三元组接力、同主体合取、
  反向补边、分层否定这一片段；不做存在量词、基数推理、数据类型推理。
- **正文长度**：缺省 ≤2 正原子，`rete_network` 档 ≤3；更长的链请拆规则。
- **物化档位默认 observe**：推导结论默认不进检索主路；要让某条规则的结论
  进主路，登记时显式 `materialization="enforce"`（该选择经审计可回退）。
- **精确撤销**：撤销一条前提（`store.retract(factId)`）时，账本沿前提边
  逐层撤销依赖它的推导结论（保守侧——多退的下一次求值会长回来）。
- 配套示例 `example_2_rule_derivation.py` 可直接跑通「登记 → 推导 → 解释 →
  撤销 → 验证」全链。
