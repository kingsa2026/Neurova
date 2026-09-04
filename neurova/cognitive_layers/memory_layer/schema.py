"""
Schema Module — 数据库 Schema 定义与迁移

管理 SQLite 数据库的 DDL 创建和旧版本迁移逻辑。
"""

from neurova.core.logger import get_logger
import sqlite3
import threading

logger = get_logger(__name__)


def init_schema(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """初始化数据库 schema

    Args:
        conn: 数据库连接
        lock: 线程锁
    """
    with lock:
        cursor = conn.cursor()

        # ── memories 表 ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                neuser_id TEXT NOT NULL DEFAULT 'default',
                user_id TEXT NOT NULL DEFAULT 'default',
                agent_id TEXT NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                categories TEXT DEFAULT '[]',
                content TEXT NOT NULL,
                channel TEXT DEFAULT 'default',
                weight REAL DEFAULT 1.0,
                importance REAL DEFAULT 0.5,
                temperature REAL DEFAULT 50.0,
                lifecycle_stage TEXT DEFAULT 'active',
                is_important INTEGER DEFAULT 0,
                is_crystallized INTEGER DEFAULT 0,
                crystallized_at TEXT,
                emotion_score REAL DEFAULT 0.0,
                emotion_tags TEXT DEFAULT '[]',
                perspective TEXT DEFAULT 'ai_inference',
                perspective_confidence REAL DEFAULT 1.0,
                origin TEXT NOT NULL DEFAULT 'agent',
                source TEXT,
                access_count INTEGER DEFAULT 0,
                last_accessed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                attachment_ids TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}'
            )
        """)

        # ── FTS5 全文搜索 ──
        try:
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content)
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT OR REPLACE INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT OR REPLACE INTO memories_fts(rowid, content) VALUES (old.rowid, '');
                END
            """)
        except sqlite3.OperationalError:
            logger.warning("FTS5 not available, full-text search will be disabled")

        # ── 用户隔离索引 ──
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_neuser_id ON memories(neuser_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_neuser_user ON memories(neuser_id, user_id)")
        except sqlite3.OperationalError:
            pass

        # ── dream_reports 表 ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dream_reports (
                id TEXT PRIMARY KEY,
                neuser_id TEXT NOT NULL DEFAULT 'default',
                user_id TEXT NOT NULL DEFAULT 'default',
                agent_id TEXT NOT NULL DEFAULT 'yi_ling',
                session_id TEXT,
                report_type TEXT NOT NULL DEFAULT 'sleep_consolidation',
                total_processed INTEGER DEFAULT 0,
                merged_count INTEGER DEFAULT 0,
                archived_count INTEGER DEFAULT 0,
                merged_details TEXT DEFAULT '[]',
                archived_ids TEXT DEFAULT '[]',
                consolidation_quality REAL DEFAULT 0.0,
                emotional_intensity REAL DEFAULT 0.0,
                memory_coherence_score REAL DEFAULT 0.0,
                sleep_start_at TEXT,
                sleep_end_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT DEFAULT '{}'
            )
        """)

        # ── dream_reports 索引 ──
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dream_reports_neuser_id ON dream_reports(neuser_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_dream_reports_user_id ON dream_reports(user_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_dream_reports_neuser_user ON dream_reports(neuser_id, user_id)"
            )
        except sqlite3.OperationalError:
            pass

        # ── memories 辅助索引 ──
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_agent_id ON memories(agent_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_channel ON memories(channel)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_temperature ON memories(temperature)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_lifecycle ON memories(lifecycle_stage)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_crystallized ON memories(is_crystallized)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)")
        # MoE 路由器复合索引（加速 _layer0_exact_index 查询）— 像髓鞘化的神经通路
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_moe_composite ON memories(category, lifecycle_stage, is_crystallized)"
        )

        # ── memory_relations 表 ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_relations (
                id TEXT PRIMARY KEY,
                source_memory_id TEXT NOT NULL,
                target_memory_id TEXT NOT NULL,
                relation_type TEXT NOT NULL DEFAULT 'related',
                strength REAL NOT NULL DEFAULT 1.0,
                source_neuser_id TEXT NOT NULL DEFAULT 'default',
                source_user_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY (target_memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mr_source ON memory_relations(source_memory_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mr_target ON memory_relations(target_memory_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mr_type ON memory_relations(relation_type)")

        # ── trigger_chains 表 ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trigger_chains (
                chain_id TEXT PRIMARY KEY,
                trigger_type TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                success INTEGER DEFAULT 0,
                result_memory_ids TEXT DEFAULT '[]',
                neuser_id TEXT NOT NULL DEFAULT 'default',
                user_id TEXT NOT NULL DEFAULT 'default',
                agent_id TEXT NOT NULL DEFAULT 'yi_ling',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── trigger_chain_nodes 表 ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trigger_chain_nodes (
                node_id TEXT PRIMARY KEY,
                chain_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                description TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                input TEXT DEFAULT '{}',
                output TEXT DEFAULT '{}',
                parent_node_id TEXT,
                neuser_id TEXT NOT NULL DEFAULT 'default',
                user_id TEXT NOT NULL DEFAULT 'default',
                agent_id TEXT NOT NULL DEFAULT 'yi_ling',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chain_id) REFERENCES trigger_chains(chain_id) ON DELETE CASCADE
            )
        """)

        # ── 索引 ──
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tc_neuser_id ON trigger_chains(neuser_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tc_user_id ON trigger_chains(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tc_agent_id ON trigger_chains(agent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tc_trigger_type ON trigger_chains(trigger_type)")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tcn_chain_id ON trigger_chain_nodes(chain_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tcn_neuser_id ON trigger_chain_nodes(neuser_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tcn_user_id ON trigger_chain_nodes(user_id)")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        logger.info("Database schema initialized")


def migrate_schema(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """数据库迁移：为现有表添加新字段（如果不存在）

    Args:
        conn: 数据库连接
        lock: 线程锁
    """
    try:
        with lock:
            # memories 表：添加 neuser_id
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN neuser_id TEXT NOT NULL DEFAULT 'default'")
                logger.info("Migrated memories table: added neuser_id column")
            except sqlite3.OperationalError:
                pass

            # memories 表：添加 user_id
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
                logger.info("Migrated memories table: added user_id column")
            except sqlite3.OperationalError:
                pass

            # dream_reports 表：添加 neuser_id
            try:
                conn.execute("ALTER TABLE dream_reports ADD COLUMN neuser_id TEXT NOT NULL DEFAULT 'default'")
                logger.info("Migrated dream_reports table: added neuser_id column")
            except sqlite3.OperationalError:
                pass

            # memories 表：添加 categories
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN categories TEXT DEFAULT '[]'")
                logger.info("Migrated memories table: added categories column")
            except sqlite3.OperationalError:
                pass

            # memories 表：添加 importance
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN importance REAL DEFAULT 0.5")
                logger.info("Migrated memories table: added importance column")
            except sqlite3.OperationalError:
                pass

            # memories 表：添加 origin（P1-9 来源信任分级，闭集 owner/agent/untrusted/system）
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN origin TEXT NOT NULL DEFAULT 'agent'")
                logger.info("Migrated memories table: added origin column")
            except sqlite3.OperationalError:
                pass

            # dream_reports 表：添加 user_id
            try:
                conn.execute("ALTER TABLE dream_reports ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
                logger.info("Migrated dream_reports table: added user_id column")
            except sqlite3.OperationalError:
                pass

            # 用户隔离索引（幂等）
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_neuser_id ON memories(neuser_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_neuser_user ON memories(neuser_id, user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dream_reports_neuser_id ON dream_reports(neuser_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dream_reports_user_id ON dream_reports(user_id)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_dream_reports_neuser_user ON dream_reports(neuser_id, user_id)"
                )
                conn.commit()
                logger.info("Database migration completed successfully")
            except sqlite3.OperationalError:
                pass

    except Exception as e:
        logger.error("Database migration failed: %s", e)
