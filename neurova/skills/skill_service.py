"""
Agent 技能服务 (SkillService)

为单个 Agent 提供技能管理功能：
- 安装/卸载技能
- 启用/禁用技能
- 技能调用
- 技能状态管理
"""

import datetime
import importlib.util
import json
from neurova.core.logger import get_logger
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class SkillService:
    """
    Agent 技能服务

    为单个 Agent 提供技能管理功能：
    - 安装/卸载技能
    - 启用/禁用技能
    - 技能调用
    - 技能状态管理
    """

    def __init__(self, agent_id: str, skills_dir: str = None):
        """
        初始化技能服务

        Args:
            agent_id: Agent ID
            skills_dir: 技能目录路径
        """
        self.agent_id = agent_id
        self.skills_dir = Path(skills_dir) if skills_dir else Path(f"data/agents/{agent_id}/skills")
        self.manifest_path = self.skills_dir / "manifest.json"
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._logger = get_logger(__name__)
        # AGENTS.md 规定：threading.RLock 用于共享状态
        # 保护 _skills / _save_manifest 在并发安装/卸载下的原子性
        # 对照：pool_service.py:70, market_importer.py:100, evolution_engine.py:99
        self._lock = threading.RLock()

        # 确保目录存在
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        # 加载已安装的技能
        self._load_skills()

        self._logger.info("SkillService initialized for agent %s", agent_id)

    def _load_skills(self) -> None:
        """加载技能清单"""
        try:
            if self.manifest_path.exists():
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    self._skills = json.load(f)
                self._logger.debug("Loaded %d skills from manifest", len(self._skills))
            else:
                self._skills = {}
                self._logger.debug("No manifest found, starting with empty skills")
        except Exception as e:
            self._logger.error("Failed to load skills: %s", e)
            self._skills = {}

    def _save_manifest(self) -> bool:
        """
        保存技能清单

        Returns:
            保存是否成功
        """
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(self._skills, f, indent=2, ensure_ascii=False)
            self._logger.debug("Saved manifest with %d skills", len(self._skills))
            return True
        except Exception as e:
            self._logger.error("Failed to save manifest: %s", e)
            return False

    def install_skill(self, skill_path: str, skill_id: str = None) -> Dict[str, Any]:
        """
        安装技能

        Args:
            skill_path: 技能路径（本地目录/zip 路径，或远程 http(s):// URL）
            skill_id: 技能ID（可选，默认从技能清单中读取）

        Returns:
            安装结果

        Notes:
            - 远程 URL（http:// 或 https://）会委托给 SkillHubClient 处理
              （SkillHubClient 已实现 HTTP 下载 + zip/tar.gz 解压 + skill.md 解析）
            - 本地路径走原解压 + copytree 流程
        """
        try:
            # 远程 URL 委托 SkillHubClient（已具备 HTTP 下载 + 解压能力）
            if isinstance(skill_path, str) and skill_path.startswith(("http://", "https://")):
                return self._install_from_url(skill_path, skill_id)

            skill_path = Path(skill_path)

            if not skill_path.exists():
                return {"success": False, "error": f"Skill path not found: {skill_path}"}

            # 如果是压缩包，先解压
            if skill_path.suffix == ".zip":
                import zipfile

                extract_dir = self.skills_dir / skill_path.stem
                with zipfile.ZipFile(skill_path, "r") as zip_ref:
                    zip_ref.extractall(extract_dir)
                skill_path = extract_dir

            # 读取技能清单
            manifest_file = skill_path / "manifest.json"
            if not manifest_file.exists():
                return {"success": False, "error": "manifest.json not found in skill directory"}

            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # 确定技能ID
            if skill_id is None:
                skill_id = manifest.get("id") or manifest.get("name")

            if not skill_id:
                return {"success": False, "error": "Skill ID not found in manifest"}

            # 复制技能到技能目录（加锁防止并发写）
            with self._lock:
                target_dir = self.skills_dir / skill_id
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                shutil.copytree(skill_path, target_dir)

                # 更新技能信息
                self._skills[skill_id] = {
                    "id": skill_id,
                    "name": manifest.get("name", skill_id),
                    "version": manifest.get("version", "0.1.0"),
                    "description": manifest.get("description", ""),
                    "enabled": True,
                    "installed_at": datetime.datetime.now().isoformat(),
                    "path": str(target_dir),
                    "manifest": manifest,
                }

                # 保存清单
                self._save_manifest()

            self._logger.info("Installed skill: %s", skill_id)
            return {"success": True, "skill_id": skill_id}

        except Exception as e:
            # 与 _install_from_url 一致：用 exception 记录完整 traceback
            self._logger.exception("Failed to install skill: %s", e)
            return {"success": False, "error": str(e)}

    def _install_from_url(self, url: str, skill_id: Optional[str]) -> Dict[str, Any]:
        """远程 URL 安装委托 SkillHubClient

        SkillHubClient 已实现完整的 HTTP 下载 + zip/tar.gz 解压 + skill.md 解析链路。
        本方法只是把 URL 转成 RemoteSkill 对象后委托，避免重复实现下载逻辑。
        """
        try:
            from neurova.skills.hub_client import RemoteSkill, SkillHubClient, SkillSource

            # 推断 source 枚举
            lower_url = url.lower()
            if "github.com" in lower_url:
                source = SkillSource.GITHUB
            elif "clawhub.com" in lower_url:
                source = SkillSource.CLAWHUB
            elif "lobehub.com" in lower_url:
                source = SkillSource.LOBEHUB
            elif "modelscope" in lower_url:
                source = SkillSource.MODELSCOPE
            else:
                source = SkillSource.GITHUB  # 默认走 github 流程

            # skill_id 作为 name（SkillHubClient 会用 name 作为目录名）
            name = skill_id or url.rsplit("/", 1)[-1].split(".")[0] or "remote-skill"
            remote_skill = RemoteSkill(
                name=name,
                source=source,
                url=url,
                download_url=url,
            )

            hub_client = SkillHubClient()
            ok = hub_client.install_skill(remote_skill)
            if ok:
                # 同步更新本地清单（让 list_skills/call_skill/uninstall_skill 能找到 URL 安装的技能）
                with self._lock:
                    self._skills[name] = {
                        "id": name,
                        "name": name,
                        "version": "remote",
                        "description": f"Installed from {url}",
                        "enabled": True,
                        "installed_at": datetime.datetime.now().isoformat(),
                        "path": str(hub_client._installed_dir / name),  # SkillHubClient 实际安装目录
                        "manifest": {"source": "remote", "url": url},
                    }
                    self._save_manifest()
                self._logger.info("Installed skill from URL: %s (skill_id=%s)", url, name)
                return {"success": True, "skill_id": name}
            return {"success": False, "error": f"SkillHubClient.install_skill returned False for {url}"}
        except Exception as e:
            self._logger.exception("Failed to install skill from URL %s: %s", url, e)
            return {"success": False, "error": str(e)}

    def uninstall_skill(self, skill_id: str) -> Dict[str, Any]:
        """
        卸载技能

        Args:
            skill_id: 技能ID

        Returns:
            卸载结果
        """
        try:
            with self._lock:
                if skill_id not in self._skills:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}

                skill_info = self._skills[skill_id]
                skill_path = Path(skill_info.get("path", ""))

                # 删除技能目录
                if skill_path.exists():
                    shutil.rmtree(skill_path)

                # 从清单中移除
                del self._skills[skill_id]

                # 保存清单
                self._save_manifest()

                self._logger.info("Uninstalled skill: %s", skill_id)
                return {"success": True}

        except Exception as e:
            self._logger.error("Failed to uninstall skill: %s", e)
            return {"success": False, "error": str(e)}

    def enable_skill(self, skill_id: str) -> Dict[str, Any]:
        """
        启用技能

        Args:
            skill_id: 技能ID

        Returns:
            操作结果
        """
        try:
            with self._lock:
                if skill_id not in self._skills:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}

                self._skills[skill_id]["enabled"] = True
                self._save_manifest()

                self._logger.info("Enabled skill: %s", skill_id)
                return {"success": True}

        except Exception as e:
            self._logger.error("Failed to enable skill: %s", e)
            return {"success": False, "error": str(e)}

    def disable_skill(self, skill_id: str) -> Dict[str, Any]:
        """
        禁用技能

        Args:
            skill_id: 技能ID

        Returns:
            操作结果
        """
        try:
            with self._lock:
                if skill_id not in self._skills:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}

                self._skills[skill_id]["enabled"] = False
                self._save_manifest()

                self._logger.info("Disabled skill: %s", skill_id)
                return {"success": True}

        except Exception as e:
            self._logger.error("Failed to disable skill: %s", e)
            return {"success": False, "error": str(e)}

    def register_auto_skill(
        self,
        skill_id: str,
        name: str,
        description: str = "",
        version: str = "0.1.0",
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        注册自动生成的技能 (无文件路径, 仅元数据持久化)

        s3 P0 #2: 桥接 AutoSkillBuilder → SkillService.
        自动技能 (从工具序列提取) 没有磁盘文件, 仅写入 manifest 元数据,
        使 GET /private 聚合 SkillService.list_skills() 时能展示自动技能.

        Args:
            skill_id: 技能 ID
            name: 技能名称
            description: 描述
            version: 版本
            config: 配置 (tool_sequence/context_template 等)

        Returns:
            True 注册成功, False 已存在 (重复)
        """
        try:
            with self._lock:
                if skill_id in self._skills:
                    self._logger.warning("register_auto_skill: skill_id=%s 已存在, 跳过", skill_id)
                    return False

                self._skills[skill_id] = {
                    "id": skill_id,
                    "name": name,
                    "version": version,
                    "description": description,
                    "enabled": True,
                    "installed_at": datetime.datetime.now().isoformat(),
                    "path": "",  # 自动技能无文件路径
                    "manifest": {
                        "source": "auto",
                        "config": config or {},
                    },
                }
                self._save_manifest()
                self._logger.info("Registered auto skill: %s", skill_id)
                return True
        except Exception as e:
            self._logger.exception("Failed to register auto skill %s: %s", skill_id, e)
            return False

    def list_skills(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """
        列出技能

        Args:
            enabled_only: 是否只返回启用的技能

        Returns:
            技能列表
        """
        try:
            with self._lock:
                skills = []
                for skill_id, skill_info in self._skills.items():
                    if enabled_only and not skill_info.get("enabled", True):
                        continue

                    skills.append(
                        {
                            "id": skill_id,
                            "name": skill_info.get("name", skill_id),
                            "version": skill_info.get("version", "0.1.0"),
                            "description": skill_info.get("description", ""),
                            "enabled": skill_info.get("enabled", True),
                            "installed_at": skill_info.get("installed_at", ""),
                        }
                    )

                return skills

        except Exception as e:
            self._logger.error("Failed to list skills: %s", e)
            return []

    def get_skill_info(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """
        获取技能信息

        Args:
            skill_id: 技能ID

        Returns:
            技能信息，如果不存在则返回None
        """
        try:
            with self._lock:
                if skill_id not in self._skills:
                    return None

                skill_info = self._skills[skill_id]
                return {
                    "id": skill_id,
                    "name": skill_info.get("name", skill_id),
                    "version": skill_info.get("version", "0.1.0"),
                    "description": skill_info.get("description", ""),
                    "enabled": skill_info.get("enabled", True),
                    "installed_at": skill_info.get("installed_at", ""),
                    "path": skill_info.get("path", ""),
                    "manifest": skill_info.get("manifest", {}),
                }

        except Exception as e:
            self._logger.error("Failed to get skill info: %s", e)
            return None

    def call_skill(self, skill_id: str, method: str = "main", **kwargs) -> Dict[str, Any]:
        """
        调用技能

        Args:
            skill_id: 技能ID
            method: 方法名
            **kwargs: 传递给技能的参数

        Returns:
            技能执行结果
        """
        try:
            with self._lock:
                if skill_id not in self._skills:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}

                skill_info = self._skills[skill_id]

                if not skill_info.get("enabled", True):
                    return {"success": False, "error": f"Skill is disabled: {skill_id}"}

                skill_path = Path(skill_info.get("path", ""))
                if not skill_path.exists():
                    return {"success": False, "error": f"Skill path not found: {skill_path}"}

                # 查找技能入口文件
                entry_file = skill_path / "main.py"
                if not entry_file.exists():
                    # 尝试查找其他入口文件
                    for py_file in skill_path.glob("*.py"):
                        if py_file.name != "__init__.py":
                            entry_file = py_file
                            break

                if not entry_file.exists():
                    return {"success": False, "error": "No entry point found for skill"}

                # 动态加载技能模块
                spec = importlib.util.spec_from_file_location(f"skill_{skill_id}", entry_file)
                if spec is None or spec.loader is None:
                    return {"success": False, "error": "Failed to load skill module"}

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 调用指定方法
                if not hasattr(module, method):
                    return {"success": False, "error": f"Method '{method}' not found in skill"}

                func = getattr(module, method)
                if not callable(func):
                    return {"success": False, "error": f"'{method}' is not callable"}

                # 执行技能
                result = func(**kwargs)

                self._logger.info("Called skill %s.%s", skill_id, method)
                return {"success": True, "result": result}

        except Exception as e:
            self._logger.error("Failed to call skill: %s", e)
            return {"success": False, "error": str(e)}
