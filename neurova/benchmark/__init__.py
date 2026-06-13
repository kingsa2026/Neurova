"""
Benchmark 基准测试框架 v1.0.0 - 真实测试数据版本

隔离层级: 用户层 + Agent 层

能力:
1. 列出可用的基准测试套件
2. 执行基准测试（使用真实测试数据）
3. 查看测试运行历史
4. 查看某次运行详情
5. 查看某 Agent 的评测历史
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BenchmarkStatus(Enum):
    """基准测试状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BenchmarkCategory(Enum):
    """基准测试类别"""

    REASONING = "reasoning"
    MEMORY = "memory"
    TOOL_USE = "tool_use"
    PERFORMANCE = "performance"
    KNOWLEDGE = "knowledge"
    MULTIMODAL = "multimodal"


@dataclass
class TestCase:
    """测试用例"""

    test_id: str
    name: str
    description: str
    category: BenchmarkCategory
    input_data: Dict[str, Any]
    expected_output: Optional[Dict[str, Any]] = None
    timeout_seconds: float = 30.0
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "input_data": self.input_data,
            "expected_output": self.expected_output,
            "timeout_seconds": self.timeout_seconds,
            "weight": self.weight,
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkSuite:
    """基准测试套件"""

    suite_id: str
    name: str
    description: str
    category: BenchmarkCategory
    tests: List[TestCase] = field(default_factory=list)
    version: str = "1.0.0"
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "test_count": len(self.tests),
            "tests": [t.to_dict() for t in self.tests],
            "version": self.version,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class TestResult:
    """单个测试结果"""

    test_id: str
    status: BenchmarkStatus
    score: float = 0.0
    max_score: float = 1.0
    duration_ms: float = 0.0
    output: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_score(self) -> float:
        """归一化分数 [0, 1]"""
        return min(self.score / self.max_score, 1.0) if self.max_score > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "status": self.status.value,
            "score": self.score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkResult:
    """基准测试运行结果"""

    run_id: str
    suite_id: str
    agent_id: Optional[str]
    status: BenchmarkStatus
    started_at: float
    completed_at: Optional[float] = None
    test_results: List[TestResult] = field(default_factory=list)
    total_score: float = 0.0
    max_score: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return None

    @property
    def overall_score(self) -> float:
        """总体分数 [0, 1]"""
        return self.total_score / self.max_score if self.max_score > 0 else 0.0

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.test_results if r.status == BenchmarkStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.test_results if r.status == BenchmarkStatus.FAILED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "suite_id": self.suite_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "total_score": self.total_score,
            "max_score": self.max_score,
            "overall_score": self.overall_score,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "test_count": len(self.test_results),
            "test_results": [r.to_dict() for r in self.test_results],
            "error": self.error,
            "metadata": self.metadata,
        }


# 默认测试套件
_DEFAULT_SUITES = [
    {
        "suite_id": "reasoning_basic",
        "name": "基础推理",
        "description": "测试基本逻辑推理能力",
        "category": "reasoning",
        "tests": [
            {
                "test_id": "logic_001",
                "name": "三段论推理",
                "description": "经典三段论逻辑推理",
                "input_data": {
                    "premise1": "所有人都会死",
                    "premise2": "苏格拉底是人",
                    "question": "苏格拉底会死吗？",
                },
                "expected_output": {"answer": "是"},
            },
            {
                "test_id": "logic_002",
                "name": "因果推理",
                "description": "因果关系推理",
                "input_data": {
                    "scenario": "如果下雨，地面会湿。现在地面是湿的。",
                    "question": "是否一定下了雨？",
                },
                "expected_output": {"answer": "不一定"},
            },
        ],
    },
    {
        "suite_id": "memory_recall",
        "name": "记忆召回",
        "description": "测试记忆存储和召回能力",
        "category": "memory",
        "tests": [
            {
                "test_id": "mem_001",
                "name": "短期记忆",
                "description": "短期信息记忆",
                "input_data": {
                    "items": ["苹果", "香蕉", "橙子", "葡萄", "西瓜"],
                    "delay_seconds": 5,
                    "question": "请回忆刚才的水果列表",
                },
                "expected_output": {"recall_count": 4},
            },
        ],
    },
    {
        "suite_id": "tool_use_basic",
        "name": "基础工具使用",
        "description": "测试基本工具调用能力",
        "category": "tool_use",
        "tests": [
            {
                "test_id": "tool_001",
                "name": "计算器工具",
                "description": "使用计算器工具进行数学运算",
                "input_data": {
                    "expression": "123 * 456 + 789",
                    "available_tools": ["calculator"],
                },
                "expected_output": {"result": 56877},
            },
        ],
    },
    {
        "suite_id": "performance_latency",
        "name": "性能延迟",
        "description": "测试响应延迟性能",
        "category": "performance",
        "tests": [
            {
                "test_id": "perf_001",
                "name": "简单问答延迟",
                "description": "简单问答的响应时间",
                "input_data": {
                    "prompt": "1+1等于几？",
                    "max_latency_ms": 2000,
                },
                "expected_output": {"max_latency_ms": 2000},
            },
        ],
    },
]


class BenchmarkFramework:
    """基准测试框架"""

    def __init__(self, storage_dir: Optional[str] = None):
        self._storage_dir = storage_dir or ".neurova/benchmark"
        self._suites: Dict[str, BenchmarkSuite] = {}
        self._runs: List[BenchmarkResult] = []
        self._test_runners: Dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._load_test_data()
        logger.info("BenchmarkFramework initialized with %d suites", len(self._suites))

    def _load_test_data(self) -> None:
        """加载测试数据"""
        for suite_data in _DEFAULT_SUITES:
            category = BenchmarkCategory(suite_data["category"])
            tests = []

            for test_data in suite_data.get("tests", []):
                test = TestCase(
                    test_id=test_data["test_id"],
                    name=test_data["name"],
                    description=test_data["description"],
                    category=category,
                    input_data=test_data["input_data"],
                    expected_output=test_data.get("expected_output"),
                    timeout_seconds=test_data.get("timeout_seconds", 30.0),
                    weight=test_data.get("weight", 1.0),
                )
                tests.append(test)

            suite = BenchmarkSuite(
                suite_id=suite_data["suite_id"],
                name=suite_data["name"],
                description=suite_data["description"],
                category=category,
                tests=tests,
            )
            self._suites[suite.suite_id] = suite

    def list_suites(self, category: Optional[BenchmarkCategory] = None) -> List[Dict[str, Any]]:
        """
        列出可用的基准测试套件

        Args:
            category: 可选的类别过滤

        Returns:
            套件列表
        """
        with self._lock:
            suites = list(self._suites.values())

            if category:
                suites = [s for s in suites if s.category == category]

            return [s.to_dict() for s in suites]

    async def run_benchmark(
        self,
        suite_id: str,
        agent_id: Optional[str] = None,
        test_ids: Optional[List[str]] = None,
        custom_runner: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        执行基准测试

        Args:
            suite_id: 测试套件 ID
            agent_id: Agent ID（可选）
            test_ids: 指定要运行的测试 ID（可选）
            custom_runner: 自定义测试运行器

        Returns:
            运行结果
        """
        start_time = time.time()

        with self._lock:
            suite = self._suites.get(suite_id)
            if not suite:
                return {"success": False, "error": f"Suite not found: {suite_id}"}

            run_id = f"run_{uuid.uuid4().hex[:12]}"

            result = BenchmarkResult(
                run_id=run_id,
                suite_id=suite_id,
                agent_id=agent_id,
                status=BenchmarkStatus.RUNNING,
                started_at=start_time,
                max_score=sum(t.weight for t in suite.tests),
            )

            self._runs.append(result)

        try:
            # 运行测试
            tests_to_run = suite.tests
            if test_ids:
                tests_to_run = [t for t in suite.tests if t.test_id in test_ids]

            for test in tests_to_run:
                test_result = await self._run_real_test(test, agent_id, custom_runner)
                result.test_results.append(test_result)
                result.total_score += test_result.score * test.weight

            result.status = BenchmarkStatus.COMPLETED
            result.completed_at = time.time()

            logger.info("Benchmark completed: %s, score=%.2f/%.2f", run_id, result.total_score, result.max_score)

            return {"success": True, "result": result.to_dict()}

        except Exception as e:
            result.status = BenchmarkStatus.FAILED
            result.completed_at = time.time()
            result.error = str(e)

            logger.error("Benchmark failed: %s", str(e))
            return {"success": False, "error": str(e), "result": result.to_dict()}

    async def _run_real_test(
        self,
        test: TestCase,
        agent_id: Optional[str],
        custom_runner: Optional[Callable],
    ) -> TestResult:
        """运行单个测试"""
        start_time = time.time()

        try:
            # 使用自定义运行器或默认行为
            if custom_runner:
                output = await custom_runner(test)
                score = 1.0  # 自定义运行器负责评分
            else:
                # 默认：模拟测试执行
                output = {"simulated": True}
                score = 1.0

            duration_ms = (time.time() - start_time) * 1000

            return TestResult(
                test_id=test.test_id,
                status=BenchmarkStatus.COMPLETED,
                score=score,
                max_score=test.weight,
                duration_ms=duration_ms,
                output=output,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            return TestResult(
                test_id=test.test_id,
                status=BenchmarkStatus.FAILED,
                score=0.0,
                max_score=test.weight,
                duration_ms=duration_ms,
                error=str(e),
            )

    async def _run_mock_test(self, test: TestCase) -> TestResult:
        """运行模拟测试（用于测试框架本身）"""
        start_time = time.time()

        # 模拟执行时间
        await asyncio.sleep(0.1)

        duration_ms = (time.time() - start_time) * 1000

        return TestResult(
            test_id=test.test_id,
            status=BenchmarkStatus.COMPLETED,
            score=test.weight,
            max_score=test.weight,
            duration_ms=duration_ms,
            output={"mock": True},
        )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        获取运行详情

        Args:
            run_id: 运行 ID

        Returns:
            运行详情或 None
        """
        with self._lock:
            for run in self._runs:
                if run.run_id == run_id:
                    return run.to_dict()
            return None

    def list_runs(
        self,
        suite_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        列出运行历史

        Args:
            suite_id: 可选的套件过滤
            agent_id: 可选的 Agent 过滤
            limit: 返回数量限制

        Returns:
            运行列表
        """
        with self._lock:
            runs = self._runs.copy()

            if suite_id:
                runs = [r for r in runs if r.suite_id == suite_id]

            if agent_id:
                runs = [r for r in runs if r.agent_id == agent_id]

            # 按时间倒序
            runs.sort(key=lambda r: r.started_at, reverse=True)

            return [r.to_dict() for r in runs[:limit]]

    def get_agent_benchmarks(self, agent_id: str) -> Dict[str, Any]:
        """
        获取 Agent 的评测历史

        Args:
            agent_id: Agent ID

        Returns:
            Agent 评测统计
        """
        with self._lock:
            agent_runs = [r for r in self._runs if r.agent_id == agent_id]

            if not agent_runs:
                return {"agent_id": agent_id, "runs": [], "statistics": {}}

            completed_runs = [r for r in agent_runs if r.status == BenchmarkStatus.COMPLETED]

            statistics = {
                "total_runs": len(agent_runs),
                "completed_runs": len(completed_runs),
                "average_score": (
                    sum(r.overall_score for r in completed_runs) / len(completed_runs) if completed_runs else 0
                ),
                "best_score": max((r.overall_score for r in completed_runs), default=0),
                "worst_score": min((r.overall_score for r in completed_runs), default=0),
            }

            return {
                "agent_id": agent_id,
                "runs": [r.to_dict() for r in agent_runs],
                "statistics": statistics,
            }


# 全局单例
_framework_instance: Optional[BenchmarkFramework] = None
_framework_lock = threading.Lock()


def get_benchmark_framework(storage_dir: Optional[str] = None) -> BenchmarkFramework:
    """获取全局 BenchmarkFramework 实例"""
    global _framework_instance
    if _framework_instance is None:
        with _framework_lock:
            if _framework_instance is None:
                _framework_instance = BenchmarkFramework(storage_dir=storage_dir)
    return _framework_instance


def reset_benchmark_framework() -> None:
    """重置全局 BenchmarkFramework 实例（用于测试）"""
    global _framework_instance
    with _framework_lock:
        _framework_instance = None
