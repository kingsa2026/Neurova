"""
经验知识库 (2.0)

存储、检索和管理技能使用经验，支持：
- 经验记录和检索（SQLite 持久化）
- 按技能/成功状态过滤查询
- 相似经验搜索（关键词重叠 + 话题匹配 + 成功率加权）
- 技能效果评估（成功率/执行时间/趋势综合评分）
- 最佳实践推荐
- 经验统计与技能排名

2.0 契约来源：
- tests/test_experience_knowledge_base.py
- docs/dev_progress/module_designs/experience_knowledge_base.md

构造契约：
    ekb = ExperienceKnowledgeBase(db_path="/path/to/experience.db")
    # 默认 db_path=None 时使用 data/experience_knowledge.db
    ekb.close()  # 用完关闭连接
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.skills.models import ExperienceRecord

logger = get_logger(__name__)


# 默认数据库路径（相对项目根目录的 data 目录）
_DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "experience_knowledge.db")


def _resolve_default_db_path() -> str:
    """解析默认落盘路径：NEUROVA_EKB_DB 环境变量优先（测试隔离挂点，
    conftest autouse fixture 把所有测试的 EKB 指向临时目录），
    未设置时回退项目 data/ 目录（向后兼容）。"""
    env_path = os.environ.get("NEUROVA_EKB_DB", "")
    return env_path or _DEFAULT_DB_PATH


# agent_id 安全字符集：字母/数字/下划线/连字符，1-64 位。
# MagicMock 泄漏（str(mock) = "<MagicMock name='...' id='...'>"）与其它
# 非法值一律归一为 None，杜绝 Mock repr 垃圾值落库（3920 事故第三根因）。
_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _sanitize_agent_id(agent_id: Optional[str]) -> Optional[str]:
    """归一化 agent_id：合法标识符原样返回，非法值（Mock repr/空串/超长）
    归一为 None（NULL 语义 = 未归属）。"""
    if agent_id is None:
        return None
    text = str(agent_id)
    if _AGENT_ID_PATTERN.match(text):
        return text
    logger.warning("Invalid agent_id sanitized to None: %.80s", text)
    return None

# CJK 2-gram 窗口内跳过的纯标点字符（避免跨标点生成噪声 gram）
_PUNCT = set("，。！？、；：\"'()（）[]【】{}<>《》…—·,.!?;: \t\r\n")


def _tokenize_for_match(text: str) -> List[str]:
    """相似度匹配分词：拉丁词按空格/大小写归一；CJK 连续段切 2-gram。

    P2-B4：原实现只 str.split()——中文整句成单 token，重叠判定几乎必失配。
    2-gram 保序切分让"抓取网页"类实词片段可精确重叠，无需引入分词依赖。
    """
    text = (text or "").lower()
    tokens: List[str] = []
    buffer: List[str] = []
    for ch in text:
        if ch.isspace() or ch in _PUNCT:
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
            continue
        buffer.append(ch)
    if buffer:
        tokens.append("".join(buffer))

    out: List[str] = []
    for tok in tokens:
        if any("\u4e00" <= c <= "\u9fff" for c in tok) and len(tok) > 1:
            out.extend(tok[i : i + 2] for i in range(len(tok) - 1))
        else:
            out.append(tok)
    return out


class ExperienceKnowledgeBase:
    """经验知识库

    使用 SQLite 持久化技能使用经验，提供效果评估和智能推荐。

    Args:
        db_path: SQLite 数据库文件路径。None 时使用默认路径
                 (data/experience_knowledge.db)。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path: str = db_path or _resolve_default_db_path()
        self._lock = threading.RLock()

        # 确保目录存在
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

        logger.debug("ExperienceKnowledgeBase initialized at %s", self._db_path)

    # ------------------------------------------------------------------
    # 内部：schema 与序列化
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """初始化数据库 schema"""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS experience_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    context TEXT,           -- JSON
                    result TEXT,            -- JSON (NULL 允许)
                    success INTEGER NOT NULL,  -- 0/1
                    timestamp TEXT,
                    feedback TEXT,
                    agent_id TEXT,
                    session_id TEXT,
                    execution_time REAL,
                    confidence_score REAL,
                    tags TEXT,              -- JSON array
                    created_at TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_exp_skill ON experience_records(skill_name)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_exp_success ON experience_records(success)"
            )
            self._conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典（成功标志转为 int 0/1，保持测试契约）"""
        d = dict(row)
        # context/result/tags 反序列化为 JSON
        if "context" in d and isinstance(d["context"], str):
            try:
                d["context"] = json.loads(d["context"])
            except (json.JSONDecodeError, TypeError):
                pass
        if "result" in d and isinstance(d["result"], str):
            try:
                d["result"] = json.loads(d["result"])
            except (json.JSONDecodeError, TypeError):
                pass
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        elif "tags" in d and d["tags"] is None:
            d["tags"] = []
        # success 保持 int 0/1（测试断言 assertEqual(records[0]["success"], 1)）
        return d

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def add_experience_record(
        self,
        skill_name: str,
        exp: ExperienceRecord,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        execution_time: Optional[float] = None,
        confidence_score: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        """添加经验记录

        Args:
            skill_name: 技能名（与 exp.skill_name 通常一致）
            exp: ExperienceRecord 实例
            agent_id: 调用 Agent ID
            session_id: 会话 ID
            execution_time: 执行耗时（秒）
            confidence_score: 置信度 [0,1]
            tags: 标签列表

        Returns:
            新记录的 id；命中去重门禁时返回既有记录 id
        """
        tags = tags or []
        agent_id = _sanitize_agent_id(agent_id)
        context_json = json.dumps(exp.context or {}, ensure_ascii=False, sort_keys=True)
        result_json = (
            json.dumps(exp.result, ensure_ascii=False, sort_keys=True) if exp.result is not None else None
        )
        tags_json = json.dumps(tags, ensure_ascii=False)
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            cur = self._conn.cursor()
            # 去重门禁：完全相同的 (agent, skill, context, result, success) 只保留一行
            # （3920 条垃圾经验事故：管线测试经单例打真库，"Hello" 重复 1223 次）。
            # success 参与键：同问同答但一成一败是两条语义不同的经验，不合并。
            cur.execute(
                """
                SELECT id FROM experience_records
                WHERE agent_id IS ? AND skill_name = ? AND context = ? AND result IS ? AND success = ?
                LIMIT 1
                """,
                (agent_id, skill_name, context_json, result_json, 1 if exp.success else 0),
            )
            existing = cur.fetchone()
            if existing is not None:
                logger.debug("Duplicate experience record skipped (existing id=%s)", existing["id"])
                return int(existing["id"])

            cur.execute(
                """
                INSERT INTO experience_records
                    (skill_name, context, result, success, timestamp, feedback,
                     agent_id, session_id, execution_time, confidence_score, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_name,
                    context_json,
                    result_json,
                    1 if exp.success else 0,
                    exp.timestamp,
                    exp.feedback,
                    agent_id,
                    session_id,
                    execution_time,
                    confidence_score,
                    tags_json,
                    created_at,
                ),
            )
            self._conn.commit()
            record_id: int = cur.lastrowid or 0

        logger.debug("Added experience record id=%s for skill=%s", record_id, skill_name)
        return record_id

    def get_experience_records(
        self,
        skill_name: str = "",
        success_only: Optional[bool] = None,
        limit: Optional[int] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取经验记录

        Args:
            skill_name: 技能名（空字符串=不限技能）
            success_only: True 仅成功，False 仅失败，None 全部
            limit: 返回数量上限
            agent_id: 限定 Agent（None=不限）

        Returns:
            记录字典列表（每条含 skill_name/success 等字段，success 为 int 0/1）
        """
        sql = "SELECT * FROM experience_records WHERE 1=1"
        params: List[Any] = []

        if skill_name:
            sql += " AND skill_name = ?"
            params.append(skill_name)
        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)

        if success_only is True:
            sql += " AND success = 1"
        elif success_only is False:
            sql += " AND success = 0"

        sql += " ORDER BY id DESC"
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def find_similar_experiences(
        self,
        skill_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5,
        top_k: Optional[int] = None,  # 兼容旧调用（injector.py）
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查找相似经验

        相似度算法（参考设计文档）：
        - 用户输入关键词重叠：权重 60%
        - 话题匹配：权重 30%
        - 成功记录加权：权重 10%

        Args:
            skill_name: 限定技能（None 则跨所有技能）
            context: 查询上下文（含 user_input/topic）
            limit: 返回数量上限（top_k 为旧别名，优先级低于 limit）
            top_k: 旧参数别名（向后兼容 injector.py）
            agent_id: 限定 Agent（None 不限）

        Returns:
            按相似度降序的记录列表，每条附加 similarity_score 字段
        """
        # top_k 向后兼容：仅在 limit 为默认值时使用
        effective_limit = limit if top_k is None else top_k

        # 提取查询关键词
        if context is None:
            return []
        query_input = ""
        if isinstance(context, dict):
            query_input = str(context.get("user_input", ""))
        else:
            # 兼容 str 输入（injector.py 传 str）
            query_input = str(context)
        query_topic = ""
        if isinstance(context, dict):
            query_topic = str(context.get("topic", ""))

        # P2-B4：中文整句 str.split() 得单 token，子串匹配几乎必失配 →
        # keyword/topic 恒 0，而成功记录保底 0.1 分恒过 threshold，任意查询
        # 恒"命中"无关经验。CJK 文本改用 2-gram 切分（与 stored_input 同规则
        # 比对子串），拉丁词保持按空格。
        query_words = _tokenize_for_match(query_input)

        sql = "SELECT * FROM experience_records WHERE 1=1"
        params: List[Any] = []
        if skill_name:
            sql += " AND skill_name = ?"
            params.append(skill_name)
        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

        scored: List[tuple] = []
        for row in rows:
            d = self._row_to_dict(row)
            stored_ctx = d.get("context") or {}
            if not isinstance(stored_ctx, dict):
                stored_ctx = {}
            stored_input = str(stored_ctx.get("user_input", "")).lower()
            stored_topic = str(stored_ctx.get("topic", "")).lower()

            # 关键词重叠 (60%)——stored 侧用同一分词规则，token 集合精确匹配
            stored_tokens = set(_tokenize_for_match(stored_input)) if stored_input else set()
            if query_words and stored_tokens:
                overlap = sum(1 for w in set(query_words) if w in stored_tokens)
                keyword_score = overlap / len(set(query_words))
            else:
                keyword_score = 0.0

            # 话题匹配 (30%)
            topic_score = 1.0 if (query_topic and query_topic == stored_topic) else 0.0

            # 成功加权 (10%)
            success_score = 1.0 if d.get("success") else 0.0

            similarity = 0.6 * keyword_score + 0.3 * topic_score + 0.1 * success_score

            # 相关性门：必须有实词/话题重叠，success 保底分不得单独入选
            #（P2-B4 根因——0.1*1=0.1>0 曾让任意查询恒命中 3 条无关经验）
            if keyword_score > 0 or topic_score > 0:
                d["similarity_score"] = round(similarity, 4)
                scored.append((similarity, d))

        # 按相似度降序
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:effective_limit]]

    def evaluate_skill_effectiveness(self, skill_name: str) -> Dict[str, Any]:
        """评估技能效果

        综合评分基于：
        - 成功率（权重 50%）
        - 执行时间（权重 30%，越低越好）
        - 趋势（权重 20%，最近 vs 历史）

        评价等级：
        - excellent (>0.8), good (>0.6), average (>0.4), poor (≤0.4)

        Args:
            skill_name: 技能名

        Returns:
            dict 含 skill_name/total_records/success_rate/effectiveness_score/evaluation
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT success, execution_time, created_at FROM experience_records WHERE skill_name = ? ORDER BY id ASC",
                (skill_name,),
            )
            rows = cur.fetchall()

        total = len(rows)
        if total == 0:
            return {
                "skill_name": skill_name,
                "total_records": 0,
                "success_rate": 0.0,
                "effectiveness_score": 0.0,
                "evaluation": "poor",
            }

        successes = sum(1 for r in rows if r["success"])
        success_rate = successes / total

        # 执行时间评分（归一化到 [0,1]）
        exec_times = [r["execution_time"] for r in rows if r["execution_time"] is not None]
        if exec_times:
            avg_time = sum(exec_times) / len(exec_times)
            # 简单归一化：1秒为基准，越快越好
            time_score = max(0.0, min(1.0, 1.0 / (1.0 + avg_time)))
        else:
            time_score = 0.5  # 无数据时中性

        # 趋势评分：最近一半 vs 历史一半的成功率差异
        if total >= 4:
            mid = total // 2
            recent = rows[mid:]
            historical = rows[:mid]
            recent_rate = sum(1 for r in recent if r["success"]) / len(recent)
            hist_rate = sum(1 for r in historical if r["success"]) / len(historical)
            trend_score = max(0.0, min(1.0, 0.5 + (recent_rate - hist_rate)))
        else:
            trend_score = 0.5  # 数据不足时中性

        effectiveness = 0.5 * success_rate + 0.3 * time_score + 0.2 * trend_score

        if effectiveness > 0.8:
            evaluation = "excellent"
        elif effectiveness > 0.6:
            evaluation = "good"
        elif effectiveness > 0.4:
            evaluation = "average"
        else:
            evaluation = "poor"

        return {
            "skill_name": skill_name,
            "total_records": total,
            "success_rate": round(success_rate, 4),
            "effectiveness_score": round(effectiveness, 4),
            "evaluation": evaluation,
        }

    def recommend_best_practices(self, skill_name: str) -> List[Dict[str, Any]]:
        """推荐最佳实践

        基于评估结果和成功模式生成推荐。

        Args:
            skill_name: 技能名

        Returns:
            推荐字典列表，每条含 type/recommendation/confidence
        """
        recommendations: List[Dict[str, Any]] = []

        evaluation = self.evaluate_skill_effectiveness(skill_name)
        total = evaluation["total_records"]
        if total == 0:
            return recommendations

        success_rate = evaluation["success_rate"]
        score = evaluation["effectiveness_score"]
        eval_label = evaluation["evaluation"]

        # 推荐类型 1：基于评估结果
        if eval_label == "excellent":
            recommendations.append({
                "type": "usage",
                "recommendation": f"技能 {skill_name} 表现优秀（成功率 {success_rate:.1%}），建议优先使用",
                "confidence": min(1.0, score),
            })
        elif eval_label == "good":
            recommendations.append({
                "type": "usage",
                "recommendation": f"技能 {skill_name} 表现良好（成功率 {success_rate:.1%}），可正常使用",
                "confidence": min(1.0, score),
            })
        elif eval_label == "average":
            recommendations.append({
                "type": "improvement",
                "recommendation": f"技能 {skill_name} 表现一般（成功率 {success_rate:.1%}），建议优化",
                "confidence": min(1.0, 1.0 - score),
            })
        else:
            recommendations.append({
                "type": "warning",
                "recommendation": f"技能 {skill_name} 表现较差（成功率 {success_rate:.1%}），建议替换或重构",
                "confidence": min(1.0, 1.0 - score),
            })

        # 推荐类型 2：成功模式（提取成功记录的反馈）
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT feedback, context FROM experience_records WHERE skill_name = ? AND success = 1 AND feedback IS NOT NULL AND feedback != '' ORDER BY id DESC LIMIT 5",
                (skill_name,),
            )
            success_rows = cur.fetchall()

        if success_rows:
            sample = success_rows[0]
            feedback = sample["feedback"] or ""
            recommendations.append({
                "type": "pattern",
                "recommendation": f"成功模式参考：{feedback[:100]}" if feedback else "存在成功执行记录可参考",
                "confidence": min(1.0, len(success_rows) / max(1, total)),
            })

        return recommendations

    def get_experience_stats(self, skill_name: Optional[str] = None, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """获取经验统计

        Args:
            skill_name: 指定技能则返回单技能统计，None 返回全局统计
            agent_id: 限定 Agent（None 不限）

        Returns:
            单技能: skill_name/total_experiences/success_count (+ success_rate 若 >0)
            全局: total_skills/total_records (+ by_skill 明细)
            空技能: total_experiences=0 + skill_name
        """
        with self._lock:
            cur = self._conn.cursor()
            if skill_name:
                sql = "SELECT COUNT(*) AS total, SUM(success) AS succ FROM experience_records WHERE skill_name = ?"
                params: List[Any] = [skill_name]
                if agent_id is not None:
                    sql += " AND agent_id = ?"
                    params.append(agent_id)
                cur.execute(sql, params)
                row = cur.fetchone()
                total = row["total"] or 0
                succ = row["succ"] or 0
                stats: Dict[str, Any] = {
                    "skill_name": skill_name,
                    "total_experiences": total,
                    "success_count": succ,
                }
                if total > 0:
                    stats["success_rate"] = round(succ / total, 4)
                return stats
            else:
                sql = "SELECT COUNT(*) AS total FROM experience_records"
                params = []
                if agent_id is not None:
                    sql += " WHERE agent_id = ?"
                    params.append(agent_id)
                cur.execute(sql, params)
                total_records = cur.fetchone()["total"] or 0
                sql2 = "SELECT COUNT(DISTINCT skill_name) AS total_skills FROM experience_records"
                if agent_id is not None:
                    sql2 += " WHERE agent_id = ?"
                cur.execute(sql2, params)
                total_skills = cur.fetchone()["total_skills"] or 0
                return {
                    "total_skills": total_skills,
                    "total_records": total_records,
                }

    def get_skill_ranking(
        self,
        metric: str = "success_rate",
        limit: int = 10,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取技能排名

        Args:
            metric: 排序指标，支持 success_rate / total / avg_execution_time
            limit: 返回数量上限
            agent_id: 限定 Agent（None 不限）

        Returns:
            排名字典列表，每条含 skill_name/total/success_rate 等
        """
        sql = """
                SELECT skill_name,
                       COUNT(*) AS total,
                       SUM(success) AS successes,
                       AVG(execution_time) AS avg_execution_time
                FROM experience_records
                """
        params: List[Any] = []
        if agent_id is not None:
            sql += " WHERE agent_id = ?"
            params.append(agent_id)
        sql += " GROUP BY skill_name"

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

        rankings: List[Dict[str, Any]] = []
        for row in rows:
            total = row["total"] or 0
            succ = row["successes"] or 0
            rankings.append({
                "skill_name": row["skill_name"],
                "total": total,
                "success_rate": round(succ / total, 4) if total > 0 else 0.0,
                "avg_execution_time": row["avg_execution_time"],
            })

        # 排序
        if metric == "success_rate":
            rankings.sort(key=lambda x: x["success_rate"], reverse=True)
        elif metric == "total":
            rankings.sort(key=lambda x: x["total"], reverse=True)
        elif metric == "avg_execution_time":
            # 执行时间越低越好（None 排到最后）
            rankings.sort(key=lambda x: (x["avg_execution_time"] is None, x["avg_execution_time"] or float("inf")))
        else:
            rankings.sort(key=lambda x: x["success_rate"], reverse=True)

        return rankings[:limit] if limit > 0 else rankings

    def get_record_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """按主键取单条记录（API 层查看/删除前置用）。"""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM experience_records WHERE id = ?", (int(record_id),)
            )
            row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def delete_record(self, record_id: int) -> bool:
        """删除指定记录，返回是否实际删除。"""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "DELETE FROM experience_records WHERE id = ?", (int(record_id),)
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭数据库连接"""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as e:
                    logger.warning("Error closing ExperienceKnowledgeBase connection: %s", e)
                self._conn = None  # type: ignore[assignment]

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# 全局单例（用于无 db_path 的默认场景，如 injector.py 调用）
_experience_kb: Optional[ExperienceKnowledgeBase] = None
_kb_lock = threading.Lock()


def get_experience_knowledge_base(db_path: Optional[str] = None) -> ExperienceKnowledgeBase:
    """获取全局经验知识库单例

    Args:
        db_path: 数据库路径（仅首次创建时生效）

    Returns:
        ExperienceKnowledgeBase 实例
    """
    global _experience_kb
    if _experience_kb is None:
        with _kb_lock:
            if _experience_kb is None:
                _experience_kb = ExperienceKnowledgeBase(db_path=db_path)
    return _experience_kb


def reset_experience_knowledge_base() -> None:
    """重置全局经验知识库单例（用于测试）"""
    global _experience_kb
    with _kb_lock:
        if _experience_kb is not None:
            try:
                _experience_kb.close()
            except Exception:
                pass
        _experience_kb = None
