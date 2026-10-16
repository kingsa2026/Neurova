"""能力缺口信号（T-03）：自主造能力的入口判据，取代用户措辞关键词。

## 为什么

事故取证（2026-09-24）：用户上传 `memory.db` 说"还有这个 你看看有什么信息可以
提炼"，三轮未成。自主创建的入口 `chat_pipeline._check_nl_synthesis` 此前挂在
**用户措辞关键词**（帮我/读取/写入/搜索/…）上，事故三轮原话零命中 ——
入口对"确实缺能力"这件事不敏感，只对"用户说得像不像命令"敏感。

真正的信号是**能力缺口**，而且它们本来就在链路上，本模块只做收敛：

==============  ==========================================================  ==========================
信号              既有读数在哪                                                 消费方
==============  ==========================================================  ==========================
S1 附件读不出     `attachment_parser.suggestExtractionPrimitive` 返回 None     附件注入步
S2 连续工具失败   执行咽喉的客观成败判据（`_result_is_success`）               工具执行后钩子
S3 检索零命中     `tool_search.search_catalog` 的命中条数                     控制工具执行体
==============  ==========================================================  ==========================

**不新造第二套工具健康度体系**：失败判据仍来自执行咽喉（`tool_layers` 已有的
`tool_lifecycle`/`adaptive_multiplier` 不被本模块改写）；S2 只把"同轮连续两次"
这件事记成缺口，不重算权重、不另起计数器表。

## 边界

- 信号**分两族且用途在单源登记**（见上方 `_GAP_PURPOSE`）：capability 族驱动自主创建，
  harness 族（`false_completion`/`loop_stalled`）只作环节证据，**不得**驱动自主创建。
- 收件箱是**轮次级**且**读取即消费**（`detectCapabilityGap` 读到就清），
  下一轮不会无据重放上一轮的缺口 —— 这与工具消息账本同生命周期，
  故同样落在 ContextVar（`core.turn_context` 的轮次族）。
  另有 `peekCapabilityGapKinds()` 作**只读**观察口（评测面逐任务取证用），
  它既不消费也不写指标；回合边界由调用方走 `clearCapabilityGap` 收口。
- 无 env 开关：接线要么生效要么不存在（AGENTS §2 无例外条款）。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, List, NamedTuple, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 缺口类别的**单源**名单（键名即观测指标名的后缀，不另起第二份枚举）。
#:
#: 两族同表但**用途不同**（用途也是这一处定义，不在消费方各判一遍）：
#: - `capability` 族＝"缺一项能力"，驱动自主创建（`chat_pipeline._check_nl_synthesis`）；
#: - `harness` 族＝"环走过不去"，**不驱动造工具**——死循环/假完成不是"缺一条工具"，
#:   把这类信号喂给自主合成只会造出更多没人用的工具（那是同一根因的另一种坏法）。
#: 边界改口的来历：原判据口径写的是"信号有界三条，不扩面"（T-03 立模块时）。
#: 2026-10-16 用户点单把环节轴并进本单源（ModularRSI 对照 §7.1-Q4 甲案），
#: 因为 `self_model` 五算子与 `FailurePattern` 六桶各自回答的是别的问题
#: （谁在失败 / 缺哪项能力 / 改哪个环节），再散着写就会长出第三套分类。
GAP_ATTACHMENT_UNREADABLE = "attachment_unreadable"
GAP_REPEATED_TOOL_FAILURE = "repeated_tool_failure"
GAP_CATALOG_MISS = "catalog_miss"
GAP_FALSE_COMPLETION = "false_completion"
GAP_LOOP_STALLED = "loop_stalled"

#: kind → 用途。新类别必须在此登记用途，否则视为非法类别被拒收。
_GAP_PURPOSE: Dict[str, str] = {
    GAP_ATTACHMENT_UNREADABLE: "capability",
    GAP_REPEATED_TOOL_FAILURE: "capability",
    GAP_CATALOG_MISS: "capability",
    GAP_FALSE_COMPLETION: "harness",
    GAP_LOOP_STALLED: "harness",
}

GAP_KINDS = tuple(_GAP_PURPOSE)
CAPABILITY_GAP_KINDS = tuple(k for k, v in _GAP_PURPOSE.items() if v == "capability")
HARNESS_GAP_KINDS = tuple(k for k, v in _GAP_PURPOSE.items() if v == "harness")

#: S2 判据边界：同一轮内**连续**失败达到此条数才算缺口。
#: 一次失败是噪声（参数写错一次很常见），两次同轮失败说明"这条工具链解决不了
#: 眼前这个任务"，那才该去找/造别的能力。
REPEATED_FAILURE_THRESHOLD = 2

#: 观测指标名（写进 `evolution/rsi/metrics` 的既有 metric 通道，D2）。
#: 前缀 `capability_gap_` 与类别名拼接，读侧由 `rsi/metrics` 的告警面消费。
METRIC_GAP_TOTAL = "capability_gap_total"

_inbox: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar("capability_gap_inbox", default=None)
_failure_streak: ContextVar[int] = ContextVar("capability_gap_failure_streak", default=0)


class CapabilityGap(NamedTuple):
    """一次缺口判定的结果。

    `kinds` 是去重后的类别清单；`details` 逐类别保留原始读数（工具名、附件的
    `file_id` 与 `status`、检索词），供日志与观测面点名，而不是只说一句"有缺口"。
    """

    hasGap: bool
    kinds: List[str]
    details: Dict[str, List[Dict[str, Any]]]
    #: 按用途拆好的两族（消费方不许各自再判一遍）。`hasGap` 是"本轮有任何缺口"，
    #: 自主创建的入口只看 `capabilityKinds`——环卡住/假完成不是"缺一条工具"。
    capabilityKinds: List[str] = []
    harnessKinds: List[str] = []


def _inbox_list() -> List[Dict[str, Any]]:
    current = _inbox.get()
    if current is None:
        current = []
        _inbox.set(current)
    return current


def recordCapabilityGap(kind: str, detail: Optional[Dict[str, Any]] = None, session_id: str = "") -> None:
    """把一条缺口信号投进本轮收件箱。

    类别不在单源名单内即拒绝并点名 —— 静默接收未知类别会让名单慢慢失效，
    而名单是观测面与判据面共用的那一份。`session_id` 只进日志用于归因。

    S2（连续失败）**在这一处判阈值**：调用方每报一次失败就调一次，
    达到 `REPEATED_FAILURE_THRESHOLD` 才落成缺口。阈值判据只有这一处，
    不在调用方各写一遍（教义第 6 条）。
    """
    if kind not in GAP_KINDS:
        logger.warning("未知的能力缺口类别被拒绝: %r（合法类别 %s）", kind, list(GAP_KINDS))
        return

    if kind == GAP_REPEATED_TOOL_FAILURE:
        streak = int(_failure_streak.get() or 0) + 1
        _failure_streak.set(streak)
        if streak < REPEATED_FAILURE_THRESHOLD:
            logger.debug("[能力缺口] 工具失败 %d 次（阈值 %d），暂不构成缺口", streak, REPEATED_FAILURE_THRESHOLD)
            return
        detail = dict(detail or {})
        detail["streak"] = streak

    _inbox_list().append({"kind": kind, "detail": dict(detail or {})})
    logger.info("[能力缺口] 命中 %s（session=%s detail=%s）", kind, session_id or "-", detail or {})


def clearCapabilityGap(session_id: str = "") -> None:
    """清空本轮收件箱与失败连击（轮次开始时调用；session_id 仅用于日志归因）。"""
    _inbox.set([])
    _failure_streak.set(0)


def noteToolSuccess() -> None:
    """任一工具成功即清零连击 —— "连续"是 S2 判据本体，隔一次成功再失败不算连续。"""
    _failure_streak.set(0)


def noteAttachmentSignal(
    filename: str, file_type: str, file_id: str, status: str
) -> bool:
    """S1 的**唯一生产点**：抽取面拿不到正文时投一条缺口信号。

    由 `chat_pipeline._inject_attachments_into_input` 在
    `extract_attachment_text` 返回空正文的分支调用 —— 那里是**真正知道**
    "这个附件读不出内容"的地方，`status` 也是抽取器给出的那份（不重算）。

    为什么不在别处按文件元数据另立一份判据：那是同一件事的第二份定义，
    两处迟早对不上（例如新增一种可抽取格式时只改一处）。返回是否构成本轮缺口。

    图片/音频/视频走 vision / ASR / 占位通道，本就不是文本抽取面 ——
    由调用方（注入步）自行排除，本函数不做二次分类。
    """
    detail = {
        "filename": filename,
        "file_type": file_type,
        "file_id": file_id or "",
        "status": status,
    }
    recordCapabilityGap(GAP_ATTACHMENT_UNREADABLE, detail)
    return True


def detectCapabilityGap(signals: Optional[List[Dict[str, Any]]] = None) -> CapabilityGap:
    """读取并**消费**本轮缺口：返回判定后清空收件箱。

    `signals` 是调用方就地提供的额外信号（与 `collectAttachmentSignals` 的
    返回值同形）；收件箱与入参信号合并判定，调用方无需先调
    `recordCapabilityGap` 再判。

    消费语义是有意的：缺口是"这一轮遇到了解决不了的事"，不是持久状态。
    若读取不清，下一轮会拿上一轮的缺口无据重放一遍合成。
    """
    kinds: List[str] = []
    details: Dict[str, List[Dict[str, Any]]] = {}
    pending = _inbox_list() + [dict(s) for s in (signals or [])]
    for item in pending:
        kind = item.get("kind")
        if kind not in kinds:
            kinds.append(kind)
        details.setdefault(kind, []).append(item.get("detail") or {})
    _inbox.set([])

    capabilityKinds = [k for k in kinds if _GAP_PURPOSE.get(k) == "capability"]
    harnessKinds = [k for k in kinds if _GAP_PURPOSE.get(k) == "harness"]

    if kinds:
        # 观测面（D2）：走既有 metric 通道，键名与类别名同源。
        # 只写不读是断点（AGENTS §2），故读侧在本文件下方 `gapMetricReadout()`，
        # 由 `/governance/rsi/status` 的 metrics 视图取走。
        recordGapMetrics(kinds)

    return CapabilityGap(hasGap=bool(kinds), kinds=kinds, details=details,
                         capabilityKinds=capabilityKinds, harnessKinds=harnessKinds)


def peekCapabilityGapKinds() -> List[str]:
    """**只读不消费**地取本轮收件箱里已有的缺口类别（去重、保持投递次序）。

    为什么要第二个读数口：`detectCapabilityGap` 的契约是「读取即消费」，而评测面要
    在**每条任务**执行后各取一次环节证据。逐条调消费口等于把自主合成的入口判据提前
    吃掉；逐条调它还会按任务数累加指标——观测面就从「命中了几类缺口」变成「被读了几次」。
    peek 两样都不做：不清收件箱（清空由调用方走既有 `clearCapabilityGap` 单点），
    不写指标。

    跨任务边界由调用方负责（`evolution/eval/runner` 逐条清），本函数只管读。
    """
    seen: List[str] = []
    for item in _inbox.get() or []:
        kind = item.get("kind")
        if kind and kind not in seen:
            seen.append(kind)
    return seen


def recordGapMetrics(kinds: List[str]) -> None:
    """把缺口命中写进 RSI 既有 metric 通道（写侧；读侧见 `gapMetricReadout`）。"""
    try:
        from neurova.agent.gap_metric_channel import bumpGapMetric

        bumpGapMetric(list(kinds))
    except Exception:  # noqa: BLE001 - 观测面故障不得阻断对话主链
        logger.debug("能力缺口指标写入失败（忽略）", exc_info=True)


def gapMetricReadout() -> Dict[str, Any]:
    """缺口指标的读侧（与写侧同一模块持有，避免"只写不读"的断点）。"""
    from neurova.agent.gap_metric_channel import readGapMetrics

    return readGapMetrics()
