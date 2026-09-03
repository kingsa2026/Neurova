#!/usr/bin/env python3
"""
Neurova 完整单元测试运行器
运行所有可用的单元测试并生成详细报告
"""

import unittest
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import io
import contextlib


class TestResultCollector(unittest.TextTestResult):
    """自定义测试结果收集器"""
    
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.test_results: List[Dict[str, Any]] = []
        self.start_time = None
        self.end_time = None

    def startTestRun(self):
        super().startTestRun()
        self.start_time = time.time()

    def stopTestRun(self):
        super().stopTestRun()
        self.end_time = time.time()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.test_results.append({
            "test": str(test),
            "status": "success",
            "duration": 0
        })

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.test_results.append({
            "test": str(test),
            "status": "failure",
            "error": self._exc_info_to_string(err, test)
        })

    def addError(self, test, err):
        super().addError(test, err)
        self.test_results.append({
            "test": str(test),
            "status": "error",
            "error": self._exc_info_to_string(err, test)
        })

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.test_results.append({
            "test": str(test),
            "status": "skipped",
            "reason": reason
        })


def discover_tests(start_dir: str = "tests/unit"):
    """发现所有测试"""
    loader = unittest.TestLoader()
    return loader.discover(start_dir, pattern="test_*.py")


def run_tests(test_suite) -> Dict[str, Any]:
    """运行测试"""
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = TestResultCollector(stream, descriptions=True, verbosity=2)
    
    start_time = time.time()
    test_result = test_suite.run(result)
    end_time = time.time()
    
    return {
        "results": result.test_results,
        "stream_output": stream.getvalue(),
        "duration": end_time - start_time,
        "total": test_result
    }


def generate_report(results: Dict[str, Any], output_file: str = "tests/COMPREHENSIVE_TEST_REPORT.md"):
    """生成Markdown格式的测试报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    total_tests = len(results["results"])
    passed = len([r for r in results["results"] if r["status"] == "success"])
    failed = len([r for r in results["results"] if r["status"] == "failure"])
    errors = len([r for r in results["results"] if r["status"] == "error"])
    skipped = len([r for r in results["results"] if r["status"] == "skipped"])
    
    report_lines = [
        "# Neurova 完整单元测试报告",
        f"生成时间: {now}",
        "",
        "## 总体统计",
        f"- 总测试数: {total_tests}",
        f"- 通过: {passed} ✅",
        f"- 失败: {failed} ❌",
        f"- 错误: {errors} ⚠️",
        f"- 跳过: {skipped} ⏭️",
        f"- 通过率: {(passed/total_tests*100):.1f}%" if total_tests > 0 else "- 通过率: 0%",
        f"- 总耗时: {results['duration']:.2f} 秒",
        "",
    ]
    
    if failed > 0 or errors > 0:
        report_lines.extend([
            "## 失败和错误详情",
            "",
        ])
        
        for result in results["results"]:
            if result["status"] in ["failure", "error"]:
                report_lines.extend([
                    f"### {result['test']}",
                    f"状态: {'失败' if result['status'] == 'failure' else '错误'}",
                    "",
                    "```",
                    result.get("error", "无错误信息"),
                    "```",
                    ""
                ])
    
    if skipped > 0:
        report_lines.extend([
            "## 跳过的测试",
            "",
        ])
        
        for result in results["results"]:
            if result["status"] == "skipped":
                report_lines.extend([
                    f"- {result['test']}: {result.get('reason', '无原因')}",
                ])
        report_lines.append("")
    
    report_lines.extend([
        "## 测试覆盖模块",
        "",
        "### 核心模块 (Core)",
        "- ConfigManager - 配置管理",
        "- StateManager - 状态管理",
        "- EventBus - 事件总线",
        "- LogManager - 日志管理",
        "",
        "### LLM模块",
        "- SecretStore - 密钥存储",
        "- ProviderManager - 提供者管理",
        "- MultiModelClient - 多模型客户端",
        "",
        "### 认证模块 (Auth)",
        "- PasswordHasher - 密码哈希",
        "- UserModel - 用户模型",
        "- VerificationCode - 验证码",
        "- InvitationCode - 邀请码",
        "",
        "### 安全模块 (Security)",
        "- RBACManager - 权限管理",
        "- DataMasker - 数据脱敏",
        "- ApiKeyManager - API密钥管理",
        "",
        "### 项目管理模块 (Projects)",
        "- ProjectManager - 项目管理",
        "- TeamManager - 团队管理",
        "",
        "### 频道模块 (Channels)",
        "- ChannelManager - 频道管理",
        "",
        "## 使用说明",
        "",
        "运行完整测试: `python tests/comprehensive_test_runner.py`",
        "",
        "运行特定模块测试: `python -m unittest tests/unit/core/`",
    ])
    
    report_content = "\n".join(report_lines)
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_content, encoding="utf-8")
    
    print(f"测试报告已生成: {output_file}")
    return report_content


def main():
    """主函数"""
    print("=" * 60)
    print("Neurova 完整单元测试运行器")
    print("=" * 60)
    
    # 发现测试
    print("\n发现测试...")
    test_suite = discover_tests()
    
    if test_suite.countTestCases() == 0:
        print("未找到测试文件，尝试从tests目录...")
        test_suite = discover_tests("tests")
    
    print(f"发现 {test_suite.countTestCases()} 个测试")
    
    # 运行测试
    print("\n开始运行测试...")
    results = run_tests(test_suite)
    
    # 打印结果
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print(results["stream_output"])
    
    # 生成报告
    print("\n生成测试报告...")
    generate_report(results)
    
    total = len(results["results"])
    passed = len([r for r in results["results"] if r["status"] == "success"])
    failed = len([r for r in results["results"] if r["status"] == "failure"])
    errors = len([r for r in results["results"] if r["status"] == "error"])
    
    print(f"\n总结: {passed}/{total} 通过, {failed} 失败, {errors} 错误")
    
    return 0 if (failed == 0 and errors == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
