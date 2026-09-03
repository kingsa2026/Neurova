"""简单测试 CrystallizedExperienceManager"""
import asyncio
from neurova.agent.crystallized_experience_manager import (
    CrystallizedExperienceManager,
    CrystallizedExperience,
    RetrievalResult,
    RetrievalStatus,
    HealthStatus,
)

class MockCrystallizer:
    def __init__(self):
        self.retrieve_count = 0
        self.results = []
    
    def retrieve(self, query: str, limit: int = 5):
        self.retrieve_count += 1
        return self.results[:limit]

def test_basic():
    """测试基本功能"""
    print("测试基本功能...")
    
    # 创建模拟结晶器
    crystallizer = MockCrystallizer()
    crystallizer.results = [
        {"id": "1", "content": "测试经验", "method": "tool_a", "confidence": 0.9, "score": 80.0}
    ]
    
    # 创建管理器
    manager = CrystallizedExperienceManager(crystallizer=crystallizer)
    
    # 测试检索
    async def retrieve():
        return await manager.retrieve("测试查询", limit=5, use_cache=False)
    
    result = asyncio.run(retrieve())
    
    assert result.status == RetrievalStatus.SUCCESS
    assert len(result.experiences) == 1
    assert result.experiences[0].content == "测试经验"
    assert crystallizer.retrieve_count == 1
    
    print("✅ 基本功能测试通过")

def test_health():
    """测试健康状态"""
    print("测试健康状态...")
    
    manager = CrystallizedExperienceManager()
    
    # 初始状态应该是健康
    assert manager.get_health() == HealthStatus.HEALTHY
    
    # 模拟连续失败
    manager._metrics.consecutive_failures = 2
    manager._update_health_status()
    assert manager.get_health() == HealthStatus.DEGRADED
    
    manager._metrics.consecutive_failures = 5
    manager._update_health_status()
    assert manager.get_health() == HealthStatus.UNHEALTHY
    
    print("✅ 健康状态测试通过")

def test_cache():
    """测试缓存功能"""
    print("测试缓存功能...")
    
    crystallizer = MockCrystallizer()
    crystallizer.results = [
        {"id": "1", "content": "缓存测试", "method": "tool_a", "confidence": 0.9, "score": 80.0}
    ]
    
    manager = CrystallizedExperienceManager(crystallizer=crystallizer)
    
    async def test():
        # 第一次检索
        result1 = await manager.retrieve("缓存查询", limit=5, use_cache=True)
        assert result1.status == RetrievalStatus.SUCCESS
        
        # 第二次检索（应该命中缓存）
        result2 = await manager.retrieve("缓存查询", limit=5, use_cache=True)
        assert result2.status == RetrievalStatus.SUCCESS
        
        # 验证只调用了一次结晶器
        assert crystallizer.retrieve_count == 1
        
        # 清空缓存
        count = manager.clear_cache()
        assert count == 1
    
    asyncio.run(test())
    print("✅ 缓存功能测试通过")

def test_statistics():
    """测试统计功能"""
    print("测试统计功能...")
    
    crystallizer = MockCrystallizer()
    crystallizer.results = [
        {"id": "1", "content": "统计测试", "method": "tool_a", "confidence": 0.9, "score": 80.0}
    ]
    
    manager = CrystallizedExperienceManager(crystallizer=crystallizer)
    
    async def test():
        # 执行几次检索
        await manager.retrieve("查询1", limit=5, use_cache=False)
        await manager.retrieve("查询2", limit=5, use_cache=False)
        
        # 获取统计
        stats = manager.get_statistics()
        assert stats["total_attempts"] == 2
        assert stats["successful_attempts"] == 2
        assert stats["success_rate"] == 1.0
    
    asyncio.run(test())
    print("✅ 统计功能测试通过")

if __name__ == "__main__":
    print("开始测试 CrystallizedExperienceManager...")
    print("=" * 60)
    
    test_basic()
    test_health()
    test_cache()
    test_statistics()
    
    print("=" * 60)
    print("✅ 所有测试通过")