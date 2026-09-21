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
import re
from neurova.security.safe_archive import safe_extract_zip
from neurova.core.logger import get_logger
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.data_root import get_data_root

# 安装技能 ID 白名单：字母数字开头，仅含 . _ - 与字母数字（拒路径穿越/绝对/相对点段）
_SAFE_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")

# ── 技能质量漏斗归因──

def compute_skill_funnel_update(
    entries: Optional[List[Dict[str, Any]]], task_completed: bool
) -> Dict[str, Dict[str, int]]:
    """轮次派发账本 → {skill_id: {selections/applications/completions/fallbacks}} 增量。

    不得记功 / store.py:1587-1659 completed/fallback 判定）：
    - selection = 该技能本轮被 LLM 派发一次（治理预检放行后进入 execute_skill_tool）
    - application = 真正进入执行（查无此技能/未初始化 = 有 selection 无 application）
    - completion = application ∧ 执行成功 ∧ 本轮任务完成
    - fallback = application ∧ ¬completion——**执行失败但本轮靠其它工具兜底
      完成时不得给技能记 completion**，这是本函数存在的意义（防漏斗被污染）
    """
    updates: Dict[str, Dict[str, int]] = {}
    for entry in entries or []:
        skill_id = str(entry.get("skill_id") or "")
        if not skill_id:
            continue
        delta = updates.setdefault(
            skill_id,
            {"selections": 0, "applications": 0, "completions": 0, "fallbacks": 0},
        )
        delta["selections"] += 1
        if not entry.get("applied"):
            continue
        delta["applications"] += 1
        if entry.get("ok") and task_completed:
            delta["completions"] += 1
        else:
            delta["fallbacks"] += 1
    return updates

# ── 信任生命周期──

def compute_trust_transition(
    state: str, outcome: str, successes_since_failure: int, min_successes: int = 2
) -> tuple:
    """provisional↔trusted 迁移纯函数。

failure 即刻降级并清零计数；晋升须
    successes_since_failure ≥ min_successes 个**独立任务**观测；trusted
    成功不计数（无意义）。未知态按保守 provisional 处理。
    """
    state = state if state in ("provisional", "trusted") else "provisional"
    count = max(0, int(successes_since_failure or 0))
    if outcome == "failure":
        return "provisional", 0
    if outcome != "success":
        return state, count
    if state == "trusted":
        return "trusted", 0
    count += 1
    return ("trusted", 0) if count >= max(1, int(min_successes)) else ("provisional", count)

def compute_trust_observations(
    entries: Optional[List[Dict[str, Any]]], task_completed: bool
) -> Dict[str, str]:
    """从派发账本派生本轮每技能的信任观测（一票制：每任务一次）。

    保守规则：同回合混合成败记 failure（晋升证据必须干净）；技能执行成功
    但任务未完成同样记 failure——与 P0-1 fallback 归因同源，不为兜底/未
    完成的回合记功。只有 selection 无 application 不投票。
    """
    seen: Dict[str, Dict[str, bool]] = {}
    for entry in entries or []:
        skill_id = str(entry.get("skill_id") or "")
        if not skill_id or not entry.get("applied"):
            continue
        agg = seen.setdefault(skill_id, {"ok": True})
        if not entry.get("ok"):
            agg["ok"] = False
    return {
        skill_id: ("success" if agg["ok"] and task_completed else "failure")
        for skill_id, agg in seen.items()
    }

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
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            self.skills_dir = get_data_root() / "agents" / str(agent_id) / "skills"
        self.manifest_path = self.skills_dir / "manifest.json"
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._logger = get_logger(__name__)
        # AGENTS.md 规定：threading.RLock 用于共享状态
        # 保护 _skills / _save_manifest 在并发安装/卸载下的原子性
        # 对照：pool_service.py:70, market_importer.py:100, evolution_engine.py:99
        from neurova.skills.creation_governance import EvidenceStore

        self.creation_evidence = EvidenceStore(self.skills_dir, agent_id)
        self._lock = self.creation_evidence.lock

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

 P1-5：tmp + os.replace 原子替换——原 open 先截断，
        写一半崩溃 = manifest 清零（providers-config-loss 事故同型病灶）。
        失败时旧文件内容保持完整（原子性即此意）。

        Returns:
            保存是否成功
        """
        try:
            import os
            import tempfile

            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.skills_dir), prefix="manifest_", suffix=".tmp"
            )
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    json.dump(self._skills, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.manifest_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._logger.debug("Saved manifest with %d skills", len(self._skills))
            return True
        except Exception as e:
            self._logger.error("Failed to save manifest: %s", e)
            return False

    # ── 别名登记（P1 统一指纹）：ID ⇒ 规范 ID 的落盘映射 ──

    _ALIASES_KEY = "_skill_aliases"

    def _aliases(self) -> Dict[str, str]:
        raw = self._skills.get(self._ALIASES_KEY)
        return dict(raw) if isinstance(raw, dict) else {}

    def register_skill_alias(self, skill_id: str, alias: str, persist: bool = True) -> bool:
        """把 alias 收敛到 canonical skill_id——重复封装漏洞的收口点。

        三条写入臂各有命名方案（skill_<md5> / genetic_<tools> / synth_*）；
        单靠指纹去重仍会因"先注册的那个 ID"造成同序列多入口。别名表让
        任一命名方案都能解析到同一技能，且注册经此表即便指纹判定失手
        （历史库）也不会再写第二条。
        """
        alias = str(alias or "")
        skill_id = str(skill_id or "")
        if not alias or not skill_id or alias == skill_id:
            return False
        with self._lock:
            aliases = dict(self._aliases())
            if aliases.get(alias) == skill_id:
                return True
            aliases[alias] = skill_id
            self._skills[self._ALIASES_KEY] = aliases
            if persist and not self._save_manifest():
                aliases.pop(alias, None)
                self._skills[self._ALIASES_KEY] = aliases
                return False
            return True

    def _entry(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """按技能 ID 取条目（含别名解析）；别名表本身不是技能，一律视为不存在。"""
        sid = str(skill_id or "")
        if sid == self._ALIASES_KEY:
            return None
        if sid not in self._skills:
            sid = self.resolve_skill_alias(sid)
        if sid == self._ALIASES_KEY:
            return None
        entry = self._skills.get(sid)
        return entry if isinstance(entry, dict) else None

    def resolve_skill_alias(self, skill_id: str) -> str:
        """别名解析到规范 ID；无别名时原样返回。"""
        aliases = self._aliases()
        seen = set()
        current = str(skill_id or "")
        while current in aliases and current not in seen:
            seen.add(current)
            current = str(aliases[current])
        return current

    def _creation_decision(self, manifest, automatic=False, db=None, alias_ids=(), exclude_ids=()):
        """重复判定：ID / 别名命中，或**业务身份**（结构+意图）与既有条目相同。

        exclude_ids：调用方声明"这些 ID 属更新语义"（同名重装/重报），不参与
        指纹判重——否则覆盖式重装会被自己的旧条目判成重复而拒绝。
        """
        from neurova.skills.creation_governance import manifest_fingerprint

        key = manifest_fingerprint(manifest)
        config = manifest.get("config") or {}
        if automatic and not self.creation_evidence.eligible(
            config.get("tool_sequence"), config.get("task_purpose")
            or config.get("context_template") or manifest.get("description", ""), db
        ):
            return {"success": False, "error": "需要至少三个独立真实成功任务证据", "code": "insufficient_evidence"}
        # 命名方案归一：请求 ID 与全部别名先解析到规范 ID，再判重。
        requested = str(manifest.get("id") or "")
        lookup_ids = {requested, self.resolve_skill_alias(requested)}
        lookup_ids.update(self.resolve_skill_alias(str(a)) for a in alias_ids)
        # exclude_ids：声明"这些 ID 属更新语义"（同名重装/重报）——既跳过 ID
        # 循环（因为同名不是"另一个入口"），也跳过业务身份判重（整份 manifest
        # 就是那条目的的升级版，判重等于自己拦自己）。
        excluded = {str(x) for x in exclude_ids} | {requested}
        for skill_id, entry in self._skills.items():
            if skill_id == self._ALIASES_KEY or skill_id in excluded or not isinstance(entry, dict):
                continue
            # 同名 ID 解析到既有条目：无论指纹是否一致都按重复处理——同名不同
            # 序列是"ID 冲突"，由 create_automatic_skill 的 ID 兜底分支报错，
            # 不能在这里悄悄放行成第二条（改名判重的核心入口）。
            if skill_id in lookup_ids and skill_id not in excluded:
                return {"success": True, "duplicate": True, "skill_id": skill_id}
        # 判重只在「不同入口 ID」之间做（requested 已在上面查过，跳过它，
        # 保持"传 ID 即认 ID"的既有语义不变；同名重装/重报是**更新**而非重复）。
        if key:
            for skill_id, entry in self._skills.items():
                if skill_id == self._ALIASES_KEY or skill_id in excluded or not isinstance(entry, dict):
                    continue
                if skill_id == requested:
                    continue
                existing = {**entry, **(entry.get("manifest") or {})}
                if manifest_fingerprint(existing) == key:
                    return {"success": True, "duplicate": True, "skill_id": skill_id}
        return None

    def _duplicate_skill_id(self, manifest, exclude_ids=()):
        """按**结构身份**在库内找重复条目，返回既有规范 ID 或 None（P1 统一指纹）。

        结构身份不含业务意图——"同一工具序列不得被封装两次"是结构问题，
        业务身份（fingerprint）留给 `_creation_decision` 判"同序列不同业务"，
        两者各管一段：结构查重 → 收敛别名；业务判重 → 拦重复注册。
        """
        from neurova.skills.creation_governance import manifest_structure

        structure = manifest_structure(manifest)
        if not structure:
            return None
        exclude = {str(x) for x in exclude_ids} | {self._ALIASES_KEY}
        for skill_id, entry in self._skills.items():
            if skill_id in exclude or not isinstance(entry, dict):
                continue
            existing = {**entry, **(entry.get("manifest") or {})}
            if manifest_structure(existing) == structure:
                return skill_id
        return None

    def create_automatic_skill(self, skill_id, name, description, config, version="1.0.0",
                               alias_ids=(), human_approved: bool = False):
        aliases = tuple(str(a) for a in (alias_ids or ()) if str(a))
        manifest = {"id": skill_id, "name": name, "description": description, "config": config}
        from neurova.skills.creation_governance import manifest_fingerprint

        key = manifest_fingerprint(manifest)
        with self.creation_evidence.transaction() as db:
            self._load_skills()
            # requested（含别名）属"更新语义"：同名重报由下方 ID 分支裁决
            # （ID 冲突报错 / 同名同身份按重复返回），指纹判重只管别的入口 ID。
            decision = self._creation_decision(
                manifest, automatic=True, db=db, alias_ids=aliases,
                exclude_ids=(str(skill_id), *aliases))
            if decision is None:
                canonical = self._duplicate_skill_id(manifest, exclude_ids=(str(skill_id), *aliases))
                if canonical:
                    # 结构身份已存在（换 ID / 换名字的重复封装）：收敛为一条，
                    # 不再新写——这正是"同一技能被封装成两条"的堵漏点。
                    decision = {"success": True, "duplicate": True, "skill_id": canonical}
                    for alias in (str(skill_id), *aliases):
                        self.register_skill_alias(canonical, alias)
            if decision:
                if decision.get("duplicate"):
                    for alias in (str(skill_id), *aliases):
                        self.register_skill_alias(decision["skill_id"], alias)
                return decision
            if skill_id in self._skills:
                # 同名条目：指纹判重刻意跳过了 requested（更新语义），此处按
                # "同身份=已存在（重复）／异身份=ID 冲突"如实裁决——否则同一条
                # 技能反复上报会被报成 ID 冲突，调用方读不到"已存在"信号。
                from neurova.skills.creation_governance import manifest_fingerprint

                existing = {**self._skills[skill_id], **(self._skills[skill_id].get("manifest") or {})}
                if key and manifest_fingerprint(existing) == key:
                    return {"success": True, "duplicate": True, "skill_id": skill_id}
                return {"success": False, "error": "Skill ID already exists with different steps",
                        "code": "id_conflict"}
            ok = self._register_metadata(skill_id, name, description, version, config,
                                         human_approved=human_approved)
            return {"success": ok, "skill_id": skill_id, **({} if ok else {"error": "Persistence failed"})}

    def install_skill(
        self,
        skill_path: str,
        skill_id: str = None,
        pool_type: str = "agent",
        owner_user_id: str = "",
        human_approved: bool = False,
    ) -> Dict[str, Any]:
        """
        安装技能

        Args:
            skill_path: 技能路径（本地目录/zip 路径，或远程 http(s):// URL）
            skill_id: 技能ID（可选，默认从技能清单中读取）
            human_approved: 该次安装由人显式批准（工单 010）。`source` 为
                auto/synthesized/llm_created 时默认按"自动行为"要求三个独立真实
                成功证据；人类刚批准的提案不是自动行为，若不区分则人工通道
                按构造走不通。判重、路径穿越与安全扫描不受此参数影响。

        Returns:
            安装结果

        Notes:
            - 远程 URL（http:// 或 https://）会委托给 SkillHubClient 处理
              （SkillHubClient 已实现 HTTP 下载 + zip/tar.gz 解压 + skill.md 解析，
              内含安装扫描门）
            - 本地目录/zip 走"独立解压 → copytree 到 .incoming 暂存 → P0-4 安装门
              → 原子交换"流程：被拦不碰旧版本、不落清单；扫描器故障 fail-closed。
              （修复预存根因 bug：原 zip 流程解压目录与 target 同路径，
              rmtree(target) 先删源 → copytree FileNotFoundError，zip 安装从未成功过。）
        """
        import time as _time
        import tempfile

        try:
            # 远程 URL 委托 SkillHubClient（已具备 HTTP 下载 + 解压能力）
            if isinstance(skill_path, str) and skill_path.startswith(("http://", "https://")):
                return self._install_from_url(skill_path, skill_id)

            skill_path = Path(skill_path)

            if not skill_path.exists():
                return {"success": False, "error": f"Skill path not found: {skill_path}"}

            _extract_tmp: Optional[Path] = None
            try:
                # 如果是压缩包，先解压到独立临时目录（不与安装目录同路径）
                if skill_path.suffix == ".zip":
                    _extract_tmp = Path(tempfile.mkdtemp(prefix="neurova_skill_zip_"))
                    # 安全审计 L3: 原 extractall 无成员校验 → Zip Slip
                    safe_extract_zip(skill_path, _extract_tmp)
                    skill_path = _extract_tmp

                # 读取技能清单
                manifest_file = skill_path / "manifest.json"
                if not manifest_file.exists():
                    return {"success": False, "error": "manifest.json not found in skill directory"}

                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                # 确定技能ID
                if skill_id is None:
                    skill_id = manifest.get("id") or manifest.get("name")
                # 判重口径对齐：manifest 自报的 ID 与调用方传入的 ID 都算"同名"。
                # （replacement 快路径用 manifest["id"] 回查 _prev；两者不一致时
                # 指纹判重会把重装误判成"别的 ID 声明了同一身份"而拒绝。）
                manifest_id = manifest.get("id") or manifest.get("name") or skill_id

                if not skill_id:
                    return {"success": False, "error": "Skill ID not found in manifest"}

                # 安装 ID 路径守卫：skill_id 直接拼成 skills_dir 子目录名，
                # 恶意包 manifest 自含 "../../x" 或 "C:\..." 会越出技能目录。
                # 与用户键 _KEY_RE 同纪律（目录名安全 = 路径注入第一道闸）。
                if not _SAFE_SKILL_ID_RE.match(str(skill_id)):
                    return {
                        "success": False,
                        "error": f"非法技能 ID（须字母数字开头且不含路径字符）: {skill_id!r}",
                    }

                # 复制技能到技能目录（加锁防止并发写）
                with self.creation_evidence.transaction() as db:
                    self._load_skills()
                    # 安装通道：同名即覆盖式重装（一等语义），指纹判重不适用——
                    # 传 requested_id 让判重只认"别的 ID 声明了同一身份"（跳转），
                    # 同名条目走下方 replacement 快路径保留账本与版本链。
                    decision = self._creation_decision(
                        manifest, automatic=manifest.get("source") in {"auto", "synthesized", "llm_created"}
                        and not human_approved,
                        db=db, exclude_ids=(str(skill_id), str(manifest_id)))
                    if decision is None and str(skill_id) in self._skills:
                        # 同名且**同一结构身份** → 同内容的重复安装：如实回报
                        # duplicate（账本/版本链不动）。服务端判重口径是工具序列
                        # 及其参数，版本/名称/描述变化都属同一技能（升级/更名），
                        # 仍走下方覆盖式重装。
                        from neurova.skills.creation_governance import manifest_structure

                        _existing = {**self._skills[str(skill_id)],
                                     **(self._skills[str(skill_id)].get("manifest") or {})}
                        if (manifest_structure(manifest) or None) and (
                                manifest_structure(manifest) == manifest_structure(_existing)):
                            decision = {"success": True, "duplicate": True, "skill_id": str(skill_id)}
                    if decision is None and str(skill_id) not in self._skills:
                        # 结构身份已存在 → 同一工具序列**换名再装**，按重复收敛到
                        # 既有条目（P1 统一指纹）。同名条目（覆盖式重装，一等语义）
                        # 跳过此查：重装是升级不是重复。
                        canonical = self._duplicate_skill_id(
                            manifest, exclude_ids=(str(skill_id), str(manifest_id)))
                        if canonical:
                            decision = {"success": True, "duplicate": True, "skill_id": canonical}
                            for alias in (str(skill_id), str(manifest_id)):
                                self.register_skill_alias(canonical, alias)
                    if decision:
                        return decision
                    # P0-4 安装门收口：本地目录/zip/
                    # /skill-pool/install-from-zip 全部汇聚到本咽喉——先复制到
                    # .incoming 暂存再扫描，被拦即删暂存、旧版本原地保留。
                    from neurova.skills.skill_install_gate import scan_skill_for_install

                    incoming = self.skills_dir / f".incoming_{skill_id}_{int(_time.time() * 1000)}"
                    shutil.copytree(skill_path, incoming)
                    scan = scan_skill_for_install(skill_id, str(incoming))
                    if scan.get("blocked"):
                        shutil.rmtree(incoming, ignore_errors=True)
                        self._logger.warning("技能 %s 安装被安全门拦截: %s", skill_id, scan.get("error"))
                        return {
                            "success": False,
                            "error": scan.get("error") or "安全扫描未通过",
                            "findings": scan.get("findings") or [],
                        }

                    target_dir = self.skills_dir / skill_id
                    if target_dir.exists():
                        shutil.rmtree(target_dir)
                    shutil.move(str(incoming), str(target_dir))

                    # 更新技能信息（覆盖式重装）。
                    # V 轮根治：既有账本字段必须保留——旧实现整条替换，
                    # usage/trust/修订链在重装瞬间清零（apply_transfer 当初
                    # 特意绕开本咽喉的"force 清零坑"，本体一直没修）。
                    from neurova.evolution.skill_review_gate import skill_review_gate_enabled
                    _prev = self._skills.get(skill_id) or self._skills.get(manifest_id) or {}
                    # 覆盖式重装：条目一律落在调用方/清单声明的 ID 上，旧条目
                    # （ID 与清单不一致时）随迁移移除，不留孤条双份。
                    for _stale in (skill_id, manifest_id):
                        if _stale != skill_id and _stale in self._skills:
                            self._skills.pop(_stale, None)
                    self._skills[skill_id] = {
                        "id": skill_id,
                        "name": manifest.get("name", skill_id),
                        "version": manifest.get("version", "1.0.0"),
                        "description": manifest.get("description", ""),
                        "enabled": bool(_prev.get("enabled", not (
                            manifest.get("source") in {"auto", "synthesized", "llm_created"}
                            and skill_review_gate_enabled()))),
                        "installed_at": datetime.datetime.now().isoformat(),
                        "path": str(target_dir),
                        # Wave H-W1 归属坐标（安装目标库由实例目录决定；
                        # 默认 agent 库 = 现状链，user/public 库经参数覆写）
                        "pool_type": str(_prev.get("pool_type") or pool_type or "agent"),
                        "owner_user_id": str(_prev.get("owner_user_id") or owner_user_id or "") or self.agent_id,
                        "manifest": manifest,
                    }
                    for _keep in ("usage", "identity", "version_history"):
                        if _keep in _prev:
                            self._skills[skill_id][_keep] = _prev[_keep]
                    # P1-6 安装即出生修订 @1（origin=import）；存量重装则
                    # 追加修订（_append_revision 读保留下来的 history 计数）
                    self._append_revision(self._skills[skill_id], trigger="install", origin="import")

                    # 保存清单
                    self._save_manifest()

                self._logger.info("Installed skill: %s", skill_id)
                return {"success": True, "skill_id": skill_id}
            finally:
                if _extract_tmp is not None:
                    shutil.rmtree(_extract_tmp, ignore_errors=True)

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
                skill_id = self.resolve_skill_alias(skill_id)
                if self._entry(skill_id) is None:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}

                skill_info = self._skills[skill_id]

                # 删除技能目录——Wave F 根治安全缺陷：原实现 Path("") → Path(".")
                # → exists()=True → rmtree(CWD) 差点删库（元数据条目 path="" 是
                # 常态：pool 创建/自动封装）。现在：空路径不删文件；删除前校验
                # 目标在本技能目录子树内（与 archive_skill 同纪律）。
                raw_path = str(skill_info.get("path") or "")
                if raw_path:
                    skill_path = Path(raw_path)
                    try:
                        within = skill_path.is_dir() and (
                            skill_path.parent.resolve() == self.skills_dir.resolve()
                        )
                    except OSError:
                        within = False
                    if within:
                        shutil.rmtree(skill_path)
                    elif skill_path.is_dir():
                        self._logger.warning(
                            "uninstall_skill: 拒绝删除技能目录子树外的路径 %s", skill_path
                        )

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
                skill_id = self.resolve_skill_alias(skill_id)
                if self._entry(skill_id) is None:
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
                skill_id = self.resolve_skill_alias(skill_id)
                if self._entry(skill_id) is None:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}

                self._skills[skill_id]["enabled"] = False
                self._save_manifest()

                self._logger.info("Disabled skill: %s", skill_id)
                return {"success": True}

        except Exception as e:
            self._logger.error("Failed to disable skill: %s", e)
            return {"success": False, "error": str(e)}

    def record_skill_usage(self, skill_id: str, success: bool = True) -> bool:
        """记录技能使用（C11：use_count/last_used_at_ms 持久化到 manifest）。

        collection-review/改进提案的消费面——此前技能层没有使用计数，
        只有肌肉记忆侧有。manifest 写穿（文件小，频率=技能执行频率）。

 生命周期：同时维护
        last_activity_at_ms（状态机活动锚）并 seed 状态/钉住/来源字段。
        """
        import time as _time

        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return False
                usage = info.setdefault(
                    "usage", {"use_count": 0, "success_count": 0, "last_used_at_ms": 0}
                )
                usage["use_count"] = int(usage.get("use_count", 0)) + 1
                if success:
                    usage["success_count"] = int(usage.get("success_count", 0)) + 1
                now_ms = int(_time.time() * 1000)
                usage["last_used_at_ms"] = now_ms
                usage["last_activity_at_ms"] = now_ms
                usage.setdefault("state", "active")
                usage.setdefault("pinned", False)
                usage.setdefault("created_at_ms", now_ms)
                usage.setdefault("created_by", self._derive_created_by(info))
            self._save_manifest()
            return True
        except Exception as e:
            self._logger.warning("记录技能使用失败: %s", e)
            return False

    def record_skill_funnel(
        self,
        skill_id: str,
        *,
        selections: int = 0,
        applications: int = 0,
        completions: int = 0,
        fallbacks: int = 0,
    ) -> bool:
        """累加技能质量漏斗计数并落盘（P0-1）。

        与 record_skill_usage（C11）同层共存、互不替代：use_count 是执行次数
        原始账，漏斗是"选用→应用→完成/兜底"归因账（消费方：召回过滤、P0-2
        信任态、前端质量徽标）。manifest 写穿，频率=回合数，非每 token。
        """
        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return False
                usage = info.setdefault("usage", {})
                # 漏斗四键恒定存在（读侧 manifest 直读不判缺；脏值归一）
                for key in ("selections", "applications", "completions", "fallbacks"):
                    try:
                        usage[key] = max(0, int(usage.get(key, 0) or 0))
                    except (TypeError, ValueError):
                        usage[key] = 0
                for key, value in (
                    ("selections", selections),
                    ("applications", applications),
                    ("completions", completions),
                    ("fallbacks", fallbacks),
                ):
                    try:
                        increment = max(0, int(value))
                    except (TypeError, ValueError):
                        increment = 0
                    if increment:
                        usage[key] = max(0, int(usage.get(key, 0) or 0)) + increment
                self._save_manifest()
            return True
        except Exception as e:
            self._logger.warning("记录技能漏斗失败 %s: %s", skill_id, e)
            return False

    def record_trust_observation(
        self, skill_id: str, outcome: str, task_id: str, min_successes: int = 2
    ) -> bool:
        """记一次独立任务信任观测并落盘（P0-2）。

        observed_task_ids 有界 20（仅防近期重复，超出窗口的历史任务按新
        观测处理——有界换页语义，非漏洞：晋升只依赖最近计数链）。
        """
        import time as _time

        if outcome not in ("success", "failure"):
            return False
        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return False
                # trust 寄居 identity 块（出生属性，不预建 usage——生命周期
                # seed-on-first-sight 契约）；无 trust 记录（导入/存量）默认 trusted
                identity = info.setdefault("identity", {})
                trust = identity.setdefault(
                    "trust",
                    {"state": "trusted", "successes_since_failure": 0, "observed_task_ids": []},
                )
                observed = trust.setdefault("observed_task_ids", [])
                if task_id and task_id in observed:
                    return False
                new_state, new_count = compute_trust_transition(
                    str(trust.get("state") or "trusted"),
                    outcome,
                    int(trust.get("successes_since_failure", 0) or 0),
                    min_successes,
                )
                old_state = trust.get("state")
                trust["state"] = new_state
                trust["successes_since_failure"] = new_count
                if task_id:
                    observed.append(task_id)
                    del observed[:-20]
                if new_state != old_state:
                    transitions = identity.setdefault("trust_transitions", [])
                    transitions.append(
                        {
                            "event": "trust_promoted" if new_state == "trusted" else "trust_demoted",
                            "task_id": task_id,
                            "at_ms": int(_time.time() * 1000),
                        }
                    )
                    del transitions[:-10]
                self._save_manifest()
            return True
        except Exception as e:
            self._logger.warning("记录信任观测失败 %s: %s", skill_id, e)
            return False

    @staticmethod
    def _derive_created_by(info: Dict[str, Any]) -> str:
        """来源标记：从 manifest.source 显式标记派生,绝不按目录位置推断。

        auto=agent 生成；marketplace/hub=市场安装；其余视为 user。
        """
        source = str((info.get("manifest") or {}).get("source") or info.get("source") or "")
        if source == "auto":
            return "agent"
        if source in ("marketplace", "hub", "skillhub"):
            return "hub"
        return "user"

    def get_skill_usage(self, skill_id: str) -> Dict[str, Any]:
        """读取技能使用计数 + 质量漏斗（无记录返回零值；存量键名不变）。"""
        info = self._skills.get(skill_id) or {}
        usage = info.get("usage") or {}
        identity = info.get("identity") or {}
        trust = identity.get("trust") or {}
        funnel = {
            key: max(0, int(usage.get(key, 0) or 0))
            for key in ("selections", "applications", "completions", "fallbacks")
        }
        selections = funnel["selections"]
        applications = funnel["applications"]
        result = {
            "use_count": int(usage.get("use_count", 0)),
            "success_count": int(usage.get("success_count", 0)),
            "last_used_at_ms": int(usage.get("last_used_at_ms", 0)),
            # P0-2 信任态：无 trust 记录（导入/存量）默认 trusted
            "trust_state": str(trust.get("state") or "trusted"),
            "trust_transitions": list(identity.get("trust_transitions") or []),
            **funnel,
            # 派生率
            "applied_rate": round(applications / selections, 4) if selections else 0.0,
            "completion_rate": (
                round(funnel["completions"] / applications, 4) if applications else 0.0
            ),
            "fallback_rate": (
                round(funnel["fallbacks"] / applications, 4) if applications else 0.0
            ),
            "effective_rate": (
                round(funnel["completions"] / selections, 4) if selections else 0.0
            ),
        }
        return result

    # ── 生命周期接口──────
    # 供 neurova.evolution.skill_lifecycle.apply_transitions 消费的最小面。

    def iter_skills(self):
        """遍历 (skill_id, info)。生命周期状态机的数据源。"""
        with self._lock:
            for skill_id, info in list(self._skills.items()):
                if skill_id == self._ALIASES_KEY or not isinstance(info, dict):
                    continue
                yield skill_id, info

    def set_skill_lifecycle_state(self, skill_id: str, state: str) -> bool:
        """更新生命周期状态(active/stale)并落盘。归档走 archive_skill。"""
        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return False
                usage = info.setdefault("usage", {})
                usage["state"] = state
                if not usage.get("created_at_ms"):
                    usage["created_at_ms"] = int(usage.get("last_used_at_ms") or 0)
            self._save_manifest()
            return True
        except Exception as e:
            self._logger.warning("更新技能状态失败 %s -> %s: %s", skill_id, state, e)
            return False

    def set_skill_pinned(self, skill_id: str, pinned: bool) -> bool:
        """钉住/解钉：pinned 技能绕开生命周期自动迁移。"""
        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return False
                usage = info.setdefault("usage", {})
                usage["pinned"] = bool(pinned)
                usage.setdefault("state", "active")
            self._save_manifest()
            return True
        except Exception as e:
            self._logger.warning("更新技能钉住失败 %s: %s", skill_id, e)
            return False

    def seed_skill_usage(self, skill_id: str) -> bool:
        """首见播种。

        无 usage 记录的技能以 now 锚 created_at 并延迟一个周期——没有活动
        证据就不参与老化;但时钟必须从此开始,否则"永不活跃"技能永远停在
        seeded、不进 stale/archived 通道。
        """
        import time as _time

        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return False
                usage = info.setdefault("usage", {})
                now_ms = int(_time.time() * 1000)
                usage.setdefault("state", "active")
                usage.setdefault("pinned", False)
                usage.setdefault("use_count", 0)
                usage.setdefault("last_activity_at_ms", 0)
                usage.setdefault("created_at_ms", now_ms)
                usage.setdefault("created_by", self._derive_created_by(info))
            self._save_manifest()
            return True
        except Exception as e:
            self._logger.warning("播种技能使用记录失败 %s: %s", skill_id, e)
            return False

    def archive_skill(self, skill_id: str) -> Dict[str, Any]:
        """归档技能——移到 .archive/（可恢复），**永不删除**。

归档是最大破坏动作，删除绝不。磁盘上存在
        技能目录的物理搬迁；纯元数据技能（auto 注册、无文件）只改状态。
        """
        try:
            with self._lock:
                info = self._skills.get(skill_id)
                if info is None:
                    return {"success": False, "error": f"Skill not found: {skill_id}"}
                usage = info.setdefault("usage", {})
                usage["state"] = "archived"

                skill_path = Path(str(info.get("path") or ""))
                moved = False
                if skill_path.is_dir() and skill_path.parent.resolve() == self.skills_dir.resolve():
                    archive_dir = self.skills_dir / ".archive"
                    archive_dir.mkdir(exist_ok=True)
                    target = archive_dir / skill_path.name
                    if target.exists():  # 重名归档：加时间戳后缀,不覆盖
                        target = archive_dir / f"{skill_path.name}_{int(datetime.datetime.now().timestamp())}"
                    shutil.move(str(skill_path), str(target))
                    info["path"] = str(target)
                    info["archived_from"] = str(skill_path)
                    moved = True
            self._save_manifest()
            self._logger.info("Archived skill %s (moved=%s)", skill_id, moved)
            return {"success": True, "moved": moved}
        except Exception as e:
            self._logger.error("归档技能失败 %s: %s", skill_id, e)
            return {"success": False, "error": str(e)}

    def register_auto_skill(
        self, skill_id, name, description="", version="1.0.0", config=None,
        manifest_source="auto", pool_type="agent", owner_user_id="",
    ) -> bool:
        with self.creation_evidence.transaction() as db:
            self._load_skills()
            manifest = {"description": description, "config": config or {}}
            decision = self._creation_decision(manifest, automatic=manifest_source in
                                               {"auto", "synthesized", "llm_created"}, db=db)
            if decision:
                return False  # Legacy bool API: duplicate is not a new registration.
            return self._register_metadata(skill_id, name, description, version, config,
                                           manifest_source, pool_type, owner_user_id)

    def _register_metadata(
        self,
        skill_id: str,
        name: str,
        description: str = "",
        version: str = "1.0.0",
        config: Optional[Dict[str, Any]] = None,
        manifest_source: str = "auto",
        pool_type: str = "agent",
        owner_user_id: str = "",
        human_approved: bool = False,
    ) -> bool:
        """
        注册元数据技能 (无文件路径, 仅 manifest 持久化)

        s3 P0 #2: 桥接 AutoSkillBuilder → SkillService.
        自动技能 (从工具序列提取) 没有磁盘文件, 仅写入 manifest 元数据,
        使 GET /private 聚合 SkillService.list_skills() 时能展示自动技能.

        Wave F（skill_pool_api 双轨合一）：manifest_source 参数化——
        pool 手工创建的条目走 "user"（restore/进化通道不认领），默认 "auto"
        保持进化产物存量行为零变化。

        Wave H-W1（三层库）：条目带归属坐标 pool_type/owner_user_id（词汇
        沿用退役孤岛 SkillPoolType）。默认 agent + 本服务 agent_id；user/
        public 库实例由调用方（library_service 路由方）显式传参。

        Args:
            skill_id: 技能 ID
            name: 技能名称
            description: 描述
            version: 版本
            config: 配置 (tool_sequence/context_template 等)
            manifest_source: manifest.source 标记（auto=进化产物 / user=池创建）
            pool_type: 归属库 agent/user/public
            owner_user_id: 归属键（agent 库=agent_id；user 库=u:/ch: 键；
                public 库=空），缺省回退本服务 agent_id

        Returns:
            True 注册成功, False 已存在 (重复)
        """
        try:
            with self._lock:
                if skill_id in self._skills:
                    self._logger.warning("register_auto_skill: skill_id=%s 已存在, 跳过", skill_id)
                    return False

                from neurova.evolution.skill_review_gate import skill_review_gate_enabled

                # 工单 016：自动产物默认进"注册即禁用"待审，但**人已经批准过的**
                # （builder 模板过审批面后才走到这里落盘）不得再被这道门按回停用 ——
                # 否则"批准"停在内存态，重启/下一轮对话读磁盘即不可用。
                self._skills[skill_id] = {
                    "id": skill_id,
                    "name": name,
                    "version": version,
                    "description": description,
                    "enabled": not (
                        manifest_source in {"auto", "synthesized", "llm_created"}
                        and skill_review_gate_enabled()
                        and not human_approved
                    ),
                    "installed_at": datetime.datetime.now().isoformat(),
                    "path": "",  # 自动技能无文件路径
                    "pool_type": str(pool_type or "agent"),
                    "owner_user_id": str(owner_user_id or "") or self.agent_id,
                    "manifest": {
                        "source": manifest_source,
                        "config": config or {},
                    },
                }
                # P1-6 出生修订 @1（origin 跟随来源）；P0-2 出生信任态
                # provisional——trust 是出生属性，寄居 identity 块，**不预建
                # usage**（生命周期 seed-on-first-sight 契约依赖"注册无 usage"）
                self._append_revision(
                    self._skills[skill_id], trigger="register", origin=manifest_source
                )
                self._skills[skill_id]["identity"]["trust"] = {
                    "state": "provisional",
                    "successes_since_failure": 0,
                    "observed_task_ids": [],
                }
                if not self._save_manifest():
                    self._skills.pop(skill_id, None)
                    return False
                self._logger.info("Registered auto skill: %s", skill_id)
                return True
        except Exception as e:
            self._logger.exception("Failed to register auto skill %s: %s", skill_id, e)
            return False

    def _quality_gate(self, skill_id: str, entry: Dict[str, Any], version, config,
                      name, description) -> str:
        """P0 「比上一版本优秀」门控——返回拒绝原因，通过返回空串。

        **本门只咬「进化提案链」，不咬「编辑链的字段修改」。**

        `update_auto_skill` 是两条语义链共用的落盘通道：
          - **进化/提案链**（skill_improver 等）：提交版本 + 全文，自证"比上一
            版本优秀"——四道闸为它而设；
          - **编辑链**（`PUT /private`、`PUT /me/skills`、share/push、enabled
            开关、库内流转）：只改字段、**恒以 version=None 调用**，压根不声称
            "更优"。
        拿提案门槛（名述自洽 / 生效正文非空）去咬编辑链，用户改个名字、打个
        共享标记就 500——门默认开（NEUROVA_SKILL_UPDATE_GATE=1）后实测复现。
        故本门先按「本次提交了什么」分类，版本/名述两闸对编辑链不做裁决。

        四道确定性闸（零 LLM）：
          1. content_non_empty  — 拒绝"清空式改写"。**存量空描述不在此闸范围**
             （编辑链创建条目时 description 默认空串，是真实一等公民，翻开关/
             打标记不该被拦）；只咬"本次主动提交空描述/把生效正文写空"这个
             动作；
          2. version_monotonic  — 版本号不得**回退**；不可解析的版本串一律
             拒绝；同版本仅当**本次提交的字段确有变化**时放行，纯重复落盘
             视为空更新拦下——「同版本原地升级」是库内同源流转/经验重建的
             真实语义，不能与「只升不降」互斥；
          3. routing_sanity     — **提案方（提交了版本）**提交了新的非空描述
             时跑名述自洽自检，与 AutoSkillBuilder.approve_template 同一判据；
          4. review_gate        — 评审闸开启且该技能 source∈{auto,synthesized,
             llm_created} 时，改写落盘即重新置回待审（enabled=False）：批准过
             一次不等于永久免疫。

        **前置条件（时序）**：调用方必须在改动条目**之前**取快照并把旧条目传
        进来——本门所有"本次提交了什么"的判据都依赖旧值。见 `update_auto_skill`
        里 `_prev` 的取值位置。
        """
        import copy as _copy

        effective = _copy.deepcopy(entry)
        if name is not None:
            effective["name"] = str(name)
        if description is not None:
            effective["description"] = str(description)
        if config is not None:
            effective["manifest"] = {**effective.get("manifest", {}), "config": dict(config)}
        eff_config = (effective.get("manifest") or {}).get("config") or {}
        body = str(eff_config.get("context_template") or "").strip()
        sequence = eff_config.get("tool_sequence") or []
        # 有效正文 = 指令体 / 描述 / 工具序列，任一非空即算有内容——这样
        # "把正文写成空串"被拦，而"只改 tool_sequence"的既有通道不受影响。
        has_body = bool(body) or bool(str(effective.get("description") or "").strip()) or bool(sequence)
        # 编辑链判定：**本次没有提交版本**。`update_auto_skill` 是两条链共用
        # 的落盘通道（见方法 docstring），编辑链（PUT/share/push/enabled 开关、
        # 库内流转）恒以 version=None 调用——它只改字段，不声称"更优"，故
        # 「版本只升不降」「名述自洽」两闸对它是**无定义**的，不做裁决。
        editing = version is None
        # 1. content_non_empty —— 只咬"本次把正文写空"这个动作，不咬存量空。
        #
        #    存量空正文条目（编辑链创建时 description 默认空串，前端大多数
        #    调用不传它）是**真实的一等公民**：翻开关/打共享标记/改 category
        #    都属正常编辑，不该被"内容为空"拦下（历史误杀实测：PUT 与 share
        #    恒 500）。故编辑链只在**本次主动提交了一个空描述**（真正的"清空
        #    描述"动作）时拦；提案方（提交了版本）仍按"生效正文非空"判——
        #    它自证"更优"，不允许把自己清空成死技能。工具序列不受影响：
        #    "只改 tool_sequence"的既有通道照常放行。
        if not has_body:
            # 编辑链（version=None）：提交空描述 = 真正的"清空描述"动作 → 拦；
            # 未提交描述（存量空条目做字段编辑）→ 放行（存量空不是本次清空，
            # 否则翻开关/打共享标记恒 500，历史误杀实测）。
            # 提案方（提交了版本）：生效正文为空一律拦（自证"更优"却清空自己）。
            if not editing or (description is not None and not str(description).strip()):
                return "content_non_empty"
        # 编辑链**主动清空**已有描述：正文虽仍在（工具序列/指令体），但"清空式
        # 改写"不该从编辑链侧门绕过——旧洞（把描述写成空串照样落盘）必须两侧
        # 同堵。仅"提交空描述且库存描述非空"这一种形态会命中。
        if description is not None and not str(description).strip() \
                and str(entry.get("description") or "").strip():
            return "content_cleared"
        if version is not None:
            order = self._version_key(version)
            if order is None:
                return "version_unparsable"
            current = entry.get("version")
            if current is not None and self._version_key(current) is not None:
                if order < self._version_key(current):
                    # 显式降级：提案方不能把旧版当新版写回（真回滚走
                    # apply_maintenance_update 豁免通道）。
                    return "version_regression"
                if order == self._version_key(current):
                    # 同版本 + 本次提交字段无变化 = 空更新（重放/自增噪声），
                    # 拦下；同版本 + 提交字段确有变化 = **原地改进**（库内同源
                    # 流转、经验重建等真实通道都会这样写），放行——否则「只升
                    # 不降」会与「同版本原地升级」的流转语义互斥，把真路径误杀。
                    # 只比对**本次提交的字段**：未提交的字段（None）不是"没变
                    # 更"的证据。
                    if not self._submitted_change(entry, name, description, config):
                        return "version_not_ascending"
        # 路由自检只在**提案方（提交了版本）+ 本次提交了非空描述**时咬合。
        #
        # 为什么加"提案方"这一条：名述自洽是**进化提案**的自证门槛，与
        # AutoSkillBuilder.approve_template 同一判据。而编辑链（PUT /private、
        # /me/skills、share）只改字段、不提交版本，其描述是**给用户看的备注
        # 文本**（"nd"/"共享标记"这类串与技能名天然无 token 交集），拿提案
        # 门槛去咬它 = 用户改个名字、打个共享标记就 500（历史误杀实测）。
        #
        # 另一类也不该被咬：库内同源流转/经验重建会把**源侧现值原样回填**
        # （name/description 与旧值逐字相同）——那种情况 `_naming_submitted_-
        # changed` 已判 False，属"重复提交同一名述"，不是新提案。
        submitted_description = description if description is not None else None
        naming_proposed = (
            not editing
            and self._naming_submitted_changed(entry, name, description)
            and str(submitted_description or "").strip()
        )
        if naming_proposed:
            try:
                from neurova.skills.skill_injection import routing_sanity_check

                issues = routing_sanity_check(
                    str(effective.get("name") or skill_id), str(submitted_description)
                )
            except Exception as e:  # noqa: BLE001 - 自检故障不阻断既有更新通道
                self._logger.debug("routing_sanity_check 跳过: %s", e)
                issues = []
            if issues:
                return "routing_sanity"
        return ""

    @staticmethod
    def _submitted_change(entry: Dict[str, Any], name, description, config) -> bool:
        """**本次提交的字段**里是否有真实变化（None=未提交，不计入）。

        与 `_content_changed`（比对合并后的生效值，含"清空"这类变化）分工：
          - `_content_changed`：回答"生效内容与旧值是否不同"；
          - `_submitted_change`：回答"提案方这次到底改了什么"，用于**空更新**
            判定。只改 name 的编辑链必须算有变化，不能因为"版本没升"被拦。
        """
        if name is not None and str(name) != str(entry.get("name") or ""):
            return True
        if description is not None and str(description) != str(entry.get("description") or ""):
            return True
        if config is not None:
            current = (entry.get("manifest") or {}).get("config") or {}
            if dict(config) != dict(current):
                return True
        return False

    @staticmethod
    def _naming_submitted_changed(entry: Dict[str, Any], name, description) -> bool:
        """本次**提交的**名述是否与库内现值不同（未提交的字段不算）。

        `_naming_changed` 在 name/description 均为 None 时回退比对**生效值**；
        本判据直接判"没提交 = 没新名述"，因为 routing_sanity 咬的是"提案方
        新提交的名述"，不是"存量名述"。
        """
        if name is not None and str(name) != str(entry.get("name") or ""):
            return True
        if description is not None and str(description) != str(entry.get("description") or ""):
            return True
        return False

    @staticmethod
    def _naming_changed(entry: Dict[str, Any], name, description) -> bool:
        """提案方是否**真的改写了**名称或描述（零 LLM，纯值比较）。

        全为 None（不带名述上下文）或与旧值逐字相同 → False：这类写入不是
        "名述提案"，路由自检无从咬合，也不该咬合。
        """
        if name is not None and str(name) != str(entry.get("name") or ""):
            return True
        if description is not None and str(description) != str(entry.get("description") or ""):
            return True
        return False

    @staticmethod
    def _content_changed(entry: Dict[str, Any], name, description, config) -> bool:
        """同版本原地升级是否带来**内容侧**实质变化（零 LLM，纯值比较）。

        只比提案方显式提交的字段：name / description / config。全为 None
        （纯重复落盘）或与旧值逐字相同 → False（属空更新，门拒绝）。
        """
        import json as _json

        if SkillService._naming_changed(entry, name, description):
            return True
        if config is not None:
            old_config = (entry.get("manifest") or {}).get("config") or {}
            try:
                if _json.dumps(dict(config), sort_keys=True, default=str) != _json.dumps(
                    dict(old_config), sort_keys=True, default=str
                ):
                    return True
            except (TypeError, ValueError):
                return True
        return False

    @staticmethod
    def _version_key(version) -> Optional[tuple]:
        """版本号可比较键（数字段逐位比较）；不可解析返回 None。"""
        parts = str(version or "").strip().split(".")
        if not parts or any(not part.isdigit() for part in parts):
            return None
        return tuple(int(part) for part in parts)

    def _reenter_review_gate(self, entry: Dict[str, Any]) -> bool:
        """改写落盘重走评审闸：auto 系产物回到待审（enabled=False）。"""
        from neurova.evolution.skill_review_gate import skill_review_gate_enabled

        source = str((entry.get("manifest") or {}).get("source") or "auto")
        if source in {"auto", "synthesized", "llm_created"} and skill_review_gate_enabled():
            entry["enabled"] = False
            return True
        return False

    def update_auto_skill(
        self,
        skill_id: str,
        version: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        *,
        enforce_quality: Optional[bool] = None,
    ) -> bool:
        """更新已存在元数据技能的版本/配置/名称/描述并落盘（持久化通道）。

        仅允许更新已存在的技能；manifest.source 保持不变。不存在时返回 False。
        Wave F：name/description 参数支撑 skill_pool_api 的 private 编辑链。

        P0 门控（2026-09-17）：本通道是「进化改进」的最后一米，此前对内容
        零校验——先批准一次即可任意改写。现加四道确定性闸 + 改写重走评审闸
        （见 _quality_gate）。系统级维护通道（迁移/回滚/经验重建）可显式传
        enforce_quality=False 保持旧语义（需要写回旧版本/搬迁库时）。

        Args:
            skill_id: 技能 ID
            version: 新版本号（None 保持不变）
            config: 新配置（None 保持不变；提供时整体替换 manifest.config）
            name: 新名称（None 保持不变）
            description: 新描述（None 保持不变）
            enforce_quality: 是否跑 P0 质量门（None=按 NEUROVA_SKILL_UPDATE_GATE
                开关，**默认开**；系统级维护通道显式传 False 豁免）

        Returns:
            bool: 更新并落盘成功
        """
        try:
            with self._lock:
                skill_id = self.resolve_skill_alias(skill_id)
                entry = self._skills.get(skill_id)
                if entry is None or skill_id == self._ALIASES_KEY:
                    self._logger.debug("update_auto_skill: skill_id=%s 不存在", skill_id)
                    return False
                import copy as _copy

                # 门要看的是**旧值**、回滚要的也是**旧值**：必须在改动 entry 之前
                # 取快照。历史缺陷：这里把 `_prev` 放在三处赋值之后取，于是门拿到的
                # "旧条目"其实是本轮改完的条目——`_submitted_change` 恒比较
                # "自己 vs 自己"返回 False，任何字段编辑都被判成空更新/无来源可核。
                _prev = _copy.deepcopy(entry)  # 深拷贝：version_history/identity 可变容器不回滚遗漏
                # P0 质量门：内容非空 / 版本只升不降 / 路由自检 / 重走评审闸
                gate_on = self._update_gate_enabled() if enforce_quality is None else bool(enforce_quality)
                if gate_on:
                    reason = self._quality_gate(skill_id, _prev, version, config, name, description)
                    if reason:
                        self._logger.warning("update_auto_skill 被质量门拒绝(%s): %s", reason, skill_id)
                        return False
                # 门通过后才落字段改动
                if name is not None:
                    entry["name"] = str(name)
                if description is not None:
                    entry["description"] = str(description)
                if version is not None:
                    entry["version"] = str(version)
                if config is not None:
                    entry["manifest"] = {**entry.get("manifest", {}), "config": dict(config)}
                if gate_on:
                    self._reenter_review_gate(entry)  # 改写落盘即回待审（批准一次 ≠ 永久免疫）
                # P1-6 版本 DAG（线性 parent 边）：version 变化追加修订历史
                if version is not None:
                    self._append_revision(entry, trigger="update")
                if not self._save_manifest():
                    # 落盘失败 → 内存整体回滚（防盘/内存 split-brain）
                    self._skills[skill_id] = _prev
                    self._logger.warning("update_auto_skill 落盘失败，已回滚内存态: %s", skill_id)
                    return False
                self._logger.info("Updated auto skill: %s → v%s", skill_id, entry["version"])
                return True
        except Exception as e:
            self._logger.exception("Failed to update auto skill %s: %s", skill_id, e)
            return False

    @staticmethod
    def apply_maintenance_update(service, skill_id, version=None, config=None):
        """系统级维护通道（重建/回滚/迁移）：绕过「比上一版本优秀」门。

        这些通道的共同点是**内容不由提案方自证**——重建内容来自已批准经验，
        回滚/迁移刻意回归旧版或跨库搬迁，拿"版本只升不降"去卡会把安全绳
        自己剪断。签名带 enforce_quality 才传，否则按老契约调用（兼容
        测试替身/外部注入的旧签名实现）。
        """
        import inspect

        update = service.update_auto_skill
        try:
            if "enforce_quality" in inspect.signature(update).parameters:
                return update(skill_id=skill_id, version=version, config=config, enforce_quality=False)
        except (TypeError, ValueError):  # 签名不可内省 → 走老契约
            pass
        return update(skill_id=skill_id, version=version, config=config)

    @staticmethod
    def _update_gate_enabled() -> bool:
        """P0 质量门开关：NEUROVA_SKILL_UPDATE_GATE（**默认开**）。

        默认开 = P0 门控真正生效，任何走 update_auto_skill 的写入都过四道闸。
        这是本门存在的意义：默认关等于门不存在（"批准一次 → 任意改写"的旧洞
        原样保留）。系统级维护通道（回滚/重建/迁移/搬运）显式传
        enforce_quality=False 豁免，不靠"整体关掉"来放行。

        置 0/false/no/off 可退回旧语义（仅供存量排查/兼容对照，生产不应使用）。
        """
        import os

        return os.environ.get("NEUROVA_SKILL_UPDATE_GATE", "1").strip().lower() not in {
            "0", "false", "no", "off",
        }

    def _append_revision(self, entry: Dict[str, Any], trigger: str = "", origin: str = "") -> Dict[str, Any]:
        """P1-6 身份 + 最小版本 DAG：version 变化时新建修订并挂 parent 边。

        revision_id 形如 ``{skill_id}@{n}``，parent_revision_id 指向上一修订，
 构成线性链（Neurova 场景为原地改进
        FIXED 恰一父）。version_history 有界 20，manifest 直读不判缺。
        """
        import uuid

        history = entry.setdefault("version_history", [])
        identity = entry.setdefault("identity", {})
        next_n = (len(history) + 1) if history else 1
        revision_id = f"{entry.get('id', '')}@{next_n}"
        parent = identity.get("revision_id") if identity else None
        entry["identity"] = {
            "skill_id": entry.get("id", ""),
            "revision_id": revision_id,
            "revision_uuid": uuid.uuid4().hex[:8],
            "origin": origin or identity.get("origin", "auto" if not parent else "evolved"),
            "parent_revision_id": parent,
            "trigger": trigger,
            "version": str(entry.get("version", "")),
        }
        # 信任账本随修订迁移（version bump 不得丢出生 trust/晋升历史）
        for _keep in ("trust", "trust_transitions"):
            if _keep in identity:
                entry["identity"][_keep] = identity[_keep]
        history.append(
            {
                "revision_id": revision_id,
                "version": str(entry.get("version", "")),
                "parent_revision_id": parent,
                "trigger": trigger,
                "created_at": datetime.datetime.now().isoformat(),
            }
        )
        del history[:-20]  # 有界
        return entry["identity"]

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
                    # 别名表是索引而非技能条目（P1 统一指纹），不进任何列表/详情面
                    if skill_id == self._ALIASES_KEY or not isinstance(skill_info, dict):
                        continue
                    if enabled_only and not skill_info.get("enabled", True):
                        continue

                    skills.append(
                        {
                            "id": skill_id,
                            "name": skill_info.get("name", skill_id),
                            "version": skill_info.get("version", "1.0.0"),
                            "description": skill_info.get("description", ""),
                            "enabled": skill_info.get("enabled", True),
                            "installed_at": skill_info.get("installed_at", ""),
                            # 生命周期与用量（前端状态列/徽标数据源, C11 延伸）
                            "usage": skill_info.get("usage") or {},
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
                if skill_id in self._skills and skill_id != self._ALIASES_KEY:
                    resolved = skill_id
                else:
                    # 别名解析：任一命名方案（genetic_* / synth_* / skill_<md5>）
                    # 都收敛到同一条目，调用方无需知道规范 ID。
                    resolved = self.resolve_skill_alias(skill_id)
                if resolved not in self._skills or resolved == self._ALIASES_KEY:
                    return None
                skill_id = resolved
                skill_info = self._skills[skill_id]
                return {
                    "id": skill_id,
                    "name": skill_info.get("name", skill_id),
                    "version": skill_info.get("version", "1.0.0"),
                    "description": skill_info.get("description", ""),
                    "enabled": skill_info.get("enabled", True),
                    "installed_at": skill_info.get("installed_at", ""),
                    "path": skill_info.get("path", ""),
                    "manifest": skill_info.get("manifest", {}),
                    # 生命周期/用量状态
                    "usage": skill_info.get("usage", {}),
                    # P1-6 身份与版本 DAG（线性修订链）
                    "identity": skill_info.get("identity", {}),
                    "version_history": skill_info.get("version_history", []),
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
                skill_id = self.resolve_skill_alias(skill_id)
                if self._entry(skill_id) is None:
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
