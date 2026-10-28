# -*- coding: utf-8 -*-
"""单元层不得为「TTL 释放后的后台预热」付真权重的账（§6-201 登记的跑测环境缺陷）。

实状（本批现算，非记忆）：`test_tts_lazy_release.py::test_ttl_release_switches_to_light_engine`
主树单格 **19.32s**、HEAD 仓外干净 worktree 单格 **31s**。多出来的不是断言，是
`_ensure_preheat` 在后台构造了**生产那个** `MOSSNanTTS`——夹具往 `_engines` 里塞假引擎
只挡得住「命中缓存」那条支路，而 TTL 释放恰好把链顶从 `_engines` 丢掉，预热因此走
**构造**支路，那里读的是 `neurova.tts.manager` 的模块级名字。
`models/**/*.data`（670MB 权重）是未跟踪件，干净 worktree 里没有 ⇒ 这一格顺路发真
HTTPS 把权重拉下来（`~/.cache/modelscope/.lock` 与落地的两份 `.data` 为凭），撞上全局
`timeout = 30` 的 thread 法即整场不产出汇总行：批 42、批 43 各因此烧掉一轮宽域自证。

契约两格互为反证：预热重建出的链顶必须是假引擎（不许真权重），且必须**真的重建出来**
（不许把预热整条改成 no-op 来糊第一格）。
"""

import pytest

from neurova.tts.moss_nano import MOSSNanTTS
from tests.unit.tts._fakeEngines import _FakeHeavyEngine


async def _driveReleaseThenPreheat(heavy_manager):
    """走一遍「服务 → TTL 释放 → 轻引擎顶班 → 后台预热重建链顶」，等预热落定。

    「现在几点」必须相对**本进程真实的单调时钟**给：`release_idle_engines` 拿它跟
    `_last_used_monotonic`（`time.monotonic()` 写入）相减判 TTL。写死一个
    `1_000_000` 只在开机不足 11.6 天的机器上「像未来」；Linux CI 的单调时钟从
    开机算起，一旦超过那个数，`now - last` 就是负数，释放条件永不成立——
    而本档报的是「前置不成立：释放没换班到轻引擎」，读的人会去查 TTS 释放逻辑。
    """
    mgr, heavy, light = heavy_manager
    await mgr.synthesize("第一句")
    # TTL 是**相对**比较（`now - _last_used_monotonic >= release_ttl_sec`），故"现在"必须
    # 从这台机器这一轮的真实读数上往后推——写死的 `1_000_000` 在运行时长已过 11.5 天的
    # CI 上是一个**过去**的时刻，差值变负数，释放不发生。
    await mgr.release_idle_engines(
        now_monotonic=(mgr._last_used_monotonic or 0.0) + 120.0)
    assert mgr._engine_name == "edge-tts", "前置不成立：释放没换班到轻引擎"

    await mgr.synthesize("第二句")  # 轻引擎立即服务，同时触发后台预热
    assert mgr._preheat_task is not None, "前置不成立：预热任务没起来，本档无从观察"
    await mgr._preheat_task
    return mgr, heavy, light


@pytest.mark.asyncio
async def test_idleReleasePreheatNeverBuildsTheRealHeavyEngine(heavy_manager):
    """预热重建链顶时构造的必须是假引擎：单元档不得载/下真权重。"""
    mgr, _heavy, _light = await _driveReleaseThenPreheat(heavy_manager)
    realBuilt = [name for name, eng in mgr._engines.items() if isinstance(eng, MOSSNanTTS)]
    assert not realBuilt, (
        f"释放后的预热构造了生产真重引擎 {realBuilt}：这一格因此在载 670MB 权重，"
        "干净 worktree 里还要先发真 HTTPS 下载（全局 timeout=30 被打断即整场无汇总行）")


@pytest.mark.asyncio
async def test_idleReleasePreheatStillRebuildsChainTop(heavy_manager):
    """反空转配对格：预热这条链得真跑通——换回链顶且进缓存的是那只假重引擎。

    没有这格，把 `_ensure_preheat` 改成 no-op 也能让上一格变绿（§2 的空转形态）。
    """
    mgr, _heavy, _light = await _driveReleaseThenPreheat(heavy_manager)
    rebuilt = mgr._engines.get("moss-nano")
    assert isinstance(rebuilt, _FakeHeavyEngine), (
        f"链顶没被预热重建（实得 {type(rebuilt).__name__}）：预热被摘掉了，"
        "上一格的绿就是空的")
    assert rebuilt.is_initialized is True
    assert mgr._engine_name == "moss-nano", "预热成功后应换回链顶（H2-C 方案 C 的闭环）"
