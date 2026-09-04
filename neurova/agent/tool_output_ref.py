"""工具大输出 OutputRef 落盘引用（OpenOcta 启发 P1-6）。

OpenOcta：ToolResult{Success, Output, OutputRef, Data, Error}——大输出
落盘为文件，上下文只放 {Path, SizeBytes, Truncated} 引用，模型可用 read
工具按需取。Neurova 的 file_read 接收绝对路径，落盘引用天然可回读。

解决缺口：工具大输出（截图 base64 / 大文件读取 / 长命令输出）整体涌入
对话历史 → token 膨胀 + 记忆/技能观察者吃进大对象。装配后：结果序列化
超过阈值 → 原样写入 <workspace>/tool_outputs/，上下文只留
{path, size_bytes, truncated, preview} 引用 + 可回读提示。

语义边界（防呆）：
- **默认不安装**：install_tool_output_ref() 显式装配（幂等）；未安装时
  maybe_output_ref 恒透传原结果对象（零行为变化）。
- **诚实降级**：无工作区/写盘失败时原样返回大结果——宁可膨胀也不丢输出。
- 与 context_pool 溢出摘要互补：一个管工具输出（本模块），一个管对话历史。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_PREVIEW_CHARS = 500


@dataclass
class OutputRefHandle:
    """装配句柄（保留扩展点：阈值/目录策略后续可热调）。"""

    max_chars: int
    output_dirname: str = "tool_outputs"


_global_handle: Optional[OutputRefHandle] = None
_install_lock = threading.RLock()


def install_tool_output_ref(max_chars: int = 8192, output_dirname: str = "tool_outputs") -> OutputRefHandle:
    """装配大输出引用（幂等：已安装返回同一句柄）。

    默认阈值 8KiB 与 OpenOcta 的单消息 8KiB 截断红线同量级。
    """
    global _global_handle
    with _install_lock:
        if _global_handle is not None:
            return _global_handle
        _global_handle = OutputRefHandle(max_chars=max_chars, output_dirname=output_dirname)
        logger.info("工具大输出引用已装配（阈值 %d 字符）", max_chars)
        return _global_handle


def uninstall_tool_output_ref(force: bool = False) -> None:
    """卸载（可逆；幂等）。force=True 时强制清空全局句柄。"""
    global _global_handle
    with _install_lock:
        _global_handle = None


def get_installed_output_ref() -> Optional[OutputRefHandle]:
    with _install_lock:
        return _global_handle


def maybe_output_ref(tool_name: str, result: Any, workspace_dir: Any) -> Any:
    """结果出流咽喉点调用：大输出落盘为引用。

    Args:
        tool_name: 工具名（落盘文件名成分）
        result: 工具结果（仅 dict 结果处理；其余原样返回）
        workspace_dir: agent 工作区目录（Path/str；None=诚实降级透传）

    Returns:
        原结果（未安装/小结果/降级）或引用 dict：
        {"success": ..., "output_ref": {path, size_bytes, truncated, preview}, "note": ...}
    """
    handle = get_installed_output_ref()
    if handle is None:
        return result
    if not isinstance(result, dict):
        return result
    if workspace_dir is None:
        return result

    try:
        serialized = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return result  # 不可序列化：原样透传（与未接入等价）
    if len(serialized) <= handle.max_chars:
        return result

    try:
        out_dir = Path(workspace_dir) / handle.output_dirname
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in tool_name if c.isalnum() or c in "-_")[:40] or "tool"
        path = out_dir / f"ref_{int(time.time())}_{safe_name}_{len(serialized):x}.json"
        path.write_text(serialized, encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - 写盘失败诚实降级：原样返回大结果
        logger.warning("OutputRef 落盘失败（透传原结果）: %s", e)
        return result

    success = result.get("success", "error" not in result)
    size_bytes = path.stat().st_size
    logger.info(
        "工具 %s 输出 %d 字符超阈值 %d → 落盘 %s（%d 字节）",
        tool_name, len(serialized), handle.max_chars, path, size_bytes,
    )
    return {
        "success": bool(success),
        "output_ref": {
            "path": str(path.resolve()),
            "size_bytes": size_bytes,
            "truncated": True,
            "preview": serialized[:_PREVIEW_CHARS],
        },
        "note": (
            f"工具 {tool_name} 输出 {len(serialized)} 字符超过阈值 {handle.max_chars}，"
            f"完整内容已落盘：{path}（可用 file_read 读取；本条仅保留引用与预览）"
        ),
    }


__all__ = [
    "OutputRefHandle",
    "get_installed_output_ref",
    "install_tool_output_ref",
    "maybe_output_ref",
    "uninstall_tool_output_ref",
]
