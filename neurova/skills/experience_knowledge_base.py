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
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.content_identity import normalized_payload_key
from neurova.core.logger import get_logger
from neurova.skills.models import ExperienceRecord
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)


# 默认数据库路径（相对项目根目录的 data 目录）
def defaultDbPath() -> str:
    """默认库落点：数据根下的绝对路径（原值按 __file__ 反推，是第二份根）。"""
    return str(get_data_root() / "experience_knowledge.db")


def _resolve_default_db_path() -> str:
    """解析默认落盘路径：NEUROVA_EKB_DB 环境变量优先（测试隔离挂点，
    conftest autouse fixture 把所有测试的 EKB 指向临时目录），
    未设置时回退项目 data/ 目录（向后兼容）。"""
    env_path = os.environ.get("NEUROVA_EKB_DB", "")
    return env_path or defaultDbPath()


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
                    success INTEGER,  -- 1/0/NULL（NULL = 本轮无客观回执，未测量）
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
            cur.execute("""CREATE TABLE IF NOT EXISTS growth_lessons (
                agent_id TEXT NOT NULL, answerer_id TEXT NOT NULL, question_id TEXT NOT NULL,
                lesson TEXT NOT NULL, PRIMARY KEY (agent_id, answerer_id, question_id))""")
            self._conn.commit()
            self._migrate_schema()

    def _migrate_schema(self) -> None:
        """幂等补齐内容门列（011），并回填存量行的 `content_key`。

        旧行没有身份键 = 永不被去重命中，升级后同一句还会另开一行，因此首次
        连接时按当前口径回填。`''` 表示"算不出身份"（不参与去重），
        `NULL` 只表示"尚未回填"——回填语句只扫 NULL 行，故不会每启动重扫一遍。
        """
        cur = self._conn.cursor()
        cols = {row[1] for row in cur.execute("PRAGMA table_info(experience_records)")}
        if "content_key" not in cols:
            cur.execute("ALTER TABLE experience_records ADD COLUMN content_key TEXT")
        # 工单 004：`success` 从 NOT NULL 放开为可空——"未测量"必须有自己的取值，
        # 不许折叠成 0（那正是把"没测到"演成"失败"的病灶）。老库按 SQLite 惯例
        # 重建列：建新表 → 拷数据 → 换名，全程幂等（notnull=0 时跳过）。
        info = {row[1]: row for row in cur.execute("PRAGMA table_info(experience_records)")}
        if info.get("success") and info["success"][3]:
            cur.execute("PRAGMA foreign_keys=off")
            cur.execute(
                "CREATE TABLE experience_records_migrating AS SELECT * FROM experience_records"
            )
            cur.execute("DROP TABLE experience_records")
            cur.execute(
                "CREATE TABLE experience_records AS SELECT * FROM experience_records_migrating"
            )
            cur.execute("DROP TABLE experience_records_migrating")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_exp_skill ON experience_records(skill_name)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_exp_success ON experience_records(success)"
            )
            cur.execute("PRAGMA foreign_keys=on")
        if "seen_count" not in cols:
            cur.execute(
                "ALTER TABLE experience_records ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1"
            )
        # 工单 006 回写通路：命中次数 / 最近使用 / 采纳后结果。
        # adoption_outcome 三值 success|failure|unevidenced，NULL 专用于"从未回写"
        # （D1：不能把"没证据"和"没发生过"混成同一个值）
        for column, ddl in (
            ("injected_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_injected_at", "TEXT"),
            ("adoption_outcome", "TEXT"),
            # 工单 008：形成侧第三态升成一等列（此前挤在 tags 字符串里）
            ("evidence_state", "TEXT NOT NULL DEFAULT 'evidenced'"),
            # 工单 015：人工处置态。与采纳证据**分列**——`adoption_outcome` 记的是
            # "这条经验被执行后客观成没成"，人说的话不能写进那一格（否则 007 的排序
            # 与 008 的读数一起吃到的就不再是证据）。NULL = 未处置。
            ("operator_disposition", "TEXT"),
            # 工单 001：逐字可核结论。与 `evidence_state`（本轮有没有服务端票据）
            # 和 `adoption_outcome`（被采纳后成没成）**三轴正交**——三者挤进任何
            # 一栏，那一栏的读数就不再指它原本指的东西。
            # 存量行回填 `unchecked`：它们写入时本闸还不存在，宣称"核过了"是假的。
            ("verifiability_state", "TEXT NOT NULL DEFAULT 'unchecked'"),
        ):
            if column not in cols:
                cur.execute(f"ALTER TABLE experience_records ADD COLUMN {column} {ddl}")
        if "evidence_state" not in cols:
            # 存量行按 002 的 tags 标记回填，避免历史数据在新列上失真
            cur.execute(
                "UPDATE experience_records SET evidence_state = 'unevidenced' "
                "WHERE tags LIKE '%unevidenced%'"
            )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_content ON experience_records"
            "(agent_id, skill_name, success, content_key)"
        )
        pending = cur.execute(
            "SELECT id, context FROM experience_records WHERE content_key IS NULL"
        ).fetchall()
        for row in pending:
            try:
                payload = json.loads(row["context"]) if row["context"] else {}
            except (json.JSONDecodeError, TypeError):
                payload = row["context"]
            cur.execute(
                "UPDATE experience_records SET content_key = ? WHERE id = ?",
                (normalized_payload_key(payload), row["id"]),
            )
        self._conn.commit()

    def publish_growth_lesson(self, lesson: Dict[str, Any]) -> bool:
        """Idempotent scoped index, separate from execution records and success metrics."""
        key = tuple(lesson[k] for k in ("agent_id", "answerer_id", "question_id"))
        payload = json.dumps(lesson, ensure_ascii=False, sort_keys=True)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT lesson FROM growth_lessons WHERE agent_id=? AND answerer_id=? AND question_id=?", key
            ).fetchone()
            if row and row[0] == payload:
                return False
            self._conn.execute("INSERT OR REPLACE INTO growth_lessons VALUES (?, ?, ?, ?)", (*key, payload))
            return True

    def find_growth_lessons(self, query: str, agent_id: str, answerer_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Private user guidance; callers must reconcile the durable queue before reading."""
        if not agent_id or not answerer_id:
            return []
        tokens = set(_tokenize_for_match(query))
        with self._lock:
            rows = self._conn.execute(
                "SELECT lesson FROM growth_lessons WHERE agent_id=? AND answerer_id=?", (agent_id, answerer_id)
            ).fetchall()
        scored = []
        for row in rows:
            lesson = json.loads(row[0])
            score = len(tokens & set(_tokenize_for_match(lesson["question"])))
            if score:
                scored.append((score, lesson))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [lesson for _, lesson in scored[:limit]]

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
        evidence: Optional[bool] = None,
        evidence_text: str = "",
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
            evidence_text: 生成这段 `result` 的原料（工单 001）。只有调用方知道
                这段说法是从哪读出来的（用户输入 / 原文）。提供时走共享逐字可核闸，
                违规记 `verifiability_state='violated'` 并在检索侧降权；不提供则落
                `unchecked`，**不冒充**核过——旧调用点未被改造前，读面上
                "没核"与"核过"必须分得开。
            evidence: 本轮是否拿到**服务端客观票据**（工单 010 起的口径）。
                None（含未传）⇒ 落 `evidence_state='unevidenced'`：模型自述与本轮
                工具回执（002 的记录聚合）都不算证据，条目照常入库（D1）但检索侧
                不得当成功票。票据三态由 `neurova/evolution/objective_evidence.py`
                给出，不在本层重算。
                工单 008 之前这格挤在 `tags=["unevidenced"]` 里，指标面只能靠字符串
                猜；升成列是为了让"无证据占比"成为可告警读数。

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
        content_key = normalized_payload_key(exp.context)
        success_flag = None if exp.success is None else (1 if exp.success else 0)
        evidence_state = "evidenced" if evidence is not None else "unevidenced"
        # 工单 001：`result` 是模型输出，引用精确标识符（URL/路径/版本/hash）时
        # 必须在 `evidence_text` 里逐字存在。判定实现在共享位——与摘要器同源。
        # 处置是**降权不阻塞**：经验是概率性资产，阻塞会让检索面大面积失声，
        # 而一条编造的经验只是"这次别照它做"，不是"这条不能存在"。
        from neurova.knowledge.verifiability import verifiabilityState

        verifiability_state = verifiabilityState(result_json or "", evidence_text)

        with self._lock:
            cur = self._conn.cursor()
            # 内容门（011）：身份 = (agent, skill, success, 归一化输入键)，命中即合并。
            # result 退出身份键——回复文本每轮都是新的 LLM 输出，把它算进身份等于
            # 宣布"永不重复"，生产库因此同一句"你好"存到 7 行。
            # success 留在键内：同问一成一败是两条语义不同的经验，失败证据必须能与
            # 成功证据并存（证伪回路读取）。
            # 合并语义：保留既有行、seen_count +1、result/timestamp 刷新为最新一次，
            # 返回既有 id（首条报错回复不得被永久钉死在经验上）。
            # content_key 为空串表示"算不出内容身份"（无字符串叶子/纯标点），
            # 这类写入各自成行——空键共用一个桶会把它们全部吞没。
            if content_key:
                cur.execute(
                    """
                    SELECT id FROM experience_records
                    WHERE agent_id IS ? AND skill_name = ? AND success = ? AND content_key = ?
                    ORDER BY id LIMIT 1
                    """,
                    (agent_id, skill_name, success_flag, content_key),
                )
                existing = cur.fetchone()
                if existing is not None:
                    record_id = int(existing["id"])
                    cur.execute(
                        """
                        UPDATE experience_records
                        SET result = ?, timestamp = ?, seen_count = seen_count + 1,
                            evidence_state = CASE WHEN ? = 'evidenced'
                                                  THEN 'evidenced' ELSE evidence_state END,
                            verifiability_state = CASE WHEN ? <> 'unchecked'
                                                       THEN ? ELSE verifiability_state END
                        WHERE id = ?
                        """,
                        (result_json, exp.timestamp, evidence_state,
                         verifiability_state, verifiability_state, record_id),
                    )
                    self._conn.commit()
                    logger.debug("Duplicate experience merged into id=%s", record_id)
                    return record_id

            cur.execute(
                """
                INSERT INTO experience_records
                    (skill_name, context, result, success, timestamp, feedback,
                     agent_id, session_id, execution_time, confidence_score, tags, created_at,
                     content_key, seen_count, evidence_state, verifiability_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    skill_name,
                    context_json,
                    result_json,
                    success_flag,
                    exp.timestamp,
                    exp.feedback,
                    agent_id,
                    session_id,
                    execution_time,
                    confidence_score,
                    tags_json,
                    created_at,
                    content_key,
                    evidence_state,
                    verifiability_state,
                ),
            )
            self._conn.commit()
            record_id: int = cur.lastrowid or 0

        logger.debug("Added experience record id=%s for skill=%s", record_id, skill_name)
        return record_id

    def record_injection_adoption(
        self, record_ids: Optional[List[int]], adopted: Optional[bool]
    ) -> int:
        """按本轮注入身份集回写采纳结果（工单 006 的唯一 UPDATE 通路）。

        Args:
            record_ids: 本轮实际注入过的经验行 id（空 ⇒ 什么都不写）
            adopted: 本轮客观成败三态（002 语义）；None = 没有客观回执

        Returns:
            真正被更新的行数（不存在的 id 不计）——调用方拿它做可观测计数。

        "没注入"与"注入后失败"是两件事：ids 为空时直接返回 0，绝不把未发生的
        采纳写成 failure（那会凭空给经验行泼脏水，007 的降权随之失真）。
        """
        if not record_ids:
            return 0
        outcome = "unevidenced" if adopted is None else ("success" if adopted else "failure")
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updated = 0
        with self._lock:
            cur = self._conn.cursor()
            for rid in record_ids:
                cur.execute(
                    """
                    UPDATE experience_records
                    SET injected_count = injected_count + 1,
                        last_injected_at = ?,
                        adoption_outcome = ?
                    WHERE id = ?
                    """,
                    (stamp, outcome, int(rid)),
                )
                updated += cur.rowcount
            self._conn.commit()
        logger.debug("经验采纳回写 %s 行 (outcome=%s)", updated, outcome)
        return updated

    # 人工处置态取值（工单 015）；None = 未处置/已恢复
    OPERATOR_DISPOSITIONS = ("endorsed", "demoted", "suppressed")
    # 降权档位在采纳证据之下再扣一档：人工判断压在客观证据之下，不是并列。
    # 0.45 不是拍的：证据档跨度是 +0.15（success）到 −0.25（failure），罚分必须大于
    # 这个跨度，否则"被降权的成功条"仍然压在"客观失败条"上面，降权等于没降。
    DEMOTION_PENALTY = 0.45
    # 逐字可核违规的罚分（工单 001）：0.30 取在证据档跨度（0.40）之内、人工处罚
    # （0.45）之下——编造的路径/版本比"照它做砸了"更该躲，但一个人明确说了
    # "这条别用"仍排在更后面（人的否定语义更强）。
    VERIFIABILITY_PENALTY = 0.30

    def set_operator_disposition(self, record_ids: Optional[List[int]], disposition: Optional[str]) -> int:
        """登记人工处置态：审核通过 / 降权 / 隐藏 / 恢复。可逆，不删行，不碰证据列。

        Args:
            record_ids: 目标行 id（空 ⇒ 返回 0，什么都不写）
            disposition: 'endorsed' | 'demoted' | 'suppressed' | None（恢复未处置）

        Returns:
            实际被更新的行数（不存在的 id 不计）

        为什么另起一列而不复用 `record_injection_adoption` 那张格子：那一格写的是
        **执行证据**，由 006 的回写通路独占。把"人工审核通过"落成
        `adoption_outcome='success'` 等于把人的判断洗成客观成功票——007 的排序与
        008 的 `adoption_success_rate` 会一起吃进假账。删除仍是另一个动作
        （`delete_record`），处置通路全程不删行。
        """
        if disposition is not None and disposition not in self.OPERATOR_DISPOSITIONS:
            raise ValueError(
                f"未知处置态 {disposition!r}；可选 {list(self.OPERATOR_DISPOSITIONS)} 或 None（恢复）"
            )
        if not record_ids:
            return 0
        updated = 0
        with self._lock:
            cur = self._conn.cursor()
            for rid in record_ids:
                cur.execute(
                    "UPDATE experience_records SET operator_disposition = ? WHERE id = ?",
                    (disposition, int(rid)),
                )
                updated += cur.rowcount
            self._conn.commit()
        logger.debug("经验人工处置 %s 行 (disposition=%s)", updated, disposition)
        return updated

    def quality_snapshot(self) -> Dict[str, Any]:
        """经验族质量读数（工单 008 的算式唯一来源）。

        Returns:
            rows: 库内条目数
            unevidenced_ratio: 形成侧无客观回执占比（无行时为 0.0，不读成"全无可疑"）
            hit_rate: 被注入过的条目占比（采纳证据的覆盖面）
            adoption_decisions: 有采纳结论（success/failure）的条目数
            adoption_success_rate: success/(success+failure)；无决策时为 None
            adoption_unevidenced: 注入过但本轮无回执的条目数（单列出来，不并入分母）

        两个"空"的方向不同是刻意的：`unevidenced_ratio=0.0` 配 `rows=0` 表示
        "没数据可判"，而 `adoption_success_rate=None` 表示"分母为零"——
        下游必须分开处理，把 None 兜成 0.0 就是把"没测到"读成"全失败"。
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS rows,
                       SUM(CASE WHEN evidence_state = 'unevidenced' THEN 1 ELSE 0 END) AS unevidenced,
                       SUM(CASE WHEN injected_count > 0 THEN 1 ELSE 0 END) AS injected,
                       SUM(CASE WHEN adoption_outcome = 'success' THEN 1 ELSE 0 END) AS a_success,
                       SUM(CASE WHEN adoption_outcome = 'failure' THEN 1 ELSE 0 END) AS a_failure,
                       SUM(CASE WHEN adoption_outcome = 'unevidenced' THEN 1 ELSE 0 END) AS a_unevidenced
                FROM experience_records
                """
            ).fetchone()
        total = int(row["rows"] or 0)
        decisions = int(row["a_success"] or 0) + int(row["a_failure"] or 0)
        return {
            "rows": total,
            "unevidenced_ratio": (int(row["unevidenced"] or 0) / total) if total else 0.0,
            "hit_rate": (int(row["injected"] or 0) / total) if total else 0.0,
            "adoption_decisions": decisions,
            "adoption_success_rate": (int(row["a_success"] or 0) / decisions) if decisions else None,
            "adoption_unevidenced": int(row["a_unevidenced"] or 0),
        }

    def experience_counts_by_skill(
        self, agent_id: Optional[str] = None
    ) -> Dict[Tuple[Optional[str], str], int]:
        """(agent_id, skill_name) → 条目数（工单 015：运营视图的"经验数"必须是真聚合）。

        此前 API 硬编码 1，同一技能在生产库里攒到 7 条，界面上仍然显示 1。
        键带 agent 维：`/ranking` 可以不传 agent_id（跨 Agent 浏览），
        此时把别人的条目算进本行就是假数。
        """
        sql = "SELECT agent_id, skill_name, COUNT(*) AS n FROM experience_records"
        params: List[Any] = []
        if agent_id is not None:
            sql += " WHERE agent_id = ?"
            params.append(agent_id)
        sql += " GROUP BY agent_id, skill_name"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return {(r["agent_id"], r["skill_name"]): int(r["n"]) for r in rows}

    def get_experience_records(
        self,
        skill_name: str = "",
        success_only: Optional[bool] = None,
        limit: Optional[int] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取经验记录（运营浏览序：待处置优先、其次写入序）

        Args:
            skill_name: 技能名（空字符串=不限技能）
            success_only: True 仅成功，False 仅失败，None 全部
            limit: 返回数量上限
            agent_id: 限定 Agent（None=不限）

        Returns:
            记录字典列表（每条含 skill_name/success 等字段，success 为 int 0/1）

        排序口径（007 登记给 015）：`ORDER BY id DESC` 会把"上次做砸了还没人看过"
        的条目埋在中段；纯按证据排又会让新入库的沉到底、运营看不见。
        故**待处置顶到最前，组内保持写入序**。待处置 = 未人工处置且
        （采纳失败 / 注入无回执 / 形成侧无客观凭据）。
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

        sql += (
            " ORDER BY CASE WHEN operator_disposition IS NULL AND ("
            "adoption_outcome IN ('failure', 'unevidenced')"
            " OR evidence_state = 'unevidenced') THEN 0 ELSE 1 END, id DESC"
        )
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
        min_relevance: float = 0.15,
    ) -> List[Dict[str, Any]]:
        """查找相似经验

        相似度算法（工单 007 之后）：
        - 相关性 = 关键词重叠 60% + 话题匹配 30%，低于 `min_relevance` 直接出局
          （旧门是布尔的：共一个 2-gram 也算命中）；
        - 采纳后证据（`adoption_outcome`，工单 006 回写）参与排序：
          success +0.15 / 无记录按形成侧 success ± / unevidenced +0.03 / failure -0.25，
          全部降权而非剔除（D1）；
        - 排序键 = 相关性 + 质量，`similarity_score` 一并回给注入侧用于优先级。
        - 人工处置（工单 015）吃同一条链：`suppressed` 直接出局，`demoted` 在证据档
          之下再扣一档，`endorsed` 不动分数（它登记的是"人看过"，不是"执行成功过"）。

        Args:
            skill_name: 限定技能（None 则跨所有技能）
            context: 查询上下文（含 user_input/topic）
            limit: 返回数量上限（top_k 为旧别名，优先级低于 limit）
            top_k: 旧参数别名（向后兼容 injector.py）
            agent_id: 限定 Agent（None 不限）
            min_relevance: 相关性门槛（默认 0.15；拨到 0 等于只要沾边就放行）

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
            # 人工隐藏（工单 015）：出局但行还在——"别再注入"和"永不许存在"（删除）
            # 是两个动作，混在一起运营就只能靠删数据来止血。
            disposition = d.get("operator_disposition")
            if disposition == "suppressed":
                continue
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

            # 相关性门（工单 007）：门只看**相关性**，质量分不得替无关条目买路。
            # 旧形态 `keyword_score > 0 or topic_score > 0` 是布尔的——查询与条目
            # 只共一个 2-gram 也算命中（P2-B4 收口后仍留着这个洞）。
            relevance = 0.6 * keyword_score + 0.3 * topic_score
            if relevance < min_relevance:
                continue

            # 采纳后证据（工单 006 的回写列）参与排序：007 之前质量只有 0.1 权重
            # 且取自那个恒为 1 的位，等于没有质量。D1 口径：全部降权而非剔除——
            # "照这条做砸了"本身是仍要能被查到的经验。
            # 无采纳记录（NULL）回落到形成侧的 success 位，既不升权也不凭空降权。
            outcome = d.get("adoption_outcome")
            if outcome == "success":
                quality_score = 0.15
            elif outcome == "failure":
                quality_score = -0.25
            elif outcome == "unevidenced":
                quality_score = 0.03
            elif d.get("success") is None:
                # 工单 004：`success` 为 NULL 是"这轮没测到"。旧写法
                # `0.1 if d.get("success") else -0.05` 把 NULL 折进失败分支，
                # 等于给未测量的行按真失败罚分（罚分必须只对真失败生效）。
                # 与 `unevidenced` 同档：可见、不升权、不扣分。
                quality_score = 0.03
            elif d.get("success") and d.get("evidence_state") == "unevidenced":
                # 工单 010：无服务端票据的"成功"是自述，不是成功票。002 之后
                # success 位开始携带信息，但它带的可能是本轮工具回执甚至关键词
                # 粗分——按 0.1 升权等于让 002 的降权形同虚设（同 adoption
                # 'unevidenced' 一档：可见、不升权，也不凭空扣分）。
                quality_score = 0.03
            else:
                quality_score = 0.1 if d.get("success") else -0.05

            similarity = relevance + quality_score
            # 逐字可核违规（工单 001）降权不剔除：这条经验引用了原文里不存在的
            # 路径/版本，照它做的代价比"没经验"更大，但它本身仍是一条可查的
            # 记录（也可能是唯一记录下"这轮出过幻觉"的行）。`unchecked` 不扣分：
            # 没核过不是核出问题，扣它等于替未被改造的调用点罚分。
            if d.get("verifiability_state") == "violated":
                similarity -= self.VERIFIABILITY_PENALTY
            # 人工降权（工单 015）压在证据档之下再扣一档：`endorsed` 刻意**不**加分，
            # 人的判断不是执行证据，加上去等于把审核洗成成功票。
            if disposition == "demoted":
                similarity -= self.DEMOTION_PENALTY
            d["similarity_score"] = round(similarity, 4)
            scored.append((similarity, d))

        # 按相似度降序
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:effective_limit]]

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
