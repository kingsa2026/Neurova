# -*- coding: utf-8 -*-
"""端点接线守卫（Issue #112 后续：未接线断点）。

背景（根因，不是形状）：注册表把**「挂载动作」与「接线完成」当成同一件事**。
`register_endpoint_routers` 只要求模块有 `router` 属性就 `include_router`，
于是三类「看起来接了、实际断着」的形态长期存活：

1. **零路由挂载**——模块级空 `APIRouter()` 被挂到 `/api/evolution`、`/api/rag`，
   落地零条路由。读者在路由表里看到这两个前缀存在，实际请求必 404；
2. **前缀叠层**——挂载前缀与 router 自持前缀同段，实际路径变成
   `/api/coordination/coordination/*`、`/api/neuron/neuron/*`；
3. **双源挂载**——同一个 router 被注册表与 `app.py` 各挂一次（`neuron`），
   同一件事两个写入点。

外加一处**契约断裂**：`cost.ts` 按 `baseURL=/api/v1` 请求 `/api/v1/budgets`、
`/api/v1/cost-rollup`，而后端把两者挂在不带 `v1` 的 `/api` 下 → 必 404。

判据单源在 `scripts/gen_api_inventory.py`（`appMounts` / `mountProblems` /
`unwiredEndpointRouters`），本守卫只做「取数 → 断言 → 反向控制」。

**剩余未接线 router 走棘轮**：已实现但全仓无挂载点的模块（`computer_api`、
`cost_api`、`phase3_api`、`migration_api`、`skill_market`、`skills_market`）
不许静默遗留，逐一登记在 `tests/unit/endpointWiringBaseline.txt`；
新增一个即红——登记不代替修复，但也不许把已知项假装不存在。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

generator = pytest.importorskip("scripts.gen_api_inventory")


class TestMountTableIsWired:
    """三类「挂载了但断着」的形态，一个都不许留在装配后的应用里。"""

    def test_no_mount_carries_zero_routes(self):
        problems = generator.mountProblems(generator.appMounts())
        empty = [p for p in problems if p["kind"] == generator.MOUNT_PROBLEM_EMPTY]
        assert not empty, (
            "存在零路由挂载——挂载动作在、叶子路由零条，请求必 404：\n  "
            + "\n  ".join(f"{p['mountPrefix']}（router 前缀 {p['routerPrefix']!r}）" for p in empty)
        )

    def test_no_mount_repeats_the_router_prefix(self):
        problems = generator.mountProblems(generator.appMounts())
        repeated = [p for p in problems if p["kind"] == generator.MOUNT_PROBLEM_REPEAT]
        assert not repeated, (
            "存在前缀叠层挂载——挂载前缀与 router 自持前缀同段，实际路径多出一段：\n  "
            + "\n  ".join(
                f"{p['mountPrefix']} + {p['routerPrefix']}" for p in repeated
            )
        )

    def test_no_router_is_mounted_twice(self):
        problems = generator.mountProblems(generator.appMounts())
        duplicated = [p for p in problems if p["kind"] == generator.MOUNT_PROBLEM_DUPLICATE]
        assert not duplicated, (
            "同一个 router 被挂载两次——同一件事两个事实源：\n  "
            + "\n  ".join(p["mountPrefix"] for p in duplicated)
        )


class TestFrontContractResolves:
    """前端按 `baseURL=/api/v1` 发的请求必须在装配后的真实路由表里命中。"""

    def test_cost_dashboard_calls_resolve(self):
        gaps = [row for row in generator.unmatchedFrontCalls() if row["module"] == "cost.ts"]
        assert not gaps, (
            "cost.ts 的调用在装配后的路由表里没有对应路由（看板数据全空，且被 catch 吞掉）：\n  "
            + "\n  ".join(f"{row['method']} {row['path']}（{row['verdict']}）" for row in gaps)
        )


class TestUnwiredRoutersAreRatcheted:
    """已实现未接线的 router 逐一登记在基线里，只降不升。"""

    def test_unwired_set_matches_baseline(self):
        baseline = generator.readWiringBaseline()
        current = set(generator.unwiredEndpointRouters())
        added = sorted(current - baseline)
        assert not added, (
            "出现新的未接线 router（模块有真实路由，但全仓无挂载点）：\n  "
            + "\n  ".join(added)
            + "\n修法：接入注册表，或删除该模块；两者都不是时登记进 "
            + generator.WIRING_BASELINE.name
        )
        removed = sorted(baseline - current)
        assert not removed, (
            "基线里的未接线 router 已被修复/删除，请同步下调基线（只降不升）：\n  "
            + "\n  ".join(removed)
        )


class TestDetectorDoesNotRunVacuous:
    """反向控制：判据必须真的能检出问题，也不能把正常挂载当问题。"""

    def test_zero_route_mount_is_detected(self):
        mounts = [("/api/empty", "", 0, 1), ("/api/real", "", 3, 2)]
        kinds = [p["kind"] for p in generator.mountProblems(mounts)]
        assert generator.MOUNT_PROBLEM_EMPTY in kinds, (
            "零路由挂载未被检出——上面那条断言会白通过。"
        )
        assert len(kinds) == 1, f"正常挂载被误判: {kinds}"

    def test_repeated_prefix_mount_is_detected(self):
        mounts = [("/api/coordination", "/coordination", 17, 1), ("/api/v1/agents", "", 11, 2)]
        kinds = [p["kind"] for p in generator.mountProblems(mounts)]
        assert generator.MOUNT_PROBLEM_REPEAT in kinds, (
            "前缀叠层未被检出——上面那条断言会白通过。"
        )
        assert generator.MOUNT_PROBLEM_EMPTY not in kinds, f"非空挂载被误判为零路由: {kinds}"

    def test_duplicate_mount_is_detected(self):
        mounts = [("/api/neuron", "/neuron", 10, 7), ("/api", "/neuron", 10, 7)]
        kinds = [p["kind"] for p in generator.mountProblems(mounts)]
        assert generator.MOUNT_PROBLEM_DUPLICATE in kinds, (
            "重复挂载未被检出——上面那条断言会白通过。"
        )

    def test_unwired_detector_marks_known_orphan_and_clears_known_wired(self):
        unwired = set(generator.unwiredEndpointRouters())
        assert "computer_api" in unwired, (
            "已实现但全仓无挂载点的 computer_api 未被检出——判据认错了接线形态。"
        )
        assert "computer" not in unwired, (
            "已接入注册表的 computer 模块被误报为未接线——那是假阳性，"
            "假阳性比漏报更坏：它会训练人忽略这份清单。"
        )

    def test_baseline_file_lives_in_the_test_root(self):
        path = generator.WIRING_BASELINE
        assert path.is_file(), f"未接线基线缺失: {path}"
        assert io.open(path, encoding="utf-8").read().strip(), "基线不得为空文件"
