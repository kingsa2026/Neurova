"""架构守卫：gate_chain 是纯编排件（P1-1，计划书 §3.4）。

门禁链编排器只做**判据结论的编排与聚合**——判据的产出由调用方注入
（P1-3 才接真实数据源）。因此它必须保持零 IO、不建应用、不跑测试、
不 import 影子验证执行器（shadow_verify 为并行在途件，编排器只消费
其结论形态 GateVerdict，不依赖其实现）。依赖面越界即红。
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_CHAIN_PATH = (
    REPO_ROOT / "neurova" / "evolution" / "rsi" / "gate_chain.py"
)

#: 纯编排件的全部合法依赖：类型标注 + 三态判据契约。出现第四个即越界。
ALLOWED_IMPORTS = {
    "__future__",
    "typing",
    "neurova.evolution.rsi.gate_verdict",
}


def _gateChainSource() -> str:
    assert GATE_CHAIN_PATH.exists(), f"门禁链编排器缺失: {GATE_CHAIN_PATH}"
    return GATE_CHAIN_PATH.read_text(encoding="utf-8")


def _importedModules(source: str) -> set:
    tree = ast.parse(source)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def test_gateChainImportsStayWithinPureOrchestrationBoundary():
    """依赖面钉死：不 import shadow_verify、不建应用、不碰任何 IO 模块。"""
    modules = _importedModules(_gateChainSource())
    offenders = {m for m in modules if m not in ALLOWED_IMPORTS}
    assert offenders == set(), (
        f"gate_chain 出现纯编排边界之外的依赖 {sorted(offenders)}——"
        "判据产出属调用方（P1-3 接线），编排器自身不得接数据源/建应用/做 IO"
    )
    shadow = [m for m in modules if "shadow_verify" in m]
    assert shadow == [], f"gate_chain 不得依赖 shadow_verify: {shadow}"


def test_gateChainPerformsNoDirectIo():
    """零 IO：不开文件、不起子进程、不发请求（判定只消费注入的 GateVerdict）。"""
    tree = ast.parse(_gateChainSource())
    forbiddenCalls = {"open", "exec", "eval", "subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            assert name not in forbiddenCalls, (
                f"gate_chain 出现 IO/执行类调用 {name!r}（行 {node.lineno}）——"
                "编排器必须保持纯函数式编排"
            )


def test_gateChainDoesNotReferenceShadowVerifyEvenInText():
    """文本级防线：并行在途件 shadow_verify 不出现在编排器源码任何位置。"""
    assert "shadow_verify" not in _gateChainSource()
