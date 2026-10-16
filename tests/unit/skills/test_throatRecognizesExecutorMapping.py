# -*- coding: utf-8 -*-
r"""执行咽喉必须认代码映射表：同一只技能在读面"可用"、在咽喉"跑不动"这条分叉收掉（§6-280 甲·第②批）。

复核实状（真账本现读，探针即用即删；改前四条读数）：
`data/agents/default/skills/manifest.json` 今天 1 条 `web-search`，`enabled=True`、目录里只有
`manifest.json`、账本没有构件摘要。三条问句给出**相反**的答案——

    读面   `availabilityFor("web-search")`            ⇒ `{'available': True}`（映射型，§6-272 甲案认它）
    咽喉   `call_skill("web-search", query=…)`        ⇒ `success=False`、`error='No entry point found for skill'`
    注册表 `market_registry._build_executable_skill`  ⇒ 真造得出 `ExecutorBackedSkill`

即"面板画成可用、点执行必失败"。而 §6-272 那套读面判据里，映射那一支**一格都没咬过**
（`tests/unit` 全仓 grep `hasExecutorMapping`／`_MARKET_EXECUTORS` 零命中，只有档头注释提了一句），
所以这条分叉既没人测也没人守。

本批两件事（用户裁定原文：「甲｜先问映射表，再回落盘」）：
① 咽喉按 `hasExecutorMapping` 分流：映射走 `ExecutorBackedSkill`，落盘走现路，一条咽喉一个口径；
② 映射表收成一份表示——`_MARKET_EXECUTORS` 的值原先是**类名字符串**，而构造处另写了一张
   `{"WebSearchSkillExecutor": WebSearchSkillExecutor}` 内联表，加一只映射要改两处、漏第二处只有
   一条 warning 加静默降级（教义第 6 条）。现在表里存工厂，`hasExecutorMapping` 与构造读同一张表。

**契约面写清，不许含糊**：映射型没有 `artifact_digest`，完整性语义是「**由代码本体负责、不受安装门
摘要管辖**」——不是"摘要缺失所以放行"（那句是巧合不是契约，见 §6-283 第一条）。所以本批必须
反向钉住"跑通后账本里仍不许出现摘要键"，也必须有对照格证明**非映射的空壳照旧拒**（否则分流就
等于把盘上什么都没有的条目一律放行）。

锁的形状也是判据，不是注释：`ExecutorBackedSkill` 把同步执行体放进 `loop.run_in_executor` 的
**工作线程**，而 `self._lock` 取自 `creation_governance.shared_lock(skills_dir)`——按目录共享、
重入只在同线程成立。所以映射那一支**必须出了锁再 await**；落盘那一支反过来必须持锁（批 61 已钉）。
两支的差别由下面那格拿"执行体回调本服务"的真路钉住，带 8s 限时：坏实现下它要自己红并说清原因，
不许靠挂死表态（形态集 256）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neurova.security import artifact_digest as AD
from neurova.skills import market_registry
from neurova.skills.executor import BaseSkillExecutor, ExecutorBackedSkill, SkillResult
from neurova.skills.skill_install_gate import reset_install_gate_scanner
from neurova.skills.skill_service import SkillService

MAPPED_ID = "b63-mapped-shell"
PLAIN_ID = "b63-plain-shell"
SKILL_MD = "# demo\n指令型技能的说明体。\n"
ENTRY = "def main(**kwargs):\n    return {'ok': True, 'saw': sorted(kwargs)}\n"


class _ProbeExecutor(BaseSkillExecutor):
    """同协议的探针执行体：只证明"经真桥接跑得起来"，不碰网。

    `callbackInto` 为真时在**自己的线程**里回调本服务——这正是主线程若持锁 await 就会死锁的那条路。
    """

    def __init__(self, skillId: str, callbackInto: bool = False):
        super().__init__(skill_id=skillId, skill_name="批 63 探针映射执行体")
        self.callbackInto = callbackInto

    def execute(self, params=None, *args, **kwargs) -> SkillResult:
        seen = dict(params or {})
        if self.callbackInto:
            same = SkillService(agent_id="b63-cb",
                                skills_dir=os.environ["B63_SKILLS_DIR"])
            seen["listedWhileAwaiting"] = len(same.list_skills())
        return SkillResult(success=True, output={"executorRan": self.skill_id, "params": seen})


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    """把全局映射表换成一份快照再跑（monkeypatch 自动还原）。

    刻意**不**借生产缝做隔离：新缝不在场时，autouse 夹具一崩就把整档全打成 setup ERROR，
    行为红一条都看不见（教义第 3 条要的是红在断言上）。装配隔离与被测 API 分开放。
    """
    reset_install_gate_scanner()
    monkeypatch.setattr(market_registry, "_MARKET_EXECUTORS",
                        dict(market_registry._MARKET_EXECUTORS))
    yield
    reset_install_gate_scanner()


def _svc(tmp_path, agent="b63-agent"):
    return SkillService(agent_id=agent, skills_dir=str(tmp_path / "installed"))


def _installShell(svc, tmp_path, skill_id: str, files=None) -> Path:
    """装一只"目录里只有 manifest.json"的空壳条目——与真账本里 `web-search` 同形。

    `files` 给非空时是"装上去就带构件"的那一形（批 64 之后两形分道：空壳不钉、有构件必钉）。

    取值必须同形是硬要求（形态集 239）：若给映射那一支挑一只盘上有 `.py` 的样本，
    "分流"与"什么都不判一律放行"两种实现就同解，格子抓不住东西。
    """
    src = (tmp_path / "src") / skill_id
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0",
                    "source": "marketplace"}, ensure_ascii=False), encoding="utf-8")
    for name, body in (files or {}).items():
        (src / name).write_text(body, encoding="utf-8")
    result = svc.install_skill(str(src), skill_id=skill_id)
    assert result.get("success") is True, f"装配本身没成功，样本不成立：{result}"
    return svc.skills_dir / skill_id


def _registerProbe(skill_id: str, callbackInto: bool = False):
    """把探针执行体注入映射表（写的是夹具那份快照，不是全局）。

    这里按表形状注入而不是调生产缝，是为了让"咽喉不认映射"这件事在改前就红在**行为**上：
    改前的表存的是**类名字符串**、构造处另有第二张 `{类名: 类}` 内联查表，所以一条新映射
    让 `hasExecutorMapping` 说 True 而构造那边造不出东西——那正是本批要收的第二处缺陷现场。
    生产缝自己由 `TestMappingTableIsOneRepresentation` 那五格咬，不靠这里代证。
    """
    market_registry._MARKET_EXECUTORS[skill_id] = (
        lambda: _ProbeExecutor(skill_id, callbackInto=callbackInto))


class TestThroatRecognizesExecutorMapping:
    def testMappedShellShapedEntryRunsThroughTheThroat(self, tmp_path):
        """本批的主红：同一只条目，读面说"可用"，咽喉就得真跑出值。"""
        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, MAPPED_ID)
        _registerProbe(MAPPED_ID)

        outcome = asyncio.run(svc.call_skill(MAPPED_ID, query="ping"))

        assert outcome.get("success") is True, (
            f"映射型在咽喉里仍跑不动（读面却说它可用）：{outcome}")
        assert (outcome.get("result") or {}).get("executorRan") == MAPPED_ID, (
            f"跑的不是那只执行体：{outcome}")
        assert (outcome.get("result") or {}).get("params", {}).get("query") == "ping", (
            f"参数没直通：{outcome}")

    def testUnmappedShellWithSameDiskShapeIsStillRefused(self, tmp_path):
        """对照格：盘上同形、只是没在册映射里 ⇒ 照旧拒——分流不等于"什么都没有也放行"。

        这一格设计成改前改后都绿（它钉的是本批**不许越界**的那一侧），红自证时它不该进失败集。
        """
        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, PLAIN_ID)

        outcome = asyncio.run(svc.call_skill(PLAIN_ID, query="ping"))

        assert outcome.get("success") is False, f"非映射空壳被执行了：{outcome}"
        assert "No entry point found" in str(outcome.get("error") or ""), (
            f"拒因换了说法（那不是本批该动的东西）：{outcome}")

    def testMappedLegNeverPinsAnArtifactDigest(self, tmp_path):
        """§6-283 第①条：映射那一趟自己**不首钉、不改钉**（完整性由代码本体负责，§6-280 甲）。

        原来说法写成"账本里不许出现摘要键"，实测把这条断错了对象：摘要是**装侧**钉的
        （`install_skill` 对一只只有 `manifest.json` 的目录当场首钉，本会话探针现读），
        不是咽喉这一趟写的。所以本格断的是咽喉自己的责任：跑之前没钉 ⇒ 跑之后仍不许有；
        跑之前钉过 ⇒ 跑之后那颗不许变。反过来读成"摘要缺失所以放行"就把闸门读没了。
        """
        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, MAPPED_ID)
        _registerProbe(MAPPED_ID)

        def ledgerDigest():
            return str(json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
                       .get(MAPPED_ID, {}).get(AD.DIGEST_FIELD) or "")

        # 把落盘账本改回"没钉"那一形（存量条目与旁路落地就是这形），然后**经装配点**重开实例，
        # 不手改内存态——否则测的是我造的中间状态，不是生产会读到的那份。
        ledger = json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
        ledger[MAPPED_ID].pop(AD.DIGEST_FIELD, None)
        Path(svc.manifest_path).write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        svc = _svc(tmp_path)
        assert (svc._skills.get(MAPPED_ID) or {}).get(AD.DIGEST_FIELD) is None, "样本没做成「未钉」那一形"

        assert asyncio.run(svc.call_skill(MAPPED_ID, query="ping")).get("success") is True
        assert ledgerDigest() == "" and not svc._skills[MAPPED_ID].get(AD.DIGEST_FIELD), (
            "映射那一趟把空壳首钉成了构件权威——日后真把字节补进这个目录，"
            "反而会被这份读数判成篡改（§6-267 同一族）")

        pinned = "sha256:" + "0" * 64
        ledger = json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
        ledger[MAPPED_ID][AD.DIGEST_FIELD] = pinned
        Path(svc.manifest_path).write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        svc = _svc(tmp_path)
        assert asyncio.run(svc.call_skill(MAPPED_ID, query="ping")).get("success") is True
        assert ledgerDigest() == pinned, f"映射那一趟改了已钉的摘要：{ledgerDigest()!r} ≠ {pinned!r}"

    def testMappedLegIgnoresDiskDigestWhileTheDiskLegStillEnforcesIt(self, tmp_path):
        """两条腿对同一份字节给出**不同**的正确答案，这一对就是"一个咽喉一个口径"的边界。

        映射型的字节不在盘上，盘上那份被动过不构成篡改证据 ⇒ 映射腿照跑；而同一状态下把映射撤掉，
        落盘腿必须按摘要不符拒——少一边都不算证到：只断"映射腿照跑"可能是整条咽喉都不看摘要了。

        **本批改过样本取法（A/B 抓出来的跨批交互，不是环境噪声）**：这一格原来装的是空壳、
        再往目录里补一份 `main.py`，靠"装侧把空壳钉过"来制造摘要不符。批 64（§6-290）把装侧改成
        "落盘没构件就不钉"，那条路径的正确答案随之翻成"**该跑得动**"——于是本格在基线上复跑三次全绿、
        在本批侧红。按回归处置：改成装时就带真字节（有构件必钉，两批都认同这条）、再把那份字节改掉，
        本格要钉的那件事（两条腿对同一份字节给不同答案）一字不改；"补进真字节应当跑得动"那一半
        现在由 `test_installDoesNotPinShellAsAuthority.py` 的第 2 格负责。
        """
        svc = _svc(tmp_path)
        installed = _installShell(svc, tmp_path, MAPPED_ID, files={"main.py": ENTRY})
        _registerProbe(MAPPED_ID)
        assert json.loads(Path(svc.manifest_path).read_text(encoding="utf-8")) \
            .get(MAPPED_ID, {}).get(AD.DIGEST_FIELD), \
            "样本前提不成立：带构件的包装完就该钉好（没钉则这一格测不到摘要门）"

        (installed / "main.py").write_text(
            "def main(**kwargs):\n    return {'sneaked': True}\n", encoding="utf-8")

        mapped = asyncio.run(svc.call_skill(MAPPED_ID, query="ping"))
        assert mapped.get("success") is True, (
            f"映射腿被盘上摘要挡住了（它的完整性在代码本体，不在这份字节）：{mapped}")
        assert (mapped.get("result") or {}).get("executorRan") == MAPPED_ID, (
            f"跑的不是映射执行体（盘上那份被改过的 main.py 被执行了？）：{mapped}")

        del market_registry._MARKET_EXECUTORS[MAPPED_ID]
        onDisk = asyncio.run(_svc(tmp_path).call_skill(MAPPED_ID, query="ping"))
        assert onDisk.get("success") is False, (
            f"落盘腿也没拦（那摘要门整条都松了）：{onDisk}")
        assert AD.REASON_MISMATCH in str(onDisk.get("error") or ""), (
            f"落盘腿拒了，但拒因不是构件摘要不符：{onDisk}")


    @pytest.mark.parametrize("skillId,expected", [(MAPPED_ID, True), (PLAIN_ID, False)])
    def testAvailabilityAndThroatAgreeOnTheSameEntry(self, tmp_path, skillId, expected):
        """名实一致那条（§6-280 的全部价值所在）：同一个问句，读面与咽喉不许相反。

        两面各跑一次而不是只看读面：`available=True` 而 `call_skill` 失败，正是本机 `web-search`
        今天的实状；反过来 `available=False` 却跑得动也是分叉（那说明读面多设了一道闸）。
        """
        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, skillId)
        if skillId == MAPPED_ID:
            _registerProbe(skillId)

        available = bool(svc.availabilityFor(skillId).get("available"))
        ran = bool(asyncio.run(svc.call_skill(skillId, query="ping")).get("success"))

        assert available is expected, f"{skillId} 读面 available 应成 {expected}：{available}"
        assert ran is available, (
            f"{skillId} 读面说 {available}、咽喉跑出 {ran}——两条路两个口径就是本批要收的那条分叉")

    def testMappedExecutorCanCallBackIntoTheLibraryWithinTimeout(self, tmp_path):
        """映射那一支必须出了锁再 await：执行体在自己线程里回调本服务，得跑得完。

        坏实现（在 `with self._lock:` 里 await 桥接体）当场死锁——`shared_lock(skills_dir)` 按目录
        共享，主线程持锁 await、worker 等锁。所以这格自带 8s 限时并**把超时转成会说话的 red**，
        不许靠挂死或整轮被打断来表态（形态集 256）。
        """
        svc = _svc(tmp_path, agent="b63-cb")
        _installShell(svc, tmp_path, MAPPED_ID)
        _registerProbe(MAPPED_ID, callbackInto=True)
        os.environ["B63_SKILLS_DIR"] = str(svc.skills_dir)

        async def drive():
            return await asyncio.wait_for(
                svc.call_skill(MAPPED_ID, query="cb"), timeout=8)

        try:
            outcome = asyncio.run(drive())
        except Exception as exc:  # noqa: BLE001 - 超时/取消的异常类名各版本不一，一律转成会说话的红
            pytest.fail(f"映射执行体回调本服务没跑完（{type(exc).__name__}: {exc}）——"
                        "这一支是在工作线程里跑的，说明咽喉持着 shared_lock 在 await")
        finally:
            os.environ.pop("B63_SKILLS_DIR", None)

        assert outcome.get("success") is True, f"回调那一趟失败了：{outcome}"
        assert (outcome.get("result") or {}).get("params", {}).get("listedWhileAwaiting") == 1, (
            f"回调里读到的条目数不对：{(outcome.get('result') or {}).get('params')}")


    def testMappedLegRefusesAnExplicitMethodName(self, tmp_path):
        """映射那一支没有"方法名"这个概念——签名里的 `method` 不许被静默吞掉。

        咽喉的 `method` 参数对映射型是无定义的：接了不用＝在契约上承诺一件不做的事
        （本仓刚在另一张票上点名过这一形）。所以要么实现它，要么如实拒；这里选如实拒。
        """
        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, MAPPED_ID)
        _registerProbe(MAPPED_ID)

        outcome = asyncio.run(svc.call_skill(MAPPED_ID, method="run", query="ping"))

        assert outcome.get("success") is False, f"传了 method 却被当成 main 跑了：{outcome}"
        assert "method" in str(outcome.get("error") or ""), (
            f"拒因没点名是哪一个参数被拒：{outcome}")


    def testDisabledMappedEntryIsStillRefusedByTheEnabledGate(self, tmp_path):
        """对照格：分流不许顺手放宽 `enabled` 闸——停用了就该拒。

        设计成改前改后都绿（改前整条咽喉都走盘，自然也拒），它的用处是给 M_D 那枚变异当针：
        谁把映射腿改成"在册映射就跑，不看行级开关"，这格当场红。
        """
        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, MAPPED_ID)
        _registerProbe(MAPPED_ID)
        ledger = json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
        ledger[MAPPED_ID]["enabled"] = False
        Path(svc.manifest_path).write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")

        outcome = asyncio.run(_svc(tmp_path).call_skill(MAPPED_ID, query="ping"))

        assert outcome.get("success") is False, f"停用的映射条目被执行了：{outcome}"
        assert "disabled" in str(outcome.get("error") or "").lower(), (
            f"拒因不是停用那一闸：{outcome}")

    def testMappingAloneDoesNotConjureAnUnlistedSkill(self, tmp_path):
        """对照格：表里有映射而**账本不认识**这条 ⇒ 仍报 `Skill not found`。

        契约放宽的边界就到"账本认识的条目"为止（§6-283 写的不可逆点是那一条，不是这条）；
        这条格子给"把分流挪到账本查询之前"那种改法当针。
        """
        svc = _svc(tmp_path)
        _registerProbe("b63-never-installed")

        outcome = asyncio.run(svc.call_skill("b63-never-installed", query="ping"))

        assert outcome.get("success") is False, "不在账本里的映射被凭空跑起来了"
        assert "not found" in str(outcome.get("error") or "").lower(), f"拒因换了出处：{outcome}"


class TestMappingTableIsOneRepresentation:
    def testRegisteringOneEntryIsSeenByBothReadPaths(self, tmp_path):
        """加一只映射只许改一处：问"有没有映射"与"造执行体"必须读同一张表。

        改前的实状是两份表示——表里存类名，构造处另写一张 `{类名: 类}` 内联查表；漏第二处时
        `hasExecutorMapping` 说 True 而构造返 None，只有一条 warning（静默降级）。
        """
        market_registry.registerExecutorMapping("b63-late-bound", lambda: _ProbeExecutor("b63-late-bound"))

        assert market_registry.hasExecutorMapping("b63-late-bound") is True, "问句没认这条新映射"
        built = market_registry.buildMappedExecutable("b63-late-bound", "")
        assert isinstance(built, ExecutorBackedSkill), (
            f"问句认得、构造造不出（{built!r}）——那张表又被拆成了两份表示")

    def testRegistrationLegSharesThatSameTable(self, tmp_path):
        """注册面（恢复口/链路口用的 `_build_executable_skill`）必须是**第三条**同表读路。

        这一格不是凑数：本批把表改成 id→工厂之后，第一版只改了构造那处，注册面仍留着旧的
        `{类名: 类}` 内联查表——于是 `web-search` 在注册面被静默降级成裸壳，
        被 `tests/unit/skills/test_market_registry.py` 那两格既有判据当场抓到
        （`AttributeError: 'Skill' object has no attribute '_get_parameters'`）。
        三条读路一起测，才拦得住"收口收到一半"。
        """
        market_registry.registerExecutorMapping(
            "b63-third-read", lambda: _ProbeExecutor("b63-third-read"))

        built = market_registry._build_executable_skill("b63-third-read", "注册面那一条", "")

        assert isinstance(built, ExecutorBackedSkill), (
            f"注册面造出的是 {type(built).__name__}（{built!r}）——那条腿没经同一张表，"
            "映射在册却被降级成壳，面板画成可用而工具面动不了")
        assert built.name == "b63-third-read", f"注册名被换了：{built.name}"

    def testTheBuiltinRegistrationLegStillBuildsTheRealExecutor(self, tmp_path):
        """内置那一条在**注册面**上也得是真执行体（既有那两格红过的就是这里，别只测新加的）。"""
        built = market_registry._build_executable_skill("web-search", "网络搜索", "")

        assert isinstance(built, ExecutorBackedSkill), (
            f"web-search 在注册面被降级成 {type(built).__name__}——工具面从此拿不到参数 schema")
        assert built._get_parameters().get("query"), "执行体的参数 schema 没露出来（模型会不知道怎么传参）"

    def testTableValuesAreFactoriesNotClassNameStrings(self):
        """表里存的必须是可调用体；"名字字符串＋第二张查表"就是分叉的本体。"""
        for skillId, entry in market_registry.executorMappings().items():
            assert callable(entry), (
                f"映射 {skillId} 存的是 {type(entry).__name__}（{entry!r}）——"
                "值若是类名，构造处就得再查一张表，加映射就变成两处一起改")

    def testBuiltinWebSearchMappingStillBuildsTheRealExecutor(self):
        """内置那一条不许被收口时弄丢：只构造，不执行（执行会出网）。"""
        assert market_registry.hasExecutorMapping("web-search") is True
        built = market_registry.buildMappedExecutable("web-search", "网络搜索")

        assert isinstance(built, ExecutorBackedSkill), f"内置映射造不出执行体：{built!r}"
        assert built.name == "web-search", f"执行体挂的名字不对：{built.name}"


class TestChainReadsTheMappedOutcome:
    def testChainStepOnMappedSkillCompletesWithDictContract(self, tmp_path):
        """§6-283 第④条：链上那一档本批要真跑一次，不许只声称"已能跑"。

        如实记两句：① `SkillChainExecutor(` 在 `neurova/` 内**零构造点**（现读），所以这格证的是
        "链经真咽喉拿到的是一份 dict 契约的执行结果、映射那一支在链上也到得了"，**不**证它在生产里在跑；
        ② 链把整包输入塞成一个关键字 `input_data=`（`skill_chain_executor.py:270`），字段名因此不是
        直通的——那是另一件事，本批不改（改了会动每一只落盘技能收到的形状），登记在案。
        """
        from neurova.skills.models import SkillChain, SkillChainStep, StepStatus
        from neurova.skills.skill_chain_executor import SkillChainExecutor

        svc = _svc(tmp_path)
        _installShell(svc, tmp_path, MAPPED_ID)
        _registerProbe(MAPPED_ID)
        chain = SkillChain(chain_id="b63-chain", name="映射那一支", steps=[
            SkillChainStep(step_id="s1", skill_id=MAPPED_ID)])

        outcome = asyncio.run(SkillChainExecutor(skill_service=svc).execute_chain(
            chain, {"query": "ping"}))

        assert outcome.success is True, (
            f"整链没成，步骤读数：{[(r.status, r.error) for r in outcome.results]}")
        stepResult = outcome.results[0]
        assert stepResult.status == StepStatus.COMPLETED, (
            f"链上那一步的状态不是完成：{stepResult.status} / {stepResult.error}")
        assert (stepResult.output_data or {}).get("executorRan") == MAPPED_ID, (
            f"链从咽喉读到的不是执行体的那份 result（dict 契约没接上）：{stepResult.output_data}")

