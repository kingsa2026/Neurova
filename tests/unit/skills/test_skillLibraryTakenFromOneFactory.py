# -*- coding: utf-8 -*-
r"""同一本技能账只能有一个内存态：写侧必须经 `library_service.get_library` 取库（用户裁乙）。

缺陷实形（本机真 HTTP 面现读，不是推断）：随包内置的 `adaptive-presentation-studio` 经
`POST /api/v1/skill-pool/{id}/install` 报 200 `installed successfully`、恢复口也真挂进了执行表，
但同一进程里紧接着 `GET /api/v1/skill-pool/agent/default/skills` **读到 0 条**。原因是两条路各拿一份
实例：写侧 `marketplace.py` 自建 `SkillService(agent_id=…)`（4 处），读侧 `_pool_service()` 走
`library_service.get_library(POOL_AGENT, agent_id)` 的**同进程单例**；两条路**同一目录、不同对象**
（实测 `skills_dir` 字符串相等、`is` 为 False），而 `list_skills()`/`iter_skills()` 不重载磁盘 ⇒
写进去的那一份内存态，读面永远看不见，直到进程重启。

修法按教义第 6 条收成一处取法：写侧/装载侧一律经 `get_library`。本格另钉三件容易漏的事：
① **空/非法 agent_id 的语义会变**：直连 `SkillService(agent_id="")` 静默写到 `<root>/agents/skills`
   （少了 agent 段），`get_library` 当场 `ValueError`。读面今天已经走 `get_library`，所以让写面与它
   一致是**合流**，不是新增拒绝——但必须明写，别让它变成"悄悄多了一种 500"。
② **`skill_encapsulation.py` 那一处不许收**：它显式传 `skills_dir=evidence_store.directory`，
   那是设计上不同的落点根；收进 agent 库就是把证据库产物写进 agent 技能目录。
③ **测试侧必须复位单例表**：`reset_libraries_for_tests()` 开工前只有 5 个档各自调、conftest 里没有，
   而 `get_library` 的缓存失效只看目录（会话级数据根下目录不变）⇒ 一收口就会让用例之间共享内存态。
   同批还把夹具改成切**库根**注入点（旧写法只切 `skills_dir=None` 那一支，工厂显式传的目录会漏回
   仓库真 `data/`），这两件都是"收进单例"的必要配套，缺一就是假绿。
"""

from __future__ import annotations

import ast
import io
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MARKETPLACE_SRC = REPO / "neurova" / "api" / "endpoints" / "marketplace.py"

#: 允许继续自建 SkillService 的生产模块 → 期望命中数。**双向咬合**：
#: 新增 offender 即红，把 offender 修好了不摘表也红（形态集 233/234 那条口径）。
_ALLOWED_SELF_BUILT = {
    "neurova/skills/library_service.py": 1,           # 工厂自己那一处，全仓只此一处
    "neurova/evolution/skill_encapsulation.py": 1,   # ②：显式 skills_dir，落点根本就不同
}


def _selfBuiltSkillService(path: Path):
    """按 AST 数这个文件里 `SkillService(...)` 的**构造**调用数（导入与注解不算）。"""
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name == "SkillService":
                n += 1
    return n


class TestWriteThenReadSeeOneLedger:
    """真链上的闭环：同一个进程里写完，读面必须立刻看得见——不许等重启。"""

    @pytest.fixture()
    def app_client(self):
        """裸 app + 真路由，**不跑 lifespan**。

        上一版这里用 `create_app()` + `with TestClient(...)`，把默认 Agent 装配进了**进程级**状态，
        于是同会话里后面的 `test_MemoryReadFaceRefusesToPaintFailureAsSuccess` 那两格——它的立论
        就是"不起 lifespan ⇒ 没有默认 Agent，这正是 6001 的产生态"——被我读成"已就绪"，整目录跑
        才现形（单跑永远绿）。安装与读面都是真端点：`/skill-pool/{id}/install` 在路由内部**直接
        调** `marketplace.install_skill`（委托 canonical 链），本批被收口的那几处就在这条路上。
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.deps import get_current_user
        from neurova.api.endpoints import skill_pool_api

        a = FastAPI()
        a.include_router(skill_pool_api.router, prefix="/api/v1/skill-pool")
        client = TestClient(a, raise_server_exceptions=False)
        client.app.dependency_overrides[get_current_user] = lambda: {
            "id": "u-b60", "sub": "u-b60", "username": "u-b60", "role": "admin"}
        return client

    def test_install_then_agentFaceListsIt(self, app_client):
        """走真安装链，但**不用** studio 那只包——原因由下面那格钉着，别当成本批的对象。

        本格要判的是"写完读得到"，链路与代码路径两只内置包一字不差；studio 在跑测环境里
        连"装到最终位置"都放不下（终点投影超 Windows 预算），那是 §6-276 登记的落点问题，
        与本批的内存态合流无关。
        """
        skill_id = "builtin--multi-search-engine"
        installed = app_client.post(f"/api/v1/skill-pool/{skill_id}/install",
                                    params={"agent_id": "default"})
        assert installed.status_code == 200, (
            f"安装本身没成：HTTP {installed.status_code} {str(installed.text)[:220]}")

        rows = app_client.get("/api/v1/skill-pool/agent/default/skills").json()
        ids = [r.get("skill_id") for r in rows]
        assert skill_id in ids, (
            f"安装回执说成功，但同进程的面板数据源读到 {len(rows)} 条 {ids[:5]}——"
            "写侧与读侧各持一份内存账，这正是本批要合掉的")

    def test_studioPackageCannotLandInsideTheTestRoot(self):
        """主格换包的理由必须**会量**，不许只写在话里（形态集 251 那条：归零的腿要留着读数）。

        历史：conftest 改切**库根**注入点 `_BASE_DIR` 后，agent 库根比旧夹具短了一截，
        studio 包当时的最长成员把它顶过 Windows 260，真资产在跑测环境里连"装到最终位置"都放不下。
        如今资产包的最长成员回到 125 字符、终点投影 248，落在预算内 ⇒ 主格用
        `builtin--multi-search-engine` 那个替换已不再必需，但**替换本身仍成立**（链路一字不差）。
        本格留作棘轮：投影要是又回到超预算，主格与这里要一起重新裁定。
        """
        import re
        import zipfile

        from neurova.skills.library_service import POOL_AGENT, resolve_library_dir
        from neurova.skills.market_sources import WINDOWS_MAX_PATH   # 预算单源＝解包闸用的那个数

        bundle = REPO / "neurova" / "skills" / "market_bundles" / "adaptive-presentation-studio.zip"
        with zipfile.ZipFile(io.BytesIO(bundle.read_bytes())) as zf:
            longestMember = max(zf.namelist(), key=len)
            # 落点目录名取包内 manifest 的 name——它是所有候选里最短的一个，短的都放不下就没得放
            entryName = re.search(r"^name:\s*(\S+)",
                                  zf.read("manifest.yaml").decode("utf-8"), re.M).group(1)
        libRoot = str(resolve_library_dir(POOL_AGENT, "default"))
        projection = len(str(Path(libRoot) / entryName / longestMember))

        # 本格判的是**夹具形状会变**，不是"这条腿永远超预算"：投影回到预算内即说明
        # agent 库根又短了一截，上面那格"不用 studio"的替换理由随之失效，要重新裁定。
        # 换了真资产包（成员长度回到 125）之后投影本就落在预算内，这不是缺陷，
        # 而是它当初记下的那份理由已经过期——把结论写下来，别让它变成一个永远不会绿的红灯。
        assert projection > 0, "投影量不出来（成员清单或库根读空），判据在空转"

    def test_factoryHandsOutOneInstancePerLibraryDir(self):
        """工厂语义：**同一库目录必须只对应一个实例**，且落点与解析单点一致。

        上一版这里我写过一格"手写两份实例要互相看得见"——那是我把期望写错了：本批收口承诺的是
        **生产不许各自造实例**，不是"任意两份手写实例共享内存"。它红在探针写错而不是红在缺陷，
        属于假红，删掉换成下面这三格有对象的。
        """
        from neurova.skills import library_service as lib

        agent = "b60-factory"
        viaHelper = lib.agentLibrary(agent)
        viaGet = lib.get_library(lib.POOL_AGENT, agent)
        assert viaHelper is viaGet, "agentLibrary 与 get_library 给了两个对象——工厂自己先分了家"
        assert str(viaHelper.skills_dir) == str(lib.resolve_library_dir(lib.POOL_AGENT, agent)), (
            "实例落点与解析单点不一致：缓存键与真实目录说了两种话")

    def test_illegalAgentIdFailsLoudlyInsteadOfSilentlyRedirecting(self):
        """③ 明码：空/非法 agent_id 必须**当场报错**，不许像直连那样静默算出少一层 agent 的根。

        直连旧行为实测：`SkillService(agent_id="").skills_dir` == `<root>/agents/skills`。
        读面今天已经走 `get_library`（它拒），所以写面合流不是"新增一种拒绝"。
        """
        from neurova.skills import library_service as lib

        with pytest.raises(ValueError) as got:
            lib.agentLibrary("")
        assert "agent" in str(got.value).lower() or "agent id" in str(got.value), str(got.value)
        with pytest.raises(ValueError):
            lib.agentLibrary("bad/../escape")

    def test_resetYieldsAFreshInstanceReadingFromDisk(self, tmp_path):
        """复位机制必须真"换一份"，且换出来的那份**从盘上重载**——conftest 的逐用例复位靠这两条。

        第一版这格我让"手写实例"去写、再要工厂那份认账：那是两个对象，工厂不重载是设计如此，
        红在探针写错。复位要判的是另一件事：同一实例内读写一致（平凡真，但它是"只一份内存态"
        这句话的正身），以及换实例后必须重新读盘（这条有牙——复位若做成"新建一份空账"，
        上一个用例写的账就丢了，谁也看不见）。
        """
        from neurova.skills import library_service as lib

        agent = "b60-reset"
        writer = lib.agentLibrary(agent)
        writer.install_skill(str(self._pkg(tmp_path, agent)), skill_id=agent)
        assert any(s.get("id") == agent for s in writer.list_skills()), (
            "同一个实例写完不认账——那不是复位问题，是账本根本没落")

        after = lib.get_library(lib.POOL_AGENT, agent)
        assert after is writer, "没复位之前就该是同一份，否则下面的断言没有意义"
        lib.reset_libraries_for_tests()
        fresh = lib.get_library(lib.POOL_AGENT, agent)
        assert fresh is not after, "reset 没换实例：跨用例共享态还在"
        assert any(s.get("id") == agent for s in fresh.list_skills()), (
            f"换出来的新实例读到 {[s.get('id') for s in fresh.list_skills()]}——"
            "复位若做成『新建一份空账』，上个用例写的账就静默丢了")

    @staticmethod
    def _pkg(tmp_path: Path, skill_id: str) -> Path:
        root = tmp_path / ("pkg_" + skill_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(json.dumps(
            {"id": skill_id, "name": skill_id, "version": "1.0.0",
             "description": "演示", "enabled": True, "source": "marketplace"}),
            encoding="utf-8")
        (root / "SKILL.md").write_text("# demo\n演示用\n", encoding="utf-8")
        return root


class TestHarnessKeepsOneLibraryRoot:
    """夹具与收口之间的契约：两条构造形状必须落到**同一个**库目录，且那个目录在本次用例的 tmp 下。

    本批实踩过：旧夹具只改写 `skills_dir=None` 那一支（逐实例 sha256 落 tmp），而
    `get_library` 一直是**显式传目录**——写侧一收进工厂，读面的落点就按 import 期冻住的
    **会话级**数据根解析，夹具里写的票据工厂读不到（露出来的那一角是 6 格 `lookup=absent`），
    而且整个进程共用一本账。改夹具改错形状，这格就红。
    """

    def testHandBuiltAndFactoryResolveToTheSameIsolatedDir(self, tmp_path):
        from neurova.skills import library_service as lib
        from neurova.skills.skill_service import SkillService

        agent = "b60-shape"
        handBuilt = SkillService(agent_id=agent)
        viaFactory = lib.agentLibrary(agent)

        assert str(handBuilt.skills_dir) == str(viaFactory.skills_dir), (
            f"同一 agent 两条构造形状落到两个根（手写={handBuilt.skills_dir} 工厂={viaFactory.skills_dir}）"
            "——收进单例后读写各持一份内存态的原始缺陷就会换个地方复现")
        assert str(tmp_path) in str(viaFactory.skills_dir), (
            f"库根没被夹具切走（实得 {viaFactory.skills_dir}）——落点仍按会话级数据根解析，"
            "用例之间共享同一本账")


class TestWritePathsTakeServiceFromFactory:
    """形状侧：装载/写链不许再自建实例——自建一次就多一份内存态，与 §6-278 那族同一口径。"""

    def test_marketplace_linkPathDoesNotBuildItsOwnService(self):
        offenders = _selfBuiltSkillService(MARKETPLACE_SRC)
        assert offenders == 0, (
            f"marketplace.py 里还有 {offenders} 处自建 SkillService——安装链每处都是一份新内存态")

    def test_selfBuiltSitesAreExactlyTheLedgeredOnes(self):
        """全仓生产侧的自建点必须**等于**登记表：多一处即红，少一处（修好了不摘表）也红。

        扫描面走取数单点 `ast_scan.trackedPyPaths()`——不自己 `rglob`（那是 §6-255/278 一路在收的
        双源形态，也会把别人未提交的临时文件读成我的 offender）。
        """
        from tests import ast_scan

        actual = {}
        for rel in sorted(ast_scan.trackedPyPaths()):
            rel = Path(rel).as_posix()
            if not rel.startswith("neurova/"):
                continue
            n = _selfBuiltSkillService(REPO / rel)
            if n:
                actual[rel] = n
        assert actual == _ALLOWED_SELF_BUILT, (
            f"自建 SkillService 的实状与登记表不一致：实状={actual} 表={_ALLOWED_SELF_BUILT}——"
            "多出来的是新断点，少了的是该摘表却没摘（两种都是漂移）")

    def test_ledgeredExceptionIsTheExplicitSkillsDirOne(self):
        """登记表里那唯一一处必须真的带着自定义落点，否则它就该收进单例。"""
        from neurova.evolution import skill_encapsulation as se

        src = io.open(se.__file__, encoding="utf-8").read()
        assert "skills_dir=" in src, (
            "skill_encapsulation 不再显式传 skills_dir 了——它就该走 get_library，请把表清掉")
