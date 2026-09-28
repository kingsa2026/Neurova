"""`file_operation` 沙箱根注入的单一事实源。

根因（2026-09-08 相对路径乱放事故）：内置文件工具与 `file_operation` 技能各自
按进程 CWD 解析相对路径，写盘散落项目根且与 SSE artifact 注册不一致。修复口径
是"相对路径锚定 agent 工作区"，且以**服务端赋值**覆盖 LLM 伪造的同名参数。

该注入原先在 `router.py` 与 `agent/loops/base.py` 各写了一份同形实现（后者已随
咽喉收编删除），故收口到此处：任何新入口要做这件事都调本函数，不再各写一份。
"""

from pathlib import Path
from typing import Any, Dict, Optional

# 需要沙箱根的服务端工具名（目前只有文件操作这一类）
SANDBOX_ROOT_TOOLS = frozenset({"file_operation"})


def resolveWorkspaceRoot(agent: Any) -> str:
    """agent 工作区根（相对路径的锚定基准）——**唯一**一处解析口径。

    校验与回落都在这里，调用方不再各写一遍：

    - `workspace_path` 缺失/为空 → `.`（保持无 agent 上下文构造的旧语义）；
    - 非真实目录 → `.`。这条**不是**多余的保护：`workspace_path` 可能是测试替身
      泄漏出来的伪路径，拿它当沙箱根会把相对路径写到不可预期的位置——宁可回退
      也不拿伪根（与 2026-09-08 事故的修复口径同向）；
    - 解析异常 → `.`（畸形字符串不得让注入整体失败）。

    此前本函数与 `tool_executor._workspace_base()` 是同一条事实的两处实现，且
    **口径已经分叉**：helper 直接 `str(workspace_path)` 不做校验，咽喉做
    `is_dir()` 校验。于是同一份 `workspace_path` 在两条入口给出不同沙箱根，
    而 `_base_dir` 是覆盖 LLM 伪造参数的服务端赋值——防伪造防线只在其中一条
    路径上成立。实测（`"/nonexistent-dir-xyz"`）：helper 给出该伪路径、咽喉给出
    `.`。判据见 tests/unit/skills/test_sandbox_root_single_source.py。
    """
    if agent is None:
        return "."
    workspace = getattr(agent, "workspace_path", None)
    if not workspace:
        return "."
    try:
        path = Path(str(workspace))
        # 非真实目录（含 Mock 泄漏）视为缺失，宁可回退也不拿伪根
        return str(path) if path.is_dir() else "."
    except Exception:  # noqa: BLE001 - 畸形路径按缺失处理
        return "."


def inject_sandbox_root(agent: Any, tool_name: str,
                        params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """按工具名注入沙箱根；不需要时原样返回参数副本。

    `_base_dir` 是服务端赋值，**覆盖** LLM 传进来的同名参数（防伪造）。
    拿不到有效工作区时回落 `.`（见 `resolveWorkspaceRoot`）。

    **成员资格与解析口径都在本模块**：调用方（`router.py`、`tool_executor`
    咽喉）只调本函数，不再自带 `skill_name == "file_operation"` 那样的第二处
    判定——那正是本模块存在时要收掉的东西。
    """
    merged = dict(params or {})
    if tool_name not in SANDBOX_ROOT_TOOLS:
        return merged
    merged["_base_dir"] = resolveWorkspaceRoot(agent)
    return merged
