# 本体教程 5 · 互操作：九格式导出、SHACL 运行时校验与 RDF/XML 导入边界

## 1. 这是什么

本体数据的进出两向：

- **导出**（`neurova/knowledge/ontology/export/` + `turtle.py`）：九种格式，
  每个模块一个 `export*(store, tenantId)` 入口，逐字节确定（排序固定），
  零第三方依赖；
- **校验**（`shacl_runtime.py`，升级卡 U1）：形状单源导出成 SHACL 文档后
  交 pyshacl 求值，`off / shadow / enforce` 三档接在写咽喉段 3 后半；
- **导入**（`rdf_import.py`）：RDF/XML 解析走 **inert 姿态**——解析结果
  与原始字节保留，但**不执行** OWL/SHACL 公理（不注册规则、不挂 shapes、
  不改判定逻辑）。

## 2. 九格式导出

```python
from neurova.knowledge.ontology.turtle import serializeAll          # ① Turtle
from neurova.knowledge.ontology.export.jsonld import exportJsonLd   # ② JSON-LD
from neurova.knowledge.ontology.export.owl import exportOwlAxioms   # ③ OWL 公理
from neurova.knowledge.ontology.export.shacl import exportShaclShapes  # ④ SHACL shapes
from neurova.knowledge.ontology.export.prov import exportProv       # ⑤ PROV-O 溯源
from neurova.knowledge.ontology.export.graph_exchange import (      # ⑥⑦⑧⑨ 图交换
    exportGraphML, exportGexf, exportCypher, exportCsv,
)

documents = {
    "turtle": serializeAll(store),
    "jsonld": exportJsonLd(store),
    "owl": exportOwlAxioms(store),
    "shacl": exportShaclShapes(store),
    "prov": exportProv(store),
    "graphml": exportGraphML(store),
    "gexf": exportGexf(store),
    "cypher": exportCypher(store),
    "csv": exportCsv(store),
}
for name, text in documents.items():
    print(name, len(text), "chars")
```

- 图交换四格式（GraphML/GEXF/Cypher/CSV）走同一份图读取（主体 + 三元组边），
  节点/边标识经 `_safeIdent` 收字形；
- RDF 基线是 RDF 1.1；RDF 1.2 特性只观察不采用；
- 全部导出**逐字节确定**：同库两次导出一致（见教程 4 的往返判据）。

格式怎么选（按消费方）：

| 格式 | 典型消费方 |
|------|------------|
| Turtle / JSON-LD | RDF 生态工具、三方图库装载、本仓自解析往返 |
| OWL 公理 | 本体工程工具查看层级/互逆/函数属性等静态公理 |
| SHACL shapes | pyshacl 等校验器（运行时校验同一份文档，见下节） |
| PROV-O | 溯源/审计面（活动-断言-推导链） |
| GraphML / GEXF | 图可视化与图分析工具 |
| Cypher | 属性图数据库批量导入 |
| CSV | 表格/电子表格侧的扁平化对账 |

### 2.1 SHACL shapes 的 DSL 映射

`exportShaclShapes` 把 `ShapeRegistry` 的 JSON DSL 逐项映射到 sh: 词汇：
`pattern → sh:pattern`、`in → sh:in`、`class → sh:class`、
`minCount/maxCount → sh:minCount/sh:maxCount`；target 走
`sh:targetObjectsOf <谓词>`（无目标术语时退 `sh:targetClass kbg:Term`）；
严重级发射为 `sh:severity sh:Violation|Warning|Info`。内置 6 项校验
（domain/range/…）不重复导出——它们是写面判据，不是数据形状。

## 3. SHACL 运行时校验（U1 三档）

形状的单一事实源是 `ShapeRegistry`（DSL 闭集：`in / pattern / minCount /
maxCount / class`，严重级三态 `violation / warning / info`）。运行时校验
把同一份形状经 `exportShaclShapes` 导出成 SHACL 文档，交 pyshacl 求值：

```python
from neurova.knowledge.ontology.shacl_runtime import (
    admissionShaclCheck, shaclMode, validateShapesRuntime,
)

print(shaclMode())   # NEUROVA_ONTOLOGY_SHACL_RUNTIME，缺省 off

# 只读报告（不写任何表）：现库全量投影 vs 形状图
report = validateShapesRuntime(store, "default", mode="shadow")
print(report["supported"], report["conforms"], report["violations"])

# 写入前 dry-run：把尚未落库的候选行拼进数据图一起校验
candidate = [{"subject_key": key, "predicate_term_id": "has_serial",
              "object_term": "BAD-001", "fact_id": "candidate_1"}]
dry = validateShapesRuntime(store, "default", mode="shadow",
                            extraFacts=candidate)
for v in dry["violations"]:
    print(v["component"], v["severity"], v["value"], v["message"])
```

三档语义（环境变量 `NEUROVA_ONTOLOGY_SHACL_RUNTIME`）：

| 档位 | 行为 |
|------|------|
| `off`（缺省） | 完全不跑，零开销，既有写入路径行为不变 |
| `shadow` | 跑并告警（logger.warning），不拒写 |
| `enforce` | 写咽喉段 3 后半：`sh:Violation` 级违规拒写（warning/info 只记录） |

pyshacl 惰性 import + fail-soft：依赖在 `requirements.txt` 里（首启链自动
安装）；旧环境未装时显式 `supported=False` 诚实降级，不炸写入面，也不假装
「校验通过」。

## 4. RDF/XML 导入：inert 姿态

```python
from neurova.knowledge.ontology.rdf_import import importRdfXml

xml = (b'<?xml version="1.0"?>'
       b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
       b' xmlns:ex="http://example.org/">'
       b'<rdf:Description rdf:about="http://example.org/a">'
       b'<ex:name>demo</ex:name></rdf:Description></rdf:RDF>')

result = importRdfXml(xml)
print(result.triple_count)     # 1
print(result.inert)            # True——公理不执行
print(result.sha256)           # 原始字节 SHA-256（导出时全量图 + 字节引用）
print(result.unsupported)      # owl#/shacl# 谓词的三元组进这里（不执行清单）
```

安全与上限（超限显式拒，不静默截断）：

- `<!DOCTYPE` / `<!ENTITY` / `ENTITY` 文本级预扫，命中即
  `RdfImportSecurityError`（XXE 面收窄——在 XML 解析器之前拦截）；
- 字节数超 `MAX_IMPORT_BYTES`（5 MiB）、三元组数超 `MAX_IMPORT_TRIPLES`
  （10000）→ `RdfImportLimitError`；
- rdflib 未安装 → `RdfImportNotSupported`（诚实形态）。

## 5. 常见错误

- **给形状用 `minCount`/`maxCount` 后跑 pyshacl 报
  `ConstraintLoadError`**：标准 SHACL 里这两个分量只能挂在
  PropertyShape（`sh:property`）上，而本仓导出面把用户形状统一发射成
  NodeShape。写前 DSL 校验（`ShapeRegistry._evaluateOne`）对二者都生效；
  要同时过 pyshacl，请选 NodeShape 合法分量（`pattern`/`in`/`class`）。
- **`in` 形状填字符串值后 SHACL 文档解析失败**：导出按
  `sh:in ( v1 v2 ... )` 裸词发射，字符串值不是合法 Turtle 项——`in`
  形状的导出互通目前只对数值取值可靠；字符串枚举请改用 `pattern`。
- **以为 enforce 档会拦下所有形状违规**：只有 `severity="violation"`
  的形状产生 `sh:Violation`；`warning`/`info` 形状任何档位都只记录。
- **以为导入即生效**：RDF/XML 导入是 inert 的——三元组与字节留档、
  OWL/SHACL 公理进 `unsupported` 清单但不注册规则、不挂形状。要把导入
  事实落库，请走写咽喉（教程 1）或批量装载。
- **直接信 `conforms=True`**：`off` 档返回的报告带 `skipped=True`；
  pyshacl 缺席时 `supported=False`。先看这两个标志再解读 `conforms`。

## 6. 边界与诚实声明

- **不做 OWL DL 一致性校验**：`exportOwlAxioms` 导出的是术语表上可静态
  表达的公理（层级/互逆/函数属性/不相交等），不运行 OWL 推理机，也不做
  一致性判定；SHACL 运行时只校验数据图对形状图的符合性。
- **导出面与校验面同源**：运行时校验用的形状文档与 `exportShaclShapes`
  逐字节同源（单一事实源）；本仓不重排、不翻译形状语义。
- **RDF 1.2 只观察**：生产基线是 RDF 1.1；新特性不进导出承诺。
- **inert 是刻意的**：导入外部公理直接执行，等于让外部文件改写本仓判定
  逻辑；本仓选择「留档 + 不执行 + 清单可见」，执行决策留给显式审批流。
