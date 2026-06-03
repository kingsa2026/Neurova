#!/usr/bin/env python3
"""
数据库初始化脚本 - 按蓝图生成完整的记忆系统数据库结构
运行: cd Neurova && python -m memory.scripts.init_db
"""

import sqlite3
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, project_root)

def get_db_path() -> str:
    return os.path.join(project_root, 'memory', 'data', 'yi_ling_memory.db')

def create_all_tables(conn: sqlite3.Connection):
    """按蓝图创建所有表结构"""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        -- ==========================================
        -- 主表: 记忆
        -- ==========================================
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            type TEXT NOT NULL CHECK(type IN ('short_term', 'long_term', 'emotional')) DEFAULT 'long_term',
            category TEXT NOT NULL CHECK(category IN (
                'conversation', 'fact', 'profile', 'relationship',
                'skill', 'experience', 'lesson', 'task',
                'creative', 'emotional', 'instruction'
            )) DEFAULT 'conversation',
            content TEXT NOT NULL,
            content_hash TEXT,
            weight REAL DEFAULT 1.0,

            -- 温度与生命周期
            temperature REAL DEFAULT 50.0 CHECK(temperature >= 0 AND temperature <= 100),
            lifecycle_stage TEXT DEFAULT 'active' CHECK(lifecycle_stage IN ('active', 'secondary', 'archived', 'deleted')),
            is_archived INTEGER DEFAULT 0,
            access_count INTEGER DEFAULT 0,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            -- 记忆属性标记
            is_important INTEGER DEFAULT 0,
            is_crystallized INTEGER DEFAULT 0,
            crystallized_at TIMESTAMP,
            perspective TEXT DEFAULT 'ai_inference' CHECK(perspective IN ('user_statement', 'ai_inference', 'shared_experience', 'external_source', 'hypothetical', 'self_reflection')),
            perspective_confidence REAL DEFAULT 1.0,
            source TEXT,

            -- 情感与元数据
            emotion_score REAL DEFAULT 0.0,
            emotion_tags TEXT DEFAULT '[]',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            metadata TEXT DEFAULT '{}'
        );

        -- 全文检索虚拟表
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content,
            content='memories',
            content_rowid='rowid'
        );

        -- ==========================================
        -- 副表: 会话记录
        -- ==========================================
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            user_id TEXT,
            title TEXT DEFAULT 'New Session',
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived', 'closed')),
            message_count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            summary TEXT,
            last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 副表: 会话消息
        CREATE TABLE IF NOT EXISTS session_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            sequence_num INTEGER,
            is_summary INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        -- 副表: 上下文快照
        CREATE TABLE IF NOT EXISTS session_context_snapshots (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            query_hash TEXT NOT NULL,
            snapshot_data TEXT NOT NULL,
            token_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        -- ==========================================
        -- 副表: 情感记录
        -- ==========================================
        CREATE TABLE IF NOT EXISTS memory_emotions (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            emotion_type TEXT NOT NULL CHECK(emotion_type IN ('joy', 'sadness', 'anger', 'fear', 'surprise', 'disgust', 'neutral', 'hope')),
            intensity REAL NOT NULL CHECK(intensity >= 0.0 AND intensity <= 1.0),
            trigger_context TEXT,
            decay_rate REAL DEFAULT 0.05,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        -- ==========================================
        -- 副表: 记忆关联
        -- ==========================================
        CREATE TABLE IF NOT EXISTS memory_relations (
            id TEXT PRIMARY KEY,
            source_memory_id TEXT NOT NULL,
            target_memory_id TEXT NOT NULL,
            relation_type TEXT NOT NULL CHECK(relation_type IN ('related', 'caused_by', 'part_of', 'similar_to', 'contradicts', 'identity_connection', 'origin_connection')),
            strength REAL DEFAULT 1.0 CHECK(strength >= 0.0 AND strength <= 1.0),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY (target_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
            UNIQUE(source_memory_id, target_memory_id, relation_type)
        );

        -- ==========================================
        -- 副表: 关键词索引
        -- ==========================================
        CREATE TABLE IF NOT EXISTS memory_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            keyword TEXT NOT NULL,
            relevance REAL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        -- ==========================================
        -- 智能增强机制副表
        -- ==========================================

        -- 冲突表
        CREATE TABLE IF NOT EXISTS memory_conflicts (
            id TEXT PRIMARY KEY,
            conflict_type TEXT NOT NULL,
            memory_a_id TEXT NOT NULL,
            memory_b_id TEXT NOT NULL,
            conflict_description TEXT,
            severity TEXT DEFAULT 'medium',
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'detected',
            resolution_strategy TEXT,
            resolved_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY (memory_a_id) REFERENCES memories(id),
            FOREIGN KEY (memory_b_id) REFERENCES memories(id)
        );

        -- 联想图
        CREATE TABLE IF NOT EXISTS memory_associations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_a_id TEXT NOT NULL,
            memory_b_id TEXT NOT NULL,
            association_type TEXT NOT NULL CHECK(association_type IN (
                'cooccurrence', 'temporal_proximity', 'emotion_consistency',
                'semantic_similar', 'user_defined'
            )),
            weight REAL DEFAULT 0.5 CHECK(weight >= 0 AND weight <= 1.0),
            supporting_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_a_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY (memory_b_id) REFERENCES memories(id) ON DELETE CASCADE,
            UNIQUE(memory_a_id, memory_b_id, association_type)
        );

        -- 合并历史
        CREATE TABLE IF NOT EXISTS memory_merge_history (
            id TEXT PRIMARY KEY,
            primary_memory_id TEXT NOT NULL,
            merged_memory_ids TEXT NOT NULL,
            merge_type TEXT NOT NULL,
            merge_summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'system',
            FOREIGN KEY (primary_memory_id) REFERENCES memories(id)
        );

        -- 溯源表
        CREATE TABLE IF NOT EXISTS memory_provenance (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            origin TEXT NOT NULL,
            original_content TEXT,
            transformations TEXT,
            creation_context TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        -- ==========================================
        -- 高级增强副表 (Phase 2)
        -- ==========================================

        -- 向量嵌入表
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            memory_id TEXT PRIMARY KEY,
            vector_json TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        -- 记忆版本历史表
        CREATE TABLE IF NOT EXISTS memory_versions (
            version_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            content_snapshot TEXT NOT NULL,
            metadata_snapshot TEXT,
            change_type TEXT NOT NULL,
            change_reason TEXT,
            previous_version_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        -- 社交图谱: 人物实体表
        CREATE TABLE IF NOT EXISTS social_entities (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            name TEXT NOT NULL,
            entity_type TEXT CHECK(entity_type IN ('person', 'group', 'organization', 'pet')),
            description TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 社交图谱: 关系边表
        CREATE TABLE IF NOT EXISTS social_relationships (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL CHECK(relationship_type IN (
                'family', 'friend', 'colleague', 'mentor', 'partner',
                'acquaintance', 'rival', 'pet_owner'
            )),
            strength REAL DEFAULT 0.5 CHECK(strength >= 0.0 AND strength <= 1.0),
            previous_strength REAL,
            strength_change_count INTEGER DEFAULT 0,
            since_date TIMESTAMP,
            last_interacted_at TIMESTAMP,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_entity_id) REFERENCES social_entities(id) ON DELETE CASCADE,
            FOREIGN KEY (target_entity_id) REFERENCES social_entities(id) ON DELETE CASCADE,
            UNIQUE(source_entity_id, target_entity_id, relationship_type)
        );

        -- 社交图谱: 记忆-人物关联表
        CREATE TABLE IF NOT EXISTS memory_social_links (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            role_in_memory TEXT,
            importance REAL DEFAULT 0.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY (entity_id) REFERENCES social_entities(id) ON DELETE CASCADE
        );

        -- 敏感信息记录表
        CREATE TABLE IF NOT EXISTS sensitive_info_records (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            category TEXT NOT NULL,
            sensitivity_level TEXT NOT NULL,
            original_content TEXT,
            masked_content TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        -- 隐私日志
        CREATE TABLE IF NOT EXISTS privacy_logs (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 时间模式表
        CREATE TABLE IF NOT EXISTS time_patterns (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            pattern_type TEXT NOT NULL,
            description TEXT,
            memory_ids TEXT,
            confidence REAL,
            occurrences INTEGER,
            time_info TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 事件提醒表
        CREATE TABLE IF NOT EXISTS time_event_reminders (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            event_type TEXT NOT NULL,
            description TEXT,
            event_date TIMESTAMP NOT NULL,
            reminder_time TIMESTAMP,
            related_memories TEXT,
            importance REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 记忆反馈表
        CREATE TABLE IF NOT EXISTS memory_feedback (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            query TEXT NOT NULL,
            retrieved_ids TEXT NOT NULL,
            retrieval_precision REAL,
            response_quality REAL,
            user_satisfaction INTEGER CHECK(user_satisfaction >= 1 AND user_satisfaction <= 5),
            implicit_signals TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ==========================================
        -- 梦境报告表 (Sleep Consolidation)
        -- ==========================================
        CREATE TABLE IF NOT EXISTS dream_reports (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL DEFAULT 'yi_ling',
            session_id TEXT,
            report_type TEXT NOT NULL DEFAULT 'sleep_consolidation'
                CHECK(report_type IN ('sleep_consolidation', 'dream_analysis', 'memory_integration')),

            -- 报告统计数据
            total_processed INTEGER DEFAULT 0,
            merged_count INTEGER DEFAULT 0,
            archived_count INTEGER DEFAULT 0,

            -- 报告详细内容 (JSON)
            merged_details TEXT DEFAULT '[]',
            archived_ids TEXT DEFAULT '[]',

            -- 梦境质量指标
            consolidation_quality REAL DEFAULT 0.0,
            emotional_intensity REAL DEFAULT 0.0,
            memory_coherence_score REAL DEFAULT 0.0,

            -- 时间信息
            sleep_start_at TIMESTAMP,
            sleep_end_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            metadata TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_dream_reports_agent ON dream_reports(agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_dream_reports_type ON dream_reports(report_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_dream_reports_session ON dream_reports(session_id);

        -- ==========================================
        -- 情感衰减视图
        -- ==========================================
        CREATE VIEW IF NOT EXISTS current_emotions AS
        SELECT
            id, memory_id, emotion_type,
            intensity * EXP(-0.05 *
                JULIANDAY(CURRENT_TIMESTAMP) - JULIANDAY(created_at)) AS decayed_intensity,
            created_at
        FROM memory_emotions;
    """)

    conn.commit()

def create_all_indexes(conn: sqlite3.Connection):
    """按蓝图创建所有索引"""
    conn.executescript("""
        -- 主表索引
        CREATE INDEX IF NOT EXISTS idx_memories_agent_type ON memories(agent_id, type, is_archived);
        CREATE INDEX IF NOT EXISTS idx_memories_created_desc ON memories(agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_weight_hot ON memories(agent_id, weight DESC, access_count DESC)
            WHERE is_archived = 0;
        CREATE INDEX IF NOT EXISTS idx_memories_covering_hot ON memories(agent_id, weight DESC, type, category, created_at DESC)
            WHERE is_archived = 0;

        -- 温度与生命周期索引
        CREATE INDEX IF NOT EXISTS idx_memories_temp_active ON memories(agent_id, temperature DESC, lifecycle_stage) WHERE lifecycle_stage = 'active';
        CREATE INDEX IF NOT EXISTS idx_memories_important ON memories(agent_id, temperature DESC) WHERE is_important = 1;
        CREATE INDEX IF NOT EXISTS idx_memories_crystallized ON memories(agent_id, crystallized_at DESC) WHERE is_crystallized = 1;
        CREATE INDEX IF NOT EXISTS idx_memories_decay_scan ON memories(lifecycle_stage, last_accessed_at ASC) WHERE is_crystallized = 0;

        -- 会话索引
        CREATE INDEX IF NOT EXISTS idx_sessions_agent_status ON sessions(agent_id, status, last_activity_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON sessions(user_id, status) WHERE status = 'active';
        CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON session_messages(session_id, sequence_num ASC);
        CREATE INDEX IF NOT EXISTS idx_messages_session_recent ON session_messages(session_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_snapshots_lookup ON session_context_snapshots(session_id, query_hash, expires_at);

        -- 副表外键与查询索引
        CREATE INDEX IF NOT EXISTS idx_emotions_memory ON memory_emotions(memory_id);
        CREATE INDEX IF NOT EXISTS idx_emotions_type ON memory_emotions(memory_id, emotion_type, intensity DESC);
        CREATE INDEX IF NOT EXISTS idx_relations_source ON memory_relations(source_memory_id, relation_type, strength DESC);
        CREATE INDEX IF NOT EXISTS idx_relations_target ON memory_relations(target_memory_id);
        CREATE INDEX IF NOT EXISTS idx_keywords_lookup ON memory_keywords(keyword, relevance DESC, memory_id);
        CREATE INDEX IF NOT EXISTS idx_keywords_memory ON memory_keywords(memory_id);

        -- 智能增强索引
        CREATE INDEX IF NOT EXISTS idx_conflicts_status ON memory_conflicts(status, severity, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conflicts_memory ON memory_conflicts(memory_a_id, memory_b_id);
        CREATE INDEX IF NOT EXISTS idx_associations_memory_a ON memory_associations(memory_a_id, weight DESC);
        CREATE INDEX IF NOT EXISTS idx_associations_memory_b ON memory_associations(memory_b_id, weight DESC);
        CREATE INDEX IF NOT EXISTS idx_associations_type ON memory_associations(association_type, weight DESC);
        CREATE INDEX IF NOT EXISTS idx_merge_history_primary ON memory_merge_history(primary_memory_id);
        CREATE INDEX IF NOT EXISTS idx_provenance_memory ON memory_provenance(memory_id);

        -- 高级增强索引
        CREATE INDEX IF NOT EXISTS idx_embeddings_model ON memory_embeddings(model_name);
        CREATE INDEX IF NOT EXISTS idx_versions_memory ON memory_versions(memory_id, version_number DESC);
        CREATE INDEX IF NOT EXISTS idx_versions_created_at ON memory_versions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_versions_change_type ON memory_versions(change_type);
        CREATE INDEX IF NOT EXISTS idx_social_entities_agent ON social_entities(agent_id, entity_type);
        CREATE INDEX IF NOT EXISTS idx_social_relationships_agent ON social_relationships(agent_id, relationship_type, strength DESC);
        CREATE INDEX IF NOT EXISTS idx_social_relationships_source ON social_relationships(source_entity_id, strength DESC);
        CREATE INDEX IF NOT EXISTS idx_social_relationships_target ON social_relationships(target_entity_id);
        CREATE INDEX IF NOT EXISTS idx_social_memory_links ON memory_social_links(memory_id, entity_id);
        CREATE INDEX IF NOT EXISTS idx_social_memory_entity ON memory_social_links(entity_id, importance DESC);
        CREATE INDEX IF NOT EXISTS idx_sensitive_memory ON sensitive_info_records(memory_id);
        CREATE INDEX IF NOT EXISTS idx_privacy_logs_agent ON privacy_logs(agent_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_time_patterns_agent ON time_patterns(agent_id, pattern_type);
        CREATE INDEX IF NOT EXISTS idx_time_reminders_agent ON time_event_reminders(agent_id, event_date DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_agent_date ON memory_feedback(agent_id, timestamp DESC);
    """)

    conn.commit()

def init_db(db_path: str = None):
    """初始化数据库"""
    if db_path is None:
        db_path = get_db_path()

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # 如果数据库已存在，先备份
    if os.path.exists(db_path):
        backup_path = db_path + '.backup'
        import shutil
        shutil.copy2(db_path, backup_path)
        os.remove(db_path)
        print(f"  已备份旧数据库到: {backup_path}")

    print(f"  数据库路径: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        print("  [1/3] 创建表结构...")
        create_all_tables(conn)

        print("  [2/3] 创建索引...")
        create_all_indexes(conn)

        # 统计
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]

        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        indexes = [row[0] for row in cursor.fetchall()]

    print(f"  [3/3] 完成!")
    print(f"  表数量: {len(tables)}")
    print(f"  索引数量: {len(indexes)}")
    print()
    print("  表列表:")
    for t in tables:
        print(f"    - {t}")

    return db_path

if __name__ == "__main__":
    print("忆灵，正在初始化数据库...\n")
    print(f"{'='*50}")
    db_path = init_db()
    print(f"{'='*50}")
    print(f"\n数据库初始化完成!")
