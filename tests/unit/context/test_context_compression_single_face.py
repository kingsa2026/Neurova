# -*- coding: utf-8 -*-
"""B6-10 批次 C：压缩面与去重面各自只允许一份实现（Issue #90 审计 §5 / P2-7）。

## 这批要处置的形态

审计 §5 把三件东西登记为死线，台账里现全为「待处置」：

1. `ContextCompressor`（`neurova/context/compressor.py`）：唯一外部消费点是
   `context_pool.py` 的 `self._compressor = ContextCompressor(max_tokens)`，
   而那个消费方（池的 `compress_context`）本身零消费 → **整条压缩面不通**。
2. `SmartContextCompressor`（`neurova/context_compressor.py`）：第二份压缩实现。
   `injector` 构造时实例化后**从不读取** `self._compressor`（全仓零读取点），
   而它与 injector 的真实签名双不符（`compress_context(messages, memories,
   system_prompt, target_tokens)` 对 injector 的调用形状是 TypeError，被
   `except` 吞掉）→ 这个压缩器在生产从未生效，injector 现走确定性淘汰。
3. `compress_context` / `dedup`（池方法）：零消费的出口，而池的实际通路分别是
   `self._compressor`（同 #1）与 `self._deduplicator.dedup(...)`（`context/dedup.py`
   的**另一接收者**）——按名字数引用会把「有真实现的第二份」误判成「可删」。

## 为什么判据落在这三条上

修复教义第 6 条（单一事实源、不新造平行体系）+ 协作红线「不留断点」：
写出无人读的字段、注册无消费者的模块、只写不读的配置均属断点。压缩面在本仓
**已有一条真通路**（`orchestrator` 的信封+历史确定性淘汰，见
`context/injector.py::_compress_context` 与 `test_envelope.py` 的 20 条判据），
故第二、第三份实现不是"备选"，而是平行体系；去重面的真通路是池自持的
`self._deduplicator`，池上那个同名 `dedup()` 出口是第二份入口。

## 判据只写一份

可达性判据取 `scripts/ci/context_deadline_ledger.py` 的 `classify()`（单一事实源），
本守卫不另写扫描逻辑；台账口径取同模块的 `readLedger()`。本守卫只做
「断言 + 反向控制」，即：处置写「已删除 / 收口第二份」而符号还在，必须报红。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import context_deadline_ledger as ledger  # noqa: E402

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/context/test_context_compression_single_face.py"

PRODUCTION_ROOT = PROJECT_ROOT / "neurova"

#: 本批给出终局的符号 → (期望处置, 期望判据类)。
#:
#: **两类判据必须分开写，不能混**：前两条的符号在生产侧**已经不存在**，裸名判据
#: 直接给 `absent`，这就是拥有者级的终局证明。后两条（`compress_context` /
#: `dedup`）是**裸名撞名**的形态——同一个名字在别的接收者上仍然活着
#: （`api/endpoints/context.py` 的端点、`context_facade` 的门面方法、
#: `context/dedup.py` 的 `DriftSafeDeduplicator.dedup`），故裸名判据只能读到
#: 那些**残留站点**，给不出 `absent`。这正是 B6-1 模块 docstring 预先点名的
#: 「按名字计数不可判别」形态，故这两条改用**拥有者级机器判据**
#: （`test_pool_keeps_only_the_deduplicator_face`：直接对 `ContextPool`
#: 断言 `hasattr` 为假），而不是硬把台账改成 `absent` 去迎合一条读不到的判据——
#: 那等于把判据降级成自述（本仓 B6-1 明令禁止）。
DISPOSED_EXPECTATIONS = {
    # 第二份压缩实现：真通路是 injector 的信封+历史确定性淘汰。
    "SmartContextCompressor": (ledger.DISPOSAL_RETIRED, ledger.JUDGE_ABSENT),
    # 同契约第二份压缩实现：唯一消费点（池的 compress_context）本身零消费。
    "ContextCompressor": (ledger.DISPOSAL_RETIRED, ledger.JUDGE_ABSENT),
    # 拥有者级终局由 OUTLET_SYMBOLS 一节断言（池上不得再有该出口）。
    "compress_context": (ledger.DISPOSAL_RETIRED, ledger.JUDGE_NO_CONSUMER),
    "dedup": (ledger.DISPOSAL_RETIRED, ledger.JUDGE_CONSUMED),
}

#: 裸名撞名的两条：终局只能由**拥有者级判据**证明（池上该出口必须消失）。
OUTLET_SYMBOLS = ("dedup", "compress_context")

#: 反向控制：这些符号仍在生产侧（判据非 absent），把它们标成「已删除」必须被抓到。
STILL_PRESENT_CONTROLS = ("draw", "archiveBatch")

#: 退场后不得再被任何生产模块导入的模块（含其全部符号）。
RETIRED_MODULES = (
    "neurova.context.compressor",
    "neurova.context_compressor",
)


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestCompressionFaceHasSingleImplementation:
    """压缩面只允许一份实现：退场面必须真的从生产侧消失。"""

    def test_retired_compressor_modules_are_absent_from_production(self):
        """退场的两个压缩模块不得再被 `neurova/` 下任何生产模块导入。"""
        offenders = []
        for path in PRODUCTION_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for module in RETIRED_MODULES:
                if module in text:
                    rel = path.relative_to(PROJECT_ROOT).as_posix()
                    offenders.append(f"{rel} 仍引用 {module}")
        assert not offenders, (
            "压缩面已收口到单一通路（orchestrator 的信封+历史确定性淘汰），"
            "退场模块不得再被生产侧引用：\n  " + "\n  ".join(sorted(offenders))
        )

    def test_retired_modules_do_not_import(self):
        """退场模块本身必须真的不存在（导入即 ModuleNotFoundError）。"""
        for module in RETIRED_MODULES:
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module)

    def test_disposed_symbols_match_declared_expectation(self):
        """处置与机器判据必须咬合：写「已删除」而符号还在 = 处置是口号。"""
        facts = _facts()
        problems = []
        for symbol, (disposal, expected_judge) in DISPOSED_EXPECTATIONS.items():
            entry = ledger.readLedger().get(symbol)
            if entry is None:
                problems.append(f"{symbol}: 台账缺该条")
                continue
            fact = facts.get(symbol)
            if fact is None:
                problems.append(f"{symbol}: 不在登记符号表里")
                continue
            if entry["disposal"] != disposal:
                problems.append(f"{symbol}: 台账处置为 {entry['disposal']}，期望 {disposal}")
            if fact["judge"] != expected_judge:
                problems.append(
                    f"{symbol}: 判据类为 {fact['judge']}（{fact['classify']['rule']}），"
                    f"期望 {expected_judge}"
                )
        assert not problems, (
            "压缩面/去重面处置与机器判据不咬合：\n  " + "\n  ".join(problems)
        )

    def test_pool_keeps_only_the_deduplicator_face(self):
        """池侧只留**一个接收者**的去重面，且没有压缩出口。

        这是本批对那两条裸名撞名符号的**拥有者级终局判据**：裸名判据
        （`classify()`）读到的是别的接收者的同名符号，只有这条能表达
        「ContextPool 这个拥有者的这个面已消失」。
        """
        from neurova.context_pool import ContextPool

        assert not hasattr(ContextPool, "dedup"), (
            "ContextPool.dedup 又回来了 —— 池的真实去重发生在 add_context"
            "（self._deduplicator + _by_hash），池上再挂一个同名出口就是第二份入口。"
        )
        assert not hasattr(ContextPool, "compress_context"), (
            "ContextPool.compress_context 又回来了 —— 池没有压缩通路"
            "（真通路在 orchestrator 的信封+历史确定性淘汰），该出口是空转。"
        )

    def test_bare_name_judge_cannot_decide_these_rows(self):
        """撞名判据不得给出 `absent`：若它给得出，说明残留站点被误删了。

        反向控制。`dedup` / `compress_context` 在别的接收者上仍有定义与消费点，
        裸名判据必须读到它们（`JUDGE_CONSUMED` / `JUDGE_NO_CONSUMER`）。
        若某天它们变成 `absent`，不是「清理成功」，而是**撞名判据被改坏**
        （例如预筛丢掉了文件），届时本节与台账都会假绿。
        """
        facts = _facts()
        for symbol in OUTLET_SYMBOLS:
            assert facts[symbol]["judge"] != ledger.JUDGE_ABSENT, (
                f"{symbol} 被判为 absent —— 裸名判据已经读不到任何残留站点，"
                "说明判据被改坏（预筛/取数失效），而非清理成功。"
            )

    def test_disposal_axis_is_not_vacuous(self):
        """反向控制：规则不得恒真——仍在仓的符号被判 absent 即报红。"""
        facts = _facts()
        offenders = [
            symbol for symbol in STILL_PRESENT_CONTROLS
            if facts[symbol]["judge"] == ledger.JUDGE_ABSENT
        ]
        assert not offenders, (
            f"反向控制项 {offenders} 被判为 absent —— 判据整体失效，"
            "本守卫的处置断言会在空转中通过。"
        )


class TestRetiredCompanionsFollowTheSingleFace:
    """压缩面收口后，只服务于第二份实现的东西一并退场（不留只写不读的伴生物）。"""

    def test_compressor_singleton_factory_is_gone(self):
        """`get_context_compressor` / `reset_context_compressor` 是同一份实现的
        单例入口，随模块一并退场；不得留下只写不读的工厂。"""
        for name in ("get_context_compressor", "reset_context_compressor"):
            fact = _facts().get(name)
            if fact is None:
                # 未登记在死线台账里（本批只登记审计 §5 点名的符号），
                # 这里直接按生产侧事实断言：符号不得存在。
                assert not _symbolExistsInProduction(name), (
                    f"{name} 仍在生产侧 —— 它只服务已退场的第二份压缩实现。"
                )


def _symbolExistsInProduction(symbol: str) -> bool:
    """按 AST 事实判断符号是否仍在生产根（复用判据模块的唯一取数入口）。"""
    return bool(ledger.referenceSites(symbol))


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        raw = PROTECTED.read_text(encoding="utf-8")
        listed = {
            line.split("#", 1)[0].strip()
            for line in raw.splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
            "（B5 收口时正是这个形态：文件在仓、单跑全绿、清单里没有）。"
        )
