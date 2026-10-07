# -*- coding: utf-8 -*-
"""B1（P3-11 拍板）：429 等待必须有**总墙钟预算**，且旋钮四处同现（单一事实源）。

拍板原话：「对比之前修过的 429：重试 10 次、每次间隔 20 秒」——即与 P2-8 让位闸同口径
（≤10 次、单次 ≤20s、总 ≤200s）。

复算现状（2026-10-08，实测而非引用台账）：`multi_model_client.py:1423-1455` 读到的策略是
max_retries=10、interval=**10s**、wait_cap=120s、max_switches=5；两个睡眠点是 `:737`（非流式）
与 `:1180`（流式，`min(retry_after, cap)`）。全文件 grep 不到任何 deadline/总预算判据，
而流式主循环 `:1005` 是 `while True` + 每次换模型把 `retry_no` 归零重来
（`:1176` `fail_count = 0`）——最坏 10×120s × 5 模型 ≈ **2 小时**，用户端只是一直转圈。

为什么"封顶单次"不够：`wait_cap` 只管一发等多久，管不到"一共等几发、跨几个模型"。
所以本批加的是**总预算**（`wait_budget`，默认 200s，含全部重试与全部模型切换），
预算耗尽即诚实失败/换模型，绝不静默续等。

旋钮是单一事实源链条，新增一格必须**四处同现**，否则就是"后端能配、前端看不见、
运行时读不到"的三截断点（AGENTS §2 功能与升级改造基线）：
`security/llm_retry_settings.py` DEFAULTS（唯一出处）→ env 覆盖 →
`api/endpoints/governance.py` 的 PUT 模型（管理面读写）→
`NeurUI/src/api/modules/settings.ts` + `SettingPage.vue`（用户可见面）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from neurova.llm.multi_model_client import _get_429_retry_config

REPO_ROOT = Path(__file__).resolve().parents[3]

RULING_RETRIES = 10
RULING_INTERVAL = 20.0
RULING_BUDGET = 200.0


def testPolicyDefaultsMatchTheRuling():
    """拍板值必须由单源 DEFAULTS 给出（不是调用点手工传参）。"""
    cfg = _get_429_retry_config()
    assert cfg["max_retries"] == RULING_RETRIES, f"max_retries={cfg['max_retries']}"
    assert cfg["interval"] == RULING_INTERVAL, (
        f"interval={cfg['interval']}，拍板是每次 20s（现值 10s 与让位闸不同口径）"
    )
    assert cfg["wait_budget"] == RULING_BUDGET, (
        f"缺 `wait_budget`（现值 {cfg.get('wait_budget')!r}）——总墙钟预算这一格根本不存在"
    )


def testBudgetIsEnvOverridable(monkeypatch):
    """env 显式值优先（与其余三格同一口径，不另造第二套开关）。"""
    monkeypatch.setenv("NEUROVA_LLM_429_WAIT_BUDGET", "5")
    cfg = _get_429_retry_config()
    assert cfg["wait_budget"] == 5.0


def testBudgetKnobExistsInSingleSource():
    """`wait_budget` 必须在 DEFAULTS 里（唯一出处），而不是硬编码在客户端。"""
    src = (REPO_ROOT / "neurova" / "security" / "llm_retry_settings.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    defaultsNode = None
    for n in ast.walk(tree):
        # DEFAULTS 声明带类型标注（`DEFAULTS: Dict[str, Any] = {...}`）→ AnnAssign
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "DEFAULTS":
            defaultsNode = n.value
        elif isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DEFAULTS":
            defaultsNode = n.value
    assert defaultsNode is not None, "找不到 DEFAULTS 声明，判据落点已失效"
    keys = {ast.unparse(k) for k in defaultsNode.keys}
    assert '"wait_budget"' in keys or "'wait_budget'" in keys, (
        f"DEFAULTS 只有 {sorted(keys)}——预算无处可配，只能散落在调用点"
    )


def testAdminReadWriteSurfaceExposesTheBudget():
    """治理面 PUT 模型必须收 `wait_budget`，否则管理页写了也存不下。"""
    src = (REPO_ROOT / "neurova" / "api" / "endpoints" / "governance.py").read_text(
        encoding="utf-8"
    )
    assert "wait_budget" in src, (
        "governance.py 的 LlmRetrySettingsUpdate 不认 wait_budget——"
        "该格会成为「只在代码里存在、无人能配」的孤儿参数"
    )


def testFrontendSurfaceExposesTheBudget():
    """用户可见面必须有这一格（后端可配 ≠ 用户能使）。"""
    apiSrc = (REPO_ROOT / "NeurUI" / "src" / "api" / "modules" / "settings.ts").read_text(
        encoding="utf-8"
    )
    pageSrc = (REPO_ROOT / "NeurUI" / "src" / "pages" / "SettingPage.vue").read_text(
        encoding="utf-8"
    )
    assert "wait_budget" in apiSrc, "settings.ts 的 LlmRetrySettings 类型缺 wait_budget"
    assert "wait_budget" in pageSrc, "SettingPage.vue 没有该旋钮 → 前端永远看不到预算"


# ── 行为判据：预算真的封顶得住，而且**跨模型切换共享** ──
# 复用 test_chat_stream_429_retry 的脚本化夹具（同 tests/unit/llm 套件既有口径：
# `_sleep_for_retry` 是显式留出的桩注入点，记录每次准备等多久）
from tests.unit.llm.test_chat_stream_429_retry import (  # noqa: E402
    RL,
    _ScriptedStream,
    _make_mmc,
    _split,
    _stream_client,
    collect,
)


@pytest.mark.asyncio
async def testBudgetSpansModelSwitches(monkeypatch):
    """核心一格：次数上限调高后，**预算**必须成为真正的上界。

    构造：`max_retries=50`（远高于预算允许的 10 发）+ 两个候选模型都恒 429。
    期望：整条流累计等待 ≤ 200s——即第一个模型把预算用完之后，换到第二个模型
    **不再新增等待**。原形态每个候选各带一份 10×interval 预算，5 个候选最坏 2 小时，
    这条判据在改前会拿到远超 200s 的累计值。
    """
    monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "50")
    monkeypatch.setenv("NEUROVA_LLM_MAX_SWITCHES", "5")

    innerA = _ScriptedStream([RL()] * 40)
    innerB = _ScriptedStream([RL()] * 40)
    clientA = _stream_client(innerA, "model-a")
    clientB = _stream_client(innerB, "model-b")
    mmc = _make_mmc(clientA, failover_chain=[clientB])

    statuses, errors, chunks = _split(
        await collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))
    )

    budget = _get_429_retry_config()["wait_budget"]
    assert sum(mmc._sleeps) <= budget, (
        f"累计等待 {sum(mmc._sleeps)}s 越过预算 {budget}s——预算没跨切换共享"
    )
    assert errors, "预算耗尽后必须给出诚实终态（错误信封），不能无声收流"
