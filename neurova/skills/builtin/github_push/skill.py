"""
GitHub Push Skill - Neurova GitHub 推送技能

封装完整的 Git 操作流程，支持：
1. 检查 Git 状态
2. 添加文件
3. 提交更改
4. 推送到 main 分支（支持直接推送而非合并）

使用方法：
- action: status, add, commit, push, full_push
- message: 提交信息（仅 commit 操作需要）
- files: 要添加的文件列表（仅 add 操作需要，默认为所有文件）
"""

import asyncio
import subprocess
import logging
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
import time

# 动态导入 Skill 类，避免包和模块冲突
import sys
import importlib.util

# 直接导入模块文件
skill_system_module_path = Path(__file__).parent.parent.parent.parent / 'skill_system.py'
if skill_system_module_path.exists():
    # 动态加载模块
    spec = importlib.util.spec_from_file_location('neurova.skill_system_module', skill_system_module_path)
    skill_system_module = importlib.util.module_from_spec(spec)
    sys.modules['neurova.skill_system_module'] = skill_system_module
    spec.loader.exec_module(skill_system_module)
    
    Skill = skill_system_module.Skill
    SkillResult = skill_system_module.SkillResult
    SkillStatus = skill_system_module.SkillStatus
else:
    # 如果模块文件不存在，从包导入
    from neurova.skill_system import Skill, SkillResult, SkillStatus

class GitHubPushSkill(Skill):
    """GitHub 推送技能"""

    def __init__(self):
        super().__init__("github_push", "GitHub 推送技能 - 封装完整的 Git 操作流程")
        self.logger = logging.getLogger(__name__)
        self.repo_path = Path(".")  # 默认当前目录

    async def execute(self, params: Dict[str, Any], context: Optional[Dict] = None) -> SkillResult:
        """
        执行 GitHub 推送操作

        Args:
            params: 操作参数
            context: 上下文信息

        Returns:
            SkillResult: 执行结果
        """
        start_time = time.time()

        try:
            action = params.get("action", "full_push")
            message = params.get("message", "Update from Neurova GitHub Push Skill")
            files = params.get("files", None)
            push_to_main = params.get("push_to_main", True)
            branch = params.get("branch", None)

            # 更新仓库路径
            if "repo_path" in params:
                self.repo_path = Path(params["repo_path"])

            if action == "status":
                result = await self._get_status()
            elif action == "add":
                result = await self._add_files(files)
            elif action == "commit":
                result = await self._commit_changes(message)
            elif action == "push":
                result = await self._push_changes(push_to_main, branch)
            elif action == "full_push":
                result = await self._full_push_workflow(message, push_to_main, branch)
            else:
                return SkillResult(
                    success=False,
                    error=f"未知操作: {action}",
                    execution_time=time.time() - start_time,
                )

            result.execution_time = time.time() - start_time
            return result

        except Exception as e:
            self.logger.error(f"GitHub 推送操作失败: {e}")
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    async def _run_git_command(self, command: List[str], check_output: bool = True) -> Dict[str, Any]:
        """执行 Git 命令"""
        try:
            self.logger.info(f"执行 Git 命令: {' '.join(command)}")

            # 使用 asyncio.create_subprocess_exec 在异步环境中执行
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path)
            )

            stdout, stderr = await process.communicate()

            result = {
                "command": ' '.join(command),
                "returncode": process.returncode,
                "stdout": stdout.decode('utf-8', errors='ignore').strip(),
                "stderr": stderr.decode('utf-8', errors='ignore').strip(),
                "success": process.returncode == 0,
            }

            if check_output and not result["success"]:
                self.logger.warning(f"Git 命令执行失败: {result['stderr']}")

            return result

        except Exception as e:
            self.logger.error(f"执行 Git 命令异常: {e}")
            return {
                "command": ' '.join(command),
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False,
            }

    async def _get_status(self) -> SkillResult:
        """获取 Git 状态"""
        result = await self._run_git_command(["git", "status", "--porcelain"])

        if result["success"]:
            # 解析状态输出
            lines = result["stdout"].split('\n') if result["stdout"] else []
            files = []
            for line in lines:
                if line.strip():
                    # 状态码在前两个字符，文件名在第三个字符后
                    status_code = line[:2].strip()
                    file_path = line[3:].strip() if len(line) > 3 else ""
                    files.append({
                        "status": status_code,
                        "file": file_path
                    })

            return SkillResult(
                success=True,
                data={
                    "files": files,
                    "total_files": len(files),
                    "clean": len(files) == 0,
                    "raw_output": result["stdout"]
                },
                execution_time=0.0,
            )
        else:
            return SkillResult(
                success=False,
                error=f"获取状态失败: {result['stderr']}",
                execution_time=0.0,
            )

    async def _add_files(self, files: Optional[List[str]] = None) -> SkillResult:
        """添加文件到暂存区"""
        if files is None:
            # 添加所有文件
            command = ["git", "add", "."]
        else:
            # 添加指定文件
            command = ["git", "add"] + files

        result = await self._run_git_command(command)

        if result["success"]:
            # 检查暂存区状态
            status_result = await self._run_git_command(["git", "diff", "--cached", "--name-only"])
            staged_files = status_result["stdout"].split('\n') if status_result["stdout"] else []
            staged_files = [f for f in staged_files if f.strip()]

            return SkillResult(
                success=True,
                data={
                    "staged_files": staged_files,
                    "staged_count": len(staged_files),
                    "message": f"成功添加 {len(staged_files)} 个文件到暂存区"
                },
                execution_time=0.0,
            )
        else:
            return SkillResult(
                success=False,
                error=f"添加文件失败: {result['stderr']}",
                execution_time=0.0,
            )

    async def _commit_changes(self, message: str) -> SkillResult:
        """提交更改"""
        # 检查是否有暂存的更改
        status_result = await self._run_git_command(["git", "diff", "--cached", "--name-only"])
        staged_files = status_result["stdout"].split('\n') if status_result["stdout"] else []
        staged_files = [f for f in staged_files if f.strip()]

        if not staged_files:
            return SkillResult(
                success=False,
                error="没有暂存的更改可提交",
                execution_time=0.0,
            )

        # 执行提交
        result = await self._run_git_command(["git", "commit", "-m", message])

        if result["success"]:
            # 获取提交哈希
            hash_result = await self._run_git_command(["git", "rev-parse", "HEAD"])
            commit_hash = hash_result["stdout"] if hash_result["success"] else "unknown"

            return SkillResult(
                success=True,
                data={
                    "commit_hash": commit_hash,
                    "message": message,
                    "files_committed": len(staged_files),
                    "files": staged_files,
                    "output": result["stdout"]
                },
                execution_time=0.0,
            )
        else:
            return SkillResult(
                success=False,
                error=f"提交失败: {result['stderr']}",
                execution_time=0.0,
            )

    async def _push_changes(self, push_to_main: bool = True, branch: Optional[str] = None) -> SkillResult:
        """推送更改到远程仓库"""
        # 首先获取当前分支
        branch_result = await self._run_git_command(["git", "branch", "--show-current"])
        current_branch = branch_result["stdout"] if branch_result["success"] else "main"

        if branch:
            current_branch = branch

        # 检查远程仓库配置
        remote_result = await self._run_git_command(["git", "remote", "-v"])
        if not remote_result["success"] or not remote_result["stdout"]:
            return SkillResult(
                success=False,
                error="未配置远程仓库",
                execution_time=0.0,
            )

        # 执行推送
        if push_to_main and current_branch != "main":
            # 直接推送到 main 分支（不合并）
            push_command = ["git", "push", "origin", f"{current_branch}:main"]
        else:
            # 推送到当前分支
            push_command = ["git", "push", "origin", current_branch]

        result = await self._run_git_command(push_command)

        if result["success"]:
            return SkillResult(
                success=True,
                data={
                    "pushed_to": "main" if push_to_main and current_branch != "main" else current_branch,
                    "branch": current_branch,
                    "output": result["stdout"],
                    "message": f"成功推送到远程仓库"
                },
                execution_time=0.0,
            )
        else:
            return SkillResult(
                success=False,
                error=f"推送失败: {result['stderr']}",
                execution_time=0.0,
            )

    async def _full_push_workflow(self, message: str, push_to_main: bool = True, branch: Optional[str] = None) -> SkillResult:
        """完整推送工作流：状态 → 添加 → 提交 → 推送"""
        workflow_steps = []
        total_start_time = time.time()

        try:
            # 步骤1: 获取状态
            self.logger.info("步骤1: 获取 Git 状态")
            status_result = await self._get_status()
            workflow_steps.append({
                "step": "status",
                "success": status_result.success,
                "data": status_result.data if status_result.success else None,
                "error": status_result.error if not status_result.success else None,
            })

            if not status_result.success:
                return SkillResult(
                    success=False,
                    error=f"获取状态失败: {status_result.error}",
                    metadata={"workflow_steps": workflow_steps},
                    execution_time=time.time() - total_start_time,
                )

            # 如果没有更改，直接返回
            if status_result.data.get("clean", True):
                return SkillResult(
                    success=True,
                    data={
                        "message": "工作区干净，无需推送",
                        "workflow_steps": workflow_steps
                    },
                    metadata={"workflow_steps": workflow_steps},
                    execution_time=time.time() - total_start_time,
                )

            # 步骤2: 添加文件
            self.logger.info("步骤2: 添加文件到暂存区")
            add_result = await self._add_files()
            workflow_steps.append({
                "step": "add",
                "success": add_result.success,
                "data": add_result.data if add_result.success else None,
                "error": add_result.error if not add_result.success else None,
            })

            if not add_result.success:
                return SkillResult(
                    success=False,
                    error=f"添加文件失败: {add_result.error}",
                    metadata={"workflow_steps": workflow_steps},
                    execution_time=time.time() - total_start_time,
                )

            # 步骤3: 提交更改
            self.logger.info("步骤3: 提交更改")
            commit_result = await self._commit_changes(message)
            workflow_steps.append({
                "step": "commit",
                "success": commit_result.success,
                "data": commit_result.data if commit_result.success else None,
                "error": commit_result.error if not commit_result.success else None,
            })

            if not commit_result.success:
                return SkillResult(
                    success=False,
                    error=f"提交失败: {commit_result.error}",
                    metadata={"workflow_steps": workflow_steps},
                    execution_time=time.time() - total_start_time,
                )

            # 步骤4: 推送更改
            self.logger.info("步骤4: 推送到远程仓库")
            push_result = await self._push_changes(push_to_main, branch)
            workflow_steps.append({
                "step": "push",
                "success": push_result.success,
                "data": push_result.data if push_result.success else None,
                "error": push_result.error if not push_result.success else None,
            })

            if not push_result.success:
                return SkillResult(
                    success=False,
                    error=f"推送失败: {push_result.error}",
                    metadata={"workflow_steps": workflow_steps},
                    execution_time=time.time() - total_start_time,
                )

            # 所有步骤成功
            return SkillResult(
                success=True,
                data={
                    "message": "完整推送工作流成功完成",
                    "workflow_steps": workflow_steps,
                    "commit_hash": commit_result.data.get("commit_hash"),
                    "pushed_to": push_result.data.get("pushed_to"),
                    "files_committed": commit_result.data.get("files_committed"),
                },
                metadata={"workflow_steps": workflow_steps},
                execution_time=time.time() - total_start_time,
            )

        except Exception as e:
            self.logger.error(f"完整推送工作流异常: {e}")
            return SkillResult(
                success=False,
                error=f"工作流异常: {str(e)}",
                metadata={"workflow_steps": workflow_steps},
                execution_time=time.time() - total_start_time,
            )

    def get_info(self):
        """获取技能信息"""
        info = super().get_info()
        info.description = "GitHub 推送技能 - 封装完整的 Git 操作流程，支持状态检查、文件添加、提交和推送"
        info.tags = ["git", "github", "push", "version-control"]
        info.parameters = {
            "action": {
                "type": "string",
                "description": "操作类型：status, add, commit, push, full_push",
                "required": False,
                "default": "full_push"
            },
            "message": {
                "type": "string",
                "description": "提交信息（commit 操作需要）",
                "required": False,
                "default": "Update from Neurova GitHub Push Skill"
            },
            "files": {
                "type": "array",
                "description": "要添加的文件列表（add 操作需要，默认为所有文件）",
                "required": False,
            },
            "push_to_main": {
                "type": "boolean",
                "description": "是否直接推送到 main 分支",
                "required": False,
                "default": True
            },
            "branch": {
                "type": "string",
                "description": "指定分支（可选）",
                "required": False,
            },
            "repo_path": {
                "type": "string",
                "description": "仓库路径（默认为当前目录）",
                "required": False,
            }
        }
        info.required_params = []
        return info


def create_github_push_skill() -> GitHubPushSkill:
    """创建 GitHub 推送技能实例"""
    return GitHubPushSkill()


# 便捷函数：一键推送
async def push_to_github(message: str = "Update from Neurova", 
                        push_to_main: bool = True,
                        repo_path: str = ".") -> SkillResult:
    """
    便捷函数：一键推送到 GitHub
    
    Args:
        message: 提交信息
        push_to_main: 是否推送到 main 分支
        repo_path: 仓库路径
        
    Returns:
        SkillResult: 执行结果
    """
    skill = create_github_push_skill()
    params = {
        "action": "full_push",
        "message": message,
        "push_to_main": push_to_main,
        "repo_path": repo_path
    }
    return await skill.execute(params)


# 如果直接运行此文件，演示技能使用
if __name__ == "__main__":
    import asyncio

    async def demo():
        """演示技能使用"""
        print("=== GitHub Push Skill 演示 ===")

        # 创建技能实例
        skill = create_github_push_skill()
        print(f"技能名称: {skill.name}")
        print(f"技能描述: {skill.description}")

        # 显示技能信息
        info = skill.get_info()
        print(f"技能标签: {info.tags}")
        print(f"参数列表: {list(info.parameters.keys())}")

        # 示例：获取状态
        print("\n--- 获取 Git 状态 ---")
        status_result = await skill.execute({"action": "status"})
        if status_result.success:
            print(f"工作区状态: {'干净' if status_result.data.get('clean') else '有更改'}")
            print(f"更改文件数: {status_result.data.get('total_files', 0)}")
        else:
            print(f"错误: {status_result.error}")

        print("\n=== 演示完成 ===")

    # 运行演示
    asyncio.run(demo())