"""
ToolExecutionLogger 单元测试

测试目标：
1. ToolExecutionEntry 数据类
2. ToolExecutionLogger 类的结构化日志记录
3. 日志查询和统计
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import json
import tempfile
import os
import time

# 导入被测模块
from neurova.tool_layers.tool_logger import ToolExecutionEntry, ToolExecutionLogger


class TestToolExecutionEntry:
    """ToolExecutionEntry 数据类测试"""

    def test_creation(self):
        """测试创建"""
        entry = ToolExecutionEntry(
            tool_name="file_read",
            params={"path": "/tmp/test.txt"},
            result={"content": "file content"},
            duration_ms=150.5,
            success=True,
            error=None,
            timestamp=time.time(),
            user_id="user1",
            session_id="session1"
        )
        assert entry.tool_name == "file_read"
        assert entry.params["path"] == "/tmp/test.txt"
        assert entry.result["content"] == "file content"
        assert entry.duration_ms == 150.5
        assert entry.success == True
        assert entry.error is None
        assert entry.user_id == "user1"
        assert entry.session_id == "session1"

    def test_defaults(self):
        """测试默认值"""
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={},
            result={},
            duration_ms=100.0,
            success=True
        )
        assert entry.error is None
        assert entry.user_id == ""
        assert entry.session_id == ""
        assert entry.metadata == {}

    def test_to_dict(self):
        """测试转换为字典"""
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={"key": "value"},
            result={"output": "data"},
            duration_ms=100.0,
            success=True,
            timestamp=1234567890.0
        )
        
        data = entry.to_dict()
        assert data["tool_name"] == "tool1"
        assert data["params"]["key"] == "value"
        assert data["result"]["output"] == "data"
        assert data["duration_ms"] == 100.0
        assert data["success"] == True
        assert data["timestamp"] == 1234567890.0

    def test_to_json(self):
        """测试转换为 JSON"""
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={"key": "value"},
            result={"output": "data"},
            duration_ms=100.0,
            success=True
        )
        
        json_str = entry.to_json()
        data = json.loads(json_str)
        
        assert data["tool_name"] == "tool1"
        assert data["params"]["key"] == "value"

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "tool_name": "tool1",
            "params": {"key": "value"},
            "result": {"output": "data"},
            "duration_ms": 100.0,
            "success": True,
            "timestamp": 1234567890.0,
            "user_id": "user1",
            "session_id": "session1"
        }
        
        entry = ToolExecutionEntry.from_dict(data)
        assert entry.tool_name == "tool1"
        assert entry.params["key"] == "value"
        assert entry.user_id == "user1"


class TestToolExecutionLogger:
    """ToolExecutionLogger 类测试"""

    def setup_method(self):
        """每个测试前重置"""
        # 使用临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "tool_execution.jsonl")
        self.logger = ToolExecutionLogger(log_file=self.log_file)

    def teardown_method(self):
        """每个测试后清理"""
        # 关闭日志器
        self.logger.close()
        
        # 清理临时文件
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_initialization(self):
        """测试初始化"""
        assert self.logger._log_file == self.log_file
        assert self.logger._buffer == []
        assert self.logger._buffer_size == 100
        assert self.logger._auto_flush == True

    def test_log_single_entry(self):
        """测试记录单个条目"""
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={"key": "value"},
            result={"output": "data"},
            duration_ms=100.0,
            success=True
        )
        
        self.logger.log(entry)
        
        # 验证缓冲区
        assert len(self.logger._buffer) == 1
        assert self.logger._buffer[0] == entry

    def test_log_multiple_entries(self):
        """测试记录多个条目"""
        for i in range(5):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i}",
                params={"index": i},
                result={"output": f"data{i}"},
                duration_ms=100.0 + i,
                success=True
            )
            self.logger.log(entry)
        
        assert len(self.logger._buffer) == 5

    def test_auto_flush(self):
        """测试自动刷新"""
        # 设置小缓冲区
        self.logger._buffer_size = 2
        
        # 记录3个条目（应该触发自动刷新）
        for i in range(3):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i}",
                params={},
                result={},
                duration_ms=100.0,
                success=True
            )
            self.logger.log(entry)
        
        # 验证缓冲区大小（应该只剩1个）
        assert len(self.logger._buffer) == 1
        
        # 验证文件已写入
        assert os.path.exists(self.log_file)
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 2  # 前两个已刷新

    def test_manual_flush(self):
        """测试手动刷新"""
        # 记录一些条目
        for i in range(3):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i}",
                params={},
                result={},
                duration_ms=100.0,
                success=True
            )
            self.logger.log(entry)
        
        # 手动刷新
        self.logger.flush()
        
        # 验证缓冲区已清空
        assert len(self.logger._buffer) == 0
        
        # 验证文件已写入
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 3

    def test_query_recent(self):
        """测试查询最近日志"""
        # 记录一些条目
        for i in range(10):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i}",
                params={"index": i},
                result={"output": f"data{i}"},
                duration_ms=100.0 + i,
                success=True,
                timestamp=time.time() - (10 - i)  # 按时间顺序
            )
            self.logger.log(entry)
        
        # 刷新到文件
        self.logger.flush()
        
        # 查询最近5条
        recent = self.logger.query_recent(limit=5)
        
        assert len(recent) == 5
        # 验证是最近的5条
        assert recent[0].params["index"] == 5
        assert recent[4].params["index"] == 9

    def test_query_by_tool(self):
        """测试按工具查询"""
        # 记录不同工具的条目
        tools = ["tool_a", "tool_b", "tool_a", "tool_c", "tool_a"]
        for i, tool in enumerate(tools):
            entry = ToolExecutionEntry(
                tool_name=tool,
                params={"index": i},
                result={},
                duration_ms=100.0,
                success=True
            )
            self.logger.log(entry)
        
        # 刷新到文件
        self.logger.flush()
        
        # 查询 tool_a 的条目
        tool_a_entries = self.logger.query_recent(tool_name="tool_a")
        
        assert len(tool_a_entries) == 3

    def test_query_by_time_range(self):
        """测试按时间范围查询"""
        # 记录不同时间的条目
        now = time.time()
        for i in range(5):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i}",
                params={},
                result={},
                duration_ms=100.0,
                success=True,
                timestamp=now - (5 - i) * 60  # 每分钟一个
            )
            self.logger.log(entry)
        
        # 刷新到文件
        self.logger.flush()
        
        # 查询最近3分钟的条目
        recent_entries = self.logger.query_recent(
            start_time=now - 3 * 60,
            end_time=now
        )
        
        assert len(recent_entries) == 3

    def test_get_stats(self):
        """测试获取统计信息"""
        # 记录一些条目
        for i in range(10):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i % 3}",  # 3个不同工具
                params={},
                result={},
                duration_ms=100.0 + i * 10,
                success=i % 2 == 0  # 一半成功，一半失败
            )
            self.logger.log(entry)
        
        # 刷新到文件
        self.logger.flush()
        
        # 获取统计信息
        stats = self.logger.get_stats()
        
        assert "total_executions" in stats
        assert "success_count" in stats
        assert "failure_count" in stats
        assert "avg_duration_ms" in stats
        assert "tool_counts" in stats
        
        assert stats["total_executions"] == 10
        assert stats["success_count"] == 5
        assert stats["failure_count"] == 5

    def test_context_manager(self):
        """测试上下文管理器"""
        with ToolExecutionLogger(log_file=self.log_file) as logger:
            entry = ToolExecutionEntry(
                tool_name="tool1",
                params={},
                result={},
                duration_ms=100.0,
                success=True
            )
            logger.log(entry)
        
        # 验证文件已写入
        assert os.path.exists(self.log_file)
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 1

    def test_close(self):
        """测试关闭"""
        # 记录一些条目
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={},
            result={},
            duration_ms=100.0,
            success=True
        )
        self.logger.log(entry)
        
        # 关闭
        self.logger.close()
        
        # 验证缓冲区已刷新
        assert len(self.logger._buffer) == 0
        
        # 验证文件已写入
        assert os.path.exists(self.log_file)

    def test_destructor(self):
        """测试析构函数"""
        # 创建日志器
        logger = ToolExecutionLogger(log_file=self.log_file)
        
        # 记录一些条目
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={},
            result={},
            duration_ms=100.0,
            success=True
        )
        logger.log(entry)
        
        # 删除日志器（触发析构）
        del logger
        
        # 验证文件已写入
        assert os.path.exists(self.log_file)
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 1

    def test_buffer_size_configuration(self):
        """测试缓冲区大小配置"""
        # 创建大缓冲区
        logger = ToolExecutionLogger(
            log_file=self.log_file,
            buffer_size=1000
        )
        
        assert logger._buffer_size == 1000
        
        # 创建小缓冲区
        logger2 = ToolExecutionLogger(
            log_file=self.log_file,
            buffer_size=10
        )
        
        assert logger2._buffer_size == 10

    def test_auto_flush_disabled(self):
        """测试禁用自动刷新"""
        # 创建禁用自动刷新的日志器
        logger = ToolExecutionLogger(
            log_file=self.log_file,
            auto_flush=False
        )
        
        # 记录超过缓冲区大小的条目
        for i in range(150):
            entry = ToolExecutionEntry(
                tool_name=f"tool{i}",
                params={},
                result={},
                duration_ms=100.0,
                success=True
            )
            logger.log(entry)
        
        # 验证缓冲区未自动刷新
        assert len(logger._buffer) == 150
        
        # 手动刷新
        logger.flush()
        
        # 验证文件已写入
        assert os.path.exists(self.log_file)
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 150

    def test_log_format(self):
        """测试日志格式"""
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={"key": "value"},
            result={"output": "data"},
            duration_ms=100.0,
            success=True,
            timestamp=1234567890.0
        )
        
        self.logger.log(entry)
        self.logger.flush()
        
        # 读取日志文件
        with open(self.log_file, 'r') as f:
            line = f.readline()
            data = json.loads(line)
            
            # 验证格式
            assert data["tool_name"] == "tool1"
            assert data["params"]["key"] == "value"
            assert data["result"]["output"] == "data"
            assert data["duration_ms"] == 100.0
            assert data["success"] == True
            assert data["timestamp"] == 1234567890.0

    def test_error_logging(self):
        """测试错误日志记录"""
        entry = ToolExecutionEntry(
            tool_name="tool1",
            params={},
            result={},
            duration_ms=100.0,
            success=False,
            error="Tool execution failed"
        )
        
        self.logger.log(entry)
        self.logger.flush()
        
        # 读取日志文件
        with open(self.log_file, 'r') as f:
            line = f.readline()
            data = json.loads(line)
            
            assert data["success"] == False
            assert data["error"] == "Tool execution failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])