"""
删除状态维护器测试

TDD: 先写测试，再实现
"""

import pytest
from neurova.cognitive_layers.memory_layer.deletion_state_manager import DeletionStateManager


class TestDeletionStateManager:
    """DeletionStateManager 测试"""
    
    def test_init(self):
        """测试初始化"""
        manager = DeletionStateManager()
        assert manager is not None
    
    def test_mark_as_deleted(self):
        """测试标记为已删除"""
        manager = DeletionStateManager()
        
        manager.mark_as_deleted(
            entity_id="entity_001",
            entity_type="memory",
            reason="用户删除",
        )
        
        status = manager.get_deletion_status("entity_001")
        assert status["is_deleted"] is True
        assert status["reason"] == "用户删除"
    
    def test_get_deletion_status_not_deleted(self):
        """测试获取未删除实体的状态"""
        manager = DeletionStateManager()
        
        status = manager.get_deletion_status("entity_002")
        assert status["is_deleted"] is False
    
    def test_restore_entity(self):
        """测试恢复实体"""
        manager = DeletionStateManager()
        
        manager.mark_as_deleted("entity_003", "memory", "测试删除")
        manager.restore_entity("entity_003")
        
        status = manager.get_deletion_status("entity_003")
        assert status["is_deleted"] is False
    
    def test_get_deleted_entities(self):
        """测试获取已删除实体列表"""
        manager = DeletionStateManager()
        
        manager.mark_as_deleted("entity_001", "memory", "删除1")
        manager.mark_as_deleted("entity_002", "memory", "删除2")
        manager.mark_as_deleted("entity_003", "skill", "删除3")
        
        # 获取所有已删除实体
        all_deleted = manager.get_deleted_entities()
        assert len(all_deleted) == 3
        
        # 按类型过滤
        memory_deleted = manager.get_deleted_entities(entity_type="memory")
        assert len(memory_deleted) == 2
    
    def test_permanently_delete(self):
        """测试永久删除"""
        manager = DeletionStateManager()
        
        manager.mark_as_deleted("entity_004", "memory", "临时删除")
        manager.permanently_delete("entity_004")
        
        status = manager.get_deletion_status("entity_004")
        assert status["is_deleted"] is True
        assert status["is_permanent"] is True
    
    def test_cleanup_old_deleted(self):
        """测试清理旧的已删除实体"""
        manager = DeletionStateManager()
        
        # 添加一些已删除实体
        manager.mark_as_deleted("entity_005", "memory", "删除1")
        manager.mark_as_deleted("entity_006", "memory", "删除2")
        
        # 清理30天前的已删除实体
        cleaned = manager.cleanup_old_deleted(days=30)
        # 由于刚添加，不会被清理
        assert cleaned == 0
