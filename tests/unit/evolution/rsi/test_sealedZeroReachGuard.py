# -*- coding: utf-8 -*-
"""D3 密封档零引用反证判据（survey §10.2）——AST 常驻守卫。

增益/候选生成链的**可达读集不含密封档**：`RSIEvalHarness.run`（gain 唯一来源）
必须经 splitSealedCases 取决策档、不得直读含密封档的 `EVAL_CASES` 全表；
`CandidatePolicy.stepCandidates/heuristicScore/quickEvalScore` 与
`generate_optimizations` 函数体零密封词。已登记的密封消费点（例外清单）：
细筛安全否决（G1 拍板，fail-closed 防线不产排名信号）与 run_sealed 读数面
（D1 验收证据）——守卫钉的是"证据生产链"，不是安全否决链。
变异格：人为让守卫域函数读密封键，扫描器当场红。
"""

import ast
from pathlib import Path

from tests.ast_scan import parseSource

PROJECT_ROOT = Path(__file__).resolve().parents[4]
EVAL_HARNESS_PY = PROJECT_ROOT / "neurova" / "evolution" / "rsi" / "eval_harness.py"
CANDIDATE_POLICY_PY = PROJECT_ROOT / "neurova" / "evolution" / "rsi" / "candidate_policy.py"
ORCHESTRATOR_PY = PROJECT_ROOT / "neurova" / "evolution" / "rsi" / "orchestrator.py"

#: 密封档的词值单源（读侧引用形态：常量名/方法名/调用名）。
SEALED_WORDS = {"SEALED_CASE_IDS", "run_sealed", "splitSealedCases", "sealed_evidence"}


def _functionBodies(path: Path, names: set) -> dict:
    """取指定模块源里目标函数的 body AST（按函数名，含方法）。"""
    tree = parseSource(path.read_text(encoding="utf-8"), filename=str(path))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            found.setdefault(node.name, []).append(node)
    return found


def _sealedWordsIn(nodes) -> list:
    """函数体内对密封词值的引用点（Name/Attribute/Str 形态）。"""
    hits = []
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in SEALED_WORDS:
                hits.append((node.name, sub.id, sub.lineno))
            elif isinstance(sub, ast.Attribute) and sub.attr in SEALED_WORDS:
                hits.append((node.name, sub.attr, sub.lineno))
    return hits


def test_gain_source_never_reads_the_full_case_table():
    """增益来源（RSIEvalHarness.run）不得直读 EVAL_CASES 全表——必须经密封切分。"""
    found = _functionBodies(EVAL_HARNESS_PY, {"run"})
    assert "run" in found, "RSIEvalHarness.run 缺失"
    for node in found["run"]:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "EVAL_CASES":
                raise AssertionError(
                    f"增益来源直读 EVAL_CASES 全表（含密封档）line {sub.lineno}——"
                    "gain 分母被密封档污染（D1 切分纪律失守）")


def test_candidate_generation_chain_is_sealed_word_free():
    """候选生成链（步进/启发式/快评/generate_optimizations）函数体零密封词。"""
    policy = _functionBodies(CANDIDATE_POLICY_PY,
                             {"stepCandidates", "heuristicScore", "quickEvalScore"})
    orch = _functionBodies(ORCHESTRATOR_PY, {"generate_optimizations"})
    for nodes in (policy.values(), orch.values()):
        for node_list in nodes:
            hits = _sealedWordsIn(node_list)
            assert not hits, f"候选生成链引用密封档：{hits}"


def test_mutation_scanner_flags_a_sealed_reading_candidate_fn():
    """变异格：人为让候选函数读密封键 → 扫描器当场红（守卫不是摆设）。"""
    violating = (
        "def stepCandidates(self, system_name, param_name, current_value, signals):\n"
        "    from neurova.evolution.rsi.eval_harness import SEALED_CASE_IDS\n"
        "    leaked = SEALED_CASE_IDS\n"
        "    return []\n"
    )
    tree = parseSource(violating, filename="<mutation>")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "stepCandidates":
            hits = _sealedWordsIn([node])
    assert hits, "变异体没被扫描器抓到——守卫空转"
    assert hits[0][1] == "SEALED_CASE_IDS"


def test_documented_sealed_consumers_are_the_registered_ones_only():
    """例外清单咬合：密封消费点恰为已登记两处（细筛安全否决＋run_sealed 读数面）。

    新增消费点必须先进例外清单（本格的集合）再落码——否则守卫当场红。
    """
    policy = _functionBodies(CANDIDATE_POLICY_PY, {"validationResult"})
    orch = _functionBodies(ORCHESTRATOR_PY, {"_sealedCandidateValidation", "_probeOutcome"})
    harness = _functionBodies(EVAL_HARNESS_PY, {"run_sealed"})
    consumers = []
    for nodes in (*policy.values(), *orch.values(), *harness.values()):
        consumers.extend(node.name for node in nodes)
    assert set(consumers) == {"validationResult", "_sealedCandidateValidation",
                              "_probeOutcome", "run_sealed"}, (
        f"密封消费点集合漂移：{sorted(consumers)}——新增消费点先进例外清单")
