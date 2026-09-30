#!/usr/bin/env python3
"""经验质量基准与 CI 门禁（工单 009）——"变好了"要能回答，不能只说"更严了"。

为什么要有这个门禁：002/006/008/010/013 把经验形成链收紧了一大轮（success 三态、
采纳回写、无据不投票、无据不播种），但收紧在观测上是否**让进 prompt 的经验变好**，
此前没有任何可比读数能回答。没有基准，本批只能宣称"更严"。

设计要点：

1. **语料是真实语料，且冻结在仓内**。`tests/fixtures/experience_quality_corpus.json`
   由 `--freeze-corpus` 从生产库 `data/experience_knowledge.db` **只读**投影而来
   （审计实测同一句"你好"重复 5 次、success 位 002 前恒为 1）。票面点名禁止
   `rsi/eval_harness.py:255-265` 那种当场合成的 `f"使用 {tool} 完成任务"`——
   合成句测不出真实重复分布与真实票据覆盖率，故载入时校验来源并拒绝模板句。
2. **读数算式只有一处**：两个读数一律取 `EKB.quality_snapshot()`（工单 008 定的
   唯一来源），本脚本不重算 SQL。临时库用生产写入路径喂
   （`add_experience_record` + `record_injection_adoption`）。两个"空"的方向不同
   也是 008 定下的：`unevidencedRatio=0.0000` 配 `rows=0` 是"没有条目可判"，
   `adoptionSuccessRate=n/a` 才是"分母为零"——报告里两格分开印，不许读成"零无据
   =满分的证据占比"。
3. **A/B 两臂**：`preTightening`（收紧前的判据形态：无据自述投成功票 + 门槛拨到
   名义值 1/0.0）与 `postTightening`（现行：三态票据 + `ExperienceFeedback`
   默认闸值）。两臂都过同一个结晶闸对象，差异只在旋钮与投票形态。
4. **反向锁**：闸值来自 004 的参数事实源（`ExperienceFeedback.crystallize_min_*`
   经 `attach_crystallizer()` 桥推入 `PatternCrystallizer`）。`--min-observations`
   / `--min-success-rate` 把旋钮拨到极端，读数必须跟着变——不变即基准只测算术。
5. **自证不空转**：`tests/fixtures/experience_quality_corpus_low_signal.json`
   是刻意构造的低质探针（全自述成功、零客观回执、同句反复）。门禁每次运行都先
   确认这份探针**会被判红**；探针不红即门禁本身失效，按基础设施错误退出 2。

退出码：0 = 语料质量达标且探针判红；1 = 质量违规；2 = 基础设施错误（脚本跑不起来
按错误处理，"跑不起来就算过"的安全门禁是安全剧场）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sqlite3
import sys

# 控制台码页编不出本脚本的字形（⚠️/🛑/→ 在中文 Windows 的 cp936 下即抛
# UnicodeEncodeError）时，「给出结论」这一步会先把门禁自己打死。
# 同仓先例：scripts/ci_static_gate.py 用的是这两行。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 门禁脚本由 CI 以 `python scripts/ci/experience_quality_gate.py` 直接跑
# （不一定 pip install -e .），显式把仓库根放进 sys.path。
# 位置必须在任何 `from neurova...` 之前：以文件路径执行时 __file__ 所属目录
# 不是仓库根，导入期就看不见 neurova 包——把它挪到导入之后，脚本会以
# `ModuleNotFoundError: No module named 'neurova'` 直接停在第一行（CI 实测）。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.core.data_root import get_data_root  # noqa: E402

CORPUS_SCHEMA = "neurova.experience.quality.corpus/v1"
REAL_SOURCE_KIND = "productionDbReadonlyProjection"
# 低质探针不是真实语料，来源标记也不同：`load_corpus` 默认只认真实投影，探针必须
# 由调用点显式放行。否则"我们构造了一份很差的语料"会被读成"生产语料很差"。
PROBE_SOURCE_KIND = "adversarialLowSignalProbe"
DEFAULT_CORPUS = PROJECT_ROOT / "tests" / "fixtures" / "experience_quality_corpus.json"
LOW_SIGNAL_PROBE = PROJECT_ROOT / "tests" / "fixtures" / "experience_quality_corpus_low_signal.json"
PRODUCTION_DB = get_data_root() / "experience_knowledge.db"

# 票面点名的禁地：`rsi/eval_harness.py:255-265` 当场合成的
# `f"使用 {tool} 成功完成"`。这种句子没有真实重复分布，测出来的只是门槛算术。
_SYNTHETIC_TEMPLATE = re.compile(r"^使用\s+\S+\s+(成功完成|完成任务)")

_TURN_KEYS = (
    "rowId",
    "agentId",
    "skillName",
    "userInput",
    "success",
    "timestamp",
    "seenCount",
    "evidenceState",
    "adoptionOutcome",
)

# 单条回合的限长窗口：与 `PatternCrystallizer.observe` 自身保存的 `context[:200]`
# 同宽——窗口之外对闸门不可见，留在冻结语料里只是把整篇对话正文抄进仓库。
USER_INPUT_WINDOW = 200


class CorpusError(RuntimeError):
    """语料本身不可用（缺文件/来源不明/混入合成句）——按基础设施错误退出 2。"""


class GateUnavailable(RuntimeError):
    """门禁跑不起来（依赖缺失/临时库建不出来）。

    "跑不起来就算过"的安全门禁是安全剧场，故它同样出声，不与"质量不达标"（红）混用。
    """


@contextlib.contextmanager
def _quiet_logs():
    """压掉 neurova 的 INFO/DEBUG 洪流，让报告可 diff；退出时还原全局开关。

    `get_logger()` 给每个模块 logger 自带 handler 与 DEBUG 级别，改 root 级别压不住，
    只能用 `logging.disable` 这个总闸。还原是必须的：本脚本也被单测同进程调用。
    """
    previous = logging.Logger.manager.disable
    logging.disable(logging.INFO)
    try:
        yield
    finally:
        logging.disable(previous)


# 报告里的读数顺序与标签（固定顺序 + 固定精度 = 两批输出可直接 diff）。
# 左边是本脚本的展示名，右边是 `quality_snapshot()` 的键——算式不在这里重算。
_READING_LABELS = (
    ("rows", "rows"),
    ("unevidencedRatio", "unevidenced_ratio"),
    ("hitRate", "hit_rate"),
    ("adoptionDecisions", "adoption_decisions"),
    ("adoptionSuccessRate", "adoption_success_rate"),
    ("adoptionUnevidenced", "adoption_unevidenced"),
)


def _relpath(path: Path) -> str:
    """报告里印仓内相对路径——绝对路径含 runner 目录，两批输出就 diff 不动。"""
    file_path = Path(path)
    return str(file_path.relative_to(PROJECT_ROOT)) if file_path.is_relative_to(PROJECT_ROOT) else str(file_path)


def _format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def _format_signed(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.4f}" if isinstance(value, float) else f"{value:+d}"


_TURN_COLUMNS = (
    "id",
    "agent_id",
    "skill_name",
    "context",
    "success",
    "timestamp",
    "seen_count",
    "evidence_state",
    "adoption_outcome",
)


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """以 `mode=ro` 打开经验库。

    生产库是运行数据（纪律 6）：本脚本任何一次取证都不许写它。URI 只读连接在
    写入时抛 `sqlite3.OperationalError`，这是可测的约束而不是注释里的约定。
    """
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def freeze_corpus(db_path: str) -> Dict[str, Any]:
    """把经验库投影成可入库的冻结语料（不含 `result` 回复文本）。

    投影只取形成侧与采纳侧的字段：`result` 自 011 起已退出内容身份键（回复文本
    每轮都是新的 LLM 输出），基准读数也不需要它，故不冻结——既减小夹具，也避免
    把对话正文抄进仓库。
    """
    cols = ", ".join(_TURN_COLUMNS)
    conn = connect_readonly(db_path)
    try:
        rows: List[Dict[str, Any]] = [
            dict(r) for r in conn.execute(f"SELECT {cols} FROM experience_records ORDER BY id")
        ]
    finally:
        conn.close()

    turns: List[Dict[str, Any]] = []
    for row in rows:
        try:
            context = json.loads(row.get("context") or "{}")
        except json.JSONDecodeError:
            context = {}
        turns.append(
            {
                "rowId": int(row["id"]),
                "agentId": row.get("agent_id"),
                "skillName": row.get("skill_name") or "",
                "userInput": str(context.get("user_input", ""))[:USER_INPUT_WINDOW],
                "success": bool(row.get("success")),
                "timestamp": row.get("timestamp") or "",
                "seenCount": int(row.get("seen_count") or 1),
                "evidenceState": row.get("evidence_state") or "unevidenced",
                "adoptionOutcome": row.get("adoption_outcome"),
            }
        )

    return {
        "schema": CORPUS_SCHEMA,
        "source": {"kind": "productionDbReadonlyProjection", "dbPath": str(db_path), "rowCount": len(turns)},
        "turns": turns,
    }


def write_corpus(path: Path, corpus: Dict[str, Any]) -> None:
    """冻结语料落盘（键序固定，便于 diff）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_corpus(path: Path, *, allowed_kinds: tuple = (REAL_SOURCE_KIND,)) -> Dict[str, Any]:
    """读取并校验冻结语料。

    三道校验都是"基准是否还在测真实东西"的入口条件，缺一道就足够让读数失去意义：
    schema 对不上⇒字段语义变了；来源不在白名单⇒吃的是手搓样本；混入模板句⇒
    测的是 `eval_harness` 那句合成话，而不是生产分布。

    `allowed_kinds` 默认只放真实投影；低质探针要显式点名才读得进来。
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise CorpusError(f"语料文件不存在: {_relpath(file_path)}")
    try:
        corpus = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"语料文件不是合法 JSON: {exc}") from exc

    if not isinstance(corpus, dict) or corpus.get("schema") != CORPUS_SCHEMA:
        raise CorpusError(f"语料 schema 不是 {CORPUS_SCHEMA}——字段语义已变，读数不可比")
    kind = (corpus.get("source") or {}).get("kind")
    if kind not in allowed_kinds:
        raise CorpusError(
            f"语料来源不可作为本用途的输入（source.kind={kind}，允许={allowed_kinds}）"
            "——基准必须吃真实语料，否则回答不了\"变好了没有\""
        )
    turns = corpus.get("turns")
    if not isinstance(turns, list) or not turns:
        raise CorpusError("语料 turns 为空")
    for turn in turns:
        missing = [key for key in _TURN_KEYS if key not in turn]
        if missing:
            raise CorpusError(f"语料第 {turn.get('rowId')} 行缺字段 {missing}")
        if not str(turn["userInput"]).strip():
            raise CorpusError(f"语料第 {turn['rowId']} 行 userInput 为空——无模式键，闸门无从判定")
        if _SYNTHETIC_TEMPLATE.search(str(turn["userInput"])):
            raise CorpusError(
                f"语料混入了当场合成的模板句（rowId={turn['rowId']}）："
                f"{turn['userInput']!r}——这种句子只能测门槛算术"
            )
    return corpus


# ── A/B 两臂 ────────────────────────────────────────────────────────────────

ARMS = ("preTightening", "postTightening")
# 收紧前的"闸"是名义值：观察 1 次、成功率 0.0 即放行，且每条观察都盖成功章
# （002 之前 `success` 位恒为真：`record.get("success", True)`）。
PRE_TIGHTENING_NOMINAL_GATE = {"minObservations": 1, "minSuccessRate": 0.0}
# 读数固定精度：CI 里两批 diff 只有数字逐位一致才可解释。
READING_PRECISION = 4
# 采纳回写的三格 → 006 `record_injection_adoption(adopted=)` 的入参
_ADOPTION_OUTCOMES = (("success", True), ("failure", False), ("unevidenced", None))


def _turn_vote(turn: Dict[str, Any], *, green_tick: bool):
    """这条回合给结晶闸投什么票。

    `green_tick=True` 是收紧前的判据形态（自述即成功章）；现行形态下无服务端票据
    的观察投 None——记账、不投票（工单 003/010），既不是成功票也不是失败票。
    """
    if green_tick:
        return True
    if turn["evidenceState"] == "unevidenced":
        return None
    return bool(turn["success"])


def _group_turns(turns: List[Dict[str, Any]]) -> Dict[tuple, List[Dict[str, Any]]]:
    """按 (agent, 技能标签, 回合文本) 分组——同一模式的重复观察是一个整体。

    排序后分组：结晶闸看的是"同一模式出现几次"，分组顺序不稳定会让读数不稳定。
    """
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for turn in sorted(turns, key=lambda t: int(t["rowId"])):
        groups.setdefault((turn["agentId"], turn["skillName"], turn["userInput"]), []).append(turn)
    return groups


def _group_admitted(feedback: Any, group: List[Dict[str, Any]], *, green_tick: bool) -> bool:
    """这一组真实回合能否过结晶闸——闸本身一处都不重写。

    门槛来自 004 的参数事实源：值写在 `ExperienceFeedback.crystallize_min_*` 上，
    经 `attach_crystallizer()` 桥推进 `PatternCrystallizer`。观察形态照生产：
    `post_chat_pipeline._step_record_experience` 每个工具各观察一次，上下文是
    用户输入，`seen_count` 是这条经验真实出现过的次数。
    """
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

    crystallizer = PatternCrystallizer(engine=None, state_path=None)
    feedback.attach_crystallizer(crystallizer)
    for turn in group:
        for tool in [t for t in str(turn["skillName"]).split(",") if t] or ["chat"]:
            for _ in range(max(1, int(turn["seenCount"]))):
                crystallizer.observe(
                    tool_name=tool,
                    context=turn["userInput"],
                    success=_turn_vote(turn, green_tick=green_tick),
                )
    # 过闸的候选默认进待裁决队列（混合信号层，工单 005）；队列溢出丢弃也计过闸，
    # 否则"闸开得越大读数越小"会成为一个假象。
    return bool(crystallizer.list_pending()) or crystallizer.pending_dropped > 0


def _snapshot_of_admitted(admitted: List[Dict[str, Any]], db_path: Path) -> Dict[str, Any]:
    """把过闸回合灌进临时经验库，读数取 `quality_snapshot()`（工单 008 唯一算式）。

    写入走生产通路（`add_experience_record` 含 011 的内容门合并、
    `record_injection_adoption` 含 006 的三态回写），本脚本不写一条 SQL。
    """
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase, ExperienceRecord

    ekb = ExperienceKnowledgeBase(db_path=str(db_path))
    try:
        ordered = sorted(admitted, key=lambda t: int(t["rowId"]))
        record_ids: Dict[int, int] = {}
        for turn in ordered:
            record_ids[int(turn["rowId"])] = ekb.add_experience_record(
                skill_name=turn["skillName"],
                exp=ExperienceRecord(
                    skill_name=turn["skillName"],
                    context={"user_input": turn["userInput"]},
                    result=None,
                    success=bool(turn["success"]),
                    timestamp=turn["timestamp"],
                ),
                agent_id=turn["agentId"],
                evidence=None if turn["evidenceState"] == "unevidenced" else True,
            )
        for outcome, adopted in _ADOPTION_OUTCOMES:
            ids = [record_ids[int(t["rowId"])] for t in ordered if t["adoptionOutcome"] == outcome]
            # 语料里 adoptionOutcome 为 null 的回合不进这个循环——"没注入"与
            # "注入后失败"是两件事，把前者写成 failure 等于凭空泼脏水（工单 006）。
            ekb.record_injection_adoption(ids, adopted)
        return ekb.quality_snapshot()
    finally:
        ekb.close()


def _round_readings(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: (round(value, READING_PRECISION) if isinstance(value, float) else value)
        for key, value in snapshot.items()
    }


def measure_arms(
    corpus: Dict[str, Any],
    *,
    min_observations: int | None = None,
    min_success_rate: float | None = None,
) -> Dict[str, Any]:
    """对同一份真实语料跑 A/B 两臂，输出可比读数与带符号的差值。

    旋钮只作用于现行闸（`postTightening`）：`min_observations` / `min_success_rate`
    经 `ExperienceFeedback` 的属性 setter 进入，与 RSI 调参走同一个事实源。
    不传即用生产默认（`ExperienceFeedback()` 构造值）。
    """
    from neurova.evolution.experience_feedback import ExperienceFeedback

    from neurova.security.governance_settings import resolve_flag

    if not resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE"):
        raise GateUnavailable(
            "结晶 LLM 裁决闸关（治理设置或 env 显式关）时候选直写存储引擎，"
            "基准没有可观测的过闸面（这不是放行理由）"
        )

    turns = corpus["turns"]
    groups = _group_turns(turns)
    arms: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="neurova-quality-") as work_dir:
        for arm in ARMS:
            green_tick = arm == "preTightening"
            feedback = ExperienceFeedback()
            if green_tick:
                feedback.crystallize_min_observations = PRE_TIGHTENING_NOMINAL_GATE["minObservations"]
                feedback.crystallize_min_success_rate = PRE_TIGHTENING_NOMINAL_GATE["minSuccessRate"]
            else:
                if min_observations is not None:
                    feedback.crystallize_min_observations = int(min_observations)
                if min_success_rate is not None:
                    feedback.crystallize_min_success_rate = float(min_success_rate)
            admitted = [
                turn
                for group in groups.values()
                if _group_admitted(feedback, group, green_tick=green_tick)
                for turn in group
            ]
            arms[arm] = {
                "gate": {
                    "minObservations": int(feedback.crystallize_min_observations),
                    "minSuccessRate": round(float(feedback.crystallize_min_success_rate), READING_PRECISION),
                    "unevidencedVotesAsSuccess": green_tick,
                },
                "snapshot": _round_readings(
                    _snapshot_of_admitted(admitted, Path(work_dir) / f"{arm}.db")
                ),
            }

    pre, post = arms["preTightening"]["snapshot"], arms["postTightening"]["snapshot"]
    rate_delta = (
        None
        if pre["adoption_success_rate"] is None or post["adoption_success_rate"] is None
        else round(post["adoption_success_rate"] - pre["adoption_success_rate"], READING_PRECISION)
    )
    return {
        "corpusTurns": len(turns),
        "corpusGroups": len(groups),
        "arms": arms,
        "delta": {
            "rows": post["rows"] - pre["rows"],
            "unevidencedRatio": round(post["unevidenced_ratio"] - pre["unevidenced_ratio"], READING_PRECISION),
            "adoptionSuccessRate": rate_delta,
        },
    }


def judge(measurement: Dict[str, Any]) -> List[Dict[str, str]]:
    """把两臂读数折成门禁判据。阈值全部取自 008 的 `RSIMetrics.ALERT_THRESHOLDS`。

    四条判据各自堵一种"看起来没问题"的形态：
    · `corpusMostlyUnevidenced`——语料本身过半没有客观回执，门槛再严也只是挑
      哪一半没证据；
    · `adoptionHurts`——过了闸的经验照做仍然做砸（决策数不足不下结论，008 口径）；
    · `gateAdmitsNothing`——读不到数就当过关，是 008 刚删掉的那种假观测面；
    · `gateNotTightening`——收紧后放进来的比无闸还多，说明闸根本没咬合。
    """
    from neurova.evolution.rsi.metrics import RSIMetrics

    thresholds = RSIMetrics.ALERT_THRESHOLDS
    pre = measurement["arms"]["preTightening"]["snapshot"]
    post = measurement["arms"]["postTightening"]["snapshot"]
    violations: List[Dict[str, str]] = []

    ratio_warn = thresholds["experience_unevidenced_ratio_warning"]
    if pre["unevidenced_ratio"] >= ratio_warn:
        violations.append(
            {
                "rule": "corpusMostlyUnevidenced",
                "detail": (
                    f"语料侧 {pre['rows']} 条里无客观回执占比 {pre['unevidenced_ratio']:.4f} ≥ {ratio_warn}"
                    "——质量位过半不携带信息，门槛再严也只是在挑哪一半没证据"
                ),
            }
        )

    rate = post["adoption_success_rate"]
    min_decisions = thresholds["experience_adoption_min_decisions"]
    rate_warn = thresholds["experience_adoption_success_rate_warning"]
    if rate is not None and post["adoption_decisions"] >= min_decisions and rate < rate_warn:
        violations.append(
            {
                "rule": "adoptionHurts",
                "detail": (
                    f"过闸条目事后成功率 {rate:.4f} < {rate_warn}"
                    f"（{post['adoption_decisions']} 次采纳决策）——照经验做整体在帮倒忙"
                ),
            }
        )

    if post["rows"] == 0:
        violations.append(
            {
                "rule": "gateAdmitsNothing",
                "detail": "现行闸一条经验都没放行：这份语料撑不起可注入的经验，读不到数不等于合格",
            }
        )

    if post["rows"] > pre["rows"]:
        violations.append(
            {
                "rule": "gateNotTightening",
                "detail": (
                    f"收紧后放行 {post['rows']} 条 > 无闸时 {pre['rows']} 条——闸没咬合，读数不可信"
                ),
            }
        )

    return violations


def _format_arm_line(name: str, arm: Dict[str, Any]) -> str:
    gate = arm["gate"]
    snapshot = arm["snapshot"]
    readings = " ".join(
        f"{label}={_format_value(snapshot[key])}" for label, key in _READING_LABELS
    )
    knobs = ",".join(
        [
            f"minObservations={gate['minObservations']}",
            f"minSuccessRate={_format_value(gate['minSuccessRate'])}",
            f"unevidencedVotesAsSuccess={gate['unevidencedVotesAsSuccess']}",
        ]
    )
    return f"  arm={name} gate[{knobs}] {readings}"


def _format_delta_line(delta: Dict[str, Any]) -> str:
    return (
        f"  delta(post-pre) rows={delta['rows']:+d} "
        f"unevidencedRatio={_format_signed(delta['unevidencedRatio'])} "
        f"adoptionSuccessRate={_format_signed(delta['adoptionSuccessRate'])}"
    )


def _direction_line(measurement: Dict[str, Any]) -> str:
    """把两个读数的方向写成一句人话——验收要求"差值方向明确"。"""
    pre = measurement["arms"]["preTightening"]["snapshot"]
    post = measurement["arms"]["postTightening"]["snapshot"]
    ratio = "下降" if post["unevidenced_ratio"] < pre["unevidenced_ratio"] else (
        "上升" if post["unevidenced_ratio"] > pre["unevidenced_ratio"] else "持平"
    )
    if pre["adoption_success_rate"] is None or post["adoption_success_rate"] is None:
        rate = "不可比（采纳决策不足）"
    else:
        rate = (
            "上升" if post["adoption_success_rate"] > pre["adoption_success_rate"] else (
                "下降" if post["adoption_success_rate"] < pre["adoption_success_rate"] else "持平"
            )
        )
    return (
        f"  方向: 入库条目无证据占比 {_format_value(pre['unevidenced_ratio'])}→"
        f"{_format_value(post['unevidenced_ratio'])} {ratio}；"
        f"被采纳条目事后成功率 {_format_value(pre['adoption_success_rate'])}→"
        f"{_format_value(post['adoption_success_rate'])} {rate}"
    )


def run_gate(
    corpus_path: Path,
    *,
    min_observations=None,
    min_success_rate=None,
    allowed_kinds: tuple | None = None,
) -> Dict[str, Any]:
    """跑一次基准：先自证探针会红，再读真实语料的 A/B。

    探针不红 ⇒ `GateUnavailable`：判据坏掉的"绿"比红危险得多。

    `allowed_kinds=None` ⇒ 只认真实投影（CI 走的这条）；显式换语料做实验时才允许
    点名探针来源，否则"注入低质语料看它报不报红"这一步没地方跑。
    """
    probe = judge(measure_arms(load_corpus(LOW_SIGNAL_PROBE, allowed_kinds=(PROBE_SOURCE_KIND,))))
    if not probe:
        raise GateUnavailable(
            f"门禁自证失败：低质探针（{LOW_SIGNAL_PROBE.name}）没有被任何判据判红，"
            "此刻的\"绿\"不作数——先修判据再谈放行"
        )
    corpus = load_corpus(corpus_path) if allowed_kinds is None else load_corpus(
        corpus_path, allowed_kinds=allowed_kinds
    )
    measurement = measure_arms(
        corpus,
        min_observations=min_observations,
        min_success_rate=min_success_rate,
    )
    return {"probeViolations": probe, "measurement": measurement, "violations": judge(measurement)}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="经验质量基准与 CI 门禁（工单 009）")
    parser.add_argument("--freeze-corpus", nargs="?", const=str(PRODUCTION_DB), default=None, metavar="DB",
                        help="只读投影经验库以重算冻结语料（维护者动作，CI 不跑）")
    parser.add_argument("--out", default=str(DEFAULT_CORPUS), metavar="PATH", help="冻结语料的输出路径")
    parser.add_argument("--corpus", default=None, metavar="PATH",
                        help="换基准语料（默认读仓内冻结的真实语料；显式点名才允许探针来源）")
    parser.add_argument("--min-observations", type=int, default=None, metavar="N",
                        help="拨 004 的观察数旋钮（反向锁：读数必须跟着变）")
    parser.add_argument("--min-success-rate", type=float, default=None, metavar="X",
                        help="拨 004 的成功率旋钮")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)

    with _quiet_logs():
        try:
            if args.freeze_corpus:
                corpus = freeze_corpus(args.freeze_corpus)
                write_corpus(Path(args.out), corpus)
                print(f"已冻结 {len(corpus['turns'])} 行 → {args.out}")
                return 0
            corpus_path = Path(args.corpus) if args.corpus else DEFAULT_CORPUS
            result = run_gate(
                corpus_path,
                min_observations=args.min_observations,
                min_success_rate=args.min_success_rate,
                allowed_kinds=(REAL_SOURCE_KIND, PROBE_SOURCE_KIND) if args.corpus else None,
            )
        except (CorpusError, GateUnavailable, sqlite3.Error) as exc:
            print(f"门禁不可用: {exc}", file=sys.stderr)
            return 2

    measurement = result["measurement"]
    violations = result["violations"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if violations else 0

    print("=" * 72)
    print("经验质量基准（工单 009）")
    print("=" * 72)
    print(f"  语料={_relpath(corpus_path)} turns={measurement['corpusTurns']} groups={measurement['corpusGroups']}")
    for arm in ARMS:
        print(_format_arm_line(arm, measurement["arms"][arm]))
    print(_format_delta_line(measurement["delta"]))
    print(_direction_line(measurement))
    print(
        "  自证探针: {} 已判红（{}）".format(
            LOW_SIGNAL_PROBE.name, ",".join(v["rule"] for v in result["probeViolations"])
        )
    )
    if violations:
        print(f"门禁不通过，{len(violations)} 项质量违规：")
        for violation in violations:
            print(f"  - {violation['rule']}: {violation['detail']}")
        return 1
    print("门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
