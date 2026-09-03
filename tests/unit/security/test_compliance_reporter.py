"""
测试：合规报告生成模块 (neurova/security/compliance_reporter.py)
"""

import datetime
import json
import pytest
from pathlib import Path

from neurova.security.compliance_reporter import (
    ReportTemplate,
    ReportStatus,
    ComplianceReport,
    ReportSubscription,
    ComplianceReporter,
    get_compliance_reporter,
)


# ============================================================
# 测试枚举
# ============================================================

class TestEnums:
    """枚举测试"""

    def test_report_template_members(self):
        assert ReportTemplate.SECURITY_OVERVIEW.value == "security_overview"
        assert ReportTemplate.GDPR_COMPLIANCE.value == "gdpr_compliance"
        assert ReportTemplate.EQUAL_PROTECTION.value == "equal_protection"
        assert ReportTemplate.AUDIT_SUMMARY.value == "audit_summary"
        assert ReportTemplate.ACCESS_CONTROL.value == "access_control"
        assert ReportTemplate.CUSTOM.value == "custom"

    def test_report_status_members(self):
        assert ReportStatus.PENDING.value == "pending"
        assert ReportStatus.GENERATING.value == "generating"
        assert ReportStatus.COMPLETED.value == "completed"
        assert ReportStatus.FAILED.value == "failed"


# ============================================================
# 测试数据类
# ============================================================

class TestDataClasses:
    """数据类测试"""

    def test_compliance_report_to_dict(self):
        report = ComplianceReport(
            title="测试报告",
            template=ReportTemplate.SECURITY_OVERVIEW,
        )
        data = report.to_dict()
        assert data["title"] == "测试报告"
        assert data["template"] == "security_overview"
        assert data["status"] == "pending"

    def test_compliance_report_from_dict(self):
        data = {
            "report_id": "test-123",
            "title": "测试报告",
            "template": "gdpr_compliance",
            "status": "completed",
            "created_at": "2026-06-05T10:00:00",
        }
        report = ComplianceReport.from_dict(data)
        assert report.report_id == "test-123"
        assert report.template == ReportTemplate.GDPR_COMPLIANCE
        assert report.status == ReportStatus.COMPLETED

    def test_report_subscription_to_dict(self):
        subscription = ReportSubscription(
            template=ReportTemplate.SECURITY_OVERVIEW,
            frequency="weekly",
            recipients=["admin@example.com"],
        )
        data = subscription.to_dict()
        assert data["template"] == "security_overview"
        assert data["frequency"] == "weekly"
        assert data["recipients"] == ["admin@example.com"]


# ============================================================
# 测试 ComplianceReporter
# ============================================================

class TestComplianceReporter:
    """合规报告生成器"""

    def test_init(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        assert reporter._reports_dir.exists()

    def test_create_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter.create_report(
            title="测试报告",
            template=ReportTemplate.SECURITY_OVERVIEW,
        )
        assert report.report_id is not None
        assert report.title == "测试报告"
        assert report.status == ReportStatus.PENDING

    def test_generate_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter.create_report("测试报告")
        result = reporter.generate_report(report.report_id)
        assert result.status == ReportStatus.COMPLETED
        assert result.file_path is not None
        assert result.content is not None

    def test_generate_gdpr_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter.create_report("GDPR报告", template=ReportTemplate.GDPR_COMPLIANCE)
        result = reporter.generate_report(report.report_id)
        assert result.status == ReportStatus.COMPLETED
        assert "GDPR" in result.content

    def test_generate_equal_protection_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter.create_report("等保报告", template=ReportTemplate.EQUAL_PROTECTION)
        result = reporter.generate_report(report.report_id)
        assert result.status == ReportStatus.COMPLETED
        assert "等保" in result.content

    def test_list_reports(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        reporter.create_report("报告1")
        reporter.create_report("报告2")
        reporter.create_report("报告3")
        reports = reporter.list_reports()
        assert len(reports) == 3

    def test_get_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        created = reporter.create_report("测试报告")
        fetched = reporter.get_report(created.report_id)
        assert fetched is not None
        assert fetched.title == "测试报告"

    def test_get_nonexistent_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        assert reporter.get_report("nonexistent") is None

    def test_download_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter.create_report("测试报告")
        reporter.generate_report(report.report_id)
        file_path = reporter.download_report(report.report_id)
        assert file_path is not None
        assert Path(file_path).exists()

    def test_delete_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter.create_report("测试报告")
        reporter.generate_report(report.report_id)
        success = reporter.delete_report(report.report_id)
        assert success is True
        assert reporter.get_report(report.report_id) is None

    def test_delete_nonexistent_report(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        assert reporter.delete_report("nonexistent") is False

    def test_create_subscription(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        subscription = reporter.create_subscription(
            template=ReportTemplate.SECURITY_OVERVIEW,
            frequency="weekly",
            recipients=["admin@example.com"],
        )
        assert subscription.subscription_id is not None
        assert subscription.frequency == "weekly"

    def test_list_subscriptions(self, tmp_path):
        reporter = ComplianceReporter(workspace_path=str(tmp_path))
        reporter.create_subscription(ReportTemplate.SECURITY_OVERVIEW, "daily")
        reporter.create_subscription(ReportTemplate.GDPR_COMPLIANCE, "weekly")
        subscriptions = reporter.list_subscriptions()
        assert len(subscriptions) == 2

    def test_persistence(self, tmp_path):
        # 创建报告
        reporter1 = ComplianceReporter(workspace_path=str(tmp_path))
        report = reporter1.create_report("持久化测试")

        # 新实例应能加载之前的报告
        reporter2 = ComplianceReporter(workspace_path=str(tmp_path))
        loaded = reporter2.get_report(report.report_id)
        assert loaded is not None
        assert loaded.title == "持久化测试"


# ============================================================
# 测试全局函数
# ============================================================

class TestGlobalFunctions:
    """全局函数测试"""

    def test_get_compliance_reporter_singleton(self, tmp_path):
        # 需要先清除全局单例
        import neurova.security.compliance_reporter as module
        original = module._compliance_reporter
        module._compliance_reporter = None

        try:
            reporter1 = get_compliance_reporter(str(tmp_path))
            reporter2 = get_compliance_reporter(str(tmp_path))
            assert reporter1 is reporter2
        finally:
            module._compliance_reporter = original


# ============================================================
# 集成测试
# ============================================================

class TestComplianceIntegration:
    """集成测试"""

    def test_full_workflow(self, tmp_path):
        """完整工作流测试"""
        reporter = ComplianceReporter(workspace_path=str(tmp_path))

        # 1. 创建报告
        report = reporter.create_report(
            title="安全概览报告",
            template=ReportTemplate.SECURITY_OVERVIEW,
        )
        assert report.status == ReportStatus.PENDING

        # 2. 生成报告
        report = reporter.generate_report(report.report_id)
        assert report.status == ReportStatus.COMPLETED
        assert report.file_path is not None

        # 3. 下载报告
        file_path = reporter.download_report(report.report_id)
        assert file_path is not None
        assert Path(file_path).exists()

        # 4. 列出报告
        reports = reporter.list_reports()
        assert len(reports) == 1
        assert reports[0].report_id == report.report_id

        # 5. 删除报告
        success = reporter.delete_report(report.report_id)
        assert success is True
        assert len(reporter.list_reports()) == 0

    def test_multiple_templates(self, tmp_path):
        """多模板测试"""
        reporter = ComplianceReporter(workspace_path=str(tmp_path))

        templates = [
            ReportTemplate.SECURITY_OVERVIEW,
            ReportTemplate.GDPR_COMPLIANCE,
            ReportTemplate.EQUAL_PROTECTION,
            ReportTemplate.AUDIT_SUMMARY,
            ReportTemplate.ACCESS_CONTROL,
        ]

        for template in templates:
            report = reporter.create_report(f"{template.value}报告", template=template)
            reporter.generate_report(report.report_id)

        reports = reporter.list_reports()
        assert len(reports) == 5

    def test_subscription_workflow(self, tmp_path):
        """订阅工作流测试"""
        reporter = ComplianceReporter(workspace_path=str(tmp_path))

        # 创建订阅
        subscription = reporter.create_subscription(
            template=ReportTemplate.SECURITY_OVERVIEW,
            frequency="weekly",
            recipients=["admin@example.com", "security@example.com"],
        )

        # 列出订阅
        subscriptions = reporter.list_subscriptions()
        assert len(subscriptions) == 1
        assert subscriptions[0].frequency == "weekly"
