# Agent × Ontology 知识库智能推荐全面方案（统一版）

> 定位：整合前序三份场景分析（方案推荐/假发推荐/检索精准度）＋本文新场景（智能客服餐饮推荐），给出**一份**覆盖全部已识别场景的统一解决方案。前序文档结论并入本文后退役。
> 事实源：`neurova/agent/chat_pipeline.py`、`knowledge_retriever_adapter.py`、`hybrid.py`、`derivation_citation.py`、`context/injector.py`、`foundation/knowledge_facts.py`、`ontology/`（B8–B14 全栈，v29–v34）。

---

## §0 一页结论

**Agent 检索本体知识库"能找到"但"找不准、不会推、不知为何推"。**

三层问题逐级递进：

| 层 | 问题 | 表现 |
|---|---|---|
| **检索层** | 找得到但不精准 | 纯文本相似度，本体语义（类型层级/关系特征/条件类）对排序零参与 |
| **推理层** | 找到了但不会推 | 无约束过滤（海鲜过敏→排除含海鲜）、无数值排序（价格偏好→低价优先）、无多跳（方案B→前置方案A） |
| **解释层** | 推了但不知为何推 | LLM 收到扁平文本；推导标注/类型层级/qualifier/时间线在 payload 里存在但 injector 不消费 |

**统一解法：六层改进架构。** L1 数据结构化 → L2 语义桥 → L3 检索策略 → L4 时间维度 → L5 约束推理与推荐 → L6 反馈闭环。

**三个场景覆盖全部六层：**
- 方案推荐 → 考 L2（语义桥）＋L3（数值比较＋多跳）＋L5（对比注入）
- 假发推荐 → 考 L4（时间衰减＋状态变更）＋L5（时序叙事）
- **餐饮推荐（本文新增）** → 考 L1（产品属性结构化）＋**L3 约束推理**（过敏排除＋价格排序）＋L5（推荐理由）——**是三个场景中唯一需要"从反馈中学习"的**

---

## §1 问题空间：三个场景统一分析

### §1.1 场景总览

| 场景 | 核心能力测试 | 难度递进 |
|---|---|---|
| S1 方案推荐（小明/方案A/B/客户甲/400M） | 属性数值匹配＋多跳遍历（B→derived_from→A→差异） | ★★★ |
| S2 假发推荐（20寸红→16寸金→剪短染金→再购） | 时间序列偏好演变＋状态变更淘汰 | ★★★ |
| **S3 餐饮推荐（套餐A/B/C＋差评→再光顾→推荐）** | **负面反馈偏好学习＋多约束产品过滤＋价格排序** | ★★★★ |

S3 是最复杂的场景因为它需要：
- 从**非结构化反馈文本**（差评）中**提取结构化偏好约束**（海鲜过敏→排除含海鲜；价格偏高→低价优先）
- 将约束**传播**到产品目录（过滤含海鲜的、按价格排序）
- 输出**带理由的推荐**（"推荐C因为无海鲜匹配您的过敏限制＋价格最低"）

### §1.2 根因统一分类（六类十二条）

| 根因 | 编号 | 表现 | S1 | S2 | S3 | 锚点 |
|---|---|---|---|---|---|---|
| **RC-1 语义桥缺失** | RC-1a | 查询归一默认 off（别名/异写不归一） | — | — | ✅ | `query_normalization.py:31` |
| | RC-1b | 本体感知查询扩展**不存在** | ✅ | ✅ | ✅ | 全仓无 query expansion |
| | RC-1c | 歧义澄清默认 off | — | — | ✅ | `ambiguity_clarification.py:31` |
| **RC-2 检索策略缺失** | RC-2a | 无数值范围比较 | ✅ | — | ✅ | `shapes.py` DSL 无 gte/lte |
| | RC-2b | 无多跳关系遍历 | ✅ | — | — | 全仓无 multi-hop |
| | RC-2c | 无"最新偏好"语义 | — | ✅ | — | `knowledge_facts.py` 无 latest-per-subject |
| **RC-3 时间维度缺失** | RC-3a | 检索无时间衰减 | — | ✅ | — | `hybrid.py` 零 recency |
| | RC-3b | payload 不透传时间戳 | — | ✅ | — | `_normalize_item` 零 recorded_at |
| **RC-4 注入结构扁平** | RC-4a | LLM 收到扁平文本列表 | ✅ | ✅ | ✅ | `injector.py` 零 derivation/ontology |
| | RC-4b | 检索 miss 不回流 | — | — | ✅ | miss capture 默认 off |
| **RC-5 偏好学习缺失** | RC-5a | 反馈中的偏好约束**不提取为结构化事实** | — | — | ✅ | 全仓无 feedback→preference 提取 |
| | RC-5b | 产品属性**不结构化为可查询事实** | — | — | ✅ | 全仓无 product attribute extraction |
| **RC-6 约束推理缺失** | RC-6a | 无基于偏好的产品过滤/排序 | — | — | ✅ | 全仓无 constraint-based recommendation |

> S3 新增 RC-5/RC-6 两类根因——它们不是"检索不准"的问题，是"**检索之上的推荐智能**"缺失。

---

## §3 统一改进架构（六层）

```
用户问题 / 客户反馈
  │
  ▼
┌─────────────────────────────────────────────────┐
│ L1 数据结构化（解决 RC-5b，写入面）               │
│  产品属性→结构化事实 / 客户偏好→约束事实          │
│  （抽取 prompt 扩展＋qualifier_schema＋B8 候选）  │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ L2 语义桥（解决 RC-1，读取面）                    │
│  查询归一(on) → 本体扩展(新) → 歧义澄清(shadow)  │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ L3 检索策略（解决 RC-2，读取面）                  │
│  四路 RRF ＋ 数值过滤 ＋ 多跳遍历 ＋ 最新偏好    │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ L4 时间维度（解决 RC-3，贯穿）                    │
│  recency 权重 ＋ payload 时间戳 ＋ 双时态        │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ L5 约束推理与推荐（解决 RC-6，新增层）            │
│  偏好约束提取 ＋ 产品过滤 ＋ 排序 ＋ 推荐理由    │
│  （新模块 ontology_recommender.py）              │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ L6 注入结构与反馈环（解决 RC-4）                  │
│  类型分层 ＋ 推导标注 ＋ 时间线 ＋ miss→候选     │
└──────────────┬──────────────────────────────────┘
               ▼
         LLM 上下文 → 回答
```

---

## §4 各层详设

### §4.1 L1 数据结构化（写入面基础）

**目标**：产品/客户/反馈全部结构化为可查询的本体事实。

| # | 改进 | 数据形状 | 落点 |
|---|---|---|---|
| D-1a | **产品属性结构化** | `(套餐A, has_seafood, "true")`、`(套餐A, price, "400")`、`(套餐A, cuisine_type, "中式")` | LLM 抽取 prompt 扩展（引导属性提取）＋ B8 候选审批 |
| D-1b | **产品关系结构化** | `(套餐B, derived_from, 套餐A)`、`(客户甲, adopted, 方案B)` | 走 B8 候选面审批 |
| D-1c | **客户购买记录** | `(客户X, purchased, 套餐A)` + valid_from=2026-08-10 | 对话/订单系统抽取 |
| D-1d | **客户偏好约束（从反馈中学习）** | `(客户X, has_dietary_restriction, "no_seafood")` + valid_from=2026-08-15；`(客户X, price_sensitivity, "high")` + valid_from=2026-08-15 | **新能力：反馈→偏好提取**（见 §4.5） |
| D-1e | **qualifier schema** | `has_seafood: {"allowed": {"true": "boolean", "false": "boolean"}}`；`price: {"allowed": {}, "valueType": "numeric"}` | v32 qualifier_schema_json |

**关键新增能力：反馈→偏好提取**（解决 RC-5a）

差评文本："A套餐中有海鲜，自己海鲜过敏，而且套餐A价格偏高"

提取逻辑（新模块 `feedback_preference_extractor.py`）：
1. LLM 分析反馈文本 → 识别两类信号：
   - **硬约束**（健康/安全）：`海鲜过敏` → `{attribute: has_seafood, operator: !=, value: true, priority: hard}`
   - **软偏好**（体验/预算）：`价格偏高` → `{attribute: price, operator: <, reference: 400, priority: soft}`
2. 硬约束映射到本体关系术语：`has_seafood` → `no_seafood` 约束
3. 软偏好映射到排序维度：`price` → 低价优先
4. 偏好约束作为结构化事实落库，带 valid_from（偏好有时效性）

### §4.2 L2 语义桥

见检索精准度方案 §3.1（A-1 到 A-4），不再重复。

### §4.3 L3 检索策略

见检索精准度方案 §3.2（B-1 到 B-4），不再重复。

### §4.4 L4 时间维度

见检索精准度方案 §3.3（C-1 到 C-3），不再重复。

### §4.5 L5 约束推理与推荐（新层，本方案核心增量）

**目标**：给定客户偏好约束（从反馈中学到的），在产品目录中过滤出兼容产品，按偏好排序，输出带理由的推荐。

**架构**：

```python
# neurova/knowledge/ontology/recommender.py（新模块）

@dataclass
class CustomerPreferenceProfile:
    """客户偏好画像：从反馈/历史/显式声明中学到的约束集。"""
    customerId: str
    hardConstraints: List[Constraint]    # 硬约束：违反即排除（如过敏）
    softPreferences: List[Constraint]    # 软偏好：违反降权（如价格敏感）
    validFrom: str                       # 偏好的生效时间

@dataclass
class Constraint:
    attribute: str       # 本体关系术语（如 has_seafood, price）
    operator: str        # == != > < >= <=
    value: str           # 期望值
    priority: str        # hard / soft

@dataclass
class ProductRecommendation:
    productId: str
    score: float
    rank: int
    matchedConstraints: List[str]   # 满足了哪些约束
    violatedConstraints: List[str]  # 违反了哪些软偏好
    rationale: str                  # "无海鲜匹配过敏限制，价格最低"


class OntologyRecommender:
    """基于本体事实的约束推理推荐器。"""

    def recommend(self, profile: CustomerPreferenceProfile,
                  productCategory: str, tenantId: str) -> List[ProductRecommendation]:
        """三步推荐：
        1. 获取产品目录（指定类型下的全部产品实例）
        2. 硬约束过滤（violation 即排除）
        3. 软偏好排序（满足多者靠前）
        4. 生成推荐理由
        """
```

**推荐流程（以 S3 餐饮场景为例）**：

```
Step 1: 构建客户偏好画像
  从 facts 读取：
  - (客户X, has_dietary_restriction, "no_seafood") valid_from=2026-08-15
  - (客户X, price_sensitivity, "high") valid_from=2026-08-15
  → hardConstraints: [{attribute: has_seafood, operator: ==, value: "false"}]
  → softPreferences: [{attribute: price, operator: <, referenceValue: 400}]

Step 2: 获取产品目录
  从 facts 读取所有 Plan 类型的产品：
  - 套餐A: {has_seafood: "true", price: "400"}
  - 套餐B: {has_seafood: "false", price: "400"}
  - 套餐C: {has_seafood: "false", price: "300"}

Step 3: 硬约束过滤
  - 套餐A: has_seafood=true → 违反 no_seafood 硬约束 → ❌ 排除
  - 套餐B: has_seafood=false → ✓ 通过
  - 套餐C: has_seafood=false → ✓ 通过

Step 4: 软偏好排序
  - 套餐B: price=400 → 客户 price_sensitivity=high + 曾反馈 400 偏高 → 得分低
  - 套餐C: price=300 → 低于客户反馈的高价阈值 → 得分高
  → 排序：C > B

Step 5: 生成推荐理由
  - 套餐C: "推荐套餐C（¥300，无海鲜）——匹配您的海鲜过敏限制和价格偏好"
  - 套餐B: "套餐B（¥400，无海鲜）也可选，但价格较高，供参考"
```

**落点**：`neurova/knowledge/ontology/recommender.py`（新模块）；`neurova/knowledge/ontology/preference_extractor.py`（反馈→偏好提取，新模块）。

**与已有机制的关系**：
- 产品目录读取复用 `registry.terms()`＋`activeFactsForPredicate`——不是第二套存储
- 硬约束过滤复用 `validation.py` 的 domain/range 逻辑（同一判据）——不是第二套校验
- 软偏好排序可复用 `feedback_prior.py` 的采纳先验权重——不是第二套排序

### §4.6 L6 注入结构与反馈环

见检索精准度方案 §3.4（D-1 到 D-6），不再重复。新增：

| # | 改进 | 说明 |
|---|---|---|
| D-7 | **推荐理由透传**：`ProductRecommendation.rationale` 直接注入 LLM prompt——LLM 引用"因为无海鲜所以推C"有据可查 | recommender 输出直接进 prompt |

---

## §5 三场景统一验证

### §5.1 场景一：方案推荐（属性匹配＋多跳）

改进前 ⭐⭐⭐ / 改进后 ⭐⭐⭐⭐⭐

| 改进层 | 驱动 | 效果 |
|---|---|---|
| L-A 查询扩展 | "高风险订单"→展开为 HighRiskOrder 实例 | 检索直接命中 |
| L-B 数值过滤＋多跳 | 400M 过滤 200M；方案B→derived_from→方案A | 只推 B；A 的属性也进 context |
| L-D 对比注入 | 方案A/B 属性以结构化表格进 LLM | LLM 直接输出对比 |

### §5.2 场景二：假发推荐（时序偏好＋状态变更）

改进前 ⭐⭐ / 改进后 ⭐⭐⭐⭐⭐

| 改进层 | 驱动 | 效果 |
|---|---|---|
| L-C recency | 9月购买排名 > 8月 | 系统层面压旧升新 |
| L-C 时间线注入 | LLM 收到倒序时间线 | LLM 可推理"最新的代表当前偏好" |
| L-D 推导/状态标注 | 客户当前发型状态（短发＋金色）可引用 | 推荐16寸金色有语义依据 |

### §5.3 场景三：餐饮推荐（偏好学习＋约束过滤＋排序）——本方案核心增量

改进前 ⭐☆ / 改进后 ⭐⭐⭐⭐⭐

| 改进层 | 驱动 | 效果 |
|---|---|---|
| L1 反馈→偏好提取 | 差评文本 → `{no_seafood, price_sensitive}` 结构化约束 | **系统知道客户过敏海鲜、觉得价格高** |
| L1 产品属性结构化 | 三套餐的 has_seafood/price 属性在库 | 产品可按属性查询 |
| L5 硬约束过滤 | has_seafood=true → 排除套餐A | 海鲜过敏安全过滤（**不是"可能不推荐"而是"确定不推"**） |
| L5 软偏好排序 | price=300 < 400 → C 得分 > B | C 排第一 |
| L-D 推荐理由 | `rationale` 直接进 prompt | LLM 说"因为您对海鲜过敏且偏好较低价位，推荐套餐C" |

**改进前后回答对比**：

改进前：
> "我们有套餐A、B、C可供选择……"（可能推荐A——含海鲜！客户过敏！）

改进后：
> "根据您之前的反馈，推荐**套餐C**（¥300，无海鲜）。
> 推荐理由：您之前反馈对海鲜过敏，套餐C不含海鲜；同时价格300元低于您之前反馈偏高的400元。
> 套餐B（¥400，无海鲜）也可选，但价格较高。套餐A含海鲜，不建议。"

---

## §6 实施路线（三批，覆盖全部三场景）

| 批次 | 内容 | 覆盖场景 | 预估改动量 |
|---|---|---|---|
| **第一批** | L-C 时间维度（recency＋时间戳透传＋时间线注入）＋L-A 开闸（归一/歧义）＋L-D 消费（推导标注/qualifier/双时态透传） | S1 部分＋S2 核心＋S3 部分 | ~150 行 |
| **第二批** | L1 产品/偏好结构化＋L5 推荐器（硬约束过滤＋软偏好排序＋理由生成）＋L-A 查询扩展 | S1 核心＋S3 核心 | ~500 行 |
| **第三批** | L-B 多跳遍历＋数值条件类＋L-E 纠正反馈环 | S1 多跳＋S3 完整 | ~350 行 |

**最小改动路径**：第一批的 C-2/C-3（时间线注入，约 20 行）让 LLM 收到时间信号，两个场景立即改善。

---

## §7 不做什么

| 项 | 理由 |
|---|---|
| 独立推荐引擎（协同过滤/深度学习） | 本体事实＋约束推理已够；引 ML 模型违零依赖决策 |
| 全量 prompt 重写 | 只在本体/产品知识命中时追加结构化段 |
| 重开 011 两池交织 | 已否证 |
| OWL DL/SPARQL/SHACL 引擎 | 评测报告不采纳 |
| 通用推荐系统框架 | 约束推理用本体事实＋确定性逻辑，不需要 ML |
| 一次性翻全部默认关 | 逐项 shadow→on，A/B 确认后逐个翻（§6 纪律） |
