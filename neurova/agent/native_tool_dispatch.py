"""原生 function-calling 链到执行咽喉的改道（工单 003）。

`agent/loops/base.py` 的两条出口（`SkillRegistry.execute_skill` / `ToolRouter.execute`）
此前各自为政，不经 `ToolExecutor._execute_single_tool_inner`，于是同一次工具执行拿不到
客观票据（`creation_governance.record_tool_execution`）、`on_tool_executed`（肌肉记忆/
生命周期）、统一治理预检、Pre/PostToolUse hooks 与 per-tool 超时。更糟的是两条链对
同一个失败工具会给出**不同的 success 值**：router 把 `{"error": …}` 包成
`ToolResult(success=True)`，`base.py` 于是恒真 ⇒ 假成功票。

本模块把改道收在一处：原生链只解析参数、落展示记录，执行一律委托咽喉。成败判据复用
咽喉的 `_result_is_success`（**单源**，此处不再写第二份内容判据）。

身份与沙箱根**不**回退成 LLM 可伪造的参数：`_caller_user_id` 由
`ToolExecutor.execute_skill_tool` 注入、`file_operation._base_dir` 由
`ToolExecutor._workspace_base` 赋值，两者都留在咽喉内。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 失败正文里允许带到模型眼前的诊断键（**单源**：`loops/base.py` 的失败分支读它，
#: 不另写第二份名单）。选键口径：执行面能给出、且模型据此能自我纠正——
#: 退出码、两端输出、耗时、运行时类型、上下文/提示、错误码。故意**不含**任何
#: 路径类键：诊断正文同样不许泄露绝对路径（附件图链的先例）。
FAILURE_DIAGNOSTIC_KEYS = (
    "exit_code",
    "stderr",
    "stdout",
    "duration_ms",
    "runtime_type",
    "context",
    "hint",
    "code",
)


def extractFailureReason(raw: Any) -> Optional[str]:
    """从执行面返回值里取出**真实**失败原因（单源提取点）。

    三层依次下探：顶层 `error` → 嵌套 `result.error`（`execute_tool_calls`
    在参数解析失败等形态下把原因嵌在 `result` 键下）→ 无。
    取不到即返回 None，由调用方决定兜底串 —— 兜底串只能是**标题**，
    不得反过来覆盖已存在的正文（那正是本模块要修的蒸发）。
    """
    if not isinstance(raw, dict):
        return None
    top = raw.get("error")
    if top:
        return str(top)
    inner = raw.get("result")
    if isinstance(inner, dict) and inner.get("error"):
        return str(inner["error"])
    return None


def buildFailureToolBody(error: Optional[str], result: Any) -> Dict[str, Any]:
    """构造喂回模型的失败正文：`error` 作标题 + 执行面可诊断子集。

    体量折叠不在此处：调用方紧接着走既有 `apply_offload_policy`
    （单源，见 D2），故本函数不做任何截断。
    """
    body: Dict[str, Any] = {"error": error}
    source = result if isinstance(result, dict) else {}
    inner = source.get("result") if isinstance(source.get("result"), dict) else {}
    for key in FAILURE_DIAGNOSTIC_KEYS:
        for container in (source, inner):
            if key not in container or key in body:
                continue
            value = container[key]
            if value is None or value == "" or value == []:
                continue
            body[key] = value
            break
    return body


async def execute_native_tool(agent: Any, tool_name: str,
                              params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """经执行咽喉跑一条原生工具调用，返回归一后的成败与结果。

    Returns:
        `{"success": bool, "result": Any, "error": Optional[str]}`——成败取自咽喉的
        `_result_is_success`，不再由调用侧按"有没有抛异常"猜。
    """
    executor = getattr(agent, "tool_executor", None)
    if executor is None:
        return {"success": False, "result": None, "error": "工具执行器未装配，原生工具调用无法执行"}

    try:
        raw = await executor.execute_tool(tool_name, dict(params or {}))
    except Exception as err:  # noqa: BLE001 - 咽喉异常即该工具失败，不许静默成功
        logger.warning("原生工具调用经咽喉执行异常: %s, %s", tool_name, err)
        return {"success": False, "result": None, "error": f"工具执行异常: {err}"}

    if not isinstance(raw, dict):
        raw = {"result": raw}
    success = executor._result_is_success(raw)
    # 兜底串只为"执行面连原因都没给"时留一个可读标题；已有正文时**不覆盖**，
    # 嵌套在 `result.error` 下的原因同样要能被取到（否则参数解析失败形态
    # 又被兜底串盖掉，模型永远看不到真因）。
    error = None if success else (extractFailureReason(raw) or f"工具执行失败: {tool_name}")
    return {"success": success, "result": raw, "error": error}
