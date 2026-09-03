"""
ComfyUI 工作流导入测试 — TDD 切片 3

验证 comfyui_importer 能将 ComfyUI API 格式工作流 JSON 转换为
Neurflow WorkflowDefinition。

ComfyUI API 格式：
    {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "prompt", "clip": ["1", 1]}
        }
    }

转换规则：
1. ComfyUI 节点 ID → Neurflow WorkflowNode.id
2. class_type → type="comfyui:{class_type}"
3. 标量 inputs → config
4. 数组 inputs [node_id, output_index] → WorkflowEdge
5. 自动生成网格布局 position

RED: 测试应先失败（comfyui_importer 模块不存在）
"""

import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ==================== 测试数据：ComfyUI 工作流样例 ====================

SIMPLE_COMFYUI_WORKFLOW = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a beautiful landscape", "clip": ["1", 1]},
    },
}

COMPLEX_COMFYUI_WORKFLOW = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a beautiful landscape", "clip": ["1", 1]},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "blurry, bad quality", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 25,
            "cfg": 7.5,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
            "denoise": 1.0,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
        },
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["6", 0]},
    },
}


class TestComfyUIWorkflowImport:
    """切片 3 - ComfyUI 工作流导入"""

    def test_import_simple_workflow_returns_workflow_definition(self):
        """RED: 导入简单工作流应返回 WorkflowDefinition"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(SIMPLE_COMFYUI_WORKFLOW, name="简单测试")

        from neurova.collaboration.neurflow.models import WorkflowDefinition
        assert isinstance(result, WorkflowDefinition), f"应返回 WorkflowDefinition，实际: {type(result)}"
        assert result.name == "简单测试"

    def test_import_creates_node_for_each_comfyui_node(self):
        """RED: 每个 ComfyUI 节点应转换为 WorkflowNode"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(COMPLEX_COMFYUI_WORKFLOW, name="复杂测试")

        # 复杂工作流有 7 个节点
        assert len(result.nodes) == 7, f"应有 7 个节点，实际: {len(result.nodes)}"

        # 节点 ID 应保留 ComfyUI 的字符串 ID
        node_ids = {n.id for n in result.nodes}
        assert "1" in node_ids, "节点 ID 应保留 ComfyUI 原始 ID"
        assert "5" in node_ids, "KSampler 节点 ID 应为 '5'"

    def test_import_adds_comfyui_prefix_to_node_type(self):
        """RED: 节点 type 应添加 comfyui: 前缀"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(SIMPLE_COMFYUI_WORKFLOW, name="前缀测试")

        # CheckpointLoaderSimple → comfyui:CheckpointLoaderSimple
        ckpt_node = next(n for n in result.nodes if n.id == "1")
        assert ckpt_node.type == "comfyui:CheckpointLoaderSimple", \
            f"应添加 comfyui: 前缀，实际: {ckpt_node.type}"

        clip_node = next(n for n in result.nodes if n.id == "2")
        assert clip_node.type == "comfyui:CLIPTextEncode"

    def test_import_converts_scalar_inputs_to_config(self):
        """RED: 标量 inputs 应转为 config"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(COMPLEX_COMFYUI_WORKFLOW, name="配置测试")

        # KSampler (id=5) 的标量参数应进入 config
        ksampler = next(n for n in result.nodes if n.id == "5")
        assert ksampler.config.get("seed") == 42, f"config 应包含 seed=42，实际: {ksampler.config}"
        assert ksampler.config.get("steps") == 25
        assert ksampler.config.get("sampler_name") == "dpmpp_2m"
        assert ksampler.config.get("cfg") == 7.5

    def test_import_converts_array_inputs_to_edges(self):
        """RED: 数组 inputs [node_id, output_index] 应转为 WorkflowEdge"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(SIMPLE_COMFYUI_WORKFLOW, name="边测试")

        # 节点 2 的 clip input = ["1", 1] 应生成一条边 1→2
        assert len(result.edges) >= 1, f"应至少 1 条边，实际: {len(result.edges)}"

        edge = result.edges[0]
        assert edge.source == "1", f"边的 source 应为 '1'，实际: {edge.source}"
        assert edge.target == "2", f"边的 target 应为 '2'，实际: {edge.target}"

    def test_import_complex_workflow_generates_correct_edges(self):
        """RED: 复杂工作流应生成所有连接边"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(COMPLEX_COMFYUI_WORKFLOW, name="复杂边测试")

        # 复杂工作流的连接数：
        # 节点2.clip ← 1.1
        # 节点3.clip ← 1.1
        # 节点5.model ← 1.0, .positive ← 2.0, .negative ← 3.0, .latent_image ← 4.0
        # 节点6.samples ← 5.0, .vae ← 1.2
        # 节点7.images ← 6.0
        # 共 9 条边
        assert len(result.edges) == 9, f"复杂工作流应有 9 条边，实际: {len(result.edges)}"

    def test_import_generates_grid_positions(self):
        """RED: 应自动生成网格布局 position"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(COMPLEX_COMFYUI_WORKFLOW, name="布局测试")

        # 每个节点应有 position
        for node in result.nodes:
            assert "x" in node.position, f"节点 {node.id} 缺少 position.x"
            assert "y" in node.position, f"节点 {node.id} 缺少 position.y"
            assert isinstance(node.position["x"], (int, float))
            assert isinstance(node.position["y"], (int, float))

    def test_import_preserves_edge_input_field_as_target_handle(self):
        """RED: 边的 target_handle 应保留 input 字段名"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(COMPLEX_COMFYUI_WORKFLOW, name="handle测试")

        # 节点 5 的 model input ← ["1", 0]
        # 应生成 edge: source="1", target="5", target_handle="model"
        model_edge = next(
            e for e in result.edges
            if e.source == "1" and e.target == "5" and e.target_handle == "model"
        )
        assert model_edge is not None, "应有 model 边连接 1→5"

        # 节点 5 的 positive input ← ["2", 0]
        positive_edge = next(
            e for e in result.edges
            if e.source == "2" and e.target == "5" and e.target_handle == "positive"
        )
        assert positive_edge is not None, "应有 positive 边连接 2→5"

    def test_import_preserves_edge_output_index_as_source_handle(self):
        """RED: 边的 source_handle 应保留 output_index"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(COMPLEX_COMFYUI_WORKFLOW, name="source_handle测试")

        # CheckpointLoaderSimple (节点1) 有 3 个输出: MODEL(0), CLIP(1), VAE(2)
        # 节点 2 的 clip ← ["1", 1] → source_handle="1" (CLIP 输出)
        # 节点 5 的 model ← ["1", 0] → source_handle="0" (MODEL 输出)
        # 节点 6 的 vae ← ["1", 2] → source_handle="2" (VAE 输出)

        clip_edge = next(e for e in result.edges if e.source == "1" and e.target == "2")
        assert clip_edge.source_handle == "1", f"CLIP 边 source_handle 应为 '1'，实际: {clip_edge.source_handle}"

        vae_edge = next(e for e in result.edges if e.source == "1" and e.target == "6" and e.target_handle == "vae")
        assert vae_edge.source_handle == "2", f"VAE 边 source_handle 应为 '2'，实际: {vae_edge.source_handle}"

    def test_import_invalid_workflow_raises_error(self):
        """RED: 无效工作流（缺少 class_type）应抛出 ValueError"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        invalid_workflow = {
            "1": {"inputs": {"text": "no class_type"}},
        }

        with pytest.raises(ValueError) as exc_info:
            import_comfyui_workflow(invalid_workflow, name="无效测试")

        assert "class_type" in str(exc_info.value).lower(), \
            f"错误信息应提及 class_type，实际: {exc_info.value}"

    def test_import_empty_workflow_returns_empty_definition(self):
        """RED: 空工作流应返回空 WorkflowDefinition"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow({}, name="空测试")

        assert len(result.nodes) == 0
        assert len(result.edges) == 0

    def test_import_sets_workflow_metadata_with_source(self):
        """RED: 导入的工作流应在 metadata 标记来源为 comfyui"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(SIMPLE_COMFYUI_WORKFLOW, name="元信息测试")

        assert result.metadata.get("source") == "comfyui", \
            f"metadata.source 应为 'comfyui'，实际: {result.metadata.get('source')}"
        assert result.category == "comfyui", \
            f"category 应为 'comfyui'，实际: {result.category}"

    def test_import_preserves_original_comfyui_workflow_in_metadata(self):
        """RED: 应在 metadata 保留原始 ComfyUI JSON 以便回溯"""
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow

        result = import_comfyui_workflow(SIMPLE_COMFYUI_WORKFLOW, name="回溯测试")

        original = result.metadata.get("original_comfyui_workflow")
        assert original is not None, "应在 metadata 保留 original_comfyui_workflow"
        assert original == SIMPLE_COMFYUI_WORKFLOW, "原始工作流应完整保留"
