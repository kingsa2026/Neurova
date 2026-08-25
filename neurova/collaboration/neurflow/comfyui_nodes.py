"""
ComfyUI 节点适配器 — TDD 切片 1

把 ComfyUI 核心节点（KSampler/VAEDecode/CheckpointLoader 等）注册到
Neurflow NodeRegistry，type 格式 `comfyui:{class_type}`，并注册执行器。

执行器 _execute_comfyui_node 剥离 comfyui: 前缀后经 ComfyUIClient 提交
到 ComfyUI /prompt 端点（见 comfyui_client.py）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

try:
    from .models import NodeDefinition, NodePort, SubBlockConfig
    from .node_registry import NodeRegistry
except ImportError:  # pragma: no cover
    from neurova.collaboration.neurflow.models import NodeDefinition, NodePort, SubBlockConfig
    from neurova.collaboration.neurflow.node_registry import NodeRegistry


# ── ComfyUI 核心节点目录 ────────────────────────────────────────
# (class_type, 标量配置项 [(id, title, type)], 输入端口, 输出端口)

_COMFYUI_NODE_CATALOG = [
    (
        "CheckpointLoaderSimple",
        [("ckpt_name", "模型文件", "input")],
        [],
        [("MODEL", "模型"), ("CLIP", "CLIP"), ("VAE", "VAE")],
    ),
    (
        "CLIPTextEncode",
        [("text", "提示词", "textarea")],
        [("clip", "CLIP")],
        [("CONDITIONING", "条件")],
    ),
    (
        "VAEDecode",
        [],
        [("samples", "LATENT"), ("vae", "VAE")],
        [("IMAGE", "图像")],
    ),
    (
        "VAEEncode",
        [],
        [("pixels", "图像"), ("vae", "VAE")],
        [("LATENT", "LATENT")],
    ),
    (
        "EmptyLatentImage",
        [("width", "宽度", "input"), ("height", "高度", "input"), ("batch_size", "批量", "input")],
        [],
        [("LATENT", "LATENT")],
    ),
    (
        "KSampler",
        [
            ("seed", "种子", "input"),
            ("steps", "步数", "slider"),
            ("cfg", "CFG", "slider"),
            ("sampler_name", "采样器", "input"),
            ("scheduler", "调度器", "input"),
            ("denoise", "降噪", "slider"),
        ],
        [("model", "模型"), ("positive", "正向条件"), ("negative", "负向条件"), ("latent_image", "LATENT")],
        [("LATENT", "LATENT")],
    ),
    (
        "KSamplerAdvanced",
        [
            ("seed", "种子", "input"),
            ("steps", "步数", "slider"),
            ("cfg", "CFG", "slider"),
            ("add_noise", "加噪", "input"),
            ("start_at_step", "起始步", "input"),
            ("end_at_step", "结束步", "input"),
            ("return_with_leftover_noise", "保留噪声", "input"),
        ],
        [("model", "模型"), ("positive", "正向条件"), ("negative", "负向条件"), ("latent_image", "LATENT")],
        [("LATENT", "LATENT")],
    ),
    (
        "SaveImage",
        [("filename_prefix", "文件名前缀", "input")],
        [("images", "图像")],
        [],
    ),
    (
        "LoadImage",
        [("image", "图片路径", "file")],
        [],
        [("IMAGE", "图像"), ("MASK", "遮罩")],
    ),
    (
        "LatentUpscale",
        [
            ("upscale_method", "放大算法", "input"),
            ("width", "宽度", "input"),
            ("height", "高度", "input"),
            ("crop", "裁剪", "input"),
        ],
        [("samples", "LATENT")],
        [("LATENT", "LATENT")],
    ),
    (
        "LoraLoader",
        [
            ("lora_name", "LoRA 文件", "file"),
            ("strength_model", "模型强度", "slider"),
            ("strength_clip", "CLIP 强度", "slider"),
        ],
        [("model", "模型"), ("clip", "CLIP")],
        [("MODEL", "模型"), ("CLIP", "CLIP")],
    ),
    (
        "CLIPSetLastLayer",
        [("stop_at_clip_layer", "截止层", "input")],
        [("clip", "CLIP")],
        [("CLIP", "CLIP")],
    ),
]


def _build_definition(class_type: str, configs, input_ports, output_ports) -> NodeDefinition:
    sub_blocks = [
        SubBlockConfig(id=cid, title=title, type=ctype, required=(i == 0))
        for i, (cid, title, ctype) in enumerate(configs)
    ]
    return NodeDefinition(
        type=f"comfyui:{class_type}",
        label=class_type,
        icon="🎨",
        category="comfyui",
        description=f"ComfyUI 节点: {class_type}",
        sub_blocks=sub_blocks,
        inputs=[NodePort(id=pid, label=label) for pid, label in input_ports],
        outputs=[NodePort(id=pid, label=label) for pid, label in output_ports],
        source="comfyui",
    )


async def _execute_comfyui_node(node_type: str, config: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """ComfyUI 节点统一执行器：剥离 comfyui: 前缀后经 HTTP 客户端提交

    Args:
        node_type: 注册表节点类型（comfyui:{class_type}）
        config: 节点标量配置
        inputs: 上游输入（引用占位）

    Returns:
        {"status": "success"|"failed", "output", "error"}
    """
    class_type = node_type[len("comfyui:"):] if node_type.startswith("comfyui:") else node_type

    from .comfyui_client import get_comfyui_client

    client = get_comfyui_client()
    if not client.is_available():
        return {
            "status": "failed",
            "error": "ComfyUI 服务不可用（未配置 NEUROVA_COMFYUI_HOST）",
            "output": None,
        }

    return await client.execute_node(class_type, config, inputs)


def register_comfyui_nodes(registry: NodeRegistry) -> int:
    """把全部 ComfyUI 核心节点注册到 NodeRegistry（含执行器）

    Returns:
        注册的节点数量
    """
    count = 0
    for class_type, configs, input_ports, output_ports in _COMFYUI_NODE_CATALOG:
        definition = _build_definition(class_type, configs, input_ports, output_ports)

        def make_executor(ct: str):
            async def executor(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
                # 上游输入引用：从 ctx["node_results"] 提取已连接节点的输出
                upstream: Dict[str, Any] = {}
                node_results = ctx.get("node_results", {}) if isinstance(ctx, dict) else {}
                for key, res in (node_results or {}).items():
                    if isinstance(res, dict) and res.get("output") is not None:
                        upstream[str(key)] = res["output"]
                return await _execute_comfyui_node(ct, config or {}, upstream)

            return executor

        registry.register(definition, make_executor(class_type))
        count += 1

    logger.info("ComfyUI 节点注册完成: %d 个", count)
    return count


__all__ = ["register_comfyui_nodes", "_execute_comfyui_node"]
