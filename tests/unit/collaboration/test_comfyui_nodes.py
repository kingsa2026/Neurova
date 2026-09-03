"""
ComfyUI 节点适配器测试 — TDD 切片 1

验证 ComfyUI 核心节点（KSampler/VAEDecode/CheckpointLoader 等）
能注册到 Neurflow NodeRegistry，并保留 ComfyUI 节点的元信息。

RED: 测试应先失败（comfyui_nodes 模块不存在）
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestComfyUINodeRegistration:
    """切片 1: ComfyUI 节点注册到 Neurflow NodeRegistry"""

    def test_kSampler_node_can_be_registered(self):
        """RED: KSampler 节点应能注册到 NodeRegistry"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()

        # 注册 ComfyUI 节点
        register_comfyui_nodes(registry)

        # KSampler 是 ComfyUI 最核心的采样节点
        node = registry.get("comfyui:KSampler")
        assert node is not None, "KSampler 节点应已注册"
        assert node.label == "KSampler"
        assert node.category == "comfyui"
        assert node.source == "comfyui"

    def test_vae_decode_node_can_be_registered(self):
        """RED: VAEDecode 节点应能注册"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()
        register_comfyui_nodes(registry)

        node = registry.get("comfyui:VAEDecode")
        assert node is not None, "VAEDecode 节点应已注册"
        assert node.category == "comfyui"

    def test_checkpoint_loader_node_can_be_registered(self):
        """RED: CheckpointLoaderSimple 节点应能注册"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()
        register_comfyui_nodes(registry)

        node = registry.get("comfyui:CheckpointLoaderSimple")
        assert node is not None, "CheckpointLoaderSimple 节点应已注册"

    def test_all_core_comfyui_nodes_registered(self):
        """RED: 至少 10 个核心 ComfyUI 节点应注册"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()
        register_comfyui_nodes(registry)

        # 获取所有 comfyui 来源的节点
        comfyui_nodes = registry.list_by_source("comfyui")
        assert len(comfyui_nodes) >= 10, (
            f"应至少注册 10 个 ComfyUI 节点，实际: {len(comfyui_nodes)}"
        )

    def test_comfyui_nodes_have_inputs_and_outputs(self):
        """RED: ComfyUI 节点应定义 inputs 和 outputs"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()
        register_comfyui_nodes(registry)

        # KSampler 应有 inputs（seed/Steps/CFG/model 等）和 outputs（LATENT）
        node = registry.get("comfyui:KSampler")
        assert node.inputs is not None and len(node.inputs) > 0, \
            "KSampler 应有输入端口"
        assert node.outputs is not None and len(node.outputs) > 0, \
            "KSampler 应有输出端口"

    def test_comfyui_nodes_have_sub_blocks_for_config(self):
        """RED: ComfyUI 节点应有 sub_blocks 用于前端配置表单"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()
        register_comfyui_nodes(registry)

        node = registry.get("comfyui:KSampler")
        assert node.sub_blocks is not None and len(node.sub_blocks) > 0, \
            "KSampler 应有 sub_blocks 配置项（seed/steps/cfg 等）"

    def test_comfyui_node_has_executor(self):
        """RED: ComfyUI 节点应注册执行器"""
        from neurova.collaboration.neurflow.node_registry import (
            get_node_registry,
            reset_node_registry,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import register_comfyui_nodes

        reset_node_registry()
        registry = get_node_registry()
        register_comfyui_nodes(registry)

        # 执行器应已注册
        executor = registry.get_executor("comfyui:KSampler")
        assert executor is not None, "KSampler 应有执行器"
        assert callable(executor), "执行器应是可调用对象"
