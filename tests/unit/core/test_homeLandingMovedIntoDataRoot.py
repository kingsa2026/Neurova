# -*- coding: utf-8 -*-
"""`~/.neurova/` 那族配置与状态收进数据根（用户 2026-10-14 第二道裁定）。

四族：LLM 供应商凭据 `config/providers.json`、审计库 `audit.db`、治理白名单
`config/governance_whitelist.json`、技能安装根 `skills/installed`。

为什么该收（复核实状，两路独立调研 + 自己复算）：
- 数据根是本仓唯一的"运行期产物"锚点，且 `NEUROVA_DATA_DIR` 是它唯一注入口；这四族
  各在 `Path.home()` 上另起一址，测试期直接写进开发者主目录（实测
  `~/.neurova/config/governance_whitelist.json` 的 `updated_at` 就是某条用例今天写的）。
- 部署面**没有**"就该放主目录"的理由：docker-compose 与 helm 只挂 `/app/data`，
  容器里 home 落点反而是悬空的（重启即失）；桌面打包配置不提 `.neurova` 目录。
- 凭据进数据根早有先例可抄：`web_reach/credentials.py`、`desktop_audit.py` 的
  `dataPath("desktop_action_audit.db")`；`secret_store_clean.py:73-84` 更自陈
  "默认落点曾是 Path.home()/.neurova，绕过数据根"——同族已收过一次。

旧落点不空手：走 `data_root.adoptLandingFrom`（空缺才搬、两侧在场不覆盖并点名）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from neurova.core.data_root import DATA_ROOT_ENV

NEUROVA = Path(__file__).resolve().parents[3] / "neurova"


@pytest.fixture()
def landingRoots(tmp_path, monkeypatch):
    """把数据根与"家"都指到临时目录：谁写错了地方，当场就能看见。"""
    dataRoot = tmp_path / "dataRoot"
    fakeHome = tmp_path / "fakeHome"
    fakeHome.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV, str(dataRoot))
    monkeypatch.setattr("pathlib.Path.home", lambda: fakeHome)
    return dataRoot, fakeHome


def _nothingUnder(home: Path) -> list:
    return sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file() or p.is_dir())


class TestFourFacesLandInTheDataRoot:
    def test_providerCredentialsWrittenIntoDataRootNotHome(self, landingRoots):
        from neurova.llm.provider_manager import get_provider_manager, reset_provider_manager

        dataRoot, fakeHome = landingRoots
        reset_provider_manager()
        try:
            manager = get_provider_manager()
            assert manager._config_path.is_absolute()
            assert dataRoot in manager._config_path.parents, (
                "供应商配置仍不在数据根下：%s" % manager._config_path
            )
            assert manager._config_path.name == "providers.json"
            assert manager._config_path.exists(), "构造后没把凭据文件落在数据根"
        finally:
            reset_provider_manager()
        assert _nothingUnder(fakeHome) == [], "仍在用户主目录创建东西：%s" % _nothingUnder(fakeHome)

    def test_auditDbWrittenIntoDataRootAndProbeListsTheSamePath(self, landingRoots):
        from neurova.core.db_indexes import resolve_probe_paths
        from neurova.security import audit_logger as auditMod

        dataRoot, fakeHome = landingRoots
        # 两层单例都要归零：`get_audit_logger` 是 @lazySingleton("_audit_logger")，
        # 只清 `AuditLogger._instance` 的话，族跑里前面谁先建过，这里就拿回那只
        # 指着别人落点的旧 logger（单跑绿、族跑红就是这个形状）。
        held = (auditMod.AuditLogger._instance, auditMod._audit_logger)
        auditMod.AuditLogger._instance = None
        auditMod._audit_logger = None
        try:
            logger = auditMod.get_audit_logger()
            assert logger.log_config_change("u-1", "temperature", 0.2, 0.7) is not False
            auditDb = dataRoot / "audit.db"
            assert auditDb.exists(), "审计库没落进数据根：%s" % logger._db_path
            with sqlite3.connect(str(auditDb)) as con:
                rows = con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
            assert rows >= 1, "写了一条而库里没有"
            # 探针与写侧必须取同一处：否则索引体检对着一个不存在的库报"缺索引"
            assert str(auditDb) in resolve_probe_paths(), "探针清单里没有新落点（第二推导未改）"
        finally:
            auditMod.AuditLogger._instance, auditMod._audit_logger = held
        assert _nothingUnder(fakeHome) == [], "审计库仍写在主目录：%s" % _nothingUnder(fakeHome)

    def testGovernanceWhitelistInDataRootAndDistinctFromSettings(self, landingRoots):
        from neurova.security.governance import get_governance, reset_governance
        from neurova.security.governance_settings import settings_path

        dataRoot, fakeHome = landingRoots
        reset_governance()
        try:
            policy = get_governance()
            policy.add_whitelist_entry(pattern="git status", match_type="prefix", note="判据用例")
            entries = policy.list_whitelist_entries()
            assert entries, "白名单条目没被收下"
            written = sorted(dataRoot.rglob("governance_whitelist.json"))
            assert written, "白名单没落进数据根"
            payload = json.loads(written[0].read_text(encoding="utf-8"))
            assert payload["entries"], "落盘了但 entries 为空——写侧与内存态不同步"
            # 这两件是**不同的东西**（settings 是 9 个标量开关，whitelist 是条目表），
            # 收落点时若把它们并成一个文件就是擅自改语义。
            assert written[0] != Path(settings_path()), "白名单与设置被并成同一文件"
        finally:
            reset_governance()
        assert _nothingUnder(fakeHome) == [], "白名单仍写在主目录：%s" % _nothingUnder(fakeHome)

    def testSkillHubRootIsUnderDataRootAndNotCreatedInHome(self, landingRoots):
        from neurova.skills.hub_client import SkillHubClient

        dataRoot, fakeHome = landingRoots
        client = SkillHubClient()
        assert dataRoot in Path(client._installed_dir).parents, (
            "技能安装根仍在主目录：%s" % client._installed_dir
        )
        assert _nothingUnder(fakeHome) == [], (
            "构造即在家目录建目录（今日实测那里就是个空壳）：%s" % _nothingUnder(fakeHome)
        )


class TestLegacyHomeCopiesAreAdopted:
    def test_existingProvidersFileIsMovedIntoDataRootOnce(self, landingRoots):
        # 直接问落点函数，不借 get_provider_manager：构造会把"没有文件"种成内置默认，
        # 断言就会被那次改写盖住——收养这一格要看的只是搬没搬、内容变没变。
        from neurova.llm.provider_manager import _default_config_dir

        dataRoot, fakeHome = landingRoots
        legacy = fakeHome / ".neurova" / "config"
        legacy.mkdir(parents=True)
        legacyFile = legacy / "providers.json"
        original = json.dumps({"providers": [{"id": "glm", "name": "GLM"}],
                              "default_provider_id": "glm"}, ensure_ascii=False)
        legacyFile.write_text(original, encoding="utf-8")

        targetDir = _default_config_dir()

        moved = targetDir / "providers.json"
        assert moved.exists(), "旧凭据没被收养进数据根"
        assert moved.read_text(encoding="utf-8") == original, (
            "收养改了内容——用户那 17 个 provider 与 9 份加密凭据会被静默丢掉"
        )
        assert not legacyFile.exists(), "旧物留在原地＝同一份凭据两个落点"
        # 按用户身份分文件的每一份都要跟着搬
        (legacy / "providers.user-alice.json").write_text(original, encoding="utf-8")
        _default_config_dir()
        assert (targetDir / "providers.user-alice.json").exists(), "scope 版没被收养"

    def test_bothSidesPresentDoesNotOverwriteAndIsNamed(self, landingRoots):
        from neurova.llm.provider_manager import _default_config_dir

        dataRoot, fakeHome = landingRoots
        legacyDir = fakeHome / ".neurova" / "config"
        legacyDir.mkdir(parents=True)
        legacyFile = legacyDir / "providers.json"
        legacyFile.write_text(json.dumps({"providers": [], "default_provider_id": "legacy-wins"}),
                              encoding="utf-8")
        # 新落点先在场（这一格必须知道子目录名，因为它要"先造出新那一份"；
        # 名字若改，上一格「落在数据根下」仍会指出真落点，不会只留一处假绿）
        targetDir = dataRoot / "llm"
        targetDir.mkdir(parents=True)
        (targetDir / "providers.json").write_text(
            json.dumps({"providers": [], "default_provider_id": "new-wins"}), encoding="utf-8")

        got = _default_config_dir()

        assert json.loads((got / "providers.json").read_text(encoding="utf-8"))[
            "default_provider_id"] == "new-wins", "旧落点把已生效的新配置盖回去了"
        assert legacyFile.exists(), "两侧同时在场时旧物被静默搬走（应保留并点名）"


class TestNoNewHomeLandingIsAllowed:
    """只降不升：生产码里 `.neurova` 家目录落点必须只剩这张表。

    四族收口后仍在表里的，是**另批待裁**的邻族（rbac 零生产调用方、knowledge 配置、
    插件与图像/评测的裸相对名、企微媒体目录）；`core/data_root.py` 那一条是
    "收养旧落点"用的唯一 helper，必须有——少了它收养就会回退到各处手拼 home。
    """

    _EXPECTED = {
        "benchmark/__init__.py": 1,
        "channels/wecom_aibot.py": 1,
        "core/data_root.py": 1,
        "image_pipeline/__init__.py": 1,
        "knowledge/config.py": 1,
        "security/rbac.py": 1,
    }

    def test_homeLandingOffendersAreExactlyTheRegisteredOnes(self):
        import ast

        offenders = {}
        for py in sorted(NEUROVA.rglob("*.py")):
            if "__pycache__" in str(py):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            docStringIds = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            # 只认"以 .neurova 打头的路径段"：`.neurova_token_secret`、
            # `.neurova_shutdown_sentinel`（环境变量名）与 `api.neurova.dev`（URL）
            # 都含这个子串，按子串数会假红、也会把人引去改错对象。
            hits = [
                node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docStringIds
                and (node.value == ".neurova" or node.value.startswith(".neurova/"))
            ]
            if hits:
                offenders[py.relative_to(NEUROVA).as_posix()] = len(hits)
        assert offenders == self._EXPECTED, (
            "家目录落点面与本批裁定后的期望表不符（新增即红；修好了不摘表也红）：\n%s"
            % offenders
        )

    def test_theOnlyHomeDerivationIsTheLegacyAdoptionHelper(self):
        """`data_root.py` 那一条必须待在收养 helper 里，不是又一处新落点。"""
        src = (NEUROVA / "core" / "data_root.py").read_text(encoding="utf-8")
        assert "def legacyHomeLanding(" in src, "收养端没了唯一取法，各处会回去手拼 home"
        body = src.split("def legacyHomeLanding(", 1)[1].split("\ndef ", 1)[0]
        assert '".neurova"' in body, "data_root 里那条 home 字面不在收养 helper 内"
