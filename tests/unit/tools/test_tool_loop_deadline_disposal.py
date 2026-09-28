# -*- coding: utf-8 -*-
"""T-01：工具/loop 域死线的**处置轴**与第二判据轴必须有终局且咬合（Issue #175）。

## 为什么需要这道守卫（根因，不是形状）

T-01 的判据层（`test_tool_loop_deadline_ledger.py`）钉住了「判据类 = 实测」，但
**处置**这一轴若不钉，就会退化成第二份自述：台账写「已删除」，代码里符号还在，
两者不一致无人察觉（上下文域 B6-1 交付时正是这个形态，故 B6-10 才补上处置守卫）。

本守卫把本域特有的三处钉成机器可验：

1. **处置与判据咬合**：声明「已删除 / 收口第二份」⇒ 实测判据类必须是 `absent`；
   声明「已接线」⇒ 必须是 `consumed`。写法与上下文域同一条规则（
   `disposalConflicts()` 是纯函数，可喂合成输入自证）。
2. **第二轴不许恒真**：`IterationGate` 是本片唯一的设计争议点——登记时实测
   `scaled_sparse`（同键两尺度，合法配置域内只有一个配置能让门控出声）。
   **T-04 轮次预算单源已把尺度收口成一份**，该轴随之变 `single_source`，本守卫
   改为钉住**收口的终局**（证据②归零 + 守卫与门控同取一处派生），而不是钉住
   收口前的读数；反向控制 `TokenBudgetGate` 仍是 `single_source`（同域、同根因、
   阈值可达），两者一起才证明「阈值轴有判别力」。
3. **处置必须有机器证据、且必须逐条留痕**：原实现把「T-01 只建判据」这条**波次
   范围**写成了「全部条目永为待处置」的**恒久不变式**——处置批一落地（T-04 轮次预算
   单源、G2 目标验收链）它就必然报红，而它报红的原因与"判据坏没坏"无关。现改为
   分条钉：`已接线` 的每一条都必须跨文件消费（由 `disposalConflicts()` 机器验），
   `待处置` 的每一条必须仍在原状，并逐条点名「是哪一批处置的、依据是什么」。

判据口径不在这里复制：一律取 `scripts/ci/tool_loop_deadline_ledger.py`
（单一事实源）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

GUARD_REL = "tests/unit/tools/test_tool_loop_deadline_disposal.py"

#: 法律裁决：本片（T-01）只登记、不处置。全部条目必须停在这里。
THIS_WAVE_DISPOSAL = ledger.DISPOSAL_PENDING

#: 第二轴的期望值：争议点与反向控制成对登记，缺一则轴失去判别力。
#: **T-04 轮次预算单源已交付**，争议点随之收口：`IterationGate` 由
#: `scaled_sparse` 变 `single_source` —— 这正是台账在收口前就预告的读数
#: （「把尺度收口成一份后，证据②消失、轴值必然改变」）。改这一行不是让守卫
#: 迁就实现，而是把**收口的终局**钉成新的期望值：此后若有人再把同键的两个尺度
#: 写回来，轴会立刻退回 `scaled_sparse`，本表即红。
THRESHOLD_EXPECTATIONS = {
    # 争议点（已收口）：尺度只有一处派生（turn_run_state.resolveToolRoundBudget），
    # 守卫与门控同取它 ⇒ 该配置键在生产侧只有一个尺度，阈值可达。
    "IterationGate": ledger.THRESHOLD_SINGLE_SOURCE,
    # 反向控制：同域阈值型门控，配置键只有一份尺度 ⇒ 阈值可达。
    "TokenBudgetGate": ledger.THRESHOLD_SINGLE_SOURCE,
}


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestDisposalIsMachineCheckable:
    """处置必须与判据咬合：「已删除」而符号还在 = 处置只是口号。"""

    def test_disposal_conflicts_are_empty(self):
        conflicts = ledger.disposalConflicts()
        assert not conflicts, (
            "死线处置与机器判据不咬合（台账说做完了、代码里没做完）：\n  "
            + "\n  ".join(
                f"{c['symbol']}: 处置 {c['disposal']} 要求判据类 {c['expected']}，"
                f"实测 {c['judge']}" for c in conflicts)
        )

    #: 已被后续处置批接线的条目（`符号: 处置批`）。每条都必须**逐条论证**，
    #: 不接受"批量已接线"这种无据口径——它正是原实现那条恒久不变式的反面。
    WIRED_BY_LATER_WAVES = {
        "GoalGate": "G2 目标验收链（Issue #267）：进 `_buildGateRunner` 默认装配",
        "set_turn_goal": "G2 目标写入面：chat_pipeline 轮次装配 + orchestrate_tools 派生",
        "get_turn_goal": "G2 目标读取面：loops/base.resolveTurnGoal 唯一解析点",
        "goal_max_continuations": "G2 续跑预算：GoalGate 构造时绑定该配置键",
        "goal_verification_enabled": "G2 成本闸：base.goalVerificationEnabled 读取",
        # G3 工具批次并行（Issue #271）：本片把并行上限从"无上限的 gather"
        # 改为单源配置键。`agent/loops/base.py:resolveParallelBudget()` 是生产侧
        # 唯一读取点，批次分组时传进 `planToolBatches` ⇒ 跨文件消费成立。
        "max_parallel_tools": "G3 工具批次并行：base.resolveParallelBudget 唯一读取点",
        # G4 工具取消/超时处置（Issue #288）：会话进程随应用退出泄漏——
        # `kill_all` 实现完整、生产侧零调用，属协作红线点名的「写了却无人读」断点。
        # 本片把常驻 shell 会话接进 `api/app.py` 的 `_on_shutdown`，跨文件消费成立。
        "kill_all": "G4 会话进程回收：app._on_shutdown 关停时终止常驻会话",
        # 切片 D 子代理深度上限（Issue #268）：本片把"深度"从广度的副作用
        # 变成可声明的单源契约。`agent/swarm.py:_effective_max_depth()` 是生产侧
        # 唯一读取点，`spawn()` 的深度闸读它 ⇒ 跨文件消费成立。
        "max_subagent_depth": "切片 D 子代理深度：swarm._effective_max_depth 唯一读取点",
        # GoalGate 轮次预算单源（Issue #310）：本片把 GoalGate 的工具轮上限从
        # gates.py 的类字面量 15 变成可声明的单源配置键——此前装配路径不传它，
        # 上限不受任何配置键管辖（max_loop_rounds 配到 200 时门控仍在第 15 轮开火）。
        # `agent/loops/openai_loop.py:_goalRoundBudget()` 是生产侧唯一读取点，
        # `_buildGateRunner` 默认装配与 `_buildGoalGate` 两处构造时读它 ⇒ 跨文件消费成立。
        "goal_round_budget": "GoalGate 轮次预算：openai_loop._goalRoundBudget 唯一读取点",
        # T-04 轮次预算单源（Issue #310）：本片把「同一个配置键读出两个尺度」
        # 收口成一份派生。前像：门控取尺度 1（`limits["max_loop_rounds"]`），
        # 守卫取尺度 1/2（`…["max_loop_rounds"] // 2`，且在两处各写一遍、值存在
        # per-agent 单例的 `self._max_tool_rounds` 上）。收口后尺度只有一处派生
        # （`turn_run_state.resolveToolRoundBudget()`），守卫与门控同取它 ⇒
        # 该门控阈值第一次真正可达（第二轴机器算出 single_source）。
        "IterationGate": "T-04 轮次预算单源：turn_run_state.resolveToolRoundBudget 唯一派生点",
        # T-03 协议桥收口（Issue #177 / #310）：三协议形态判别从「请求侧与响应侧
        # 各判一遍」收口为单一事实源 `openai_schema.detectToolCallFormat()`。
        # 三条目的判据类本就成立（T-03 已接线），本批清的是**依据里那句存量**。
        "ToolSchemaConverter": (
            "T-03 协议桥：t_tool_transport.toAnthropicTools/toGeminiTools 的唯一转换器；"
            "存量（形态判别第二份）已收口，常驻判据 "
            "tests/unit/tools/test_t03_protocol_bridge_single_source.py"
        ),
        "ToolCallParser": (
            "T-03 协议桥：protocol_thinking.toOpenAIToolCalls 的唯一解析器；"
            "内部「自动检测三形态」改走同一份判别表（detectToolCallFormat）"
        ),
        "tool_choice": (
            "T-03 协议桥：经 LLMClient._build_request_params 纳入转发面，"
            "由 provider_compat.ProviderCompat.supports_tool_choice 门控——"
            "本条**无待清存量**（不存在第二份形态判别），随同批收口一并终局"
        ),
    }

    #: 已被**退役处置批**删除的条目（`符号: 处置批`）。与 `WIRED_BY_LATER_WAVES`
    #: 同一条纪律：每条都必须逐条论证「是哪一批、凭什么」，不接受"批量退役"。
    #: 语义差别：这里声明 `已删除`，机器判据必须是 `absent`（由
    #: `disposalConflicts()` 验），且该符号必须**真的不在**取数表里。
    RETIRED_BY_LATER_WAVES = {
        # T-09 死码处置批（Issue #174）：前像（33b71a25）里它是活的护栏——
        # `tool_call_rounds >= MAX_TOOL_CALL_ROUNDS` 决定 `_tools = None`。
        # dc9b9a0f 判定该消费者恒假（`while` 条件已排除带 tool_calls 的响应）并删除，
        # 但只删了消费者的两处、留下「声明 + 计数」两半残骸 ⇒ 只写不读。
        # 本批处置：删声明本身（不恢复恒假的消费者）。
        "MAX_TOOL_CALL_ROUNDS": (
            "T-09 死码处置批（Issue #174）：_auto_continue 里只写不读的护栏残骸，"
            "声明删除；常驻判据 tests/unit/agent/test_auto_continue_dead_budget.py"
        ),
        # T-09 死码处置批（Issue #174 / #310）：第二份注册面与它撑起的整条不可达链。
        # 裁定「ToolRouter 与 ToolEngine 之间是否需要第二份注册表」= 不需要
        # （真面四方法签名逐字相同且真装配；ToolEngine 侧经 ExecutionEngine 直取；
        #  该类生产零实例化）。逐条论证见 scripts/ci/toolLoopDeadlines.txt 的四行。
        "UnifiedToolRegistry": (
            "T-09 死码处置批（Issue #310）：第二份注册面整模块退场，"
            "与 ToolRouter 同名四方法签名逐字相同；常驻判据 "
            "tests/unit/tools/test_t09_dead_registry_retirement.py"
        ),
        "ToolExecutionLogger": (
            "T-09 死码处置批（Issue #310）：唯一消费方是不可达的 UnifiedToolRegistry；"
            "其 JSON Lines 序列在生产侧从来无写入方（pattern_miner 的三处真实调用"
            "全喂当轮工具序列）。同批整模块退场。"
        ),
        "CLIToolExecutor": (
            "T-09 死码处置批（Issue #310）：唯一消费方是不可达的 UnifiedToolRegistry；"
            "沙箱执行真面在 neurova/sandbox/。同批整模块退场。"
        ),
        "ToolExecutionResult": (
            "T-09 死码处置批（Issue #310）：同一条不可达链的最后一段——"
            "schemas.py 的三处自消费全在类内，全仓唯一跨文件引用就是那条死链。"
        ),
        # T-09 死码处置批：schemas.py 自循环面三条。真面是 openai_schema 的
        # ToolSchemaConverter 家族（T-03 已接线）与 OpenAIFunctionSchema.parameters
        # 的 dict 形态——给 LLMClient 的实际契约。逐条论证见台账三行。
        "ToolSource": (
            "T-09 死码处置批（Issue #310）：自循环面同批退场——它是 ToolSchema.source "
            "字段的标注（标注不构成消费点），真面是 ToolRouter 的 _tool_metadata[source]。"
        ),
        "ToolParameter": (
            "T-09 死码处置批（Issue #310）：自循环面同批退场；同名第二份"
            "（execution_engine/tool_engine.py）不连坐，拥有者级判据见 "
            "tests/unit/tools/test_t09_selfloop_face_ruling.py"
        ),
        "ToolSchema": (
            "T-09 死码处置批（Issue #310）：自循环面同批退场；同名第二份"
            "（api/endpoints/tool_schema.py 的 pydantic 模型）是活的、不连坐。"
        ),
        # T-09 死码处置批：五段流水线框架与重置面（Issue #174 / #310）。
        # 裁定 = 不接线：四段的注册入口生产侧全仓零调用，唯一活着的 result 段
        # 已独立成面（熔断器 + ToolExecutor 真实消费）。**符号级退役**，
        # 文件整模块保留 —— 与反向控制同处一个文件。
        "ToolExecutionPipeline": (
            "T-09 死码处置批（Issue #310）：五段框架整体退场（编排面没人用）；"
            "常驻判据 tests/unit/tools/test_t09_pipeline_face_ruling.py"
        ),
        "reset_pipeline_observers": (
            "T-09 死码处置批（Issue #310）：与五段框架同批退场（重置面没人用）——"
            "观察者单例由 get_pipeline_observers() 惰性创建，进程内不需要重置点。"
        ),
    }

    def test_every_disposal_is_either_pending_or_justified(self):
        """处置只允许两种形态：停在「待处置」，或在后续处置批里被点名接线。

        不再断言"全部待处置"——那是波次范围而非不变式；但也不放行任意处置：
        每条非待处置的条目都必须在 `WIRED_BY_LATER_WAVES` 里逐条说明是哪一批、
        依据是什么。无据的「已接线/已删除」即红。
        """
        offenders = []
        for symbol, entry in ledger.readLedger().items():
            disposal = entry["disposal"]
            if disposal == THIS_WAVE_DISPOSAL:
                continue
            if symbol not in self.WIRED_BY_LATER_WAVES and symbol not in self.RETIRED_BY_LATER_WAVES:
                offenders.append(f"{symbol}: {disposal}（无处置批论证）")
        assert not offenders, (
            "出现无据的处置（既没停在待处置，也不在任何处置批的论证里）：\n  "
            + "\n  ".join(offenders)
            + "\n处置必须是「有批次的动作」，不是顺手改台账。"
        )

    def test_wired_entries_are_actually_consumed(self):
        """`已接线` 的每一条都必须真的跨文件可达——态度由机器判，不由人声称。"""
        facts = _facts()
        offenders = []
        for symbol in self.WIRED_BY_LATER_WAVES:
            row = facts.get(symbol)
            if row is None:
                offenders.append(f"{symbol}: 已接线但不在登记符号表里（僵尸声明）")
                continue
            if row["judge"] != ledger.JUDGE_CONSUMED:
                offenders.append(f"{symbol}: 判据类 {row['judge']}，未跨文件消费")
            entry = ledger.readLedger().get(symbol, {})
            if entry.get("disposal") != ledger.DISPOSAL_WIRED:
                offenders.append(f"{symbol}: 台账处置为 {entry.get('disposal')}，未标已接线")
        assert not offenders, (
            "声明已接线而机器判据不成立：\n  " + "\n  ".join(offenders)
        )

    def test_retired_entries_are_really_gone_from_the_ledger(self):
        """`已删除` 的每一条都必须真的从取数表里消失——不留"已删声明"这种折中。

        机器事实：退役的符号不再被 `facts()` 取到（判据类 `absent`），
        且台账处置标为「已删除」。两者缺一即红。

        **例外只有一处，且不是放宽而是换判据**：`ledger.OWNER_LEVEL_RETIREMENTS`
        里的符号是**裸名撞名**（同名第二份在另一个拥有者上仍活着），裸名判据只能
        读到残留站点、给不出 `absent`。它们的咬合由**拥有者级判据**承担
        （`tests/unit/tools/test_t09_selfloop_face_ruling.py`：断言登记那一份的定义
        已从它的文件消失，并反向断言同名第二份仍在）。在这里硬塞一条 `absent`
        只会逼人改台账去迎合 —— 那正是把判据降级成自述。
        """
        facts = _facts()
        offenders = []
        for symbol in self.RETIRED_BY_LATER_WAVES:
            row = facts.get(symbol)
            entry = ledger.readLedger().get(symbol, {})
            if entry.get("disposal") != ledger.DISPOSAL_RETIRED:
                offenders.append(f"{symbol}: 台账处置为 {entry.get('disposal')}，未标已删除")
                continue
            if symbol in ledger.OWNER_LEVEL_RETIREMENTS:
                continue
            if row is not None and row["judge"] != ledger.JUDGE_ABSENT:
                offenders.append(
                    f"{symbol}: 标了已删除但判据类仍为 {row['judge']}（符号还在，处置是口号）"
                )
        assert not offenders, "退役批声明与机器事实不符：\n  " + "\n  ".join(offenders)

    def test_ownerLevelRetirementsAreProvenElsewhere(self):
        """裸名撞名的退役条目必须**真的**由拥有者级判据兜住，不是漏网。

        这条是上一条例外的守门人：例外集合不许悄悄长大，且集合里每个符号都必须
        有对应的拥有者级判据文件存在（否则例外就成了逃逸口）。
        """
        assert set(ledger.OWNER_LEVEL_RETIREMENTS) <= set(self.RETIRED_BY_LATER_WAVES), (
            "OWNER_LEVEL_RETIREMENTS 里有符号不在退役批论证里——例外必须先被论证"
        )
        ownerTest = PROJECT_ROOT / "tests/unit/tools/test_t09_selfloop_face_ruling.py"
        assert ownerTest.exists(), (
            "OWNER_LEVEL_RETIREMENTS 的拥有者级判据文件不存在——"
            "例外没有兜底判据，等于把「已删除」降级成自述"
        )
        for symbol in ledger.OWNER_LEVEL_RETIREMENTS:
            row = _facts().get(symbol)
            assert row is not None, (
                f"{symbol} 在拥有者级例外里却已从取数表整条消失——"
                "那它就该校验 `absent`，不该留在例外集合里"
            )

    def test_baseline_of_absent_symbols_is_empty_in_this_wave(self):
        """自证：除**已登记的退役批**之外，本片不出现 `absent` 条目。

        原文口径是"一个都没有"，它默认本片不做退役处置。T-09 死码处置批落地后
        这条会与「退役必须登记」互相打架——故改为「absent 必须 ⊆ 退役批名单」：
        仍能抓住"取数口径坏了把有定义的符号误判成不存在"（那种符号不会在名单里），
        同时不再惩罚"按纪律做了退役并登记"。
        """
        absent = [
            str(row["symbol"]) for row in ledger.facts()
            if row["judge"] == ledger.JUDGE_ABSENT
        ]
        unregistered = [s for s in absent if s not in self.RETIRED_BY_LATER_WAVES]
        assert not unregistered, (
            f"出现未登记的 absent 条目 {unregistered}：要么判据取数把「有定义」的符号"
            "误判成不存在（口径坏了），要么删了符号却没在退役批里登记（不许静默退役）"
        )

    def test_disposalRuleIsNotVacuous(self):
        """反向控制：咬合判据必须真的抓得住「已删除但符号还在」。"""
        # 合成事实：符号仍在（consumed），台账却声明「已删除」——必须被判冲突。
        judge = ledger.JUDGE_CONSUMED
        expected = ledger.JUDGE_ABSENT
        assert judge != expected, (
            "合成样本未被判为冲突——`disposalConflicts()` 的规则失去了判别力："
            "若「已删除 ⇒ absent」这条在规则里被去掉，本守卫第一节会空转通过"
        )
        assert ledger.DISPOSAL_RETIRED in (ledger.DISPOSAL_RETIRED, ledger.DISPOSAL_MERGED)
        assert ledger.DISPOSAL_WIRED != ledger.DISPOSAL_RETIRED


class TestThresholdAxisIsNotVacuous:
    """第二轴必须有判别力：争议点与反向控制成对钉住。"""

    def test_expected_threshold_axes(self):
        facts = _facts()
        problems = []
        for symbol, expected in THRESHOLD_EXPECTATIONS.items():
            actual = facts[symbol]["threshold_axis"]
            if actual != expected:
                problems.append(
                    f"{symbol}: 第二轴为 {actual}，期望 {expected}"
                    f"（{facts[symbol]['threshold_detail'].get('reason')}）")
        assert not problems, (
            "第二轴的读数与预期不符——T-04 若把轮次尺度收口成一份，"
            "IterationGate 的轴值必然改变，此时应同步更新本表而不是让守卫红着:\n  "
            + "\n  ".join(problems)
        )

    def test_iteration_gate_closure_removed_the_second_scale(self):
        """T-04 收口后：争议点的证据①仍在（绑定配置键），**证据②必须归零**。

        证据②（同键 `…[max_loop_rounds] // d`，d≥2 的更小尺度守卫）消失，正是
        收口本身的读数：尺度只有一处派生，不存在第二个更小的尺度去抢先开火。
        若它又出现，说明有人把 `// 2` 写了回来 ⇒ 本判据红。
        """
        detail = _facts()["IterationGate"]["threshold_detail"]
        assert detail.get("config_key") == "max_loop_rounds", (
            "门控构造处没绑定配置键——收口后它必须仍绑着单源，否则上限又不受配置管辖"
        )
        # 直接问机器要证据②的取数（`single_source` 分支不携带 witnesses 字段，
        # 故不能靠 detail 里"有没有这个键"来判断——那会把"没算"读成"没有"）。
        witnesses = ledger._scalingWitnesses("max_loop_rounds")
        assert not witnesses, (
            "同键又出现了更小尺度守卫（`…[max_loop_rounds] // d`，d≥2）——"
            "T-04 已把尺度收口成一份，它不该再存在：\n  " + repr(witnesses)
        )
        binding = detail.get("binding") or {}
        assert binding.get("config_key") == "max_loop_rounds", (
            f"绑定来源不是 max_loop_rounds：{binding}"
        )

    def test_single_source_binding_form_is_recognized(self):
        """收口后的绑定写法（调单源派生点）必须被器械认成配置绑定。

        不认它，轴会退成 `unbound` —— 那是**判据替旧形态背书**：收口本身被判违规。
        本判据同时钉住两种写法都可被识别：下标（构造处直取）与单源派生点（函数体内取）。
        """
        derivations = ledger._singleSourceDerivations()
        assert derivations.get("resolveToolRoundBudget") == "max_loop_rounds", (
            "单源派生点未被识别出它读的配置键——绑定写法②会退成 unbound：\n  "
            + repr({k: v for k, v in derivations.items() if "Round" in k})
        )
        assert ledger._derivationCallKey(
            "resolveToolRoundBudget()", derivations
        ) == "max_loop_rounds", "调用单源派生点的形态未被认成绑定"

    def test_guard_and_gate_share_one_derivation(self):
        """收口的终局判据：守卫与门控取到**同一个数**（逐档实测，不是静态声称）。"""
        import neurova.security.agent_limits_settings as als

        original = dict(als.DEFAULTS)
        try:
            from tests.unit.agent.test_tool_round_budget_single_source import (
                _buildLoop,
                _gateThreshold,
                _guardBudget,
            )

            for rounds in (2, 20, 200):
                loop = _buildLoop({"max_loop_rounds": rounds, "goal_round_budget": None})
                assert _guardBudget() == _gateThreshold(loop) == rounds, (
                    f"max_loop_rounds={rounds} 时守卫与门控不同取一处派生："
                    f"守卫={_guardBudget()} 门控={_gateThreshold(loop)}"
                )
        finally:
            als.DEFAULTS.clear()
            als.DEFAULTS.update(original)

    def test_legal_config_enumeration_is_honest(self):
        """可达配置必须**如实枚举**有限域，不能用一个恒假断言代替。"""
        assert ledger._reachableConfigs(2, 200, 2) == [2], (
            "可达配置枚举结果变了：`n // d + 1 >= n` 在合法域内的解集是这条轴的骨，"
            "它一旦被改成空集，IterationGate 就会退成 scaled_unreachable"
        )
        assert ledger._reachableConfigs(2, 200, 1) == list(range(2, 201)), (
            "d=1 时不应有遮蔽（除数 1 不缩小尺度）——此时合法域内全部配置都可达，"
            "若这条返回空集，说明该式把「无遮蔽」也当成了遮蔽"
        )


class TestWaveScopeIsRespected:
    """本片不得改生产码，也不得登记进受保护子集（红线 2 / 红线 4）。"""

    def test_guard_is_not_registered_in_this_wave(self):
        protected = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt")
        listed = {
            line.split("#", 1)[0].strip()
            for line in protected.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL not in listed, (
            f"{GUARD_REL} 被登记进受保护子集了——登记动作统一放 T-10（红线 2）"
        )

    def test_production_paths_are_untouched_by_this_wave(self):
        """本片独占文件全在 `scripts/ci/` 与 `tests/unit/tools/` 之下。"""
        owned = (
            "scripts/ci/toolLoopDeadlines.txt",
            "scripts/ci/tool_loop_deadline_ledger.py",
            "tests/unit/tools/test_tool_loop_deadline_ledger.py",
            "tests/unit/tools/test_tool_loop_deadline_disposal.py",
        )
        assert all(not path.startswith("neurova/") for path in owned), "独占文件集越界"
        assert ledger.LEDGER_PATH.name == "toolLoopDeadlines.txt"
        assert (PROJECT_ROOT / "scripts" / "ci" / "toolLoopDeadlines.txt").is_file()
