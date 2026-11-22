# 本体教程 3 · 版本门禁与回滚：流水线批次、semver 与三臂门禁

## 1. 这是什么

本体结构变更（加术语、改层级、登记规则）走 `OntologyPipeline`
（`neurova/knowledge/ontology/pipeline.py`）做**单批次原子**成版：

1. **先全部 dry-run**：候选事实逐条过只读校验路径（与 `/ontology/validate`
   同一事实源 `validation.py`），任一 violation → 整批拒绝、零落盘；
2. **应用不落半态**：术语 upsert（`declarePartial` 部分声明合并）与规则
   登记逐条应用，中途失败**回滚本批已应用**的变更再抛错；
3. **基线快照**：应用后的 terms/rules/shapes 全量声明存进
   `knowledge_baselines`（scope=`ontology_pipeline`），作为回滚点与 diff 端点。

版本号用 semver（`semver.py`）：破坏性变更进 major、增术语进 minor、
修标签进 patch。存量 `vN` 形状只读兼容，新登记一律走 `X.Y.Z`。

## 2. 最小代码示例：批次成版与整批拒绝

```python
import tempfile
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import OntologyPipeline
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

store = KnowledgeFactStore(tempfile.mkdtemp() + "/kb.db")
registry = OntologyTermRegistry(store)
pipeline = OntologyPipeline(store)

# 第一批：登记术语与关系（lives_in 定义域 person），冻结基线
first = pipeline.run(
    agentId="default",
    termUpserts=[
        {"termId": "person", "kind": "concept", "label": "人员",
         "version": "1.0.0"},
        {"termId": "city", "kind": "concept", "label": "城市",
         "version": "1.0.0"},
        {"termId": "lives_in", "kind": "relation", "label": "居住于",
         "domain": ["person"], "version": "1.0.0"},
    ],
    createdBy="tutorial", reason="初版建模")
print(first["accepted"], first["baselineId"])   # True kb_xxxxxxxx

# 事实本身不经 pipeline.run 落库——它只做 dry-run 门禁；写入走咽喉：
from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate

gate = productionAdmissionGate(store)
content = "张三 is_a city"
gate.admit(AdmissionRequest(
    agentId="default", subjectLabel="张三", predicateTermId="is_a",
    objectTerm="city", content=content,
    assertions=[{"actorType": "user", "actorId": "u1",
                 "statementText": content}]))
key = store.resolveSubjectKey("default", "张三")
registry.assignSubjectType(key, "city")   # 定义域校验读这一列

# 第二批：候选事实违规（city 不在 lives_in 定义域 person 内）
# → 任一 violation 整批拒绝，术语/规则/基线一概不落
second = pipeline.run(
    agentId="default",
    termUpserts=[{"termId": "district", "kind": "concept", "label": "城区"}],
    factCandidates=[
        {"subjectLabel": "张三", "predicateTermId": "lives_in",
         "objectTerm": "某某市"},
    ],
    createdBy="tutorial")
print(second["accepted"])            # False
print(second["rejections"][0]["violations"][0]["rule"])   # domain
print(registry.term("district"))     # None——违规批的术语不落半行
```

拒收回执形如 `{accepted: False, baselineId: "", rejections: [{index,
subjectKey, findings, violations, verdict}], summary}`——violation 是
**返回值不是异常**；只有术语/规则应用中途失败才抛错（且本批已回滚）。

## 3. diff、semver 与影响面预标注

```python
from neurova.knowledge.ontology.semver import bumpVersion, impactOfDiff

# 两基线 diff（toBaselineId 缺省对比当前实况，toState=live）
diff = pipeline.diff(first["baselineId"])
print(diff["terms"]["added"], diff["terms"]["changed"])

# 变更种类 → 版本推进
print(bumpVersion("1.0.0", "minor"))   # 1.1.0（增术语）
print(bumpVersion("1.0.0", "major"))   # 2.0.0（破坏性：删术语/改父链/改关系代数特征）

# diff → 逐条 impact 预标注（纯函数只读；四态：breaking / needs_remap /
# needs_reextraction / needs_rule_build）
impact = impactOfDiff({"terms": {"added": [], "removed": ["lives_in"],
                                 "changed": []},
                       "rules": {"added": [], "removed": [], "changed": []}})
print(impact["summary"])   # {'breaking': 1, 'needs_remap': 0, ...}
```

预标注是**审批辅助**：breaking=本体结构被破坏（既有推导与导出公理可能
失效）；needs_remap=值域/类型/限定符口径变了（企业源映射要跟改）；
needs_reextraction=消解口径变了（显示名/别名/身份判据——已抽事实的主体
对齐可能要重跑）；needs_rule_build=规则面有任何增删改。定义/描述类字段
变更不标 impact。

## 4. 三臂对照门禁（checkGate）

候选上线前在**克隆副本**里先演一遍，生产库零写入：

```python
from neurova.knowledge.ontology.pipeline import checkGate

# 假设：把 lives_in 的定义域从 person 改成 city。
# 候选「李四 lives_in 某某市」在现库合法（李四是 person），
# 在草稿（定义域=city）里违规——门禁应当拦下这批假设。
report = checkGate(
    store, "default", "default",
    termUpserts=[{"termId": "lives_in", "kind": "relation",
                  "domain": ["city"]}],
    ruleRegistrations=[],
    factCandidates=[{"subjectLabel": "李四", "predicateTermId": "lives_in",
                     "objectTerm": "某某市"}])
print(report["gate"])     # fail
print(report["reasons"])  # ['candidate 0 regressed：基线 pass、草稿 violation——新假设制造违规']
print(report["arms"])     # baseline=['pass'] draft=['violation'] replay=['pass']
print(report["shifts"])   # 草稿臂注入候选后的增量（added/removed/affected）
```

三臂语义：

- **baseline**：现库对候选事实 dry-run（零成本）；
- **draft**：SQLite `backup` 整库复制出副本 → 副本内应用术语/规则假设 →
  候选过同一咽喉注入 → 引擎到不动点 → 对比；
- **replay**：baseline 同参重放——确定性校验下两臂必须逐条一致，漂移即
  「环境不稳定」，门禁结果不可信，直接 fail。

gate 判定：任一候选「基线 pass、草稿 violation」的倒退即 fail（新假设制造
了违规）；纯新增推导不拦，shifts 如实随报。门禁不落台账——结论随审批流记录。

## 5. 基线回滚

```python
rolled = pipeline.rollback(first["baselineId"], actor="tutorial")
print(rolled["accepted"], rolled["restored"])   # True {'terms': n, 'rules': n, 'shapes': n}
```

回滚把快照里的行逐字恢复（register / INSERT OR REPLACE），快照里没有而
现在有的行删除；删除术语前过 `impactOf` 影响面——被事实/主体类型/子术语
引用的不删，进审计账（`change_log`）。恢复后的规则重推一轮（`fireAll`），
受影响的旧推导经账本精确撤销。

## 6. 常见错误

- **以为 `run` 会把 `factCandidates` 写库**：不会。pipeline 只对候选做
  dry-run 门禁并计数（`applied["facts"]`），事实写入走写咽喉或
  `bulkLoadFacts`。测试判据：干净批次跑完 `factCount() == 0`。
- **批内候选互相看不见**：dry-run 逐条对**现库**判。同一批里两条候选
  （先断言 A 类再断言与 A 不相交的 B 类）彼此不可见，不会互相触发
  disjoint；要拦这种冲突，分两批或先落第一条再过门禁。
- **不相交（disjoint）是检测判据，不是第二次写入的拦截判据**：写入口的
  disjoint 检查读的是**已落库**的类型断言集。给同一主体写第二条冲突
  `is_a` 时，检查时点它还没入库，因此该次写入不会被 disjoint 拦下；
  冲突落库后，**后续任何写入**（任意谓词）过校验时都会报出 disjoint
  violation。要事前拦截，走 `checkGate` 在副本里先演，或用巡检面扫存量。
- **新主体没挂类型**：候选的 subjectLabel 在库里无精确匹配时，定义域
  校验只能报 `unregistered(domain)`（免检不阻断）。要触发定义域/不相交
  判据，主体须已存在且挂了类型（`assignSubjectType`）。
- **跨租户 diff/回滚**：diff 拒绝跨租户基线对比；回滚只作用于基线自己的
  租户分区。
- **用事实基线做 terms/rules diff**：`diff` 只认 scope=`ontology_pipeline`
  的基线，事实基线传入直接 `ValueError`。

## 7. 边界与诚实声明

- **基线是全量声明快照**，不是增量操作日志；两次导出/回滚之间没有隐藏
  状态。幂等 rerun 的 diff 为空（stratification 等派生记账字段不进 diff）。
- **回滚不删被引用的术语**：这是判据不是缺陷——先清引用（事实/主体类型/
  子术语），再回滚才能删干净；残留引用进审计账可查。
- **semver 只管术语声明**：`bumpVersion`/`impactOfDiff` 是纯函数；版本的
  真正生效点在术语行的 `version` 列（登记时写入），引擎不读它做行为分支。
- **checkGate 的副本即抛即毁**：生产库零写入、零台账；它回答「这批假设
  会不会把现有数据搞坏」，不回答「业务上该不该上线」。
