"""渠道发送者 ↔ 平台账号的绑定存储（工单 `2026-10-10-渠道身份绑定与群聊记忆分账` 批 1）。

补的是 §6-127 记的那处"先声明、后无人实装"：`channels/models.py:98` 的 `UserIdentity` 有形状、
无管理器（`test_p3_p4_refactor.py` 整格 skip 就是为此）。这里只加**存储与解析**，
不改任何渠道路径的取值——接入在批 2（那时才动 `channel_router` 的 meta 与记忆作用域）。

三条口径写在这里，是因为它们都不可逆或会被绕过：

1. **唯一键含 `agent_id`**（裁定 ③＝agent 级）：同一渠道用户在 N 个 agent 下要各绑一次。
   代价如实记在这里，别到读侧才发现"绑过一次怎么另一个 bot 不认"。
2. **未绑定的命名空间复用技能库既有口径** `ch:{渠道}:{发送者}`（`skill_visibility.py:138-161`），
   不另造第二种键（教义第 6 条）。绑定成功只改**今后**写入的归属，历史留在原命名空间、
   由读侧双读——合并搬迁是不可逆动作，未裁不做。
3. **本模块不解析入站报文自带的 `user_id`**：渠道报文里的同名字段一律不信，
   身份只能由这张表得出，否则外部可冒充平台账号（治理与审计会拿它查不存在的用户）。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.core.data_root import resolveDataPath
from neurova.core.logger import get_logger

logger = get_logger(__name__)


_DDL = """
CREATE TABLE IF NOT EXISTS channel_user_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    neuser_id TEXT,
    display_name TEXT,
    bound_by TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(agent_id, channel_type, channel_user_id)
)
"""
_DDL_INDEX_USER = (
    "CREATE INDEX IF NOT EXISTS idx_cub_user ON channel_user_bindings(user_id, agent_id)"
)

# 观察面与绑定面是两件事：绑定行＝"这个渠道身份算谁"的**决定**（可解绑、要留痕），
# 观察行＝"这个 agent 的这条渠道里见到过谁"（无决定语义，只是面板要能列出可绑的人）。
# 混进同一张表会让"revoked 留痕"和"见过但没绑"两种状态互相污染。
_DDL_OBSERVED = """
CREATE TABLE IF NOT EXISTS channel_observed_senders (
    agent_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    display_name TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    PRIMARY KEY (agent_id, channel_type, channel_user_id)
)
"""
_DDL_INDEX_OBSERVED = (
    "CREATE INDEX IF NOT EXISTS idx_cos_agent ON channel_observed_senders(agent_id, channel_type)"
)


class UserIdentityManager:
    """渠道身份绑定的唯一存储（DCL 单例 + `RLock`，与 `qclaw_binding_model` 同形态）。"""

    _instance: Optional["UserIdentityManager"] = None
    _instanceLock = threading.RLock()

    def __new__(cls, dbPath: Optional[str] = None) -> "UserIdentityManager":
        with cls._instanceLock:
            if cls._instance is None:
                created = super().__new__(cls)
                created._initialized = False
                cls._instance = created
            return cls._instance

    def __init__(self, dbPath: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self._dbPath = str(dbPath or resolveDataPath("channel_user_bindings.db"))
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initDb()
        self._initialized = True

    # ── 装配 ──

    def _initDb(self) -> None:
        with self._lock:
            conn = self._getConn()
            conn.execute(_DDL)
            conn.execute(_DDL_INDEX_USER)
            conn.execute(_DDL_OBSERVED)
            conn.execute(_DDL_INDEX_OBSERVED)
            conn.commit()

    def _getConn(self) -> sqlite3.Connection:
        if self._conn is None:
            # 常驻连接跨线程复用：写侧在渠道事件循环（绑定消息），读侧也可能在 API 线程池
            # （绑定面板）。缺 `check_same_thread=False` 时第二次跨线程取数直接
            # ProgrammingError → 500，与本仓另外 21 处常驻存储同一形态；所有操作都在
            # `self._lock`（RLock）里串行，故无需再依赖 sqlite 的线程模式。
            self._conn = sqlite3.connect(self._dbPath, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @classmethod
    def resetInstance(cls) -> None:
        """测试/teardown 用：换库路径或清场时重建单例（沿 `ExecutionEngine` 那套收口）。"""
        with cls._instanceLock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                except Exception:  # noqa: BLE001 - 关不掉不该阻止重建
                    logger.debug("关闭 UserIdentityManager 连接失败", exc_info=True)
            cls._instance = None

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── 写面 ──

    def bindIdentity(
        self,
        agentId: str,
        channelType: str,
        channelUserId: str,
        userId: str,
        *,
        neuserId: Optional[str] = None,
        displayName: Optional[str] = None,
        boundBy: str = "",
    ) -> Dict[str, Any]:
        """把一个渠道发送者绑到平台账号；同 `(agent, 渠道, 发送者)` 再绑即换主（覆盖并刷新时间）。

        空 `userId` 与缺省身份一律拒：那等于把渠道发送者塞回 `default` 共享桶——
        正是 §6-123 要消掉的那个形态，不能由这张表重新制造。

        `neuserId` 缺省取 `userId`，但绑定入口应当把登录态的两个 id 都传进来：
        记忆隔离键是 `{agent}:{neuser_id}:{user_id}` 两元组（`api/deps.py:118-125` 从 JWT 成对取），
        只存一个就复现不出控制台写入的那个键，渠道侧读起来会变成"同一个人两份记忆"。
        """
        agentId = str(agentId or "").strip()
        channelType = str(channelType or "").strip()
        channelUserId = str(channelUserId or "").strip()
        userId = str(userId or "").strip()
        if not (agentId and channelType and channelUserId):
            raise ValueError("绑定三键（agent/渠道/渠道发送者）都不得为空")
        # "非个人身份"的闭集只有一处定义（`skill_visibility._SYSTEM_IDENTITIES`），这里不另立
        # 第二套名单：这张表不得把渠道发送者重新塞回共享桶——那正是 §6-123 的成因。
        # 取数走懒加载（channels ← skills 顶层互引会拉出循环，见 AGENTS.md §3）。
        from neurova.skills.skill_visibility import _SYSTEM_IDENTITIES
        if not userId or userId.lower() in _SYSTEM_IDENTITIES:
            raise ValueError(
                f"绑定目标必须是真实平台账号，不得是 {sorted(_SYSTEM_IDENTITIES)} 里的非个人身份")

        now = time.time()
        with self._lock:
            conn = self._getConn()
            conn.execute(
                """
                INSERT INTO channel_user_bindings
                    (agent_id, channel_type, channel_user_id, user_id, neuser_id,
                     display_name, bound_by, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(agent_id, channel_type, channel_user_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    neuser_id = excluded.neuser_id,
                    display_name = excluded.display_name,
                    bound_by = excluded.bound_by,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (agentId, channelType, channelUserId, userId, neuserId or userId,
                 displayName, boundBy, now, now),
            )
            conn.commit()
        return {
            "agent_id": agentId,
            "channel_type": channelType,
            "channel_user_id": channelUserId,
            "user_id": userId,
            "neuser_id": neuserId or userId,
            "display_name": displayName,
            "bound_by": boundBy,
            "status": "active",
        }

    def revokeBinding(self, agentId: str, channelType: str, channelUserId: str) -> bool:
        """解绑：置 `revoked` 而不是删行——留痕才能回答"这个人以前算谁的"。"""
        with self._lock:
            conn = self._getConn()
            cur = conn.execute(
                "UPDATE channel_user_bindings SET status='revoked', updated_at=?"
                " WHERE agent_id=? AND channel_type=? AND channel_user_id=?"
                " AND status='active'",
                (time.time(), str(agentId), str(channelType), str(channelUserId)),
            )
            conn.commit()
            return cur.rowcount > 0

    # ── 读面 ──

    def resolveUserId(self, agentId: str, channelType: str, channelUserId: str) -> Optional[str]:
        """已绑定 → 平台账号；未绑定/已解绑 → None（由调用方回落到渠道命名空间）。"""
        with self._lock:
            row = self._getConn().execute(
                "SELECT user_id FROM channel_user_bindings"
                " WHERE agent_id=? AND channel_type=? AND channel_user_id=?"
                " AND status='active'",
                (str(agentId), str(channelType), str(channelUserId)),
            ).fetchone()
        return str(row["user_id"]) if row else None

    def resolveTurnIdentity(
        self, agentId: str, channelType: str, channelUserId: str
    ) -> Dict[str, str]:
        """渠道路径唯一的"这一轮是谁"出口：已绑→平台账号对，未绑→渠道专属命名空间。

        两条都不留空：未绑定时返回 `ch:{渠道}:{发送者}` 而不是 `"default"`——把所有人
        塞进一个桶正是 §6-123 的成因。绑定后的"提升"只改**今后**写入的归属，历史仍留在
        原命名空间（合并搬迁不可逆，未裁不做）。
        """
        bound = self.resolveBinding(agentId, channelType, channelUserId)
        if bound:
            return {"user_id": bound["user_id"], "neuser_id": bound["neuser_id"],
                    "bound": "true"}
        namespace = self.channelNamespace(channelType, channelUserId)
        return {"user_id": namespace, "neuser_id": namespace, "bound": "false"}

    def resolveBinding(self, agentId: str, channelType: str,
                       channelUserId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._getConn().execute(
                "SELECT user_id, neuser_id, display_name, bound_by FROM channel_user_bindings"
                " WHERE agent_id=? AND channel_type=? AND channel_user_id=?"
                " AND status='active'",
                (str(agentId), str(channelType), str(channelUserId)),
            ).fetchone()
        return dict(row) if row else None

    def listBindings(self, agentId: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._getConn().execute(
                "SELECT agent_id, channel_type, channel_user_id, user_id, neuser_id, display_name,"
                " bound_by, status, created_at, updated_at FROM channel_user_bindings"
                " WHERE agent_id=? ORDER BY updated_at DESC",
                (str(agentId),),
            ).fetchall()
        return [dict(row) for row in rows]

    def boundChannelUsers(self, agentId: str, userId: str) -> List[Dict[str, Any]]:
        """一个平台账号在该 agent 下绑了哪些渠道身份（①"不同渠道可绑同一 userID"的正向读面）。"""
        with self._lock:
            rows = self._getConn().execute(
                "SELECT channel_type, channel_user_id, display_name FROM channel_user_bindings"
                " WHERE agent_id=? AND user_id=? AND status='active'"
                " ORDER BY channel_type, channel_user_id",
                (str(agentId), str(userId)),
            ).fetchall()
        return [dict(row) for row in rows]

    def observeSender(self, agentId: str, channelType: str, channelUserId: str,
                      displayName: Optional[str] = None) -> Dict[str, Any]:
        """登记"这个 agent 的这条渠道里见到过这个发送者"（工单批 6，裁定「按渠道查人要建」）。

        写点在渠道路径上（每条入站消息一次），读点是控制台的绑定面板——没有这一面，
        面板就只能让用户自己抄 `ou_xxx` 这种平台内部 ID，而人抄不到自己的 open_id。

        命名空间走 `registerUser()`（同一出处），不在这里再拼一次 `ch:` 串。
        重复观察只推进 `last_seen` 与显示名，`first_seen` 不动（面板要能答"什么时候见过"）。
        """
        agentId = str(agentId or "").strip()
        channelType = str(channelType or "").strip()
        channelUserId = str(channelUserId or "").strip()
        if not (agentId and channelType and channelUserId):
            raise ValueError("观察登记需要 agent/渠道/渠道发送者三键")
        identity = self.registerUser(channelType, channelUserId, displayName)

        now = time.time()
        with self._lock:
            conn = self._getConn()
            conn.execute(
                """
                INSERT INTO channel_observed_senders
                    (agent_id, channel_type, channel_user_id, namespace,
                     display_name, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, channel_type, channel_user_id) DO UPDATE SET
                    display_name = COALESCE(excluded.display_name, display_name),
                    last_seen = excluded.last_seen
                """,
                (agentId, channelType, channelUserId, identity.user_id,
                 displayName, now, now),
            )
            conn.commit()
        return {
            "agent_id": agentId,
            "channel_type": channelType,
            "channel_user_id": channelUserId,
            "namespace": identity.user_id,
            "display_name": displayName,
        }

    def listObservedSenders(self, agentId: str,
                            channelType: Optional[str] = None) -> List[Dict[str, Any]]:
        """该 agent 观察到的渠道发送者，并带出它当前绑到谁（面板据此分"已绑/可绑"）。

        `bound_user_id` 来自同一张绑定表的 active 行——面板不必再猜，也不许前端自己
        拿两份数据对（对错了就会把已绑的人再摆成"绑给我自己"）。
        """
        sql = (
            "SELECT o.agent_id, o.channel_type, o.channel_user_id, o.namespace,"
            " o.display_name, o.first_seen, o.last_seen,"
            " b.user_id AS bound_user_id, b.neuser_id AS bound_neuser_id"
            " FROM channel_observed_senders o"
            " LEFT JOIN channel_user_bindings b"
            " ON b.agent_id = o.agent_id AND b.channel_type = o.channel_type"
            " AND b.channel_user_id = o.channel_user_id AND b.status = 'active'"
            " WHERE o.agent_id = ?"
        )
        args: List[Any] = [str(agentId)]
        if channelType:
            sql += " AND o.channel_type = ?"
            args.append(str(channelType))
        sql += " ORDER BY o.last_seen DESC LIMIT 200"
        with self._lock:
            rows = self._getConn().execute(sql, tuple(args)).fetchall()
        return [dict(row) for row in rows]

    def registerUser(self, channel, channelUserId: str,
                     displayName: Optional[str] = None):
        """未绑定发送者的身份登记：返回条目的 `user_id` 就是渠道专属命名空间（裁定 ①）。

        这只**命名**、不落绑定表——真绑定时 `bindIdentity` 才写行。返回 `UserIdentity`
        （`channels/models.py:98` 那个 dataclass）是为了让调用方拿到的形状与既有导出一致，
        不再另外发明一个"身份"类型。
        """
        from neurova.channels.models import UserIdentity
        channelValue = getattr(channel, "value", channel)
        namespace = self.channelNamespace(str(channelValue or ""), channelUserId)
        if not namespace:
            raise ValueError("登记渠道身份需要渠道与渠道发送者ID")
        return UserIdentity(user_id=namespace, channel=channel,
                            channel_user_id=str(channelUserId), display_name=displayName)

    @staticmethod
    def channelNamespace(channelType: str, channelUserId: str) -> str:
        """未绑定发送者的隔离命名空间——口径与 `skill_visibility.resolve_user_key` 同源。

        刻意与 `skills/skill_visibility.py` 的 `ch:{渠道}:{发送者}` 同形（同一用户在三处
        ——技能库、记忆、审计——必须是同一个键）；两边各有前缀字面量属**协议**而非实现，
        改任一处都要同步，本方法的单测就是那条同步钉。
        """
        channel = str(channelType or "").strip()
        sender = str(channelUserId or "").strip()
        if not channel or not sender:
            return ""
        return f"ch:{channel}:{sender}"


__all__ = ["UserIdentityManager"]
