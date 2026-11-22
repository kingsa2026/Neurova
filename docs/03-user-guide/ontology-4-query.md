# 本体教程 4 · 查询：Turtle 投影、SPARQL 只读面与图走查注入

> 离线可跑的配套示例：`examples/ontology/example_3_export_roundtrip.py`
> （全库 Turtle 导出 → 自家解析往返 → 逐字节一致断言）。

## 1. 这是什么

本体查询有四个只读面，按需选用：

| 面 | 入口 | 用途 |
|----|------|------|
| Turtle 投影 | `turtle.serializeAll` / `serializeFact` | 全库/单事实导出成 Turtle 文档（确定性逐字节可复现） |
| 自解析 | `turtle.parseTurtle` | 导出文本读回三元组（往返判据的唯一格式校验） |
| SPARQL 只读 | `sparql_query.runSparqlQuery` | 在投影图上跑 SELECT/ASK（行数上限 + 超时 + 写形拒绝） |
| 图走查 | `graph_walk.GraphFactWalker.walkFromQuery` | 从查询提到的主体出发多跳走查，给对话检索注入事实 |

共同纪律：**只读、零事实写**。查询面不产生事实、不改状态；需要写知识
请走写咽喉（教程 1/2）。

## 2. Turtle 投影与自解析往返

```python
from neurova.knowledge.ontology.turtle import (
    NAMESPACE, iri, literal, parseTurtle, serializeAll,
)

text = serializeAll(store)            # 本租户全库 → 一个 Turtle 文档
triples = parseTurtle(text)           # 自家解析器读回 (主语, 谓词, 宾语)

# 文档形状：@prefix kbg: <https://neurova.local/knowledge/> .
# 三段注释分段：# terms / # rules / # facts
assert text.startswith("@prefix kbg: <%s> ." % NAMESPACE)

# 同库两次导出逐字节一致（排序只来自固定 ORDER BY，时间戳/写入序不进文本）
assert serializeAll(store) == text
```

要点：

- **确定性**：同一库内容两次 `serializeAll` 逐字节一致；同一逻辑内容
  不同写入次序导出也一致。这是回放/比对/缓存键的基石。
- **facts 段主语用 `subject_key`**（ASCII 唯一键）：中文 canonical_label
  经 IRI 字形收口会全部塌成同一个 `kbg:_`，不同主体在导出里互相吞并。
- **谓词映射**：`is_a` 走标准槽位 `rdf:type`；其余谓词按数据原样收字形为
  `kbg:<term>`；字面量带语言标签 `"文本"@zh`。
- `serializeFact(store, factId)` 导出单条事实的完整血缘（断言链 + 推理链），
  事实不存在直接报错，不返回空文本。

### 2.1 单事实血缘导出

```python
from neurova.knowledge.ontology.turtle import serializeFact

rows = [f for f in store.searchableFacts(agentId="default")
        if f["canonical_label"] == "路由器R1"]
ttl = serializeFact(store, rows[0]["fact_id"])
print(ttl)
# @prefix kbg: <https://neurova.local/knowledge/> .
# kbg:fact_… kbg:tripleSubject "路由器R1"@zh ;
#   kbg:mentions "端口P1"@zh ;
#   kbg:recordKind "triple"@zh ; kbg:lifecycleStatus "active"@zh ;
#   kbg:assertedBy "user:u1"@zh ;
#   kbg:assertedStatement "路由器R1 mentions 端口P1"@zh ;
#   kbg:chainSeq "1"@zh ; kbg:chainDigest "…"@zh .
```

血缘行把「谁在何时经何种媒介断言 / 由哪条规则从哪些前提推出」一并带出
（`assertedBy` / `assertedStatement` / `derivedVia` / `derivedFrom` /
`chainDigest`），是审计与解释的导出形态。血缘视图对单库直读的事实行
可能拿不到主体规范名（`tripleSubject` 空串）——这是诚实缺维，不是错误；
需要带标签的投影请先走 `searchableFacts` 这类带 JOIN 的读面。

## 3. SPARQL 只读面

```python
from neurova.knowledge.ontology.sparql_query import runSparqlQuery

result = runSparqlQuery(
    store,
    """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
       SELECT ?s ?o WHERE { ?s rdf:type ?o }""",
    agentId="default", tenantId="default")
print(result["variables"])   # ['s', 'o']
print(result["rows"])        # [{'s': 'https://neurova.local/knowledge/subj_…', 'o': '…/router'}, …]
print(result["row_count"], result["truncated"])
```

行为契约（超限/越权显式拒，不静默降级）：

- **只读**：`INSERT / DELETE / CONSTRUCT / DESCRIBE / DROP / LOAD / CLEAR /
  CREATE / MOVE / COPY` 开头的查询直接 `ValueError`——投影只读面只承诺
  SELECT/ASK；
- **行数上限** `MAX_SPARQL_ROWS = 200`：超出截断并在 `truncated` 如实标注
  （不是报错——分页语义由调用方决定）；
- **查询超时** `SPARQL_TIMEOUT_SECONDS = 10`；
- **rdflib 未安装**：显式 `SparqlNotSupported`（501 形态）——rdflib 是
  可选生产依赖，缺了就诚实说 not_supported，不假装查到空结果；
- **查询缓存**（U2）：进程内缓存键带库指纹与事实水印，库一动键就换，
  失效不挂钩子；命中不豁免任何校验，也不绕过行数上限。

## 4. 图走查：把本体事实注入检索

对话检索侧（`knowledge_retriever_adapter` / `chat_pipeline`）用
`GraphFactWalker` 把查询词命中的主体作为锚点，沿「客体↔主体」接力走
若干跳，把相关事实注入上下文：

```python
from neurova.knowledge.foundation.graph_walk import GraphFactWalker

walker = GraphFactWalker(store, agentId="default")
hops = walker.walkFromQuery("路由器R1 的端口情况", maxHops=2, limit=8,
                            tenantId="default")
for hop in hops:
    print(hop["subject"], hop["predicate"], hop["object"],
          "hop=", hop["hop"], "via_derived=", hop["via_derived"])
```

行为要点：

- 锚点 = 查询文本命中的主体（精确/别名），再经本体扩展（概念实例、
  关系主体只增补不排挤）；无锚点时按种子主体兜底并记收益账。
- 返回 hop ≥ 2 的终点事实，按跳数由近及远、同跳内按置信与新近排序。
- 推导行默认不进走查（观察态在 CTE 里排除）；本租户有 `enforce` 档规则
  时推导行进得来并带 `via_derived` 标注（物化档位见教程 2）。
- 开关 `GraphWalkConfig.fromEnv()`（默认开）；`allowedCategories`
  分类白名单下推到锚点段与递归段，空列表 = 零命中，None = 不启用。

## 5. 常见错误

- **拿 `kbg:is_a` 查 SPARQL 查不到**：`is_a` 在投影里映射成标准槽位
  `rdf:type`。查询要么显式 `PREFIX rdf: ... ?s rdf:type ?o`，要么用
  其他谓词的 `kbg:<term>` 形。
- **主语当成了中文标签**：facts 段主语是 `subject_key`（如
  `subj_b4f42929c39bc698`），不是「路由器R1」。要拿标签，先
  `store.resolveSubjectKey(agentId, label)` 或回读 subjects 表。
- **把写形当查询**：`CONSTRUCT` 也在拒绝清单里——它虽是查询语法，但
  产出新图，越过「投影只读」的承诺；需要投影变换请在 Python 侧处理
  `parseTurtle` 的结果。
- **忽略 `truncated`**：行数到 200 即截断；大结果集请按谓词/主体分片查询。
- **在多租户库上忘了传 tenantId**：投影与走查都按租户分区；缺省 default，
  跨租户数据互不可见。

## 6. 边界与诚实声明

- **投影是简化词表**：Turtle 投影服务本仓的导出/校验/缓存链路，不承诺
  完整 RDF 映射（如 qualifier、叙述记录、账本细节各有专门导出面）。
- **SPARQL 能力以 rdflib 为界**：本仓不自带 SPARQL 引擎；rdflib 支持的
  SELECT/ASK 子集可用，更新类语法一律拒绝。
- **走查是启发式召回**：多跳走查按结构邻近度取事实，不做语义相关度排序；
  注入上下文前调用方应按自身预算裁剪（limit/maxHops 都有具名上限）。
- 配套示例 `example_3_export_roundtrip.py` 演示导出确定性 + 自解析往返；
  互操作格式（JSON-LD/OWL/SHACL/PROV-O/GraphML 等）见教程 5。
