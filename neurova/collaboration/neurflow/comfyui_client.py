"""
ComfyUI HTTP 客户端 — TDD 切片 2

与 ComfyUI 服务的 HTTP 交互层：
- 单例获取 get_comfyui_client() / reset_comfyui_client()
- 可用性检测 is_available()（依据 NEUROVA_COMFYUI_HOST 配置）
- 节点执行 execute_node()（POST {host}/prompt）

设计约束（AGENTS.md）:
- 深模块：小接口（is_available / execute_node），深实现（HTTP 细节内聚）
- 故障隔离：网络异常返回 failed 结果字典，绝不向上抛
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover - httpx 为可选依赖
    httpx = None  # type: ignore[assignment]
    HTTPX_AVAILABLE = False


class ComfyUIClient:
    """ComfyUI HTTP 客户端

    Attributes:
        host: ComfyUI 服务地址（如 http://localhost:8188），未配置为 None
    """

    def __init__(self):
        self.host: Optional[str] = self._read_host()

    @staticmethod
    def _read_host() -> Optional[str]:
        """从配置读取 ComfyUI 主机地址"""
        try:
            from neurova.core.config import get

            host = get("NEUROVA_COMFYUI_HOST", None)
            return str(host) if host else None
        except Exception:  # noqa: BLE001 - 配置系统不可用时视为未配置
            return None

    def is_available(self) -> bool:
        """ComfyUI 服务是否已配置可用"""
        return bool(self.host)

    async def execute_node(
        self,
        class_type: str,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """执行一个 ComfyUI 节点（提交 prompt 到 /prompt 端点）

        Args:
            class_type: ComfyUI 节点类名（如 KSampler，不带 comfyui: 前缀）
            config: 节点配置（标量参数，如 seed/steps/cfg）
            inputs: 上游输入（如 model/positive 的引用占位）
            timeout: HTTP 超时秒数

        Returns:
            {"status": "success"|"failed", "output": {...}|None, "error": str|None}
        """
        if not self.is_available():
            return {
                "status": "failed",
                "error": "ComfyUI 服务未配置（缺少 NEUROVA_COMFYUI_HOST）或不可用",
                "output": None,
            }

        if not HTTPX_AVAILABLE:
            return {
                "status": "failed",
                "error": "httpx 未安装，无法调用 ComfyUI",
                "output": None,
            }

        # ComfyUI API 格式：prompt 字段内为 {node_id: {class_type, inputs}}
        merged_inputs: Dict[str, Any] = {}
        merged_inputs.update(config or {})
        merged_inputs.update(inputs or {})
        payload = {"prompt": {"1": {"class_type": class_type, "inputs": merged_inputs}}}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.host.rstrip('/')}/prompt", json=payload)
                response.raise_for_status()
                data = response.json()
                return {
                    "status": "success",
                    "output": {
                        "prompt_id": data.get("prompt_id"),
                        "number": data.get("number"),
                        "node_errors": data.get("node_errors", {}),
                    },
                    "error": None,
                }
        except Exception as e:  # noqa: BLE001 - 网络异常隔离为 failed 结果
            logger.warning("ComfyUI 调用失败 (%s): %s", class_type, e)
            return {
                "status": "failed",
                "error": str(e),
                "output": None,
            }


# ── 单例生命周期 ────────────────────────────────────────────────

_comfyui_client_instance: Optional[ComfyUIClient] = None


def get_comfyui_client() -> ComfyUIClient:
    global _comfyui_client_instance
    if _comfyui_client_instance is None:
        _comfyui_client_instance = ComfyUIClient()
    return _comfyui_client_instance


def reset_comfyui_client() -> None:
    global _comfyui_client_instance
    _comfyui_client_instance = None


__all__ = ["ComfyUIClient", "get_comfyui_client", "reset_comfyui_client"]
