# -*- coding: utf-8 -*-
"""通用 suite 评测执行器（N3，2026-11-17 新建能力）。

与 `rag_eval` / `multi_agent` 同构的第三方执行链：判据注入式、逐任务故障
隔离、事实记录、不伪造分数（simulated 诚实纪律）。

背景：`neurova/api/endpoints/benchmark.py` 的 `/run` 此前只记录 simulated
运行（score=None）。原 `neurova/benchmark` 门面（7 类框架）从未服务过该端点
且已按票④退役——本模块是**新建**的执行器，不是门面复活，也不复制门面。

形态：
- 任务 = `SuiteTask`（题面 prompt + 判据 check(answer)→(passed, score, details)），
  判据随任务注入，执行器只产事实；
- 任务库按 suite_id 注册（`registerSuiteTasks`），现役种子库覆盖
  reasoning-v1 / coding-v1 / memory-v1 / creative-v1；
  **multimodal-v1 不接任务库**（文本 LLM 通道无法诚实考多模态）——对该 suite
  的运行请求走端点既有 simulated 路径，不硬考；
- `runSuite` 逐任务调 `answerFn(prompt)` 取回答、计量时延、按判据给分；
  answerFn 抛异常＝该任务失败事实（计 0 分、记 error、计入 tasks_total），
  不中断整个 run、不悄悄剔除、不谎报；
- coding 套件种子题采用「读代码答输出值」形式（判分确定性精确匹配）；
  「让 LLM 写代码并在服务端执行」的判分面涉及任意代码执行安全，不在本批落地。

LLM 通道由调用方注入（端点侧复用 `_rag_llm_fn` 单一事实源），本模块不关心
provider 细节；无通道时由端点如实 503，不在本模块伪造回答。
"""
from __future__ import annotations

import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

CheckFn = Callable[[str], Tuple[bool, float, dict]]
_ANSWER_SNIPPET_LEN = 400
_SCORE_DIGITS = 6


# ── 任务与判据 ─────────────────────────────────────────────────────

@dataclass
class SuiteTask:
    """一道评测题：题面 + 判据。判据输入被测方回答，输出 (passed, score, details)。"""

    task_id: str
    prompt: str
    check: CheckFn
    description: str = ""


_PUNCT = "。．，、；：！？!?,.;:~～…—·-_'\"“”‘’（）()《》<>【】[]{}|\\\n\r\t"


def normalizeAnswer(answer: str) -> str:
    """归一化：NFKC（全角→半角）+ 小写 + 去首尾空白与标点。判分确定性单源。

    只去**首尾**空白/标点，不去内部空格——"1 5" 与 "15" 必须不等，
    判分从严（宁可判错不给误判对）。
    """
    text = unicodedata.normalize("NFKC", str(answer or "")).strip().lower()
    return text.strip(_PUNCT)


def exactAnswer(gold: str) -> CheckFn:
    """精确匹配判据（归一化后相等）。"""

    def _check(answer: str) -> Tuple[bool, float, dict]:
        normalized = normalizeAnswer(answer)
        passed = normalized == normalizeAnswer(gold)
        return passed, (1.0 if passed else 0.0), {"gold": gold, "answer": normalized}

    return _check


def markersPresent(markers: Sequence[str]) -> CheckFn:
    """多标记判据：全部命中才 passed，按命中比例给分（部分诚实给分）。"""

    def _check(answer: str) -> Tuple[bool, float, dict]:
        text = str(answer or "")
        missing = [m for m in markers if m not in text]
        score = round((len(markers) - len(missing)) / max(len(markers), 1), _SCORE_DIGITS)
        return (not missing), score, {"missing_markers": missing}

    return _check


# ── 任务库注册表 ───────────────────────────────────────────────────

_BANK_LOCK = threading.RLock()
_SUITE_BANKS: Dict[str, List[SuiteTask]] = {}


def registerSuiteTasks(suiteId: str, tasks: Sequence[SuiteTask]) -> None:
    """按 suite 注册任务库（同 id 覆盖，保持幂等）。"""
    with _BANK_LOCK:
        _SUITE_BANKS[suiteId] = list(tasks)


def getSuiteTasks(suiteId: str) -> List[SuiteTask]:
    with _BANK_LOCK:
        return list(_SUITE_BANKS.get(suiteId, []))


def suiteWired(suiteId: str) -> bool:
    """该 suite 是否接了真实任务库（未接＝端点走 simulated，不硬考）。"""
    with _BANK_LOCK:
        return bool(_SUITE_BANKS.get(suiteId))


def clearSuiteBanks() -> None:
    with _BANK_LOCK:
        _SUITE_BANKS.clear()


# ── 执行器 ─────────────────────────────────────────────────────────

def runSuite(
    tasks: Sequence[SuiteTask],
    answerFn: Callable[[str], str],
    clockFn: Callable[[], float] = time.perf_counter,
    limit: Optional[int] = None,
) -> dict:
    """逐任务执行：answerFn(prompt)→回答→判据给分，产出真实聚合指标。

    - 单任务异常（LLM 或判据）＝该任务失败事实，计 0 分、记 error、计入
      tasks_total，不中断 run（与 multi_agent.BenchRunner 同款故障隔离）；
    - 时延只计取答段（clockFn 注入，测试可断言）；
    - 空任务库如实返回 score=None，不编造 0 分或 1 分。
    """
    if answerFn is None:
        raise ValueError("answer_fn 未提供——无 LLM 通道不得伪造回答")

    selected = list(tasks)
    if limit is not None:
        selected = selected[: max(1, int(limit))]

    perTask: List[dict] = []
    for task in selected:
        started = clockFn()
        error: Optional[str] = None
        answer = ""
        try:
            answer = str(answerFn(task.prompt) or "")
        except Exception as exc:  # noqa: BLE001 - 故障隔离：事实进 error
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("[suite_eval] 任务取答异常 task=%s: %s", task.task_id, exc)
        finally:
            elapsedMs = (clockFn() - started) * 1000.0

        passed, score, details = False, 0.0, {}
        if error is None:
            try:
                passed, score, details = task.check(answer)
            except Exception as exc:  # noqa: BLE001 - 判据故障不掩盖执行事实
                details = {"checker_error": str(exc)}
                logger.warning("[suite_eval] 判据异常 task=%s: %s", task.task_id, exc)

        perTask.append({
            "task_id": task.task_id,
            "passed": bool(passed) and error is None,
            "score": round(float(score), _SCORE_DIGITS),
            "error": error,
            "details": details,
            "latency_ms": round(elapsedMs, 2),
            "answer_snippet": answer[:_ANSWER_SNIPPET_LEN],
        })

    tasksTotal = len(perTask)
    scores = [row["score"] for row in perTask]
    latencies = [row["latency_ms"] for row in perTask]
    return {
        "status": "completed",
        "tasks_total": tasksTotal,
        "tasks_correct": sum(1 for row in perTask if row["passed"]),
        "score": round(sum(scores) / len(scores), _SCORE_DIGITS) if scores else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "per_task": perTask,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 种子任务库（现役四 suite；multimodal-v1 有意不接，见模块 docstring）──

def _reasoningBank() -> List[SuiteTask]:
    numeric = "请用阿拉伯数字回答，只回答数字本身。"
    return [
        SuiteTask("r1", f"小明有 12 个苹果，送给小红 5 个，又买了 8 个。现在小明有几个苹果？{numeric}", exactAnswer("15"), "加减应用题"),
        SuiteTask("r2", "所有的猫都是哺乳动物，小花是一只猫。由此可以推出：小花一定是什么类别的动物？只回答类别名。", exactAnswer("哺乳动物"), "三段论"),
        SuiteTask("r3", f"数列 2, 4, 8, 16 的规律是每项乘 2。下一项是多少？{numeric}", exactAnswer("32"), "数列推理"),
        SuiteTask("r4", f"班里 30 人，其中 18 人喜欢数学，15 人喜欢英语，3 人两科都不喜欢。两科都喜欢的人数是多少？{numeric}", exactAnswer("6"), "容斥原理"),
        SuiteTask("r5", "如果今天是星期三，那么 100 天后是星期几？只回答星期几（如：星期一）。", exactAnswer("星期五"), "模运算"),
        SuiteTask("r6", "甲比乙高，乙比丙高，丙比丁高。四人中谁最矮？只回答名字。", exactAnswer("丁"), "传递推理"),
    ]


def _codingBank() -> List[SuiteTask]:
    def codeTask(taskId: str, code: str, gold: str, note: str) -> SuiteTask:
        prompt = (
            "以下 Python 代码运行后得到的值是什么？只回答该值本身"
            "（数字用阿拉伯数字、字符串只回答内容本身，不要解释、不要引号）。\n\n"
            f"```python\n{code}\n```"
        )
        return SuiteTask(taskId, prompt, exactAnswer(gold), note)

    return [
        codeTask("c1", "def f(x):\n    return x * 2 + 1\n\nf(5)", "11", "算术函数求值"),
        codeTask("c2", 's = "abc"\nresult = ""\nfor ch in s:\n    result = ch + result\n\nresult', "cba", "循环拼接（字符串逆序）"),
        codeTask("c3", "def g(n):\n    if n <= 1:\n        return n\n    return g(n - 1) + g(n - 2)\n\ng(6)", "8", "递归（斐波那契）"),
        codeTask("c4", "nums = [1, 2, 3, 4]\nsum(n for n in nums if n % 2 == 0)", "6", "过滤求和"),
    ]


def _memoryBank() -> List[SuiteTask]:
    return [
        SuiteTask("m1", "请记住：张伟喜欢红色，李娜喜欢蓝色，王强喜欢绿色。问题：李娜喜欢什么颜色？只回答颜色名。", exactAnswer("蓝色"), "单轮上下文记忆"),
        SuiteTask("m2", "购物清单顺序如下：苹果、香蕉、牛奶、面包、鸡蛋。问题：清单中排第三位的物品是什么？只回答物品名。", exactAnswer("牛奶"), "顺序记忆"),
        SuiteTask("m3", "会议安排：周一讨论预算，周三讨论招聘，周五讨论发布计划。问题：周五讨论什么？只回答议题名。", exactAnswer("发布"), "日程记忆"),
        SuiteTask("m4", "访问码是 7F3K。问题：访问码是什么？请原样回答，不要解释。", exactAnswer("7F3K"), "原样复述"),
    ]


def _creativeBank() -> List[SuiteTask]:
    def nightLampCheck(answer: str) -> Tuple[bool, float, dict]:
        """复合约束判据样例：以『夜』开头 + 含『灯』+ 句号结尾。"""
        text = str(answer or "").strip()
        constraints = {
            "starts_with_ye": text.startswith("夜"),
            "contains_deng": "灯" in text,
            "ends_with_period": text.endswith("。"),
        }
        missed = [name for name, ok in constraints.items() if not ok]
        score = round((len(constraints) - len(missed)) / len(constraints), _SCORE_DIGITS)
        return not missed, score, {"unmet_constraints": missed}

    return [
        SuiteTask("cr1", "写一句话，必须同时包含『大海』和『星星』这两个词。", markersPresent(("大海", "星星")), "双词约束"),
        SuiteTask("cr2", "写一句关于『时间』的比喻句：句中必须包含『时间』一词，且必须出现『像』这个词。", markersPresent(("时间", "像")), "比喻结构"),
        SuiteTask("cr3", "给『月亮』写一句拟人句：句中必须有『月亮』，并把月亮称作『她』。", markersPresent(("月亮", "她")), "拟人结构"),
        SuiteTask("cr4", "写一句话，必须以『夜』字开头、包含『灯』这个字、并以句号（。）结尾。", nightLampCheck, "复合约束"),
    ]


def _registerSeedBanks() -> None:
    registerSuiteTasks("reasoning-v1", _reasoningBank())
    registerSuiteTasks("coding-v1", _codingBank())
    registerSuiteTasks("memory-v1", _memoryBank())
    registerSuiteTasks("creative-v1", _creativeBank())


_registerSeedBanks()
