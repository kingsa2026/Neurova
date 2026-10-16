# -*- coding: utf-8 -*-
"""DoomLoopGate 的三个在用阈值必须受配置键管辖（ModularRSI 对照 §4 M-A 第①步；台账记有本格）。

## 根因（同一装配点上的管辖口径不一致）

门控装配的唯一实现点是 `agent/loops/base.py:_buildGateRunner()`。它把另外三把门都接到了
配置单源 `security/agent_limits_settings.get_effective_limits()`：

    IterationGate(max_rounds=resolveToolRoundBudget())        # 派生自 max_loop_rounds
    TokenBudgetGate(max_tokens=limits["token_budget"])
    GoalGate(maxContinuations=limits["goal_max_continuations"], ...)

而同一行集合里的 **`DoomLoopGate()` 是无参构造**（`base.py:379`），三个阈值
`window_size=4` / `similarity_threshold=0.95` / `max_interrupts=2` 只活在 `gates.py:105-115`
的类字面量上——**不受任何配置键管辖**。同文件 `:366-368` 的注释已经把这种形态点名为忌讳
（那是 GoalGate 轮次预算收口时写下的原话：「默认装配路径也必须传它，否则门控回落到
gates.py 的类字面量，上限再次不受任何配置键管辖」）。

这不是假设：死循环门是**唯一没有管理面的一档**——管理员把 `max_loop_rounds` 调到 200
可以，改「几次重复签名就判死循环」只能改代码。

## 复核实状时改掉的一条原前提（重要），以及它后来的下落

原以为三阈值都要挂键。实测 `similarity_threshold` **存进实例后全仓零读取**——`check()`
判的是签名是否**逐字相等**落在滑动窗口里，近似匹配从未实装。给它造一个配置键，就是仓里
明令禁止的第二形态「棘轮奖励自己编辑空对象」。M-A 那批因此**只把两个真在用的阈值接到单源**，
第三键登记待裁（甲 实装近似比较＝行为变更｜乙 退役这个误导旋钮｜丙 原样留着）。

**2026-10-16 用户裁甲并已实装**：`gates.py:_signaturesSimilar` 现在真按这一档比对，
配置键 `doom_loop_similarity_threshold` 也随之进单源。默认值取 **1.0（＝逐字相等，
线上开火时点一字不变）**，理由是实测量出来的而不是推测：用生产签名拼法 `_toolSignatures`
算出的比值——同参空转 0.978、翻页推进 0.976、顺序读不同文件 0.932/0.843、
不同工具同参数 0.902、多调用 vs 单调用 0.489。收紧到 0.95 抓到空转，但**会把翻页
读取判成重复**（长文件分段读是常见动作），所以启用与否留给配置面显式决定；
代价与判据同档可复核（见本档 `TestSignatureSimilarity` 的比值格）。

## 判据（八格 + 相似度语义格，全部走真装配点取数，不手工传阈值）

1. 默认装配的三个阈值 == 配置单源的生效值；
2. 改配置 ⇒ 装配读数跟着走（管辖成立的正向读数）；
3. **阈值真被使用**：`max_interrupts=1` 与 `=3` 两档下，同一个重复签名序列读出的
   `StopAction` 必须不同；
4. 合法域夹紧：越界配置被夹回区间（窗口下界 1、中断下界 1、相似度下界 0.5——
   再低就等于任意两轮都算重复，那是把门控变成无条件开火）；
5. 持久化面：设置文件能写能读回这些键（`load/save` 按 `DEFAULTS` 过滤 ⇒ 漏定义键就静默丢）；
6. 装配点形状：唯一装配点上 `DoomLoopGate` 的构造必须带齐这三个关键字实参（钉代码形态），
   且类默认值取自同一单源、`gates.py` 里不留数字字面量的第二份手抄。
7. 声明式配置门（`gate_catalog`）与装配点**不许有两份默认值**：三键缺省即回落单源。
8. 挂键与读取必须同时成立（这一格从 M-A 的蕴涵式转成直接断言）。
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE_LOOP_PY = PROJECT_ROOT / "neurova" / "agent" / "loops" / "base.py"
GATES_PY = PROJECT_ROOT / "neurova" / "agent" / "gates.py"

DOOM_KEYS = ("doom_loop_window_size", "doom_loop_max_interrupts",
             "doom_loop_similarity_threshold")
CTOR_ATTRS = ("window_size", "max_interrupts", "similarity_threshold")
#: 曾经的"只写不读死旋钮"，2026-10-16 按用户裁定甲实装并挂键（见上方文档段）。
DEAD_KNOB_KEY = "doom_loop_similarity_threshold"


def _effective():
    from neurova.security.agent_limits_settings import get_effective_limits

    return get_effective_limits()


def _assembledDoomGate():
    """真装配点构造出来的那只死循环门（`OpenAILoop` + 生产 `_buildGateRunner`）。"""
    from neurova.agent.loops.openai_loop import OpenAILoop

    agent = MagicMock()
    agent.config.name = "probe-agent"
    agent.config.agent_id = "probe-agent-id"
    agent.llm_client = MagicMock()
    for gate in OpenAILoop(agent)._buildGateRunner().gates:
        if getattr(gate, "name", "") == "doom_loop":
            return gate
    raise AssertionError("默认装配里没有 doom_loop 门控——本片前提不成立")


@pytest.fixture
def restoreDefaults():
    """改 DEFAULTS 的用例必须按原值整体还原（dict 引用不换、内容复原）。"""
    import neurova.security.agent_limits_settings as als

    original = dict(als.DEFAULTS)
    yield als
    als.DEFAULTS.clear()
    als.DEFAULTS.update(original)


class TestDoomLoopThresholdsFollowConfig:
    """死循环门的三阈值是「被声明的契约」，不是类字面量的副作用。"""

    def test_01_defaultAssemblyEqualsEffectiveConfig(self):
        effective = _effective()
        missing = [k for k in DOOM_KEYS if k not in effective]
        assert not missing, (
            f"配置单源缺键 {missing}：死循环门限无处声明，只能回落到 gates.py 的类字面量"
        )
        gate = _assembledDoomGate()
        for key, attr in zip(DOOM_KEYS, CTOR_ATTRS):
            assert getattr(gate, attr) == effective[key], (
                f"装配读到的 {attr}={getattr(gate, attr)!r} 与单源 {key}={effective[key]!r} 不一致"
            )

    def test_02_assemblyScalesWithConfig(self, restoreDefaults):
        restoreDefaults.DEFAULTS["doom_loop_window_size"] = 9
        restoreDefaults.DEFAULTS["doom_loop_max_interrupts"] = 5
        gate = _assembledDoomGate()
        assert (gate.window_size, gate.max_interrupts) == (9, 5), (
            f"改配置后装配读数未跟随：{(gate.window_size, gate.max_interrupts)}"
        )

    def test_03_thresholdIsActuallyUsedByTheGate(self, restoreDefaults):
        """阈值不能只是"挂上了却没人比"——两档配置必须读出**不同的开火时点**。

        生产语义（`gates.py` 的 `check()`）：首个签名入窗，之后每次重复使中断计数 +1，
        计数达 `max_interrupts` 才 TERMINATE。所以 `max_interrupts=N` 时，第一次终止
        落在第 N+1 次 `check()`（索引 N）。判据按这个规则取"首次终止索引"，
        不是我自己缩一个"永不终止"的窄口径。
        """
        from neurova.agent.gates import StopAction

        def firstTerminateIndex(maxInterrupts: int) -> int:
            restoreDefaults.DEFAULTS["doom_loop_max_interrupts"] = maxInterrupts
            gate = _assembledDoomGate()
            for i in range(8):
                if gate.check({"round_signature": "same-tool-same-args"}).action is StopAction.TERMINATE:
                    return i
            return -1

        strict = firstTerminateIndex(1)
        lenient = firstTerminateIndex(3)
        assert strict == 1, f"max_interrupts=1 应在第 2 次 check 终止，实测索引 {strict}"
        assert lenient == 3, f"max_interrupts=3 应在第 4 次 check 终止，实测索引 {lenient}"
        assert strict != lenient, "两档配置读出同一个时点——阈值根本没被比"

    def test_04_outOfRangeConfigIsClamped(self, restoreDefaults):
        restoreDefaults.DEFAULTS["doom_loop_window_size"] = 10_000
        restoreDefaults.DEFAULTS["doom_loop_max_interrupts"] = -3
        effective = _effective()
        assert effective["doom_loop_window_size"] == restoreDefaults.MAX_DOOM_LOOP_WINDOW, (
            f"window_size 越界未被夹紧：{effective['doom_loop_window_size']}"
        )
        assert effective["doom_loop_max_interrupts"] >= 1, (
            f"中断上限被夹成 {effective['doom_loop_max_interrupts']}（0 或负数＝第一次重复就终止，"
            "那不是收紧而是换了一道判据）"
        )

    def test_04b_similarityThresholdDomainIsClamped(self, restoreDefaults):
        """相似度的合法域是 (0,1]：下界之下等于"任意两轮都算重复"。

        下界取 0.5 有实测依据——生产签名拼法下，**完全不像**的两轮比值 0.489；
        允许更低就是把门控变成无条件开火，而不是收紧判据。
        """
        restoreDefaults.DEFAULTS["doom_loop_similarity_threshold"] = 0.1
        assert _effective()["doom_loop_similarity_threshold"] == \
            restoreDefaults.MIN_DOOM_LOOP_SIMILARITY
        restoreDefaults.DEFAULTS["doom_loop_similarity_threshold"] = 1.7
        assert _effective()["doom_loop_similarity_threshold"] == \
            restoreDefaults.MAX_DOOM_LOOP_SIMILARITY
        restoreDefaults.DEFAULTS["doom_loop_similarity_threshold"] = "abc"
        assert _effective()["doom_loop_similarity_threshold"] == 1.0, (
            "坏值必须回默认（逐字相等），不能把脏配置读成「近似开火」")

    def test_05_persistenceRoundTripsTheGovernedKeys(self, tmp_path, monkeypatch):
        import json

        import neurova.security.agent_limits_settings as als

        target = tmp_path / "agent_limits.json"
        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(target))
        wanted = {"doom_loop_window_size": 7, "doom_loop_max_interrupts": 4}
        assert als.save_agent_limits(dict(wanted)), "写入失败"
        onDisk = json.loads(target.read_text(encoding="utf-8"))
        assert all(onDisk.get(k) == v for k, v in wanted.items()), (
            f"落盘缺键：{onDisk}"
        )
        assert als.load_agent_limits() == {**als.DEFAULTS, **wanted}, (
            "读回与默认值合并结果不符——load 按 DEFAULTS 过滤，键没定义就静默丢"
        )

    def test_06_assemblyPassesAllThreeKeywords(self):
        """唯一装配点上必须显式传三键（钉代码形态，不钉词）。"""
        tree = ast.parse(BASE_LOOP_PY.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", "")) == "DoomLoopGate"
        ]
        assert calls, "装配点里找不到 DoomLoopGate 构造——本判据的扫描面变了，须改判而非放过"
        for call in calls:
            passed = {kw.arg for kw in call.keywords}
            assert set(CTOR_ATTRS) <= passed, (
                f"{BASE_LOOP_PY.name}:{call.lineno} 的 DoomLoopGate 构造缺关键字实参，"
                f"现传 {sorted(passed)}——缺的那格会回落到类字面量，不受配置管辖"
            )

    def test_07_gateClassDefaultsComeFromTheSameSource(self):
        """类默认值也不许是第二份手抄：无参构造的默认必须等于单源 DEFAULTS 现值。

        先例 `agent/swarm.py:_settingsDefaultSubagentDepth()`——把单源的值搬进类属性，
        而不是在此再抄一个数字。
        """
        import neurova.security.agent_limits_settings as als
        from neurova.agent.gates import DoomLoopGate

        gate = DoomLoopGate()
        for key, attr in zip(DOOM_KEYS, CTOR_ATTRS):
            assert key in als.DEFAULTS, f"单源缺 {key}"
            assert getattr(gate, attr) == als.DEFAULTS[key], (
                f"gates.py 的 {attr} 默认值 {getattr(gate, attr)!r} 与单源 "
                f"{als.DEFAULTS[key]!r} 是两份手抄——改一处另一处静默不动"
            )
        assert "window_size: int = 4" not in GATES_PY.read_text(encoding="utf-8"), (
            "gates.py 里仍留着 window_size 的数字字面量默认值"
        )

    def test_08_keyIsBothBoundAndRead(self):
        """这一格从 M-A 的**蕴涵式**转成直接断言：旋钮已实装，挂键与读取必须同时成立。

        原形态是"键未定义就跳过"，防的是"挂上管理面却仍不生效"（面板显示一份没在生效
        的值）。甲案落地后那个跳过分支就是死代码，留着等于给未来的回退留一条静默路。
        """
        import neurova.security.agent_limits_settings as als

        assert DEAD_KNOB_KEY in als.DEFAULTS, "键被摘掉：旋钮又回到不受管辖的字面量"
        gatesText = GATES_PY.read_text(encoding="utf-8")
        body = gatesText.split("def reset_session", 1)[0].split("class DoomLoopGate", 1)[1]
        assert "self.similarity_threshold" in body, (
            f"{DEAD_KNOB_KEY} 在配置单源里，但 DoomLoopGate 没读 self.similarity_threshold"
            "——管理员会以为调它有效果"
        )


def _sig(name, args):
    """用**生产拼法**造签名（含参数截 64 字符的既有口径），不手造字符串。"""
    from neurova.agent.loops.base import BaseAgentLoop

    return BaseAgentLoop._toolSignatures([
        {"function": {"name": name, "arguments": args}}])


def _gate(threshold, window=4, interrupts=2):
    from neurova.agent.gates import DoomLoopGate

    return DoomLoopGate(window_size=window, similarity_threshold=threshold,
                        max_interrupts=interrupts)


class TestSignatureSimilarity:
    """近似判定真在比，且**代价与收益都可判**——比值全部来自生产签名拼法。"""

    def test_spinningRetryIsCaughtAt095(self):
        """同一调用只换一点参数（论文那类空转）：0.95 下算重复并升级。"""
        from neurova.agent.gates import StopAction

        a = _sig("read_file", '{"path":"docs/audit.md","offset":10}')
        b = _sig("read_file", '{"path":"docs/audit.md","offset":11}')
        # 中断上限 2：第一次算重复只注入"换策略"，第二次才终止（升级阶梯本身也是判据）
        gate = _gate(0.95, interrupts=2)
        assert gate.check({"round_signature": a}).action is StopAction.BYPASS
        assert gate.check({"round_signature": b}).action is StopAction.INTERRUPT_AND_CONTINUE
        assert gate.check({"round_signature": b}).action is StopAction.TERMINATE
        # 同一序列在默认档（1.0）下什么都不会发生——这一格就是"线上开火时点会变"的正向证据
        untouched = _gate(1.0, interrupts=2)
        untouched.check({"round_signature": a})
        assert untouched.check({"round_signature": b}).action is StopAction.BYPASS

    def test_sequentialDistinctFileReadsAreNotCaughtAt095(self):
        """正常推进（换文件读）不得被误判：这一格是"0.95 可用"的下界证据。"""
        from neurova.agent.gates import StopAction

        a = _sig("read_file", '{"path":"src/components/SettingsPage.vue"}')
        b = _sig("read_file", '{"path":"src/components/GlassButton.vue"}')
        gate = _gate(0.95, interrupts=1)
        gate.check({"round_signature": a})
        assert gate.check({"round_signature": b}).action is StopAction.BYPASS

    def test_pagingIsCaughtTooAndThatIsTheDocumentedCost(self):
        """翻页读取（page 1→2）在 0.95 下**也**被判重复——这是本档默认的已知代价。

        写成一格而不是只写在注释里，是因为它是"默认为什么留 1.0"的唯一可复核证据：
        字符串层面翻页与空转不可分（0.976 vs 0.978），要区分得读工具返回值，
        而本门的 `check(ctx)` 只看轮次签名。收紧之前必须知道这条代价。
        """
        from neurova.agent.gates import StopAction

        p1 = _sig("read_file", '{"path":"docs/long.md","page":1}')
        p2 = _sig("read_file", '{"path":"docs/long.md","page":2}')
        gate = _gate(0.95, interrupts=2)
        gate.check({"round_signature": p1})
        assert gate.check({"round_signature": p2}).action is StopAction.INTERRUPT_AND_CONTINUE

    def test_defaultOnePointZeroIsExactlyTheOldSemantics(self):
        """默认 1.0 = 逐字相等：近似不误伤，而真重复照旧开火（线上开火时点不变的证据）。"""
        from neurova.agent.gates import StopAction

        spinA = _sig("read_file", '{"path":"docs/audit.md","offset":10}')
        spinB = _sig("read_file", '{"path":"docs/audit.md","offset":11}')
        gate = _gate(1.0, interrupts=1)
        gate.check({"round_signature": spinA})
        assert gate.check({"round_signature": spinB}).action is StopAction.BYPASS, (
            "阈值 1.0 却按近似开了火——默认值不再是「实装前的语义」")
        same = _sig("read_file", '{"path":"docs/audit.md","offset":10}')
        assert gate.check({"round_signature": same}).action is StopAction.TERMINATE

    def test_productionAssemblyKeepsTheOldFiringTime(self):
        """装配点取的是单源默认（1.0）：本批没有把线上判定悄悄改成近似。"""
        import neurova.security.agent_limits_settings as als

        assert als.DEFAULTS["doom_loop_similarity_threshold"] == 1.0
        assert _assembledDoomGate().similarity_threshold == 1.0

    def test_absurdlyLowThresholdDoesNotBecomeFireAlways(self):
        """非法下界不解释成"任意两轮都算重复"（那等于门控无条件开火）。"""
        from neurova.agent.gates import StopAction

        gate = _gate(0.0, interrupts=1)
        gate.check({"round_signature": _sig("read_file", '{"path":"a.md"}')})
        assert gate.check({"round_signature": _sig("write_file", '{"path":"zzz.md"}')}).action \
            is StopAction.BYPASS

    def test_comparisonCostHasAnUpperBound(self):
        """长参数不得把每轮比对放大：比对前按上界截断，这是成本上界的可判形式。"""
        from neurova.agent.gates import _SIGNATURE_COMPARE_CAP, _signaturesSimilar

        longTail = "x" * (4 * _SIGNATURE_COMPARE_CAP)
        a = "read:" + longTail + "|A"
        b = "read:" + longTail + "|B"
        # 尾部不同，但截断后完全相同 ⇒ 判为同一条：证明只看前 CAP 个字符
        assert _signaturesSimilar(a, b, 0.999) is True
        headA = "read:" + "a" * _SIGNATURE_COMPARE_CAP
        headB = "read:" + "b" * _SIGNATURE_COMPARE_CAP
        assert _signaturesSimilar(headA, headB, 0.999) is False


class TestDeclarativeGateSharesTheSingleSource:
    """声明式配置门与装配点不许各持一份默认值（两份默认＝两种判重语义，各自都绿）。"""

    def testOmittedParamsFallBackToTheConfigSingleSource(self):
        from neurova.agent.gate_catalog import GateCatalog, compile_gates
        import neurova.security.agent_limits_settings as als

        gate = compile_gates([{"type": "doom_loop"}], GateCatalog())[0]
        defaults = als.DEFAULTS
        assert gate.window_size == defaults["doom_loop_window_size"]
        assert gate.max_interrupts == defaults["doom_loop_max_interrupts"]
        assert gate.similarity_threshold == defaults["doom_loop_similarity_threshold"]

    def testCatalogDoesNotRetypeTheDefaults(self):
        text = (PROJECT_ROOT / "neurova" / "agent" / "gate_catalog.py").read_text(
            encoding="utf-8")
        for line in ("window_size: int = 4", "similarity_threshold: float = 0.95",
                     "max_interrupts: int = 2"):
            assert line not in text, f"gate_catalog.py 里仍手抄默认值：{line}"

    def testOutOfRangeParamsFailFast(self):
        from pydantic import ValidationError

        from neurova.agent.gate_catalog import DoomLoopParams

        with pytest.raises(ValidationError):
            DoomLoopParams(similarity_threshold=1.5)
        with pytest.raises(ValidationError):
            DoomLoopParams(similarity_threshold=0.2)


class TestSiblingGatesShareTheSameSource:
    """§6-271「仍开②」的落点：同一条根因在另外两把门上的两个命中点（教义第 5 条）。

    `IterationGate(max_rounds: int = 20)` 与 `TokenBudgetGate(max_tokens: int = 100000)`
    都是配置单源 `agent_limits_settings.DEFAULTS` 的第二份手抄，`gate_catalog` 的
    `IterationParams` / `TokenBudgetParams` 又抄了第三、第四份。生产装配点每轮都显式传值
    （`base.py:422-423`），所以这些数字今天"只是"漂移风险——但漂移这条路本来就没有正确答案：

    **`IterationGate(max_rounds=None)` 走的是 `self.ROUND_BUDGET_FALLBACK`，而那个属性只在
    `GoalGate` 上定义（`gates.py:245`）**，None 传进来当场 AttributeError。
    也就是说"缺省时取什么"这一格上，一份手抄数字与一条会崩的分支并排放着——本批把它接到单源，
    形态与 `DoomLoopGate` / `DoomLoopParams` 完全一致（缺省＝取单源，合法域＝取夹紧常量）。
    """

    def testClassDefaultsEqualTheSingleSource(self):
        import neurova.security.agent_limits_settings as als
        from neurova.agent.gates import IterationGate, TokenBudgetGate

        assert IterationGate().max_rounds == als.DEFAULTS["max_loop_rounds"]
        assert TokenBudgetGate().max_tokens == als.DEFAULTS["token_budget"]

    def testDefaultsTrackTheSingleSourceNotAReType(self, restoreDefaults):
        """按值相等只证"今天恰好一样"——把单源改掉，缺省读数必须跟着动（形态集 241）。"""
        from neurova.agent.gates import IterationGate, TokenBudgetGate

        restoreDefaults.DEFAULTS["max_loop_rounds"] = 33
        restoreDefaults.DEFAULTS["token_budget"] = 44000
        assert IterationGate().max_rounds == 33, "IterationGate 的缺省不跟着单源动＝又抄了一份"
        assert TokenBudgetGate().max_tokens == 44000, "TokenBudgetGate 同上"

    def testNoneMeansFollowTheSourceNotCrash(self):
        """显式传 None 与不传必须同解——今天前者直接 AttributeError（属性定义在另一把门上）。"""
        import neurova.security.agent_limits_settings as als
        from neurova.agent.gates import IterationGate, TokenBudgetGate

        assert IterationGate(max_rounds=None).max_rounds == als.DEFAULTS["max_loop_rounds"]
        assert TokenBudgetGate(max_tokens=None).max_tokens == als.DEFAULTS["token_budget"]

    def testGatesSourceDoesNotRetypeThoseLiterals(self):
        """形状反证：数字不许留在 `gates.py` 的签名默认值上（同 `window_size: int = 4` 那一格）。"""
        text = GATES_PY.read_text(encoding="utf-8")
        for line in ("max_rounds: int = 20", "max_tokens: int = 100000"):
            assert line not in text, f"gates.py 里仍手抄默认值：{line}"

    def testCatalogOmittedParamsFallBackToTheSource(self):
        """声明式配置与装配点同取一份默认，否则两边按两种阈值判停、各自测试都绿。"""
        import neurova.security.agent_limits_settings as als
        from neurova.agent.gate_catalog import GateCatalog, compile_gates

        defaults = als.DEFAULTS
        built = {g.name: g for g in compile_gates(
            [{"type": "iteration"}, {"type": "token_budget"}], GateCatalog())}
        assert built["iteration"].max_rounds == defaults["max_loop_rounds"]
        assert built["token_budget"].max_tokens == defaults["token_budget"]

    def testCatalogDoesNotRetypeThoseDefaults(self):
        text = (PROJECT_ROOT / "neurova" / "agent" / "gate_catalog.py").read_text(encoding="utf-8")
        for line in ("max_rounds: int = 20", "max_tokens: int = 100000"):
            assert line not in text, f"gate_catalog.py 里仍手抄默认值：{line}"

    def testCatalogBoundsComeFromTheClampConstants(self):
        """合法域也取同一批常量：面板/schema 报出的区间必须等于 `get_effective_limits` 夹紧用的区间。"""
        import neurova.security.agent_limits_settings as als
        from pydantic import ValidationError

        from neurova.agent.gate_catalog import IterationParams, TokenBudgetParams

        def bounds(model, name):
            ge = le = None
            for meta in model.model_fields[name].metadata:
                ge = getattr(meta, "ge", ge)
                le = getattr(meta, "le", le)
            return ge, le

        assert bounds(IterationParams, "max_rounds") == (als.MIN_ROUNDS, als.MAX_ROUNDS)
        assert bounds(TokenBudgetParams, "max_tokens") == (als.MIN_TOKEN_BUDGET, als.MAX_TOKEN_BUDGET)
        for bad in (als.MIN_ROUNDS - 1, als.MAX_ROUNDS + 1):
            with pytest.raises(ValidationError):
                IterationParams(max_rounds=bad)
        for bad in (als.MIN_TOKEN_BUDGET - 1, als.MAX_TOKEN_BUDGET + 1):
            with pytest.raises(ValidationError):
                TokenBudgetParams(max_tokens=bad)
