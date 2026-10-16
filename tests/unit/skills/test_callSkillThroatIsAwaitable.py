# -*- coding: utf-8 -*-
r"""技能执行咽喉 `SkillService.call_skill` 必须是协程：await 之后拿得到值，而不是拿到 coroutine。

裁定（用户拍甲·分两批）：本批**只做咽喉异步化**，映射表分流（§6-280）留下一批。

实状（开工前现场复算，三处都不在旧描述里）：
- `neurova/api/endpoints/skill_pool_api.py:460` 在 `async def execute_private_skill` 里
  **内联同步**调咽喉 ⇒ 入口是协程的技能，今天得到的是 `{"success": True, "result": <coroutine>}`
  ——一个没人 await 过的协程对象，被当成执行结果回给用户（"跑通了"是假的）。
- `neurova/skills/skill_chain_executor.py:270` 已经在 `await` 这个同步方法，随后还按
  `.output`/`.success`/`.error` **属性**取值 ⇒ 两处都与咽喉的 dict 契约不符。这条链在
  `neurova/` 内零构造点（只有一个测试构造它，且构造时不带 service，走的是"模拟执行"那一支），
  所以本批**不声称线上在炸**，只把它的契约改对并用直接调那条格的方式证明。
- 盘上（市场包与 builtin 目录）现读**没有**协程入口的技能 ⇒ 上面那条不是存量事故，而是口径洞：
  哪天有技能写成 `async def main`，咽喉就静默交出一个 coroutine 对象。

修法照本仓既有形态（`neurova/agent/sub_session.py:25` 的 `callSubSessionChannel`）：**在调用之前**
判 `iscoroutinefunction`，协程入口 `await`；同步入口照旧在本线程调用（**不**挪 `asyncio.to_thread`
——咽喉持的 `self._lock` 是 RLock，属线程级重入；技能体里回调本服务今天能过，一旦把技能体丢进
线程池，主线程持锁等线程、线程等锁，当场死锁）。这条不是偏好，本档第 2 格就是它的牙。
"""

from __future__ import annotations

import asyncio
import ast
import io
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neurova.skills.skill_install_gate import reset_install_gate_scanner  # noqa: E402
from neurova.skills.skill_service import SkillService  # noqa: E402

SKILL_MD = "# demo\n\n演示技能，说明文档。\n"


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _makePkg(base: Path, skillId: str, body: str) -> Path:
    src = base / skillId
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skillId, "name": skillId, "version": "1.0.0"}), encoding="utf-8")
    (src / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (src / "main.py").write_text(body, encoding="utf-8")
    return src


def _svcInstalled(tmp_path: Path, agentId: str, skillId: str, body: str) -> SkillService:
    """真装一份技能进真库（不 mock 咽喉；装完就用同一份实例调用它）。"""
    pkg = _makePkg(tmp_path / "src", skillId, body)
    svc = SkillService(agent_id=agentId, skills_dir=str(tmp_path / "installed"))
    result = svc.install_skill(str(pkg))
    assert result.get("success") is True, f"技能没装上：{result}"
    return svc


class TestThroatActuallyAwaitsTheSkill:
    def testCoroutineEntryReturnsTheAwaitedValue(self, tmp_path):
        """主格：入口是 `async def main` 的技能，await 咽喉必须拿到**它的返回值**。

        改前必红在这条行为上——今天交回来的是 `{"success": True, "result": <coroutine ...>}`，
        即"技能没跑、回执说成功"。这一格不判签名，判的是调用方拿到的东西。
        """
        svc = _svcInstalled(tmp_path, "b61-coro", "coro1",
                            "async def main(**kwargs):\n    return {'ran': 'coroutine-entry'}\n")

        outcome = asyncio.run(svc.call_skill("coro1"))

        assert outcome.get("success") is True, outcome
        assert outcome.get("result") == {"ran": "coroutine-entry"}, (
            f"协程入口拿到的是 {outcome.get('result')!r}——协程没被 await，"
            "调用方收到的'成功'里装的是一个从未跑过的协程对象")

    def testSyncEntryStaysOnTheCallerThread(self, tmp_path):
        """同步入口必须留在**调用线程**上跑：这是下面那条重入判据的前提。"""
        svc = _svcInstalled(tmp_path, "b61-thread", "thr1",
                            "import threading\n"
                            "def main(**kwargs):\n"
                            "    return {'thread': threading.current_thread().name}\n")

        mainName = threading.current_thread().name
        outcome = asyncio.run(svc.call_skill("thr1"))

        assert outcome.get("success") is True, outcome
        assert (outcome.get("result") or {}).get("thread") == mainName, (
            f"技能体跑在 {(outcome.get('result') or {}).get('thread')!r}，调用线程是 {mainName!r}"
            "——把同步技能挪进线程池，咽喉那把线程级 RLock 的重入语义就没了")

    def testSkillBodyCanCallBackTheServiceWithoutDeadlock(self, tmp_path):
        """技能体里回调本服务必须在**同一次调用**里跑通（今天靠同线程 RLock 重入）。

        这条是给"顺手改成 `asyncio.to_thread`"那种实现准备的牙。为什么必须带 timeout：
        不带的话它在那种实现下不是红，而是 worker 线程永远卡在 `lock.acquire()`、
        主线程持锁 await，整轮 session 被 30s thread 超时直接打断（本会话实测就是这样）——
        格子要能**自己红**，不许把跑测拖成事故。
        """
        # 落点直接写进这只**临时技能**的源码里，不走进程 env：测试改进程 env 会带倒同轮
        # 后续用例（本仓 tests/manual/* 那族就是靠 pytest_configure 拦的同一形态）。
        body = (
            "from neurova.skills.skill_service import SkillService\n"
            "def main(**kwargs):\n"
            f"    same = SkillService(agent_id='b61-cb', skills_dir={str(tmp_path / 'installed')!r})\n"
            "    return {'listed': len(same.list_skills()), 'reentrant': True}\n")
        svc = _svcInstalled(tmp_path, "b61-cb", "cb1", body)

        try:
            outcome = asyncio.run(asyncio.wait_for(svc.call_skill("cb1"), timeout=8))
        except Exception as exc:         # 超时/取消的异常类名各版本不一；一律转成会说话的红，且不许把整轮拖死
            pytest.fail(f"技能体回调本服务没能按时完成（{type(exc).__name__}: {exc}）——咽喉的 RLock 是"
                        "线程级重入，把技能体挪出调用线程即死锁；这条就是那枚变异的牙")

        assert outcome.get("success") is True, outcome
        result = outcome.get("result") or {}
        assert result.get("reentrant") is True, f"技能体内回调本服务没跑通：{outcome}"
        assert result.get("listed", 0) >= 1, "回调里读到的库是空的，重入没真发生过"

    def testEndpointDoesNotPaintAnUnawaitedCoroutineAsSuccess(self, tmp_path):
        """对外面：真 HTTP 执行口必须回出**跑过的值**，不是协程对象的序列化失败。

        走裸 app ＋ 真路由（不起 lifespan——起它会往进程级状态装默认 Agent，
        把同会话里依赖"未就绪"形态的其它档带倒，本会话刚为此修过一批）。
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.deps import get_current_user
        from neurova.api.endpoints import skill_pool_api

        from neurova.skills import library_service as lib

        # 装进**端点自己会解析的那个根**（经 agentLibrary），而不是改 _BASE_DIR 去迁就断言：
        # 这样这格证的才是"对外面上这条链真跑通"，而不是"我把落点挪到了探针方便的地方"。
        svc = lib.agentLibrary("b61-http")
        pkg = _makePkg(tmp_path / "src", "coro2",
                       "async def main(**kwargs):\n    return {'ran': 'over-http'}\n")
        assert svc.install_skill(str(pkg)).get("success") is True

        app = FastAPI()
        app.include_router(skill_pool_api.router, prefix="/api/v1/skill-pool")
        client = TestClient(app, raise_server_exceptions=False)
        client.app.dependency_overrides[get_current_user] = lambda: {
            "id": "u-b61", "sub": "u-b61", "username": "u-b61", "role": "admin"}

        got = client.post("/api/v1/skill-pool/private/coro2/execute",
                          json={"agent_id": "b61-http", "arguments": {}})

        assert got.status_code == 200, f"执行口 HTTP {got.status_code}：{got.text[:180]}"
        data = (got.json() or {}).get("data") or {}
        assert data.get("result") == {"ran": "over-http"}, (
            f"回执 data={str(data)[:200]}——协程入口经 HTTP 口交回来的不是跑过的值")


class TestContractIsConsistentAtEveryHit:
    """教义第 5 条：同一条契约的**所有**读法一起改对，不能只修被报告的那一条链。"""

    def testChainStepReadsTheDictContractNotAttributes(self):
        """链那侧直接调 `_execute_step`：await 之后必须按 dict 取，不许再摸 `.output` 属性。

        打的是行为而不是符号名——给链塞一个**真契约**（async 返回咽喉那份 dict）的 service，
        直接调那条执行步骤，要求步骤读数落对。
        """
        from neurova.skills.skill_chain_executor import SkillChainExecutor

        class _ThroatShapedService:
            async def call_skill(self, skill_id, **kwargs):     # 与真咽喉同形同契约
                return {"success": True, "result": {"from": skill_id}}

        chain = SkillChainExecutor(skill_service=_ThroatShapedService())
        step = _makeStep("s1", "demo-skill")

        outcome = asyncio.run(chain._execute_step(step, {"a": 1}, {}))

        assert outcome.output_data == {"from": "demo-skill"}, (
            f"链步骤按属性读咽喉的 dict 契约（.output/.success/.error），实得 {outcome}——"
            "await 改对了但读法没跟上")
        assert (getattr(outcome, "error", "") or "") == "", outcome

    def testBothProductionCallSitesAwaitInsteadOfInline(self):
        """两处生产调用点都必须 `await`：在 running loop 里包一层 `asyncio.run` 会当场报错。"""
        sites = [("neurova/api/endpoints/skill_pool_api.py", "execute_private_skill"),
                 ("neurova/skills/skill_chain_executor.py", "_execute_step")]
        offenders = []
        for rel, _fn in sites:
            tree = ast.parse(io.open(REPO / rel, encoding="utf-8").read(), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _calleeIsCallSkill(node):
                    parent = node
                    if not _isAwaited(tree, parent):
                        offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"咽喉被同步内联调用（协程入口就此拿到 coroutine 对象）：{offenders}")

    def testThroatJudgesCoroutineBeforeCallingIt(self):
        """口径照 `sub_session.callSubSessionChannel`：**调用之前**判 `iscoroutinefunction`。

        先调用再判会留下同一族坏形态：同步重活先阻塞事件循环再被发现。这一格按 AST 判形状，
        不钉词——注释里写"iscoroutinefunction"不该让它自己变绿。
        """
        throat = SkillService.call_skill
        assert asyncio.iscoroutinefunction(throat), (
            "call_skill 还是同步函数——端点在 running loop 里内联它，协程入口永远跑不起来")

        tree = ast.parse(io.open(_throatSourceFile(), encoding="utf-8").read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "call_skill")
        checkLine, callLine = None, None
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and _calleeName(node).endswith("iscoroutinefunction"):
                checkLine = node.lineno if checkLine is None else checkLine
            if isinstance(node, ast.Call) and _calleeName(node) == "func":
                callLine = node.lineno if callLine is None else callLine
        assert checkLine is not None and callLine is not None and checkLine < callLine, (
            f"判定（行 {checkLine}）没在调用（行 {callLine}）之前——同步重活会先卡住 loop")


    def testNoAsyncioRunWrappedAroundTheThroatInProduction(self):
        """反向钉：`neurova/` 里不许出现"在同步路径里 `asyncio.run(call_skill(...))`"那种兜底。"""
        offenders = []
        for rel in _trackedNeurovaPy():
            src = (REPO / rel).read_text(encoding="utf-8")
            if "asyncio.run(" not in src:
                continue
            tree = ast.parse(src, filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _calleeName(node) == "asyncio.run":
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Call) and _calleeIsCallSkill(inner):
                            offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"生产里用 asyncio.run 包咽喉（running loop 下当场 RuntimeError，是 consumer-side 兜底）："
            f"{offenders}")


def _throatSourceFile() -> Path:
    """咽喉所在源文件：`__file__` 是**模块**属性，不是类属性（在类上取会 AttributeError）。"""
    return Path(sys.modules[SkillService.__module__].__file__)


def _calleeName(node) -> str:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return f"{getattr(fn.value, 'id', '')}.{fn.attr}" if isinstance(fn.value, ast.Name) else fn.attr
    return fn.id if isinstance(fn, ast.Name) else ""


def _calleeIsCallSkill(node) -> bool:
    return _calleeName(node).split(".")[-1] == "call_skill" and isinstance(
        node.func, (ast.Attribute, ast.Name))


def _isAwaited(tree, node) -> bool:
    for parent in ast.walk(tree):
        if isinstance(parent, ast.Await) and any(
                child is node for child in ast.walk(parent.value)):
            return True
    return False


def _trackedNeurovaPy():
    from tests import ast_scan

    return [Path(rel) for rel in ast_scan.trackedPyPaths()
            if str(rel).replace("\\", "/").startswith("neurova/")
            and str(rel).endswith(".py")]


def _makeStep(stepId: str, skillId: str):
    from neurova.skills.models import SkillChainStep

    return SkillChainStep(step_id=stepId, skill_id=skillId, input_mapping={})


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
