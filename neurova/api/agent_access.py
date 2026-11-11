# -*- coding: utf-8 -*-
"""Agent 属主判定单源（Wave H-W0，三层技能库前置安全）

背景（三层库侦查坐实）：agent 的 owner_user_id 链（创建写入→workspace 落盘→
重启回填→chat 执行门）已通，但列表面/详情面/写口/中枢登记面各自缺位或
复制了不同口径的实现（chat 拒绝无主 vs package 公共可读语义相反）。三层技能
库落地后，"改他人 agent"等价于绕过他人私库隔离——本模块统一为唯一判定源。

口径（与 chat 现行执行门一致，显示对齐执行）：
- admin：全量（可见/可管）；
- 非 admin：仅 owner_user_id == 自己的 user_id；
- **无 owner 的 agent 仅 admin**（历史无主 agent 由管理员认领/管理；
  与 chat 执行门同源，消除"列表可见、对话被拒"的误导态）。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from fastapi import HTTPException

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "agentOwnerById",
    "agentGroupById",
    "agentDeptRootById",
    "agentOwnerDeptRootById",
    "can_access_agent",
    "requireAgentOwner",
    "resolve_agent_owner",
    "migrateUserAgentsToDept",
]


def can_access_agent(user_id: str, role: str, owner: Optional[str]) -> bool:
    """访问/管理判定单源：admin 全量；owner 匹配；无主仅 admin。"""
    if role == "admin":
        return True
    owner_s = str(owner or "").strip()
    if not owner_s:
        return False
    return owner_s == str(user_id or "").strip()


def resolve_agent_owner(agent_id: str, *, state_agent: Any = None, registered_cfg: Any = None) -> Optional[str]:
    """解析 agent 属主：运行实例 config 优先，中枢登记（agents.json/
    workspace agent_config.json 由 _save_agent_config 同步）回退。"""
    if state_agent is not None:
        cfg = getattr(state_agent, "config", None)
        owner = getattr(cfg, "owner_user_id", None) if cfg is not None else None
        if owner:
            return str(owner)
    if isinstance(registered_cfg, dict):
        owner = registered_cfg.get("owner_user_id") or (registered_cfg.get("config") or {}).get("owner_user_id")
        if owner:
            return str(owner)
    return None


def agentOwnerById(agent_id: str) -> Optional[str]:
    """按 agent_id 取属主：运行实例优先，中枢登记（agents.json / workspace 同步）回退。

    **取数也收在这一处**：此前渠道、技能池、agent 各面各自拼一遍"先查 state 再查
    登记"，同一契约多份取数实现 —— 其中任何一份漏了回退，就会把有主 agent 判成
    无主，而无主的判据是"仅 admin"，属主本人被自己挡在门外。
    """
    state_agent = None
    try:
        from neurova.api.endpoints import get_agent_instance

        state_agent = get_agent_instance(agent_id)
    except Exception as exc:  # noqa: BLE001 - 状态面不可用即按"无实例"走登记回退
        logger.debug("agent 实例查询失败 %s: %s", agent_id, exc)
    registered_cfg = None
    if state_agent is None:
        try:
            from neurova.api.endpoints.agent import get_agent_config_manager

            registered_cfg = get_agent_config_manager().get_agent(agent_id)
        except Exception as exc:  # noqa: BLE001 - 登记面不可用即按"无登记"走
            logger.debug("agent 登记查询失败 %s: %s", agent_id, exc)
    return resolve_agent_owner(agent_id, state_agent=state_agent, registered_cfg=registered_cfg)


def agentGroupById(agent_id: str) -> Optional[str]:
    """agent 绑定的部门组 id（specs/2026-11-07 批 D）：运行实例 config 优先，
    中枢登记（agents.json 的 config.group_id）回退；取数链与 agentOwnerById 同形。"""
    state_agent = None
    try:
        from neurova.api.endpoints import get_agent_instance

        state_agent = get_agent_instance(agent_id)
    except Exception as exc:  # noqa: BLE001 - 状态面不可用即走登记回退
        logger.debug("agent 实例查询失败 %s: %s", agent_id, exc)
    if state_agent is not None:
        cfg = getattr(state_agent, "config", None)
        gid = getattr(cfg, "group_id", None) if cfg is not None else None
        if gid:
            return str(gid)
    if state_agent is None:
        try:
            from neurova.api.endpoints.agent import get_agent_config_manager

            registered_cfg = get_agent_config_manager().get_agent(agent_id)
        except Exception as exc:  # noqa: BLE001 - 登记面不可用即按"无登记"走
            logger.debug("agent 登记查询失败 %s: %s", agent_id, exc)
        if isinstance(registered_cfg, dict):
            gid = registered_cfg.get("group_id") or (registered_cfg.get("config") or {}).get("group_id")
            if gid:
                return str(gid)
    return None


def agentDeptRootById(agent_id: str) -> Optional[str]:
    """agent 的部门根（specs/2026-11-07 批 D）：沿绑定部门组的 parent 链上溯。

    绑定组缺失/非 custom（部门）组/解析异常 → None——**缺配不锁人**：
    部门门只对明确绑定到部门组的 agent 生效。
    """
    gid = agentGroupById(agent_id)
    if not gid:
        return None
    try:
        from neurova.auth.user_group_model import UserGroupType, get_user_group_manager

        mgr = get_user_group_manager()
        group = mgr.get_group(gid)
        if group is None or group.group_type != UserGroupType.CUSTOM:
            return None
        seen: set = set()
        while group.parent_group_id and group.parent_group_id not in seen:
            seen.add(group.group_id)
            parent = mgr.get_group(group.parent_group_id)
            if parent is None:
                break
            group = parent
        return group.group_id
    except Exception as exc:  # noqa: BLE001 - 分组面不可用即不设门
        logger.debug("agent 部门根解析失败 %s: %s", agent_id, exc)
        return None


def agentOwnerDeptRootById(agent_id: str) -> Optional[str]:
    """渠道 agent 属主的部门根（渠道租户对账用，specs/2026-11-07 批 D）。

    owner 是 user_id，群成员按 username 记账——补一次 id→username 查表；
    无属主/查表失败 → None；属主无部门 → "default"（对账侧据此保留渠道配置）。
    """
    owner = agentOwnerById(agent_id)
    if not owner:
        return None
    try:
        from neurova.auth.user_model import UserModel

        row = UserModel().get_user_by_id(int(owner))
        username = str(getattr(row, "username", "") or "")
        if not username:
            return None
        from neurova.auth.user_group_model import resolveUserDepartment

        return str(resolveUserDepartment(username).get("tenant_id") or "default")
    except Exception as exc:  # noqa: BLE001 - 对账依赖面不可用即不设门
        logger.debug("agent 属主部门根解析失败 %s: %s", agent_id, exc)
        return None


def requireAgentOwner(agent_id: str, current_user: Any, *, action: str = "访问") -> None:
    """HTTP 门：admin 全量；非 admin 仅属主；**无主（含 `default`）仅 admin**。

    与 `can_access_agent` 同一判据，只是把"拒绝"落成 403。门的默认方向是
    **拒绝**：身份缺席（端点被直调而未传身份）按匿名处理，不让"忘了传身份"
    变成绕过口的旁路。
    """
    identity = current_user if isinstance(current_user, Mapping) else {}
    uid = str(identity.get("user_id") or "")
    role = str(identity.get("role") or "user")
    if can_access_agent(uid, role, agentOwnerById(agent_id)):
        return
    raise HTTPException(
        status_code=403,
        detail=f"无权{action}智能体『{agent_id}』（仅属主或管理员可操作）",
    )


def migrateUserAgentsToDept(
    username: str,
    *,
    manager: Optional[Any] = None,
    registry: Optional[Any] = None,
    state_agents: Optional[Mapping[str, Any]] = None,
    dept_registry: Optional[Any] = None,
) -> Dict[str, Any]:
    """用户换部门 → 名下 agent 的部门绑定迁移到新部门组（用户需求 2026-11-12）。

    语义：组成员变更（加入/移出部门组）后，按 `resolveUserDepartment` 单源解析
    该用户当下的部门组，名下（owner_user_id 匹配）全部 agent 的 group_id 跟随
    迁移——绑定三处同步，与 update_agent 端点落盘形态同款：
      1. 运行实例 `config.group_id`；
      2. workspace 配置文件（`_save_agent_config`，与 update 端点同一落盘口）；
      3. agents.json 登记的 config 子字典**合并写**（整键替换会丢 model/provider，
         specs/2026-11-07 批 D 同款教训）。

    幂等（已在新组的 agent 跳过）；解析不出部门组（None/default）不动任何
    agent——解析不出就不猜；非该用户的 agent 不碰。成员变更端点在变更成功后
    触发本函数，迁移失败不回滚成员变更（主操作优先），结果随响应外露。
    """
    readout: Dict[str, Any] = {
        "username": str(username or ""),
        "new_group_id": None,
        "migrated": [],
        "skipped": [],
    }

    try:
        from neurova.auth.user_group_model import resolveUserDepartment

        kwargs: Dict[str, Any] = {}
        if manager is not None:
            kwargs["manager"] = manager
        if dept_registry is not None:
            # 分类对表注册表透传（resolveUserDepartment 单源参数）；None=生产单源自取
            kwargs["registry"] = dept_registry
        dept = resolveUserDepartment(str(username or ""), **kwargs)
    except Exception as exc:  # noqa: BLE001 - 解析失败不猜部门
        logger.debug("迁移前置：部门解析失败 %s: %s", username, exc)
        readout["reason"] = "dept_resolve_failed"
        return readout

    new_gid = dept.get("group_id")
    readout["new_group_id"] = new_gid
    if not new_gid:
        readout["reason"] = "no_department"
        return readout

    try:
        from neurova.auth.user_model import UserModel

        row = UserModel().get_user_by_username(str(username or ""))
        user_id = str(getattr(row, "id", "") or "") if row is not None else ""
    except Exception as exc:  # noqa: BLE001 - 查表失败不迁移，如实点名
        logger.warning("迁移前置：user_id 查表失败 %s: %s", username, exc)
        readout["reason"] = "user_lookup_failed"
        return readout
    if not user_id:
        readout["reason"] = "user_not_found"
        return readout
    readout["user_id"] = user_id

    if registry is None:
        try:
            from neurova.api.endpoints.agent import get_agent_config_manager

            registry = get_agent_config_manager()
        except Exception as exc:  # noqa: BLE001 - 登记面不可用即无从枚举
            logger.warning("迁移前置：agent 登记面不可用: %s", exc)
            readout["reason"] = "registry_unavailable"
            return readout
    if state_agents is None:
        try:
            from neurova.api.endpoints import get_app_state

            state = get_app_state() or {}
            state_agents = state.get("agents") or {}
        except Exception as exc:  # noqa: BLE001 - 状态面不可用即只走登记面
            logger.debug("agent 运行状态面不可用: %s", exc)
            state_agents = {}

    def _ownedIds():
        """该用户名下 agent id 并集：登记面（owner_user_id 顶层键）∪ 运行面。"""
        ids: list[str] = []
        try:
            for rec in registry.list_agents():
                aid = str((rec or {}).get("id") or "")
                full = registry.get_agent(aid) or {}
                if str(full.get("owner_user_id") or "") == user_id:
                    ids.append(aid)
        except Exception as exc:  # noqa: BLE001 - 登记面遍历失败不炸迁移
            logger.debug("登记面枚举失败: %s", exc)
        try:
            for aid, agent in dict(state_agents or {}).items():
                cfg = getattr(agent, "config", None)
                if cfg is not None and str(getattr(cfg, "owner_user_id", "") or "") == user_id:
                    if aid not in ids:
                        ids.append(str(aid))
        except Exception as exc:  # noqa: BLE001 - 状态面遍历失败不炸迁移
            logger.debug("运行面枚举失败: %s", exc)
        return ids

    for agent_id in _ownedIds():
        # 当前绑定：运行实例优先，登记回退（与 agentGroupById 同形）
        current: Optional[str] = None
        agent = (state_agents or {}).get(agent_id)
        cfg = getattr(agent, "config", None) if agent is not None else None
        if cfg is not None:
            current = getattr(cfg, "group_id", None)
        reg = registry.get_agent(agent_id) or {}
        if current is None:
            current = reg.get("group_id") or (reg.get("config") or {}).get("group_id")
        current_str = str(current) if current else None

        if current_str == new_gid:
            readout["skipped"].append({"agent_id": agent_id, "reason": "already_on_target"})
            continue

        # 1) 运行实例
        if cfg is not None:
            try:
                cfg.group_id = new_gid
            except Exception as exc:  # noqa: BLE001 - 单 agent 失败不拖垮整批
                logger.warning("agent %s 实例绑定更新失败: %s", agent_id, exc)
        # 2) workspace 配置文件（与 update_agent 端点同一落盘口）
        if agent is not None:
            try:
                from neurova.api.endpoints.agent import _save_agent_config

                _save_agent_config(agent)
            except Exception as exc:  # noqa: BLE001 - 落盘失败不拖垮整批，登记面仍会同步
                logger.warning("agent %s 配置文件落盘失败: %s", agent_id, exc)
        # 3) agents.json 登记（config 合并写防丢 model/provider）
        try:
            merged = dict(reg.get("config") or {})
            merged["group_id"] = new_gid
            registry.update_agent(agent_id, {"config": merged})
        except Exception as exc:  # noqa: BLE001 - 登记写失败不拖垮整批
            logger.warning("agent %s 登记面绑定更新失败: %s", agent_id, exc)

        readout["migrated"].append(
            {"agent_id": agent_id, "from": current_str, "to": new_gid})
        logger.info(
            "部门迁移：用户 %s 的 agent %s 绑定 %s → %s",
            username, agent_id, current_str, new_gid,
        )

    return readout
