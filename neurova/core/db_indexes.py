"""
数据库索引管理

添加缺失的索引以提高查询性能。
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# 需要添加索引的表和列
INDEXES_TO_ADD = [
    # 用户表
    ("users", "email", "idx_users_email"),
    ("users", "status", "idx_users_status"),
    ("users", "created_at", "idx_users_created_at"),
    
    # 登录日志表
    ("login_logs", "user_id", "idx_login_logs_user_id"),
    ("login_logs", "created_at", "idx_login_logs_created_at"),
    
    # 记忆表
    ("memory_emotions", "agent_id", "idx_memory_emotions_agent_id"),
    ("memory_emotions", "user_id", "idx_memory_emotions_user_id"),
    ("memory_emotions", "created_at", "idx_memory_emotions_created_at"),
    
    # 工作流表
    ("workflows", "agent_id", "idx_workflows_agent_id"),
    ("workflows", "status", "idx_workflows_status"),
    ("executions", "workflow_id", "idx_executions_workflow_id"),
    ("executions", "status", "idx_executions_status"),
]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """检查表是否存在"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    """检查索引是否存在"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,)
    )
    return cursor.fetchone() is not None


def add_indexes(db_path: str = "neurova_memory.db") -> dict:
    """
    添加缺失的索引
    
    Args:
        db_path: 数据库文件路径
        
    Returns:
        dict: 添加结果统计
    """
    if not Path(db_path).exists():
        logger.warning("数据库文件不存在: %s", db_path)
        return {"added": 0, "skipped": 0, "errors": 0}
    
    conn = sqlite3.connect(db_path)
    stats = {"added": 0, "skipped": 0, "errors": 0}
    
    try:
        for table, column, index_name in INDEXES_TO_ADD:
            # 检查表是否存在
            if not table_exists(conn, table):
                logger.debug("表不存在，跳过: %s", table)
                stats["skipped"] += 1
                continue
            
            # 检查索引是否已存在
            if index_exists(conn, index_name):
                logger.debug("索引已存在，跳过: %s", index_name)
                stats["skipped"] += 1
                continue
            
            # 创建索引
            try:
                sql = f"CREATE INDEX {index_name} ON {table} ({column})"
                conn.execute(sql)
                conn.commit()
                logger.info("创建索引: %s ON %s(%s)", index_name, table, column)
                stats["added"] += 1
            except sqlite3.Error as e:
                logger.error("创建索引失败: %s - %s", index_name, e)
                stats["errors"] += 1
        
        logger.info(
            "索引添加完成: 添加=%d, 跳过=%d, 错误=%d",
            stats["added"], stats["skipped"], stats["errors"]
        )
        
    finally:
        conn.close()
    
    return stats


def list_indexes(db_path: str = "neurova_memory.db") -> list:
    """
    列出数据库中的所有索引
    
    Args:
        db_path: 数据库文件路径
        
    Returns:
        list: 索引信息列表
    """
    if not Path(db_path).exists():
        return []
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, tbl_name, sql 
            FROM sqlite_master 
            WHERE type='index' 
            ORDER BY tbl_name, name
        """)
        return cursor.fetchall()
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else "neurova_memory.db"
    
    print(f"添加索引到: {db_path}")
    stats = add_indexes(db_path)
    print(f"结果: {stats}")
    
    print("\n当前索引:")
    indexes = list_indexes(db_path)
    for name, table, sql in indexes:
        print(f"  {name} ON {table}")
