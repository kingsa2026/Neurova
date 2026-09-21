"""`file_operation` 沙箱根注入的单一事实源。

根因（2026-09-08 相对路径乱放事故）：内置文件工具与 `file_operation` 技能各自
按进程 CWD 解析相对路径，写盘散落项目根且与 SSE artifact 注册不一致。修复口径
是"相对路径锚定 agent 工作区"，且以**服务端赋值**覆盖 LLM 伪造的同名参数。

该注入原先在 `router.py` 与 `agent/loops/base.py` 各写了一份同形实现（后者已随
咽喉收编删除），故收口到此处：任何新入口要做这件事都调本函数，不再各写一份。
"""

from typing import Any, Dict, Optional

# 需要沙箱根的服务端工具名（目前只有文件操作这一类）
SANDBOX_ROOT_TOOLS = frozenset({"file_operation"})


def inject_sandbox_root(agent: Any, tool_name: str,
                        params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """按工具名注入沙箱根；不需要时原样返回参数副本。

    `_base_dir` 是服务端赋值，**覆盖** LLM 传进来的同名参数（防伪造）。
    拿不到工作区时回落 `.`（保持无 agent 上下文构造的旧语义）。
    """
    merged = dict(params or {})
    if tool_name not in SANDBOX_ROOT_TOOLS:
        return merged
    workspace = getattr(agent, "workspace_path", "") if agent is not None else ""
    merged["_base_dir"] = str(workspace) if workspace else "."
    return merged
