"""状态事件桥（specs/2026-11-12 §5 W3）：EventBus → 状态机 → 咽喉。

世界"被持续观察"的最小形态：启动时按各状态机的 event_bindings 向既有事件总线
登记订阅；事件到达→映射 descriptor 取 subject/state→构造 AdmissionRequest→admit
（身份按 descriptor **显式**带 tenant/agent，不从 ContextVar 猜——AGENTS.md §3
身份纪律）。未映射事件零写入；admit 拒如实记日志不重试（fail-closed）。

缺省 off（`NEUROVA_KB_STATE_EVENT_BRIDGE`），翻 on 须活体判据——配置开关语义
与 enterprise 源 enabled 同款：关闸＝零订阅零网络。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 事件桥开关（缺省 off：新能力的默认态必须是旧行为）
BRIDGE_ENV = "NEUROVA_KB_STATE_EVENT_BRIDGE"

#: 总线订阅的 module 名（退订按它走）
module_name = "kb_state_event_bridge"

_ON_VALUES = ("1", "true", "on", "yes")


def bridgeEnabled() -> bool:
    """缺省 off：显式 opt-in 才订阅（新能力默认态＝旧行为）。"""
    return str(os.environ.get(BRIDGE_ENV) or "").strip().lower() in _ON_VALUES


class StateEventBridge:
    """事件→状态写入的桥。start/stop 成对（订阅与退订同批）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._subscriptions: List[Any] = []
        self._bus: Any = None

    def start(self) -> int:
        """按启用状态机的 event_bindings 订阅；返回订阅条数（off 时为 0）。"""
        if not bridgeEnabled():
            return 0
        from neurova.core.event_bus import resolveEventBus

        from .ontology.state_machine_registry import StateMachineRegistry

        self._bus = resolveEventBus()
        bindings = StateMachineRegistry(self._store).eventBindings(tenantId="default")
        count = 0
        for binding in bindings:
            eventName = str(binding.get("eventName") or "").strip()
            if not eventName:
                continue
            handler = self._makeHandler(binding)
            self._subscriptions.append(self._bus.subscribe(
                eventName, handler, module_name=module_name))
            count += 1
        if count:
            logger.info("state_event_bridge: 已按 %d 条 event_bindings 订阅（%s）",
                        count, sorted({str(b.get("eventName")) for b in bindings}))
        return count

    def stop(self) -> int:
        """退掉本桥全部订阅。"""
        if self._bus is None:
            return 0
        count = self._bus.unsubscribe_module(module_name)
        self._subscriptions.clear()
        self._bus = None
        return count

    def _makeHandler(self, binding: Dict[str, Any]):
        subjectField = str(binding.get("subjectField") or "").strip()
        stateField = str(binding.get("stateField") or "").strip()
        termId = str(binding.get("term_id") or "").strip()
        agentId = str(binding.get("agentId") or "default")
        tenantId = str(binding.get("tenantId") or "default")

        def handler(event: Any) -> None:
            """事件→admit。总线契约：handler 收 Event 对象（event.name/.data）。
            未映射数据形状/闭集外状态：admit 拒即留名，不重试。"""
            event_name = str(getattr(event, "name", "") or "")
            data = getattr(event, "data", None)
            if not isinstance(data, dict):
                logger.warning("state_event_bridge: 事件 %s 数据非 dict，零写入", event_name)
                return
            subjectLabel = str(data.get(subjectField) or "").strip()
            newState = str(data.get(stateField) or "").strip()
            if not subjectLabel or not newState:
                logger.warning(
                    "state_event_bridge: 事件 %s 缺 %s/%s，零写入",
                    event_name, subjectField, stateField)
                return
            # 状态机在册才写（未映射机/机已删：事件不发状态）
            from .ontology.state_machine_registry import StateMachineRegistry

            machine = StateMachineRegistry(self._store).get(termId, tenantId=tenantId)
            if machine is None or not machine.get("enabled"):
                logger.warning(
                    "state_event_bridge: 事件 %s 的状态机 %s 未登记/停用，零写入",
                    event_name, termId)
                return
            # 主体类型守卫：事件只对挂了本状态机的主体写状态——未登记主体/
            # 异型主体的事件不是本机的映射对象，零写入
            from neurova.knowledge.foundation.knowledge_facts import normalizeLabel

            row = None
            with self._store._lock:
                row = self._store._conn.execute(
                    "SELECT type_term_id FROM knowledge_subjects"
                    " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?"
                    " AND status = 'active'",
                    (agentId, tenantId, normalizeLabel(subjectLabel))).fetchone()
            typeTerm = str(row["type_term_id"] or "") if row is not None else ""
            if typeTerm != termId:
                logger.warning(
                    "state_event_bridge: 事件 %s 的主体 %r 类型 %r 不挂状态机 %s，零写入",
                    event_name, subjectLabel, typeTerm, termId)
                return
            from .foundation.admission import AdmissionRequest, productionAdmissionGate

            content = "%s has_state %s" % (subjectLabel, newState)
            try:
                gate = productionAdmissionGate(self._store,
                                               toolVersion="state_event_bridge")
                gate.admit(AdmissionRequest(
                    agentId=agentId, tenantId=tenantId,
                    subjectLabel=subjectLabel, predicateTermId="has_state",
                    objectTerm=newState, content=content,
                    assertions=[{"actorType": "pipeline",
                                 "actorId": "event:%s" % event_name,
                                 "mediumRef": "event:%s" % event_name,
                                 "statementText": content}],
                    activityKind="admit",
                    activityBasis="state_event_bridge（事件 %s → 状态机 %s）"
                                  % (event_name, termId)))
            except Exception as exc:  # noqa: BLE001 - fail-closed：拒即留名，不重试
                logger.warning(
                    "state_event_bridge: 事件 %s 写入被拒（%s: %s）——不重试",
                    event_name, type(exc).__name__, exc)

        return handler
