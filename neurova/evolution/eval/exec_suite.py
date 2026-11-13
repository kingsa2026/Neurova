"""可执行测试判据层（HN2/HC2，2026-11-13）。

来历：HarnessPro 对照（docs/08-research/harnesspro_vs_neurova_cost_aware_
harness_rsi_comparison_2026-11-13.md）断点 HN2——合成评测集
（`eval/synthetic.py`）产出的是 rubric 文本，判分靠 LLM judge；judge 的
系统性漏判（HarnessPro 实测 41.7% 召回）会直接进采纳决策。

本模块补一层**确定性可执行判据**（借鉴 HarnessPro 的 Test Synthesizer
形态，独立实现，不搬其文本）：

1. `TestSynthesizer`：LLM 从**技能公共契约**（当前基线正文）＋若干参考
   任务生成带断言的评测用例；只收七种确定性断言 op，非法 op/空任务剔除，
   按配置限量；生成失败 ⇒ 空套件（不可用），绝不臆造。
2. 套件**冻结**：`suite_hash` 对用例集稳定（sha256），基线与候选跑的是
   同一套件——防「为候选改测试」。
3. `run_exec_suite`：对已捕获的输出逐案执行断言；输出缺失的用例记
   unevidenced（不是通过）；pass_rate 分母 = 已评测数。
4. runner 侧非回归门（判定 2.15）：候选通过率 < 基线通过率 ⇒
   exec_suite_regression 拒绝。judge 照常工作——两层判据各管各的。

反 gaming 边界：生成器只看基线契约与参考任务面（不读候选正文）；断言
引擎是确定性字符串/正则判定，**不执行生成代码**（无任意代码执行面）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig

logger = get_logger(__name__)

#: 断言 op 的合法域与说明（单一出处；超出即剔除，不静默放行）
ASSERTION_OPS: Dict[str, str] = {
    "non_empty": "输出非空（去空白后长度 > 0）",
    "contains": "输出包含 value（大小写不敏感）",
    "not_contains": "输出不包含 value（大小写不敏感）",
    "equals": "输出去空白后与 value 完全相等",
    "regex": "输出匹配 value 正则（re.search）",
    "length_le": "输出长度 ≤ int(value)",
    "length_ge": "输出长度 ≥ int(value)",
    # R2 结构化断言：面向 JSON 形态的输出
    "json_path": "输出按 JSON 解析后，value（点路径，列表用数字下标）可解析；"
                 "spec 带 expected 时还须与该值相等",
    "json_keys": "输出按 JSON 对象解析后，value（逗号分隔键名）全部存在",
    # R2 差分（metamorphic）断言：相对基线输出的判定
    "differs_from_baseline": "输出与同案基线输出不同",
    "same_as_baseline": "输出与同案基线输出相同",
}

#: 差分 op（需要同案基线输出才能判定；缺席 ⇒ 该案 unevidenced）
_DIFFERENTIAL_OPS = frozenset({"differs_from_baseline", "same_as_baseline"})

#: R7 覆盖面：哪些工件类型合成可执行套件（单一出处，service 装配读它）
EXEC_SUITE_ARTIFACT_TYPES = ("skill", "template", "tool_description")

_GEN_SYSTEM = (
    "你是一名评测工程师。给定一段 agent 技能/提示词文本（公共契约）与若干任务示例，"
    "生成**可确定性判定**的评测用例。每条用例包含：\n"
    '- task_input：用户会真实提出的任务\n'
    '- assertions：对任务输出的可执行断言数组，每条形如 {"op": "...", "value": "..."}，'
    "op 只能取 " + "/".join(sorted(ASSERTION_OPS)) + " 之一\n"
    "只对「仅凭公共契约即可判定对错」的行为写断言；需要人工判断的内容不要写；"
    "不要把示例里的答案原样抄进断言。\n"
    "只输出 JSON 数组，不要其它文字。"
)


def _jsonPathResolve(payload: Any, path: str) -> tuple:
    """点路径取值（列表用数字下标）→ (found, value)。"""
    current = payload
    for part in [p for p in str(path or "").split(".") if p]:
        if isinstance(current, dict):
            if part not in current:
                return (False, None)
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                return (False, None)
            if idx < 0 or idx >= len(current):
                return (False, None)
            current = current[idx]
        else:
            return (False, None)
    return (True, current)


def evaluateAssertions(output: str, assertions: List[Dict[str, Any]],
                       baseline_output: Optional[str] = None) -> List[str]:
    """对单条输出执行一组断言，返回**失败原因**列表（空 = 全过）。

    确定性字符串/正则/JSON 判定，不执行任何生成代码；未知 op 记失败并点名
    （不崩溃、不静默当作通过）。差分 op 需要同案基线输出——缺席时记失败
    （run_exec_suite 在更上层把这种案整体标 unevidenced，不进通过率分母）。
    """
    text = str(output if output is not None else "")
    failures: List[str] = []
    for spec in assertions or []:
        op = str((spec or {}).get("op", "")).strip().lower()
        value = (spec or {}).get("value")
        expected = (spec or {}).get("expected")
        if op == "non_empty":
            if not text.strip():
                failures.append("non_empty: 输出为空")
        elif op == "contains":
            if str(value or "").lower() not in text.lower():
                failures.append(f"contains: 未包含 {value!r}")
        elif op == "not_contains":
            if str(value or "").lower() in text.lower():
                failures.append(f"not_contains: 不应包含 {value!r}")
        elif op == "equals":
            if text.strip() != str(value or ""):
                failures.append(f"equals: 期望精确匹配 {value!r}")
        elif op == "regex":
            try:
                if not re.search(str(value or ""), text):
                    failures.append(f"regex: 未匹配 {value!r}")
            except re.error as e:
                failures.append(f"regex: 正则非法 {value!r} ({e})")
        elif op == "length_le":
            try:
                if len(text) > int(value):
                    failures.append(f"length_le: 长度 {len(text)} > {value}")
            except (TypeError, ValueError):
                failures.append(f"length_le: 阈值非法 {value!r}")
        elif op == "length_ge":
            try:
                if len(text) < int(value):
                    failures.append(f"length_ge: 长度 {len(text)} < {value}")
            except (TypeError, ValueError):
                failures.append(f"length_ge: 阈值非法 {value!r}")
        elif op == "json_path":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                failures.append("json_path: 输出不是合法 JSON")
                continue
            found, resolved = _jsonPathResolve(payload, value)
            if not found:
                failures.append(f"json_path: 路径 {value!r} 不可解析")
            elif "expected" in (spec or {}):
                if resolved != expected:
                    failures.append(
                        f"json_path: {value!r} 期望 {expected!r} 实得 {resolved!r}")
        elif op == "json_keys":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                failures.append("json_keys: 输出不是合法 JSON")
                continue
            if not isinstance(payload, dict):
                failures.append("json_keys: 输出不是 JSON 对象")
                continue
            wanted = [k.strip() for k in str(value or "").split(",") if k.strip()]
            missing = [k for k in wanted if k not in payload]
            if missing:
                failures.append(f"json_keys: 缺键 {missing}")
        elif op in _DIFFERENTIAL_OPS:
            if baseline_output is None:
                failures.append(f"{op}: 同案基线输出缺席，无法判定")
            else:
                same = text == str(baseline_output)
                if op == "differs_from_baseline" and same:
                    failures.append("differs_from_baseline: 与基线输出相同")
                if op == "same_as_baseline" and not same:
                    failures.append("same_as_baseline: 与基线输出不同")
        else:
            failures.append(f"未知断言 op: {op!r}")
    return failures


@dataclass(frozen=True)
class ExecCase:
    """一条可执行评测用例。"""

    case_id: str
    task_input: str
    assertions: tuple  # tuple[dict, ...]
    description: str = ""
    kind: str = "behavioral"


@dataclass(frozen=True)
class ExecutableTestSuite:
    """冻结的可执行测试套件（基线与候选共跑同一份）。"""

    skill_id: str
    cases: tuple  # tuple[ExecCase, ...]
    suite_hash: str = ""
    generated_at: str = ""
    source: str = ""

    def isUsable(self) -> bool:
        return bool(self.cases)

    def taskInputs(self) -> List[str]:
        return [c.task_input for c in self.cases]


def _canonicalHash(cases: tuple) -> str:
    payload = [
        {
            "case_id": c.case_id,
            "task_input": c.task_input,
            "assertions": [dict(a) for a in c.assertions],
            "kind": c.kind,
        }
        for c in cases
    ]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _parseCases(raw_cases: Any, *, cap: int) -> tuple:
    """原始 LLM 输出 → 合法 ExecCase 元组：剔非法 op/空任务，限量 cap。"""
    cases: List[ExecCase] = []
    if not isinstance(raw_cases, list):
        return tuple()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict) or len(cases) >= cap:
            continue
        task_input = str(raw.get("task_input", "")).strip()
        raw_assertions = raw.get("assertions")
        if not task_input or not isinstance(raw_assertions, list):
            continue
        assertions = []
        for spec in raw_assertions:
            if not isinstance(spec, dict):
                continue
            op = str(spec.get("op", "")).strip().lower()
            if op not in ASSERTION_OPS:
                continue
            entry = {"op": op, "value": spec.get("value", "")}
            if "expected" in spec:  # json_path 等结构化断言的期望值
                entry["expected"] = spec.get("expected")
            assertions.append(entry)
        if not assertions:
            continue
        cases.append(
            ExecCase(
                case_id=f"exec_{index:04d}",
                task_input=task_input,
                assertions=tuple(assertions),
                description=str(raw.get("description", "")).strip()[:200],
                kind=str(raw.get("kind", "behavioral")).strip() or "behavioral",
            ))
    return tuple(cases)


class TestSynthesizer:
    """LLM 合成可执行测试套件；llm_call 可注入以便离线测试。"""

    def __init__(self, config: EvolutionConfig, llm_call: Optional[Callable[..., Any]] = None):
        self.config = config
        self._llm_call = llm_call

    async def _call_llm(self, messages: list[dict[str, str]], model: str) -> Dict[str, Any]:
        if self._llm_call is not None:
            return await self._llm_call(messages, model)
        try:
            from neurova.llm.multi_model_client import get_multi_model_client

            result = await get_multi_model_client().chat(messages, model=model or None)
        except Exception as e:  # noqa: BLE001
            logger.debug("可执行测试合成 LLM 调用失败: %s", e)
            return {"success": False, "error": str(e)}
        # 形态归一：部分 provider/mock 路径的 result["response"] 是 LLMResponse
        # 对象而非字符串——取其 content，保证下游解析面拿到字符串。
        if result.get("success") and not isinstance(result.get("response"), str):
            response = result.get("response")
            result["response"] = str(getattr(response, "content", "") or "")
        return result

    async def generate(self, *, skill_text: str, reference_tasks: Optional[List[str]] = None,
                       artifact_type: str = "skill") -> ExecutableTestSuite:
        """从技能契约生成套件；任何失败都回**不可用空套件**（不臆造）。

        真模型实证（2026-11-13）：链路可通（真实 provider 合成出可用套件），
        但存在输出不可解析的运行间波动——故对「调用成功但解析失败」多做
        一次重试（有界 2 次），仍失败即诚实回退。
        """
        size = max(1, int(self.config.exec_suite_size))
        refs = [str(t)[:200] for t in (reference_tasks or []) if str(t).strip()][:6]
        user = (
            f"【{artifact_type} 公共契约】\n{str(skill_text or '')[:12000]}\n\n"
            f"【参考任务示例（仅作任务面风格参照，不是答案）】\n"
            + ("\n".join(f"- {t}" for t in refs) if refs else "（无）")
            + f"\n\n请生成 {size} 条可执行评测用例。"
        )
        messages = [{"role": "system", "content": _GEN_SYSTEM},
                    {"role": "user", "content": user}]
        last_source = "llm_failed"
        for _attempt in range(2):
            try:
                result = await self._call_llm(messages, self.config.judge_model)
            except Exception as e:  # noqa: BLE001 - 合成器故障不阻断进化，诚实回退
                logger.debug("可执行测试合成失败: %s", e)
                return ExecutableTestSuite(skill_id="", cases=tuple(), source="error")
            if not result.get("success"):
                return ExecutableTestSuite(skill_id="", cases=tuple(),
                                           source=last_source)
            raw = _extractJsonArray(str(result.get("response") or ""))
            if raw:
                return self._build(skill_id="", raw_cases=raw, source="synthetic",
                                   cap=size)
            last_source = "unparseable"  # 调用成功但输出不可解析 → 重试一次
        return ExecutableTestSuite(skill_id="", cases=tuple(), source=last_source)

    @staticmethod
    def _build(*, skill_id: str, raw_cases: Any, source: str,
               cap: Optional[int] = None) -> ExecutableTestSuite:
        """原始用例 → 冻结套件的唯一构造点（解析/校验/限量/哈希）。"""
        limit = cap if cap is not None else 64
        cases = _parseCases(raw_cases, cap=limit)
        return ExecutableTestSuite(
            skill_id=str(skill_id or ""),
            cases=cases,
            suite_hash=_canonicalHash(cases) if cases else "",
            source=source,
        )


def _extractJsonArray(text: str) -> Optional[list]:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def run_exec_suite(suite: ExecutableTestSuite,
                   outputs: Dict[str, str],
                   baseline_outputs: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """对已捕获的输出执行套件断言（确定性，无 LLM、无代码执行）。

    - 输出缺失的用例记 unevidenced（**不是通过**）；
    - 差分断言（differs_from_baseline/same_as_baseline）需要同案基线输出——
      基线缺席时该案 unevidenced（不进分母也不冒充通过）；
    - pass_rate 分母 = 已评测数；
    - state 三态：measured（全部跑到）/ partially_measured（部分跑到——
      分母不一致，消费方不得拿它做两侧对比判据）/ unevidenced（一条都没跑到）。
    """
    if not suite.isUsable():
        return {"state": "unavailable", "total": 0, "evaluated": 0,
                "passed": 0, "pass_rate": None, "cases": []}
    rows: List[Dict[str, Any]] = []
    evaluated = passed = 0
    for case in suite.cases:
        if case.task_input not in outputs:
            rows.append({"case_id": case.case_id, "task_input": case.task_input[:80],
                         "state": "unevidenced", "passed": None, "failures": []})
            continue
        needsBaseline = any(a.get("op") in _DIFFERENTIAL_OPS for a in case.assertions)
        baseOut = None
        if needsBaseline:
            baseOut = (baseline_outputs or {}).get(case.task_input)
            if baseOut is None:
                rows.append({"case_id": case.case_id, "task_input": case.task_input[:80],
                             "state": "unevidenced", "passed": None,
                             "failures": ["差分断言缺同案基线输出"]})
                continue
        failures = evaluateAssertions(outputs[case.task_input], list(case.assertions),
                                      baseline_output=baseOut)
        case_passed = not failures
        evaluated += 1
        passed += int(case_passed)
        rows.append({"case_id": case.case_id, "task_input": case.task_input[:80],
                     "state": "evaluated", "passed": case_passed,
                     "failures": [f[:160] for f in failures]})
    if evaluated == 0:
        overall = "unevidenced"
    elif evaluated < len(suite.cases):
        overall = "partially_measured"
    else:
        overall = "measured"
    return {
        "state": overall,
        "suite_hash": suite.suite_hash,
        "total": len(suite.cases),
        "evaluated": evaluated,
        "passed": passed,
        "pass_rate": round(passed / evaluated, 4) if evaluated else None,
        "cases": rows,
    }
