"""前置脚手架的有效性守卫（行为形态，不读 pytest 内部）。

晋升判据新增的结构性前置在链首硬否决。`tests/conftest.py` 里那枚 autouse 夹具把它
桩成"齐备"，好让在测"无回滚天数 / roi / 收敛结论 / 经验质量"的既有用例仍走得到自己
那条轴（实测：不桩则 44 格集体走不到断言）。

那枚夹具若被静默摘掉，坏处是 44 格无主红墙。这一格把它换成**一格**明确命名的红：
脚手架在 ⇒ 阶段 1 的证据齐备即可晋升；脚手架没了 ⇒ 这里红，而红话直接说清去哪修。

**两条已实测走不通的形态，别再试**（都在本文件/夹具的注释里留过痕）：
1. 把"接缝还在吗"写成会话级 autouse 夹具 ⇒ 断言失败时整场每条用例都 ERROR
   （在摘掉接缝的工作树里实测 **228 条同句错误**），刷屏只是换了报错文字；
2. 把 `hasattr(controllerModule, "automationPrerequisiteVerdict")` 写成普通用例 ⇒
   **恒真**：夹具那句 `monkeypatch.setattr(..., raising=False)` 本来就会在模块上**造出**
   这个名字，检查者与被检查者是同一只手。
真正的"摘掉实装仍要红"由 `test_automationPrerequisiteGate.py` 的
`TestControllerCarriesThePrerequisiteCell` 两格拿到（同名夹具遮蔽 ⇒ 测未桩掉的真实否决）。
在摘掉接缝的工作树里实测（选择集 = `tests/unit/evolution/rsi` + 两枚治理端点文件）：
**5 failed / 223 passed**，其中本批的两格红正是 `test_firstAutonomyPhaseIsVetoedAndNamed`
与 `test_cellIsWhatBlocksNotSomethingElse`，另 3 格是 main 预存红（端点 401 那一簇）；
没有错误墙。
"""

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController


def test_scaffoldKeepsOtherEvidenceAxesReachable():
    verdict = RSIDeploymentController(initial_phase=1).evaluate_phase_transition({
        "days_without_rollback": 8, "roi": None, "convergence_status": "insufficient_data",
    })

    assert bool(verdict) is True, (
        f"前置脚手架失效：{verdict.state} / {verdict.reason}\n"
        "→ 修 `tests/conftest.py::_automationPrerequisitesHeldForEvidenceAxes`，"
        "而不是把晋升判据调松")
