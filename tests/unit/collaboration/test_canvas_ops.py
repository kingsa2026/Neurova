"""
Canvas Op 层测试（TDD 红灯）— Phase 1：Agent 交互式操作画布

设计要点（见方案讨论）：
1. 语义操作而非像素操作：add_node / connect / set_config / layout 等 op
   是画布的唯一写入口（agent 工具与 HTTP 端点共用）。
2. 乐观锁：画布记录带单调递增 version；op 可携带 base_version，
   不匹配抛 CanvasVersionConflict —— 用户实时抢占（手动保存）后，
   agent 的过期 op 被拒绝并重新读取，而不是静默覆盖。
3. 事件直播：每个成功 op 通过 broadcaster 推送 {canvas_id, op, version,
   data, actor} 事件（生产环境走 SessionSyncManager 的 canvas_op 事件）。

注：op 方法为 async，测试用 asyncio.run 运行，避免依赖 pytest-asyncio。
"""

import asyncio
import contextlib
import shutil
import tempfile
from pathlib import Path

import pytest

from neurova.collaboration.canvas_ops import (
    CanvasOpError,
    CanvasOpService,
    CanvasVersionConflict,
    compute_layout,
    get_canvas_op_service,
    reset_canvas_op_service,
)
from neurova.collaboration.canvas_store import CanvasStore


def _run(coro):
    return asyncio.run(coro)


@contextlib.contextmanager
def _tempdir():
    d = tempfile.mkdtemp(prefix="canvas-ops-test-")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class FakeBroadcaster:
    """收集广播事件的假 broadcaster（async callable 协议）"""

    def __init__(self):
        self.events = []

    async def __call__(self, session_id, payload):
        self.events.append((session_id, payload))


@pytest.fixture
def env():
    """store + broadcaster + service 三件套（隔离临时目录）"""
    with _tempdir() as d:
        store = CanvasStore(Path(d))
        broadcaster = FakeBroadcaster()
        service = CanvasOpService(store=store, broadcaster=broadcaster)
        yield {"store": store, "broadcaster": broadcaster, "service": service}


# ═══════════════════════════════════════════════════════════════
# 1. 存储层版本号（乐观锁地基）
# ═══════════════════════════════════════════════════════════════


class TestStoreVersioning:
    def test_create_starts_at_version_1(self, env):
        record = env["store"].create({"name": "t", "nodes": [], "edges": []})
        assert record["version"] == 1

    def test_update_bumps_version(self, env):
        created = env["store"].create({"name": "t", "nodes": [], "edges": []})
        updated = env["store"].update(created["id"], {"name": "t2", "nodes": [], "edges": []})
        assert updated["version"] == 2
        assert env["store"].get(created["id"])["version"] == 2

    def test_update_with_stale_base_version_raises(self, env):
        created = env["store"].create({"name": "t", "nodes": [], "edges": []})
        env["store"].update(created["id"], {"name": "t2", "nodes": [], "edges": []})  # v2
        with pytest.raises(CanvasVersionConflict):
            env["store"].update(
                created["id"], {"name": "t3", "nodes": [], "edges": []}, base_version=1
            )

    def test_update_with_matching_base_version_ok(self, env):
        created = env["store"].create({"name": "t", "nodes": [], "edges": []})
        updated = env["store"].update(
            created["id"], {"name": "t2", "nodes": [], "edges": []}, base_version=1
        )
        assert updated["version"] == 2

    def test_mutate_is_atomic_read_modify_write(self, env):
        created = env["store"].create({"name": "t", "nodes": [], "edges": []})

        def add_node(record):
            record["nodes"].append({"id": "n1"})
            return record

        result = env["store"].mutate(created["id"], add_node)
        assert result["version"] == 2
        assert result["nodes"] == [{"id": "n1"}]

    def test_mutate_missing_canvas_returns_none(self, env):
        assert env["store"].mutate("ghost", lambda r: r) is None

    def test_mutate_stale_base_version_raises_and_no_write(self, env):
        created = env["store"].create({"name": "t", "nodes": [], "edges": []})
        env["store"].update(created["id"], {"name": "t2", "nodes": [], "edges": []})  # v2
        with pytest.raises(CanvasVersionConflict):
            env["store"].mutate(created["id"], lambda r: r, base_version=1)
        # 冲突不得产生写入
        assert env["store"].get(created["id"])["version"] == 2

    def test_mutate_returning_none_aborts_without_version_bump(self, env):
        created = env["store"].create({"name": "t", "nodes": [], "edges": []})
        result = env["store"].mutate(created["id"], lambda r: None)
        # 中止时返回当前记录，版本不变
        assert result["version"] == 1


# ═══════════════════════════════════════════════════════════════
# 2. 创建 / 读取
# ═══════════════════════════════════════════════════════════════


class TestCreateRead:
    def test_create_canvas_returns_record(self, env):
        record = _run(env["service"].create_canvas(name="短剧流水线"))
        assert record["id"]
        assert record["name"] == "短剧流水线"
        assert record["version"] == 1
        assert record["nodes"] == []
        assert record["edges"] == []

    def test_create_canvas_broadcasts_to_session(self, env):
        record = _run(
            env["service"].create_canvas(name="x", session_id="sess_1", actor="agent")
        )
        assert len(env["broadcaster"].events) == 1
        session_id, payload = env["broadcaster"].events[0]
        assert session_id == "sess_1"
        assert payload["op"] == "create"
        assert payload["canvas_id"] == record["id"]
        assert payload["actor"] == "agent"
        assert payload["version"] == 1

    def test_create_without_session_no_broadcast(self, env):
        _run(env["service"].create_canvas(name="x"))
        assert env["broadcaster"].events == []

    def test_read_missing_raises_not_found(self, env):
        with pytest.raises(CanvasOpError) as ei:
            _run(env["service"].read_canvas("ghost"))
        assert ei.value.code == "not_found"


# ═══════════════════════════════════════════════════════════════
# 3. add_node
# ═══════════════════════════════════════════════════════════════


class TestAddNode:
    def _create(self, env, name="t"):
        return _run(env["service"].create_canvas(name=name))

    def test_add_known_node_with_ports_from_registry(self, env):
        canvas = self._create(env)
        node = _run(
            env["service"].add_node(canvas["id"], node_type="builtin:start")
        )
        assert node["type"] == "builtin:start"
        assert node["id"]
        assert node["label"]  # 从注册表补全
        assert isinstance(node["outputs"], list) and node["outputs"]
        assert node["config"] == {} or isinstance(node["config"], dict)
        # 已落盘
        record = env["store"].get(canvas["id"])
        assert record["nodes"][0]["id"] == node["id"]
        assert record["version"] == 2

    def test_add_unknown_node_type_raises_with_candidates(self, env):
        canvas = self._create(env)
        with pytest.raises(CanvasOpError) as ei:
            _run(env["service"].add_node(canvas["id"], node_type="builtin:strat"))
        assert ei.value.code == "unknown_node_type"
        # 错误信息应包含候选建议（模糊匹配 start）
        assert "builtin:start" in str(ei.value)

    def test_add_node_with_config_and_position(self, env):
        canvas = self._create(env)
        node = _run(
            env["service"].add_node(
                canvas["id"],
                node_type="builtin:end",
                config={"k": 1},
                position={"x": 500, "y": 300},
                label="自定义标签",
            )
        )
        assert node["config"] == {"k": 1}
        assert node["position"] == {"x": 500, "y": 300}
        assert node["label"] == "自定义标签"

    def test_add_node_auto_position_advances(self, env):
        canvas = self._create(env)
        n1 = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        n2 = _run(env["service"].add_node(canvas["id"], node_type="builtin:end"))
        # 自动布局：第二个节点不得与第一个重叠
        assert (n1["position"]["x"], n1["position"]["y"]) != (
            n2["position"]["x"],
            n2["position"]["y"],
        )

    def test_add_node_broadcasts_op_event(self, env):
        canvas = self._create(env, name="bc")
        env["broadcaster"].events.clear()
        node = _run(
            env["service"].add_node(
                canvas["id"], node_type="builtin:start", session_id="s1", actor="agent"
            )
        )
        assert len(env["broadcaster"].events) == 1
        _, payload = env["broadcaster"].events[0]
        assert payload["op"] == "add_node"
        assert payload["canvas_id"] == canvas["id"]
        assert payload["version"] == 2
        assert payload["data"]["node"]["id"] == node["id"]

    def test_add_node_missing_canvas_raises(self, env):
        with pytest.raises(CanvasOpError) as ei:
            _run(env["service"].add_node("ghost", node_type="builtin:start"))
        assert ei.value.code == "not_found"


# ═══════════════════════════════════════════════════════════════
# 4. connect
# ═══════════════════════════════════════════════════════════════


class TestConnect:
    def _canvas_with_two_nodes(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        n1 = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        n2 = _run(env["service"].add_node(canvas["id"], node_type="builtin:end"))
        return canvas, n1, n2

    def test_connect_two_nodes(self, env):
        canvas, n1, n2 = self._canvas_with_two_nodes(env)
        edge = _run(
            env["service"].connect(
                canvas["id"], source_node=n1["id"], target_node=n2["id"]
            )
        )
        assert edge["source"]["nodeId"] == n1["id"]
        assert edge["target"]["nodeId"] == n2["id"]
        record = env["store"].get(canvas["id"])
        assert len(record["edges"]) == 1

    def test_connect_unknown_node_raises(self, env):
        canvas, n1, _ = self._canvas_with_two_nodes(env)
        with pytest.raises(CanvasOpError) as ei:
            _run(
                env["service"].connect(
                    canvas["id"], source_node=n1["id"], target_node="ghost"
                )
            )
        assert ei.value.code == "unknown_node"

    def test_duplicate_edge_raises(self, env):
        canvas, n1, n2 = self._canvas_with_two_nodes(env)
        _run(env["service"].connect(canvas["id"], source_node=n1["id"], target_node=n2["id"]))
        with pytest.raises(CanvasOpError) as ei:
            _run(
                env["service"].connect(
                    canvas["id"], source_node=n1["id"], target_node=n2["id"]
                )
            )
        assert ei.value.code == "duplicate_edge"

    def test_connect_invalid_port_raises(self, env):
        canvas, n1, n2 = self._canvas_with_two_nodes(env)
        with pytest.raises(CanvasOpError) as ei:
            _run(
                env["service"].connect(
                    canvas["id"],
                    source_node=n1["id"],
                    source_port="no_such_port",
                    target_node=n2["id"],
                )
            )
        assert ei.value.code == "unknown_port"

    def test_connect_broadcasts(self, env):
        canvas, n1, n2 = self._canvas_with_two_nodes(env)
        env["broadcaster"].events.clear()
        _run(
            env["service"].connect(
                canvas["id"], source_node=n1["id"], target_node=n2["id"], session_id="s"
            )
        )
        _, payload = env["broadcaster"].events[0]
        assert payload["op"] == "connect"
        assert payload["data"]["edge"]["source"]["nodeId"] == n1["id"]


# ═══════════════════════════════════════════════════════════════
# 5. set_config / move_node / remove
# ═══════════════════════════════════════════════════════════════


class TestConfigAndRemove:
    def test_set_config_merges_values(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        node = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        updated = _run(
            env["service"].set_config(canvas["id"], node["id"], {"prompt": "hi"})
        )
        assert updated["config"]["prompt"] == "hi"
        # 二次合并而非覆盖
        updated2 = _run(
            env["service"].set_config(canvas["id"], node["id"], {"temp": 0.7})
        )
        assert updated2["config"] == {"prompt": "hi", "temp": 0.7}

    def test_set_config_unknown_node_raises(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        with pytest.raises(CanvasOpError) as ei:
            _run(env["service"].set_config(canvas["id"], "ghost", {"a": 1}))
        assert ei.value.code == "unknown_node"

    def test_move_node(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        node = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        moved = _run(env["service"].move_node(canvas["id"], node["id"], 800, 600))
        assert moved["position"] == {"x": 800, "y": 600}

    def test_remove_node_cascades_edges(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        n1 = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        n2 = _run(env["service"].add_node(canvas["id"], node_type="builtin:end"))
        _run(env["service"].connect(canvas["id"], source_node=n1["id"], target_node=n2["id"]))
        result = _run(env["service"].remove_node(canvas["id"], n1["id"]))
        assert result["removed_edges"] == 1
        record = env["store"].get(canvas["id"])
        assert [n["id"] for n in record["nodes"]] == [n2["id"]]
        assert record["edges"] == []

    def test_remove_edge(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        n1 = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        n2 = _run(env["service"].add_node(canvas["id"], node_type="builtin:end"))
        edge = _run(
            env["service"].connect(canvas["id"], source_node=n1["id"], target_node=n2["id"])
        )
        _run(env["service"].remove_edge(canvas["id"], edge["id"]))
        assert env["store"].get(canvas["id"])["edges"] == []

    def test_remove_unknown_edge_raises(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        with pytest.raises(CanvasOpError) as ei:
            _run(env["service"].remove_edge(canvas["id"], "ghost"))
        assert ei.value.code == "unknown_edge"


# ═══════════════════════════════════════════════════════════════
# 6. 乐观锁：实时抢占语义
# ═══════════════════════════════════════════════════════════════


class TestOptimisticLocking:
    def test_op_with_stale_base_version_conflicts(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))  # v1
        _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))  # v2
        with pytest.raises(CanvasVersionConflict):
            _run(
                env["service"].add_node(
                    canvas["id"], node_type="builtin:end", base_version=1
                )
            )

    def test_op_with_current_base_version_succeeds(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))  # v1
        node = _run(
            env["service"].add_node(
                canvas["id"], node_type="builtin:start", base_version=1
            )
        )
        assert node["id"]
        assert env["store"].get(canvas["id"])["version"] == 2

    def test_user_save_then_agent_op_conflicts_then_reread(self, env):
        """模拟实时抢占全流程：
        agent 读到 v1 → 用户手动保存(v2) → agent 基于 v1 的 op 冲突 →
        agent 重读拿到 v2 与新节点 → 基于 v2 重试成功。
        """
        canvas = _run(env["service"].create_canvas(name="t"))
        agent_view = _run(env["service"].read_canvas(canvas["id"]))
        assert agent_view["version"] == 1

        # 用户抢占：直接经 store 保存（模拟 PUT /canvas）
        user_snap = dict(agent_view)
        user_snap["nodes"] = agent_view["nodes"] + [
            {"id": "user_n", "type": "builtin:end", "position": {"x": 0, "y": 0}, "config": {}}
        ]
        env["store"].update(canvas["id"], user_snap)  # v2

        with pytest.raises(CanvasVersionConflict):
            _run(
                env["service"].add_node(
                    canvas["id"], node_type="builtin:start", base_version=agent_view["version"]
                )
            )

        fresh = _run(env["service"].read_canvas(canvas["id"]))
        assert fresh["version"] == 2
        assert any(n["id"] == "user_n" for n in fresh["nodes"])

        node = _run(
            env["service"].add_node(
                canvas["id"], node_type="builtin:start", base_version=fresh["version"]
            )
        )
        assert node["id"]
        final = env["store"].get(canvas["id"])
        assert final["version"] == 3
        assert len(final["nodes"]) == 2


# ═══════════════════════════════════════════════════════════════
# 7. 自动布局
# ═══════════════════════════════════════════════════════════════


class TestLayout:
    def test_chain_layout_left_to_right(self):
        nodes = [
            {"id": "a", "position": {"x": 0, "y": 0}},
            {"id": "b", "position": {"x": 0, "y": 0}},
            {"id": "c", "position": {"x": 0, "y": 0}},
        ]
        edges = [
            {"source": {"nodeId": "a"}, "target": {"nodeId": "b"}},
            {"source": {"nodeId": "b"}, "target": {"nodeId": "c"}},
        ]
        pos = compute_layout(nodes, edges)
        assert pos["a"]["x"] < pos["b"]["x"] < pos["c"]["x"]

    def test_diamond_layout_same_layer_aligned(self):
        nodes = [{"id": i, "position": {"x": 0, "y": 0}} for i in "abcd"]
        edges = [
            {"source": {"nodeId": "a"}, "target": {"nodeId": "b"}},
            {"source": {"nodeId": "a"}, "target": {"nodeId": "c"}},
            {"source": {"nodeId": "b"}, "target": {"nodeId": "d"}},
            {"source": {"nodeId": "c"}, "target": {"nodeId": "d"}},
        ]
        pos = compute_layout(nodes, edges)
        # b、c 同层：x 相同、y 不同
        assert pos["b"]["x"] == pos["c"]["x"]
        assert pos["b"]["y"] != pos["c"]["y"]

    def test_cycle_does_not_hang(self):
        nodes = [{"id": "a", "position": {"x": 0, "y": 0}}, {"id": "b", "position": {"x": 0, "y": 0}}]
        edges = [
            {"source": {"nodeId": "a"}, "target": {"nodeId": "b"}},
            {"source": {"nodeId": "b"}, "target": {"nodeId": "a"}},
        ]
        pos = compute_layout(nodes, edges)
        assert set(pos) == {"a", "b"}

    def test_apply_layout_op_persists_and_broadcasts(self, env):
        canvas = _run(env["service"].create_canvas(name="t"))
        n1 = _run(env["service"].add_node(canvas["id"], node_type="builtin:start"))
        n2 = _run(env["service"].add_node(canvas["id"], node_type="builtin:end"))
        _run(env["service"].connect(canvas["id"], source_node=n1["id"], target_node=n2["id"]))
        env["broadcaster"].events.clear()

        positions = _run(
            env["service"].apply_layout(canvas["id"], session_id="s")
        )
        assert positions[n1["id"]]["x"] < positions[n2["id"]]["x"]
        record = env["store"].get(canvas["id"])
        by_id = {n["id"]: n for n in record["nodes"]}
        assert by_id[n1["id"]]["position"] == positions[n1["id"]]
        _, payload = env["broadcaster"].events[0]
        assert payload["op"] == "layout"


# ═══════════════════════════════════════════════════════════════
# 8. 单例生命周期
# ═══════════════════════════════════════════════════════════════


class TestSingleton:
    def test_singleton_identity_and_reset(self):
        reset_canvas_op_service()
        first = get_canvas_op_service()
        assert first is get_canvas_op_service()
        reset_canvas_op_service()
        assert first is not get_canvas_op_service()
        reset_canvas_op_service()
