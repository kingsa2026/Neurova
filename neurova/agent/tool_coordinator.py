"""
工具执行协调器

- per-tool 超时注册表：元数据声明制
- 超时转后台不取消：执行超时的任务转入后台继续跑并持有独立引用，
  立即返回 background 信封（{"status":"background","task_id",...}），
  后台完成后结果/错误落入 pending hints，供下一轮注入 LLM 上下文
- 并行能力声明制：可并发性由**工具自己的声明**回答（`core/tool_capability.py`
  定形状与推导，`builtin_tools` 的 schema 声明位定成员）；未声明一律串行
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

if TYPE_CHECKING:  # 导入期不引入 core 依赖（本模块被 tool_executor 早加载）
    from neurova.core.tool_capability import TimeoutDisposition

logger = logging.getLogger(__name__)

#: 收尸窗口兜底值（`asyncio.wait` 的 `timeout` 不接受 None 以外的语义缺失）。
#: 数值单源在 `sandbox/exec_sandbox.KILL_GRACE_S`——此处**只**作为导入失败时的
#: 最后兜底，正常运行恒走单源（见 `_reapCancelled` 与取消分支的导入）。
KILL_GRACE_FALLBACK_S = 5.0

# per-tool 超时（秒）：只读/轻工具短超时，浏览器/重 IO 长超时
TOOL_TIMEOUTS_S: Dict[str, float] = {
    "calculator": 5,
    "memory_search": 10,
    "recall_history": 10,
    "recall_context_span": 10,
    "web_search": 30,
    "web_fetch": 30,
    "weather": 15,
    "browser_navigate": 90,
    "browser_click": 60,
    "browser_type": 60,
    "browser_screenshot": 60,
    "browser_extract_text": 60,
    # 快照类留 45s 余量（枚举控件树/可访问性树是慢操作）。
    # 此处曾写 `"dom_snapshot": 45` —— **幻名**：它不在内置注册面（71）内，
    # 全仓也没有任何注册处，故那条放宽从未作用在任何工具上。真名有两个
    # （浏览器侧与桌面侧 UIA 树快照），都已补上。
    # 判据：tests/unit/agent/test_timeout_table_honesty.py 逐名复算
    # 「表里的键必须是注册面真名」+「快照类真名拿到了放宽」。
    "browser_dom_snapshot": 45,
    "computer_dom_snapshot": 45,
    # computer_ssh_exec：缺凭据时按需卡弹出后有限轮询等待（≤90s）+ SSH 命令本身，
    # 放宽到 180s 避免等待期被协调器掐断（当场续跑的前提）
    "computer_ssh_exec": 180,
    # P0/P1 工具族（2026-09-12）：deep_research 并发扇出（检索≤5 + 抓取≤15，
    # 信号量 6），慢站最坏需 >60s，表内放宽避免中途转后台
    "deep_research": 180,
    # file_parse 大 PDF/Office 解析留线程池慢余量
    "file_parse": 120,
    "git": 120,
}

TOOL_DEFAULT_TIMEOUT_S = 60.0

# P2（2026-09-10 蜂群排查）：前台 spawn 子任务动辄数分钟，60s 默认=必然转后台，
# 全部依赖 hints 注入的滞后语义——落表 600s 让多数子任务在窗口内直接返回报告
TOOL_TIMEOUTS_S["spawn_subagent"] = 600.0

# P1（2026-09-10）：转后台信封的 task_id 是 coordinator 通用键，特定工具的
# 自有查询凭据（如 spawn 的 subagent_id）不在信封里——per-tool 轮询提示
# 让主 agent 知道该用什么工具主动查询，而不是傻等 pending hints 注入
_OFFLOAD_HINTS: Dict[str, str] = {
    "spawn_subagent": "可用 subagent_status 查询子 Agent 状态与报告（subagent_id 可省略，省略时返回最近派生列表）",
}

def get_tool_timeout(tool_name: str, default: Optional[float] = None) -> float:
    """per-tool 超时；未知工具回落默认（大小写不敏感）。"""
    name = (tool_name or "").strip().lower()
    return TOOL_TIMEOUTS_S.get(name, default if default is not None else TOOL_DEFAULT_TIMEOUT_S)


def resolveToolCapability(tool_name: str):
    """取工具的并行能力声明；未声明/未知工具返回 None（调用方按串行处置）。

    唯一的解析入口。事实源按**提供方自己的声明处**取，本函数只做"取"与"归一"，
    不持有任何名单：

    - 内置工具：`builtin_tools` 的 schema 声明位（工具名大小写不敏感，既有口径）；
    - MCP 工具：`mcp.{server}.{tool}` → 该 server 在本仓侧配置里的 `tool_capabilities`
      声明位。第三方 server 提供的 schema 本仓改不了，故声明落在本仓侧的 server
      配置上——即"每个提供方自己的声明处"，不是集中一份大名单。
    """
    from neurova.builtin_tools import get_builtin_tool_capability

    cap = get_builtin_tool_capability((tool_name or "").strip().lower())
    if cap is not None:
        return cap
    return _resolveMcpToolCapability(tool_name)


def _resolveMcpToolCapability(tool_name: str):
    """MCP 命名空间名的声明取数（`mcp.{server}.{tool}`）。

    名字形态解析复用 `security/mcp_grants.parse_mcp_tool_name`（既有单源，不另写
    一份拆分）。**裸名一律不走这里**：MCP 工具在工具面上有裸名别名，按裸名取声明
    等于让第三方 server 的配置覆盖本仓工具；裸名归各自来源。
    前缀严格按小写匹配（真实注册名恒为小写前缀），不做"宽容匹配"——那是没有
    真实生产者的分支。

    取数落点是**配置的单一事实源**（`SharedConfigManager`，内存态字典，无落盘 IO）
    ——API 写入、bootstrap 读取、本函数取声明，三处同一个存储。改读各客户端的
    连接态副本会立刻造出第二份事实源（bootstrap 表与进程级单例各一份，取哪一份
    取决于走了哪条路径），正是协作红线点名的断点形态。
    未注册 server / 未声明工具一律返回 None，调用方按串行处置（fail-closed：
    向第三方 server 的信任不该默认给）。
    """
    from neurova.core.tool_capability import parseToolCapability
    from neurova.security.mcp_grants import parse_mcp_tool_name

    parts = parse_mcp_tool_name(str(tool_name or ""))
    if parts is None:
        return None
    server_id, tool = parts

    from neurova.shared_config import get_shared_config_manager

    try:
        entry = get_shared_config_manager().get_mcp_server(server_id) or {}
    except Exception as e:  # noqa: BLE001
        # 读不到配置 ⇒ 按**未声明**处置（即串行）。这不是"把失败改写成成功"：
        # 能力解析的失败一侧本来就与"未声明"同一处置（fail-closed），串行是安全
        # 的那一侧；反之让解析异常穿透出去会打断整轮工具执行——那是把"少用一点
        # 并行"升级成"这一轮工具全不跑"。失败以警告形态暴露，不静默。
        # 与 `resolveParallelBudget()` 的取不到设置口径同型（读不到即退保守侧）。
        logger.warning("MCP 并行声明读取失败（按未声明处置，退串行）: %s", e)
        return None
    return parseToolCapability((entry.get("tool_capabilities") or {}).get(tool))


def resolveBatchCapabilities(tool_calls: List) -> Dict[str, Any]:
    """为一批调用解析能力声明：`{归一工具名: 声明或 None}`（每名只解析一次）。

    解析入口的**批量形态**，供调度侧取数用——调度侧不自行拼装工具名归一与
    去重（那会变成第二份口径），只认这一个口。
    """
    resolved: Dict[str, Any] = {}
    for tool_call in tool_calls or []:
        name = ((tool_call or {}).get("function") or {}).get("name", "")
        key = (name or "").strip().lower()
        if key not in resolved:
            resolved[key] = resolveToolCapability(key)
    return resolved


def resolveTimeoutDisposition(tool_name: str) -> TimeoutDisposition:
    """取工具的超时处置声明；未声明/未知一律 `BACKGROUND`（与改造前同行为）。

    与 `resolveToolCapability` 共用同一个解析入口——本函数只做"从解析结果里取
    那一个字段"，不自己再读一遍声明位（那会变成第二份解析口径）。
    """
    from neurova.core.tool_capability import TimeoutDisposition

    cap = resolveToolCapability(tool_name)
    if cap is None:
        return TimeoutDisposition.BACKGROUND
    return cap.timeoutDisposition


class ToolCoordinator:
    """工具执行协调：per-tool 超时 + 超时转后台 + pending hints。"""

    def __init__(self):
        # task_id → {"task", "tool_name", "result", "error", "success"}
        self._background: Dict[str, Dict[str, Any]] = {}
        # 资源修复: 观察完成后的终态结果移入有界留存(插入序淘汰),
        # 活动字典只保留运行中任务——此前超时任务条目只增不减
        self._completed: Dict[str, Dict[str, Any]] = {}
        self._MAX_COMPLETED = 200
        self._pending_hints: List[Dict[str, Any]] = []

    async def run_with_timeout(
        self,
        tool_name: str,
        awaitable_or_factory: Any,
        timeout: Optional[float] = None,
        token: Any = None,
        disposition: Any = None,
    ) -> Any:
        """带超时执行；超时按**工具自己的处置声明**分派。

        三条分支（`TimeoutDisposition`）：

        - `BACKGROUND`（缺省）：同一任务继续在后台跑完，返回 background 信封。
          **同一任务**这条语义是硬要求——工厂重建会让副作用工具双执行。本方法
          持有任务引用防止 GC 静默吞掉；观察者协程把结果/错误推入 pending hints。
        - `ABORT`：取消任务并返回 cancelled 形态（可打断的 async 工具）。
        - `KILL`：置位取消令牌（触发已注册的进程组杀灭）→ 有界收尸 → 报取消。

        Args:
            tool_name: 工具名（查超时注册表）
            awaitable_or_factory: 协程/可等待对象，或返回协程的零参工厂
            timeout: 显式超时；None 用注册表
            token: 取消令牌（`KILL` 分支置位用）；缺省取本轮令牌，再缺省即无令牌
            disposition: 显式处置；None 用该工具的声明

        Returns:
            工具结果；或 background 信封；或 cancelled 形态
            （{"status":"cancelled","cancelled":True,...}）
        """
        from neurova.core.tool_capability import TimeoutDisposition

        effective = timeout if timeout is not None else get_tool_timeout(tool_name)
        mode = disposition
        if mode is None:
            mode = resolveTimeoutDisposition(tool_name)
        if token is None:
            from neurova.core.cancel_token import getTurnCancelToken

            token = getTurnCancelToken()

        aw = awaitable_or_factory() if callable(awaitable_or_factory) else awaitable_or_factory
        task = asyncio.ensure_future(aw)
        try:
            done, pending = await asyncio.wait({task}, timeout=effective)
        except asyncio.CancelledError:
            # 用户停止（`task_tracker.request_session_stop` 取消整轮 chat 任务）时，
            # 取消经 await 点传到这里。**这里是执行层唯一能兑现它的地方**：
            # 外层取消对已进 `to_thread` 的调用无效（线程照跑到自然结束），
            # 只有置位令牌才能让 worker 注册的进程杀灭回调真正发出。
            # 收尸有界，随后把取消原样继续上抛——本层不吞取消。
            if token is not None:
                token.cancel("user")
            task.cancel()
            try:
                await asyncio.wait({task}, timeout=KILL_GRACE_FALLBACK_S)
            except Exception as e:  # noqa: BLE001 - 收尸失败不改写"已取消"这个事实
                logger.warning("取消收尸异常（%s）: %s", tool_name, e)
            raise


        if not pending:
            return task.result()

        if mode is TimeoutDisposition.KILL:
            return await self._reapCancelled(tool_name, task, token, "timeout")
        if mode is TimeoutDisposition.ABORT:
            return await self._reapCancelled(tool_name, task, None, "timeout")

        # 超时 → 转后台：同一任务继续（持有引用防 GC 静默吞掉），观察者投递 hint
        task_id = f"bg_{uuid.uuid4().hex[:12]}"
        self._background[task_id] = {
            "task": task,
            "tool_name": tool_name,
            "result": None,
            "error": None,
            "success": None,
        }
        # A-20：观察者任务挂强引用——事件循环对 Task 只持弱引用，裸
        # ensure_future 的观察者可能被 GC 静默吞掉（pending hints 永不投递）。
        # 引用挂在 entry 上，观察者 finally 自行置 None 断开引用环。
        self._background[task_id]["observer"] = asyncio.ensure_future(
            self._observe_background(tool_name, task_id, task)
        )
        message = (
            f"工具 {tool_name} 执行超时，已转入后台继续运行；"
            f"完成后结果将注入后续上下文（task_id={task_id}）"
        )
        hint = _OFFLOAD_HINTS.get((tool_name or "").strip().lower())
        if hint:
            message += f"。{hint}"
        logger.info(
            "工具 %s 超时（%.0fs），转后台继续（task_id=%s）", tool_name, effective, task_id
        )
        return {
            "status": "background",
            "task_id": task_id,
            "tool_name": tool_name,
            "message": message,
        }

    async def _reapCancelled(
        self, tool_name: str, task: asyncio.Future, token: Any, reason: str
    ) -> Dict[str, Any]:
        """放弃一个已超时的任务，并**确认它真的停了**。

        `KILL` 走令牌：令牌上挂着执行体注册的进程组杀灭回调（`CancelToken.onCancel`），
        置位时同步执行。收尸窗口有界——上限取自 `exec_sandbox.KILL_GRACE_S`
        （既有沙箱路径 `communicate(timeout=5)` 的同一数值，不新造第二个尺度）。

        窗口内任务没退 ⇒ **如实标注**"已发杀灭、未确认退出"，不谎报已终止
        （`AGENTS.md` 修复教义第 2 条：报错要么根修、要么以诚实形态暴露）。
        """
        from neurova.sandbox.exec_sandbox import KILL_GRACE_S

        reaped = False
        if token is not None:
            token.cancel(reason)
        task.cancel()
        try:
            await asyncio.wait({task}, timeout=KILL_GRACE_S)
            reaped = task.done()
        except Exception as e:  # noqa: BLE001 - 收尸失败不改变"已取消"这个终态
            logger.warning("取消后收尸异常（%s）: %s", tool_name, e)

        outcome: Dict[str, Any] = {
            "status": "cancelled",
            "cancelled": True,
            "tool_name": tool_name,
            "reason": reason,
        }
        if not reaped:
            # 诚实形态：不返回"已终止"，而是把未确认这一事实交给上层与用户。
            outcome["message"] = (
                f"工具 {tool_name} 已发杀灭，但在 {KILL_GRACE_S:.0f}s 内未确认退出；"
                "进程可能仍在收尾"
            )
            logger.warning(
                "工具 %s 取消后未在 %.0fs 内收尸（已发杀灭，未确认退出）",
                tool_name, KILL_GRACE_S,
            )
        else:
            outcome["message"] = f"工具 {tool_name} 已取消（{reason}）"
            logger.info("工具 %s 已取消并收尸（reason=%s）", tool_name, reason)
        return outcome

    async def _observe_background(self, tool_name: str, task_id: str, task: asyncio.Future) -> None:
        entry = self._background.get(task_id)
        if entry is None:
            return
        try:
            entry["result"] = await task
            entry["success"] = True
            self._pending_hints.append({
                "task_id": task_id,
                "tool_name": tool_name,
                "success": True,
                "result": entry["result"],
            })
        except asyncio.CancelledError:
            entry["success"] = False
            entry["error"] = "cancelled"
            # 断链修复（G4-RC6）：取消分支此前既不投 hint 也不记日志，`finally`
            # 只把 entry 移入 `_completed`。于是 `get_background_status` 查得到
            # "cancelled"，而下一轮 LLM 与用户**永远收不到这条终态**——一个已经
            # 转后台的工具被取消后凭空消失。终态必须回到反馈环。
            self._pending_hints.append({
                "task_id": task_id,
                "tool_name": tool_name,
                "success": False,
                "cancelled": True,
                "error": "cancelled",
            })
            logger.info("后台工具 %s (%s) 已取消", tool_name, task_id)
        except Exception as e:
            entry["error"] = str(e)
            entry["success"] = False
            self._pending_hints.append({
                "task_id": task_id,
                "tool_name": tool_name,
                "success": False,
                "error": str(e),
            })
            logger.warning("后台工具 %s (%s) 失败: %s", tool_name, task_id, e)
        finally:
            entry["task"] = None
            # A-20：断开对观察者自身的强引用（entry 随后移入 _completed 留存）
            entry["observer"] = None
            # 资源修复: 移入有界留存(供 get_background_status 查询近 200 条终态)
            self._background.pop(task_id, None)
            self._completed[task_id] = entry
            while len(self._completed) > self._MAX_COMPLETED:
                self._completed.pop(next(iter(self._completed)), None)

    def recordApprovalOutcome(self, tool_name: str, call_id: Optional[str], *,
                              success: bool, session_id: Optional[str] = None,
                              result: Any = None, error: Optional[str] = None) -> None:
        """把"带外批准之后才产生的工具终态"投进同一条晚到通路。

        为什么复用 `_pending_hints` 而不是另起一条：本方法要解决的事与"超时转后台的
        工具完成后回报"是同一件——**结果比轮次晚到**，而下一轮才是它能被读到的时刻。
        再造一条通道就会有两个排水点、两种注入措辞、两套丢单语义（同一契约的第二份定义）。

        `success` 由调用方给定，不在这里自己判：成败判据全仓唯一
        （`ToolExecutor._result_is_success`），在此重推一遍就是造第二份。
        """
        self._pending_hints.append({
            "kind": "approval",
            "task_id": call_id,
            "tool_name": tool_name,
            "session_id": session_id,
            "success": success,
            "result": result,
            "error": error,
        })

    def pop_pending_hints(self) -> List[Dict[str, Any]]:
        """取走全部已完成的晚到提示（清空）——注入下一轮 LLM 上下文。"""
        hints = self._pending_hints
        self._pending_hints = []
        return hints

    def get_background_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询后台任务状态（运行中/已完成/未知）。"""
        entry = self._background.get(task_id) or self._completed.get(task_id)
        if entry is None:
            return None
        return {
            "task_id": task_id,
            "tool_name": entry["tool_name"],
            "running": entry["task"] is not None,
            "success": entry["success"],
        }
