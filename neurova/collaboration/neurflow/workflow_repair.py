"""工作流节点修复监督器（N5）。

循环（设计 §5.8.4）：
    draft 执行失败 → 读 failed 节点/错误 → 查 EKB → 生成候选
    → 只改 DRAFT 副本 → 再跑 → 失败回滚到快照 → 最多 5 轮
    → 通过后提交目标（已发布工作流 / 画布配置）→ 写 EKB 与审计

本模块复用：
- RSI 提案生命周期契约（`ProposalStatus` / `assert_can_decide` / `require_approver`）
- RSI 回滚快照管理器（只做快照与回滚留痕，真实状态由工作流版本回滚恢复）
- EKB（`skill_name=workflow_node_repair`）
不把 `RSIOrchestrator` 接到节点失败上。
"""

from __future__ import annotations

import copy
import datetime
import difflib
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.proposal_lifecycle import (
    ProposalStatus,
    assert_can_decide,
    assert_can_rollback,
    require_approver,
)

from .models import WorkflowStatus
from .node_registry import get_node_registry
from .workflow_definition_editor import (
    duplicateWorkflowDefinition,
    executeWorkflowDefinition,
    getWorkflowDefinitionStorage,
    recordWorkflowAudit,
    rollbackWorkflowDefinition,
    updateWorkflowDefinition,
)

logger = get_logger(__name__)

SKILL_NAME = "workflow_node_repair"
MAX_ROUNDS = 5
DEFAULT_TIME_BUDGET_SECONDS = 300

_SENSITIVE_KEY_TOKENS = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "private_key",
)


@dataclass
class RepairProposal:
    """修复提案（复用 RSI 提案状态机，不接 RSIOrchestrator）。"""

    proposal_id: str
    round: int
    target: str
    patch: Dict[str, Any]
    status: str = ProposalStatus.PENDING.value
    approver: str = ""
    reason: str = ""

    def toDict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "round": self.round,
            "target": self.target,
            "patch": self.patch,
            "status": self.status,
            "approver": self.approver,
            "reason": self.reason,
        }


def _redactValue(key: str, value: Any) -> Any:
    lowered = str(key or "").lower()
    if any(token in lowered for token in _SENSITIVE_KEY_TOKENS) and value not in (None, ""):
        return "[REDACTED]"
    return value


def _redactConfig(config: Any) -> Dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    return {str(key): _redactValue(str(key), value) for key, value in config.items()}


def _errorCode(error: str) -> str:
    text = str(error or "").lower()
    if any(token in text for token in ("keyerror", "missing", "required", "缺少", "必填")):
        return "missing_config"
    if any(token in text for token in ("env", "credential", "api key", "环境变量", "凭据")):
        return "missing_env"
    if "timeout" in text or "超时" in text:
        return "timeout"
    if "validation" in text or "校验" in text:
        return "validation"
    return "runtime_error"


def _blockDict(block: Any) -> Dict[str, Any]:
    if isinstance(block, dict):
        return block
    return {
        "id": str(getattr(block, "id", "") or ""),
        "title": str(getattr(block, "title", "") or ""),
        "type": str(getattr(block, "type", "") or ""),
        "required": bool(getattr(block, "required", False)),
        "default_value": getattr(block, "default_value", None),
    }


class WorkflowRepairSupervisor:
    def __init__(
        self,
        *,
        storage=None,
        execute: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        ekb=None,
        rollbackManager=None,
        customNodeService=None,
        canvasStore=None,
        canvasOpService=None,
        envPreflight: Optional[Callable[..., Dict[str, Any]]] = None,
        candidateGenerator: Optional[Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = None,
        auditor: Optional[Callable[[Dict[str, Any]], None]] = None,
        armed: Optional[bool] = None,
        allowCommit: Optional[bool] = None,
        maxRounds: int = MAX_ROUNDS,
        timeBudgetSeconds: Optional[float] = None,
    ) -> None:
        self._storage = storage or getWorkflowDefinitionStorage()
        self._execute = execute
        self._ekb = ekb
        self._rollbackManager = rollbackManager
        self._customNodeService = customNodeService
        self._canvasStore = canvasStore
        self._canvasOpService = canvasOpService
        self._envPreflight = envPreflight
        self._candidateGenerator = candidateGenerator
        self._auditor = auditor or recordWorkflowAudit
        self._armed = (
            armed
            if armed is not None
            else os.environ.get("NEUROVA_NODE_REPAIR") == "1"
        )
        self._allowCommit = (
            allowCommit
            if allowCommit is not None
            else os.environ.get("NEUROVA_NODE_REPAIR_COMMIT") == "1"
        )
        self._maxRounds = max(1, min(int(maxRounds or MAX_ROUNDS), MAX_ROUNDS))
        budget = timeBudgetSeconds
        if budget is None:
            budget = os.environ.get("NEUROVA_NODE_REPAIR_TIME_BUDGET_S") or DEFAULT_TIME_BUDGET_SECONDS
        self._timeBudgetSeconds = max(1.0, float(budget))

    # ==================== 依赖懒加载 ====================

    def _getCustomService(self):
        if self._customNodeService is None:
            from .custom_nodes import get_custom_node_service

            self._customNodeService = get_custom_node_service()
        return self._customNodeService

    def _getEkb(self):
        if self._ekb is None:
            from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

            self._ekb = get_experience_knowledge_base()
        return self._ekb

    def _getRollbackManager(self):
        if self._rollbackManager is None:
            from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

            self._rollbackManager = RSIRollbackManager()
        return self._rollbackManager

    def _getCanvasStore(self):
        if self._canvasStore is None:
            from neurova.collaboration.canvas_store import get_canvas_store

            self._canvasStore = get_canvas_store()
        return self._canvasStore

    def _getCanvasOpService(self):
        if self._canvasOpService is None:
            from neurova.collaboration.canvas_ops import CanvasOpService

            self._canvasOpService = CanvasOpService(store=self._getCanvasStore())
        return self._canvasOpService

    # ==================== 审计 / EKB ====================

    def _audit(self, action: str, **fields: Any) -> None:
        try:
            self._auditor({"action": action, **fields})
        except Exception as exc:  # noqa: BLE001 - 审计失败不阻断修复
            logger.warning("修复审计写入失败: %s", exc)

    def _recordEkb(
        self,
        *,
        nodeType: str,
        error: str,
        patch: Optional[Dict[str, Any]],
        outcome: str,
        success: bool,
        executionId: str = "",
        roundNo: int = 0,
        configBefore: Optional[Dict[str, Any]] = None,
        agentId: str = "",
    ) -> bool:
        try:
            from neurova.skills.models import ExperienceRecord

            exp = ExperienceRecord(
                skill_name=SKILL_NAME,
                context={
                    "node_type": nodeType,
                    "error_code": _errorCode(error),
                    "error": str(error or "")[:1000],
                    "config_before": _redactConfig(configBefore or {}),
                    "round": roundNo,
                    "outcome": outcome,
                },
                result={
                    "patch": patch,
                    "attempt": roundNo,
                    "outcome": outcome,
                    "execution_id": executionId,
                },
                success=bool(success),
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
            tags = [SKILL_NAME]
            if nodeType:
                tags.append(f"node:{nodeType}")
            tags.append(f"outcome:{outcome}")
            self._getEkb().add_experience_record(
                SKILL_NAME,
                exp,
                agent_id=agentId or "workflow_repair",
                tags=tags,
                evidence=True,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - EKB 失败不伪造成功
            logger.warning("修复经验写入失败: %s", exc)
            return False

    @staticmethod
    def _patchNodeType(patch: Optional[Dict[str, Any]]) -> str:
        for candidate in (patch or {}).get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("node_type"):
                return str(candidate["node_type"])
        return ""

    # ==================== 节点契约 / 候选 ====================

    def _schemaFor(self, nodeType: str) -> Optional[Dict[str, Any]]:
        try:
            if nodeType.startswith("custom:"):
                definition = self._getCustomService().get_node(nodeType)
            else:
                registry = get_node_registry()
                registry.ensure_builtin()
                definition = registry.get(nodeType)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取节点契约失败 %s: %s", nodeType, exc)
            return None
        if definition is None:
            return None
        return {
            "type": nodeType,
            "label": str(getattr(definition, "label", "") or ""),
            "category": str(getattr(definition, "category", "") or ""),
            "sub_blocks": [_blockDict(block) for block in (definition.sub_blocks or [])],
            "env_requirements": [
                str(item) for item in (definition.env_requirements or []) if str(item).strip()
            ],
        }

    def _replacementsFor(
        self, node, currentSchema: Dict[str, Any], draft
    ) -> List[Dict[str, Any]]:
        """同类别 + 标签近似的已注册节点（候选，不保证语义等价）。"""
        currentCategory = str(currentSchema.get("category") or "")
        currentLabel = str(currentSchema.get("label") or node.type)
        if not currentCategory:
            return []
        definitions: List[Any] = []
        try:
            registry = get_node_registry()
            registry.ensure_builtin()
            definitions.extend(registry.list_all())
        except Exception:  # noqa: BLE001
            pass
        try:
            definitions.extend(self._getCustomService().list_nodes())
        except Exception:  # noqa: BLE001
            pass

        usedTypes = {item.type for item in draft.nodes}
        candidates: List[Dict[str, Any]] = []
        for definition in definitions:
            otherType = str(getattr(definition, "type", "") or "")
            if not otherType or otherType == node.type:
                continue
            if str(getattr(definition, "status", "active") or "active") != "active":
                continue
            if str(getattr(definition, "category", "") or "") != currentCategory:
                continue
            otherLabel = str(getattr(definition, "label", "") or otherType)
            ratio = difflib.SequenceMatcher(None, currentLabel, otherLabel).ratio()
            if ratio < 0.75:
                continue
            candidates.append(
                {
                    "action": "replace_node",
                    "node_id": node.id,
                    "node_type": node.type,
                    "from_type": node.type,
                    "to_type": otherType,
                    "reason": (
                        f"同类别近似节点候选（相似度 {ratio:.2f}）："
                        f"{currentLabel} → {otherLabel}；需人工确认语义"
                    ),
                    "source": "schema",
                }
            )
            if len(candidates) >= 2:
                break
        return [c for c in candidates if c.get("to_type") not in usedTypes]

    def _diagnose(self, draft, runResult: Dict[str, Any]) -> Dict[str, Any]:
        nodeMap = {node.id: node for node in draft.nodes}
        failed: List[Dict[str, Any]] = []
        for nodeId, nodeResult in (runResult.get("node_results") or {}).items():
            if not isinstance(nodeResult, dict):
                continue
            status = str(nodeResult.get("status") or "")
            if status not in ("failed", "error", "cancelled"):
                continue
            node = nodeMap.get(nodeId)
            failed.append(
                {
                    "node_id": nodeId,
                    "node_type": node.type if node else "",
                    "error": str(nodeResult.get("error") or runResult.get("error") or ""),
                    "config": copy.deepcopy(node.config) if node else {},
                }
            )
        if not failed and runResult.get("error"):
            failed.append(
                {
                    "node_id": "",
                    "node_type": "",
                    "error": str(runResult.get("error")),
                    "config": {},
                }
            )
        return {
            "failed_nodes": failed,
            "error": str(runResult.get("error") or ""),
            "execution_id": str(runResult.get("execution_id") or ""),
            "ekb_matches": [],
        }

    def _ekbCandidates(
        self, diagnosis: Dict[str, Any], draft
    ) -> tuple:
        nodeIds = {node.id for node in draft.nodes}
        matches: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []
        try:
            ekb = self._getEkb()
        except Exception as exc:  # noqa: BLE001
            logger.warning("EKB 不可用: %s", exc)
            return matches, candidates

        for failed in diagnosis.get("failed_nodes") or []:
            nodeType = str(failed.get("node_type") or "")
            error = str(failed.get("error") or "")
            try:
                found = ekb.find_similar_experiences(
                    skill_name=SKILL_NAME,
                    context={"user_input": error or nodeType, "topic": nodeType},
                    limit=5,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("EKB 检索失败: %s", exc)
                continue
            for match in found or []:
                result = match.get("result")
                patch = result.get("patch") if isinstance(result, dict) else None
                summary = {
                    "id": match.get("id"),
                    "success": match.get("success"),
                    "tags": match.get("tags") or [],
                    "similarity_score": match.get("similarity_score"),
                    "patch": copy.deepcopy(patch) if isinstance(patch, dict) else None,
                }
                matches.append(summary)
                if not isinstance(patch, dict):
                    continue
                nodeId = str(patch.get("node_id") or failed.get("node_id") or "")
                if nodeId not in nodeIds:
                    continue
                if patch.get("action") == "set_config":
                    if not isinstance(patch.get("set"), dict):
                        continue
                    candidates.append(
                        {
                            "action": "set_config",
                            "node_id": nodeId,
                            "node_type": nodeType,
                            "set": dict(patch.get("set") or {}),
                            "remove": [
                                str(key) for key in (patch.get("remove") or [])
                            ],
                            "reason": "EKB 历史修复候选（仍需重新评估）",
                            "source": "ekb",
                        }
                    )
                elif patch.get("action") == "replace_node":
                    toType = str(patch.get("to_type") or "")
                    if not toType or self._schemaFor(toType) is None:
                        continue
                    candidates.append(
                        {
                            "action": "replace_node",
                            "node_id": nodeId,
                            "node_type": nodeType,
                            "from_type": nodeType,
                            "to_type": toType,
                            "reason": "EKB 历史换节点候选（仍需重新评估）",
                            "source": "ekb",
                        }
                    )
        return matches, candidates

    def _defaultCandidates(
        self, diagnosis: Dict[str, Any], draft
    ) -> tuple:
        matches, candidates = self._ekbCandidates(diagnosis, draft)
        nodeMap = {node.id: node for node in draft.nodes}

        for failed in diagnosis.get("failed_nodes") or []:
            nodeId = str(failed.get("node_id") or "")
            node = nodeMap.get(nodeId)
            if node is None:
                continue
            schema = self._schemaFor(node.type)
            if schema is None:
                continue
            blocks = schema.get("sub_blocks") or []
            declaredIds = [str(block.get("id") or "") for block in blocks if block.get("id")]
            if not declaredIds:
                if not any(item.get("node_id") == nodeId for item in candidates):
                    candidates.extend(self._replacementsFor(node, schema, draft))
                continue
            requiredDefaults = {
                str(block.get("id")): block.get("default_value")
                for block in blocks
                if block.get("required") and block.get("id")
            }
            config = node.config or {}
            unknown = [str(key) for key in config if str(key) not in declaredIds]
            missing = [key for key in requiredDefaults if key not in config]
            consumed = set()

            for unknownKey in unknown:
                close = difflib.get_close_matches(
                    unknownKey, [key for key in missing if key not in consumed], n=1, cutoff=0.6
                )
                if not close:
                    continue
                matched = close[0]
                consumed.add(matched)
                candidates.append(
                    {
                        "action": "set_config",
                        "node_id": nodeId,
                        "node_type": node.type,
                        "set": {matched: config[unknownKey]},
                        "remove": [unknownKey],
                        "reason": f"配置键 '{unknownKey}' 疑似应为 '{matched}'",
                        "source": "schema",
                    }
                )

            for key in missing:
                if key in consumed:
                    continue
                default = requiredDefaults[key]
                if default is None:
                    candidates.append(
                        {
                            "action": "needs_input",
                            "node_id": nodeId,
                            "node_type": node.type,
                            "missing_keys": [key],
                            "reason": f"必填配置 '{key}' 缺失且无默认值，需要用户提供",
                            "source": "schema",
                        }
                    )
                    continue
                candidates.append(
                    {
                        "action": "set_config",
                        "node_id": nodeId,
                        "node_type": node.type,
                        "set": {key: default},
                        "remove": [],
                        "reason": f"必填配置 '{key}' 缺失，使用节点声明的默认值",
                        "source": "schema",
                    }
                )

            if not any(item.get("node_id") == nodeId for item in candidates):
                candidates.extend(self._replacementsFor(node, schema, draft))

        deduped: List[Dict[str, Any]] = []
        seen = set()
        for candidate in candidates:
            key = (
                candidate.get("action"),
                candidate.get("node_id"),
                tuple(sorted((candidate.get("set") or {}).keys())),
                tuple(sorted(candidate.get("remove") or [])),
                tuple(candidate.get("missing_keys") or []),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return matches, deduped

    def _candidates(self, diagnosis: Dict[str, Any], draft) -> tuple:
        if self._candidateGenerator is not None:
            generated = self._candidateGenerator(diagnosis) or []
            return diagnosis.get("ekb_matches") or [], list(generated)
        return self._defaultCandidates(diagnosis, draft)

    # ==================== 应用 / 回滚 ====================

    def _applyCandidates(
        self,
        draft,
        candidates: List[Dict[str, Any]],
        baseVersion: int,
        actorId: str,
        batchId: str,
    ) -> Dict[str, Any]:
        nodes = copy.deepcopy(draft.nodes)
        byId = {node.id: node for node in nodes}
        for candidate in candidates:
            action = candidate.get("action")
            node = byId.get(str(candidate.get("node_id") or ""))
            if node is None:
                continue
            if action == "replace_node":
                toType = str(candidate.get("to_type") or "")
                if toType:
                    node.type = toType
                continue
            if action != "set_config":
                continue
            config = dict(node.config or {})
            for key in candidate.get("remove") or []:
                config.pop(str(key), None)
            config.update(dict(candidate.get("set") or {}))
            node.config = config
        return updateWorkflowDefinition(
            draft.id,
            nodes=[node.__dict__ for node in nodes],
            edges=[edge.__dict__ for edge in draft.edges],
            baseVersion=baseVersion,
            actorId=actorId,
            batchId=batchId,
            note="self_heal round patch",
            storage=self._storage,
        )

    def _createSnapshot(self, draft, version: int) -> str:
        return self._getRollbackManager().create_snapshot(
            {
                "workflow_id": draft.id,
                "version": version,
                "nodes": copy.deepcopy([node.__dict__ for node in draft.nodes]),
                "edges": copy.deepcopy([edge.__dict__ for edge in draft.edges]),
            }
        )

    def _rollbackDraft(
        self,
        draft,
        snapshotId: str,
        snapshotVersion: int,
        actorId: str,
        batchId: str,
        proposal: Optional[RepairProposal],
    ) -> Dict[str, Any]:
        executed = self._getRollbackManager().execute_rollback(snapshotId)
        restored = rollbackWorkflowDefinition(
            draft.id,
            targetVersion=snapshotVersion,
            actorId=actorId,
            batchId=batchId,
            storage=self._storage,
        )
        if proposal is not None and proposal.status == ProposalStatus.APPLIED.value:
            assert_can_rollback(proposal.status)
            proposal.status = ProposalStatus.ROLLED_BACK.value
        return {
            "snapshot_id": snapshotId,
            "snapshot_version": snapshotVersion,
            "rollback_manager_executed": bool(executed),
            "restored": restored,
        }

    # ==================== 提交 ====================

    def _commitWorkflow(
        self,
        targetId: str,
        targetVersion: int,
        draft,
        actorId: str,
        batchId: str,
    ) -> Dict[str, Any]:
        result = updateWorkflowDefinition(
            targetId,
            nodes=[node.__dict__ for node in draft.nodes],
            edges=[edge.__dict__ for edge in draft.edges],
            baseVersion=targetVersion,
            actorId=actorId,
            batchId=batchId,
            note="self_heal commit",
            storage=self._storage,
        )
        if result.get("success"):
            target = self._storage.get_workflow(targetId)
            status = str(getattr(getattr(target, "status", None), "value", ""))
            if status == "published":
                try:
                    self._storage.setSafeVersion(
                        targetId,
                        result["version"],
                        reason="repair_verified",
                        evidence={
                            "actor": actorId,
                            "batch_id": batchId,
                            "draft_workflow_id": draft.id,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - 安全版本提升失败如实留痕
                    logger.warning("修复提交后安全版本提升失败: %s", exc)
        return result

    async def _commitCanvas(
        self,
        targetId: str,
        draft,
        actorId: str,
        sessionId: str,
    ) -> Dict[str, Any]:
        store = self._getCanvasStore()
        original = store.get(targetId, requester_id=actorId or None)
        if original is None:
            return {"success": False, "code": "not_found", "error": "画布不存在或无权访问"}

        originalNodes = {node.get("id"): node for node in original.get("nodes") or []}
        draftNodes = {node.id: node for node in draft.nodes}
        configChanges = []
        structural = []
        for nodeId, node in draftNodes.items():
            if nodeId not in originalNodes:
                structural.append({"kind": "added_node", "node_id": nodeId})
                continue
            if dict(node.config or {}) != dict(originalNodes[nodeId].get("config") or {}):
                configChanges.append(nodeId)
        for nodeId in originalNodes:
            if nodeId not in draftNodes:
                structural.append({"kind": "removed_node", "node_id": nodeId})
        originalEdgeIds = {edge.get("id") for edge in original.get("edges") or []}
        draftEdgeIds = {edge.id for edge in draft.edges}
        if originalEdgeIds != draftEdgeIds:
            structural.append({"kind": "edges_changed"})

        service = self._getCanvasOpService()
        applied = []
        try:
            for nodeId in configChanges:
                current = store.get(targetId, requester_id=actorId or None)
                if current is None:
                    return {"success": False, "code": "not_found", "error": "画布读取失败"}
                await service.set_config(
                    targetId,
                    nodeId,
                    dict(draftNodes[nodeId].config or {}),
                    base_version=int(current["version"]),
                    session_id=sessionId or None,
                    actor=actorId or "agent",
                    replace=True,
                )
                applied.append(nodeId)
        except Exception as exc:  # noqa: BLE001 - 版本冲突等转结构化失败
            return {
                "success": False,
                "code": "commit_failed",
                "error": f"画布提交失败: {exc}",
                "applied_nodes": applied,
            }
        return {
            "success": True,
            "kind": "canvas",
            "canvas_id": targetId,
            "applied_config_nodes": applied,
            "deferred_changes": structural,
        }

    # ==================== 主循环 ====================

    async def repair(
        self,
        workflowId: Optional[str] = None,
        canvasId: Optional[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
        commit: bool = True,
        actorId: str = "",
        actorAgentId: Optional[str] = None,
        sessionId: str = "",
        batchId: str = "",
    ) -> Dict[str, Any]:
        started = time.monotonic()
        result: Dict[str, Any] = {
            "success": False,
            "status": "failed",
            "rounds": 0,
            "target": {},
            "draft_workflow_id": "",
            "missing_env": [],
            "preflight": {},
            "diagnosis": {},
            "candidates_considered": [],
            "proposals": [],
            "rollbacks": [],
            "committed": False,
            "commit": {},
            "ekb_recorded": False,
        }
        proposals: List[RepairProposal] = []

        def pubResult() -> Dict[str, Any]:
            result["proposals"] = [proposal.toDict() for proposal in proposals]
            return result

        if bool(workflowId) == bool(canvasId):
            result["status"] = "error"
            result["error"] = "workflow_id 与 canvas_id 必须且只能提供一个"
            return pubResult()

        # ── 目标与 DRAFT 副本 ──────────────────────────────
        canvasOriginal = None
        canvasVersion = 0
        if workflowId:
            target = self._storage.get_workflow(
                workflowId, requester_id=actorId or None
            )
            if target is None:
                result["status"] = "error"
                result["code"] = "not_found"
                result["error"] = f"工作流不存在或无权访问: {workflowId}"
                return pubResult()
            targetVersion = self._storage.get_workflow_version_number(workflowId)
            duplicated = duplicateWorkflowDefinition(
                workflowId,
                name=f"{target.name} (自愈草稿)",
                actorId=actorId,
                batchId=batchId,
                storage=self._storage,
            )
            if not duplicated.get("success"):
                result["status"] = "error"
                result["code"] = duplicated.get("code") or "draft_failed"
                result["error"] = duplicated.get("error") or "创建自愈草稿失败"
                return pubResult()
            draftId = duplicated["workflow_id"]
            result["target"] = {"kind": "workflow", "id": workflowId, "version": targetVersion}
        else:
            canvasStore = self._getCanvasStore()
            canvasOriginal = canvasStore.get(canvasId, requester_id=actorId or None)
            if canvasOriginal is None:
                result["status"] = "error"
                result["code"] = "not_found"
                result["error"] = f"画布不存在或无权访问: {canvasId}"
                return pubResult()
            canvasVersion = int(canvasOriginal.get("version") or 0)
            try:
                from neurova.collaboration.canvas_bridge import canvas_to_workflow

                compiled = canvas_to_workflow(
                    canvasOriginal,
                    name=f"{canvasOriginal.get('name') or canvasId} (自愈草稿)",
                )
            except Exception as exc:  # noqa: BLE001
                result["status"] = "error"
                result["code"] = "invalid_canvas"
                result["error"] = f"画布无法编译为工作流草稿: {exc}"
                return pubResult()
            draftId = f"canvas_repair_{canvasId}_{uuid.uuid4().hex[:8]}"
            compiled.id = draftId
            compiled.status = WorkflowStatus.DRAFT
            compiled.user_id = actorId or None
            compiled.origin = "nl_chat"
            compiled.created_at = time.time()
            compiled.updated_at = time.time()
            compiled.metadata = dict(compiled.metadata or {})
            compiled.metadata.update(
                {
                    "source_canvas_id": canvasId,
                    "source_canvas_version": canvasVersion,
                    "batch_id": batchId,
                }
            )
            self._storage.save_workflow(compiled, user_id=actorId or None)
            result["target"] = {"kind": "canvas", "id": canvasId, "version": canvasVersion}
        result["draft_workflow_id"] = draftId

        draft = self._storage.get_workflow(draftId)
        if draft is None:
            result["status"] = "error"
            result["code"] = "draft_failed"
            result["error"] = "自愈草稿创建后不可读"
            return pubResult()
        initialVersion = self._storage.get_workflow_version_number(draftId)

        # ── 环境预检（缺环境不烧轮次）─────────────────────
        nodeTypes = sorted({node.type for node in draft.nodes})
        preflightFn = self._envPreflight
        if preflightFn is None:
            from .env_preflight import preflightNodeEnv

            preflightFn = preflightNodeEnv
        preflight = preflightFn(
            nodeTypes,
            customNodeService=self._getCustomService(),
        )
        result["preflight"] = preflight
        result["missing_env"] = list(preflight.get("missing") or [])
        if preflight.get("missing") or preflight.get("unknown_types") or preflight.get("inactive_types"):
            result["status"] = "blocked"
            result["error"] = (
                preflight.get("error")
                or "缺少运行环境，已停在预检阶段：" + ", ".join(preflight.get("missing") or [])
            )
            for nodeType, names in (preflight.get("declared") or {}).items():
                for name in names:
                    if name in result["missing_env"]:
                        result["ekb_recorded"] = self._recordEkb(
                            nodeType=nodeType,
                            error=result["error"],
                            patch=None,
                            outcome="blocked",
                            success=False,
                            roundNo=0,
                            agentId=actorAgentId or actorId,
                        ) or result["ekb_recorded"]
            self._audit(
                "repair_blocked",
                workflow_id=str(result["target"].get("id") or ""),
                draft_workflow_id=draftId,
                actor=actorId,
                batch_id=batchId,
                missing_env=result["missing_env"],
            )
            return pubResult()

        # ── 授权闸门 ─────────────────────────────────────
        if not self._armed:
            result["status"] = "needs_approval"
            result["reason"] = "repair_not_armed"
            result["error"] = "自动修复未武装（NEUROVA_NODE_REPAIR!=1），仅生成诊断与草稿"
            return pubResult()
        if commit and not self._allowCommit:
            result["status"] = "needs_approval"
            result["reason"] = "commit_not_allowed"
            result["error"] = "提交已发布工作流/画布需要批次审批"
            return pubResult()

        # ── 执行循环 ─────────────────────────────────────
        async def runDraft() -> Dict[str, Any]:
            if self._execute is not None:
                return await self._execute(draftId, dict(inputs or {}))
            return await executeWorkflowDefinition(
                draftId,
                inputs=dict(inputs or {}),
                allowDraft=True,
                actorId=actorId,
                actorAgentId=actorAgentId,
                sessionId=sessionId,
                storage=self._storage,
            )

        lastProposal: Optional[RepairProposal] = None
        lastSnapshot: Optional[str] = None
        lastSnapshotVersion: Optional[int] = None
        lastPatch: Optional[Dict[str, Any]] = None
        finalCommit: Dict[str, Any] = {}

        while result["rounds"] < self._maxRounds:
            if time.monotonic() - started > self._timeBudgetSeconds:
                result["status"] = "budget_exhausted"
                result["error"] = "修复时间预算已用尽"
                break

            runResult = await runDraft()
            result["rounds"] += 1
            executionId = str(runResult.get("execution_id") or "")

            if runResult.get("success"):
                if lastProposal is not None:
                    lastProposal.status = ProposalStatus.APPLIED.value
                result["diagnosis"] = result.get("diagnosis") or {}
                if commit:
                    if result["target"].get("kind") == "workflow":
                        finalCommit = self._commitWorkflow(
                            str(result["target"].get("id") or ""),
                            int(result["target"].get("version") or 0),
                            draft,
                            actorId,
                            batchId,
                        )
                    else:
                        finalCommit = await self._commitCanvas(
                            str(result["target"].get("id") or ""),
                            draft,
                            actorId,
                            sessionId,
                        )
                    result["commit"] = finalCommit
                    if not finalCommit.get("success"):
                        result["status"] = "commit_failed"
                        result["error"] = finalCommit.get("error") or "提交失败"
                        result["ekb_recorded"] = self._recordEkb(
                            nodeType=self._patchNodeType(lastPatch),
                            error=result["error"],
                            patch=lastPatch,
                            outcome="commit_failed",
                            success=False,
                            executionId=executionId,
                            roundNo=result["rounds"],
                            agentId=actorAgentId or actorId,
                        ) or result["ekb_recorded"]
                        return pubResult()
                result["committed"] = bool(commit)
                result["success"] = True
                result["status"] = "completed"
                result["ekb_recorded"] = self._recordEkb(
                    nodeType=self._patchNodeType(lastPatch),
                    error="",
                    patch=lastPatch,
                    outcome="committed" if commit else "draft_verified",
                    success=True,
                    executionId=executionId,
                    roundNo=result["rounds"],
                    agentId=actorAgentId or actorId,
                ) or result["ekb_recorded"]
                self._audit(
                    "repair_success",
                    workflow_id=str(result["target"].get("id") or ""),
                    draft_workflow_id=draftId,
                    actor=actorId,
                    batch_id=batchId,
                    rounds=result["rounds"],
                    committed=result["committed"],
                    execution_id=executionId,
                )
                return pubResult()

            # 失败：先回滚上一轮补丁，再基于恢复后的草稿诊断
            if lastProposal is not None and lastSnapshot is not None:
                rollback = self._rollbackDraft(
                    draft,
                    lastSnapshot,
                    int(lastSnapshotVersion or initialVersion),
                    actorId,
                    batchId,
                    lastProposal,
                )
                result["rollbacks"].append(rollback)
                result["ekb_recorded"] = self._recordEkb(
                    nodeType=self._patchNodeType(lastPatch),
                    error=runResult.get("error") or "",
                    patch=lastPatch,
                    outcome="rolled_back",
                    success=False,
                    executionId=executionId,
                    roundNo=result["rounds"],
                    agentId=actorAgentId or actorId,
                ) or result["ekb_recorded"]
                self._audit(
                    "repair_rollback",
                    workflow_id=str(result["target"].get("id") or ""),
                    draft_workflow_id=draftId,
                    actor=actorId,
                    batch_id=batchId,
                    round=result["rounds"],
                    snapshot_id=lastSnapshot,
                )
                draft = self._storage.get_workflow(draftId) or draft
                lastProposal = None
                lastSnapshot = None
                lastSnapshotVersion = None
                lastPatch = None

            diagnosis = self._diagnose(draft, runResult)
            result["diagnosis"] = diagnosis
            ekbMatches, candidates = self._candidates(diagnosis, draft)
            diagnosis["ekb_matches"] = ekbMatches
            result["candidates_considered"].extend(candidates)

            if not candidates:
                result["status"] = "needs_agent"
                result["error"] = "没有可自动生成的修复候选，需要 Agent 进一步诊断"
                result["ekb_recorded"] = self._recordEkb(
                    nodeType=(diagnosis.get("failed_nodes") or [{}])[0].get("node_type", ""),
                    error=diagnosis.get("error") or "",
                    patch=None,
                    outcome="no_candidate",
                    success=False,
                    executionId=executionId,
                    roundNo=result["rounds"],
                    agentId=actorAgentId or actorId,
                ) or result["ekb_recorded"]
                return pubResult()

            if any(item.get("action") == "needs_input" for item in candidates):
                result["status"] = "needs_input"
                result["error"] = "存在必填配置缺失且无默认值，需要用户提供"
                return pubResult()

            if any(item.get("action") != "set_config" and item.get("action") != "replace_node" for item in candidates):
                result["status"] = "needs_approval"
                result["reason"] = "candidate_requires_approval"
                result["error"] = "候选包含建节点/缺少必填值，需审批后执行"
                return pubResult()

            if result["rounds"] >= self._maxRounds:
                break

            currentVersion = self._storage.get_workflow_version_number(draftId)
            snapshotId = self._createSnapshot(draft, currentVersion)
            proposal = RepairProposal(
                proposal_id=f"repair_{uuid.uuid4().hex[:12]}",
                round=result["rounds"] + 1,
                target=draftId,
                patch={"candidates": copy.deepcopy(candidates)},
                reason="auto config repair",
            )
            approver = require_approver(
                "workflow_repair:auto", action="approve"
            )
            assert_can_decide(proposal.status)
            proposal.status = ProposalStatus.APPLIED.value
            proposal.approver = approver
            proposals.append(proposal)

            applied = self._applyCandidates(
                draft,
                candidates,
                baseVersion=currentVersion,
                actorId=actorId,
                batchId=batchId,
            )
            if not applied.get("success"):
                assert_can_rollback(proposal.status)
                proposal.status = ProposalStatus.ROLLED_BACK.value
                result["status"] = "needs_agent"
                result["error"] = applied.get("error") or "候选应用失败"
                return pubResult()

            lastProposal = proposal
            lastSnapshot = snapshotId
            lastSnapshotVersion = currentVersion
            lastPatch = {"candidates": copy.deepcopy(candidates)}
            draft = self._storage.get_workflow(draftId) or draft
            self._audit(
                "repair_round",
                workflow_id=str(result["target"].get("id") or ""),
                draft_workflow_id=draftId,
                actor=actorId,
                batch_id=batchId,
                round=result["rounds"],
                candidates=[
                    {
                        "node_id": item.get("node_id"),
                        "action": item.get("action"),
                        "source": item.get("source"),
                    }
                    for item in candidates
                ],
            )

        # 轮次/预算用尽：回滚最后一轮补丁，保留草稿供诊断
        if lastProposal is not None and lastSnapshot is not None:
            rollback = self._rollbackDraft(
                draft,
                lastSnapshot,
                int(lastSnapshotVersion or initialVersion),
                actorId,
                batchId,
                lastProposal,
            )
            result["rollbacks"].append(rollback)
        if result["status"] == "failed" or result["status"] == "budget_exhausted":
            if result["status"] == "failed":
                result["error"] = f"{self._maxRounds} 轮内未修复"
            self._audit(
                "repair_failed",
                workflow_id=str(result["target"].get("id") or ""),
                draft_workflow_id=draftId,
                actor=actorId,
                batch_id=batchId,
                rounds=result["rounds"],
                status=result["status"],
            )
        return pubResult()



__all__ = ["WorkflowRepairSupervisor", "RepairProposal", "SKILL_NAME"]
