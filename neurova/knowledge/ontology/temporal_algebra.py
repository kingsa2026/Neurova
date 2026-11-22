"""Allen 区间代数引擎（本体域升级卡 U4）。

事实层（`neurova/knowledge/foundation/knowledge_facts.py`）带 `valid_from` /
`valid_until` 双时态列，但此前时间关系不推理；`upper_lite.py` 只声明了
before/after/overlaps/during 四条受控词汇（OWL-Time 仅作 `skos_exactMatch`
导出映射，不生成传递规则）。本模块补齐 Allen 13 区间关系的**判定**
（`classifyIntervalRel`）与**合成**（`composeRelations`）两个核心原语，
供时效事实两两时间关系判定使用。

设计约束（D-U6 决议）：
- 纯函数、无 IO、无 store 依赖——`relationsForFacts` 只吃已取出的 dict 列表；
- 不生成任何派生事实、不接规则库——传递性由合成表在求值期给出；
- 时间口径：内部一律毫秒 epoch int；入参接受 int/float（视为毫秒 epoch）
  或 ISO8601 字符串（naive 按 UTC 解读，与 `knowledge_facts._instant` 同口径），
  解析失败显式抛 `ValueError`，不静默。
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

# ── 13 关系闭集（唯一事实源）────────────────────────────────────

REL_BEFORE = "before"                # a 在 b 之前（ae < bs）
REL_AFTER = "after"                  # a 在 b 之后（as > be）
REL_MEETS = "meets"                  # a 搭接 b（ae == bs）
REL_MET_BY = "metBy"                 # b 搭接 a（as == be）
REL_OVERLAPS = "overlaps"            # a 领先交叠 b（as < bs < ae < be）
REL_OVERLAPPED_BY = "overlappedBy"   # b 领先交叠 a（bs < as < be < ae）
REL_STARTS = "starts"                # a 与 b 同起点、a 先收（as == bs，ae < be）
REL_STARTED_BY = "startedBy"         # a 与 b 同起点、a 后收（as == bs，ae > be）
REL_DURING = "during"                # a 严格落在 b 内部（bs < as，ae < be）
REL_CONTAINS = "contains"            # b 严格落在 a 内部（as < bs，be < ae）
REL_FINISHES = "finishes"            # a 与 b 同终点、a 晚起（ae == be，as > bs）
REL_FINISHED_BY = "finishedBy"       # a 与 b 同终点、a 早起（ae == be，as < bs）
REL_EQUAL = "equal"                  # 两区间端点分别相等

#: Allen 13 关系闭集——判定结果与合成表取值都从这里收口
INTERVAL_RELATIONS: tuple[str, ...] = (
    REL_BEFORE, REL_AFTER, REL_MEETS, REL_MET_BY,
    REL_OVERLAPS, REL_OVERLAPPED_BY, REL_STARTS, REL_STARTED_BY,
    REL_DURING, REL_CONTAINS, REL_FINISHES, REL_FINISHED_BY, REL_EQUAL,
)

_RELATION_SET: frozenset = frozenset(INTERVAL_RELATIONS)

#: 逆关系（converse）映射：rel(b, a) == inverseRelation(rel(a, b))
_INVERSE: dict[str, str] = {
    REL_BEFORE: REL_AFTER, REL_AFTER: REL_BEFORE,
    REL_MEETS: REL_MET_BY, REL_MET_BY: REL_MEETS,
    REL_OVERLAPS: REL_OVERLAPPED_BY, REL_OVERLAPPED_BY: REL_OVERLAPS,
    REL_STARTS: REL_STARTED_BY, REL_STARTED_BY: REL_STARTS,
    REL_DURING: REL_CONTAINS, REL_CONTAINS: REL_DURING,
    REL_FINISHES: REL_FINISHED_BY, REL_FINISHED_BY: REL_FINISHES,
    REL_EQUAL: REL_EQUAL,
}


# ── 时间口径归一 ────────────────────────────────────────────────

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parseToEpochMs(value) -> int:
    """把时间入参归一到毫秒 epoch int。

    数值（int/float）视为已是毫秒 epoch；字符串按 ISO8601 解析，naive 按 UTC
    解读（与 `knowledge_facts._instant` 同口径）。解析失败或类型不支持一律
    显式抛 `ValueError`，不做静默兜底。
    """
    if isinstance(value, bool):  # bool 是 int 子类，但作为时间戳没有意义
        raise ValueError("时间入参不支持 bool: %r" % (value,))
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("时间入参不是有限数值: %r" % (value,))
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError("无法按 ISO8601 解析时间入参: %r" % (value,)) from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = parsed - _EPOCH
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    raise ValueError("时间入参类型不支持（应为毫秒 epoch 数值或 ISO8601 字符串）: %r"
                     % (value,))


# ── 判定与逆关系 ────────────────────────────────────────────────

def classifyIntervalRel(aStart, aEnd, bStart, bEnd) -> str:
    """判定区间 a=[aStart,aEnd) 与 b=[bStart,bEnd) 的唯一 Allen 关系。

    端点语义按 Allen 标准：区间为正时长半开区间（start < end，倒置或零长度
    都算非法区间，显式报错）；meets 即 aEnd == bStart（首尾搭接）。
    """
    as_, ae = _parseToEpochMs(aStart), _parseToEpochMs(aEnd)
    bs, be = _parseToEpochMs(bStart), _parseToEpochMs(bEnd)
    if as_ >= ae or bs >= be:
        raise ValueError("非法区间（要求 start < end）: a=(%r, %r), b=(%r, %r)"
                         % (aStart, aEnd, bStart, bEnd))
    if ae < bs:
        return REL_BEFORE
    if ae == bs:
        return REL_MEETS
    if as_ > be:
        return REL_AFTER
    if as_ == be:
        return REL_MET_BY
    if as_ == bs:
        if ae == be:
            return REL_EQUAL
        return REL_STARTS if ae < be else REL_STARTED_BY
    if ae == be:
        return REL_FINISHED_BY if as_ < bs else REL_FINISHES
    if as_ < bs:
        # 至此必有 as < bs < ae（否则已是 before/meets），只看右端点
        return REL_CONTAINS if ae > be else REL_OVERLAPS
    # as > bs：对称地必有 bs < as < be
    return REL_DURING if ae < be else REL_OVERLAPPED_BY


def inverseRelation(relation: str) -> str:
    """取逆关系（converse）：rel(b, a) == inverseRelation(rel(a, b))。"""
    try:
        return _INVERSE[relation]
    except KeyError:
        raise ValueError("未知区间关系: %r（有效值: %s）"
                         % (relation, " / ".join(INTERVAL_RELATIONS))) from None


# ── 合成表（13×13 全覆盖，程序化生成后冻结为常量）───────────────

def _buildCompositionTable() -> dict[tuple[str, str], frozenset]:
    """按 Allen 合成的语义定义生成完整 13×13 合成表：

    comp(r1, r2) = { rel(a, c) | 存在区间 a, b, c：rel(a,b)=r1 且 rel(b,c)=r2 }。

    Allen 关系只由 6 个端点的相对次序决定，且 meets/metBy/starts/finishes/
    equal 等关系依赖**端点相等**——所以不能只枚举严格全序（那只覆盖 6 端点
    两两不同的形态），必须枚举"弱序"：把 6 个端点指派到 0..5 的秩上允许并列
    （区间内部仍要求 start < end）。6 个端点至多需要 6 个层级，秩 0..5 恰好
    全部可表达，故该枚举对每一格既不缺也不多，产物即标准 Allen 合成表。
    表在导入期生成一次并冻结，运行期只读。
    """
    table: dict[tuple[str, str], set] = {
        (r1, r2): set() for r1 in INTERVAL_RELATIONS for r2 in INTERVAL_RELATIONS
    }
    for as_, ae, bs, be, cs, ce in itertools.product(range(6), repeat=6):
        if as_ >= ae or bs >= be or cs >= ce:
            continue
        relAB = classifyIntervalRel(as_, ae, bs, be)
        relBC = classifyIntervalRel(bs, be, cs, ce)
        table[(relAB, relBC)].add(classifyIntervalRel(as_, ae, cs, ce))
    return {key: frozenset(value) for key, value in table.items()}


_COMPOSITION: dict[tuple[str, str], frozenset] = _buildCompositionTable()


def composeRelations(relA: str, relB: str) -> frozenset:
    """Allen 合成：a relA b 且 b relB c 时，a 与 c 可能的关系集合（frozenset）。

    合成表完整覆盖 13×13=169 格；传递性在求值期由本表给出，不入规则库
    （D-U6 决议）。relA / relB 不在 13 关系闭集内时显式报错。
    """
    for relation in (relA, relB):
        if relation not in _RELATION_SET:
            raise ValueError("未知区间关系: %r（有效值: %s）"
                             % (relation, " / ".join(INTERVAL_RELATIONS)))
    return _COMPOSITION[(relA, relB)]


# ── 便利函数：时效事实两两判定 ─────────────────────────────────

_ID_FIELDS = ("id", "factId", "fact_id")
_START_FIELDS = ("validFrom", "valid_from")
_END_FIELDS = ("validUntil", "valid_until")


def _field(fact: dict, names: tuple[str, ...]):
    for name in names:
        if name in fact:
            return fact[name]
    return None


def relationsForFacts(facts) -> list[dict]:
    """对已取出的时效事实列表做两两 Allen 关系判定。

    入参字段名对齐 `knowledge_facts._hydrate` 的实际返回（`fact_id` /
    `valid_from` / `valid_until`，DB 列名口径），同时兼容 camelCase 别名
    （`id` / `validFrom` / `validUntil`，admission 入参契约写法）。

    任一事实的端点缺失（NULL 有效期）时，涉及该事实的配对不产出结果——
    端点不全构不成可判定的区间。输出按输入顺序取 i<j 组合，每项为
    {"aId", "bId", "relation"}，relation 是 a 视角下的唯一关系。
    """
    items = []
    for index, fact in enumerate(facts):
        factId = _field(fact, _ID_FIELDS)
        if factId is None:
            raise ValueError("第 %d 条事实缺少 id 字段（应为 %s 之一）"
                             % (index, " / ".join(_ID_FIELDS)))
        items.append((str(factId),
                      _field(fact, _START_FIELDS),
                      _field(fact, _END_FIELDS)))
    results = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            idA, startA, endA = items[i]
            idB, startB, endB = items[j]
            if startA is None or endA is None or startB is None or endB is None:
                continue
            results.append({
                "aId": idA,
                "bId": idB,
                "relation": classifyIntervalRel(startA, endA, startB, endB),
            })
    return results
