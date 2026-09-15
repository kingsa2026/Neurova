"""会话历史挖掘 — 从真实使用记录生成评测集(解冷启动)。

  - 源 A:`core/agent_run_store` 的 agent_runs(真实任务 + 状态)
  - 源 B:会话历史(已完成会话的 user/assistant 对)
  - 源 C:golden JSONL(手写关键技能)

两条不可省的安全与质检线:
  1. **密钥清洗**:任何命中密钥模式的消息一律剔除,绝不进评测集;
  2. **两级筛选**:便宜词面预筛 → LLM 相关性打分(LLM 失败计数上报,
     不让静默失败拉低数据集质量)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.dataset import EvalDataset, EvalExample

logger = get_logger(__name__)

# ── 密钥检测──# 每条锚定已知密钥格式,尽量减少对正常文本的误报。
SECRET_PATTERNS = re.compile(
    r"("
    r"sk-ant-api\S+"           # Anthropic
    r"|sk-or-v1-\S+"           # OpenRouter
    r"|sk-\S{20,}"             # OpenAI 风格(sk- 后 20+ 字符)
    r"|ghp_\S+"                # GitHub PAT
    r"|ghu_\S+"                # GitHub user token
    r"|xoxb-\S+"               # Slack bot
    r"|xapp-\S+"               # Slack app
    r"|ntn_\S+"                # Notion
    r"|AKIA[0-9A-Z]{16}"       # AWS access key id
    r"|Bearer\s+\S{20,}"       # Bearer 头
    r"|-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"
    r"|ANTHROPIC_API_KEY"      # 已知环境变量名(精确)
    r"|OPENAI_API_KEY"
    r"|OPENROUTER_API_KEY"
    r"|SLACK_BOT_TOKEN"
    r"|GITHUB_TOKEN"
    r"|AWS_SECRET_ACCESS_KEY"
    r"|DATABASE_URL"
    r"|\bpassword\s*[=:]\s*\S+"
    r"|\bsecret\s*[=:]\s*\S+"
    r"|\btoken\s*[=:]\s*\S{10,}"
    r")",
    re.IGNORECASE,
)

MIN_TEXT_LEN = 10
_MIN_RELEVANCE_OVERLAP = 2

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _effective_len(text: str) -> int:
    """有效长度:CJK 字符按 2 计(信息密度约为拉丁字符两倍)。

    `< 10` 闸是按英文习惯定的,Neurova 面向中文用户,须按脚本密度折算。
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return len(text) + cjk


def contains_secret(text: str) -> bool:
    """消息是否含密钥/凭据(命中即整条剔除)。"""
    return bool(text and SECRET_PATTERNS.search(text))


def sanitize_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤掉含密钥、过短或缺字段的消息。"""
    clean: list[dict[str, Any]] = []
    for m in messages or []:
        task = (m.get("task_input") or "").strip()
        resp = (m.get("assistant_response") or "").strip()
        if _effective_len(task) < MIN_TEXT_LEN:
            continue
        if contains_secret(task) or contains_secret(resp):
            continue
        clean.append({**m, "task_input": task, "assistant_response": resp})
    return clean


# ── 相关性筛选 ──


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text.lower()) if len(t) > 3}


def is_relevant(task_input: str, skill_name: str, skill_text: str) -> bool:
    """便宜词面预筛:技能名或技能正文关键词与任务重叠足够。"""
    text_lower = task_input.lower()
    name_norm = skill_name.lower().replace("-", " ").replace("_", " ")
    if name_norm and name_norm in text_lower:
        return True
    for word in name_norm.split():
        if len(word) > 3 and word in text_lower:
            return True
    skill_keywords = _tokenize(skill_text[:800])
    task_words = _tokenize(text_lower)
    return len(skill_keywords & task_words) >= _MIN_RELEVANCE_OVERLAP


class RelevanceScorer:
    """LLM 相关性打分(第二阶段)。llm_call 可注入以便离线测试。"""

    def __init__(self, llm_call: Optional[Callable[..., Any]] = None, model: str = ""):
        self._llm_call = llm_call
        self.model = model

    async def score(self, *, skill_name: str, skill_text: str,
                    task_input: str, assistant_response: str) -> Optional[dict]:
        if self._llm_call is None:
            return {"relevant": True, "expected_behavior": "应正确完成该任务",
                    "difficulty": "medium", "category": "general"}
        messages = [
            {"role": "system", "content":
             "判断用户消息是否与给定技能相关。只输出 JSON:{relevant:bool, "
             "expected_behavior:str, difficulty:str, category:str}"},
            {"role": "user", "content":
             f"技能名:{skill_name}\n技能描述:{skill_text[:800]}\n"
             f"用户消息:{task_input[:1000]}\n助手回复:{assistant_response[:1000]}"},
        ]
        try:
            result = await self._llm_call(messages, self.model)
        except Exception as e:  # noqa: BLE001
            logger.debug("相关性打分调用失败: %s", e)
            return None
        if not result.get("success"):
            return None
        return _extract_json(result.get("response") or "")


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            d = json.loads(text[start : end + 1])
            return d if isinstance(d, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class HistoryMiner:
    """从会话历史挖掘评测用例。"""

    def __init__(self, scorer: Optional[RelevanceScorer] = None, max_examples: int = 50):
        self.scorer = scorer or RelevanceScorer()
        self.max_examples = max_examples

    async def mine(
        self,
        *,
        skill_name: str,
        skill_text: str,
        messages: list[dict[str, Any]],
    ) -> list[EvalExample]:
        """清洗 → 预筛 → LLM 精筛 → 产出 EvalExample。"""
        messages = sanitize_messages(messages)
        candidates = [m for m in messages if is_relevant(m["task_input"], skill_name, skill_text)]
        candidates = candidates[: self.max_examples * 3]

        examples: list[EvalExample] = []
        errors = 0
        for m in candidates:
            scored = await self.scorer.score(
                skill_name=skill_name,
                skill_text=skill_text,
                task_input=m["task_input"],
                assistant_response=m.get("assistant_response", ""),
            )
            if scored is None:
                errors += 1
                continue
            if not scored.get("relevant", False):
                continue
            expected = (scored.get("expected_behavior") or "").strip()
            if not expected:
                continue
            examples.append(
                EvalExample(
                    task_input=m["task_input"],
                    expected_behavior=expected,
                    difficulty=scored.get("difficulty", "medium"),
                    category=scored.get("category", "general"),
                    source=m.get("source", "history"),
                )
            )
            if len(examples) >= self.max_examples:
                break

        if errors:
            total = len(candidates) or 1
            logger.warning("相关性打分失败 %d/%d (%.0f%%)", errors, total, errors / total * 100)
        return examples


# ── 数据源:会话历史(session_repository)──


def messages_from_sessions(
    agent_id: str, limit_sessions: int = 20, repo: Any = None
) -> list[dict[str, Any]]:
    """从会话仓库挖 (user_input, assistant_response) 对(尽力而为,失败返回空)。

    数据源是 session_repository.get_history(会话真实持久层,聊天页刷新的
    同源),按回合配对:user 消息 + 下一条 assistant 回复(跳过中间 tool 消息)。
    """
    try:
        if repo is None:
            from neurova.session_repository import get_session_repository

            repo = get_session_repository()
        sessions = repo.list_sessions(agent_id=agent_id)[: max(0, limit_sessions)]
    except Exception as e:  # noqa: BLE001
        logger.debug("读取会话仓库失败: %s", e)
        return []

    out: list[dict[str, Any]] = []
    for sess in sessions:
        sid = sess.get("session_id") or sess.get("id") or ""
        if not sid:
            continue
        try:
            history = repo.get_history(agent_id, sid) or []
        except Exception as e:  # noqa: BLE001
            logger.debug("读取会话 %s 历史失败: %s", sid, e)
            continue
        for i, msg in enumerate(history):
            if (msg.get("role") or "") != "user":
                continue
            user_text = str(msg.get("content") or "").strip()
            if not user_text:
                continue
            assistant_text = ""
            for j in range(i + 1, len(history)):
                role = history[j].get("role") or ""
                if role == "assistant":
                    assistant_text = str(history[j].get("content") or "").strip()
                    break
                if role == "user":
                    break  # 下一个用户回合,本轮无 assistant 回复
            out.append(
                {
                    "task_input": user_text,
                    "assistant_response": assistant_text,
                    "source": "history",
                    "session_id": sid,
                }
            )
    return out


def load_golden(path: Path) -> list[EvalExample]:
    """加载手写 golden JSONL。"""
    path = Path(path)
    if not path.exists():
        return []
    examples: list[EvalExample] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    examples.append(EvalExample.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
    return examples


async def build_dataset(
    *,
    skill_name: str,
    skill_text: str,
    messages: list[dict[str, Any]],
    seed: int = 42,
    max_examples: int = 50,
    scorer: Optional[RelevanceScorer] = None,
) -> EvalDataset:
    """挖掘 + 切分,产出可直接跑进化的 EvalDataset。"""
    miner = HistoryMiner(scorer=scorer, max_examples=max_examples)
    examples = await miner.mine(skill_name=skill_name, skill_text=skill_text, messages=messages)
    return EvalDataset.split(examples, seed=seed)
