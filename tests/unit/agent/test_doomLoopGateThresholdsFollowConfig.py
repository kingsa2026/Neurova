# -*- coding: utf-8 -*-
"""DoomLoopGate 的两个在用阈值必须受配置键管辖（ModularRSI 对照 §4 M-A 第①步；台账记有本格）。

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

## 复核实状时改掉的一条原前提（重要）

原以为三阈值都要挂键。实测 `similarity_threshold`（`gates.py:108,114`）**存进实例后全仓零读取**
——`check()` 判的是签名是否**逐字相等**落在滑动窗口里（`:124` `if signature in self._window`），
近似匹配从未实装。给它造一个配置键，就是仓里明令禁止的第二形态「棘轮奖励自己编辑空对象」
（见 `integration_manager.py:56-60` 的入表前置、§6-1 的 `context.experience_knowledge` 死旋钮）。
本批因此**只把两个真在用的阈值接到单源**，`similarity_threshold` 的存废作为同根因第四格
登记待裁（甲 实装近似比较＝行为变更｜乙 退役这个误导旋钮｜丙 原样留着），本批不擅动它。

## 判据（六格，全部走真装配点取数，不手工传阈值）

1. 默认装配的两个阈值 == 配置单源的生效值（改前：单源根本没有这两个键 ⇒ 红）；
2. 改配置 ⇒ 装配读数跟着走（管辖成立的正向读数，改前恒为 4/2）；
3. **阈值真被使用**：`max_interrupts=1` 与 `=3` 两档下，同一个重复签名序列读出的
   `StopAction` 必须不同（改前装配不传值，两档同读数）；
4. 合法域夹紧：越界配置被夹回区间（窗口下界 1、中断下界 1——0 意味着第一次重复就终止，
   那不是"收紧"而是换了一道判据）；
5. 持久化面：设置文件能写能读回这两个键（`load/save` 按 `DEFAULTS` 过滤 ⇒ 漏定义键就静默丢）；
6. 装配点形状：唯一装配点上 `DoomLoopGate` 的构造必须带齐这两个关键字实参（钉代码形态），
   且类默认值取自同一单源、`gates.py` 里不留这两个数字的第二份手抄。
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE_LOOP_PY = PROJECT_ROOT / "neurova" / "agent" / "loops" / "base.py"
GATES_PY = PROJECT_ROOT / "neurova" / "agent" / "gates.py"

DOOM_KEYS = ("doom_loop_window_size", "doom_loop_max_interrupts")
CTOR_ATTRS = ("window_size", "max_interrupts")
#: 存进实例却全仓零读取的那一格（本批只登记不接线）——它若被挂上配置键，必须同时被读。
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

    def test_08_deadKnobGetsNoConfigKeyUntilItIsRead(self):
        """登记待裁的那一格：`similarity_threshold` 存进实例后全仓没人读。

        判据写成**蕴涵**而不是"永远不许有键"：将来谁真去实装近似比较（甲案），
        加键的同时必须让 gates.py 里出现读取点，否则这一格红——
        防的是"挂上管理面却仍不生效"那种比死旋钮更坏的形态（面板显示一份没在生效的值）。
        """
        import neurova.security.agent_limits_settings as als

        if DEAD_KNOB_KEY not in als.DEFAULTS:
            return  # 本批现状：键未定义，旋钮未接线——两件事保持一致
        gatesText = GATES_PY.read_text(encoding="utf-8")
        readsIt = "self.similarity_threshold" in gatesText.split(
            "def reset_session", 1)[0].split("class DoomLoopGate", 1)[1]
        assert readsIt, (
            f"{DEAD_KNOB_KEY} 已进配置单源，但 DoomLoopGate 里没有一处读 self.similarity_threshold"
            "——管理员会以为调它有效果"
        )
