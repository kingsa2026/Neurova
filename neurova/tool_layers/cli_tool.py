"""
CLI Tool Executor v1.0.0 — 独立的命令行工具模块

职责:
- 安全的命令行执行（风险评估 + 超时 + 脱敏）
- 命令模板化创建（参数化 CLI 工具）
- 从 ComputerUseManager.shell() 提取的独立模块

隔离层级: 与 ToolRouter/ToolEngine 平级，通过统一 Schema 注册
"""

import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import typing

logger = logging.getLogger(__name__)


class CLIToolExecutor:
    """
    CLI 工具执行器
    
    功能：
    1. 安全的命令行执行
    2. 风险评估
    3. 命令模板化
    4. 输出脱敏
    """
    
    def __init__(self):
        """初始化执行器"""
        # 风险模式
        self._risk_patterns = [
            # 极高风险模式
            (r'rm\s+-rf\s+/', "critical", 0.95),
            (r'dd\s+if=.*of=/dev/', "critical", 0.95),
            (r'mkfs\.', "critical", 0.9),
            (r'fork\s*bomb|:\(\)\{.*\}\;', "critical", 0.95),
            (r'chmod\s+-R\s+777\s+/', "critical", 0.9),
            
            # 高风险模式
            (r'sudo\s+rm\s+-rf', "high", 0.8),
            (r'rm\s+-rf\s+', "high", 0.7),
            (r'wget.*\|\s*bash', "high", 0.8),
            (r'curl.*\|\s*bash', "high", 0.8),
            (r'eval\s*\(', "high", 0.7),
            (r'exec\s*\(', "high", 0.7),
            
            # 中等风险模式
            (r'cat\s+/etc/passwd', "medium", 0.5),
            (r'find\s+/\s+', "medium", 0.4),
            (r'grep\s+-r\s+password', "medium", 0.4),
            (r'chmod\s+777', "medium", 0.5),
            (r'chown\s+.*:.*\s+/', "medium", 0.5),
            
            # 命令注入模式
            (r';\s*rm\s+-rf', "critical", 0.95),
            (r'&&\s*rm\s+-rf', "critical", 0.95),
            (r'\|\s*rm\s+-rf', "critical", 0.95),
            (r'\$\(rm\s+-rf', "critical", 0.95),
            (r'`rm\s+-rf`', "critical", 0.95),
        ]
        
        # 允许的命令（白名单）
        self._allowed_commands = [
            'ls', 'echo', 'cat', 'grep', 'find', 'wc', 'head', 'tail',
            'sort', 'uniq', 'awk', 'sed', 'tr', 'cut', 'paste',
            'mkdir', 'rmdir', 'touch', 'cp', 'mv', 'ln',
            'ps', 'top', 'df', 'du', 'free', 'uptime',
            'git', 'python', 'pip', 'node', 'npm',
            'docker', 'kubectl', 'make', 'cmake'
        ]
        
        # 敏感信息模式（用于输出脱敏）
        self._sensitive_patterns = [
            (r'password\s*[=:]\s*\S+', "password=***"),
            (r'api_key\s*[=:]\s*\S+', "api_key=***"),
            (r'secret\s*[=:]\s*\S+', "secret=***"),
            (r'token\s*[=:]\s*\S+', "token=***"),
            (r'key\s*[=:]\s*[A-Za-z0-9+/=]{20,}', "key=***"),
            (r'[A-Za-z0-9+/=]{40,}', "***"),  # Base64 编码的长字符串
        ]
        
        # CLI 工具注册表
        self._cli_tools: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    
    def assess_risk(self, command: str) -> typing.Dict[str, typing.Any]:
        """
        评估命令风险
        
        参数:
            command: 要评估的命令
            
        返回:
            风险评估结果
        """
        command_lower = command.lower().strip()
        
        # 检查风险模式
        max_risk = 0.0
        risk_level = "low"
        risk_reasons = []
        
        for pattern, level, score in self._risk_patterns:
            if re.search(pattern, command_lower):
                if score > max_risk:
                    max_risk = score
                    risk_level = level
                risk_reasons.append(f"Pattern: {pattern}")
        
        # 检查命令是否在白名单中
        command_parts = shlex.split(command)
        if command_parts:
            base_command = command_parts[0]
            if base_command not in self._allowed_commands:
                # 未知命令，增加风险
                max_risk = max(max_risk, 0.3)
                if risk_level == "low":
                    risk_level = "medium"
                risk_reasons.append(f"Unknown command: {base_command}")
        
        # 检查特殊字符
        dangerous_chars = ['|', '&', ';', '$', '`', '(', ')', '{', '}']
        for char in dangerous_chars:
            if char in command:
                # 增加风险
                max_risk = min(1.0, max_risk + 0.1)
                risk_reasons.append(f"Dangerous character: {char}")
        
        return {
            "level": risk_level,
            "score": min(1.0, max_risk),
            "reasons": risk_reasons,
            "allowed": max_risk < 0.7  # 风险分数低于0.7才允许执行
        }
    
    def execute_sync(
        self, 
        command: str, 
        timeout: float = 30.0,
        cwd: typing.Optional[str] = None,
        env: typing.Optional[typing.Dict[str, str]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        同步执行命令
        
        参数:
            command: 要执行的命令
            timeout: 超时时间（秒）
            cwd: 工作目录
            env: 环境变量
            
        返回:
            执行结果
        """
        # 风险评估
        risk = self.assess_risk(command)
        if not risk["allowed"]:
            return {
                "success": False,
                "output": "",
                "error": f"Command blocked due to high risk: {risk['level']}",
                "return_code": -1,
                "risk": risk
            }
        
        # 清理命令
        cleaned_command = self._clean_command(command)
        
        try:
            # 执行命令
            result = subprocess.run(
                cleaned_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env
            )
            
            # 脱敏输出
            sanitized_stdout = self._sanitize_output(result.stdout)
            sanitized_stderr = self._sanitize_output(result.stderr)
            
            return {
                "success": result.returncode == 0,
                "output": sanitized_stdout,
                "error": sanitized_stderr,
                "return_code": result.returncode,
                "risk": risk
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"Command timed out after {timeout} seconds",
                "return_code": -1,
                "risk": risk
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "return_code": -1,
                "risk": risk
            }
    
    def create_cli_tool(
        self,
        name: str,
        command: str,
        parameters: typing.Dict[str, typing.Any],
        description: str = "",
        timeout: float = 30.0
    ) -> typing.Dict[str, typing.Any]:
        """
        创建 CLI 工具
        
        参数:
            name: 工具名称
            command: 命令模板（使用 {param} 作为参数占位符）
            parameters: 参数定义
            description: 工具描述
            timeout: 默认超时时间
            
        返回:
            工具定义
        """
        tool = {
            "name": name,
            "command": command,
            "parameters": parameters,
            "description": description,
            "timeout": timeout,
            "created_at": time.time()
        }
        
        # 注册工具
        self._cli_tools[name] = tool
        
        logger.info(f"Created CLI tool: {name}")
        return tool
    
    def execute_cli_tool(
        self,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        timeout: typing.Optional[float] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        执行 CLI 工具
        
        参数:
            tool_name: 工具名称
            params: 参数值
            timeout: 超时时间（可选）
            
        返回:
            执行结果
        """
        # 检查工具是否存在
        if tool_name not in self._cli_tools:
            return {
                "success": False,
                "output": "",
                "error": f"CLI tool '{tool_name}' not found",
                "return_code": -1
            }
        
        tool = self._cli_tools[tool_name]
        
        # 验证参数
        validation_error = self._validate_params(tool, params)
        if validation_error:
            return {
                "success": False,
                "output": "",
                "error": validation_error,
                "return_code": -1
            }
        
        # 替换命令模板中的参数
        command = tool["command"]
        for param_name, param_value in params.items():
            command = command.replace(f"{{{param_name}}}", str(param_value))
        
        # 执行命令
        return self.execute_sync(
            command,
            timeout=timeout or tool.get("timeout", 30.0)
        )
    
    def _clean_command(self, command: str) -> str:
        """
        清理命令
        
        参数:
            command: 原始命令
            
        返回:
            清理后的命令
        """
        # 移除多余空格
        command = ' '.join(command.split())
        
        # 使用 shlex 分割和重新组合（处理引号）
        try:
            parts = shlex.split(command)
            return ' '.join(parts)
        except ValueError:
            # 如果 shlex 解析失败，返回原始命令
            return command
    
    def _sanitize_output(self, output: str) -> str:
        """
        脱敏输出
        
        参数:
            output: 原始输出
            
        返回:
            脱敏后的输出
        """
        if not output:
            return output
        
        sanitized = output
        
        # 应用脱敏模式
        for pattern, replacement in self._sensitive_patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
        
        return sanitized
    
    def _validate_params(
        self, 
        tool: typing.Dict[str, typing.Any], 
        params: typing.Dict[str, typing.Any]
    ) -> typing.Optional[str]:
        """
        验证参数
        
        参数:
            tool: 工具定义
            params: 参数值
            
        返回:
            错误信息，如果验证通过则返回 None
        """
        parameters = tool.get("parameters", {})
        
        # 检查必需参数
        for param_name, param_def in parameters.items():
            if param_def.get("required", False) and param_name not in params:
                return f"Required parameter '{param_name}' is missing"
        
        # 检查参数类型
        for param_name, param_value in params.items():
            if param_name not in parameters:
                continue
            
            param_def = parameters[param_name]
            param_type = param_def.get("type", "string")
            
            # 类型检查
            if param_type == "integer":
                if not isinstance(param_value, int):
                    try:
                        int(param_value)
                    except (ValueError, TypeError):
                        return f"Parameter '{param_name}' must be an integer"
                
                # 范围检查
                if "minimum" in param_def and param_value < param_def["minimum"]:
                    return f"Parameter '{param_name}' must be >= {param_def['minimum']}"
                if "maximum" in param_def and param_value > param_def["maximum"]:
                    return f"Parameter '{param_name}' must be <= {param_def['maximum']}"
            
            elif param_type == "number":
                if not isinstance(param_value, (int, float)):
                    try:
                        float(param_value)
                    except (ValueError, TypeError):
                        return f"Parameter '{param_name}' must be a number"
            
            elif param_type == "string":
                if not isinstance(param_value, str):
                    return f"Parameter '{param_name}' must be a string"
                
                # 模式检查
                if "pattern" in param_def:
                    if not re.match(param_def["pattern"], param_value):
                        return f"Parameter '{param_name}' does not match pattern: {param_def['pattern']}"
        
        return None
    
    def list_cli_tools(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        列出所有 CLI 工具
        
        返回:
            工具列表
        """
        return list(self._cli_tools.values())