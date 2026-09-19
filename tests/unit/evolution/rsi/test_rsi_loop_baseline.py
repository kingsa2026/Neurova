"""RSI 进化闭环基线（工单 001）。

本文件断言的是修复后的目标态，期望值来自 2026-09-19 闭环审计的实测数据（独立真相源），
不由被测代码反算。审计实测基线（改动前）：
- 默认 rsi_phase=0 连跑 60 轮 → phase 停在 1、applied_count 累计 0。
- rsi_phase=2 连跑 → 第 20 轮 should_continue() 翻 False，本进程内 RSI 永久自停。

工单 004/007/008 落地后两条基线均已转绿；其中基线 A 的前提在 008 执行期被证伪并改写
（见对应用例 docstring）—— 卡口该是"能被满足的证据"，不是"能在一个进程里跑出来的天数"。
"""


def test_rsi_promotes_past_manual_once_the_rollback_free_window_is_met(rsi_probe_factory):
    """卡口必须是"能被满足的证据"，不是"结构上取不到的读数"（工单 001 基线 A，前提已修正）。

    原写作"默认 rsi_phase=0 连跑 60 轮 ⇒ phase>1 或 applied>0"。004/008 之后
    这条按字面已不成立，而且**不该**成立：1→2 的判据是"装配以来 7 天无回滚"，
    同一进程跑 60 轮不可能攒出 7 天 —— 把它跑绿等于把卡口悄悄拆掉。

    真正的死锁是**该读数在结构上永远取不到**：无回滚历史时
    `_compute_days_without_rollback()` 返回 0.0（rsi/orchestrator.py:176-184 旧实现），
    于是"要回滚先应用、要应用先晋升、要晋升先回滚"三者互锁。
    工单 004 把起算点改为 RSI 装配时刻后，"装了很久且没回滚"成为可满足条件。
    本用例因此把 `installed_at` 诚实回填到 8 天前 —— 这等价于"这套 RSI 已装配 8 天"，
    走的是公开属性，不是 `conftest` 规则 1 禁止的私赋阶段。
    不回填时卡口仍须生效，由 `test_fresh_install_still_gated_on_age` 反向锁住。
    """
    from datetime import datetime, timedelta, timezone

    probe = rsi_probe_factory(rsi_phase=0)
    probe.orchestrator.rollback_manager.installed_at = (
        datetime.now(timezone.utc) - timedelta(days=8)
    )

    probe.run(4)

    assert probe.phase > 1, (
        f"无回滚窗口已满足却仍未走到可自动执行低风险的阶段：phase={probe.phase} "
        f"最后判据={probe.results[-1]['phase_verdict']}"
    )
    assert probe.applied_total > 0, "晋升到 phase 2 后参数必须真的被应用，否则第二臂仍断"


def test_fresh_install_still_gated_on_age(rsi_probe_factory):
    """反向一例：装配时刻新鲜时卡口必须仍然拦得住，且要说得出拦在哪。

    没有这条，上一条可以靠"把天数门槛改成 0"蒙绿 —— 判据就又不证伪了。
    """
    probe = rsi_probe_factory(rsi_phase=1).run(4)

    verdict = probe.results[-1]["phase_verdict"]
    assert probe.phase == 1
    assert verdict["state"] == "failed", verdict
    assert "days_without_rollback" in verdict["reason"], verdict


def test_convergence_must_not_permanently_stop_evolution(rsi_probe_factory):
    """RSI 一旦判收敛，不得在本进程内永久停止迭代（工单 001 基线 B，前提已修正）。

    **前提修正说明**（工单 007/008 执行期证伪了本用例最初的假设）：
    原写作 `not (status == "converged" and 全部 gain == 0)`，
    把"应用了但测不出差异"当成必然的谎报收敛。007 把证据计数显式化后推得：
    候选要求参数非 None，而"参数被真实系统暴露"正是评测用例有证据的同一条件 ——
    所以"全族失明 ⇒ 无候选 ⇒ 不应用 ⇒ 不喂数"，
    **applied-but-blind 不可构造**。真实停机路径是：
    唯一梯度的参数走到 setpoint → 一串**有证据的零增益** → `converged` 是合法结论
    → 而 `post_chat_pipeline.py:2729` 把 `should_continue()==False` 读成"本进程内永不再跑"。

    因此本用例改锁那个真正的危害：收敛可以是结论，不能是终点。
    零证据不得被判收敛这一条由
    `tests/unit/evolution/rsi/test_convergence_evidence.py` 在分析器接缝上覆盖。
    """
    probe = rsi_probe_factory(rsi_phase=2)

    probe.run(probe.orchestrator.convergence_analyzer.window_size + 5)
    status = probe.convergence_status

    assert status == "converged", (
        f"前置失效：探针场景本应走到有证据的收敛，实际 {status} / {probe.gains[:5]}")
    assert probe.orchestrator.iteration_cadence().mode == "backoff", (
        "收敛后必须转入降频巡检，而不是永久跳过")

    # 收敛之后仍要在后续窗口里被重新量一次：证明"停"是降频不是终止
    assert probe.orchestrator.should_continue() is False, (
        "should_continue 的既有契约（收敛即 False）不得改动 —— "
        "真实棘轮收益耗尽即停，见 test_rsi_ratchet_effectiveness.py:187")


def test_probe_skill_stub_straddles_the_two_identity_domains(fake_skill):
    """探针自带的技能桩必须真的踩在双键域缺陷上，否则工单 013/014 拿它验不出东西。

    现状两域分立：注册表按 ``skill.name`` 建键（skill_system.py:505），
    进化侧身份按 skill_id 优先解析（skills/skill_contract.py:86-91）。
    旧桩令 id==name（tests/unit/skills/test_improvement_persistence.py:47-52），
    于是 8 处按 identity 取技能的调用点永远命中，缺陷被洗绿。
    """
    from neurova.skills.skill_contract import resolve_skill_identity

    identity = resolve_skill_identity(fake_skill)

    assert identity == fake_skill.skill_id, f"身份解析应取 skill_id，实际 {identity!r}"
    assert identity != fake_skill.name, "探针桩必须 id != name，否则与旧假注册表同病"
    assert fake_skill.name not in identity, "两域不得有任何前缀包含关系（避免碰巧命中）"
