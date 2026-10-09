"""前置脚手架的有效性守卫（行为形态，不读 pytest 内部）。

晋升判据新增的结构性前置在链首硬否决。`tests/conftest.py` 里那枚 autouse 夹具把它
桩成"齐备"，好让在测"无回滚天数 / roi / 收敛结论 / 经验质量"的既有用例仍走得到自己
那条轴（实测：不桩则 44 格集体走不到断言）。

那枚夹具若被静默摘掉，坏处是 44 格无主红墙。这一格把它换成**一格**明确命名的红：
脚手架在 ⇒ 阶段 1 的证据齐备即可晋升；脚手架没了 ⇒ 这里红，而红话直接说清去哪修。
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
