"""
测试 skills 模块的实现
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSearchResult:
    """测试 SearchResult 数据类（v2 契约: skill_name/market 主字段，name/source 别名）"""

    def test_search_result_creation(self):
        """测试 SearchResult 创建"""
        from neurova.skills.market_searcher import SearchResult

        result = SearchResult(
            skill_name="test-skill",
            market="github",
            description="A test skill",
            url="https://github.com/test/skill",
            version="1.0.0",
            author="test",
            tags=["test", "skill"]
        )

        # v2 主字段
        assert result.skill_name == "test-skill"
        assert result.market == "github"
        # 兼容别名 property
        assert result.name == "test-skill"
        assert result.source == "github"
        assert result.description == "A test skill"
        assert result.url == "https://github.com/test/skill"
        assert result.version == "1.0.0"
        assert result.author == "test"
        assert result.tags == ["test", "skill"]

    def test_search_result_to_dict(self):
        """测试 SearchResult 转字典"""
        from neurova.skills.market_searcher import SearchResult

        result = SearchResult(
            skill_name="test-skill",
            market="github",
            description="A test skill"
        )

        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["skill_name"] == "test-skill"
        assert data["market"] == "github"
        assert data["name"] == "test-skill"
        assert data["source"] == "github"

    def test_search_result_from_dict(self):
        """测试从字典创建 SearchResult（新旧键均兼容）"""
        from neurova.skills.market_searcher import SearchResult

        result = SearchResult.from_dict({
            "skill_name": "test-skill",
            "market": "github",
            "description": "A test skill"
        })
        assert result.skill_name == "test-skill"
        assert result.market == "github"

        legacy = SearchResult.from_dict({
            "name": "legacy-skill",
            "source": "clawhub",
            "description": "Legacy"
        })
        assert legacy.skill_name == "legacy-skill"
        assert legacy.market == "clawhub"


class TestSkillMarketSearcher:
    """测试 SkillMarketSearcher 类"""
    
    def test_searcher_initialization(self):
        """测试 SkillMarketSearcher 初始化"""
        from neurova.skills.market_searcher import SkillMarketSearcher
        
        searcher = SkillMarketSearcher()
        assert searcher is not None
        assert hasattr(searcher, 'search_all_markets')
        assert hasattr(searcher, 'search_market')
    
    def test_list_markets(self):
        """测试列出支持的市场"""
        from neurova.skills.market_searcher import SkillMarketSearcher
        
        searcher = SkillMarketSearcher()
        markets = searcher.list_markets()
        
        assert isinstance(markets, list)
        assert len(markets) > 0
        assert "github" in markets
    
    def test_search_all_markets(self):
        """测试搜索所有市场"""
        from neurova.skills.market_searcher import SkillMarketSearcher

        searcher = SkillMarketSearcher()

        # v2: 搜索委托 registry 适配器，mock 适配器的 sync search
        with patch.object(searcher.registry.get_adapter("github"), "search", return_value=[]):
            results = searcher.search_all_markets("test query")

            assert isinstance(results, list)

    def test_search_market(self):
        """测试搜索单个市场"""
        from neurova.skills.market_searcher import SkillMarketSearcher

        searcher = SkillMarketSearcher()

        # v2: mock 适配器的 sync search
        with patch.object(searcher.registry.get_adapter("github"), "search", return_value=[]):
            results = searcher.search_market("github", "test query")

            assert isinstance(results, list)
    
    def test_search_nonexistent_market(self):
        """测试搜索不存在的市场"""
        from neurova.skills.market_searcher import SkillMarketSearcher
        
        searcher = SkillMarketSearcher()
        
        with pytest.raises(ValueError):
            searcher.search_market("nonexistent", "test query")
    
    def test_cache_mechanism(self):
        """测试缓存机制"""
        from neurova.skills.market_searcher import SkillMarketSearcher

        searcher = SkillMarketSearcher()

        # 添加到缓存
        from neurova.skills.market_searcher import SearchResult
        result = SearchResult(skill_name="test", market="github", description="test")
        searcher._add_to_cache("test_key", [result])

        # 从缓存获取
        cached = searcher._get_from_cache("test_key")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].skill_name == "test"

    def test_clear_cache(self):
        """测试清除缓存"""
        from neurova.skills.market_searcher import SkillMarketSearcher

        searcher = SkillMarketSearcher()

        # 添加到缓存
        from neurova.skills.market_searcher import SearchResult
        result = SearchResult(skill_name="test", market="github", description="test")
        searcher._add_to_cache("test_key", [result])
        
        # 清除缓存
        searcher.clear_cache()
        
        # 缓存应该为空
        cached = searcher._get_from_cache("test_key")
        assert cached is None


class TestSkillMarketAdapter:
    """测试 SkillMarketAdapter 基类"""
    
    def test_adapter_initialization(self):
        """测试适配器初始化"""
        from neurova.skills.market_adapters import SkillMarketAdapter
        
        # SkillMarketAdapter 是基类，应该有基本接口
        assert hasattr(SkillMarketAdapter, '__init__')
    
    def test_github_adapter(self):
        """测试 GitHub 适配器"""
        from neurova.skills.market_adapters import GitHubMarketAdapter
        
        adapter = GitHubMarketAdapter()
        assert adapter is not None
        assert hasattr(adapter, 'search')
        assert hasattr(adapter, 'install')
    
    def test_lobehub_adapter(self):
        """测试 LobeHub 适配器"""
        from neurova.skills.market_adapters import LobeHubMarketAdapter
        
        adapter = LobeHubMarketAdapter()
        assert adapter is not None
        assert hasattr(adapter, 'search')
        assert hasattr(adapter, 'install')


class TestSkillMarketRegistry:
    """测试 SkillMarketRegistry 类"""
    
    def test_registry_initialization(self):
        """测试注册表初始化"""
        from neurova.skills.market_adapters import SkillMarketRegistry
        
        registry = SkillMarketRegistry()
        assert registry is not None
    
    def test_register_adapter(self):
        """测试注册适配器"""
        from neurova.skills.market_adapters import SkillMarketRegistry, GitHubMarketAdapter
        
        registry = SkillMarketRegistry()
        adapter = GitHubMarketAdapter()
        
        registry.register_adapter("github", adapter)
        assert registry.get_adapter("github") is adapter
    
    def test_get_adapter(self):
        """测试获取适配器"""
        from neurova.skills.market_adapters import SkillMarketRegistry, GitHubMarketAdapter
        
        registry = SkillMarketRegistry()
        adapter = GitHubMarketAdapter()
        
        registry.register_adapter("github", adapter)
        retrieved = registry.get_adapter("github")
        assert retrieved is adapter
    
    def test_get_nonexistent_adapter(self):
        """测试获取不存在的适配器"""
        from neurova.skills.market_adapters import SkillMarketRegistry
        
        registry = SkillMarketRegistry()
        
        with pytest.raises(KeyError):
            registry.get_adapter("nonexistent")
    
    def test_parse_url(self):
        """测试解析 URL"""
        from neurova.skills.market_adapters import SkillMarketRegistry
        
        registry = SkillMarketRegistry()
        
        # 测试 GitHub URL
        result = registry.parse_url("https://github.com/user/repo")
        assert result is not None
        assert result["market"] == "github"
    
    def test_list_markets(self):
        """测试列出已注册的市场"""
        from neurova.skills.market_adapters import SkillMarketRegistry, GitHubMarketAdapter
        
        registry = SkillMarketRegistry()
        adapter = GitHubMarketAdapter()
        
        registry.register_adapter("github", adapter)
        markets = registry.list_markets()
        
        assert isinstance(markets, list)
        assert "github" in markets


class TestSecurityLevel:
    """测试 SecurityLevel 枚举"""
    
    def test_security_levels(self):
        """测试安全级别枚举"""
        from neurova.skills.security_scanner import SecurityLevel
        
        assert SecurityLevel.SAFE.value == "safe"
        assert SecurityLevel.WARNING.value == "warning"
        assert SecurityLevel.DANGEROUS.value == "dangerous"
        assert SecurityLevel.CRITICAL.value == "critical"


class TestSecurityIssue:
    """测试 SecurityIssue 数据类"""
    
    def test_security_issue_creation(self):
        """测试 SecurityIssue 创建"""
        from neurova.skills.security_scanner import SecurityIssue, SecurityLevel
        
        issue = SecurityIssue(
            level=SecurityLevel.WARNING,
            description="Test warning",
            file_path="test.py",
            line_number=10,
            code_snippet="os.system('test')"
        )
        
        assert issue.level == SecurityLevel.WARNING
        assert issue.description == "Test warning"
        assert issue.file_path == "test.py"
        assert issue.line_number == 10


class TestSecurityReport:
    """测试 SecurityReport 数据类"""
    
    def test_security_report_creation(self):
        """测试 SecurityReport 创建"""
        from neurova.skills.security_scanner import SecurityReport, SecurityLevel, SecurityIssue
        
        issues = [
            SecurityIssue(
                level=SecurityLevel.WARNING,
                description="Test warning",
                file_path="test.py",
                line_number=10
            )
        ]
        
        report = SecurityReport(
            skill_name="test-skill",
            issues=issues,
            overall_level=SecurityLevel.WARNING,
            scan_time=1234567890.0
        )
        
        assert report.skill_name == "test-skill"
        assert len(report.issues) == 1
        assert report.overall_level == SecurityLevel.WARNING
    
    def test_has_critical_issues(self):
        """测试是否有严重问题"""
        from neurova.skills.security_scanner import SecurityReport, SecurityLevel, SecurityIssue
        
        issues = [
            SecurityIssue(
                level=SecurityLevel.CRITICAL,
                description="Critical issue",
                file_path="test.py",
                line_number=10
            )
        ]
        
        report = SecurityReport(
            skill_name="test-skill",
            issues=issues,
            overall_level=SecurityLevel.CRITICAL,
            scan_time=1234567890.0
        )
        
        assert report.has_critical_issues() is True


class TestSkillScanner:
    """测试 SkillScanner 类"""
    
    def test_scanner_initialization(self):
        """测试 SkillScanner 初始化"""
        from neurova.skills.security_scanner import SkillScanner
        
        scanner = SkillScanner()
        assert scanner is not None
        assert hasattr(scanner, 'scan')
    
    def test_scan_safe_code(self):
        """测试扫描安全代码"""
        from neurova.skills.security_scanner import SkillScanner, SecurityLevel
        
        scanner = SkillScanner()
        
        # 创建临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("print('Hello, World!')")
            temp_path = f.name
        
        try:
            report = scanner.scan_file(temp_path)
            assert report.overall_level == SecurityLevel.SAFE
        finally:
            os.unlink(temp_path)
    
    def test_scan_dangerous_code(self):
        """测试扫描危险代码"""
        from neurova.skills.security_scanner import SkillScanner, SecurityLevel
        
        scanner = SkillScanner()
        
        # 创建包含危险代码的临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("import os\nos.system('rm -rf /')")
            temp_path = f.name
        
        try:
            report = scanner.scan_file(temp_path)
            assert report.overall_level in [SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL]
            assert len(report.issues) > 0
        finally:
            os.unlink(temp_path)


class TestSkillSandbox:
    """测试 SkillSandbox 类"""
    
    def test_sandbox_initialization(self):
        """测试 SkillSandbox 初始化"""
        from neurova.skills.security_scanner import SkillSandbox
        
        sandbox = SkillSandbox()
        assert sandbox is not None
        assert hasattr(sandbox, 'execute')
    
    def test_execute_safe_code(self):
        """测试执行安全代码"""
        from neurova.skills.security_scanner import SkillSandbox
        
        sandbox = SkillSandbox()
        
        # 测试执行简单代码
        result = sandbox.execute("print('Hello')")
        assert result.success is True


class TestSecurityManager:
    """测试 SecurityManager 类"""
    
    def test_manager_initialization(self):
        """测试 SecurityManager 初始化"""
        from neurova.skills.security_scanner import SecurityManager
        
        manager = SecurityManager()
        assert manager is not None
        assert hasattr(manager, 'scan_skill')
        assert hasattr(manager, 'execute_skill')
    
    def test_scan_skill(self):
        """测试扫描技能"""
        from neurova.skills.security_scanner import SecurityManager
        
        manager = SecurityManager()
        
        # Mock Skill 对象
        mock_skill = MagicMock()
        mock_skill.name = "test-skill"
        mock_skill.path = "/path/to/skill"
        
        with patch.object(manager.scanner, 'scan', return_value=MagicMock()):
            result = manager.scan_skill(mock_skill)
            assert result is not None


class TestSubTask:
    """测试 SubTask 数据类"""
    
    def test_subtask_creation(self):
        """测试 SubTask 创建"""
        from neurova.skills.task_decomposer import SubTask
        
        subtask = SubTask(
            id="task-1",
            description="Test task",
            task_type="analysis",
            required_skills=["skill1", "skill2"],
            dependencies=[]
        )
        
        assert subtask.id == "task-1"
        assert subtask.description == "Test task"
        assert subtask.task_type == "analysis"
        assert subtask.required_skills == ["skill1", "skill2"]
        assert subtask.dependencies == []


class TestTaskDecompositionResult:
    """测试 TaskDecompositionResult 数据类"""
    
    def test_decomposition_result_creation(self):
        """测试 TaskDecompositionResult 创建"""
        from neurova.skills.task_decomposer import TaskDecompositionResult, SubTask
        
        subtasks = [
            SubTask(id="task-1", description="Task 1", task_type="analysis"),
            SubTask(id="task-2", description="Task 2", task_type="execution", dependencies=["task-1"])
        ]
        
        result = TaskDecompositionResult(
            original_request="Test request",
            subtasks=subtasks,
            required_skills=["skill1", "skill2"],
            decomposition_strategy="llm"
        )
        
        assert result.original_request == "Test request"
        assert len(result.subtasks) == 2
        assert result.required_skills == ["skill1", "skill2"]
        assert result.decomposition_strategy == "llm"


class TestTaskDecomposer:
    """测试 TaskDecomposer 类"""
    
    def test_decomposer_initialization(self):
        """测试 TaskDecomposer 初始化"""
        from neurova.skills.task_decomposer import TaskDecomposer
        
        decomposer = TaskDecomposer()
        assert decomposer is not None
        assert hasattr(decomposer, 'decompose')
        assert hasattr(decomposer, 'analyze_skill_needs')
    
    def test_decompose_simple_request(self):
        """测试分解简单请求"""
        from neurova.skills.task_decomposer import TaskDecomposer
        
        decomposer = TaskDecomposer()
        
        # Mock LLM 调用
        with patch.object(decomposer, '_decompose_with_llm', return_value=None):
            with patch.object(decomposer, '_decompose_with_rules') as mock_rules:
                mock_rules.return_value = MagicMock(subtasks=[MagicMock()])
                
                result = decomposer.decompose("Create a web application")
                
                assert result is not None
                assert hasattr(result, 'subtasks')
    
    def test_analyze_skill_needs(self):
        """测试分析技能需求"""
        from neurova.skills.task_decomposer import TaskDecomposer
        
        decomposer = TaskDecomposer()
        
        # Mock decompose 方法
        with patch.object(decomposer, 'decompose') as mock_decompose:
            mock_decompose.return_value = MagicMock(
                required_skills=["web-development", "database"]
            )
            
            skills = decomposer.analyze_skill_needs("Build a REST API")
            
            assert isinstance(skills, list)
            assert len(skills) > 0


class TestSkillAcquisitionResult:
    """测试 SkillAcquisitionResult 数据类"""
    
    def test_acquisition_result_creation(self):
        """测试 SkillAcquisitionResult 创建"""
        from neurova.skills.skill_need_analyzer import SkillAcquisitionResult
        
        result = SkillAcquisitionResult(
            skill_name="test-skill",
            success=True,
            source="github",
            version="1.0.0",
            message="Successfully acquired"
        )
        
        assert result.skill_name == "test-skill"
        assert result.success is True
        assert result.source == "github"
        assert result.version == "1.0.0"


class TestSkillNeedAnalyzer:
    """测试 SkillNeedAnalyzer 类"""
    
    def test_analyzer_initialization(self):
        """测试 SkillNeedAnalyzer 初始化"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer
        
        analyzer = SkillNeedAnalyzer()
        assert analyzer is not None
        assert hasattr(analyzer, 'analyze_and_acquire')
        assert hasattr(analyzer, 'suggest_skills')
    
    def test_analyze_and_acquire(self):
        """测试分析并获取技能（v2: 返回 dict，results 为 SkillAcquisitionResult 列表）"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer

        analyzer = SkillNeedAnalyzer(auto_install=False)

        results = analyzer.analyze_and_acquire("Build a web app")

        assert isinstance(results, dict)
        assert "required_skills" in results
        assert "missing_skills" in results
        assert "results" in results
    
    def test_suggest_skills(self):
        """测试建议技能"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer
        
        analyzer = SkillNeedAnalyzer()
        
        # Mock 依赖
        with patch.object(analyzer, '_select_best_match') as mock_select:
            mock_select.return_value = MagicMock()
            
            suggestions = analyzer.suggest_skills("Create a REST API")
            
            assert isinstance(suggestions, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
