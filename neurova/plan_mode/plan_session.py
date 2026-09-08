"""PlanSession —— 计划会话状态机 + PlanSessionManager。

状态流转：
    asking ──submit_answers（LLM 判定继续出题/生成计划）──▶ asking | awaiting_approval
    asking ──decide(approve/reject)──▶ PlanStateError（无计划可批）
    awaiting_approval ──decide(approve)──▶ approved（产出 execute_prompt）
    awaiting_approval ──decide(reject)──▶ rejected
    awaiting_approval ──submit_answers(supplement)──▶ asking（继续补充）
    approved/rejected ──终态，不可再变更

LLM 契约（两段式，经 llm_call(prompt)->str 桥接 MultiModelLLMClient.chat）：
1. 出题阶段：返回 JSON {"done": false, "questions": [{id, question,
   options:[{label, description}], multi, allow_custom}]}；done=true 时改发
2. 计划阶段：返回 JSON {"title": ..., "markdown": ...}
均容忍 ```json code fence 包裹。
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.plan_mode.errors import PlanError, PlanDocError, PlanLLMError, PlanStateError

logger = get_logger(__name__)

LLM_TIMEOUT_S = 90
MAX_QUESTION_ROUNDS = 12  # 硬上限防 LLM 出题死循环（正常 2-4 轮即收口）


def _extract_json(text: str) -> Dict[str, Any]:
    """从 LLM 输出提取 JSON 对象（容忍 ```json fence / 前后杂讯）。"""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # 兜底：截取首个 { 到末个 } 之间
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise PlanLLMError("LLM 输出不含 JSON")
        try:
            obj = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as e:
            raise PlanLLMError(f"LLM 输出 JSON 解析失败: {e}") from e
    if not isinstance(obj, dict):
        raise PlanLLMError("LLM 输出不是 JSON 对象")
    return obj


_QUESTIONS_SYSTEM = (
    "你是需求澄清助手。用户要为一个任务制定计划，但信息还不完整。\n"
    "你的职责：每次提出 1~3 个最关键的澄清问题（选择题/多选题/可自由补充），"
    "帮助明确计划所需的关键决策点。\n"
    "严格只输出 JSON，格式：\n"
    '{"done": false, "questions": [{"id": "q1", "question": "问题文本", '
    '"options": [{"label": "选项", "description": "说明"}], "multi": false, "allow_custom": true}]}\n'
    "规则：\n"
    "- 当关键信息已足够时输出 {\"done\": true}（不再出题）；\n"
    "- 不要一次问超过 3 个问题；不要重复已问过的问题；\n"
    "- 每个问题给 2~4 个选项；需要自由输入时 allow_custom=true；\n"
    "- 问题 id 用 q1/q2/…，每轮重新编号。"
)

_PLAN_SYSTEM = (
    "你是计划撰写助手。根据用户需求与全部澄清问答，产出一份结构化计划文档。\n"
    "严格只输出 JSON：{\"title\": \"简短计划标题\", \"markdown\": \"完整 Markdown 计划全文\"}。\n"
    "markdown 要求：用 ## 分节（背景与目标 / 方案要点 / 实施步骤 / 风险与回滚 / 验收标准），"
    "实施步骤用有序列表且每步可直接执行；全文用与用户相同的语言撰写。"
)

_EXECUTE_PROMPT_TEMPLATE = (
    "请按照以下计划执行任务。\n\n"
    "计划文档：{rel_path}\n\n"
    "--- 计划全文开始 ---\n{plan}\n--- 计划全文结束 ---\n\n"
    "严格按计划中的实施步骤顺序推进；遇到与计划冲突的现实约束时先说明再行动。"
)


class PlanSession:
    """单个计划会话（状态机；线程安全）。"""

    STATUS_ASKING = "asking"
    STATUS_AWAITING_APPROVAL = "awaiting_approval"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    _TERMINAL = {STATUS_APPROVED, STATUS_REJECTED}

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
        request: str,
        llm_call: Callable[[str], Any],
        doc_store: Any = None,
    ):
        self.session_id = session_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.request = request
        self.llm_call = llm_call
        # PlanDocStore；默认走单例（测试可注入 tmp 目录实现）
        if doc_store is None:
            from neurova.plan_mode.plan_docs import get_plan_doc_store

            doc_store = get_plan_doc_store()
        self._doc_store = doc_store
        self.status = self.STATUS_ASKING
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.document: Optional[Dict[str, Any]] = None  # save() 结果
        self.execute_prompt: Optional[str] = None
        # rounds[i] = {"questions": [...], "answers": [...]}（首项 answers=[]
        # 待首轮提交后回填）
        self.rounds: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._started = False

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "agent_id": self.agent_id,
                "request": self.request,
                "status": self.status,
                "rounds": self.rounds,
                "document": self.document,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }

    def _touch(self) -> None:
        self.updated_at = time.time()

    # ------------------------------------------------------------------
    # LLM 桥
    # ------------------------------------------------------------------

    async def _ask_llm(self, prompt: str) -> str:
        result = self.llm_call(prompt)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, dict):
            return str(result.get("content") or "")
        return str(result)

    # ------------------------------------------------------------------
    # 首轮出题
    # ------------------------------------------------------------------

    async def ensure_started(self) -> None:
        """生成首轮澄清问题（幂等）。"""
        with self._lock:
            if self._started:
                return
        await self._ask_questions(history_suffix="")
        with self._lock:
            self._started = True
        self._touch()

    # ------------------------------------------------------------------
    # 问答推进
    # ------------------------------------------------------------------

    async def submit_answers(
        self, answers: Optional[List[Dict[str, Any]]] = None, supplement: str = ""
    ) -> Dict[str, Any]:
        """提交本轮回答/自由补充 → LLM 出下一轮问题或生成计划。"""
        answers = answers or []
        supplement = (supplement or "").strip()
        with self._lock:
            if self.status in self._TERMINAL:
                raise PlanStateError(f"会话已终结（{self.status}），不可继续问答")
            if self.status == self.STATUS_AWAITING_APPROVAL:
                # 审批面继续补充 → 回到 asking 追加一轮
                self.status = self.STATUS_ASKING
                self.document = None
            if not answers and not supplement:
                raise PlanStateError("回答与补充不能同时为空")
            if not self.rounds:
                raise PlanStateError("会话尚未出题")
            self.rounds[-1]["answers"] = answers
            self.rounds[-1]["supplement"] = supplement

        round_no = len(self.rounds)
        history_suffix = ""
        if supplement:
            history_suffix += f"\n\n用户本轮自由补充：{supplement}"
        plan: Optional[Dict[str, Any]] = None
        if round_no >= MAX_QUESTION_ROUNDS:
            plan = await self._generate_plan(history_suffix)
        else:
            probe = await self._ask_questions(history_suffix)
            if isinstance(probe, dict):
                plan = probe  # LLM 跳过收口直接输出计划
            elif probe is None:  # LLM 判定信息已足够
                plan = await self._generate_plan(history_suffix)
        if plan is not None:
            self._finalize_plan(plan)
        self._touch()
        return self.to_dict()

    async def _ask_questions(self, history_suffix: str):
        """出题一轮。

        返回：问题列表（继续问答）/ None（done=true，信息已足够）/
        计划 dict（LLM 跳过收口直接输出计划形态 JSON）。
        """
        transcript = self._transcript()
        prompt = (
            f"{_QUESTIONS_SYSTEM}\n\n用户需求：{self.request}\n\n已完成问答记录：{transcript or '（尚无）'}"
            + history_suffix
            + "\n\n请输出下一轮澄清问题 JSON（信息已足够时输出 {\"done\": true}）。"
        )
        obj = _extract_json(await self._ask_llm(prompt))
        md = obj.get("markdown")
        if isinstance(md, str) and md.strip():
            return {"title": str(obj.get("title") or "").strip() or "计划", "markdown": md.strip()}
        if obj.get("done") is True:
            return None
        questions = obj.get("questions")
        if not isinstance(questions, list) or not questions:
            raise PlanLLMError("LLM 未返回有效问题列表")
        cleaned = [self._clean_question(q) for q in questions]
        with self._lock:
            self.rounds.append({"questions": cleaned, "answers": []})
        return cleaned

    @staticmethod
    def _clean_question(q: Any) -> Dict[str, Any]:
        if not isinstance(q, dict) or not str(q.get("question") or "").strip():
            raise PlanLLMError("问题条目格式非法")
        opts = q.get("options") or []
        clean_opts = []
        for o in opts if isinstance(opts, list) else []:
            if isinstance(o, dict) and str(o.get("label") or "").strip():
                clean_opts.append({"label": str(o["label"]), "description": str(o.get("description") or "")})
        return {
            "id": str(q.get("id") or f"q{len(clean_opts) + 1}"),
            "question": str(q["question"]).strip(),
            "options": clean_opts,
            "multi": bool(q.get("multi")),
            "allow_custom": bool(q.get("allow_custom", True)),
        }

    # ------------------------------------------------------------------
    # 计划生成与落盘
    # ------------------------------------------------------------------

    async def _generate_plan(self, history_suffix: str) -> Dict[str, Any]:
        transcript = self._transcript()
        prompt = (
            f"{_PLAN_SYSTEM}\n\n用户需求：{self.request}\n\n全部澄清问答记录：{transcript or '（尚无）'}"
            + history_suffix
            + "\n\n请输出计划 JSON。"
        )
        obj = _extract_json(await self._ask_llm(prompt))
        title = str(obj.get("title") or "").strip()
        markdown = str(obj.get("markdown") or "").strip()
        if not markdown:
            raise PlanLLMError("LLM 未返回计划正文")
        return {"title": title or "计划", "markdown": markdown}

    def _finalize_plan(self, plan: Dict[str, Any]) -> None:
        self.document = self._doc_store.save(
            agent_id=self.agent_id, title=plan["title"], content=plan["markdown"]
        )
        self.document["title"] = plan["title"]
        with self._lock:
            self.status = self.STATUS_AWAITING_APPROVAL

    def _transcript(self) -> str:
        parts: List[str] = []
        for i, r in enumerate(self.rounds, 1):
            qs = "; ".join(q["question"] for q in r.get("questions", []))
            ans = r.get("answers") or []
            ans_txt = "; ".join(
                f"{a.get('id')}={'/'.join(a.get('selected') or []) or ''}{('（自定义）' + a['custom']) if a.get('custom') else ''}"
                for a in ans
                if isinstance(a, dict)
            )
            supp = r.get("supplement") or ""
            parts.append(f"第{i}轮 问：{qs}\n第{i}轮 答：{ans_txt or '（未答）'}" + (f" 补充：{supp}" if supp else ""))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 审批
    # ------------------------------------------------------------------

    async def decide(self, action: str, note: str = "") -> Dict[str, Any]:
        """审批决定：approve → approved + execute_prompt；reject → rejected。"""
        with self._lock:
            if self.status == self.STATUS_ASKING:
                raise PlanStateError("计划尚未生成，无可审批对象")
            if self.status in self._TERMINAL:
                raise PlanStateError(f"会话已终结（{self.status}）")
        if action == "approve":
            if not self.document:
                raise PlanStateError("计划文档缺失")
            plan_md = self._doc_store.read(self.agent_id, self.document["name"])
            self.execute_prompt = _EXECUTE_PROMPT_TEMPLATE.format(
                rel_path=self.document["rel_path"], plan=plan_md
            )
            with self._lock:
                self.status = self.STATUS_APPROVED
        elif action == "reject":
            with self._lock:
                self.status = self.STATUS_REJECTED
        else:
            raise PlanStateError(f"未知审批动作: {action}")
        self._touch()
        return self.to_dict()


class PlanSessionManager:
    """会话注册表（归属隔离 + TTL 过期；RLock 保护）。"""

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, PlanSession] = {}
        self._lock = threading.RLock()

    async def create(
        self,
        agent_id: str,
        user_id: str,
        request: str,
        llm_call: Callable[[str], Any],
        ensure_started: bool = True,
    ) -> PlanSession:
        sess = PlanSession(
            session_id=f"plan-{int(time.time() * 1000):x}-{id(object()):x}",
            agent_id=agent_id,
            user_id=user_id,
            request=request,
            llm_call=llm_call,
        )
        if ensure_started:
            await sess.ensure_started()
        with self._lock:
            self._evict_expired_locked()
            self._sessions[sess.session_id] = sess
        return sess

    def get(self, session_id: str, user_id: str) -> Optional[PlanSession]:
        """按归属读取；非本人不可见（None）；过期即逐出。"""
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None or sess.user_id != user_id:
                return None
            if time.time() - sess.updated_at > self.ttl_seconds:
                del self._sessions[session_id]
                return None
            return sess

    def _evict_expired_locked(self) -> None:
        now = time.time()
        for sid in [s for s, v in self._sessions.items() if now - v.updated_at > self.ttl_seconds]:
            del self._sessions[sid]


_manager_singleton: Optional[PlanSessionManager] = None


def get_plan_session_manager() -> PlanSessionManager:
    """进程级单例（惰性创建）。"""
    global _manager_singleton
    if _manager_singleton is None:
        _manager_singleton = PlanSessionManager()
    return _manager_singleton


def reset_plan_session_manager() -> None:
    """重置单例（测试用）。"""
    global _manager_singleton
    _manager_singleton = None
