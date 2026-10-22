"""装配后路由表的冲突与死壳判据（本仓唯一取数口径：`tests/route_table.py`）。

2026-10-22 整改（§6-401 批 J）。这个档原来有 5 格，其中三格**只 print 不断言**：

- `test_channel_route_registration` 用 `for r in app.routes: if hasattr(r, "path")`
  取数——现行 FastAPI 把 `include_router` 落成惰性包装 `_IncludedRouter`，那一形在装配后的
  app 上实测只取到 **7** 条（同一份结果经口径单源取到 877 条），所以它取到的"路由列表"
  根本不含叶子路径；两个布尔只 print，从不 assert。它自己的注释还写着冲突主体
  （`endpoints.channel`，`/v1/channels` 假桥）已于 2026-09-13 删除——**冲突不复存在，
  而判据也从没咬过**。现改为咬两件事：那只死壳不得复活 ＋ 现存挂载点必须真在表上。
- `test_actual_registration_simulation` 同样只 print。它想证的性质（挂载前缀与模块
  自述前缀叠加出重复段）其实**今天真有两条命中**：`/api/v1/tasks/tasks/{task_id}`
  与 `/api/v1/tasks/tasks/{task_id}/move`（`endpoints/tasks_api.py:10-11` 自己就这么
  文档化的）。改成只降不升的棘轮把它们点名列册：新增一条双前缀落点即红。
  为什么不一并修 `tasks/tasks`：那是对外地址，改了要连前端调用一起动，属另一张票。
- `test_frontend_api_coverage_analysis` 拿硬编码的 `backend_count = 75` 去除以前端模块数
  算"覆盖率"并 print（现算挂载路径是 877 条，那个 75 是凭空的），`return coverage`
  无人接收——**没有断言的读数不计入门禁意义**，比 skip 更会骗人（通过数里混着空转）。
  本格删除；要做"前端调用是否都打得到后端"这条真判据，得另批按调用面逐条对表，
  不在这里用两个臆造数字占位。

保留的两格（原本就咬得住）：`test_context_route_registration` 与
`test_deprecated_market_shells_are_gone`。
"""

import importlib
import importlib.util

import pytest
from fastapi import FastAPI

from tests.route_table import registeredPaths


def create_test_app():
    return FastAPI()


def _mountedPaths(app) -> set:
    return set(registeredPaths(app))


def test_channelDeadShellStaysGone_and_channelsMountsWhereTheTableSays():
    """冲突主体（`endpoints.channel` 假桥）不得复活；现存 channels 面按表内前缀挂。

    原格断的是 `/api/v1/channels` 与 `/api/v1/channels/channels` 相冲——那两个地址今天
    都不存在（表里给 `endpoints.channels` 的前缀是 `/v1/channel-adapters`），
    而它用朴素口径连一条叶子路径都没取到，只 print 了两个布尔。
    """
    assert importlib.util.find_spec("neurova.api.endpoints.channel") is None, (
        "`neurova.api.endpoints.channel` 又出现了：2026-09-13 死壳清理把它当假桥删了，"
        "复活即重新造出与 channels 相撞的前缀"
    )
    from neurova.api.endpoints import channels

    app = create_test_app()
    app.include_router(channels.router, prefix="/api/v1/channel-adapters", tags=["Channel Adapters"])
    paths = _mountedPaths(app)
    assert paths, "channels 模块挂上去却一条路径都没有——那才是真断点"
    assert not any(p.startswith("/api/v1/channels/channels") for p in paths), (
        f"双前缀落点又出现：{[p for p in paths if p.startswith('/api/v1/channels/channels')]}——"
        "挂载前缀与模块自述前缀叠加是这条链当年的事故形态"
    )


def test_context_route_registration():
    """context 面必须真挂在 `/api/v1/context` 下（取数走口径单源）。"""
    app = create_test_app()
    from neurova.api.endpoints import context

    app.include_router(context.router, prefix="/api/v1/context", tags=["context"])
    paths = _mountedPaths(app)
    assert any("/api/v1/context" in p for p in paths), paths


def test_deprecated_market_shells_are_gone():
    """skill_market / skills_market 双套已按 ADR 0013 删除（不再注册到任何前缀）。"""
    for name in ("neurova.api.endpoints.skill_market", "neurova.api.endpoints.skills_market"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


#: 双前缀落点的**已知存量**（2026-10-22 现算，两条都来自 tasks_api 自述的
#: `/v1/tasks` 表内前缀 × 模块 router 自带 `/tasks`；改它们是对外地址变更，另票）。
_KNOWN_DOUBLE_SEGMENT_PATHS = {
    "/api/v1/tasks/tasks/{task_id}",
    "/api/v1/tasks/tasks/{task_id}/move",
}


def test_doubleSegmentMountsAreExactlyTheRegisteredOnes():
    """全仓挂载表里的"重复段"路径必须只多不少地等于在册名单。

    这条取代原来的 `test_actual_registration_simulation`（它只 print 注册组合，从不 assert，
    而且用朴素口径）。判据要的性质是真的：**挂载前缀与模块自述前缀叠加出不必要的重复段**，
    今天确实有两条命中。新增一条即红；把 `tasks/tasks` 收掉时把在册名单一起改小。
    """
    from neurova.api.app import create_app

    paths = _mountedPaths(create_app(enable_memory=False, enable_channels=False))
    doubled = {
        p for p in paths
        if any(seg and seg == nxt for seg, nxt in zip(p.split("/")[2:], p.split("/")[3:]))
    }
    assert doubled == _KNOWN_DOUBLE_SEGMENT_PATHS, (
        f"双前缀落点与在册名单不符——新增 {sorted(doubled - _KNOWN_DOUBLE_SEGMENT_PATHS)}、"
        f"消失 {sorted(_KNOWN_DOUBLE_SEGMENT_PATHS - doubled)}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
