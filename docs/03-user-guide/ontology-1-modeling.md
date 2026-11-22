# 本体教程 1 · 建模入门：术语、层级与关系特征

> 离线可跑的配套示例：`examples/ontology/example_1_build_and_validate.py`
> （建 3 术语 + 2 形状 + 过咽喉写 3 事实 + SHACL 报告，`.venv` 直跑无需网络）。

## 1. 这是什么

本仓的本体层把「有哪些概念、有哪些关系、谁的父类是谁、定义域值域是什么」
做成**数据库里的行**（`ontology_terms` 表），而不是写死在代码里的 Enum。
加一种类型 = 往表里登记一行，不需要改源码发版本。

唯一读写面是 `OntologyTermRegistry`
（`neurova/knowledge/ontology/term_registry.py`）。术语分三类：

| kind | 含义 | 典型用途 |
|------|------|----------|
| `concept` | 概念/类型 | 主体挂类型（`is_a` 断言的客体） |
| `relation` | 关系谓词 | 三元组的谓词位 |
| `property` | 数据属性 | 挂在关系上的限定键 |

一条刻意的保守原则：**未登记的术语不算违规，只算「这一维没依据」**。
校验（`validation.py`）对未登记谓词免检，巡检读数里如实报 `unregistered`。
拿「没登记」当「不合法」，等于让注册表覆盖率决定写入是否可用——那是把治理
做成随机拒绝，本仓不这么做。

## 2. 最小代码示例

```python
import tempfile
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

store = KnowledgeFactStore(tempfile.mkdtemp() + "/kb.db")
registry = OntologyTermRegistry(store)   # 构造期自动播种 core 种子术语

# 概念 + 层级：router 的父类是 device
registry.register("device", "concept", label="设备",
                  definition="可联网的硬件设备")
registry.register("router", "concept", label="路由器",
                  parentTermId="device",
                  definition="在网络间转发数据包的设备")

# 关系：定义域 + 基数（cardinality=1 即函数属性）
registry.register("has_serial", "relation", label="有序列号",
                  domain=["device"], cardinality=1)

# 数据属性：datatype 只允许 property 声明，闭集见 DATA_TYPES
registry.register("serial_text", "property", label="序列号文本",
                  datatype="text")

# 多语言 label（BCP47 语言标记闭集）与别名
registry.register("switch", "concept", label="交换机",
                  labels={"zh": "交换机", "en": "Switch",
                          "ja": "スイッチ"},
                  altLabels={"en": ["LAN switch"]},
                  aliases=["交换器"])

# 关系特征：逆关系（登记时双向补齐）、对称、传递
# 注意顺序：inverseOf 的目标必须先登记
registry.register("hosts", "relation", label="承载")
registry.register("located_in", "relation", label="位于",
                  inverseOf="hosts", transitive=True)

# 读回与层级判定
term = registry.term("router")
print(term["label"], term["parent_term_id"])       # 路由器 device
print(registry.isSubtypeOf("router", "device"))    # True（沿父链走）
print(registry.term("located_in")["inverse_of"])   # hosts（登记处双向补齐）
```

传递/对称/逆关系**登记即推理**：`ForwardChainingEngine.ensureAutoRules()`
在每次求值前把术语表上的关系特征幂等对齐成 `auto_*` 规则行——声明翻转或
撤除时，旧 auto 行删除并经推导账本精确撤销其结论。你不需要手工为
「传递关系写传递规则」。

## 3. 读面：查询、影响面与删除

```python
# 列出某类全部术语（按 term_id 排序）
for term in registry.terms("relation"):
    print(term["term_id"], term["label"], term["cardinality"])

# 定义域/值域：声明 + 沿父属性继承 + rangeKinds 展开
print(registry.domainOf("has_serial"))   # ['device']
print(registry.rangeOf("is_a"))          # 全部已登记 concept（随表增长自动跟随）

# 删除前先看影响面：被事实/主体类型/子术语引用的术语删不掉
impact = registry.impactOf("device")
print(impact["fact_count"], impact["typed_subject_count"],
      impact["child_terms"])             # 0 0 ['router']

# 仍有子术语的术语删除直接拒绝：
registry.register("router2", "concept", label="子路由", parentTermId="router")
try:
    registry.dropTerm("router")
except ValueError as exc:
    print("删除被拒：", exc)   # 术语 router 仍有子术语 router2——先处理子术语
registry.dropTerm("router2")              # 先删叶子，再删父级
```

删除的守门在注册表层做最后一道：仍有子术语直接拒绝；事实引用、主体类型
引用由调用方先过 `impactOf` 影响面裁定（REST 删除端点与流水线回滚同用
这一判据）。

### 3.1 主体挂类型的两个半边

类型断言有两个落点，缺一不可：

```python
# 半边一：is_a 三元组（事实层，可多条——一个主体可以既是 A 又是 B）
from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate

gate = productionAdmissionGate(store)
content = "路由器R1 is_a router"
gate.admit(AdmissionRequest(
    agentId="default", subjectLabel="路由器R1",
    predicateTermId="is_a", objectTerm="router", content=content,
    assertions=[{"actorType": "user", "actorId": "u1",
                 "statementText": content}]))

# 半边二：主体列上的 type_term_id（定义域/值域校验读的是这一列）
key = store.resolveSubjectKey("default", "路由器R1")
registry.assignSubjectType(key, "device")
```

只写 `is_a` 事实不挂列，定义域校验读不到类型（报 `unregistered(domain)`，
免检不阻断）；只挂列不写事实，不相交判定少一半证据。判据读法：
`assertedTypesOf()` = 列上那一个 + 全部 `is_a` 事实客体的并集。

## 4. 常见错误

- **父类未登记就登记子类**：`register(parentTermId=...)` 要求父类已在本租户
  登记过，否则 `ValueError: 父类未登记`。父子 kind 还必须一致
  （concept 的父类是 concept，relation 的父类是 relation）。
- **别名冲突**：别名按租户唯一。同一 surface 已归属其他术语时登记直接拒绝
  （不覆盖），先查 `resolveRelationAlias()` 再起别名。
- **datatype 用错位置**：`datatype` 只有 `kind="property"` 能声明；
  relation/concept 声明即拒。取值必须在 `DATA_TYPES` 闭集内
  （boolean/date/number/text/url）。
- **关系特征用错位置**：`inverseOf`/`symmetric`/`transitive` 只允许
  `relation` 声明；数据属性具传递/对称/互逆性会被 7.2.2 d) 判据拒绝。
- **模块翻转**：`module="core"` 的术语不允许被 `domain` 覆盖同 id，反之亦然。
- **自己当自己的父类 / 父子链成环**：登记处直接拒绝
  （`_ensureNoParentCycle`），不留悬空边。

## 5. 边界与诚实声明

- **不做 OWL DL**：本仓本体层是「三元组 + 类型表 + 规则」的轻量栈，不提供
  OWL DL 量词/基数公理/自动分类机。需要的是层级、定义域值域、关系特征、
  SHACL 形状这些工程语义，而不是描述逻辑完备性。
- **租户分区**：自 v25 起术语按租户隔离（主键 `(tenant_id, term_id)`）。
  父类引用不跨租户；非 default 租户的种子术语由写咽喉首跳幂等补种。
- **`is_a` 是结构层固定谓词**：类型断言统一走 `is_a`（`IS_A_PREDICATE`），
  不要自造「属于类型」谓词；它的值域按 `rangeKinds: ["concept"]` 声明，
  新增概念自动进入其值域。
- **部分声明用 `declarePartial`**：`register` 是 INSERT OR REPLACE 语义；
  批次/REST 只改一两栏时走 `declarePartial`，没给的栏保留现值，
  否则其余声明会被写回默认裸值。
- **身份判据与外部映射**：`identityKeys` 声明类型级身份键（如 `external_id`），
  供主体消解按类型读取；`externalIris` 走结构化列表
  `[{"kind": "skos_exactMatch", "iri": "..."}]`（kind 闭集：
  skos_exactMatch/skos_closeMatch/skos_relatedMatch/equivalentClass），
  导出面按「附加断言」发射，不做名称替换。
- **命名空间**：非空 `namespace` 必须命中 `NAMESPACE_REGISTRY` 注册表
  （如 `so` = 标准本体领域包），`iri_base` 留空时按注册表自动补齐。
- 配套示例 `example_1_build_and_validate.py` 展示了术语 + 形状 + 咽喉写入的
  完整闭环；形状（SHACL DSL）见教程 5，规则见教程 2，查询见教程 4。
