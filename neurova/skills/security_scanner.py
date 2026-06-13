"""
Skill 安全扫描系统

提供Skill的安全扫描、沙箱执行和安全管理功能。
包括静态代码分析、危险函数检测、权限检查和沙箱隔离执行。
"""

import ast
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SecurityLevel(str, Enum):
    """
    安全级别枚举
    """

    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


@dataclass
class SecurityIssue:
    """
    安全问题数据类
    """

    level: SecurityLevel
    description: str
    file_path: str = ""
    line_number: int = 0
    code_snippet: str = ""
    recommendation: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "level": self.level.value,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "recommendation": self.recommendation,
            "metadata": self.metadata,
        }


@dataclass
class SecurityReport:
    """
    安全报告数据类
    """

    skill_name: str
    issues: List[SecurityIssue] = field(default_factory=list)
    overall_level: SecurityLevel = SecurityLevel.SAFE
    scan_time: float = 0.0
    files_scanned: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_critical_issues(self) -> bool:
        """是否有严重问题"""
        return any(issue.level == SecurityLevel.CRITICAL for issue in self.issues)

    def has_dangerous_issues(self) -> bool:
        """是否有危险问题"""
        return any(issue.level in [SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL] for issue in self.issues)

    def get_issues_by_level(self, level: SecurityLevel) -> List[SecurityIssue]:
        """按级别获取问题"""
        return [issue for issue in self.issues if issue.level == level]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "skill_name": self.skill_name,
            "issues": [issue.to_dict() for issue in self.issues],
            "overall_level": self.overall_level.value,
            "scan_time": self.scan_time,
            "files_scanned": self.files_scanned,
            "metadata": self.metadata,
        }


class _DangerousNodeVisitor(ast.NodeVisitor):
    """
    危险代码节点访问器

    使用 AST 分析检测危险的代码模式。
    """

    # 危险的内置函数
    DANGEROUS_BUILTINS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "isinstance",
        "issubclass",
        "callable",
        "repr",
        "hash",
        "id",
        "type",
        "super",
        "classmethod",
        "staticmethod",
    }

    # 危险的 os 函数
    DANGEROUS_OS_FUNCTIONS = {
        "system",
        "popen",
        "exec",
        "execle",
        "execl",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "spawn",
        "spawnl",
        "spawnle",
        "spawnv",
        "spawnve",
        "startfile",
        "remove",
        "unlink",
        "rename",
        "rmdir",
        "removedirs",
        "makedirs",
        "mkdir",
    }

    # 危险的模块
    DANGEROUS_MODULES = {
        "subprocess",
        "shutil",
        "socket",
        "http",
        "ftplib",
        "smtplib",
        "imaplib",
        "poplib",
        "telnetlib",
        "xmlrpc",
        "pickle",
        "shelve",
        "marshal",
        "ctypes",
        "signal",
        "mmap",
    }

    def __init__(self, source_code: str = ""):
        """
        初始化访问器

        Args:
            source_code: 源代码
        """
        self.issues: List[SecurityIssue] = []
        self.source_code = source_code
        self.source_lines = source_code.splitlines() if source_code else []

    def visit_Import(self, node: ast.Import):
        """访问 import 语句"""
        for alias in node.names:
            module_name = alias.name
            if module_name in self.DANGEROUS_MODULES:
                self.issues.append(
                    SecurityIssue(
                        level=SecurityLevel.WARNING,
                        description=f"Import of potentially dangerous module: {module_name}",
                        line_number=node.lineno,
                        code_snippet=self._get_source_snippet(node.lineno),
                        recommendation=f"Review the usage of {module_name} module",
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """访问 from...import 语句"""
        if node.module:
            module_name = node.module
            if module_name in self.DANGEROUS_MODULES:
                self.issues.append(
                    SecurityIssue(
                        level=SecurityLevel.WARNING,
                        description=f"Import from potentially dangerous module: {module_name}",
                        line_number=node.lineno,
                        code_snippet=self._get_source_snippet(node.lineno),
                        recommendation=f"Review the usage of {module_name} module",
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """访问函数调用"""
        call_name = self._get_call_name(node)

        if call_name:
            # 检查危险的内置函数
            if call_name in self.DANGEROUS_BUILTINS:
                self.issues.append(
                    SecurityIssue(
                        level=SecurityLevel.DANGEROUS,
                        description=f"Call to dangerous builtin function: {call_name}",
                        line_number=node.lineno,
                        code_snippet=self._get_source_snippet(node.lineno),
                        recommendation=f"Avoid using {call_name} as it can be a security risk",
                    )
                )

            # 检查 os.system 等危险调用
            if call_name.startswith("os.") and call_name[3:] in self.DANGEROUS_OS_FUNCTIONS:
                self.issues.append(
                    SecurityIssue(
                        level=SecurityLevel.CRITICAL,
                        description=f"Call to dangerous os function: {call_name}",
                        line_number=node.lineno,
                        code_snippet=self._get_source_snippet(node.lineno),
                        recommendation=f"Avoid using {call_name} as it can execute arbitrary commands",
                    )
                )

            # 检查 subprocess 调用
            if call_name.startswith("subprocess."):
                self.issues.append(
                    SecurityIssue(
                        level=SecurityLevel.DANGEROUS,
                        description=f"Call to subprocess function: {call_name}",
                        line_number=node.lineno,
                        code_snippet=self._get_source_snippet(node.lineno),
                        recommendation="Use subprocess with caution and validate all inputs",
                    )
                )

        self.generic_visit(node)

    def visit_Exec(self, node):
        """访问 exec 语句（Python 2 兼容）"""
        self.issues.append(
            SecurityIssue(
                level=SecurityLevel.CRITICAL,
                description="Use of exec statement",
                line_number=node.lineno,
                code_snippet=self._get_source_snippet(node.lineno),
                recommendation="Avoid using exec as it can execute arbitrary code",
            )
        )
        self.generic_visit(node)

    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """
        获取函数调用名称

        Args:
            node: 函数调用节点

        Returns:
            Optional[str]: 函数名称
        """
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            elif isinstance(node.func.value, ast.Attribute):
                # 处理链式调用如 os.path.join
                parent = self._get_call_name(ast.Call(func=node.func.value, args=[]))
                if parent:
                    return f"{parent}.{node.func.attr}"
        return None

    def _get_source_snippet(self, line_number: int, context_lines: int = 2) -> str:
        """
        获取源代码片段

        Args:
            line_number: 行号
            context_lines: 上下文行数

        Returns:
            str: 源代码片段
        """
        if not self.source_lines:
            return ""

        start = max(0, line_number - context_lines - 1)
        end = min(len(self.source_lines), line_number + context_lines)

        snippet_lines = []
        for i in range(start, end):
            prefix = ">>> " if i == line_number - 1 else "    "
            snippet_lines.append(f"{prefix}{i+1}: {self.source_lines[i]}")

        return "\n".join(snippet_lines)


class SkillScanner:
    """
    技能扫描器

    提供静态代码分析、危险函数检测和权限检查功能。
    """

    # 危险的文件扩展名
    DANGEROUS_EXTENSIONS = {".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".js"}

    # 敏感文件模式
    SENSITIVE_PATTERNS = [
        r"\.env",
        r"\.git",
        r"\.ssh",
        r"\.aws",
        r"password",
        r"secret",
        r"token",
        r"key\.pem",
        r"id_rsa",
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化扫描器

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self._dangerous_visitor = _DangerousNodeVisitor()
        logger.info("SkillScanner initialized")

    def scan(self, skill_path: str) -> SecurityReport:
        """
        扫描技能目录

        Args:
            skill_path: 技能目录路径

        Returns:
            SecurityReport: 安全报告
        """
        start_time = time.time()
        skill_path = Path(skill_path)

        if not skill_path.exists():
            return SecurityReport(
                skill_name=skill_path.name,
                issues=[
                    SecurityIssue(level=SecurityLevel.CRITICAL, description=f"Skill path does not exist: {skill_path}")
                ],
                overall_level=SecurityLevel.CRITICAL,
                scan_time=time.time() - start_time,
            )

        all_issues: List[SecurityIssue] = []
        files_scanned = 0

        # 扫描所有 Python 文件
        for py_file in skill_path.rglob("*.py"):
            try:
                file_issues = self._scan_file(str(py_file))
                all_issues.extend(file_issues)
                files_scanned += 1
            except Exception as e:
                logger.error("Failed to scan %s: %s", py_file, e)
                all_issues.append(
                    SecurityIssue(
                        level=SecurityLevel.WARNING,
                        description=f"Failed to scan file: {py_file}",
                        file_path=str(py_file),
                    )
                )

        # 检查危险文件类型
        for dangerous_ext in self.DANGEROUS_EXTENSIONS:
            for dangerous_file in skill_path.rglob(f"*{dangerous_ext}"):
                all_issues.append(
                    SecurityIssue(
                        level=SecurityLevel.WARNING,
                        description=f"Dangerous file type found: {dangerous_file.name}",
                        file_path=str(dangerous_file),
                        recommendation="Remove or review executable files",
                    )
                )

        # 检查敏感文件
        for pattern in self.SENSITIVE_PATTERNS:
            for sensitive_file in skill_path.rglob(f"*{pattern}*"):
                all_issues.append(
                    SecurityIssue(
                        level=SecurityLevel.WARNING,
                        description=f"Sensitive file found: {sensitive_file.name}",
                        file_path=str(sensitive_file),
                        recommendation="Remove sensitive files before distribution",
                    )
                )

        # 计算总体安全级别
        overall_level = self._calculate_security_level(all_issues)

        return SecurityReport(
            skill_name=skill_path.name,
            issues=all_issues,
            overall_level=overall_level,
            scan_time=time.time() - start_time,
            files_scanned=files_scanned,
        )

    def scan_file(self, file_path: str) -> SecurityReport:
        """
        扫描单个文件

        Args:
            file_path: 文件路径

        Returns:
            SecurityReport: 安全报告
        """
        start_time = time.time()
        file_path = Path(file_path)

        if not file_path.exists():
            return SecurityReport(
                skill_name=file_path.name,
                issues=[SecurityIssue(level=SecurityLevel.CRITICAL, description=f"File does not exist: {file_path}")],
                overall_level=SecurityLevel.CRITICAL,
                scan_time=time.time() - start_time,
            )

        issues = self._scan_file(str(file_path))
        overall_level = self._calculate_security_level(issues)

        return SecurityReport(
            skill_name=file_path.name,
            issues=issues,
            overall_level=overall_level,
            scan_time=time.time() - start_time,
            files_scanned=1,
        )

    def _scan_file(self, file_path: str) -> List[SecurityIssue]:
        """
        扫描单个文件（内部方法）

        Args:
            file_path: 文件路径

        Returns:
            List[SecurityIssue]: 安全问题列表
        """
        issues: List[SecurityIssue] = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()

            # AST 分析
            ast_issues = self._analyze_ast(source_code, file_path)
            issues.extend(ast_issues)

            # 检查危险函数
            danger_issues = self._check_dangerous_functions(source_code, file_path)
            issues.extend(danger_issues)

            # 检查权限
            permission_issues = self._check_permissions(source_code, file_path)
            issues.extend(permission_issues)

        except SyntaxError as e:
            issues.append(
                SecurityIssue(
                    level=SecurityLevel.WARNING,
                    description=f"Syntax error in file: {e}",
                    file_path=file_path,
                    line_number=e.lineno or 0,
                )
            )
        except Exception as e:
            issues.append(
                SecurityIssue(
                    level=SecurityLevel.WARNING, description=f"Failed to analyze file: {e}", file_path=file_path
                )
            )

        return issues

    def _check_dangerous_functions(self, source_code: str, file_path: str) -> List[SecurityIssue]:
        """
        检查危险函数

        Args:
            source_code: 源代码
            file_path: 文件路径

        Returns:
            List[SecurityIssue]: 安全问题列表
        """
        issues: List[SecurityIssue] = []

        # 使用正则表达式检查危险函数调用
        import re

        dangerous_patterns = [
            (r"\beval\s*\(", SecurityLevel.CRITICAL, "Use of eval()"),
            (r"\bexec\s*\(", SecurityLevel.CRITICAL, "Use of exec()"),
            (r"\bos\.system\s*\(", SecurityLevel.CRITICAL, "Use of os.system()"),
            (r"\bsubprocess\.call\s*\(", SecurityLevel.DANGEROUS, "Use of subprocess.call()"),
            (r"\bsubprocess\.Popen\s*\(", SecurityLevel.DANGEROUS, "Use of subprocess.Popen()"),
            (r"\b__import__\s*\(", SecurityLevel.DANGEROUS, "Use of __import__()"),
            (r"\bcompile\s*\(", SecurityLevel.WARNING, "Use of compile()"),
        ]

        lines = source_code.splitlines()
        for line_num, line in enumerate(lines, 1):
            for pattern, level, description in dangerous_patterns:
                if re.search(pattern, line):
                    issues.append(
                        SecurityIssue(
                            level=level,
                            description=description,
                            file_path=file_path,
                            line_number=line_num,
                            code_snippet=line.strip(),
                            recommendation=f"Review the usage of this function",
                        )
                    )

        return issues

    def _analyze_ast(self, source_code: str, file_path: str) -> List[SecurityIssue]:
        """
        AST 分析

        Args:
            source_code: 源代码
            file_path: 文件路径

        Returns:
            List[SecurityIssue]: 安全问题列表
        """
        try:
            tree = ast.parse(source_code)
            visitor = _DangerousNodeVisitor(source_code)
            visitor.visit(tree)

            # 设置文件路径
            for issue in visitor.issues:
                issue.file_path = file_path

            return visitor.issues
        except SyntaxError:
            return []

    def _check_permissions(self, source_code: str, file_path: str) -> List[SecurityIssue]:
        """
        检查权限相关代码

        Args:
            source_code: 源代码
            file_path: 文件路径

        Returns:
            List[SecurityIssue]: 安全问题列表
        """
        issues: List[SecurityIssue] = []

        # 检查文件权限修改
        import re

        permission_patterns = [
            (r"\bos\.chmod\s*\(", SecurityLevel.WARNING, "File permission modification"),
            (r"\bos\.chown\s*\(", SecurityLevel.WARNING, "File ownership modification"),
            (r"\bos\.umask\s*\(", SecurityLevel.WARNING, "Umask modification"),
        ]

        lines = source_code.splitlines()
        for line_num, line in enumerate(lines, 1):
            for pattern, level, description in permission_patterns:
                if re.search(pattern, line):
                    issues.append(
                        SecurityIssue(
                            level=level,
                            description=description,
                            file_path=file_path,
                            line_number=line_num,
                            code_snippet=line.strip(),
                            recommendation="Review permission changes",
                        )
                    )

        return issues

    def _calculate_security_level(self, issues: List[SecurityIssue]) -> SecurityLevel:
        """
        计算总体安全级别

        Args:
            issues: 安全问题列表

        Returns:
            SecurityLevel: 总体安全级别
        """
        if not issues:
            return SecurityLevel.SAFE

        # 按严重程度排序
        level_order = {
            SecurityLevel.CRITICAL: 4,
            SecurityLevel.DANGEROUS: 3,
            SecurityLevel.WARNING: 2,
            SecurityLevel.SAFE: 1,
        }

        max_level = max(issues, key=lambda x: level_order.get(x.level, 0))
        return max_level.level


class SkillSandbox:
    """
    技能沙箱

    提供安全的代码执行环境。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化沙箱

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self._timeout = self.config.get("timeout", 30)  # 默认30秒超时
        self._max_memory = self.config.get("max_memory", 100 * 1024 * 1024)  # 默认100MB
        logger.info("SkillSandbox initialized")

    def execute(self, code: str, language: str = "python") -> "ExecutionResult":
        """
        执行代码

        Args:
            code: 要执行的代码
            language: 编程语言

        Returns:
            ExecutionResult: 执行结果
        """
        if language != "python":
            return ExecutionResult(success=False, error=f"Unsupported language: {language}", output="")

        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                temp_path = f.name

            # 创建受限环境
            restricted_env = self._create_restricted_env()

            # 执行代码
            result = self._execute_in_sandbox(temp_path, restricted_env)

            # 清理临时文件
            os.unlink(temp_path)

            return result

        except Exception as e:
            return ExecutionResult(success=False, error=str(e), output="")

    def _create_restricted_env(self) -> Dict[str, str]:
        """
        创建受限环境变量

        Returns:
            Dict[str, str]: 环境变量字典
        """
        env = os.environ.copy()

        # 移除敏感环境变量
        sensitive_vars = [
            "AWS_SECRET_ACCESS_KEY",
            "AWS_ACCESS_KEY_ID",
            "GITHUB_TOKEN",
            "GITHUB_PASSWORD",
            "DATABASE_PASSWORD",
            "DB_PASSWORD",
            "SECRET_KEY",
            "API_KEY",
            "TOKEN",
        ]

        for var in sensitive_vars:
            env.pop(var, None)

        # 设置安全限制
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"

        return env

    def _execute_in_sandbox(self, script_path: str, env: Dict[str, str]) -> "ExecutionResult":
        """
        在沙箱中执行脚本

        Args:
            script_path: 脚本路径
            env: 环境变量

        Returns:
            ExecutionResult: 执行结果
        """
        try:
            # 使用 subprocess 执行
            process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=tempfile.mkdtemp(),
            )

            # 设置超时
            try:
                stdout, stderr = process.communicate(timeout=self._timeout)
                return ExecutionResult(
                    success=process.returncode == 0,
                    output=stdout.decode("utf-8", errors="replace"),
                    error=stderr.decode("utf-8", errors="replace"),
                    return_code=process.returncode,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                return ExecutionResult(success=False, error="Execution timed out", output="")

        except Exception as e:
            return ExecutionResult(success=False, error=str(e), output="")


@dataclass
class ExecutionResult:
    """
    执行结果数据类
    """

    success: bool = False
    output: str = ""
    error: str = ""
    return_code: int = -1
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "return_code": self.return_code,
            "execution_time": self.execution_time,
            "metadata": self.metadata,
        }


class SecurityManager:
    """
    安全管理器

    整合扫描器和沙箱，提供完整的安全管理功能。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化安全管理器

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.scanner = SkillScanner(config)
        self.sandbox = SkillSandbox(config)
        self._security_policies: Dict[str, Dict[str, Any]] = {}
        logger.info("SecurityManager initialized")

    def scan_skill(self, skill_path: str) -> SecurityReport:
        """
        扫描技能

        Args:
            skill_path: 技能路径

        Returns:
            SecurityReport: 安全报告
        """
        return self.scanner.scan(skill_path)

    def execute_skill(self, skill_path: str, entry_point: str = "main.py") -> ExecutionResult:
        """
        执行技能

        Args:
            skill_path: 技能路径
            entry_point: 入口点文件

        Returns:
            ExecutionResult: 执行结果
        """
        # 先扫描
        report = self.scan_skill(skill_path)

        # 检查是否有严重问题
        if report.has_critical_issues():
            return ExecutionResult(success=False, error="Skill has critical security issues", output="")

        # 执行技能
        script_path = os.path.join(skill_path, entry_point)
        if not os.path.exists(script_path):
            return ExecutionResult(success=False, error=f"Entry point not found: {entry_point}", output="")

        with open(script_path, "r", encoding="utf-8") as f:
            code = f.read()

        return self.sandbox.execute(code)

    def set_security_policy(self, skill_name: str, policy: Dict[str, Any]):
        """
        设置安全策略

        Args:
            skill_name: 技能名称
            policy: 安全策略
        """
        self._security_policies[skill_name] = policy
        logger.info("Set security policy for %s", skill_name)

    def get_security_policy(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        获取安全策略

        Args:
            skill_name: 技能名称

        Returns:
            Optional[Dict[str, Any]]: 安全策略
        """
        return self._security_policies.get(skill_name)

    def remove_security_policy(self, skill_name: str):
        """
        移除安全策略

        Args:
            skill_name: 技能名称
        """
        if skill_name in self._security_policies:
            del self._security_policies[skill_name]
            logger.info("Removed security policy for %s", skill_name)

    def batch_scan(self, skill_paths: List[str]) -> List[SecurityReport]:
        """
        批量扫描技能

        Args:
            skill_paths: 技能路径列表

        Returns:
            List[SecurityReport]: 安全报告列表
        """
        reports = []
        for skill_path in skill_paths:
            try:
                report = self.scan_skill(skill_path)
                reports.append(report)
            except Exception as e:
                logger.error("Failed to scan %s: %s", skill_path, e)
                reports.append(
                    SecurityReport(
                        skill_name=Path(skill_path).name,
                        issues=[SecurityIssue(level=SecurityLevel.CRITICAL, description=f"Failed to scan: {e}")],
                        overall_level=SecurityLevel.CRITICAL,
                    )
                )
        return reports
