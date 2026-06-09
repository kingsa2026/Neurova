"""
ToolExecutor — 统一工具执行器

从 agent_core.py 提取 (P1 拆分)，负责：
- 文本工具调用解析与执行 (_execute_text_tool_calls)
- 肌肉记忆工具执行 (_execute_tool_from_memory)
- Skill/CLI/MCP 工具分派 (_execute_skill_tool, _execute_cli_tool)
- 集中化工具执行后钩子 (_on_tool_executed)
- 内置工具参数信息 (_get_builtin_tool_params)

设计原则：
- 依赖注入：通过 agent_ref 访问 Agent 实例的属性
- 可独立测试：不依赖 Agent 类的完整初始化
"""

import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# ToolEngine 延迟导入（避免循环依赖）
_TOOL_ENGINE_AVAILABLE = False
_ToolEngine = None

def _get_tool_engine_class():
    """延迟导入 ToolEngine 类"""
    global _TOOL_ENGINE_AVAILABLE, _ToolEngine
    if _ToolEngine is None:
        try:
            from neurova.execution_engine.tool_engine import ToolEngine
            _ToolEngine = ToolEngine
            _TOOL_ENGINE_AVAILABLE = True
        except ImportError:
            _TOOL_ENGINE_AVAILABLE = False
    return _ToolEngine

class ToolExecutor:
    """统一工具执行器

    通过 agent_ref 访问 Agent 实例的：
    - _skill_registry, tool_router, tool_memory, tool_lifecycle, skill_packer
    - _tool_messages_list, config
    """

    def __init__(self, agent_ref):
        """
        初始化工具执行器

        Args:
            agent_ref: Agent 实例引用
        """
        self._agent = agent_ref
        self._messages_list: List[Dict] = []
        self._tool_engine = None  # ToolEngine 实例（延迟初始化）

    @property
    def tool_engine(self):
        """获取 ToolEngine 实例（延迟初始化）"""
        if self._tool_engine is None:
            # 首先尝试从 ExecutionEngine 获取
            try:
                from neurova.shared_core.execution_engine import ExecutionEngine
                engine = ExecutionEngine()
                if hasattr(engine, '_tool_engine') and engine._tool_engine is not None:
                    self._tool_engine = engine._tool_engine
                    logger.debug("从 ExecutionEngine 获取 ToolEngine")
                    return self._tool_engine
            except Exception as e:
                logger.debug(f"从 ExecutionEngine 获取 ToolEngine 失败: {e}")
            
            # 如果 ExecutionEngine 不可用，创建新的 ToolEngine
            ToolEngineClass = _get_tool_engine_class()
            if ToolEngineClass:
                try:
                    self._tool_engine = ToolEngineClass()
                    logger.debug("创建新的 ToolEngine 实例")
                except Exception as e:
                    logger.warning(f"创建 ToolEngine 失败: {e}")
        return self._tool_engine

    @property
    def _skill_registry(self):
        """获取 skill 注册表"""
        return getattr(self._agent, '_skill_registry', None)

    @property
    def tool_router(self):
        """获取工具路由器"""
        return getattr(self._agent, 'tool_router', None)

    @property
    def tool_memory(self):
        """获取工具记忆"""
        return getattr(self._agent, 'tool_memory', None)

    @property
    def tool_lifecycle(self):
        """获取工具生命周期"""
        return getattr(self._agent, 'tool_lifecycle', None)

    @property
    def skill_packer(self):
        """获取 skill 打包器"""
        return getattr(self._agent, 'skill_packer', None)

    @property
    def config(self):
        """获取配置"""
        return getattr(self._agent, 'config', None)

    def _ensure_messages_list(self, messages: Optional[List[Dict]] = None) -> List[Dict]:
        """确保消息列表存在"""
        if messages is None:
            if not self._messages_list:
                self._messages_list = []
            return self._messages_list
        return messages

    async def execute_text_tool_calls(self, tool_calls: List[Dict], messages: Optional[List[Dict]] = None) -> List[Dict]:
        """
        执行文本工具调用

        Args:
            tool_calls: 工具调用列表
            messages: 消息列表（可选）

        Returns:
            工具执行结果列表
        """
        messages = self._ensure_messages_list(messages)
        results = []

        for tool_call in tool_calls:
            try:
                # 解析工具调用
                function = tool_call.get("function", {})
                tool_name = function.get("name", "")
                arguments_str = function.get("arguments", "{}")

                # 解析参数
                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError:
                    arguments = {}

                # 执行工具
                result = await self._execute_single_tool(tool_name, arguments)
                results.append({
                    "tool_call_id": tool_call.get("id", ""),
                    "name": tool_name,
                    "result": result,
                    "success": True,
                })

                # 记录到消息列表
                self._messages_list.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False),
                })

            except Exception as e:
                logger.error(f"工具执行失败: {e}")
                results.append({
                    "tool_call_id": tool_call.get("id", ""),
                    "name": tool_name if 'tool_name' in locals() else "unknown",
                    "error": str(e),
                    "success": False,
                })

        return results

    async def execute_from_memory(self, tool_name: str, params: Dict, context: Optional[Dict] = None) -> Dict:
        """
        从肌肉记忆执行工具

        Args:
            tool_name: 工具名称
            params: 工具参数
            context: 上下文信息

        Returns:
            执行结果
        """
        # 检查工具记忆
        if self.tool_memory:
            try:
                # check_tool_memory 接受 user_input 字符串
                memory_result, _ = self.tool_memory.check_tool_memory(tool_name)
                if memory_result and memory_result.get("confidence", 0) > 0.8:
                    # 使用记忆中的结果
                    return memory_result.get("result", {})
            except Exception as e:
                logger.debug(f"工具记忆检查失败: {e}")

        # 执行工具
        result = await self._execute_single_tool(tool_name, params)

        # 记录工具使用
        if self.tool_memory:
            try:
                self.tool_memory.record_tool_usage(
                    tool_name=tool_name,
                    success=result is not None,
                    tool_params=params,
                )
            except Exception as e:
                logger.debug(f"工具记忆记录失败: {e}")

        return result

    async def execute_from_memory_async(
        self,
        tool_memory_result: Dict[str, Any],
        user_input: str,
    ) -> Dict[str, Any]:
        """从肌肉记忆结果自动执行工具（异步版本，支持超时控制）

        Args:
            tool_memory_result: 肌肉记忆匹配结果（来自 check_tool_memory）
            user_input: 用户原始输入

        Returns:
            {"status": "success"|"failure", "result": ..., "tool_name": ..., "error": ...}
        """
        if not tool_memory_result:
            return {"status": "failure", "error": "空的 tool_memory_result", "tool_name": ""}

        tool_name = tool_memory_result.get("tool_name")
        tool_source = tool_memory_result.get("tool_source")
        tool_params = tool_memory_result.get("tool_params", tool_memory_result.get("tool_params_template", {}))

        if not tool_name:
            return {"status": "failure", "error": "ToolMemory 结果缺少 tool_name", "tool_name": ""}

        logger.info(f"自动执行工具（异步）: {tool_name} (来源: {tool_source})")

        self._messages_list.append({
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_source": tool_source,
            "params": tool_params,
            "timestamp": datetime.now().isoformat(),
        })

        try:
            result = await self._execute_single_tool(tool_name, tool_params)
            success = result is not None and "error" not in result

            # 记录工具使用
            if self.tool_memory:
                try:
                    self.tool_memory.record_tool_usage(
                        tool_name=tool_name,
                        success=success,
                        problem_text=user_input,
                        tool_source=tool_source,
                        tool_params=tool_params,
                    )
                except Exception as e:
                    logger.debug(f"工具记忆记录失败: {e}")

            if success:
                return {"status": "success", "result": result, "tool_name": tool_name}
            else:
                error_msg = result.get("error", "未知错误") if isinstance(result, dict) else "执行失败"
                return {"status": "failure", "error": error_msg, "tool_name": tool_name, "result": result}

        except Exception as e:
            logger.error(f"工具自动执行异常: {tool_name}, {e}")
            return {"status": "failure", "error": str(e), "tool_name": tool_name}

    async def execute_skill_tool(self, skill_name: str, params: Dict, context: Optional[Dict] = None) -> Dict:
        """
        执行 Skill 工具

        Args:
            skill_name: Skill 名称
            params: 参数
            context: 上下文

        Returns:
            执行结果
        """
        if not self._skill_registry:
            return {"error": "Skill 注册表未初始化"}

        try:
            # 获取 Skill
            skill = self._skill_registry.get_skill(skill_name)
            if not skill:
                return {"error": f"Skill {skill_name} 不存在"}

            # 执行 Skill
            result = await skill.execute(params, context)
            return result

        except Exception as e:
            logger.error(f"Skill 执行失败: {e}")
            return {"error": str(e)}

    async def execute_cli_tool(self, command: str, args: Optional[Dict] = None) -> Dict:
        """
        执行 CLI 工具

        Args:
            command: 命令
            args: 参数

        Returns:
            执行结果
        """
        # 这里可以实现 CLI 工具执行逻辑
        return {"error": "CLI 工具执行未实现"}

    async def _execute_single_tool(self, tool_name: str, params: Dict) -> Dict:
        """
        执行单个工具

        Args:
            tool_name: 工具名称
            params: 参数

        Returns:
            执行结果
        """
        # 优先使用 ToolEngine（如果可用）
        if self.tool_engine:
            try:
                # 获取 user_id 和 agent_id（如果可用）
                user_id = getattr(self._agent, 'user_id', None)
                agent_id = getattr(self._agent, 'agent_id', None)
                
                result = await self.tool_engine.execute_with_safeguards(
                    tool_name=tool_name,
                    parameters=params,
                    user_id=user_id,
                    agent_id=agent_id
                )
                logger.debug(f"ToolEngine 执行成功: {tool_name}")
                return result
            except ValueError as e:
                # 工具未注册或不可用，回退到其他方式
                logger.debug(f"ToolEngine 工具 {tool_name} 未注册或不可用: {e}")
            except Exception as e:
                logger.warning(f"ToolEngine 执行失败: {tool_name}, {e}")
        
        # 回退到原有逻辑
        # 内置工具
        builtin_tools = [
            "memory_search", "file_read", "file_write", "file_create",
            "file_delete", "file_edit", "computer_screenshot", "computer_click",
            "computer_type", "computer_scroll", "computer_shell", "emotion_analyze"
        ]

        if tool_name in builtin_tools:
            return await self._execute_builtin_tool(tool_name, params)

        # Skill 工具
        if self._skill_registry and self._skill_registry.has_skill(tool_name):
            return await self.execute_skill_tool(tool_name, params)

        # 通过工具路由器
        if self.tool_router:
            try:
                result = await self.tool_router.route(tool_name, params)
                return result
            except Exception as e:
                logger.debug(f"工具路由器执行失败: {e}")

        return {"error": f"未知工具: {tool_name}"}

    async def _execute_builtin_tool(self, tool_name: str, params: Dict) -> Dict:
        """执行内置工具"""
        # 简单的内置工具实现
        if tool_name == "memory_search":
            return await self._execute_memory_search(params)
        elif tool_name == "file_read":
            return await self._execute_file_read(params)
        elif tool_name == "file_write":
            return await self._execute_file_write(params)
        elif tool_name == "file_create":
            return await self._execute_file_create(params)
        elif tool_name == "file_delete":
            return await self._execute_file_delete(params)
        elif tool_name == "file_edit":
            return await self._execute_file_edit(params)
        elif tool_name == "computer_screenshot":
            return await self._execute_computer_screenshot(params)
        elif tool_name == "computer_click":
            return await self._execute_computer_click(params)
        elif tool_name == "computer_type":
            return await self._execute_computer_type(params)
        elif tool_name == "computer_scroll":
            return await self._execute_computer_scroll(params)
        elif tool_name == "computer_shell":
            return await self._execute_computer_shell(params)
        elif tool_name == "emotion_analyze":
            return await self._execute_emotion_analyze(params)
        else:
            return {"error": f"未知内置工具: {tool_name}"}

    async def _execute_memory_search(self, params: Dict) -> Dict:
        """执行记忆搜索"""
        query = params.get("query", "")
        category = params.get("category")
        limit = params.get("limit", 5)

        # 这里应该调用记忆管理器
        # 暂时返回模拟结果
        return {
            "results": [],
            "query": query,
            "category": category,
            "limit": limit,
            "count": 0,
        }

    async def _execute_file_read(self, params: Dict) -> Dict:
        """执行文件读取"""
        file_path = params.get("file_path", "")
        offset = params.get("offset", 0)
        encoding = params.get("encoding", "utf-8")

        try:
            with open(file_path, 'r', encoding=encoding) as f:
                lines = f.readlines()
                if offset > 0:
                    lines = lines[offset-1:]  # offset 从 1 开始
                content = ''.join(lines)
                return {"content": content, "lines": len(lines)}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_write(self, params: Dict) -> Dict:
        """执行文件写入"""
        file_path = params.get("file_path", "")
        content = params.get("content", "")
        encoding = params.get("encoding", "utf-8")

        try:
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(content)
                return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_create(self, params: Dict) -> Dict:
        """执行文件创建"""
        file_path = params.get("file_path", "")
        content = params.get("content", "")

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_delete(self, params: Dict) -> Dict:
        """执行文件删除"""
        import os
        file_path = params.get("file_path", "")

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return {"success": True, "file_path": file_path}
            else:
                return {"error": f"文件不存在: {file_path}"}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_edit(self, params: Dict) -> Dict:
        """执行文件编辑"""
        file_path = params.get("file_path", "")
        old_str = params.get("old_str", "")
        new_str = params.get("new_str", "")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if old_str in content:
                new_content = content.replace(old_str, new_str, 1)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                return {"success": True, "file_path": file_path}
            else:
                return {"error": "未找到目标文本"}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_computer_screenshot(self, params: Dict) -> Dict:
        """执行屏幕截图"""
        # 这里需要 Computer Use 模块
        return {"error": "Computer Use 未初始化"}

    async def _execute_computer_click(self, params: Dict) -> Dict:
        """执行鼠标点击"""
        # 这里需要 Computer Use 模块
        return {"error": "Computer Use 未初始化"}

    async def _execute_computer_type(self, params: Dict) -> Dict:
        """执行键盘输入"""
        # 这里需要 Computer Use 模块
        return {"error": "Computer Use 未初始化"}

    async def _execute_computer_scroll(self, params: Dict) -> Dict:
        """执行屏幕滚动"""
        # 这里需要 Computer Use 模块
        return {"error": "Computer Use 未初始化"}

    async def _execute_computer_shell(self, params: Dict) -> Dict:
        """执行 shell 命令"""
        # 这里需要 Computer Use 模块
        return {"error": "Computer Use 未初始化"}

    async def _execute_emotion_analyze(self, params: Dict) -> Dict:
        """执行情感分析"""
        text = params.get("text", "")
        # 简单的情感分析
        return {
            "emotion": "neutral",
            "confidence": 0.5,
            "raw": text,
        }

    def _on_tool_executed(self, tool_name: str, result: Dict, success: bool):
        """
        工具执行后钩子

        Args:
            tool_name: 工具名称
            result: 执行结果
            success: 是否成功
        """
        # 记录工具使用统计
        if self.tool_memory:
            try:
                self.tool_memory.record_tool_usage(
                    tool_name=tool_name,
                    success=success,
                    tool_params=result,
                )
            except Exception as e:
                logger.debug(f"工具记忆记录失败: {e}")

        # 更新工具生命周期
        if self.tool_lifecycle:
            try:
                self.tool_lifecycle.update_usage(tool_name, success)
            except Exception as e:
                logger.debug(f"工具生命周期更新失败: {e}")

    def _get_builtin_tool_params(self, tool_name: str) -> Optional[Dict]:
        """
        获取内置工具参数

        Args:
            tool_name: 工具名称

        Returns:
            工具参数 schema
        """
        try:
            from neurova.builtin_tools import get_builtin_tool_params
            return get_builtin_tool_params(tool_name)
        except ImportError as e:
            logger.debug(f"get_builtin_tool_params 延迟导入失败: {e}")
            return {}

    def get_tool_messages(self) -> List[Dict]:
        """获取工具消息列表"""
        return self._messages_list.copy()

    def clear_tool_messages(self):
        """清空工具消息列表"""
        self._messages_list.clear()