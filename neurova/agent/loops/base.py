"""
Agent Loop 基类 - 定义标准接口

每个 Loop 实现特定的模型交互逻辑。
"""

import asyncio
import json
from neurova.core.logger import get_logger
from abc import ABC, abstractmethod
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Agent 仅用于类型注解；运行时导入会与 agent_core 形成循环依赖
if TYPE_CHECKING:
    from neurova.agent_core import Agent


logger = get_logger(__name__)


def _safe_json_dumps(obj: Any) -> str:
    """JSON 序列化兜底（LLM 工具结果必须可序列化）。

    SkillResult 等自定义对象（实测：幻觉工具名经 ToolRouter 返回）无法
    json.dumps 时，降级为 repr 截断——执行链不因序列化崩溃，LLM 仍能
    看到错误形态并自我纠正。
    """
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        return json.dumps({"non_serializable": repr(obj)[:500]})


class BaseAgentLoop(ABC):
    """
    Agent Loop 基类

    每个 Loop 实现特定的模型交互逻辑。
    子类必须实现 predict_step() 方法。

    """

    def __init__(self, agent: "Agent"):
        """
        初始化 Loop

        参数:
            agent: Agent 实例，提供对记忆、技能等系统的访问
        """
        self.agent = agent
        self.llm_client = agent.llm_client

    @abstractmethod
    async def predict_step(self, messages: List[Dict], tools: Optional[List[Dict]] = None, **kwargs) -> Any:
        """
        执行一步预测 - 子类必须实现

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            **kwargs: 额外参数

        返回:
            LLMResponse 对象或原始响应
        """
        # A-11：abstractmethod 只在实例化时拦截；动态构造/热加载等绕过 ABC
        # 检查的路径会落到这里——必须显式抛错，不得静默返回 None（空回复）
        raise NotImplementedError("子类必须实现 predict_step()")

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 - 默认实现

        遍历 tool_calls，执行对应的 Skill，
        并将结果作为 tool 消息添加到 messages。

        参数:
            tool_calls: LLM 返回的工具调用列表
            messages: 当前对话历史

        返回:
            新的消息列表 (tool 消息)
        """
        new_messages = []

        # P1-2 切片 3：声明制并行——同轮全部调用均声明并行安全才 gather，
        # 任一未声明（含未知工具）→ 整轮保守串行（混合批次的排序/共享状态
        # 复杂度不进热路径）。结果按原 tool_call 顺序回装（id 一一对应）。
        from neurova.agent.tool_coordinator import is_concurrency_safe

        use_parallel = len(tool_calls) > 1 and all(
            is_concurrency_safe((tc.get("function") or {}).get("name", ""))
            for tc in tool_calls
        )

        if use_parallel:
            outcomes = await asyncio.gather(
                *(self._execute_tool_call_worker(tc) for tc in tool_calls)
            )
        else:
            outcomes = [await self._execute_tool_call_worker(tc) for tc in tool_calls]

        # 回装（原序）：tool 消息 + call/result 展示记录（保持相邻配对契约）
        for msg, records in outcomes:
            new_messages.append(msg)
            self.agent.append_tool_messages(records)

        # P1-9：工具轮间隙排空插话邮箱——turn 进行中
        # 用户补充的消息以 user 角色并入消息序列，下一次采样即可见
        try:
            from neurova.core.steer_queue import get_steer_queue

            _sid = getattr(self.agent, "current_session_id", "") or ""
            for _steer_text in get_steer_queue().drain(str(_sid)):
                new_messages.append(
                    {"role": "user", "content": f"[用户插话] {_steer_text}"}
                )
        except Exception:  # noqa: BLE001 - 插话排空失败不影响工具结果回装
            logger.debug("steer 排空失败(忽略)", exc_info=True)

        # P2-5：排空子代理回传邮箱——后台子代理的完成
        # 结果逐轮可见；嵌套模式的完成摘要同样显式回灌
        try:
            from neurova.agent.mailbox import get_agent_mailbox

            _sid = getattr(self.agent, "current_session_id", "") or ""
            for _mail_text in get_agent_mailbox().drain(str(_sid)):
                new_messages.append(
                    {"role": "user", "content": _mail_text}
                )
        except Exception:  # noqa: BLE001
            logger.debug("子代理邮箱排空失败(忽略)", exc_info=True)

        return new_messages

    async def _execute_tool_call_worker(self, tool_call: Dict) -> tuple:
        """单条工具调用执行（P1-2 抽取，顺序无关的纯执行单元）。

        Returns:
            (tool_message, records)：tool_message 为回传 LLM 的 tool 消息；
            records 为 _tool_messages_list 的追加记录（tool_call + tool_result，
            由调用方按原序落位，保持前端配对展示契约）。
        """
        records: List[Dict] = []

        # 每次迭代使用独立的变量名，防止跨迭代器状态污染
        _tc_function_name = tool_call.get("function", {}).get("name", "unknown_tool")
        _tc_id = tool_call.get("id", f"call_{id(tool_call)}")

        # [TOOLROBUST-A] 参数 JSON 解析单独 try：
        # 原实现在 try 外 json.loads，一遇到某条工具参数是非法 JSON，
        # handle_tool_calls 整体抛异常 → 被 loop 当作"工具调用失败"降级/回退到
        # 无工具路径，本轮全部工具静默丢失。
        # 现在解析失败只把错误作为该工具的结果回传给 LLM，让它自行纠正参数格式。
        _tc_arguments = {}
        # T-10a：provider 是否**真给过** arguments —— 记录里只收原文，
        # 缺键时不补默认值（补了等于替 provider 声称"它给过"）。
        _has_raw_arguments = "arguments" in (tool_call.get("function") or {})
        try:
            _raw_arguments = tool_call.get("function", {}).get("arguments", "{}")
            if isinstance(_raw_arguments, str):
                _tc_arguments = json.loads(_raw_arguments) if _raw_arguments.strip() else {}
            elif isinstance(_raw_arguments, dict):
                _tc_arguments = _raw_arguments
        except (json.JSONDecodeError, TypeError, ValueError) as _parse_err:
            _parse_error = f"工具 {_tc_function_name} 参数 JSON 解析失败: {_parse_err}"
            logger.warning(_parse_error)
            parse_msg = {
                "role": "tool",
                "tool_call_id": _tc_id,
                "name": _tc_function_name,
                "content": json.dumps({"error": _parse_error}),
            }
            records.append(
                {
                    "type": "tool_result",
                    "tool_name": _tc_function_name,
                    "tool_call_id": _tc_id,
                    "result": _parse_error,
                    "success": False,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            return parse_msg, records

        # B3：剥离执行摘要参数——taskName* 是给时间轴 UI 的展示元数据，
        # 不属于工具真实参数；先提取再从 _tc_arguments 移除，SkillRegistry/
        # ToolRouter 两条执行通道都收不到
        _task_name_active = ""
        _task_name_complete = ""
        try:
            _task_name_active = str(_tc_arguments.pop("taskNameActive", "") or "")
            _task_name_complete = str(_tc_arguments.pop("taskNameComplete", "") or "")
        except AttributeError:
            pass

        # 记录工具调用消息（用于前端展示）
        _call_record = {
            "type": "tool_call",
            "tool_name": _tc_function_name,
            "params": _tc_arguments,
            "timestamp": datetime.now().isoformat(),
        }
        # T-10a（工单 §11.2）：调用侧记录必须把配对信息一起带走。
        # 落盘的是这批展示记录（`post_chat_pipeline._step_save_session` 写进
        # 会话 `metadata.tool_calls`），配对关系在这里丢一次就再也补不回来：
        #   - `tool_call_id` 是结果侧的寻址键（`_recall_by_call_id` 按它直取原文），
        #     调用侧缺它则 id ↔ arguments 的对应关系不在库里；
        #   - `arguments` 是 provider 回传的**协议原文形态**，读侧重建
        #     `assistant.tool_calls` 必须与它逐字节一致——`params` 是剥掉
        #     taskName* 的解析结果，重新序列化会改写空白，替代不了原文。
        # 只增键，不改既有键语义（工单 §11.7 第 4 条）。
        _call_record["tool_call_id"] = _tc_id
        if _has_raw_arguments:
            _call_record["arguments"] = _raw_arguments
        if _task_name_active:
            _call_record["task_name"] = _task_name_active
        records.append(_call_record)

        # 执行工具：一律经执行咽喉（ToolExecutor._execute_single_tool_inner）。
        # 原生链此前各自调用 SkillRegistry / ToolRouter，既拿不到客观票据与
        # on_tool_executed，又与文本链对同一失败工具给出不同的 success 值
        # （见 neurova/agent/native_tool_dispatch.py 的模块说明）。
        from neurova.agent.native_tool_dispatch import execute_native_tool

        outcome = await execute_native_tool(self.agent, _tc_function_name, dict(_tc_arguments))
        exec_result = SimpleNamespace(
            success=outcome["success"],
            data=outcome["result"],
            error=outcome["error"],
            metadata={},
        )

        # 构建 tool_result message
        if exec_result.success:
            content = _safe_json_dumps(exec_result.data) if exec_result.data is not None else "Success"
        else:
            content = _safe_json_dumps({"error": exec_result.error})

        # P1-#6（§5.6）：溢出分层——可重现大结果全文落工作区文件、
        # 消息体换预览+指针；不可重现（含 MCP/自创未声明）豁免原文直进。
        from neurova.core.tool_offload import apply_offload_policy, resolve_tool_reproducible

        _reproducible = resolve_tool_reproducible(self.agent, _tc_function_name)
        _offload = apply_offload_policy(
            tool_name=_tc_function_name,
            call_id=_tc_id,
            content=content,
            reproducible=_reproducible,
            workspace_root=getattr(self.agent, "workspace_path", None) or None,
        )
        content = _offload.content

        tool_msg = {
            "role": "tool",
            "tool_call_id": _tc_id,
            "name": _tc_function_name,
            "content": content,
        }

        # 记录工具执行结果（用于前端展示）
        # 完整保留 content（不预截断）：SSE 去重 key 基于完整内容 hash，
        # 截断会让"前缀相同正文不同"的结果（如同计划 create/mark_step）
        # 被误判为重复；展示层截断由 console._build_tool_events 的 [:500] 处理
        # P1-#6 条目增强：call_id 硬地址 + reproducible 落盘证据（防工具
        # 改标/删除后历史语义漂移）+ offload_path（溢出时全文真相指针）
        _result_record = {
            "type": "tool_result",
            "tool_name": _tc_function_name,
            "tool_call_id": _tc_id,
            "result": content if content else "执行完成",
            "success": exec_result.success,
            "timestamp": datetime.now().isoformat(),
            "reproducible": _reproducible,
            "offload_path": _offload.offload_path,
        }
        if _task_name_complete:
            _result_record["task_name"] = _task_name_complete
        records.append(_result_record)

        logger.info("Tool executed: %s, success=%s", _tc_function_name, exec_result.success)
        return tool_msg, records

