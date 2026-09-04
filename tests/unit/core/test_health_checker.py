"""
测试健康检查器模块
"""
import pytest
from neurova.core.health_checker import (
    HealthStatus,
    CheckType,
    RecoveryAction,
    HealthCheck,
    HealthCheckResult,
    HealthChecker,
    get_health_checker,
)


class TestEnums:
    """测试枚举类"""

    def test_health_status_members(self):
        """测试健康状态枚举"""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_check_type_members(self):
        """测试检查类型枚举"""
        assert CheckType.LIVENESS.value == "liveness"
        assert CheckType.READINESS.value == "readiness"
        assert CheckType.DEPENDENCY.value == "dependency"
        assert CheckType.CUSTOM.value == "custom"

    def test_recovery_action_members(self):
        """测试恢复动作枚举"""
        assert RecoveryAction.RESTART.value == "restart"
        assert RecoveryAction.RECONNECT.value == "reconnect"
        assert RecoveryAction.FALLBACK.value == "fallback"
        assert RecoveryAction.ALERT.value == "alert"
        assert RecoveryAction.NONE.value == "none"


class TestHealthCheck:
    """测试HealthCheck类"""

    def test_create_health_check(self):
        """测试创建健康检查"""
        def mock_check():
            return True, "OK"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
            timeout=10.0,
            critical=True,
            interval=60.0,
        )

        assert health_check.name == "test_check"
        assert health_check.check_type == CheckType.CUSTOM
        assert health_check.check_func == mock_check
        assert health_check.timeout == 10.0
        assert health_check.critical is True
        assert health_check.interval == 60.0


class TestHealthCheckResult:
    """测试HealthCheckResult类"""

    def test_create_health_check_result(self):
        """测试创建健康检查结果"""
        result = HealthCheckResult(
            name="test_check",
            status=HealthStatus.HEALTHY,
            message="检查通过",
            details={"key": "value"},
            duration=100.0,
        )

        assert result.name == "test_check"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "检查通过"
        assert result.details == {"key": "value"}
        assert result.duration == 100.0


class TestHealthChecker:
    """测试HealthChecker类"""

    def test_init(self):
        """测试初始化"""
        checker = HealthChecker()

        assert checker._checks == {}
        assert checker._results == {}

    def test_register_check(self):
        """测试注册健康检查"""
        checker = HealthChecker()

        def mock_check():
            return True, "OK"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
        )

        checker.register_check(health_check)

        assert "test_check" in checker._checks

    def test_register快捷方法(self):
        """测试快捷注册健康检查"""
        checker = HealthChecker()

        def mock_check():
            return True, "OK"

        checker.register("quick_check", mock_check, check_type=CheckType.READINESS)

        assert "quick_check" in checker._checks
        assert checker._checks["quick_check"].check_type == CheckType.READINESS

    def test_run_check_success(self):
        """测试运行健康检查成功"""
        checker = HealthChecker()

        def mock_check():
            return True, "检查通过"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
        )

        checker.register_check(health_check)

        result = checker.run_check("test_check")

        assert result is not None
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "检查通过"

    def test_run_check_failure(self):
        """测试运行健康检查失败"""
        checker = HealthChecker()

        def mock_check():
            return False, "检查失败"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
        )

        checker.register_check(health_check)

        result = checker.run_check("test_check")

        assert result is not None
        assert result.status == HealthStatus.UNHEALTHY

    def test_run_check_nonexistent(self):
        """测试运行不存在的健康检查"""
        checker = HealthChecker()

        result = checker.run_check("nonexistent")

        assert result is None

    def test_run_check_exception(self):
        """测试健康检查抛出异常"""
        checker = HealthChecker()

        def bad_check():
            raise RuntimeError("Check error")

        health_check = HealthCheck(
            name="bad_check",
            check_type=CheckType.CUSTOM,
            check_func=bad_check,
        )

        checker.register_check(health_check)

        result = checker.run_check("bad_check")

        assert result is not None
        assert result.status == HealthStatus.UNHEALTHY

    def test_run_all_checks(self):
        """测试运行所有健康检查"""
        checker = HealthChecker()

        def mock_check1():
            return True, "OK"

        def mock_check2():
            return True, "OK"

        health_check1 = HealthCheck(
            name="check1",
            check_type=CheckType.CUSTOM,
            check_func=mock_check1,
        )
        health_check2 = HealthCheck(
            name="check2",
            check_type=CheckType.CUSTOM,
            check_func=mock_check2,
        )

        checker.register_check(health_check1)
        checker.register_check(health_check2)

        results = checker.run_all_checks()

        assert len(results) == 2
        assert "check1" in results
        assert "check2" in results

    def test_get_check_result(self):
        """测试获取上次检查结果"""
        checker = HealthChecker()
        assert checker.get_check_result("nonexistent") is None

    def test_get_all_results(self):
        """测试获取所有检查结果"""
        checker = HealthChecker()
        results = checker.get_all_results()
        assert isinstance(results, dict)

    def test_clear_results(self):
        """测试清空检查结果"""
        checker = HealthChecker()

        def mock_check():
            return True, "OK"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
        )

        checker.register_check(health_check)
        checker.run_check("test_check")
        assert len(checker._results) == 1

        checker.clear_results()
        assert len(checker._results) == 0

    def test_get_overall_status_unknown(self):
        """测试获取整体状态（未知）"""
        checker = HealthChecker()

        assert checker.get_overall_status() == HealthStatus.UNKNOWN

    def test_get_overall_status_healthy(self):
        """测试获取整体状态（健康）"""
        checker = HealthChecker()

        def mock_check():
            return True, "OK"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
        )

        checker.register_check(health_check)
        checker.run_check("test_check")

        assert checker.get_overall_status() == HealthStatus.HEALTHY

    def test_get_report(self):
        """测试获取健康报告"""
        checker = HealthChecker()

        def mock_check():
            return True, "OK"

        health_check = HealthCheck(
            name="test_check",
            check_type=CheckType.CUSTOM,
            check_func=mock_check,
        )

        checker.register_check(health_check)
        checker.run_check("test_check")

        report = checker.get_report()

        assert report["status"] == "healthy"
        assert "checks" in report
        assert "test_check" in report["checks"]


class TestGlobalFunctions:
    """测试全局函数"""

    def test_get_health_checker(self):
        """测试获取健康检查器实例"""
        checker1 = get_health_checker()
        checker2 = get_health_checker()

        assert checker1 is checker2
