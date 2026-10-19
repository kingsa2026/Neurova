# -*- coding: utf-8 -*-
"""mcp 声明的**下界**必须与代码真正取用的 SDK 世代同代。

钉的是什么：`requirements*.txt` 里 mcp 的范围可以写得比实装宽——允许装 1.x，而生产
在模块级 `import mcp_types`（只有 2.x 才提供的顶层包）。此时"声明存在"这一族守卫全绿
（它们管的是四处声明齐不齐），按这份声明装出来的环境却是坏的：客户端侧
`_SDK_AVAILABLE=False` 让全部 MCP 连接失败，服务端面在装载表里因 `ModuleNotFoundError`
被整张跳过。这是 Issue #62 那一族"CI 全绿、线上挂"的下界版本。

为什么单开一档而不是并进 `TestMcpSdkDeclaredForRuntime`：那一类钉的是**四处声明在不在**
（两份 txt + 两份 lock），本档钉的是**范围本身对不对**——两条不变量不同，且互不重复；
交叉引用写在两份 requirements 的注释里。
"""

import ast
import io
import re
from pathlib import Path

from tests import ast_scan

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MANIFESTS = ("requirements.txt", "requirements-ci.txt")
LOCKS = ("requirements-full.lock", "requirements-ci.lock")

# `mcp-types` 作为独立顶层包**自 mcp 2.0.0 起才是 mcp 的依赖**（PyPI 元数据实证：
# 1.2.0／1.9.4 的 requires_dist 里没有它，2.0.0／2.2.0 有）。生产 import 它即意味着
# 声明的下界不许低于 2.0.0。
SDK_TWO_ERA_ROOT = "mcp_types"
MIN_FLOOR_FOR_SDK2 = (2, 0, 0)

_CONSTRAINT = re.compile(r"(?m)^\s*mcp\s*([><=!~]+[0-9][0-9.a-z\-]*(?:\s*,\s*[><=!~]+\s*[0-9][0-9.a-z\-]*)*)")


def _declaredConstraints(rel):
    text = io.open(PROJECT_ROOT / rel, encoding="utf-8").read()
    return _CONSTRAINT.findall(text)


def _floorOf(constraint):
    """取下界：`>=x` / `==x` 之类的最低版本；无上界单条（如 `mcp`）返回 None。"""
    bounds = []
    for part in constraint.split(","):
        match = re.match(r"\s*(>=|==|>)\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", part)
        if match:
            bounds.append((int(match.group(2)), int(match.group(3) or 0), int(match.group(4) or 0)))
    return min(bounds) if bounds else None


def _sdkTwoImportsInProduction():
    """生产代码里 `import mcp_types[...]` 的落点（按 AST 判，注释与文档不算）。

    取数走共享入口：`sourceRefsUnder(hints=...)` 把解析量从"代码总量"收成"命中面"，
    再用 `transientTree` 一次性解析（不留常驻语法树）。
    """
    hits = []
    for ref in ast_scan.sourceRefsUnder(PROJECT_ROOT / "neurova", hints=(SDK_TWO_ERA_ROOT,)):
        for node in ast.walk(ast_scan.transientTree(ref.path)):
            roots = set()
            if isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            if SDK_TWO_ERA_ROOT in roots:
                hits.append(f"{ref.path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}")
    return sorted(set(hits))


class TestMcpSdkFloorMatchesImportedEra:
    def test_production_uses_sdk_two_only_names(self):
        """正控：前提成立时才谈下界。生产不再 import `mcp_types` 的话，本族判据需随之改判。"""
        assert _sdkTwoImportsInProduction(), (
            "生产已不再 import mcp_types——本档三条判据的前提没了。"
            "别把它改成恒真：要么删掉本档，要么换成当下真正取用的世代。"
        )

    def test_faceReadingIsNotVacuous(self):
        """面自证：本档三条判据都建立在"扫过 `neurova/`"这个前提上，根被改窄时必须先在这里红。

        取数走共享枚举入口 `filesUnder`（只数文件、不解析）——本档的解析量已经在
        `sourceRefsUnder(hints=...)` 的命中面上付过一次，这里不该再付一趟（预算门禁同一条理由）。
        阈值取现读的一半上下（本批量得 1018 个 `.py`），只保证"根写错/被改窄"这条坏法先响。
        """
        scanned = len(ast_scan.filesUnder(PROJECT_ROOT / "neurova", ".py"))
        assert scanned > 700, f"扫描根 `neurova/` 现读 {scanned} 个 .py，低于下限——根写错了本族判据就不说话"

    def test_floor_covers_the_names_production_imports(self):
        imports = _sdkTwoImportsInProduction()
        for rel in MANIFESTS:
            constraints = _declaredConstraints(rel)
            assert constraints, f"{rel} 未声明 mcp 范围"
            floors = [f for f in (_floorOf(c) for c in constraints) if f]
            assert floors, f"{rel} 的 mcp 声明没有下界（只写上界等于允许任意老版本）"
            assert min(floors) >= MIN_FLOOR_FOR_SDK2, (
                f"{rel} 声明 mcp{constraints[0]}，而生产在模块级 import 只有 2.x 才有的 "
                f"{SDK_TWO_ERA_ROOT}（{', '.join(imports[:3])}）。按这份下界装出 1.x 时："
                "客户端侧 _SDK_AVAILABLE=False 让全部 MCP 连接失败，服务端面在装载表里因 "
                "ModuleNotFoundError 被整张跳过——声明允许的版本根本跑不起来。"
            )

    def test_both_manifests_declare_the_same_constraint(self):
        """两份 txt 的 mcp 范围必须逐字同值。

        「四处声明齐备」那条守卫只要求两份都在，两份各写一个不同下界同样能过它——
        那就是第二个事实源：薄环境装出来的与生产不是同一件事。
        """
        per = {rel: _declaredConstraints(rel) for rel in MANIFESTS}
        for rel, constraints in per.items():
            assert len(constraints) == 1, f"{rel} 里 mcp 声明出现 {len(constraints)} 次，范围应只有一条"
        first, second = (per[rel][0] for rel in MANIFESTS)
        assert first == second, (
            f"两份清单给了同一个依赖两个范围：requirements.txt={first!r} ↔ requirements-ci.txt={second!r}"
        )

    @pytest.mark.parametrize("lock", LOCKS)
    def test_lock_pin_satisfies_declared_floor(self, lock):
        """控制格（设计成现在就绿）：锁里的 pin 必须落在声明的下界之上。

        钉的是「改下界而不改锁」这条路——把 floor 抬到 2.x 而 pin 仍是 1.x，
        前面几格全绿，实际装出来的仍是跑不起来的那版。
        """
        text = io.open(PROJECT_ROOT / lock, encoding="utf-8").read()
        pin = re.search(r"(?m)^mcp==([0-9.]+)", text)
        assert pin, f"{lock} 缺 mcp pin"
        version = tuple(int(x) for x in pin.group(1).split(".")[:3])
        for rel in MANIFESTS:
            floor = _floorOf(_declaredConstraints(rel)[0])
            assert version >= floor, f"{lock} pin mcp=={pin.group(1)} 不满足 {rel} 的下界 {floor}"
