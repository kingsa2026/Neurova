"""工具并行能力的形状与推导（**唯一**一处判据；本模块不定义任何成员）。

## 为什么有此模块

同轮多工具的并行资格，此前由 `agent/tool_coordinator.py` 一份**名字硬编码
清单**回答：清单外（含未知工具、MCP / Skill / workflow 命名空间）一律串行，
且是 all-or-nothing（任一未声明 ⇒ 整轮串行）。三个结构性缺口：**封闭**
（能力无法由工具自己声明，新工具与第三方 MCP 永远进不来）、**漂移无人拦**
（运行期成员查询，无装配期校验，清单里还混着两个不存在的名字）、
**粒度太粗**（一个未声明项拖垮整轮）。

本模块把"能不能并发"换成**读每个工具自己的声明**：形状与推导在这里（一处），
**成员落在各工具的声明处**（`builtin_tools` 的 schema 声明位 / 将来的 MCP
注册点），因此不是"把大名单挪个文件"。

## 合取判据（fail-closed）

`ToolCapability` 的每个字段缺省都是最保守值：未声明 ⇒ `concurrentSafe=False`
且 `readOnly=False` ⇒ 串行。**单个工具的判定**因此与改造前逐条等价（旧判据对
未声明工具也返回 False）；改变的是**一批工具**的编排：旧判据 all-or-nothing
（任一未声明 ⇒ 整轮串行），新判据按声明分组（未声明项自己串行，**不拖累**
相邻的已声明项）。混合批的时序变化是有意为之，不是回归。

并行资格是**合取**，不是单字段：声明了 `readOnly` 但共享作用域非空（如远端写、
共享外设）仍判定不可并行。这条合取挡住的正是"标了只读却发写请求"这类误声明
——声明写错也不会上行，是第二层防护。

共享状态的读**永不并行**（`WriteScope.SHARED`）：桌面截图 / 浏览器分片续读 /
画布快照这类"读"取的是同一个外部对象的瞬时态，并发时两个调用会拿到彼此的
中间态（例如浏览器分片续读会互相推进同一个页面的游标）。它们语义上只读，
但在并行轴上必须串行——这正是"一个布尔字段表达不了两件事"的实例，也是本模块
保留**作用域**、而不只留一个开关的原因。该族的成员在 `builtin_tools` 的声明位
逐条给出，并由 `tests/unit/tools/test_tool_batch_parallelism.py` 逐名钉住
"恒不可并行"。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Sequence, Tuple

__all__ = [
    "WriteScope",
    "ToolCapability",
    "ToolBatch",
    "ToolBatchShape",
    "parseToolCapability",
    "isParallelEligible",
    "planToolBatches",
    "classifyBatchShape",
]


class WriteScope(str, Enum):
    """工具的执行会不会触碰**与同批其它调用共享**的状态（并行轴上的冲突域）。

    **只收能改变裁决的取值**——枚举是判据的输入，不是分类学。并行轴只问一件事：
    "两个调用同时跑会不会互相干扰"，答案只有"不会"与"会"两种，故这里**只有两档**：

    - `NONE`：不触碰任何共享状态，两个调用同时跑互不影响；
    - `SHARED`：会触碰共享状态（会话态 / 工作区 / 版本库 / 桌面 / 浏览器 / 画布的
      瞬时态）。这些细分的**裁决完全相同**（都不可并行），各自造一个取值就是
      第二堆没人消费的枚举值——`AGENTS.md` 协作红线把"写出无人读的字段"算作
      断点，故只在注释里记录细分，不落到枚举上。

    缺省（未声明）= `{SHARED}`：状态不明即按"会互相干扰"处理，最保守。
    """

    NONE = "none"      # 不触碰任何共享状态 ⇒ 只读工具用它才可能并行
    SHARED = "shared"  # 会触碰共享状态（细分见类 docstring；裁决一律串行）


#: 缺省作用域 = 共享：未声明即"状态不明"，按会互相干扰处理（最保守）。
_DEFAULT_WRITE_SCOPES: FrozenSet[WriteScope] = frozenset({WriteScope.SHARED})


@dataclass(frozen=True)
class ToolCapability:
    """工具自身能力的声明（缺省即最保守：不可并行、不算只读）。

    Attributes:
        readOnly: 声明为只读。
        concurrentSafe: 声明"与同批其它调用同时跑不会互相破坏"。
            **必须显式声明**：`readOnly` 本身不足以放行——共享外设的读就属此列。
        writeScopes: 会触碰的共享状态层集合，缺省 `{SHARED}`（状态不明⇒最保守）。
            **必须显式列举**，不接受空集合：空集合是"没填"还是"确认没有"分不清，
            而这两种语义的安全处置相反（前者最保守、后者可放行）。
    """

    readOnly: bool = False
    concurrentSafe: bool = False
    writeScopes: FrozenSet[WriteScope] = _DEFAULT_WRITE_SCOPES


def parseToolCapability(raw: Any) -> "ToolCapability | None":
    """把一份**原始声明**（dict，来自某提供方的声明位）解析为 `ToolCapability`。

    **唯一一处**声明解析。内置工具从 `_BUILTIN_SCHEMAS` 的声明位取、MCP 工具从本仓侧
    server 配置的声明位取，两条路径都走这里——两处各写一遍解析，就会给同一种输入
    两个事实（一侧拒、一侧采信），这正是本模块要收掉的那种分叉。

    失败一律返回 `None`（调用方按未声明处置，即最保守的串行）。三条拒收规则：

    - 形态非法（不是 dict / 布尔位不是布尔 / 作用域不是序列）：不部分采信——
      半个声明比没声明更危险；
    - 作用域含未登记取值：整条作废，不做"忽略未知项"的宽容；
    - 作用域是**空集合**：分不清"没填"与"确认没有"，而两种语义的安全处置相反
      （前者最保守、后者可放行），故不替调用方推断意图。

    声明面因此自身不构成攻击面：写错的声明只会让该工具退回串行，绝不会误放开。
    """
    if not isinstance(raw, dict):
        return None
    read_only = raw.get("readOnly")
    concurrent = raw.get("concurrentSafe")
    scopes = raw.get("writeScopes")
    if not isinstance(read_only, bool) or not isinstance(concurrent, bool):
        return None
    if not isinstance(scopes, (list, tuple)):
        return None
    try:
        parsed = frozenset(WriteScope(str(item)) for item in scopes)
    except ValueError:
        return None
    if not parsed:
        return None
    return ToolCapability(
        readOnly=read_only, concurrentSafe=concurrent, writeScopes=parsed
    )


class ToolBatchShape(str, Enum):
    """一轮工具调用的**执行形态**（取值即埋点标签，是判据的输入而不是分类学）。

    三态按"这一轮 M3 有没有拿到并行"分，不按工具类别分：

    - `SINGLE_CALL`：本轮只有一个调用 —— M3 在这上面本来就没有收益可言，
      混进分母会把"多工具批次占比"稀释成两个不同问题的平均数；
    - `MULTI_PARALLEL`：至少有一个**成组**批 —— M3 唯一能兑现收益的形态；
    - `MULTI_SERIAL`：多调用但零成组批 —— M3 的目标客户。

    **写入侧与读数侧共用这一份词汇**：两边各写一遍字面量，漂移时读数侧会把不认识
    的标签静默丢掉，然后照着一个不完整的分母出结论（实测 8 个样本里 5 个被扔掉，
    读数给出 `sparse`）。故标签值只在本处定义，其余落点一律引用。
    """

    SINGLE_CALL = "single_call"
    MULTI_SERIAL = "multi_serial"
    MULTI_PARALLEL = "multi_parallel"


def classifyBatchShape(batchCount: int, hasGroupedBatch: bool) -> ToolBatchShape:
    """批次计划 → 形态（**唯一一处**判定，取代调用点里的三字面量分支）。

    Args:
        batchCount: 本轮所有批次里的调用总数。
        hasGroupedBatch: 是否存在成组批（`planToolBatches` 只在 ≥2 项时标记并发）。
    """
    if batchCount <= 1:
        return ToolBatchShape.SINGLE_CALL
    if hasGroupedBatch:
        return ToolBatchShape.MULTI_PARALLEL
    return ToolBatchShape.MULTI_SERIAL


def isParallelEligible(cap: ToolCapability) -> bool:
    """并行资格推导（**唯一**一处，取代按名字查清单的成员判定）。

    合取三态：显式声明可并发 + 声明只读 + 写作用域为空。
    任一条不成立即串行（fail-closed，与改造前对未声明工具的处置同）。
    """
    if not cap.concurrentSafe or not cap.readOnly:
        return False
    return set(cap.writeScopes) <= {WriteScope.NONE}


@dataclass(frozen=True)
class ToolBatch:
    """一个执行批次：`items` 是 `(原下标, tool_call)`，`parallel` 示是否并发。"""

    items: Tuple[Tuple[int, Any], ...]
    parallel: bool

    def __len__(self) -> int:
        return len(self.items)


def planToolBatches(
    toolCalls: Sequence[Any],
    capabilities: Dict[str, ToolCapability],
    *,
    maxParallel: int,
) -> List[ToolBatch]:
    """把一轮调用切成批次（纯函数，可静态测，不碰运行时）。

    规则：按**原声明顺序**扫描，连续的资格项合成一批（每批不超过 `maxParallel`，
    超出即另起一批）；非资格项每一项自成一池批。**单项批一律标为串行**——
    此时并发与串行执行等价，标记只为让"批次标记 = 实际执行形态"始终成立。

    保序：分组只改变**执行时序**，不改回装次序——调用方按原下标回装，
    `asyncio.gather` 自身保序，逐批串接后仍按原索引落位。

    Args:
        toolCalls: 本轮 `tool_calls`（每项形如 `{"function": {"name": ...}}`）。
        capabilities: 工具名 → 声明；缺席按未声明（串行）。
        maxParallel: 单批并发上限（合法域由配置键夹紧，见调用方）。

    未知工具名下 `capabilities.get(name)` 为 `None` ⇒ 非资格项 ⇒ 串行，
    与"未声明即串行"同一处置，不需要第二分支。
    """
    limit = max(1, int(maxParallel))
    batches: List[ToolBatch] = []
    pending: List[Tuple[int, Any]] = []

    def _flush() -> None:
        # `parallel` 只在**成组**（≥2 项）时为真：单项批的并发与串行等价，
        # 标成并发会让"批次标记"与"实际执行形态"分裂成两套口径。
        # 执行侧因此只需认这一个标记，不必再判长度。
        if len(pending) > 1:
            batches.append(ToolBatch(items=tuple(pending), parallel=True))
        elif pending:
            batches.append(ToolBatch(items=tuple(pending), parallel=False))
        pending.clear()

    for index, toolCall in enumerate(toolCalls or []):
        name = ((toolCall or {}).get("function") or {}).get("name", "")
        cap = capabilities.get(_normalizeName(name))
        if cap is not None and isParallelEligible(cap):
            pending.append((index, toolCall))
            if len(pending) >= limit:
                _flush()
            continue
        _flush()
        batches.append(ToolBatch(items=((index, toolCall),), parallel=False))
    _flush()
    return batches


def _normalizeName(name: Any) -> str:
    """工具名归一（大小写不敏感），与既有查表口径一致。"""
    return str(name or "").strip().lower()
