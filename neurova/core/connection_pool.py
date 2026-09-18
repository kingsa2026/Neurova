"""
数据库连接池

提供SQLite连接池管理，支持：
- 连接复用
- 线程安全
- 自动重连
- 连接超时

P0-2 治理点：
- 归还连接前强制 rollback（未提交事务会被下个借用者继承，WAL 下表现为
  长事务持锁）；
- 连接创建/销毁向 core/metrics.py 计数（"连接创建/销毁频率"基线）；
- idle/active/total 连接数以 gauge 暴露（observe_pools 抓取，见 metrics.py）。
"""

import sqlite3
import threading
from neurova.core.logger import get_logger
from typing import Optional
from contextlib import contextmanager
from queue import Queue, Empty, Full

logger = get_logger(__name__)


def _metric_created(db_path: str) -> None:
    """连接创建埋点（lazy import：metrics 依赖第三方 prometheus_client）。"""
    try:
        from neurova.core.metrics import record_db_connection_created

        record_db_connection_created(db_path)
    except Exception:  # noqa: BLE001 - 埋点失败不影响连接管理
        logger.debug("db created metric failed", exc_info=True)


def _metric_closed(db_path: str) -> None:
    """连接销毁埋点。"""
    try:
        from neurova.core.metrics import record_db_connection_closed

        record_db_connection_closed(db_path)
    except Exception:  # noqa: BLE001
        logger.debug("db closed metric failed", exc_info=True)


class SQLiteConnectionPool:
    """SQLite连接池
    
    使用队列管理连接，支持线程安全的连接获取和释放。
    """
    
    def __init__(
        self,
        db_path: str,
        max_connections: int = 5,
        timeout: float = 30.0,
        check_same_thread: bool = False,
    ):
        """
        初始化连接池
        
        Args:
            db_path: 数据库文件路径
            max_connections: 最大连接数
            timeout: 连接获取超时时间（秒）
            check_same_thread: 是否检查线程一致性（SQLite默认True）
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self.check_same_thread = check_same_thread
        # PRAGMA 基线：连接级状态，借用者可改写 → 归还时复原（防污染下个借用者）。
        # busy_timeout 显式声明：池化后写竞争等待时长必须可读、可预期。
        self._pragmas = (
            "PRAGMA journal_mode=WAL",
            "PRAGMA foreign_keys=ON",
            f"PRAGMA busy_timeout={int(self.timeout * 1000)}",
        )
        
        self._pool: Queue = Queue(maxsize=max_connections)
        self._lock = threading.RLock()
        self._created_count = 0
        # 本池创建的连接集合（P1-4 前置）：return_db_conn 需要判定"这条连接
        # 归哪个池"。没有归属校验时，它按 _get_all_pools() 顺序逐个尝试归还，
        # 而任意有效连接都能通过 SELECT 1 —— 于是 A 库的连接会被塞进 B 库的池，
        # 之后 B 库的借用者拿到的其实是 A 库的连接（跨库串用，静默数据错乱）。
        self._owned: set = set()
        # 当前已借出（不在队列里）的连接。用于识别"重复归还"——把同一个连接
        # 归还两次会让队列里出现两条同一连接，两个借用者拿到同一条连接并发
        # 读写（静默数据错乱）。仅靠"owned 里有没有"判不出来：归还后连接仍在
        # owned 集合里（它依然是本池创建的），必须单独跟踪借出状态。
        self._checked_out: set = set()
        
        logger.debug("连接池初始化: db=%s, max_conn=%d", db_path, max_connections)
    
    def _create_connection(self) -> sqlite3.Connection:
        """创建新的数据库连接（按 self._pragmas 基线设定）。

        基线显式声明而不是依赖 `timeout=` 的隐式副作用：`timeout=30.0` 恰好会
        把 busy_timeout 设成 30000ms，但那是 CPython 的实现细节，读代码的人
        看不出"写锁竞争会等多久"。PRAGMA 是可被借用者改写的连接级状态，
        故基线必须集中一处，并在归还时复原（见 `_restore_pragma_baseline`）。
        """
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=self.check_same_thread,
            timeout=self.timeout,
        )
        conn.row_factory = sqlite3.Row
        for pragma in self._pragmas:
            conn.execute(pragma)
        with self._lock:
            self._owned.add(conn)
        _metric_created(self.db_path)
        return conn
    
    def get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接
        
        优先从池中获取空闲连接，如果没有则创建新连接。
        
        Returns:
            sqlite3.Connection: 数据库连接
        """
        try:
            # 非阻塞取空闲连接：空池立即走创建分支。
            # 原实现的阻塞 get(timeout) 会让"空池首次调用"白等一个
            # timeout 才落到下面的创建分支（健康检查曾因此卡 30s）。
            conn = self._pool.get_nowait()
            # 验证连接是否有效
            try:
                conn.execute("SELECT 1")
                self._mark_checked_out(conn)
                return conn
            except sqlite3.ProgrammingError:
                # 连接已关闭：注销并计数，随后创建新连接
                self._discard_connection(conn)
        except Empty:
            pass
        
        # 创建新连接
        with self._lock:
            if self._created_count >= self.max_connections:
                logger.warning("连接池已满，等待可用连接")
                try:
                    conn = self._pool.get(timeout=self.timeout)
                    self._mark_checked_out(conn)
                    return conn
                except Empty:
                    raise RuntimeError("无法获取数据库连接：连接池超时")
            
            self._created_count += 1
        
        logger.debug("创建新连接: %s (总数: %d)", self.db_path, self._created_count)
        conn = self._create_connection()
        self._mark_checked_out(conn)
        return conn

    def _mark_checked_out(self, conn: sqlite3.Connection) -> None:
        """登记"已借出"。"""
        with self._lock:
            self._checked_out.add(conn)
    
    def owns(self, conn: sqlite3.Connection) -> bool:
        """这条连接是否由本池创建（归属校验；跨池归还防护用）。"""
        with self._lock:
            return conn in self._owned

    def return_connection(self, conn: sqlite3.Connection) -> bool:
        """
        归还连接到连接池

        P0-2：归还前回滚未提交事务。池是跨调用方复用的，若不回滚，调用方
        遗留的写事务会被下个借用者继承（WAL 下表现为长事务持锁、并发写被
        阻塞），且事务语义漂移到非预期连接上。

        P1-4：先做归属校验。非本池创建的连接直接返回 False，**不入池** ——
        否则 A 库的连接会进 B 库的池（跨库串用）。不能靠"SELECT 1 是否成功"
        判断归属：任何有效连接都能通过。

        Returns:
            bool: True 表示已归还本池（或已按本池规则丢弃）；False 表示这条
            连接不属于本池，调用方须另找归属方或自行关闭。
        """
        if conn is None:
            return True
        if not self.owns(conn):
            return False

        with self._lock:
            if conn not in self._checked_out:
                # 重复归还（同一连接还了两次）或归还了从未借出的连接。
                # 不得再入队：队列里出现重复条目会让两个借用者拿到同一条连接。
                logger.warning(
                    "连接重复归还，已忽略（db=%s）——请检查调用方是否成对借用/归还",
                    self.db_path,
                )
                return True
            self._checked_out.discard(conn)

        try:
            # 清理残留事务：脏连接不入池（WAL 长事务持锁根因）
            if conn.in_transaction:
                conn.rollback()
            # 验证连接是否有效
            conn.execute("SELECT 1")
            self._restore_pragma_baseline(conn)
            # 尝试放回池中
            self._pool.put_nowait(conn)
            return True
        except (sqlite3.ProgrammingError, sqlite3.OperationalError, Full):
            # 连接已关闭/回滚失败/池已满，丢弃连接
            self._discard_connection(conn)
            return True

    def _restore_pragma_baseline(self, conn: sqlite3.Connection) -> None:
        """归还前把连接级 PRAGMA 复原到池基线。

        池是跨调用方复用的：某借用者把 `busy_timeout` 改成 4000 后归还，
        下个借用者拿到的是 4000 —— 这种"配置漂移"静默且难查（也是"自持常驻
        连接不进池"的一条理由，见 ADR 0014）。只在值确实不同时改，避免每次
        归还都白付一次 PRAGMA 开销。
        """
        try:
            expected_timeout = int(self.timeout * 1000)
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            current = int(row[0]) if row else expected_timeout
            if current != expected_timeout:
                conn.execute(f"PRAGMA busy_timeout={expected_timeout}")
            # foreign_keys 被关掉会让写入绕过外键校验（静默数据风险）
            fk = conn.execute("PRAGMA foreign_keys").fetchone()
            if fk and not int(fk[0]):
                conn.execute("PRAGMA foreign_keys=ON")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            # 复原失败：连接不再可靠，交给调用方的异常路径丢弃
            raise

    def _discard_connection(self, conn: sqlite3.Connection) -> None:
        """关闭并注销一个不再入池的连接（统一 counting 出口）。"""
        with self._lock:
            known = conn in self._owned
            self._owned.discard(conn)
            self._checked_out.discard(conn)
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - close 失败不影响计数
            pass
        if not known:
            # 非本池连接：不递减本池计数（计数只反映本池创建量）
            return
        with self._lock:
            self._created_count -= 1
        _metric_closed(self.db_path)
    
    def close_all(self) -> None:
        """关闭所有连接"""
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    self._owned.discard(conn)
                    conn.close()
                    _metric_closed(self.db_path)
                except Exception:
                    pass
            # 借出中（不在队列里）的连接无处可关；清空归属登记，避免
            # 后续误把它们当本池连接归还进已关闭的池
            self._owned.clear()
            self._checked_out.clear()
            self._created_count = 0
        logger.debug("所有连接已关闭: %s", self.db_path)
    
    @contextmanager
    def connection(self):
        """
        上下文管理器，自动获取和归还连接
        
        Usage:
            with pool.connection() as conn:
                conn.execute("SELECT * FROM table")
        """
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)
    
    @property
    def pool_size(self) -> int:
        """当前池中空闲连接数"""
        return self._pool.qsize()
    
    @property
    def active_count(self) -> int:
        """当前活跃（已借出未归还）连接数。

        以借出登记为准，而不是 `created - idle`：后者把"已从队列取出但校验
        失败被丢弃"的中间态也算作 active，且并发下两个量取自不同时点。
        """
        with self._lock:
            return len(self._checked_out)

    @property
    def total_count(self) -> int:
        """当前池持有的连接总数（idle + active，即 _created_count）"""
        return self._created_count


# 全局连接池管理
_pools: dict = {}
_pools_lock = threading.Lock()


def get_connection_pool(
    db_path: str = "neurova_memory.db",
    max_connections: int = 5,
) -> SQLiteConnectionPool:
    """
    获取或创建数据库连接池
    
    Args:
        db_path: 数据库文件路径
        max_connections: 最大连接数
        
    Returns:
        SQLiteConnectionPool: 连接池实例
    """
    with _pools_lock:
        if db_path not in _pools:
            _pools[db_path] = SQLiteConnectionPool(
                db_path=db_path,
                max_connections=max_connections,
            )
            logger.info("创建连接池: %s (max_conn=%d)", db_path, max_connections)
        else:
            pool = _pools[db_path]
            if max_connections != pool.max_connections:
                # 池已存在时 max_connections 无法热改（在途连接语义未定义），
                # 但必须显式告警：静默忽略会让调用方以为限流已生效。
                logger.warning(
                    "连接池已存在，max_connections=%d 未生效（当前 %d）: %s",
                    max_connections,
                    pool.max_connections,
                    db_path,
                )
        return _pools[db_path]


def iter_pools():
    """遍历当前全部连接池（metrics 快照用；快照列表避免持锁调用）。"""
    with _pools_lock:
        return list(_pools.items())


def close_all_pools() -> None:
    """关闭所有连接池"""
    with _pools_lock:
        for db_path, pool in _pools.items():
            pool.close_all()
        _pools.clear()
    logger.info("所有连接池已关闭")


@contextmanager
def get_db_connection(db_path: str = "neurova_memory.db"):
    """
    获取数据库连接的便捷函数
    
    Usage:
        with get_db_connection() as conn:
            conn.execute("SELECT * FROM table")
    """
    pool = get_connection_pool(db_path)
    with pool.connection() as conn:
        yield conn
