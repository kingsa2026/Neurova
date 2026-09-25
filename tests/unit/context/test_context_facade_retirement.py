# -*- coding: utf-8 -*-
"""B6-10 批次 E：门面层退场裁定（Issue #90 §5 死线清单 / 工单 B6-10）。

## 台账里留的两条自述

`scripts/ci/contextDeadlines.txt` 对 `ContextFacade` 与 `build_system_prompt`
两条的处置一直是「待处置」，依据写的是：

> **两级同时死，只删一级无效**

这句话点出了形态（传递不可达），但没有回答"该往哪边处置"。本批把裁定做完。

## 裁定：门面层退场，`build_system_prompt` 保留为公开面

先分清两件事——它们是**两级**，但**结局不同**：

**第一级 `ContextFacade`：退场。** 它是编排器的**第二份装配路径**：

- 全仓零非测试消费者（`grep -rn 'context_facade|ContextFacade' neurova/` 只命中
  它自己的定义文件与编排器里一句注释）；
- 它的工厂 `get_context_facade()` 零消费（判据 `ContextFacade` 报 `self_loop`）；
- 它**已经坏了且没人发现** —— `build_context()` 与 `build_system_prompt()` 都把
  同步方法当协程 await：

  ```
  $ python -c "... facade.build_system_prompt()"
  ERROR - 系统提示构建失败: object str can't be used in 'await' expression
  facade.build_system_prompt() -> ''      ← 恒空串（异常被 except 吞成空返回）

  orchestrator.build_system_prompt 是协程函数: False
  sync 直调 build_system_prompt 首行: 'SOUL\\n\\n\\n## 工具使用规则…'   ← 真面是同步的
  ```

  也就是说：这条"第二份装配路径"自诞生起就没有一次能跑通，而它**永远返回空**
  这件事没有任何读数——正是修复教义第 2 条点名的形态（报错被吞成看起来正常的
  空值）。

**第二级 `build_system_prompt`：保留，但判据如实报零消费。** 它不是这个门面的一部分，
而是 `ContextOrchestrator` 上的**公开工具方法**。门面是它**唯一**的 `call` 点；
门面一删，判据类由 `self_loop` 转 `no_consumer`（`classify()` 规则 2）——
这是**接线之前**的诚实形态，**不许为它编造消费点**（拿一句"它是公开面"把零消费
说成可达，就是把结论当判据）。

那为什么没被一起删？一条事实差别：**它跑得通，门面那层跑不通**。

```
orchestrator.build_system_prompt 是协程函数: False      ← 同步方法
sync 直调 build_system_prompt 首行: 'SOUL\n\n\n## 工具使用规则…'   ← 完整 prompt
facade.build_system_prompt() -> ''                     ← 被 await 坏掉，异常吞成空串
```

外加三条辅证（都属"测试/文档面"，不能当消费点，但说明它不是废面）：

- `tests/unit/agent/test_agent.py::TestAgentBuildSystemPrompt` 锁的三条腿
  （soul 在 prompt / 行为规则段 / 中文交流段）**只在这条路径上可见** —— 实测
  `build_context` 的 system 行里「行为规则」标题不出现（它把 `behavior_rules`
  逐条铺成独立 system 行，形状不同；规则文本本身两路都在）；
- `neurova/agent/README.md:85` 把它写成公开接口示例；
- 它与 `build_context` 共用三处单源 helper（`_workspace_docs_section` /
  `_skill_catalog_section` / `rules_sections.build_all_sections`），
  `test_rules_sections` / `test_workspace_docs` 的「双路径一致」防漂移断言正是
  靠它才可证伪。

所以裁定是：**删门面（`context_facade.py` 整文件），保工具方法并如实登记其
零生产消费**。台账 `ContextFacade` 行处置改「已删除」；`build_system_prompt` 行
判据类由机器改判 `no_consumer`、处置保持「待处置」——**下一步要么接线、要么按
零生产消费退役，但不能再拿门面当理由删它**（那条理由随门面一起消失了）。

## 本守卫钉什么

1. 门面层在生产侧已退场（模块不可导入、符号判据类为 `absent`）；
2. `build_system_prompt` 仍是编排器上的公开方法且有真实消费点（判据类非 `absent`）；
3. 它守的三条契约腿在**真面**上仍然成立（断言未删，搬到 `build_system_prompt` 直调）；
4. 台账那两条与机器判据咬合（与 `test_context_deadline_disposal.py` 同源取数）：
   门面 `absent`/「已删除」，工具方法 `no_consumer`/「待处置」**如实**。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import context_deadline_ledger as ledger  # noqa: E402

FACADE_MODULE = PROJECT_ROOT / "neurova" / "context" / "context_facade.py"
#: 本批给出终局的符号 → 期望（处置, 判据类）。
DISPOSED_EXPECTATIONS = {
    # 第二份装配路径整文件退场（含 ContextResult / get_context_facade /
    # reset_context_facade 三个只服务它的符号）。
    "ContextFacade": (ledger.DISPOSAL_RETIRED, ledger.JUDGE_ABSENT),
    # 公开工具方法保留为**能跑的**面（判据类由 self_loop 转 no_consumer：
    # 门面是它唯一的 call 点，删门面后生产侧零消费——这是接线之前的如实形态）。
    # 「两级同时死、只删一级无效」这个自述被推翻：它们只是**曾经串在同一条链上**，
    # 判据类相同但结局不同（门面自诞生即坏，本方法跑得通）。处置仍为「待处置」：
    # 零生产消费点这一事实不许被抹掉，下一步是接线或按此退役，不再拿门面当理由。
    "build_system_prompt": (ledger.DISPOSAL_PENDING, ledger.JUDGE_NO_CONSUMER),
}


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestFacadeModuleIsRetired:
    def test_module_is_gone_from_production(self):
        assert not FACADE_MODULE.exists(), (
            "`context/context_facade.py` 仍在仓 —— 它是编排器的第二份装配路径，"
            "零非测试消费者，且 build_context/build_system_prompt 把同步方法当"
            "协程 await（实测恒返回空串、异常被吞）。"
        )

    def test_module_is_not_importable(self):
        with __import__("pytest").raises(ImportError):
            importlib.import_module("neurova.context.context_facade")


class TestToolMethodStaysAsPublicFace:
    """`build_system_prompt` 与门面不是同一件事：它是编排器上的公开工具方法。"""

    def test_orchestrator_still_exposes_it(self):
        from neurova.context.orchestrator import ContextOrchestrator

        assert callable(getattr(ContextOrchestrator, "build_system_prompt", None)), (
            "`build_system_prompt` 被连带删掉了 —— 它不是门面的一部分，"
            "删它会让三处单源 helper（workspace docs / skill catalog / rules "
            "sections）的『双路径一致』约束失去可证伪面。"
        )

    def test_its_contract_legs_hold_on_the_real_face(self, tmp_path):
        """断言未删：原来锁在门面用例里的三条腿，改在真面上钉住。"""
        from neurova.agent_core import Agent

        agent = Agent(workspace_path=str(tmp_path), enable_memory=False)
        prompt = agent.context_orchestrator.build_system_prompt()

        assert agent.soul in prompt, "soul 未进 system prompt（真面第一腿）"
        assert "行为规则" in prompt, "行为规则段不见了（真面第二腿）"
        assert "中文交流" in prompt, "中文交流约束不见了（真面第三腿）"

    def test_deadline_ledger_agrees_it_still_exists(self):
        """判据类不是 absent：符号在生产侧，只是当前零消费点。

        **不为它编造消费点**。「门面在调它」这条理由随门面一起消失了，
        判据随之由 `self_loop` 转 `no_consumer` —— 这是诚实的读数，
        不许用一句"它是公开面"把零消费说成可达（那就是把结论当判据）。
        """
        fact = _facts()["build_system_prompt"]
        assert fact["judge"] != ledger.JUDGE_ABSENT, (
            "判据把 `build_system_prompt` 算成 absent —— 它仍在生产侧，"
            "这条会与上面的可调用性断言互相矛盾。"
        )
        assert fact["judge"] == ledger.JUDGE_NO_CONSUMER, (
            f"判据类为 {fact['judge']} —— 门面退场后它应为 `no_consumer`；"
            "若变成了 `consumed`，说明有人补了消费点（那是下一步的活，"
            "该在同一个提交里连同台账处置一起改），或判据被改坏了。"
        )

    def test_it_runs_through_the_real_call(self, tmp_path):
        """它与门面那条链的**关键差别**：它自己跑得通（同步方法，不 await）。

        门面把它当协程 await → `object str can't be used in 'await' expression`
        被 except 吞成恒空串；直调则拿到完整 prompt。这条差别是本批只删门面、
        不删方法的事实依据，故必须钉住（否则下一轮会因为"都是 self_loop"把它们
        一锅端掉）。
        """
        import inspect

        from neurova.agent_core import Agent
        from neurova.context.orchestrator import ContextOrchestrator

        assert not inspect.iscoroutinefunction(ContextOrchestrator.build_system_prompt), (
            "`build_system_prompt` 变成了协程函数 —— 本守卫依据「它跑得通」保留了它；"
            "形态一变，这个结论要重新论证。"
        )
        agent = Agent(workspace_path=str(tmp_path), enable_memory=False)
        prompt = agent.context_orchestrator.build_system_prompt()
        assert prompt.strip(), (
            "直调返回空串 —— 那它就不是「能跑的工具方法」了，"
            "本批保留它的依据失效（会与门面同处置）。"
        )


class TestDisposalMatchesMachineJudge:
    def test_both_rows_are_settled_and_agree(self):
        facts = _facts()
        problems = []
        for symbol, (disposal, expected_judge) in DISPOSED_EXPECTATIONS.items():
            entry = ledger.readLedger().get(symbol)
            if entry is None:
                problems.append(f"{symbol}: 台账缺该条")
                continue
            if entry["disposal"] != disposal:
                problems.append(
                    f"{symbol}: 台账处置为 {entry['disposal']}，期望 {disposal}")
            fact = facts.get(symbol)
            if fact is None or fact["judge"] != expected_judge:
                actual = fact["judge"] if fact else "缺数"
                problems.append(f"{symbol}: 判据类为 {actual}，期望 {expected_judge}")
        assert not problems, (
            "B6-10 批次 E 的门面裁定与机器判据不咬合：\n  " + "\n  ".join(problems)
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in (
                PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
            ).read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        rel = "tests/unit/context/test_context_facade_retirement.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
            "（B5 收口时正是这个形态：文件在仓、单跑全绿、清单里没有）。"
        )
