# -*- coding: utf-8 -*-
"""工具结果溢出分层（P1 #6 触点3核心判定 + P0-4 截断显式化）。

三档策略（按 大小 × 落盘成败）：
  ① 未超阈值            → 原样（全文驻留消息与会话台账）
  ② 超阈值（可重现与否）→ 全文落工作区文件 outputs/tool_offload/<tool>-<sha16>.txt，
                          消息体 = head+tail 预览 + 截断标注 + 指针
                          （call_id/ts/文件路径/原始体量），全文一条不丢，
                          生命周期=随工作区
  ③ 落盘失败            → fail-open：原样放行（消息完整性优先，宁可窗口大
                          也不丢结果）

P0-4 契约变更（Codex head+tail 对齐，docs/Neurova_Codex代码级对比_2026-09-14.md
§2.7）：原 ② 仅可重现工具溢出、③ 不可重现工具全文直进窗口——巨量输出挤占
窗口后在折叠中整段丢失。现在统一"落盘保全 + head+tail + 显式标注"：模型
永远知道被截了多少、去哪取回全文（recall_history 按指针直取）。落盘失败时
fail-open 保留原保真方向。

预览格式与 microcompact 视图占位统一寻址语法（tool/call/ts），模型经
recall_history 按指针直取。Yuxi 同构先例：large_tool_results offload
（summary.py:591-626），差异在 NV 用 head+tail 双端预览。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from neurova.core.logger import get_logger
from neurova.security.tool_offload_settings import get_threshold_kb

logger = get_logger(__name__)

OFFLOAD_SUBDIR = "outputs/tool_offload"
_PREVIEW_CHARS = 400


def _head_tail_preview(text: str) -> str:
    """head+tail 双端预览（P0-4）：中段以省略行显式计数，绝不静默消失。"""
    if len(text) <= _PREVIEW_CHARS:
        return text
    if len(text) <= _PREVIEW_CHARS * 2:
        return text[:_PREVIEW_CHARS] + "…"
    omitted = len(text) - _PREVIEW_CHARS * 2
    return (
        text[:_PREVIEW_CHARS]
        + f"\n…[中间省略 {omitted} 字符]…\n"
        + text[-_PREVIEW_CHARS:]
    )


@dataclass
class OffloadOutcome:
    content: str                      # 进消息体/窗口的文本（溢出时=预览+指针）
    offloaded: bool
    offload_path: Optional[str] = None  # 相对 workspace_root 的路径（溢出时）
    preview: Optional[str] = None


def _sha16(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]


def resolve_tool_reproducible(agent, tool_name: str) -> bool:
    """可重现性统一查询点（消费面单源，§5.6 触点1 拍板）。

    顺序：内置单源表（_NON_REPRODUCIBLE_TOOLS 派生）→ 自创技能 manifest
    声明（create_skill 按步骤推导写入 config.reproducible）→ 其余
    （MCP/未知/未声明）保守 False——数据保真方向：不可重放的原文
    不允许外移到溢出文件被清理。
    """
    from neurova.builtin_tools import _BUILTIN_SCHEMAS, is_builtin_tool_reproducible

    if tool_name in _BUILTIN_SCHEMAS:
        return is_builtin_tool_reproducible(tool_name)
    try:
        registry = getattr(agent, "_skill_registry", None) if agent is not None else None
        if registry is not None:
            skill = (getattr(registry, "skills", None) or {}).get(tool_name)
            cfg = getattr(skill, "config", None) if skill is not None else None
            if isinstance(cfg, dict) and isinstance(cfg.get("reproducible"), bool):
                return cfg["reproducible"]
    except Exception:  # noqa: BLE001 - 查询失败按保守 False，不阻断执行链
        logger.debug("skill reproducible 查询失败: %s", tool_name, exc_info=True)
    return False


def apply_offload_policy(
    tool_name: str,
    call_id: str,
    content: str,
    reproducible: bool,
    workspace_root=None,
    threshold_kb: Optional[int] = None,
) -> OffloadOutcome:
    """对工具结果应用分层策略；返回要写进消息体的文本与溢出元数据。

    任何落盘异常降级为"原样不溢出"（fail-open：消息完整性优先，
    宁可窗口大也不丢结果）——异常本身记日志。
    reproducible 保留为元数据（记录进台账），不再作为豁免维度（P0-4）。
    """
    text = str(content or "")
    kb = get_threshold_kb() if threshold_kb is None else max(1, int(threshold_kb))
    if len(text.encode("utf-8", "replace")) <= kb * 1024:
        return OffloadOutcome(content=text, offloaded=False)

    root = Path(workspace_root) if workspace_root else Path("data")
    target_dir = root / OFFLOAD_SUBDIR
    # 内容寻址命名（tool-sha16）：同内容重复溢出幂等复用同一文件（call 级
    # 寻址由记录 offload_path 承担）
    _safe_tool = "".join(c if c.isalnum() else "_" for c in (tool_name or "tool"))[:40]
    filename = f"{_safe_tool}-{_sha16(text)}.txt"
    target = target_dir / filename
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists():  # 同内容重复溢出幂等复用（sha 寻址）
            target.write_text(text, encoding="utf-8")
    except OSError as e:
        logger.error("工具结果溢出落盘失败（原样放行，不截断）: %s", e)
        return OffloadOutcome(content=text, offloaded=False)

    try:
        rel_path = str(target.relative_to(root))
    except ValueError:
        rel_path = str(target)
    pointer = (
        f"[工具输出已截断并溢出至工作区文件: tool={tool_name} call={call_id} "
        f"ts={datetime.now().isoformat(timespec='seconds')} size={len(text)} "
        f"path={rel_path}；完整内容经 recall_history(session_id, tool_call_id=\"{call_id}\") 取回]\n"
        f"{_head_tail_preview(text)}"
    )
    return OffloadOutcome(
        content=pointer, offloaded=True, offload_path=rel_path,
        preview=_head_tail_preview(text),
    )
