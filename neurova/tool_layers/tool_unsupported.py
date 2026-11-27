# -*- coding: utf-8 -*-
"""U12 结构化拒绝分类学：能力未装配 / 端不支持的稳定错误形状。

从 neurova.tool_executor 拆出；`neurova.tool_executor` re-export
`ToolUnsupportedError` / `toolUnsupportedResult` / `TOOL_UNSUPPORTED_CODE` 旧路径。
"""
from typing import Any, Dict, List, Optional

__all__ = ["TOOL_UNSUPPORTED_CODE", "ToolUnsupportedError", "toolUnsupportedResult"]

#: 稳定错误码：工具能力未装配，或该端不支持所请求的工具/输入域。
TOOL_UNSUPPORTED_CODE = "TOOL_UNSUPPORTED"


class ToolUnsupportedError(RuntimeError):
    """能力未装配 / 端不支持的信号异常——执行边界统一翻译成结构化拒绝 dict。

    为什么是异常而不是各执行体直接返回 dict：不支持情形可能产生在深层
    （如 create_skill 的注入扫描器缺失），裸异常逸出会给模型一句
    "工具执行异常: …" 的散装串；逐层传 dict 又会误触发回退链的
    "失败→换下一档"。异常只在执行边界（_execute_single_tool）翻译一次。
    """

    def __init__(self, reason: str, supported: Optional[List[str]] = None):
        super().__init__(reason)
        self.reason = reason
        self.supported = list(supported or [])


def toolUnsupportedResult(reason: str, supported: Optional[List[str]] = None) -> Dict[str, Any]:
    """U12 稳定拒绝形状（单源构造点）。

    `error` 键保留原文原因：`_result_is_success` 与既有消费方按 error 判失败，
    字符串断言（如 "未知工具" 子串）继续成立；`error_code`/`reason`/`supported`
    是新增的结构化判别面。
    """
    return {
        "success": False,
        "error_code": TOOL_UNSUPPORTED_CODE,
        "reason": reason,
        "supported": list(supported or []),
        "error": reason,
    }
