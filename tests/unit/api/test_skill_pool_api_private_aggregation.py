"""
s2 TDD（历史）→ Wave F 契约演化：private 技能单源 = SkillService manifest

历史根因 (bug-hunt Phase 3): list_private_skills 仅读 _private_skills 内存 dict，
install-from-url/zip 落盘的技能在 SkillPoolPage 不可见 — split-brain。s2 当时的
修复是"聚合两源"。

Wave F (2026-09-15) 把 create 侧也落到 SkillService manifest，两源合一：
- 内存 dict `_private_skills` 已删除（create 写它 → 重启丢 + 与磁盘互不可见，
  是 split-brain 的另一半）；
- list/private 读单源（磁盘 manifest），owner 语义=目录级隔离
  （data/agents/{agent_id}/skills），不再内存过滤；
- 异常降级契约保持：读失败 → 返回空 + logger.exception（不静默吞）。
"""

import asyncio
import inspect
from unittest.mock import MagicMock, patch


def _fake_service(entries):
    """iter_skills 形态的单源替身（entries: [(sid, info)]）。"""
    svc = MagicMock()
    svc.iter_skills.return_value = entries
    return svc


def _patch_service(svc):
    """patch 端点解析链：skill_service 模块属性（_pool_service 延迟解析）。"""
    return patch("neurova.skills.skill_service.SkillService", return_value=svc)


def test_list_private_skills_single_disk_source():
    """静态契约演化: list 源码走 _pool_service（SkillService manifest 单源），
    内存双轨 dict 已从模块删除（hasattr 为真权威断言——源码子串检查会被
    函数名 list_private_skills 误撞，不用）。"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.list_private_skills)
    assert "_pool_service" in src, "应经 _pool_service 解析 SkillService"
    assert not hasattr(mod, "_private_skills"), "模块级 _private_skills 必须删除"
    assert "_private_skills[" not in src and "_private_skills." not in src


def test_list_private_skills_returns_manifest_entries():
    """行为契约: 单源条目 → SkillInfo 列表（含 usage/category/shared 透传）。"""
    from neurova.api.endpoints import skill_pool_api as mod

    svc = _fake_service([
        (
            "s-1",
            {
                "name": "alpha",
                "description": "d",
                "version": "1.0.1",
                "enabled": True,
                "manifest": {"config": {"category": "research", "shared": True}},
                "usage": {"use_count": 2},
            },
        ),
    ])
    with _patch_service(svc):
        result = asyncio.run(mod.list_private_skills(agent_id="a1"))
    assert len(result) == 1
    row = result[0]
    assert row.name == "alpha" and row.category == "research"
    assert row.shared is True and row.owner_id == "a1"
    assert row.usage == {"use_count": 2}


def test_list_private_skills_degrades_when_service_raises():
    """演化契约: 磁盘读失败 → 空列表 + logger.exception（不静默吞，不再回退内存源）。"""
    from neurova.api.endpoints import skill_pool_api as mod

    def _boom(agent_id):
        raise RuntimeError("disk error")

    with patch.object(mod, "_pool_service", side_effect=_boom):
        with patch.object(mod.logger, "exception") as mock_log_exc:
            result = asyncio.run(mod.list_private_skills(agent_id="a2"))
    assert result == []
    assert mock_log_exc.called, "读失败必须 logger.exception"


def test_list_private_skills_passes_agent_id_to_service():
    """s2.5 演化: agent_id 透传构造（目录级 owner 隔离的单源实现）。"""
    from neurova.api.endpoints import skill_pool_api as mod

    svc = _fake_service([])
    with patch("neurova.skills.skill_service.SkillService") as mock_cls:
        mock_cls.return_value = svc
        asyncio.run(mod.list_private_skills(agent_id="agent-xyz"))
        assert mock_cls.called
        assert mock_cls.call_args.kwargs.get("agent_id") == "agent-xyz"


def test_create_persists_via_service_not_memory():
    """create 契约: 经 register_auto_skill 落盘（manifest_source=user），
    不再有内存 dict 写入路径。"""
    from neurova.api.endpoints import skill_pool_api as mod
    from neurova.api.endpoints.skill_pool_api import SkillCreate

    svc = MagicMock()
    svc.register_auto_skill.return_value = True
    with patch.object(mod, "_pool_service", return_value=svc):
        info = asyncio.run(
            mod.create_private_skill(SkillCreate(name="n1", description="d1"), agent_id="a3")
        )
    assert info.owner_id == "a3"
    kwargs = svc.register_auto_skill.call_args.kwargs
    assert kwargs.get("manifest_source") == "user", "池创建条目不得冒充 auto 进化产物"
    assert kwargs.get("name") == "n1"
