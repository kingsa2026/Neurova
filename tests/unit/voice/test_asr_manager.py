"""
ASR Manager 单元测试

TDD 第一步：tracer bullet 测试 ASRManager 初始化与转写功能
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from neurova.asr.base import ASRBase
from neurova.asr.manager import ASRManager, ASRConfig


class MockASR(ASRBase):
    """Mock ASR 引擎用于测试"""
    
    def __init__(self, should_fail=False):
        super().__init__()
        self.should_fail = should_fail
        self._initialized = False
        
    async def initialize(self) -> bool:
        if self.should_fail:
            return False
        self._initialized = True
        return True
    
    async def transcribe(self, audio_bytes: bytes, language: str = "zh") -> dict:
        if not self._initialized:
            return {"text": "", "error": "未初始化"}
        
        # 模拟转写结果
        return {
            "text": "模拟识别结果",
            "language": language,
            "duration_sec": 1.5,
        }
    
    async def shutdown(self) -> None:
        self._initialized = False


class TestASRManager:
    """ASRManager 测试套件"""
    
    @pytest.fixture
    def mock_config(self):
        """测试配置"""
        return ASRConfig(
            engine="mock",
            fallback_enabled=True,
        )
    
    @pytest.fixture
    def manager(self, mock_config):
        """创建 ASRManager 实例"""
        return ASRManager(mock_config)
    
    @pytest.mark.asyncio
    async def test_initialization_success(self, manager):
        """测试 ASRManager 初始化成功"""
        # 红：测试失败 - ASRManager 不存在
        success = await manager.initialize()
        
        # 绿：实现后通过
        assert success is True
        assert manager.is_initialized is True
        assert manager.engine_name == "mock"
    
    @pytest.mark.asyncio
    async def test_transcribe_with_initialized_engine(self, manager):
        """测试已初始化引擎的转写功能"""
        # 红：测试失败
        await manager.initialize()
        
        # 准备测试音频数据（最小有效 WAV）
        audio_bytes = b'\x00' * 100  # 模拟音频数据
        
        result = await manager.transcribe(audio_bytes)
        
        # 验证转写结果
        assert "text" in result
        assert result["text"] == "模拟识别结果"
        assert "language" in result
        assert "duration_sec" in result
    
    @pytest.mark.asyncio
    async def test_transcribe_without_initialization(self, manager):
        """测试未初始化引擎的转写功能"""
        # 红：测试失败
        audio_bytes = b'\x00' * 100
        
        result = await manager.transcribe(audio_bytes)
        
        # 应返回错误
        assert "error" in result
        assert "未初始化" in result["error"]
    
    @pytest.mark.asyncio
    async def test_fallback_to_next_engine(self):
        """测试 fallback 机制"""
        # 红：测试失败
        config = ASRConfig(
            engine="auto",
            fallback_enabled=True,
        )
        manager = ASRManager(config)
        
        # Mock 第一个引擎失败，第二个成功
        with patch.object(manager, '_initialize_engine') as mock_init:
            # 第一次调用失败，第二次成功
            mock_init.side_effect = [False, True]
            
            success = await manager.initialize()
            
            # 应该尝试了两个引擎
            assert mock_init.call_count == 2
            assert success is True
    
    @pytest.mark.asyncio
    async def test_shutdown_releases_resources(self, manager):
        """测试关闭引擎释放资源"""
        # 红：测试失败
        await manager.initialize()
        assert manager.is_initialized is True
        
        await manager.shutdown()
        
        # 验证资源释放
        assert manager.is_initialized is False
        assert manager._engine is None
    
    @pytest.mark.asyncio
    async def test_stats_returns_engine_info(self, manager):
        """测试状态信息返回"""
        # 红：测试失败
        await manager.initialize()
        
        stats = manager.stats
        
        # 验证状态结构
        assert "engine" in stats
        assert "initialized" in stats
        assert stats["engine"] == "mock"
        assert stats["initialized"] is True


class TestASRConfig:
    """ASRConfig 配置测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        # 红：测试失败
        config = ASRConfig()
        
        # 验证默认值
        assert config.engine == "auto"
        assert config.fallback_enabled is True
        assert config.voice == "zh"
    
    def test_custom_config(self):
        """测试自定义配置"""
        # 红：测试失败
        config = ASRConfig(
            engine="funasr",
            fallback_enabled=False,
            voice="en",
        )
        
        # 验证自定义值
        assert config.engine == "funasr"
        assert config.fallback_enabled is False
        assert config.voice == "en"