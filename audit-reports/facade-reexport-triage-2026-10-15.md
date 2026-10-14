# 包门面（`__init__.py`）再导出分流档案 —— 批 47

工单：`audit-reports/simplification-audit-2026-10-05.md` §6-210「同根因扫荡」登记的那条待分流面。
用户裁定（2026-10-14）：**A：门面零消费者再导出逐包分流**——先出档案，无争议那族同批退役。

本档案是**只读产物**；动手面写在 §4，其余三态都要人拍板。

---

## 1. 口径先被自己纠正了三次

批 46 落账时那句「现算全仓 360 个零消费者门面名」**是三处口径缺陷下的读数**，本版重算：

| 缺陷 | 后果 | 现在的口径 |
|---|---|---|
| 消费者按 `asname` 记账 | `from neurova.api.endpoints.memory import router as memoryRouter`（4 个集成测试真在这么写）被记成取用了 `memoryRouter`，于是 `router` 被读成**零消费者** | 按**原名**（`a.name`）记账 |
| 不解析相对导入 | `from ..memory import router` / `from .base import router` 一律不计 ⇒ 又一族假死 | 按发起文件位置解析成绝对模块名 |
| 只认 `from … import …` | `import neurova.cognitive as cog` 之后 `cog.Memory` 这种**属性读取**不认 ⇒ `neurova.cognitive.Memory` 被判死，而它正是 `tests/unit/cognitive_layers/memory_layer/test_memory_dataclass_unification.py:58-65` 钉着的那格 | 收 `import pkg`/`import pkg as p` 之后的属性链（`p.X`、`pkg.X`） |

**现值（2026-10-15 复算）**：81 个包 `__init__.py` 有包级绑定，其中 **56** 个至少挂着一个零消费者绑定，
零消费者绑定合计 **364** 个。另有一类**动态取用**（`importlib.import_module("<pkg>")` 字符串）
静态口径不宣称覆盖，已单列并逐条人眼过（见 §5）。

---

## 2. 四态

| 态 | 判据 | 数量 | 本批处置 |
|---|---|---|---|
| **甲 已声明的公开面** | 零消费者 ∧ 名字在本包 `__all__` 里 | **272** | **不动**（删＝改产品语义，需人裁） |
| **乙 本文件自用而未声明** | 零消费者 ∧ 本文件读它 ∧ 不在 `__all__` | **74** | **不动**（删不掉——本文件要用；缺的是"声明公开面"那一步） |
| **丙 带自陈的业务类再导出** | 零消费者 ∧ 本文件不读 ∧ 无 `__all__` 项，但**档内注释/docstring 明写这次导出的意图** | **18** | **不动**（逐包裁，见 §3） |
| **丁 通用名泄漏 / 被盖掉的 import** | stdlib/typing/`get_logger` 这类通用名绑在包级且本文件不读；或顶层 import 被同文件后面的同名定义**当场作废** | **4 处** | **本批退役**（§4） |

丁 那 4 处的共同点：**没有任何东西在为它们背书**——不是公开面（没进 `__all__`）、不是自用
（本文件不读）、甚至根本不是活的绑定（被同名后定义盖掉）。这与甲乙丙三态是两类问题。

---

## 3. 丙态逐包：18 个落点全部带自陈（所以不由 AST 代拍）

| 包 | 零消费者绑定 | 自陈出处（读文件得到的，不是猜的） | 档案建议 |
|---|---|---|---|
| `neurova.cognitive_layers.meta_cognition_layer` | 8（`GrowthLogManager`、`QuestionQueueManager` 及 6 个数据/枚举类型） | `__init__.py:18-20`：「根因修复: 此前是 10 个 `try: pass except ImportError` 空块，包的公开类（GrowthLogManager/QuestionQueueManager 等）从未被导出……安全导出」——即批 42/43 拆空转段时**刻意补的导出** | 保留，或补 `__all__` 把意图明写；**删它就是回头改批 42/43 的判断** |
| `neurova.memory` | 2（`ConversationMemoryBuffer`、`MoEMemoryRouter`） | `__init__.py:1-5`：「Memory模块兼容性层……为了兼容现有测试代码中的导入语句」，且 `:12-17` 逐条记着批 42/43/45 修坏指路的经过 | 需裁：兼容层要么继续兼容（保留），要么先出"哪些测试还在这么取"的清单再收 |
| `neurova.admin` | 3（`AdminService`、`ResourceQuotaManager`、`ResourceUsage`） | `admin_service.py:85-89` 记着配额账本收口的经过，其中一句「且按 `neurova.admin.__init__` 的导出调真 API 得到 AttributeError」——说明这层导出曾是**修 bug 的落点** | 需裁（现役消费者全部直取子模块，见 §5） |
| `neurova.llm.providers` | 2（`BaseProvider`、`ConnectionResult`） | 同包其余 6 个 provider 名**都有现役消费者**，这 2 个没有；文件自称「统一的 LLM Provider 接口和实现」 | 建议：给本包补 `__all__` 明写公开面（把 6 个活的列进去），比单删 2 个更像修根 |
| `neurova.recovery` | 1（`ShutdownGuard`） | `__init__.py:4-6` 的 docstring 明列「模块: ShutdownGuard」＝自我声明的包面 | 保留或补 `__all__`；现役 3 档判据都直取 `neurova.recovery.shutdown_guard` |

**结论**：丙态没有一处的删除是"无争议"的——每处都有注释或 docstring 在为它表态，
删它们等于推翻批 42/43 或改包的对外语义。所以本批**只动丁态**。

---

## 4. 本批动手面（4 处）

| 落点 | 形态 | 处置 |
|---|---|---|
| `neurova/auth/__init__.py:10` | `import hashlib` 绑在包级，本文件不读、不在 `__all__` | 删该行 |
| `neurova/security/__init__.py:15` | `from neurova.core.logger import get_logger`，**同文件 `:22` 又定义同名函数** ⇒ 这条 import 在绑定的一刻就作废 | 删该行 |
| `neurova/security/__init__.py:22-26` + `__all__` 里的 `"get_logger"` | 本地那只 `get_logger` 全仓零引用（`from neurova.security import get_logger`／`security.get_logger` 两处 grep 均 0 命中）；§6-201 已按"预存死码、本批不顺手"登记 | 删函数与 `__all__` 项 |
| `neurova/api/endpoints/growth.py:59-62` | `get_agent as _get_agent` / `get_request_id as _get_request_id` 被 `:71`/`:76` 的局部包装盖掉；真转发用的是 `:36` 那条 `_impl` 别名 ⇒ 这两条别名 import 从来没生效过 | 删整块 |

替代性核对（§7「删即永久失去该能力」那条前置）：本地 `get_logger(name)` 的作用只是
`logging.getLogger("neurova.security.<name>")` 且**不做 handler/级别配置**；
`neurova.core.logger.get_logger(name)`（`:81-95`）走 `logging.getLogger(name)` 并带缓存与
handler 配置 ⇒ 取同一只 logger 的写法是 `get_logger("neurova.security.x")`，**能力有等价替代**，
被删的那只是更弱的一份（按 §7 属"弱者退役"，不是"唯一实装"）。

---

## 5. 顺带撞见、本批不处置（逐条登记）

1. **`neurova.knowledge.foundation` 的 `ADOPTION_OUTCOMES`**（`__init__.py:18` 零消费者，
   真身在 `knowledge_facts.py:36 = ("success","failure","unevidenced")`）——这串词与
   `neurova/skills/models.py:58-76` 的 `OUTCOME_SUCCESS/FAILURE/UNEVIDENCED` + `OUTCOME_STATES`
   是**同一件事的第二份定义**，而 `tests/unit/knowledge/test_usage_writeback_foundation.py:16`
   还手抄了第三份字面量。收口属 §6 那条根因，另批判（要先定"三态词"的唯一事实源在哪）。
2. **`tests/e2e/cua_sim/harness.py:17-23`**：`from … import PlaywrightBackend` 之后又
   `PlaywrightBackend = pytest.importorskip(...) and PlaywrightBackend`——`and` 的左值只起
   "跳过"作用，右值又指回被盖掉的那个名字，形状可疑但不是本批口径（生产侧）。
3. **动态取用面**（`importlib.import_module("<pkg>")` 字符串）现读命中：
   `tests/manual/deadImportFacade_batch42.py:138`（批 42 的活体档，取 6 个门面读 None 占位符）、
   `tests/manual/facadePlaceholders_batch43.py:119`、
   `tests/unit/llm/test_l05_provider_cache_invalidation_regression.py:37`。
   三处都是"取模块对象"而不是"取包门面里的名字"，删那几个名字不影响；已逐条眼过。
4. **实现写在 `__init__.py` 里的 5 个包**（乙态的主要来源）：`execution_layers` 706 行 / 16 个定义、
   `computer_use` 701 行 / 11、`benchmark` 562 行 / 9、`image_pipeline` 382 行 / 6、
   `api/endpoints` 368 行 / 20。这是结构问题（包门面同时是实现体），
   与"门面挂零消费者名字"同根但不同治——建议另立一批：先把实现挪进子模块，再声明 `__all__`。
5. `neurova/channels/__init__.py` 的 21 个绑定里 12 个活着、9 个在 `__all__` 里零消费者——
   这包正被并发会话改着，**本档案只读数不碰**。

---

## 6. 要人拍的三张票（各选项分别导致什么）

**票一 · 甲态 272 个「已声明而无人取用」的包外名**
- 甲〔结清不立项〕：它们都在 `__all__` 里＝作者明写的对外面；本仓包外消费者（插件、桌面端脚本、
  `agent_workspaces/` 落盘件、NeurUI 侧按名调用）**不在静态口径覆盖范围内**，删它们的风险是不可逆的
  对外破坏。代价：364 个名字里最大那一坨继续留着，台账上这条永远"未清"。
- 乙〔逐包退役〕：能净删 200+ 行，但每包都要先证明"没有包外消费者"——本档案做不到（见 §5 的口径限制）。
  不可逆点：一旦删了，外部按名取用的报错要在下一次运行才暴露，而本仓没有那份消费者清单。
- **推荐 甲**，理由与 §6-210 那句"刻意公开面不等于该删"同一条。

**票二 · 乙态 74 个（实现写在 `__init__.py`）**
- 甲〔只补 `__all__`〕：机械、零行为变更（全仓对 `neurova.*` 的 `import *` 现读 **0** 处，已实测），
  把"什么算这个包的公开面"从隐式变显式。代价：不解决"实现写在门面里"本身。
- 乙〔挪实现 + 补 `__all__`〕：根治，但是 5 个包 2700+ 行的结构搬迁，风险与本批不同量级。
- **推荐 先甲后乙**：甲可以下一批就做（一次 5 档文件），乙等真要去动那 5 个包的功能时顺路做。

**票三 · 丙态 18 个带自陈的再导出**
- 甲〔全保留并补 `__all__`〕：承认它们是包语义的一部分，代价是"零消费者"这条尺子在该族失效。
- 乙〔逐包出清单再收〕：先补一格"哪些测试/文档还指望这层导出"，按清单逐个删；成本是一包一趟 A/B。
- **推荐 乙**，但**先做 `neurova.llm.providers` 与 `neurova.admin` 两包**（丙态里唯一"现役消费者
  全部直取子模块"的两档，见 §3 表），其余四包（meta_cognition_layer / memory / recovery）带明确
  自陈，留着不亏。

---

## 附录 A · 56 个包的逐包读数（现算，2026-10-15）

列义：绑定＝包级 `__init__.py` 顶层绑定的名字数；活＝其中经该包路径被取用（含相对与属性形）的数；`__all__`＝该包是否写了 `__all__`；甲/乙/丙/丁＝§2 四态的计数（丁 在 §4 另有 4 处，含非 `__init__.py` 的 growth.py）。

| 包 | 绑定 | 活 | `__all__` | 丙(可删候选) | 乙(需声明) | 甲(已声明) | 子模块绑定 |
|---|---|---|---|---|---|---|---|
| `neurova.admin` | 3 | 0 | 否 | 3 | 0 | 0 | 0 |
| `neurova.agent` | 18 | 3 | 是 | 0 | 0 | 15 | 0 |
| `neurova.agent.loops` | 6 | 5 | 是 | 0 | 0 | 1 | 0 |
| `neurova.agent.matrix` | 3 | 0 | 是 | 0 | 0 | 3 | 0 |
| `neurova.agent.protocols` | 11 | 0 | 是 | 0 | 0 | 11 | 0 |
| `neurova.agent.templates` | 13 | 0 | 是 | 0 | 0 | 13 | 0 |
| `neurova.aigc_studio` | 3 | 0 | 是 | 0 | 0 | 3 | 0 |
| `neurova.analytics` | 1 | 0 | 是 | 0 | 1 | 0 | 0 |
| `neurova.api.endpoints` | 5 | 0 | 否 | 0 | 5 | 0 | 0 |
| `neurova.asr` | 5 | 0 | 是 | 0 | 0 | 5 | 0 |
| `neurova.auth` | 6 | 0 | 是 | 1 | 0 | 5 | 0 |
| `neurova.backup` | 7 | 0 | 是 | 0 | 0 | 7 | 0 |
| `neurova.benchmark` | 13 | 0 | 否 | 0 | 13 | 0 | 0 |
| `neurova.channels` | 21 | 12 | 是 | 0 | 0 | 9 | 0 |
| `neurova.checkpoints` | 2 | 0 | 是 | 0 | 0 | 2 | 0 |
| `neurova.cognitive_layers.knowledge_graph` | 11 | 0 | 是 | 0 | 0 | 11 | 0 |
| `neurova.cognitive_layers.memory_layer` | 1 | 0 | 是 | 0 | 1 | 0 | 0 |
| `neurova.cognitive_layers.memory_layer.bayesian_eki` | 7 | 0 | 是 | 0 | 0 | 7 | 0 |
| `neurova.cognitive_layers.memory_layer.channels` | 13 | 0 | 是 | 0 | 0 | 13 | 0 |
| `neurova.cognitive_layers.meta_cognition_layer` | 9 | 0 | 否 | 8 | 1 | 0 | 0 |
| `neurova.collaborate.workflow` | 8 | 6 | 是 | 0 | 0 | 2 | 0 |
| `neurova.collaboration` | 1 | 0 | 是 | 0 | 0 | 1 | 0 |
| `neurova.collaboration.neurflow` | 1 | 0 | 是 | 0 | 1 | 0 | 0 |
| `neurova.collaboration.neurflow.templates` | 5 | 0 | 是 | 0 | 5 | 0 | 0 |
| `neurova.computer_use` | 6 | 0 | 否 | 0 | 6 | 0 | 0 |
| `neurova.crdt` | 13 | 0 | 是 | 0 | 0 | 13 | 0 |
| `neurova.embedding` | 4 | 1 | 是 | 0 | 2 | 1 | 0 |
| `neurova.evolution` | 1 | 0 | 是 | 0 | 1 | 0 | 0 |
| `neurova.evolution.eval` | 10 | 0 | 是 | 0 | 0 | 10 | 0 |
| `neurova.evolution.rsi` | 1 | 0 | 是 | 0 | 1 | 0 | 0 |
| `neurova.execution_layers` | 15 | 0 | 否 | 0 | 15 | 0 | 0 |
| `neurova.guest_agent` | 3 | 0 | 是 | 0 | 0 | 3 | 0 |
| `neurova.image_pipeline` | 12 | 0 | 否 | 0 | 12 | 0 | 0 |
| `neurova.interfaces` | 3 | 2 | 是 | 0 | 0 | 1 | 0 |
| `neurova.knowledge.evaluation` | 4 | 2 | 是 | 0 | 0 | 2 | 0 |
| `neurova.knowledge.foundation` | 25 | 1 | 是 | 1 | 0 | 23 | 0 |
| `neurova.knowledge.identity` | 9 | 0 | 是 | 0 | 0 | 9 | 0 |
| `neurova.language` | 1 | 0 | 是 | 0 | 0 | 1 | 0 |
| `neurova.llm` | 6 | 0 | 是 | 0 | 0 | 6 | 0 |
| `neurova.llm.generators` | 18 | 10 | 是 | 0 | 0 | 8 | 0 |
| `neurova.llm.model_runtime` | 24 | 0 | 是 | 0 | 0 | 24 | 0 |
| `neurova.llm.providers` | 8 | 6 | 否 | 2 | 0 | 0 | 0 |
| `neurova.memory` | 27 | 11 | 是 | 2 | 3 | 11 | 0 |
| `neurova.memory_ingest.converters` | 9 | 7 | 否 | 0 | 2 | 0 | 0 |
| `neurova.notifications` | 5 | 0 | 是 | 0 | 0 | 5 | 0 |
| `neurova.plan_mode` | 12 | 11 | 是 | 0 | 0 | 1 | 0 |
| `neurova.planning` | 5 | 3 | 是 | 0 | 0 | 2 | 0 |
| `neurova.plugins` | 9 | 0 | 是 | 0 | 0 | 9 | 0 |
| `neurova.recovery` | 1 | 0 | 否 | 1 | 0 | 0 | 0 |
| `neurova.sandbox` | 8 | 0 | 是 | 0 | 0 | 8 | 0 |
| `neurova.security` | 4 | 0 | 是 | 0 | 0 | 4 | 0 |
| `neurova.skill_system` | 10 | 9 | 是 | 0 | 0 | 1 | 0 |
| `neurova.skills.builtin` | 7 | 0 | 是 | 0 | 0 | 7 | 0 |
| `neurova.sync` | 7 | 0 | 是 | 0 | 0 | 7 | 0 |
| `neurova.tool_layers` | 5 | 0 | 是 | 0 | 5 | 0 | 0 |
| `neurova.tts` | 8 | 0 | 是 | 0 | 0 | 8 | 0 |

合计：零消费者绑定 **364**（丙 18／乙 74／甲 272／子模块绑定 0），包数 **56**。
