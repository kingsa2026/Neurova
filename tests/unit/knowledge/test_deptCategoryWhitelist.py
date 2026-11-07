# -*- coding: utf-8 -*-
"""部门分类白名单执行点契约（specs/2026-11-07 批 C）。

红灯判据（设计 §2.5/§2.6）：
- visible_items：非 admin 且部门受限 → 白名单外条目不可见（restricted 空列表 = 全不可见）；
- admin 在本部门租户内不受白名单限制（反向钉：管理面全量语义不变）；
- 无部门组（restricted=False）用户行为与今天逐字一致（反向钉）；
- can_view/can_modify 同口径（读/改都挡白名单外）；
- FTS 检索路同样被白名单收口（restricted 时 d.category IN 白名单）；
- kb_builder 落库：tenant_id＝说话人部门根、category＝显式 > 部门缺省 > "kb_builder"；
- 导入分类解析：显式指定 > 部门缺省分类 > "import"。
"""

import pytest

from neurova.knowledge.repository import KnowledgeRepository

DEPT_RND = {
    "tenant_id": "dept_root",
    "group_id": "g1",
    "allowed_categories": ["rnd"],
    "restricted": True,
    "default_category": None,
}
DEPT_EMPTY_RESTRICTED = {
    "tenant_id": "dept_root",
    "group_id": "g1",
    "allowed_categories": [],
    "restricted": True,
    "default_category": None,
}
UNRESTRICTED = {
    "tenant_id": "default",
    "group_id": None,
    "allowed_categories": [],
    "restricted": False,
    "default_category": None,
}


def _patchResolver(monkeypatch, dept):
    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment", lambda username, **kw: dept
    )


def _seed(repo, tenant="dept_root"):
    inside = repo.create_knowledge(
        agent_id="a1", title="研发条目", content="rnd secret alpha token",
        category="rnd", tags=[], source="s", confidence=0.9,
        owner_user_id="u1", tenant_id=tenant,
    )
    outside = repo.create_knowledge(
        agent_id="a1", title="其他条目", content="other secret beta token",
        category="other", tags=[], source="s", confidence=0.9,
        owner_user_id="u1", tenant_id=tenant,
    )
    return inside, outside


def _dept_user():
    return {"user_id": "u1", "username": "alice", "tenant_id": "dept_root"}


def testVisibleItemsFiltersOutsideWhitelist(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path))
    _seed(repo)
    _patchResolver(monkeypatch, DEPT_RND)
    items = repo.visible_items(_dept_user(), scope="all")
    assert [i["category"] for i in items] == ["rnd"]


def testRestrictedEmptyWhitelistSeesNothing(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path))
    _seed(repo)
    _patchResolver(monkeypatch, DEPT_EMPTY_RESTRICTED)
    assert repo.visible_items(_dept_user(), scope="all") == []


def testVisibleItemsAdminBypassesWhitelist(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path))
    _seed(repo)
    _patchResolver(monkeypatch, DEPT_RND)
    admin = {"user_id": "u9", "username": "root", "role": "admin", "tenant_id": "dept_root"}
    items = repo.visible_items(admin, scope="all")
    assert sorted(i["category"] for i in items) == ["other", "rnd"]


def testUnrestrictedDeptUserSeesAll(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path))
    _seed(repo, tenant="default")
    _patchResolver(monkeypatch, UNRESTRICTED)
    user = {"user_id": "u1", "username": "alice", "tenant_id": "default"}
    items = repo.visible_items(user, scope="all")
    assert sorted(i["category"] for i in items) == ["other", "rnd"]


def testCanViewAndModifyBlockOutsideWhitelist(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path))
    inside, outside = _seed(repo)
    _patchResolver(monkeypatch, DEPT_RND)
    user = _dept_user()
    # 属主本人也受白名单约束（隔离先于归属）
    assert repo.can_view(user, inside) is True
    assert repo.can_view(user, outside) is False
    assert repo.can_modify(user, inside) is True
    assert repo.can_modify(user, outside) is False
    admin = {"user_id": "u9", "username": "root", "role": "admin", "tenant_id": "dept_root"}
    assert repo.can_view(admin, outside) is True
    assert repo.can_modify(admin, outside) is True


def testHandBuiltUserWithoutUsernameUnaffected(tmp_path, monkeypatch):
    """手搓 user dict（无 username，测试/内部调用）不触发解析 → 行为不变（反向钉）。"""
    repo = KnowledgeRepository(str(tmp_path))
    _seed(repo)
    user = {"user_id": "u1", "tenant_id": "dept_root"}
    items = repo.visible_items(user, scope="all")
    assert sorted(i["category"] for i in items) == ["other", "rnd"]


def testFtsSearchWhitelistFilters(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path))
    inside, outside = _seed(repo)
    _patchResolver(monkeypatch, DEPT_RND)
    user = _dept_user()
    hits = repo.ftsSearch("alpha", user, scope="all", limit=10)
    assert hits, "FTS 应命中 alpha"
    # FTS 命中行是投影（不含 category），按 knowledge_id 回查条目定类
    cats = [repo.find_item(h["knowledge_id"])[1].get("category") for h in hits]
    assert cats == ["rnd"]
    # 白名单外关键词：请求侧没有 category 参数，结果同样被白名单收口
    hits_out = repo.ftsSearch("beta", user, scope="all", limit=10)
    assert all(h["knowledge_id"] != outside["knowledge_id"] for h in hits_out)


def testKbBuilderLandsCallerDeptTenantAndCategory(tmp_path):
    from neurova.skills.builtin.kb_builder_executor import KbBuilderSkillExecutor

    repo = KnowledgeRepository(str(tmp_path))
    exe = KbBuilderSkillExecutor(repository=repo)
    result = invoke_record_summary(exe, {
        "topic": "心智模型",
        "content": "综述正文",
        "_caller_user_id": "u1",
        "_caller_tenant_id": "dept_root",
        "_caller_default_category": "rnd",
    })
    assert result.success is True
    item = repo.find_item(result.output["summary_knowledge_id"])[1]
    assert item["tenant_id"] == "dept_root"
    assert item["category"] == "rnd"


def testKbBuilderWithoutDeptContextKeepsLegacyShape(tmp_path):
    """无部门上下文（_caller_tenant_id 缺省）→ 落 default 租户＋kb_builder 分类（反向钉）。"""
    from neurova.skills.builtin.kb_builder_executor import KbBuilderSkillExecutor

    repo = KnowledgeRepository(str(tmp_path))
    exe = KbBuilderSkillExecutor(repository=repo)
    result = invoke_record_summary(exe, {"topic": "T", "content": "C", "_caller_user_id": "u1"})
    assert result.success is True
    item = repo.find_item(result.output["summary_knowledge_id"])[1]
    assert item["tenant_id"] == "default"
    assert item["category"] == "kb_builder"


def invoke_record_summary(exe, params):
    return getattr(exe, "execute")({"action": "record_summary", **params})


def testImportCategoryResolution(monkeypatch):
    from neurova.api.endpoints.knowledge_ingestion import _resolveImportCategory

    # 显式指定优先
    assert _resolveImportCategory(_dept_user(), "arch") == "arch"
    # 部门缺省分类次之
    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment",
        lambda username, **kw: {**DEPT_RND, "default_category": "rnd"},
    )
    assert _resolveImportCategory(_dept_user(), "") == "rnd"
    # 都没有 → 既有 "import"（反向钉）
    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment", lambda username, **kw: dict(DEPT_RND)
    )
    assert _resolveImportCategory(_dept_user(), "") == "import"
    # 无 username（服务令牌等）→ "import"
    assert _resolveImportCategory({"user_id": "system"}, "") == "import"
