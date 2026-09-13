# -*- coding: utf-8 -*-
"""工具结果溢出分层（P1 #6 触点3核心判定，对比报告 §5.6 定稿）。

三档策略（按 reproducible × 大小）：
  ① 未超阈值            → 原样（全文驻留消息与会话台账）
  ② 可重现 + 超阈值     → 全文落工作区文件 outputs/tool_offload/<call>-<sha16>.txt，
                          消息体 = 预览 + 硬指针（call_id/ts/文件路径），
                          全文一条不丢，生命周期=随工作区
  ③ 不可重现 + 超阈值   → 豁免：原样全文（当时的原文即唯一记录，禁止外移）

预览格式与 microcompact 视图占位统一寻址语法（tool/call/ts），模型经
recall_history 按指针直取。Yuxi 同构先例：large_tool_results offload
（summary.py:591-626），差异在 NV 用可重现性做豁免维度。
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
    """
    text = str(content or "")
    kb = get_threshold_kb() if threshold_kb is None else max(1, int(threshold_kb))
    if not reproducible or len(text.encode("utf-8", "replace")) <= kb * 1024:
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

    preview = text[:_PREVIEW_CHARS] + ("…" if len(text) > _PREVIEW_CHARS else "")
    try:
        rel_path = str(target.relative_to(root))
    except ValueError:
        rel_path = str(target)
    pointer = (
        f"[工具输出已溢出至工作区文件: tool={tool_name} call={call_id} "
        f"ts={datetime.now().isoformat(timespec='seconds')} size={len(text)} "
        f"path={rel_path}；完整内容经 recall_history(session_id, tool_call_id=\"{call_id}\") 取回]\n{preview}"
    )
    return OffloadOutcome(
        content=pointer, offloaded=True, offload_path=rel_path, preview=preview
    )
