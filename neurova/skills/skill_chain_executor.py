"""
技能链执行器 (Skill Chain Executor)

执行技能链，管理技能间的依赖和数据流。
实现 Meta-skill 的 skill-chain-executor 能力。
"""

from __future__ import annotations

import asyncio
from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List

from .models import (
    ChainExecutionResult,
    ChainStatus,
    ChainStatusInfo,
    SkillChain,
    SkillChainStep,
    StepExecutionResult,
    StepStatus,
)

logger = get_logger(__name__)


class SkillChainExecutor:
    """
    技能链执行器

    执行技能链，管理技能间的依赖和数据流。
    实现 Meta-skill 的 skill-chain-executor 能力。
    """

    def __init__(self, skill_service=None):
        """
        初始化技能链执行器

        Args:
            skill_service: 技能服务，用于执行单个技能
        """
        self.skill_service = skill_service
        self._active_chains: Dict[str, Dict[str, Any]] = {}
        self._chain_instances: Dict[str, SkillChain] = {}

        logger.info("SkillChainExecutor 初始化完成")

    async def execute_chain(self, chain: SkillChain, initial_input: Dict[str, Any]) -> ChainExecutionResult:
        """
        执行技能链

        Args:
            chain: 技能链定义
            initial_input: 初始输入数据

        Returns:
            ChainExecutionResult: 执行结果
        """
        chain_id = chain.chain_id or str(uuid.uuid4())
        chain.chain_id = chain_id

        try:
            # 初始化执行上下文
            context = {
                "chain_id": chain_id,
                "variables": {**chain.variables, **initial_input},
                "step_results": {},
                "current_step": 0,
                "status": ChainStatus.RUNNING,
            }

            self._active_chains[chain_id] = context
            self._chain_instances[chain_id] = chain

            logger.info("开始执行技能链: %s (%s)", chain.name, chain_id)

            # 执行每个步骤
            step_results = []
            current_input = initial_input

            for i, step in enumerate(chain.steps):
                context["current_step"] = i

                # 检查是否应该跳过步骤
                if await self._should_skip_step(step, context):
                    step_result = StepExecutionResult(
                        step_id=step.step_id,
                        skill_id=step.skill_id,
                        status=StepStatus.SKIPPED,
                        input_data=current_input,
                    )
                    step_results.append(step_result)
                    continue

                # 执行步骤
                step_result = await self._execute_step(step, current_input, context)
                step_results.append(step_result)

                # 检查步骤是否成功
                if step_result.status == StepStatus.FAILED:
                    context["status"] = ChainStatus.FAILED

                    return ChainExecutionResult(
                        chain_id=chain_id,
                        status=ChainStatus.FAILED,
                        success=False,
                        results=step_results,
                        error=f"步骤 {step.step_id} 执行失败: {step_result.error}",
                        total_duration=sum(r.duration for r in step_results),
                    )

                # 更新输入数据
                current_input = await self._map_output_to_input(step_result.output_data, step.output_mapping, context)

                # 更新上下文
                context["step_results"][step.step_id] = step_result.output_data

            # 执行完成
            context["status"] = ChainStatus.COMPLETED

            result = ChainExecutionResult(
                chain_id=chain_id,
                status=ChainStatus.COMPLETED,
                success=True,
                results=step_results,
                final_output=current_input,
                total_duration=sum(r.duration for r in step_results),
                metadata={
                    "chain_name": chain.name,
                    "step_count": len(chain.steps),
                    "completed_steps": len([r for r in step_results if r.status == StepStatus.COMPLETED]),
                },
            )

            logger.info("技能链执行完成: %s (%s)", chain.name, chain_id)
            return result

        except Exception as e:
            logger.error("技能链执行失败: %s", e)

            return ChainExecutionResult(chain_id=chain_id, status=ChainStatus.FAILED, success=False, error=str(e))

        finally:
            # 清理上下文
            self._active_chains.pop(chain_id, None)
            self._chain_instances.pop(chain_id, None)

    async def pause_chain(self, chain_id: str) -> bool:
        """
        暂停技能链

        Args:
            chain_id: 技能链 ID

        Returns:
            bool: 是否成功暂停
        """
        if chain_id not in self._active_chains:
            logger.warning("找不到活动的技能链: %s", chain_id)
            return False

        context = self._active_chains[chain_id]
        context["status"] = ChainStatus.PAUSED

        logger.info("技能链已暂停: %s", chain_id)
        return True

    async def resume_chain(self, chain_id: str) -> bool:
        """
        恢复技能链

        Args:
            chain_id: 技能链 ID

        Returns:
            bool: 是否成功恢复
        """
        if chain_id not in self._active_chains:
            logger.warning("找不到活动的技能链: %s", chain_id)
            return False

        context = self._active_chains[chain_id]
        if context["status"] != ChainStatus.PAUSED:
            logger.warning("技能链未处于暂停状态: %s", chain_id)
            return False

        context["status"] = ChainStatus.RUNNING

        logger.info("技能链已恢复: %s", chain_id)
        return True

    async def get_chain_status(self, chain_id: str) -> ChainStatusInfo:
        """
        获取技能链状态

        Args:
            chain_id: 技能链 ID

        Returns:
            ChainStatusInfo: 状态信息
        """
        if chain_id not in self._active_chains:
            return ChainStatusInfo(chain_id=chain_id, status=ChainStatus.PENDING, progress=0.0)

        context = self._active_chains[chain_id]
        chain = self._chain_instances.get(chain_id)

        if not chain:
            return ChainStatusInfo(chain_id=chain_id, status=ChainStatus.PENDING, progress=0.0)

        current_step = context.get("current_step", 0)
        total_steps = len(chain.steps)
        progress = current_step / total_steps if total_steps > 0 else 0.0

        return ChainStatusInfo(
            chain_id=chain_id,
            status=context.get("status", ChainStatus.PENDING),
            progress=progress,
            current_step=current_step,
            total_steps=total_steps,
            metadata={"chain_name": chain.name, "variables": context.get("variables", {})},
        )

    async def cancel_chain(self, chain_id: str) -> bool:
        """
        取消技能链

        Args:
            chain_id: 技能链 ID

        Returns:
            bool: 是否成功取消
        """
        if chain_id not in self._active_chains:
            logger.warning("找不到活动的技能链: %s", chain_id)
            return False

        context = self._active_chains[chain_id]
        context["status"] = ChainStatus.CANCELLED

        logger.info("技能链已取消: %s", chain_id)
        return True

    async def _execute_step(
        self, step: SkillChainStep, input_data: Dict[str, Any], context: Dict[str, Any]
    ) -> StepExecutionResult:
        """
        执行单个步骤

        Args:
            step: 技能链步骤
            input_data: 输入数据
            context: 执行上下文

        Returns:
            StepExecutionResult: 步骤执行结果
        """
        import time

        start_time = time.time()

        try:
            # 映射输入数据
            mapped_input = await self._map_input_data(input_data, step.input_mapping, context)

            # 执行技能
            if self.skill_service:
                # 使用技能服务执行
                execution_result = await self.skill_service.call_skill(skill_id=step.skill_id, input_data=mapped_input)

                output_data = execution_result.output if execution_result.success else {}
                error = execution_result.error if not execution_result.success else ""
                status = StepStatus.COMPLETED if execution_result.success else StepStatus.FAILED
            else:
                # 模拟执行
                await asyncio.sleep(0.1)  # 模拟执行时间
                output_data = {"result": f"模拟执行 {step.skill_id}", "input": mapped_input}
                error = ""
                status = StepStatus.COMPLETED

            duration = time.time() - start_time

            return StepExecutionResult(
                step_id=step.step_id,
                skill_id=step.skill_id,
                status=status,
                input_data=mapped_input,
                output_data=output_data,
                error=error,
                duration=duration,
                retries=0,
            )

        except Exception as e:
            duration = time.time() - start_time

            # 重试逻辑
            retries = 0
            if step.retry_count > 0:
                for retry in range(step.retry_count):
                    try:
                        logger.info("重试步骤 %s，第 %s 次", step.step_id, retry + 1)
                        return await self._execute_step(step, input_data, context)
                    except Exception:
                        retries += 1
                        continue

            return StepExecutionResult(
                step_id=step.step_id,
                skill_id=step.skill_id,
                status=StepStatus.FAILED,
                input_data=input_data,
                error=str(e),
                duration=duration,
                retries=retries,
            )

    async def _map_input_data(
        self, input_data: Dict[str, Any], mapping: Dict[str, str], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """映射输入数据"""
        if not mapping:
            return input_data

        mapped = {}

        for target_key, source_key in mapping.items():
            if source_key in input_data:
                mapped[target_key] = input_data[source_key]
            elif source_key in context.get("variables", {}):
                mapped[target_key] = context["variables"][source_key]
            elif source_key.startswith("$"):
                # 变量引用
                var_name = source_key[1:]
                if var_name in context.get("variables", {}):
                    mapped[target_key] = context["variables"][var_name]
            else:
                # 直接值
                mapped[target_key] = source_key

        return mapped

    async def _map_output_to_input(
        self, output_data: Dict[str, Any], mapping: Dict[str, str], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """将输出映射为下一步的输入"""
        if not mapping:
            return output_data

        mapped = {}

        for target_key, source_key in mapping.items():
            if source_key in output_data:
                mapped[target_key] = output_data[source_key]
            else:
                mapped[target_key] = output_data

        return mapped

    async def _should_skip_step(self, step: SkillChainStep, context: Dict[str, Any]) -> bool:
        """检查是否应该跳过步骤"""
        if not step.condition:
            return False

        # 简单的条件评估
        try:
            # 替换变量
            condition = step.condition
            for var_name, var_value in context.get("variables", {}).items():
                condition = condition.replace(f"${var_name}", str(var_value))

            # 安全评估（仅支持简单条件）
            if condition.startswith("skip_if:"):
                # 格式: skip_if:variable_name==value
                condition_part = condition[8:].strip()
                if "==" in condition_part:
                    var_name, expected = condition_part.split("==", 1)
                    var_name = var_name.strip()
                    expected = expected.strip()

                    actual = context.get("variables", {}).get(var_name)
                    return str(actual) == expected

            return False

        except Exception:
            return False

    def get_active_chains(self) -> List[str]:
        """获取活动的技能链 ID 列表"""
        return list(self._active_chains.keys())

    def get_chain_variables(self, chain_id: str) -> Dict[str, Any]:
        """获取技能链变量"""
        if chain_id not in self._active_chains:
            return {}

        return self._active_chains[chain_id].get("variables", {})

    def update_chain_variable(self, chain_id: str, key: str, value: Any) -> bool:
        """更新技能链变量"""
        if chain_id not in self._active_chains:
            return False

        self._active_chains[chain_id]["variables"][key] = value
        return True
