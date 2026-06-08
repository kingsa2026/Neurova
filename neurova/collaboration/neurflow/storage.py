"""
Neurflow 存储层 — 垂直切片 2
SQLite 持久化：工作流定义、节点定义、执行实例、Agent 信息
"""
import sqlite3
import json
import threading
import time
from typing import Dict, List, Optional, Any
from pathlib import Path

from .models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeDefinition, SubBlockConfig, NodePort,
    ExecutionInstance, NodeExecutionResult, AgentInfo
)


class NeurflowStorage:
    """Neurflow SQLite 存储管理器"""
    
    def __init__(self, db_path: str = "neurflow.db"):
        """
        初始化存储管理器
        
        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = None
        self._init_db()
    
    def _init_db(self):
        """初始化数据库连接和表结构"""
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        
        # 创建表结构
        self._create_tables()
    
    def _create_tables(self):
        """创建数据库表结构"""
        with self._lock:
            # 工作流定义表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    version TEXT DEFAULT '1.0.0',
                    nodes_json TEXT DEFAULT '[]',
                    edges_json TEXT DEFAULT '[]',
                    variables_json TEXT DEFAULT '[]',
                    tags_json TEXT DEFAULT '[]',
                    category TEXT DEFAULT 'general',
                    author TEXT,
                    created_at REAL,
                    updated_at REAL,
                    status TEXT DEFAULT 'draft',
                    template INTEGER DEFAULT 0,
                    public INTEGER DEFAULT 0,
                    metadata_json TEXT DEFAULT '{}'
                )
            """)
            
            # 节点定义表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS node_definitions (
                    type TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    icon TEXT,
                    category TEXT,
                    description TEXT,
                    sub_blocks_json TEXT DEFAULT '[]',
                    inputs_json TEXT DEFAULT '[]',
                    outputs_json TEXT DEFAULT '[]',
                    source TEXT DEFAULT 'builtin',
                    source_id TEXT,
                    version TEXT DEFAULT '1.0.0',
                    tags_json TEXT DEFAULT '[]',
                    deprecated INTEGER DEFAULT 0
                )
            """)
            
            # 执行实例表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    status TEXT DEFAULT 'draft',
                    inputs_json TEXT DEFAULT '{}',
                    outputs_json TEXT,
                    node_results_json TEXT DEFAULT '{}',
                    variables_json TEXT DEFAULT '{}',
                    started_at REAL,
                    finished_at REAL,
                    duration REAL,
                    error TEXT,
                    agent_id TEXT,
                    user_id TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
                )
            """)
            
            # Agent 信息表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    config_json TEXT DEFAULT '{}',
                    flow_id TEXT,
                    created_at REAL,
                    archived_at REAL,
                    status TEXT DEFAULT 'active',
                    capabilities_json TEXT DEFAULT '[]',
                    metadata_json TEXT DEFAULT '{}'
                )
            """)
            
            # 创建索引
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_workflows_category ON workflows(category)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_workflows_author ON workflows(author)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_workflow ON executions(workflow_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_user ON executions(user_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_flow ON agents(flow_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)")
            
            self._conn.commit()
    
    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    # ==================== 工作流 CRUD ====================
    
    def save_workflow(self, workflow: WorkflowDefinition) -> bool:
        """
        保存工作流定义
        
        Args:
            workflow: 工作流定义对象
            
        Returns:
            bool: 保存是否成功
            
        Raises:
            ValueError: 当工作流数据无效时
        """
        if not workflow.id:
            raise ValueError("工作流 ID 不能为空")
        
        with self._lock:
            try:
                self._conn.execute("""
                    INSERT OR REPLACE INTO workflows 
                    (id, name, description, version, nodes_json, edges_json, 
                     variables_json, tags_json, category, author, created_at, 
                     updated_at, status, template, public, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    workflow.id,
                    workflow.name,
                    workflow.description,
                    workflow.version,
                    json.dumps([n.__dict__ for n in workflow.nodes], ensure_ascii=False),
                    json.dumps([e.__dict__ for e in workflow.edges], ensure_ascii=False),
                    json.dumps([v.__dict__ for v in workflow.variables], ensure_ascii=False),
                    json.dumps(workflow.tags, ensure_ascii=False),
                    workflow.category,
                    workflow.author,
                    workflow.created_at,
                    workflow.updated_at,
                    workflow.status.value,
                    1 if workflow.template else 0,
                    1 if workflow.public else 0,
                    json.dumps(workflow.metadata, ensure_ascii=False)
                ))
                self._conn.commit()
                return True
            except Exception as e:
                self._conn.rollback()
                raise e
    
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """
        获取工作流定义
        
        Args:
            workflow_id: 工作流 ID
            
        Returns:
            WorkflowDefinition 或 None
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            return self._row_to_workflow(row)
    
    def delete_workflow(self, workflow_id: str) -> bool:
        """
        删除工作流定义
        
        Args:
            workflow_id: 工作流 ID
            
        Returns:
            bool: 删除是否成功
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM workflows WHERE id = ?", (workflow_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0
    
    def list_workflows(
        self,
        category: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        author: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowDefinition]:
        """
        列出工作流定义
        
        Args:
            category: 按分类过滤
            status: 按状态过滤
            author: 按作者过滤
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            工作流定义列表
        """
        with self._lock:
            query = "SELECT * FROM workflows WHERE 1=1"
            params = []
            
            if category:
                query += " AND category = ?"
                params.append(category)
            
            if status:
                query += " AND status = ?"
                params.append(status.value)
            
            if author:
                query += " AND author = ?"
                params.append(author)
            
            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_workflow(row) for row in rows]
    
    def search_workflows(self, query: str) -> List[WorkflowDefinition]:
        """
        搜索工作流定义
        
        Args:
            query: 搜索关键词
            
        Returns:
            匹配的工作流定义列表
        """
        with self._lock:
            search_pattern = f"%{query}%"
            cursor = self._conn.execute("""
                SELECT * FROM workflows 
                WHERE name LIKE ? OR description LIKE ? OR tags_json LIKE ?
                ORDER BY updated_at DESC
            """, (search_pattern, search_pattern, search_pattern))
            
            rows = cursor.fetchall()
            return [self._row_to_workflow(row) for row in rows]
    
    def _row_to_workflow(self, row: sqlite3.Row) -> WorkflowDefinition:
        """将数据库行转换为 WorkflowDefinition"""
        nodes_data = json.loads(row["nodes_json"])
        edges_data = json.loads(row["edges_json"])
        variables_data = json.loads(row["variables_json"])
        
        nodes = [WorkflowNode(**n) for n in nodes_data]
        edges = [WorkflowEdge(**e) for e in edges_data]
        variables = [WorkflowVariable(**v) for v in variables_data]
        
        return WorkflowDefinition(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            version=row["version"] or "1.0.0",
            nodes=nodes,
            edges=edges,
            variables=variables,
            tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
            category=row["category"] or "general",
            author=row["author"] or "",
            created_at=row["created_at"] or 0.0,
            updated_at=row["updated_at"] or 0.0,
            status=WorkflowStatus(row["status"]) if row["status"] else WorkflowStatus.DRAFT,
            template=bool(row["template"]),
            public=bool(row["public"]),
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        )
    
    # ==================== 节点定义 CRUD ====================
    
    def save_node_definition(self, node_def: NodeDefinition) -> bool:
        """
        保存节点定义
        
        Args:
            node_def: 节点定义对象
            
        Returns:
            bool: 保存是否成功
        """
        if not node_def.type:
            raise ValueError("节点类型不能为空")
        
        with self._lock:
            try:
                self._conn.execute("""
                    INSERT OR REPLACE INTO node_definitions 
                    (type, label, icon, category, description, sub_blocks_json,
                     inputs_json, outputs_json, source, source_id, version,
                     tags_json, deprecated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    node_def.type,
                    node_def.label,
                    node_def.icon,
                    node_def.category,
                    node_def.description,
                    json.dumps([s.__dict__ for s in node_def.sub_blocks], ensure_ascii=False),
                    json.dumps([i.__dict__ for i in node_def.inputs], ensure_ascii=False),
                    json.dumps([o.__dict__ for o in node_def.outputs], ensure_ascii=False),
                    node_def.source,
                    node_def.source_id,
                    node_def.version,
                    json.dumps(node_def.tags, ensure_ascii=False),
                    1 if node_def.deprecated else 0
                ))
                self._conn.commit()
                return True
            except Exception as e:
                self._conn.rollback()
                raise e
    
    def get_node_definition(self, node_type: str) -> Optional[NodeDefinition]:
        """
        获取节点定义
        
        Args:
            node_type: 节点类型
            
        Returns:
            NodeDefinition 或 None
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM node_definitions WHERE type = ?", (node_type,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            return self._row_to_node_definition(row)
    
    def delete_node_definition(self, node_type: str) -> bool:
        """
        删除节点定义
        
        Args:
            node_type: 节点类型
            
        Returns:
            bool: 删除是否成功
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM node_definitions WHERE type = ?", (node_type,)
            )
            self._conn.commit()
            return cursor.rowcount > 0
    
    def list_node_definitions(
        self,
        category: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[NodeDefinition]:
        """
        列出节点定义
        
        Args:
            category: 按分类过滤
            source: 按来源过滤
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            节点定义列表
        """
        with self._lock:
            query = "SELECT * FROM node_definitions WHERE 1=1"
            params = []
            
            if category:
                query += " AND category = ?"
                params.append(category)
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            query += " ORDER BY type LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_node_definition(row) for row in rows]
    
    def search_node_definitions(self, query: str) -> List[NodeDefinition]:
        """
        搜索节点定义
        
        Args:
            query: 搜索关键词
            
        Returns:
            匹配的节点定义列表
        """
        with self._lock:
            search_pattern = f"%{query}%"
            cursor = self._conn.execute("""
                SELECT * FROM node_definitions 
                WHERE label LIKE ? OR description LIKE ? OR tags_json LIKE ?
                ORDER BY type
            """, (search_pattern, search_pattern, search_pattern))
            
            rows = cursor.fetchall()
            return [self._row_to_node_definition(row) for row in rows]
    
    def _row_to_node_definition(self, row: sqlite3.Row) -> NodeDefinition:
        """将数据库行转换为 NodeDefinition"""
        sub_blocks_data = json.loads(row["sub_blocks_json"])
        inputs_data = json.loads(row["inputs_json"])
        outputs_data = json.loads(row["outputs_json"])
        
        sub_blocks = [SubBlockConfig(**s) for s in sub_blocks_data]
        inputs = [NodePort(**i) for i in inputs_data]
        outputs = [NodePort(**o) for o in outputs_data]
        
        return NodeDefinition(
            type=row["type"],
            label=row["label"],
            icon=row["icon"] or "",
            category=row["category"] or "",
            description=row["description"] or "",
            sub_blocks=sub_blocks,
            inputs=inputs,
            outputs=outputs,
            source=row["source"] or "builtin",
            source_id=row["source_id"],
            version=row["version"] or "1.0.0",
            tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
            deprecated=bool(row["deprecated"])
        )
    
    # ==================== 执行实例 CRUD ====================
    
    def save_execution(self, execution: ExecutionInstance) -> bool:
        """
        保存执行实例
        
        Args:
            execution: 执行实例对象
            
        Returns:
            bool: 保存是否成功
        """
        if not execution.id:
            raise ValueError("执行实例 ID 不能为空")
        
        with self._lock:
            try:
                # 序列化 node_results
                node_results_json = json.dumps(
                    {k: v.__dict__ for k, v in execution.node_results.items()},
                    ensure_ascii=False
                )
                
                self._conn.execute("""
                    INSERT OR REPLACE INTO executions 
                    (id, workflow_id, status, inputs_json, outputs_json,
                     node_results_json, variables_json, started_at, finished_at,
                     duration, error, agent_id, user_id, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    execution.id,
                    execution.workflow_id,
                    execution.status.value,
                    json.dumps(execution.inputs, ensure_ascii=False),
                    json.dumps(execution.outputs, ensure_ascii=False) if execution.outputs else None,
                    node_results_json,
                    json.dumps(execution.variables, ensure_ascii=False),
                    execution.started_at,
                    execution.finished_at,
                    execution.duration,
                    execution.error,
                    execution.agent_id,
                    execution.user_id,
                    json.dumps(execution.metadata, ensure_ascii=False)
                ))
                self._conn.commit()
                return True
            except Exception as e:
                self._conn.rollback()
                raise e
    
    def get_execution(self, execution_id: str) -> Optional[ExecutionInstance]:
        """
        获取执行实例
        
        Args:
            execution_id: 执行实例 ID
            
        Returns:
            ExecutionInstance 或 None
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM executions WHERE id = ?", (execution_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            return self._row_to_execution(row)
    
    def list_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[WorkflowStatus] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ExecutionInstance]:
        """
        列出执行实例
        
        Args:
            workflow_id: 按工作流过滤
            status: 按状态过滤
            user_id: 按用户过滤
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            执行实例列表
        """
        with self._lock:
            query = "SELECT * FROM executions WHERE 1=1"
            params = []
            
            if workflow_id:
                query += " AND workflow_id = ?"
                params.append(workflow_id)
            
            if status:
                query += " AND status = ?"
                params.append(status.value)
            
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            
            query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_execution(row) for row in rows]
    
    def _row_to_execution(self, row: sqlite3.Row) -> ExecutionInstance:
        """将数据库行转换为 ExecutionInstance"""
        inputs = json.loads(row["inputs_json"]) if row["inputs_json"] else {}
        outputs = json.loads(row["outputs_json"]) if row["outputs_json"] else None
        variables = json.loads(row["variables_json"]) if row["variables_json"] else {}
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        
        # 反序列化 node_results
        node_results_data = json.loads(row["node_results_json"]) if row["node_results_json"] else {}
        node_results = {}
        for node_id, result_data in node_results_data.items():
            node_results[node_id] = NodeExecutionResult(**result_data)
        
        return ExecutionInstance(
            id=row["id"],
            workflow_id=row["workflow_id"],
            status=WorkflowStatus(row["status"]) if row["status"] else WorkflowStatus.DRAFT,
            inputs=inputs,
            outputs=outputs,
            node_results=node_results,
            variables=variables,
            started_at=row["started_at"] or 0.0,
            finished_at=row["finished_at"],
            duration=row["duration"],
            error=row["error"],
            agent_id=row["agent_id"],
            user_id=row["user_id"],
            metadata=metadata
        )
    
    # ==================== Agent CRUD ====================
    
    def save_agent(self, agent: AgentInfo) -> bool:
        """
        保存 Agent 信息
        
        Args:
            agent: Agent 信息对象
            
        Returns:
            bool: 保存是否成功
        """
        if not agent.agent_id:
            raise ValueError("Agent ID 不能为空")
        
        with self._lock:
            try:
                self._conn.execute("""
                    INSERT OR REPLACE INTO agents 
                    (agent_id, name, role, config_json, flow_id, created_at,
                     archived_at, status, capabilities_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    agent.agent_id,
                    agent.name,
                    agent.role,
                    json.dumps(agent.config, ensure_ascii=False),
                    agent.flow_id,
                    agent.created_at,
                    agent.archived_at,
                    agent.status,
                    json.dumps(agent.capabilities, ensure_ascii=False),
                    json.dumps(agent.metadata, ensure_ascii=False)
                ))
                self._conn.commit()
                return True
            except Exception as e:
                self._conn.rollback()
                raise e
    
    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """
        获取 Agent 信息
        
        Args:
            agent_id: Agent ID
            
        Returns:
            AgentInfo 或 None
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            return self._row_to_agent(row)
    
    def list_agents(
        self,
        flow_id: Optional[str] = None,
        status: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[AgentInfo]:
        """
        列出 Agent 信息
        
        Args:
            flow_id: 按工作流过滤
            status: 按状态过滤
            include_archived: 是否包含已归档的 Agent
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            Agent 信息列表
        """
        with self._lock:
            query = "SELECT * FROM agents WHERE 1=1"
            params = []
            
            if flow_id:
                query += " AND flow_id = ?"
                params.append(flow_id)
            
            if status:
                query += " AND status = ?"
                params.append(status)
            elif not include_archived:
                query += " AND status != 'archived'"
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_agent(row) for row in rows]
    
    def delete_agent(self, agent_id: str) -> bool:
        """
        删除 Agent 信息
        
        Args:
            agent_id: Agent ID
            
        Returns:
            bool: 删除是否成功
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM agents WHERE agent_id = ?", (agent_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0
    
    def _row_to_agent(self, row: sqlite3.Row) -> AgentInfo:
        """将数据库行转换为 AgentInfo"""
        config = json.loads(row["config_json"]) if row["config_json"] else {}
        capabilities = json.loads(row["capabilities_json"]) if row["capabilities_json"] else []
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        
        return AgentInfo(
            agent_id=row["agent_id"],
            name=row["name"],
            role=row["role"],
            config=config,
            flow_id=row["flow_id"],
            created_at=row["created_at"] or 0.0,
            archived_at=row["archived_at"],
            status=row["status"] or "active",
            capabilities=capabilities,
            metadata=metadata
        )
    
    # ==================== 统计和清理 ====================
    
    def get_statistics(self) -> Dict[str, int]:
        """
        获取存储统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            stats = {}
            
            # 工作流数量
            cursor = self._conn.execute("SELECT COUNT(*) FROM workflows")
            stats["workflows"] = cursor.fetchone()[0]
            
            # 节点定义数量
            cursor = self._conn.execute("SELECT COUNT(*) FROM node_definitions")
            stats["node_definitions"] = cursor.fetchone()[0]
            
            # 执行实例数量
            cursor = self._conn.execute("SELECT COUNT(*) FROM executions")
            stats["executions"] = cursor.fetchone()[0]
            
            # Agent 数量
            cursor = self._conn.execute("SELECT COUNT(*) FROM agents")
            stats["agents"] = cursor.fetchone()[0]
            
            return stats
    
    def cleanup_old_executions(self, days: int = 30) -> int:
        """
        清理旧的执行记录
        
        Args:
            days: 保留天数
            
        Returns:
            删除的记录数
        """
        with self._lock:
            cutoff_time = time.time() - (days * 86400)
            cursor = self._conn.execute(
                "DELETE FROM executions WHERE started_at < ?", (cutoff_time,)
            )
            self._conn.commit()
            return cursor.rowcount


# 便捷导出
__all__ = ["NeurflowStorage"]