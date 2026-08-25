"""
Neurflow 执行引擎 — 垂直切片 6
工作流执行、节点调度、变量传递、事件通知
"""

from neurova.core.logger import get_logger
import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .dag import get_dag_validator, is_loop_back_edge
from .models import (
    ExecutionInstance,
    NodeExecutionResult,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from .node_registry import get_node_registry
from .safe_eval import safe_eval_condition
from .variable_resolver import ResolutionContext, get_variable_resolver

logger = get_logger(__name__)


class _NodeExecutionError(RuntimeError):
    """节点执行失败（携带首个失败信息，触发工作流级失败处理）"""


class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class ExecutionEventType(Enum):
    """执行事件类型枚举"""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_SKIPPED = "node_skipped"
    VARIABLE_SET = "variable_set"
    PAUSED = "paused"
    RESUMED = "resumed"


@dataclass
class ExecutionEvent:
    """执行事件

    使用 ExecutionEventType 枚举或字符串（向后兼容）
    """

    type: Union[ExecutionEventType, str]
    workflow_id: str
    execution_id: str
    node_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class WorkflowExecutor:
    """
    工作流执行器

    职责：
    1. 创建执行实例
    2. 拓扑排序节点
    3. 按顺序执行节点
    4. 传递变量和上下文
    5. 事件通知
    """

    def __init__(self):
        """初始化执行器"""
        self._dag_validator = get_dag_validator()
        self._variable_resolver = get_variable_resolver()
        self._node_registry = get_node_registry()
        # 确保内置节点已注册
        self._node_registry.ensure_builtin()
        self._event_handlers: List[Callable] = []
        self._instances: Dict[str, ExecutionInstance] = {}
        self._statuses: Dict[str, ExecutionStatus] = {}
        # loop 执行计划缓存（_plan_loops 产物，供嵌套 loop 递归驱动查询）
        self._loop_plans_cache: Dict[str, Dict[str, Any]] = {}

    def on_event(self, handler: Callable[[ExecutionEvent], None]) -> None:
        """注册事件处理器"""
        self._event_handlers.append(handler)

    def _emit(self, event: ExecutionEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error("事件处理器错误: %s", e)

    def create_instance(
        self,
        workflow: WorkflowDefinition,
        inputs: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ExecutionInstance:
        """
        创建执行实例

        Args:
            workflow: 工作流定义
            inputs: 输入变量
            user_id: 用户 ID
            agent_id: Agent ID

        Returns:
            ExecutionInstance
        """
        instance_id = f"exec_{uuid.uuid4().hex[:12]}"

        # 初始化变量
        variables = {}
        for var in workflow.variables:
            variables[var.name] = var.default_value

        instance = ExecutionInstance(
            id=instance_id,
            workflow_id=workflow.id,
            status=WorkflowStatus.DRAFT,
            inputs=inputs,
            variables=variables,
            started_at=time.time(),
            agent_id=agent_id,
            user_id=user_id,
        )

        self._instances[instance_id] = instance
        self._statuses[instance_id] = ExecutionStatus.PENDING

        return instance

    def get_status(self, execution_id: str) -> ExecutionStatus:
        """获取执行状态"""
        return self._statuses.get(execution_id, ExecutionStatus.PENDING)

    def validate_workflow(self, workflow: WorkflowDefinition):
        """验证工作流"""
        return self._dag_validator.validate(workflow.nodes, workflow.edges)

    async def execute(
        self,
        workflow: WorkflowDefinition,
        inputs: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        memory_manager: Optional[Any] = None,
        context_pool: Optional[Any] = None,
        emotion_module: Optional[Any] = None,
        crystallizer: Optional[Any] = None,
        session_id: Optional[str] = None,
        instance: Optional[ExecutionInstance] = None,
    ) -> ExecutionInstance:
        """
        执行工作流

        Args:
            workflow: 工作流定义
            inputs: 输入变量
            user_id: 用户 ID
            agent_id: Agent ID
            memory_manager: 记忆管理器（可选）
            context_pool: 上下文池（可选）
            emotion_module: 情感模块（可选）
            crystallizer: 结晶器（可选）
            session_id: 聊天会话 ID（可选；透传给 agent 节点的蜂群事件广播）
            instance: 已创建的执行实例（可选；画布运行端点预创建以便立即返回 ID）

        Returns:
            ExecutionInstance 执行实例
        """
        # 创建执行实例（外部已创建则复用）
        if instance is None:
            instance = self.create_instance(workflow, inputs, user_id, agent_id)
        else:
            self._instances[instance.id] = instance
            self._statuses[instance.id] = ExecutionStatus.PENDING
        execution_id = instance.id

        # 验证工作流
        validation = self.validate_workflow(workflow)
        if not validation.is_valid:
            instance.status = WorkflowStatus.FAILED
            instance.error = f"工作流验证失败: {'; '.join(validation.errors)}"
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED
            return instance

        # 获取执行路径（使用公共 API）
        execution_order = self._dag_validator.get_execution_path(workflow.nodes, workflow.edges)
        if not execution_order:
            instance.status = WorkflowStatus.FAILED
            instance.error = "拓扑排序失败：无法确定执行顺序（可能存在环）"
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED
            return instance

        # 构建节点映射
        node_map = {n.id: n for n in workflow.nodes}

        # 构建解析上下文
        resolution_context = ResolutionContext(
            workflow_id=workflow.id,
            execution_id=execution_id,
            inputs=inputs,
            variables=dict(instance.variables),
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            memory_manager=memory_manager,
            context_pool=context_pool,
            emotion_module=emotion_module,
            crystallizer=crystallizer,
        )

        # 发送工作流开始事件
        self._statuses[execution_id] = ExecutionStatus.RUNNING
        instance.status = WorkflowStatus.RUNNING

        self._emit(
            ExecutionEvent(
                type=ExecutionEventType.WORKFLOW_STARTED,
                workflow_id=workflow.id,
                execution_id=execution_id,
                data={"inputs": inputs},
            )
        )

        # 按拓扑分层执行：层内并发（asyncio.gather）、condition 真分支、loop 迭代驱动
        try:
            # 预构建边索引
            out_edges: Dict[str, List[WorkflowEdge]] = defaultdict(list)
            in_edges: Dict[str, List[WorkflowEdge]] = defaultdict(list)
            for e in workflow.edges:
                out_edges[e.source].append(e)
                in_edges[e.target].append(e)

            # loop 结构预计算（body 子图 / 迭代顺序 / 出口节点）
            loop_plans = self._plan_loops(workflow, node_map, out_edges, execution_order)
            self._loop_plans_cache = loop_plans

            # 拓扑分层（层内节点无依赖，可并发）
            layers = self._compute_layers(execution_order, in_edges)

            skipped: Set[str] = set()
            loop_driven: Set[str] = set()

            for layer in layers:
                # 本层中的 loop 节点单独驱动（不参与 gather）
                loop_nodes = [nid for nid in layer if node_map[nid].type == "builtin:loop"]
                active = [
                    nid
                    for nid in layer
                    if nid not in skipped and nid not in loop_driven and node_map[nid].type != "builtin:loop"
                ]

                # ── 层内并发执行普通节点 ──
                if active:
                    tasks = [
                        self._execute_single_node(
                            nid,
                            node_map[nid],
                            inputs,
                            resolution_context,
                            instance,
                            workflow.id,
                            execution_id,
                        )
                        for nid in active
                    ]
                    gathered = await asyncio.gather(*tasks, return_exceptions=True)

                    first_failure: Optional[str] = None
                    for nid, res in zip(active, gathered):
                        if isinstance(res, BaseException):
                            if first_failure is None:
                                first_failure = f"节点 '{nid}' 执行失败: {res}"
                    if first_failure is not None:
                        raise _NodeExecutionError(first_failure)

                # ── condition 真分支：传播跳过 ──
                for nid in active:
                    if node_map[nid].type == "builtin:condition":
                        nres = resolution_context.node_results.get(nid, {})
                        # exec_condition 把 branch 放在 output 内
                        branch = "true"
                        if isinstance(nres, dict):
                            output = nres.get("output")
                            if isinstance(output, dict) and output.get("branch"):
                                branch = output["branch"]
                        newly = self._propagate_skip(nid, branch, out_edges, in_edges, skipped, loop_driven)
                        for sid in newly:
                            self._record_skipped(sid, instance, workflow.id, execution_id)
                        skipped.update(newly)

                # ── loop 节点：驱动循环体迭代 ──
                for loop_id in loop_nodes:
                    if loop_id in skipped:
                        # loop 被跳过：body 与下游（loop_done 出边）一并跳过
                        self._record_skipped(loop_id, instance, workflow.id, execution_id)
                        inactive_loop_edges = {e.id for e in out_edges.get(loop_id, [])}
                        propagated = self._propagate_skip_edges(
                            inactive_loop_edges, out_edges, in_edges, skipped, loop_driven
                        )
                        for sid in propagated | loop_plans.get(loop_id, {}).get("body", set()):
                            if sid not in skipped:
                                self._record_skipped(sid, instance, workflow.id, execution_id)
                        skipped.update(propagated)
                        skipped.update(loop_plans.get(loop_id, {}).get("body", set()))
                        continue
                    await self._run_loop(
                        loop_id,
                        loop_plans.get(loop_id),
                        node_map[loop_id],
                        node_map,
                        out_edges,
                        in_edges,
                        inputs,
                        resolution_context,
                        instance,
                        workflow.id,
                        execution_id,
                        skipped,
                    )
                    loop_driven.update(loop_plans.get(loop_id, {}).get("body", set()))

            # 工作流完成
            instance.status = WorkflowStatus.COMPLETED
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.COMPLETED

            # 收集最终输出（最后一个有输出的节点）
            if instance.node_results:
                last_output = None
                for nid in execution_order:
                    nres = instance.node_results.get(nid)
                    if nres and nres.output is not None:
                        last_output = nres.output
                instance.outputs = {"result": last_output}

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.WORKFLOW_COMPLETED,
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    data={"outputs": instance.outputs},
                )
            )

        except _NodeExecutionError as e:
            # 节点失败（_execute_single_node 已记录节点级结果与事件）
            instance.status = WorkflowStatus.FAILED
            instance.error = str(e)
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.WORKFLOW_FAILED,
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    data={"error": instance.error},
                )
            )

        except Exception as e:
            instance.status = WorkflowStatus.FAILED
            instance.error = f"执行异常: {str(e)}"
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.WORKFLOW_FAILED,
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    data={"error": str(e)},
                )
            )

        return instance

    # ── 节点执行（单节点，含结果记录与事件） ──────────────────────

    async def _execute_single_node(
        self,
        node_id: str,
        node: WorkflowNode,
        inputs: Dict[str, Any],
        resolution_context: ResolutionContext,
        instance: ExecutionInstance,
        workflow_id: str,
        execution_id: str,
    ) -> None:
        """执行单个节点并记录结果/事件；失败抛异常由调用方聚合处理"""
        self._emit(
            ExecutionEvent(
                type=ExecutionEventType.NODE_STARTED,
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node_id,
            )
        )
        started_at = time.time()
        try:
            resolved_config = self._variable_resolver.resolve_config(node.config, resolution_context)
            result = await self._execute_node(
                node,
                resolved_config,
                {
                    "inputs": inputs,
                    "variables": resolution_context.variables,
                    "node_results": resolution_context.node_results,
                    "memory_manager": resolution_context.memory_manager,
                    "context_pool": resolution_context.context_pool,
                    "emotion_module": resolution_context.emotion_module,
                    "crystallizer": resolution_context.crystallizer,
                    "variable_resolver": self._variable_resolver,
                    "resolution_context": resolution_context,
                },
            )
            finished_at = time.time()
            instance.node_results[node_id] = NodeExecutionResult(
                node_id=node_id,
                status="success",
                output=result.get("output"),
                started_at=started_at,
                finished_at=finished_at,
                duration=finished_at - started_at,
            )
            resolution_context.node_results[node_id] = result

            # 变量节点特殊处理
            if node.type == "builtin:variable" and isinstance(result.get("output"), dict):
                var_output = result["output"]
                if "name" in var_output and "value" in var_output:
                    instance.variables[var_output["name"]] = var_output["value"]
                    resolution_context.variables[var_output["name"]] = var_output["value"]

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.NODE_COMPLETED,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=node_id,
                    data={"result": result},
                )
            )
        except Exception as e:
            finished_at = time.time()
            instance.node_results[node_id] = NodeExecutionResult(
                node_id=node_id,
                status="failed",
                output=None,
                error=str(e),
                started_at=started_at,
                finished_at=finished_at,
                duration=finished_at - started_at,
            )
            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.NODE_FAILED,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=node_id,
                    data={"error": str(e)},
                )
            )
            raise

    def _record_skipped(
        self, node_id: str, instance: ExecutionInstance, workflow_id: str, execution_id: str
    ) -> None:
        """记录被跳过的节点（condition 分支未命中 / 所属 loop 未执行）"""
        now = time.time()
        if node_id not in instance.node_results:
            instance.node_results[node_id] = NodeExecutionResult(
                node_id=node_id,
                status="skipped",
                output=None,
                started_at=now,
                finished_at=now,
                duration=0.0,
            )
        self._emit(
            ExecutionEvent(
                type=ExecutionEventType.NODE_SKIPPED,
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node_id,
            )
        )

    # ── condition 分支跳过传播 ────────────────────────────────────

    def _propagate_skip(
        self,
        cond_id: str,
        branch: str,
        out_edges: Dict[str, List[WorkflowEdge]],
        in_edges: Dict[str, List[WorkflowEdge]],
        skipped: Set[str],
        loop_driven: Set[str],
    ) -> Set[str]:
        """condition 节点定分支后，把未命中分支的边标记为不活跃并传播跳过。

        语义：某节点被跳过 ⇔ 其所有（非回边）入边都不活跃。
        边不活跃 ⇔ 边被 condition 判为未命中分支，或边的 source 已被跳过。
        汇聚点自然被保护：只要有任一活跃入边就不跳。
        """
        inactive_edges = {
            e.id for e in out_edges.get(cond_id, []) if e.source_handle and e.source_handle != branch
        }
        return self._propagate_skip_edges(inactive_edges, out_edges, in_edges, skipped, loop_driven)

    def _propagate_skip_edges(
        self,
        inactive_edge_ids: Set[str],
        out_edges: Dict[str, List[WorkflowEdge]],
        in_edges: Dict[str, List[WorkflowEdge]],
        skipped: Set[str],
        loop_driven: Set[str],
    ) -> Set[str]:
        """按"边活跃性"不动点传播跳过标记（汇聚点保护）"""
        newly: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for nid, pred_edges in in_edges.items():
                if nid in skipped or nid in loop_driven or nid in newly:
                    continue
                preds = [e for e in pred_edges if not is_loop_back_edge(e)]
                if not preds:
                    continue
                if all(
                    (e.id in inactive_edge_ids) or (e.source in newly) or (e.source in skipped)
                    for e in preds
                ):
                    newly.add(nid)
                    changed = True
        return newly

    # ── 分层（Kahn 层级，层内可并发） ─────────────────────────────

    def _compute_layers(
        self, execution_order: List[str], in_edges: Dict[str, List[WorkflowEdge]]
    ) -> List[List[str]]:
        """按拓扑序计算层级：节点层级 = 最长前驱层级 + 1；同层无依赖可并发"""
        node_layer: Dict[str, int] = {}
        for nid in execution_order:
            pred_layers = []
            for e in in_edges.get(nid, []):
                if is_loop_back_edge(e):
                    continue
                if e.source in node_layer:
                    pred_layers.append(node_layer[e.source])
            node_layer[nid] = (max(pred_layers) + 1) if pred_layers else 0

        by_layer: Dict[int, List[str]] = defaultdict(list)
        for nid in execution_order:
            by_layer[node_layer[nid]].append(nid)
        return [by_layer[i] for i in sorted(by_layer)]

    # ── loop 结构预计算与迭代驱动 ─────────────────────────────────

    def _plan_loops(
        self,
        workflow: WorkflowDefinition,
        node_map: Dict[str, WorkflowNode],
        out_edges: Dict[str, List[WorkflowEdge]],
        execution_order: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """预计算每个 loop 节点的 body 子图、迭代顺序与出口节点。

        body 入口 = loop 经 `current` 出边的目标；body 出口 = 经 `loop_body`
        端口回边回到 loop 的源节点。嵌套 loop 由内向外规划，外层 body 不含
        内层已认领的节点（内层 loop 节点本身保留，由外层迭代递归驱动）。
        """
        loop_ids = [nid for nid in execution_order if node_map[nid].type == "builtin:loop"]
        claimed: Dict[str, str] = {}  # node_id -> 认领它的 loop_id
        plans: Dict[str, Dict[str, Any]] = {}

        # 内层（拓扑序靠后）优先规划
        for loop_id in reversed(loop_ids):
            entries = [
                e.target
                for e in out_edges.get(loop_id, [])
                if e.source_handle == "current" and e.target in node_map and e.target != loop_id
            ]
            exits = [
                e.source
                for e in workflow.edges
                if e.target == loop_id and is_loop_back_edge(e) and e.source in node_map
            ]

            # BFS 收集 body 节点（不含 loop 自身、不含内层已认领节点）
            body: Set[str] = set()
            queue = [t for t in entries if t != loop_id and t not in claimed]
            while queue:
                nid = queue.pop()
                if nid == loop_id or nid in body:
                    continue
                if nid in claimed and claimed[nid] != loop_id:
                    continue  # 内层已认领，由内层驱动
                body.add(nid)
                for e in out_edges.get(nid, []):
                    if is_loop_back_edge(e):
                        continue  # 回边到 loop，不外溢
                    if e.target != loop_id and e.target not in body:
                        queue.append(e.target)

            # 认领（内层先规划，故此处认领的均为本层专属）
            for nid in body:
                claimed[nid] = loop_id

            # body 内拓扑排序（豁免回边）
            body_nodes = [node_map[nid] for nid in body]
            body_edges = [
                e
                for e in workflow.edges
                if e.source in body and e.target in body and not is_loop_back_edge(e)
            ]
            body_order = self._dag_validator.get_execution_path(body_nodes, body_edges)

            plans[loop_id] = {
                "entries": entries,
                "exits": [x for x in exits if x in body],
                "body": body,
                "order": body_order,
            }

        return plans

    async def _run_loop(
        self,
        loop_id: str,
        plan: Optional[Dict[str, Any]],
        node: WorkflowNode,
        node_map: Dict[str, WorkflowNode],
        out_edges: Dict[str, List[WorkflowEdge]],
        in_edges: Dict[str, List[WorkflowEdge]],
        inputs: Dict[str, Any],
        resolution_context: ResolutionContext,
        instance: ExecutionInstance,
        workflow_id: str,
        execution_id: str,
        global_skipped: Set[str],
    ) -> None:
        """驱动 loop 节点的循环体迭代（引擎级循环，body 节点由本方法调度）"""
        started_at = time.time()

        if not plan or not plan.get("order"):
            # 无循环体：退化为单次直通
            final_output = {"iterations": 0, "last_output": None, "broken": False}
            now = time.time()
            instance.node_results[loop_id] = NodeExecutionResult(
                node_id=loop_id,
                status="success",
                output=final_output,
                started_at=started_at,
                finished_at=now,
                duration=now - started_at,
            )
            resolution_context.node_results[loop_id] = {"output": final_output}
            return

        resolved_config = self._variable_resolver.resolve_config(node.config, resolution_context)
        try:
            max_iterations = int(resolved_config.get("max_iterations", 10))
        except (TypeError, ValueError):
            max_iterations = 10
        max_iterations = max(1, min(max_iterations, 1000))
        break_condition = resolved_config.get("break_condition", "") or ""

        # 初始迭代值：上游最后完成的输出，否则工作流输入
        current_value: Any = inputs
        for e in in_edges.get(loop_id, []):
            if is_loop_back_edge(e):
                continue
            up_res = resolution_context.node_results.get(e.source)
            if isinstance(up_res, dict) and up_res.get("output") is not None:
                current_value = up_res.get("output")

        broken = False
        iterations_done = 0

        for iteration in range(1, max_iterations + 1):
            # loop 的 output 在 body 执行期间 = 当前迭代值（body 用 ${loop_id.output} 引用）
            resolution_context.node_results[loop_id] = {
                "output": current_value,
                "iteration": iteration,
            }
            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.NODE_STARTED,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=loop_id,
                    data={"iteration": iteration},
                )
            )

            # 执行一轮 body（顺序；条件分支在迭代内生效）
            iter_skipped = set(global_skipped)
            for body_id in plan["order"]:
                body_node = node_map[body_id]
                if body_id in iter_skipped:
                    self._record_skipped(body_id, instance, workflow_id, execution_id)
                    continue

                if body_node.type == "builtin:loop":
                    # 嵌套 loop：递归驱动
                    await self._run_loop(
                        body_id,
                        self._loop_plans_cache.get(body_id),
                        body_node,
                        node_map,
                        out_edges,
                        in_edges,
                        inputs,
                        resolution_context,
                        instance,
                        workflow_id,
                        execution_id,
                        global_skipped,
                    )
                    continue

                if body_node.type == "builtin:condition":
                    await self._execute_single_node(
                        body_id, body_node, inputs, resolution_context, instance, workflow_id, execution_id
                    )
                    nres = resolution_context.node_results.get(body_id, {})
                    branch = "true"
                    if isinstance(nres, dict):
                        output = nres.get("output")
                        if isinstance(output, dict) and output.get("branch"):
                            branch = output["branch"]
                    newly = self._propagate_skip(body_id, branch, out_edges, in_edges, iter_skipped, set())
                    for sid in newly:
                        self._record_skipped(sid, instance, workflow_id, execution_id)
                    iter_skipped.update(newly)
                    continue

                await self._execute_single_node(
                    body_id, body_node, inputs, resolution_context, instance, workflow_id, execution_id
                )

            iterations_done = iteration

            # 迭代产出：出口节点（回边源）的最后输出
            for exit_id in plan["exits"]:
                exit_res = resolution_context.node_results.get(exit_id)
                if isinstance(exit_res, dict) and exit_res.get("output") is not None:
                    current_value = exit_res.get("output")

            # 跳出条件（安全 DSL 求值，无 eval）
            if break_condition and safe_eval_condition(
                break_condition,
                {
                    "$iteration": iteration,
                    "$current": current_value,
                    "$node": resolution_context.node_results,
                    "$var": resolution_context.variables,
                    "$input": inputs,
                },
            ):
                broken = True
                self._emit(
                    ExecutionEvent(
                        type=ExecutionEventType.NODE_COMPLETED,
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=loop_id,
                        data={"iteration": iteration, "broken": True},
                    )
                )
                break

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.NODE_COMPLETED,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=loop_id,
                    data={"iteration": iteration, "broken": False},
                )
            )

        # loop 最终结果（loop_done 语义：完成后向下游传递末次迭代值）
        finished_at = time.time()
        final_output = {"iterations": iterations_done, "last_output": current_value, "broken": broken}
        instance.node_results[loop_id] = NodeExecutionResult(
            node_id=loop_id,
            status="success",
            output=final_output,
            started_at=started_at,
            finished_at=finished_at,
            duration=finished_at - started_at,
        )
        resolution_context.node_results[loop_id] = {"output": final_output, "iterations": iterations_done}

    async def _execute_node(
        self, node: WorkflowNode, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行单个节点

        Args:
            node: 工作流节点
            config: 已解析的配置
            context: 执行上下文

        Returns:
            执行结果
        """
        # 内置节点处理
        if node.type == "builtin:start":
            return {"output": context.get("inputs", {})}

        elif node.type == "builtin:end":
            # 收集所有节点输出
            node_results = context.get("node_results", {})
            if node_results:
                last_output = None
                for node_id, result in node_results.items():
                    if result.get("output") is not None:
                        last_output = result["output"]
                return {"output": last_output}
            return {"output": None}

        elif node.type == "builtin:variable":
            return {"output": {"name": config.get("name", ""), "value": config.get("value")}}

        elif node.type == "builtin:transform":
            # 简单变换（实际应支持代码执行）
            expression = config.get("expression", "")
            return {"output": f"transform: {expression}"}

        # 注册表中的节点
        node_type = node.type
        executor = self._node_registry.get_executor(node_type)
        if executor:
            return await executor(config, context)

        # 默认返回
        return {"output": None}

    def cancel(self, execution_id: str) -> bool:
        """
        取消执行

        Args:
            execution_id: 执行 ID

        Returns:
            是否成功取消
        """
        if execution_id not in self._instances:
            return False

        instance = self._instances[execution_id]
        status = self._statuses.get(execution_id)

        # 只能取消运行中的执行
        if status not in [ExecutionStatus.RUNNING, ExecutionStatus.PAUSED]:
            return False

        instance.status = WorkflowStatus.CANCELLED
        instance.finished_at = time.time()
        instance.duration = instance.finished_at - instance.started_at
        instance.error = "执行已取消"
        self._statuses[execution_id] = ExecutionStatus.CANCELLED

        self._emit(
            ExecutionEvent(
                type=ExecutionEventType.WORKFLOW_FAILED,
                workflow_id=instance.workflow_id,
                execution_id=execution_id,
                data={"error": "执行已取消"},
            )
        )

        return True

    def resume(self, execution_id: str) -> bool:
        """
        恢复执行（人工审批后）

        Args:
            execution_id: 执行 ID

        Returns:
            是否成功恢复
        """
        if execution_id not in self._instances:
            return False

        instance = self._instances[execution_id]
        status = self._statuses.get(execution_id)

        # 只能恢复暂停的执行
        if status != ExecutionStatus.PAUSED:
            return False

        instance.status = WorkflowStatus.RUNNING
        self._statuses[execution_id] = ExecutionStatus.RUNNING

        self._emit(
            ExecutionEvent(type=ExecutionEventType.RESUMED, workflow_id=instance.workflow_id, execution_id=execution_id)
        )

        return True

    def get_recent_executions(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 10,
        since_timestamp: Optional[float] = None,
    ) -> List[ExecutionInstance]:
        """
        获取最近的执行实例

        Args:
            agent_id: 可选，按 Agent ID 过滤
            user_id: 可选，按用户 ID 过滤
            limit: 最大返回数量
            since_timestamp: 可选，只返回此时间戳之后的执行

        Returns:
            按开始时间降序排列的执行实例列表
        """
        now = time.time()
        if since_timestamp is None:
            # 默认返回最近 5 分钟内的执行
            since_timestamp = now - 300

        # 收集符合条件的实例
        recent = []
        for instance_id, instance in self._instances.items():
            # 时间过滤
            if instance.started_at < since_timestamp:
                continue

            # Agent ID 过滤
            if agent_id and instance.agent_id != agent_id:
                continue

            # User ID 过滤
            if user_id and instance.user_id != user_id:
                continue

            # 只包含已完成的执行
            status = self._statuses.get(instance_id)
            if status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]:
                recent.append(instance)

        # 按开始时间降序排序
        recent.sort(key=lambda x: x.started_at, reverse=True)

        # 限制返回数量
        return recent[:limit]


# 单例
_workflow_executor: Optional[WorkflowExecutor] = None


def get_workflow_executor() -> WorkflowExecutor:
    """获取工作流执行器单例"""
    global _workflow_executor
    if _workflow_executor is None:
        _workflow_executor = WorkflowExecutor()
    return _workflow_executor


__all__ = ["ExecutionStatus", "ExecutionEventType", "ExecutionEvent", "WorkflowExecutor", "get_workflow_executor"]
