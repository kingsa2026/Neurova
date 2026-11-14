"""BuildSession：一句话需求的构建就绪门与过程中交互。

职责边界（N0）：
- 先问清再动手：ready 之前，画布写工具由 ToolExecutor 的 build gate 拒绝；
- 问答轮复用计划模式的协议形状（id/question/options/multi/allow_custom）；
- secret 回答只写 SecretStore，会话记录只留 key 名与 configured 标记；
- 构建中的 ask_user 把会话置 blocked，回答后恢复 building；
- 批次由会话批准时生成，生命周期覆盖本任务轮次。

本模块不直接执行画布/工作流；它只维护「能不能动手」的状态与问答记录。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.data_root import dataPath
from neurova.core.logger import get_logger

logger = get_logger(__name__)

MAX_QUESTION_ROUNDS = 12
MAX_QUESTIONS_PER_ROUND = 3
DEFAULT_TIMEOUT_SECONDS = 600

STATUS_CLARIFYING = "clarifying"
STATUS_READY = "ready"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_APPROVED = "approved"
STATUS_BUILDING = "building"
STATUS_BLOCKED = "blocked"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset(
    {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED}
)

CHECKLIST_KEYS = (
    "goal",
    "target",
    "nodes",
    "params",
    "env",
    "permissions",
    "budget",
    "safe_version",
)

_VALID_QUESTION_KINDS = frozenset({"choice", "multi", "text", "secret", "confirm"})


class BuildSessionError(ValueError):
    """构建会话错误；code ∈ invalid_state|not_found|llm_failed|invalid_question。"""

    def __init__(self, message: str, code: str = "invalid_state"):
        super().__init__(message)
        self.code = code


def _extractJson(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise BuildSessionError("LLM 输出不含 JSON", "llm_failed") from None
        try:
            obj = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise BuildSessionError(f"LLM 输出 JSON 解析失败: {exc}", "llm_failed") from exc
    if not isinstance(obj, dict):
        raise BuildSessionError("LLM 输出不是 JSON 对象", "llm_failed")
    return obj


def _secretStore():
    from neurova.llm.providers.secret_store_clean import get_secret_store

    return get_secret_store()


def _cleanOptions(options: Any) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for option in options or []:
        if isinstance(option, str):
            cleaned.append({"label": option, "description": ""})
            continue
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        if not label:
            continue
        item = {"label": label}
        if option.get("description"):
            item["description"] = str(option["description"])
        if option.get("recommended") is True:
            item["recommended"] = True
        cleaned.append(item)
    return cleaned[:6]


def _cleanQuestion(raw: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise BuildSessionError("问题条目不是对象", "invalid_question")
    question = str(raw.get("question") or "").strip()
    if not question:
        raise BuildSessionError("问题文本为空", "invalid_question")
    kind = str(raw.get("kind") or "choice").strip().lower()
    if kind not in _VALID_QUESTION_KINDS:
        kind = "choice"
    secretKey = str(raw.get("secret_key") or "").strip()
    if kind == "secret" and not secretKey:
        raise BuildSessionError("secret 问题必须给 secret_key", "invalid_question")
    qid = str(raw.get("id") or f"q{index + 1}").strip()
    return {
        "id": qid,
        "question": question,
        "kind": kind,
        "options": _cleanOptions(raw.get("options")),
        "multi": bool(raw.get("multi")) or kind == "multi",
        "allow_custom": bool(raw.get("allow_custom")),
        "why": str(raw.get("why") or ""),
        "impact": str(raw.get("impact") or ""),
        "required": bool(raw.get("required", True)),
        "secret_key": secretKey,
        "timeout_seconds": int(raw.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
    }


def _normalizeChecklist(raw: Any) -> Dict[str, bool]:
    source = raw if isinstance(raw, dict) else {}
    return {key: bool(source.get(key)) for key in CHECKLIST_KEYS}


_BUILD_PROMPT = """你是工作流构建就绪助手。用户准备让 Agent 搭建/修改一条工作流。
你的职责不是执行，而是判断「现在是否具备动手条件」，并把缺口变成 1~3 个可回答的问题。

必须检查（checklist）：
- goal：目标、范围、验收标准是否明确
- target：新建还是修改既有画布/工作流，目标 id 与归属是否明确
- nodes：所需节点类型是否已知/可用
- params：必填参数是否齐全（不知道的值不得猜）
- env：所需环境变量/凭据是否可用（不知道时用 secret 问题问，不要假设）
- permissions：用户/Agent/画布/工作流权限是否明确
- budget：轮次/时间/成本约束是否可接受
- safe_version：修改已发布工作流时是否有可回滚的安全版本

严格只输出 JSON：
{"ready": false,
 "checklist": {"goal": false, "target": false, "nodes": false, "params": false,
               "env": false, "permissions": false, "budget": false, "safe_version": true},
 "build_plan": {"summary": "一句话构建计划"},
 "questions": [
   {"id": "q1", "question": "问题", "kind": "choice|multi|text|secret|confirm",
    "options": [{"label": "选项", "description": "说明", "recommended": true}],
    "multi": false, "allow_custom": true, "why": "为什么问", "impact": "影响什么",
    "required": true, "secret_key": "NEUROVA_...", "timeout_seconds": 600}
 ]}

规则：
- 只有 checklist 全部为 true 且没有必需问题时才 ready=true；
- 不要问已经能从需求/问答记录确定的事；
- secret 问题必须给 secret_key，且不得要求用户在聊天正文里粘贴凭据；
- 每轮最多 3 个问题；没有问题且未 ready 时给出最关键的 1 个问题。
用户需求：{request}
已有问答：
{transcript}
{history_suffix}
请只输出 JSON。"""


@dataclass
class BuildSession:
    session_id: str
    request: str
    agent_id: str
    user_id: str
    target_kind: str = ""
    target_id: str = ""
    status: str = STATUS_CLARIFYING
    checklist: Dict[str, bool] = field(default_factory=lambda: {k: False for k in CHECKLIST_KEYS})
    rounds: List[Dict[str, Any]] = field(default_factory=list)
    build_plan: Dict[str, Any] = field(default_factory=dict)
    interactions: List[Dict[str, Any]] = field(default_factory=list)
    batch_id: str = ""
    approved_by: str = ""
    approved_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""

    def toDict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "request": self.request,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "status": self.status,
            "checklist": dict(self.checklist),
            "rounds": list(self.rounds),
            "build_plan": dict(self.build_plan),
            "interactions": list(self.interactions),
            "batch_id": self.batch_id,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "BuildSession":
        return cls(
            session_id=str(data.get("session_id") or ""),
            request=str(data.get("request") or ""),
            agent_id=str(data.get("agent_id") or ""),
            user_id=str(data.get("user_id") or ""),
            target_kind=str(data.get("target_kind") or ""),
            target_id=str(data.get("target_id") or ""),
            status=str(data.get("status") or STATUS_CLARIFYING),
            checklist=_normalizeChecklist(data.get("checklist")),
            rounds=list(data.get("rounds") or []),
            build_plan=dict(data.get("build_plan") or {}),
            interactions=list(data.get("interactions") or []),
            batch_id=str(data.get("batch_id") or ""),
            approved_by=str(data.get("approved_by") or ""),
            approved_at=float(data.get("approved_at") or 0),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            error=str(data.get("error") or ""),
        )


class BuildSessionManager:
    """JSON 持久化的构建会话管理器（原子写 + RLock）。"""

    def __init__(self, store_path: Optional[str] = None, llm_call: Optional[Callable[[str], Any]] = None):
        self._path = store_path or os.environ.get("NEUROVA_BUILD_SESSIONS") or dataPath(
            "build_sessions.json"
        )
        self._llm_call = llm_call
        self._sessions: Dict[str, BuildSession] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning("构建会话存储读取失败，按空存储继续: %s", self._path)
            return
        items = raw.get("sessions") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        for item in items:
            try:
                session = BuildSession.fromDict(item)
            except Exception:  # noqa: BLE001 - 单条损坏不阻断整体
                continue
            if session.session_id:
                self._sessions[session.session_id] = session

    def _save(self) -> None:
        with self._lock:
            payload = {"sessions": [s.toDict() for s in self._sessions.values()]}
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            tmp = f"{self._path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("构建会话存储写入失败: %s", exc)

    def get(self, session_id: str) -> Optional[BuildSession]:
        with self._lock:
            return self._sessions.get(str(session_id or ""))

    def list(self, user_id: str = "", agent_id: str = "") -> List[BuildSession]:
        with self._lock:
            values = list(self._sessions.values())
        if user_id:
            values = [s for s in values if s.user_id == user_id]
        if agent_id:
            values = [s for s in values if s.agent_id == agent_id]
        return sorted(values, key=lambda s: s.updated_at, reverse=True)

    def _require(self, session_id: str) -> BuildSession:
        session = self.get(session_id)
        if session is None:
            raise BuildSessionError(f"构建会话不存在: {session_id}", "not_found")
        return session

    def _transcript(self, session: BuildSession) -> str:
        lines: List[str] = []
        for index, rnd in enumerate(session.rounds, 1):
            lines.append(f"第 {index} 轮：")
            for question in rnd.get("questions") or []:
                lines.append(f"  问：{question.get('question', '')}")
            for answer in rnd.get("answers") or []:
                selected = answer.get("selected") or []
                custom = answer.get("custom") or ""
                secret = answer.get("secret_key") or ""
                value = "（已配置）" if answer.get("configured") else (custom or ", ".join(selected))
                lines.append(f"  答（{answer.get('id', '')}{'/' + secret if secret else ''}）：{value}")
        return "\n".join(lines)

    async def _assess(
        self,
        session: BuildSession,
        historySuffix: str = "",
        llmCall: Optional[Callable[[str], Any]] = None,
    ) -> None:
        llmCall = llmCall or self._llm_call
        if llmCall is None:
            raise BuildSessionError("构建会话未注入 LLM 调用器", "llm_failed")
        prompt = (
            _BUILD_PROMPT.replace("{request}", session.request)
            .replace("{transcript}", self._transcript(session) or "（尚无）")
            .replace("{history_suffix}", historySuffix)
        )
        try:
            raw = llmCall(prompt)
            text = await raw if hasattr(raw, "__await__") else raw
        except BuildSessionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BuildSessionError(f"LLM 调用失败: {exc}", "llm_failed") from exc

        obj = _extractJson(str(text or ""))
        checklist = _normalizeChecklist(obj.get("checklist"))
        rawQuestions = obj.get("questions") or []
        if not isinstance(rawQuestions, list):
            raise BuildSessionError("LLM 返回的 questions 不是列表", "llm_failed")
        questions = [_cleanQuestion(item, index) for index, item in enumerate(rawQuestions[:MAX_QUESTIONS_PER_ROUND])]
        if len(session.rounds) >= MAX_QUESTION_ROUNDS:
            raise BuildSessionError(
                f"澄清问题超过 {MAX_QUESTION_ROUNDS} 轮，已停止自动出题", "invalid_state"
            )

        with self._lock:
            session.checklist = checklist
            if isinstance(obj.get("build_plan"), dict):
                session.build_plan = dict(obj["build_plan"])
            if obj.get("ready") is True and not questions and all(checklist.values()):
                session.status = STATUS_READY
                session.rounds.append({"questions": [], "answers": []})
            else:
                if not questions:
                    questions = [
                        _cleanQuestion(
                            {
                                "id": "q1",
                                "question": "还缺一项关键信息，请补充目标、参数或凭据。",
                                "kind": "text",
                                "allow_custom": True,
                                "why": "就绪清单未全绿",
                                "impact": "补齐后才能开始构建",
                            },
                            0,
                        )
                    ]
                session.rounds.append({"questions": questions, "answers": []})
                session.status = STATUS_CLARIFYING
            session.updated_at = time.time()
        self._save()

    async def create(
        self,
        request: str,
        agent_id: str,
        user_id: str,
        target_kind: str = "",
        target_id: str = "",
        llm_call: Optional[Callable[[str], Any]] = None,
    ) -> BuildSession:
        session = BuildSession(
            session_id=f"build_{uuid.uuid4().hex[:16]}",
            request=str(request or "").strip(),
            agent_id=str(agent_id or "default"),
            user_id=str(user_id or ""),
            target_kind=str(target_kind or ""),
            target_id=str(target_id or ""),
        )
        if not session.request:
            raise BuildSessionError("需求不能为空", "invalid_state")
        with self._lock:
            self._sessions[session.session_id] = session
        self._save()
        await self._assess(session, llmCall=llm_call)
        return session

    async def answer(
        self,
        session_id: str,
        answers: Optional[List[Dict[str, Any]]] = None,
        supplement: str = "",
        llm_call: Optional[Callable[[str], Any]] = None,
    ) -> BuildSession:
        session = self._require(session_id)
        with self._lock:
            if session.status in TERMINAL_STATUSES:
                raise BuildSessionError(f"会话已终结（{session.status}）", "invalid_state")
            if session.status not in (STATUS_CLARIFYING, STATUS_READY):
                raise BuildSessionError(f"当前状态不可回答: {session.status}", "invalid_state")
            if not session.rounds:
                raise BuildSessionError("会话尚未出题", "invalid_state")
            current = session.rounds[-1]
            current["answers"] = self._applyAnswers(current.get("questions") or [], answers or [])
            if supplement.strip():
                current["supplement"] = supplement.strip()
            session.updated_at = time.time()
        self._save()
        await self._assess(
            session,
            f"\n\n用户本轮自由补充：{supplement.strip()}" if supplement.strip() else "",
            llmCall=llm_call,
        )
        return session

    def _applyAnswers(
        self, questions: List[Dict[str, Any]], answers: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        byId = {q["id"]: q for q in questions}
        cleaned: List[Dict[str, Any]] = []
        for answer in answers or []:
            if not isinstance(answer, dict):
                continue
            qid = str(answer.get("id") or "")
            question = byId.get(qid)
            if question is None:
                continue
            if question.get("kind") == "secret":
                value = str(answer.get("secret_value") or "").strip()
                configured = bool(answer.get("configured"))
                if value:
                    try:
                        _secretStore().set(question["secret_key"], value)
                        configured = True
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("构建会话写 SecretStore 失败: %s", exc)
                        configured = False
                cleaned.append(
                    {
                        "id": qid,
                        "secret_key": question["secret_key"],
                        "configured": configured,
                    }
                )
                continue
            cleaned.append(
                {
                    "id": qid,
                    "selected": [str(v) for v in (answer.get("selected") or []) if str(v).strip()],
                    "custom": str(answer.get("custom") or ""),
                }
            )
        return cleaned

    def approve(self, session_id: str, approver: str) -> BuildSession:
        session = self._require(session_id)
        if session.status not in (STATUS_READY, STATUS_AWAITING_APPROVAL):
            raise BuildSessionError(
                f"当前状态不可批准（{session.status}）；需先补齐就绪清单", "invalid_state"
            )
        if not approver.strip():
            raise BuildSessionError("批准必须记录非空审批人", "invalid_state")
        with self._lock:
            session.status = STATUS_APPROVED
            session.approved_by = approver.strip()
            session.approved_at = time.time()
            session.batch_id = session.batch_id or f"build_batch_{uuid.uuid4().hex[:12]}"
            session.updated_at = time.time()
        self._save()
        return session

    def markBuilding(self, session_id: str) -> BuildSession:
        session = self._require(session_id)
        if session.status != STATUS_APPROVED:
            raise BuildSessionError(f"当前状态不可开始构建（{session.status}）", "invalid_state")
        with self._lock:
            session.status = STATUS_BUILDING
            session.updated_at = time.time()
        self._save()
        return session

    def ask(
        self,
        session_id: str,
        question: str,
        *,
        options: Optional[List[Any]] = None,
        kind: str = "choice",
        multi: bool = False,
        allow_custom: bool = False,
        why: str = "",
        impact: str = "",
        secret_key: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        chat_session_id: str = "",
    ) -> Dict[str, Any]:
        session = self._require(session_id)
        if session.status not in (STATUS_APPROVED, STATUS_BUILDING, STATUS_BLOCKED):
            raise BuildSessionError(
                f"当前状态不可向用户提问（{session.status}）", "invalid_state"
            )
        clean = _cleanQuestion(
            {
                "id": f"build_q_{len(session.interactions) + 1}",
                "question": question,
                "kind": kind,
                "options": options or [],
                "multi": multi,
                "allow_custom": allow_custom,
                "why": why,
                "impact": impact,
                "secret_key": secret_key,
                "timeout_seconds": timeout_seconds,
            },
            0,
        )
        interaction = {
            "interaction_id": f"int_{uuid.uuid4().hex[:12]}",
            "question": clean,
            "status": "pending",
            "answer": None,
            "created_at": time.time(),
            "answered_at": 0.0,
            "chat_session_id": str(chat_session_id or "").strip(),
        }
        with self._lock:
            session.interactions.append(interaction)
            session.status = STATUS_BLOCKED
            session.updated_at = time.time()
        self._save()
        return dict(interaction)

    def answerInteraction(
        self, session_id: str, interaction_id: str, answer: Dict[str, Any]
    ) -> BuildSession:
        session = self._require(session_id)
        interaction = next(
            (item for item in session.interactions if item.get("interaction_id") == interaction_id),
            None,
        )
        if interaction is None:
            raise BuildSessionError(f"交互不存在: {interaction_id}", "not_found")
        if interaction.get("status") != "pending":
            raise BuildSessionError("该交互已回答或已关闭", "invalid_state")
        question = interaction.get("question") or {}
        stored: Dict[str, Any] = {
            "id": question.get("id", ""),
            "selected": [str(v) for v in (answer.get("selected") or []) if str(v).strip()],
            "custom": str(answer.get("custom") or ""),
        }
        if question.get("kind") == "secret":
            value = str(answer.get("secret_value") or "").strip()
            configured = False
            if value:
                try:
                    _secretStore().set(question["secret_key"], value)
                    configured = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("构建交互写 SecretStore 失败: %s", exc)
            stored = {
                "id": question.get("id", ""),
                "secret_key": question.get("secret_key", ""),
                "configured": configured,
            }
        with self._lock:
            interaction["status"] = "answered"
            interaction["answer"] = stored
            interaction["answered_at"] = time.time()
            session.status = STATUS_BUILDING
            session.updated_at = time.time()
        self._save()
        return session

    def complete(self, session_id: str) -> BuildSession:
        session = self._require(session_id)
        with self._lock:
            session.status = STATUS_COMPLETED
            session.updated_at = time.time()
        self._save()
        return session

    def fail(self, session_id: str, error: str) -> BuildSession:
        session = self._require(session_id)
        with self._lock:
            session.status = STATUS_FAILED
            session.error = str(error or "")
            session.updated_at = time.time()
        self._save()
        return session

    def cancel(self, session_id: str) -> BuildSession:
        session = self._require(session_id)
        with self._lock:
            session.status = STATUS_CANCELLED
            session.updated_at = time.time()
        self._save()
        return session


_manager: Optional[BuildSessionManager] = None
_managerLock = threading.RLock()


def get_build_session_manager() -> BuildSessionManager:
    global _manager
    if _manager is None:
        with _managerLock:
            if _manager is None:
                _manager = BuildSessionManager()
    return _manager


def reset_build_session_manager() -> None:
    global _manager
    with _managerLock:
        _manager = None


__all__ = [
    "BuildSession",
    "BuildSessionError",
    "BuildSessionManager",
    "get_build_session_manager",
    "reset_build_session_manager",
    "MAX_QUESTION_ROUNDS",
]
