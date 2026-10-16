r"""读面不许把"账本在册"当"可得"——投影与物化必须同向（用户裁甲，§6-272）。

撞见过程（现读实状，比票面写的更大）：本机 `data/agents/default/skills/manifest.json` 的 8 条里，
**7 条的落盘目录只有 `manifest.json`**（无 `SKILL.md`、无 `.py`、无 `tool_sequence`），mtime 都是
2026-10-06 那一批旧代码留下的陈态。而读侧每一面都只认账本的 `enabled`：
`list_skills`／`get_skill_info` 原样吐、`/agent/{id}/skills` 与 `/private`／`/me/skills` 投影出去、
`skill_visibility.VisibleSkill.enabled` 的三闸只看 `enabled`／运行时 `status`／生命周期 `state`——
**没有一面看过落盘**。更糟的是物化口：`market_registry.py:376-379` 在造不出执行体时
**兜底注册一个 `status=ACTIVE` 的裸基类**，于是工具 schema、提示词目录、`has_skill` 全把它画成"存在且可用"，
要到 `execute()` 才 `NotImplementedError`。

本批按甲案收：**"可得"的凭据从"清单在册"换成"这份条目真能变成一个动得了的执行体"**，
并且投影侧与物化侧必须同一条判定——两处各写一份就会各自演化（本仓同族教训见 §6-247/§6-259）。

三条分支都是**真形状**，少认一条就是把可用技能误标成不可用（那是另一种故障）：

- 账本自证型（`manifest.config.tool_sequence` 非空）：合成／自主分装的字节本来就在账本里，磁盘可以空；
- 映射执行体型（`web-search` 那一族，`_MARKET_EXECUTORS` 命中）：执行体在代码里，不在盘上；
- 落盘构件型：目录里有 `SKILL.md`（指令型）或入口脚本（`main.py`／首个非 `__init__` 的 `.py`）。

另有存量那一形：`path` 为空（`register_auto_skill` 写的"自动技能无文件路径"）——**本判据不裁决它**，
否则会把从没打算落盘的技能一并画成不可用。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.skills.skill_install_gate import reset_install_gate_scanner
from neurova.skills.skill_service import SkillService

REPO = Path(__file__).resolve().parents[3]
SKILL_MD = "# demo\n指令型技能的说明体。\n"


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _svc(tmp_path, agent="b58-agent"):
    return SkillService(agent_id=agent, skills_dir=str(tmp_path / "installed"))


def _install(svc, tmp_path, skill_id, *, files, base=None, source="marketplace"):
    """按给定文件清单落一只包并走真安装咽喉。

    `source` 必须是 `marketplace`——恢复口 `restore_market_skills_from_service` 按来源白名单挑条目，
    来源不匹配时它根本不看这条，"没被注册"就成了白过的空场断言（本档第一版就差点这么绿）。
    """
    src = (base or tmp_path / "src") / skill_id
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0", "source": source},
                   ensure_ascii=False), encoding="utf-8")
    for name, body in files.items():
        (src / name).write_text(body, encoding="utf-8")
    result = svc.install_skill(str(src), skill_id=skill_id)
    assert result.get("success") is True, f"装配本身没成功，样本不成立：{result}"
    assert (svc.get_skill_info(skill_id) or {}).get("manifest", {}).get("source") == source, \
        "账本里的来源没落对，恢复口不会碰这条"
    return svc.skills_dir / skill_id


def _makeShell(svc, tmp_path, skill_id="shell-b58") -> Path:
    """真·空壳：装一只只带 manifest 的包，再把落盘内容删光（就是本机那 7 条的形状）。"""
    installed = _install(svc, tmp_path, skill_id, files={})
    assert skill_id in [s["id"] for s in svc.list_skills()], "条目没进账本，样本不成立"
    return installed


def _stripToolSequence(svc, skill_id):
    """把账本条目的落点与构件抹干净，但保留 `manifest.config.tool_sequence`（账本自证型）。"""
    ledger = json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
    entry = ledger[skill_id]
    entry["manifest"] = {"source": "synthesized",
                         "config": {"tool_sequence": ["read_file", "write_file"]}}
    Path(svc.manifest_path).write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")


class TestAvailabilityProjection:
    def test_shellEntryProjectsAsUnavailable(self, tmp_path):
        """本批的红：账本在册、目录只有 manifest.json ⇒ 读面必须说不引进。"""
        svc = _svc(tmp_path)
        _makeShell(svc, tmp_path)
        reopened = _svc(tmp_path)

        info = reopened.get_skill_info("shell-b58")
        assert info is not None, "条目从详情面消失了——那是另一种故障（用户该看见它装过）"
        assert info.get("available") is False, (
            f"空壳仍被投影成可得：{ {k: info.get(k) for k in ('enabled', 'available')} }")
        reason = str(info.get("unavailableReason") or "")
        assert reason, "拒因不给，读的人无从判断该重装还是该撤条目"
        row = next((s for s in reopened.list_skills() if s["id"] == "shell-b58"), None)
        assert row is not None and row.get("available") is False, f"列表面与详情面不同向：{row}"

    def test_docSkillWithSkillMdIsStillAvailable(self, tmp_path):
        """对照格①：指令型（只有 SKILL.md，没有 .py）不许被误伤。"""
        svc = _svc(tmp_path)
        _install(svc, tmp_path, "doc-b58", files={"SKILL.md": SKILL_MD})
        info = _svc(tmp_path).get_skill_info("doc-b58")
        assert info.get("available") is True, (
            f"指令型技能被判成不可用（它本来就没有 .py）：{info.get('unavailableReason')}")

    def test_ledgerSelfProvingToolSequenceIsAvailableWithoutDiskBytes(self, tmp_path):
        """对照格②：合成／自主分装的字节在账本里，磁盘空着也算可得——误判它就是把好技能灰掉。"""
        svc = _svc(tmp_path)
        installed = _install(svc, tmp_path, "seq-b58", files={"main.py":
                             "def main(**kwargs):\n    return {'ok': True}\n"})
        (installed / "main.py").unlink()
        _stripToolSequence(svc, "seq-b58")

        info = _svc(tmp_path).get_skill_info("seq-b58")
        assert info.get("available") is True, (
            f"账本自证型（tool_sequence）被误标不可用：{info.get('unavailableReason')}")

    def test_emptyPathEntryIsLeftAlone(self, tmp_path):
        """对照格③：`path` 为空的存量形（自动技能声明"无文件路径"）不由本判据裁决。"""
        svc = _svc(tmp_path)
        _install(svc, tmp_path, "nopath-b58", files={"main.py":
                 "def main(**kwargs):\n    return {'ok': True}\n"})
        ledger = json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
        ledger["nopath-b58"]["path"] = ""
        Path(svc.manifest_path).write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")

        info = _svc(tmp_path).get_skill_info("nopath-b58")
        assert info.get("available") is not False, (
            "从没打算落盘的条目被画成不可用——这是本判据越界")

    def test_missingLedgerDirProjectsUnavailable(self, tmp_path):
        """落点声明了却不在盘上（被清理／手删／迁移丢件）⇒ 与空壳同一如实形态。"""
        svc = _svc(tmp_path)
        installed = _install(svc, tmp_path, "gone-b58", files={"SKILL.md": SKILL_MD})
        import shutil
        shutil.rmtree(installed)

        info = _svc(tmp_path).get_skill_info("gone-b58")
        assert info.get("available") is False, "目录都没了仍被投影成可得"


class TestApiProjectionCarriesAvailability:
    """端点必须把这条对账读数带出去——否则这字段就是新的"只写不读"断点（§2 断点条款）。

    走真 HTTP 面（`TestClient`），不把端点当普通函数 `await`（本仓 §6-28 修过那一形）；
    契约在册与否按 `app.openapi()` 取，不看装饰器（形态集 214）。
    """

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.deps import get_current_user
        from neurova.api.endpoints import skill_pool_api
        from neurova.skills import library_service as lib

        monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
        lib.reset_libraries_for_tests()
        app = FastAPI()
        app.include_router(skill_pool_api.router, prefix="/api/v1/skill-pool")
        # 身份走 dependency_overrides 打**端点模块真正 import 的那个函数对象**——
        # `Depends(...)` 在装饰时就绑了函数，patch 模块属性无效（本仓 §4 记过这一形）
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "7", "username": "qa", "role": "admin", "neuser_id": "7"}
        with TestClient(app, raise_server_exceptions=False) as c:
            c.app = app
            yield c
        app.dependency_overrides.clear()
        lib.reset_libraries_for_tests()

    def _seed(self, client, tmp_path, skill_id, files):
        from neurova.skills import library_service as lib

        service = lib.get_library(lib.POOL_AGENT, "b58ep")
        _install(service, tmp_path, skill_id, files=files)
        return service

    def test_contract_exposes_the_availability_pair(self, client):
        schema = json.dumps(client.app.openapi(), ensure_ascii=False)
        assert '"available"' in schema and '"unavailable_reason"' in schema, (
            "投影字段没进响应契约——前端拿不到，这一格就成了断点")

    def test_shellShowsAsUnavailableOnBothAgentFaces(self, client, tmp_path):
        self._seed(client, tmp_path, "ep-shell-b58", files={})
        for path in ("/api/v1/skill-pool/private?agent_id=b58ep",
                     "/api/v1/skill-pool/agent/b58ep/skills"):
            items = client.get(path).json()
            row = next((i for i in items if i.get("skill_id") == "ep-shell-b58"), None)
            assert row is not None, f"{path} 里这条不见了（用户更无从重装/撤条目）"
            assert row.get("available") is False, f"{path} 仍把空壳报成可得：{row}"
            assert row.get("unavailable_reason"), f"{path} 没给原因：{row}"

    def test_docSkillShowsAsAvailableOnBothAgentFaces(self, client, tmp_path):
        self._seed(client, tmp_path, "ep-doc-b58", files={"SKILL.md": SKILL_MD})
        for path in ("/api/v1/skill-pool/private?agent_id=b58ep",
                     "/api/v1/skill-pool/agent/b58ep/skills"):
            row = next((i for i in client.get(path).json()
                        if i.get("skill_id") == "ep-doc-b58"), None)
            assert row is not None and row.get("available") is True, (
                f"指令型技能在 {path} 被报成不可用（误伤）：{row}")


class TestProjectionAndMaterializationAgree:
    """跨边界闭环：投影说不可用，物化口就不许给它一个 ACTIVE 执行体。

    写成"两面对同一条目给同向读数"而不是各测各的，是为了让任何一侧单独放宽都立刻红。
    """

    def _restore(self, svc, registry):
        from neurova.skills.market_registry import restore_market_skills_from_service

        restore_market_skills_from_service(svc, registry)

    def test_shellIsNotRegisteredAsAnExecutable(self, tmp_path):
        svc = _svc(tmp_path)
        _makeShell(svc, tmp_path, "shell-reg-b58")
        reopened = _svc(tmp_path)

        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        self._restore(reopened, registry)

        assert registry.get_skill("shell-reg-b58") is None, (
            "空壳被注册进了执行表——工具 schema 与提示词目录会把它画成可调用")
        assert reopened.get_skill_info("shell-reg-b58").get("available") is False, (
            "物化口拒了，投影面却说可得：两处判定已经分叉")

    def test_docSkillIsBothRegisteredAndProjectedAvailable(self, tmp_path):
        svc = _svc(tmp_path)
        _install(svc, tmp_path, "doc-reg-b58", files={"SKILL.md": SKILL_MD})
        reopened = _svc(tmp_path)

        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        self._restore(reopened, registry)

        assert registry.get_skill("doc-reg-b58") is not None, "指令型技能没被恢复——本批把它误杀了"
        assert reopened.get_skill_info("doc-reg-b58").get("available") is True

    def test_visibilityGateRefusesShellAndKeepsRealOne(self, tmp_path):
        """三闸之外加第四闸：轮级可见性（→ 工具 schema／目录）必须把空壳判为不可调。"""
        from neurova.skills.skill_visibility import VisibleSkill

        def _visible(entry):
            return VisibleSkill(name=entry["name"], skill_id=entry["id"],
                                pool="agent", owner_key="default", entry=entry)

        shell = _visible({"id": "x", "name": "x", "enabled": True, "available": False,
                          "unavailableReason": "落盘无可执行构件", "manifest": {}, "usage": {}})
        real = _visible({"id": "y", "name": "y", "enabled": True, "available": True,
                         "manifest": {}, "usage": {}})
        assert shell.enabled is False, (
            "构件缺失的条目仍被判可调——它进了 LLM 的工具表却必然失败")
        assert real.enabled is True, "第四闸把正常条目也拦了"
