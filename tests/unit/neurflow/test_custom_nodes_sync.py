"""
遗留 A — custom:* 自定义节点接入 registry 同步测试

问题：CustomNodeService.load_into_registry()（重启恢复执行器）全仓无调用方——
进程重启后 custom 节点既不出现在 /nodes，画布运行校验也 400 未注册。

契约：
- canvas_bridge._known_node_types()：加载 custom 节点后，
  画布快照含 custom:* 类型不再抛"未注册节点类型"
- adapters.sync_all(registry)：加载 custom 节点进 registry（/nodes 通道）

TDD：先红后绿。tmp DB 隔离。
"""
import pytest

from neurova.collaboration.neurflow.custom_nodes import (
    CustomNodeService,
    TIER_DECLARATIVE,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    """tmp DB 的 CustomNodeService（storage 隔离；registry 绑全局单例——
    bridge/sync_all 都从 get_node_registry() 读）。"""
    from neurova.collaboration.neurflow.storage import NeurflowStorage
    from neurova.collaboration.neurflow.node_registry import get_node_registry

    storage = NeurflowStorage(db_path=str(tmp_path / "custom.db"))
    nr = get_node_registry()
    nr.ensure_builtin()
    svc = CustomNodeService(storage=storage, registry=nr)
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.custom_nodes._service_instance", svc
    )
    return svc


def _create_custom_node(service, name="greeter"):
    return service.create_node({
        "label": "问候节点",
        "type": name,
        "description": "测试自定义节点",
        "tier": TIER_DECLARATIVE,
        "executor_body": {"template": "你好 {name}"},
    })


class TestCustomNodesSync:
    def test_canvas_bridge_accepts_custom_node(self, service, monkeypatch):
        """重启后 load_into_registry → 画布快照含 custom 类型可通过校验"""
        _create_custom_node(service, "bridge_node")

        # 模拟重启：全局单例指向 tmp service，load_into_registry 从同库恢复执行器
        from neurova.collaboration.neurflow.custom_nodes import get_custom_node_service

        monkeypatch.setattr(
            "neurova.collaboration.neurflow.custom_nodes._service_instance",
            service,
        )
        get_custom_node_service().load_into_registry()

        from neurova.collaboration.canvas_bridge import canvas_to_workflow

        snapshot = {
            "name": "custom-canvas",
            "nodes": [
                {"id": "n1", "type": "custom:bridge_node", "label": "N1",
                 "position": {"x": 0, "y": 0}, "config": {}},
            ],
            "edges": [],
        }
        wf = canvas_to_workflow(snapshot, name="custom-canvas")  # 不应抛 ValueError
        assert wf.nodes[0].type == "custom:bridge_node"

    def test_sync_all_loads_custom_nodes(self, service, monkeypatch):
        """adapters.sync_all 后 registry 含 custom 节点（/nodes 通道）"""
        _create_custom_node(service, "sync_probe")
        service.load_into_registry()  # 模拟重启恢复
        # sync_all 内部走全局单例——patch 到 tmp service
        monkeypatch.setattr(
            "neurova.collaboration.neurflow.custom_nodes._service_instance",
            service,
        )

        from neurova.collaboration.neurflow.node_registry import NodeRegistry

        nr = NodeRegistry()
        nr.ensure_builtin()
        from neurova.collaboration.neurflow.adapters import sync_all

        sync_all(nr)

        assert nr.get("custom:sync_probe") is not None