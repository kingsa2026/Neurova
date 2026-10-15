"""市场取数预算单源 + 聚合截止线（§6-198，2026-10-14 裁定 A：收每市场预算）。

动手前实测（不是估算）：
- `SkillMarketRegistry` 现役注册 **7** 只适配器（`market_adapters.py:515-523`：
  skills_sh/clawhub/skillsmp/lobehub/github/modelscope/skillhub_cn），
  `search_all_markets` 是**串行** for 循环（`market_searcher.py:151-156`）；
- 每市场走 `market_adapters.py:127` 的 `urlopen(req, timeout=30)` ⇒ 一次搜索最坏 7 × 30 = **210 秒**；
- 同一能力的另两份私有实现各写各的预算：`market_sources.py:37` `HTTP_TIMEOUT = 20`、
  `hub_client.py:127` `config.get("HTTP_TIMEOUT", "30")`——后者还有 `retries+1 = 4` 次重试 + 退避，
  单次调用最坏 120 秒以上，而这条路在**生产安装链**上（`agent_skill_manager.py:79`、
  `manifest_source.py:119`、`skill_service.py:652`）；
- 每个市场的失败都被 `except Exception` 吞掉（只 warn），所以"转了两分钟什么也没搜到"
  在日志里连一条能出口的读数都没有。

口径两条，缺一不算闭合：
1. **每市场预算单点**：一个常量定义在一处，三处 fetcher 都取它；任何一处再出现裸数字即红（教义第 6 条）。
2. **聚合有截止线**：串行 fan-out 必须有一条总预算；到点就带着已完成的结果返回，并记出跳过了哪几只——
   不是静默跳过（§2 不许把失败改写成没事）。

判据按**现读的活值**算：市场数从注册表数、墙钟从 `pyproject.toml` 读、重试数从 `hub_client` 读，
不在断言里手抄数字（手抄已经错过一次：批 39 的台账把 7 只适配器写成"四市场 ≈120s"，随本批勘误）。
"""

from __future__ import annotations

import ast
import logging
import pathlib
import sys
import tomllib
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: 同一能力（取一个市场 URL）在本仓的三份私有实现——预算只准有一个宿主。
FETCHERS = ("neurova/skills/market_adapters.py",
            "neurova/skills/market_sources.py",
            "neurova/skills/hub_client.py")
BUDGET_NAME = "MARKET_FETCH_TIMEOUT_SECONDS"
AGGREGATE_NAME = "MARKET_SEARCH_AGGREGATE_SECONDS"
SEARCHER = "neurova/skills/market_searcher.py"


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace"),
                     filename=rel)


def _assignedNames(node: ast.AST) -> list[str]:
    """取一条赋值语句左边的名字，`X = 1` 与 `X: float = 1` 两种写法都认。

    只认 `ast.Assign` 的话，把常量改成带注解的赋值就从探测器底下滑走了——
    本仓同一族坑踩过两次（AST 只认字面量、真码是 `10*1024*1024`；以及这次）。
    """
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [t.id for t in targets if isinstance(t, ast.Name)]
    return []


def _timeoutOffenders(tree: ast.AST, label: str) -> list[str]:
    """同一套判定只写一份：三处坏形状都从这一个函数出。

    ① `urlopen(..., timeout=数字字面量)`；② `HTTP_TIMEOUT = 数字`（第二份预算定义）；
    ③ `config.get("HTTP_TIMEOUT", "数字")`（兜底写死）。
    只认 ① 会漏掉 ②——`market_sources.py:37` 那份就是从赋值语句里自己开账的。
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname == "urlopen":
                for kw in node.keywords:
                    if kw.arg == "timeout" and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, (int, float)):
                        offenders.append(f"{label}:{node.lineno} urlopen 的 timeout 写死数字")
            if fname == "get" and node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == "HTTP_TIMEOUT" and len(node.args) > 1 \
                    and isinstance(node.args[1], ast.Constant):
                offenders.append(f"{label}:{node.lineno} config HTTP_TIMEOUT 兜底写死字面量")
        if any(name == "HTTP_TIMEOUT" for name in _assignedNames(node)) \
                and getattr(node, "value", None) is not None \
                and isinstance(node.value, ast.Constant):
            offenders.append(f"{label}:{node.lineno} 第二份预算定义 HTTP_TIMEOUT=…")
    return offenders


def _bareTimeoutLiterals() -> list[str]:
    found: list[str] = []
    for rel in FETCHERS:
        found.extend(_timeoutOffenders(_tree(rel), rel))
    return found


def _budgetHosts() -> dict[str, int]:
    hosts: dict[str, int] = {}
    for rel in FETCHERS + (SEARCHER,):
        for node in ast.walk(_tree(rel)):
            if BUDGET_NAME in _assignedNames(node):
                hosts[rel] = hosts.get(rel, 0) + 1
    return hosts


def _activeMarketCount() -> int:
    """市场数取**聚合那一步自己看到的**口径：`search_all_markets` 迭代的就是
    `SkillMarketSearcher.list_market_names()`——不去 registry 上数（registry 无此方法，
    而且它数出来的与聚合面可能不同形）。
    """
    from neurova.skills.market_searcher import SkillMarketSearcher

    return len(SkillMarketSearcher().list_market_names())


def _pytestWallClock() -> float:
    cfg = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return float(cfg["tool"]["pytest"]["ini_options"]["timeout"])


class TestHubRetryStackIsBounded:
    """`hub_client` 这条路上还有 `retries+1` 次尝试 + 指数退避——只收单试预算不够。

    实测（本批动手前）：每试 30s × 4 次 + 退避 ≈ 127s；把每试收到 6s 后仍量得 **31.9s**
    （4 × 6.0 + 退避 7.9），依旧高于 30s 跑测墙钟——所以这条路上真正兜底的是**总预算**，
    不是单次超时。
    """

    def testTotalBudgetLeavesRoomForTheInFlightAttempt(self):
        import neurova.skills.hub_client as H

        total = getattr(H, "HUB_FETCH_TOTAL_SECONDS", None)
        assert isinstance(total, (int, float)), (
            "hub_client 没有总预算线——重试与退避叠起来仍会超墙钟（实测 31.9s）")
        from neurova.skills.market_adapters import MARKET_FETCH_TIMEOUT_SECONDS as B

        wall = _pytestWallClock()
        assert total + B <= wall, f"总预算 {total}s + 在飞的一次 {B}s 超过墙钟 {wall}s"

    def testRetriesStopWhenTheTotalBudgetIsSpent(self, monkeypatch):
        """到点就不再重试，并且**照旧把失败抛出去**——不是悄悄返回半截结果。

        这格原先读真实墙钟（`time.monotonic()` 差值断 `elapsed < 1.5`）。那是**负载敏感的上界**：
        注入的 0.2s 延迟在加压机器上会漂，同一份代码一红一绿——正是 `test_clock_caliber_ledger`
        这道门要求逐条给结论的形态（§6-96/§6-216 记过同族）。现改成**虚拟单调钟**驱动：
        时钟由被测代码去取（`H.time.monotonic()`），推进量由本格指定，于是"重试几次被掐停"
        是精确读数，与机器负载无关。
        """
        import urllib.error as ue

        import neurova.skills.hub_client as H

        class VirtualTime:
            """只实现被测代码用到的两个入口：取时与睡。推进量全部由本格指定。"""

            def __init__(self):
                self.now = 0.0

            def monotonic(self):        # noqa: D401 - 被测的截止线读的就是这个口
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = VirtualTime()
        attempts: list = []
        perAttempt = 0.2

        def fake_urlopen(request, timeout=None):
            attempts.append(timeout)
            clock.now += perAttempt        # 慢远端：在虚拟钟上花钱，不真睡
            raise ue.URLError("simulated slow remote")

        monkeypatch.setattr(H, "time", clock)
        monkeypatch.setattr(H, "urlopen", fake_urlopen)
        monkeypatch.setattr(H, "_compute_backoff_seconds", lambda attempt: 0.0)
        monkeypatch.setattr(H, "HUB_FETCH_TOTAL_SECONDS", 0.5, raising=False)
        monkeypatch.setattr(H, "_http_retries", lambda: 50)   # 重试次数故意给大

        with pytest.raises(ue.URLError):
            H._http_fetch("https://hub.invalid/x")

        # 0.5s 预算 ÷ 每试 0.2s ⇒ 恰好三次：第三次结束时虚拟钟 0.6s ≥ 截止线，循环不再开第四次
        assert len(attempts) == 3, (
            f"重试次数应当被总预算掐在 3 次（每试 {perAttempt}s ÷ 预算 0.5s），实得 {len(attempts)} 次")
        assert clock.now == pytest.approx(0.6, abs=1e-9), (
            f"虚拟钟推进量异常：{clock.now}——截止线不是由这条预算算出来的")


class TestBudgetIsSingleSource:
    def testBudgetHasExactlyOneHost(self):
        hosts = _budgetHosts()
        assert hosts == {"neurova/skills/market_adapters.py": 1}, (
            f"每市场预算的宿主应当唯一（现值 {hosts}）——两处定义就是两本账，"
            "改一处忘另一处正是本批要消掉的形态")

    def testNoBareTimeoutLiteralsRemainInTheThreeFetchers(self):
        offenders = _bareTimeoutLiterals()
        assert not offenders, (
            "同一能力的三份 fetcher 还在各写各的超时：\n  " + "\n  ".join(offenders)
            + "\n——预算只许一处定义（教义第 6 条）。")

    def testDetectorIsNotToothless(self):
        """反空转格：三类坏形状喂给同一个判定函数，必须逐类点名。

        只测"现在干净"的话，一个恒返回空列表的探测器和真守卫长得一模一样。
        """
        sample = (
            "import urllib.request\n"
            "HTTP_TIMEOUT = 20\n"
            "def f(url):\n"
            "    urllib.request.urlopen(url, timeout=30)\n"
            "    return {}.get('HTTP_TIMEOUT', '30')\n".format("config"))
        hits = _timeoutOffenders(ast.parse(sample), "sample")
        assert len(hits) == 3, f"应当点名三类落点，实得 {hits}"


class TestAggregateIsBounded:
    def testWorstCaseStaysUnderTheTestWallClock(self):
        """最坏时长按现读的活值算：市场数自己数、墙钟自己读，都不手抄。"""
        import neurova.skills.market_adapters as MA
        import neurova.skills.market_searcher as MS

        budget = getattr(MA, BUDGET_NAME, None)
        assert isinstance(budget, (int, float)), (
            f"`{BUDGET_NAME}` 不存在——每市场预算还没有单点定义")
        aggregate = getattr(MS, AGGREGATE_NAME, None)
        assert isinstance(aggregate, (int, float)), (
            f"`{AGGREGATE_NAME}` 不存在——串行 fan-out 还没有聚合截止线")

        markets = _activeMarketCount()
        assert markets > 0, "现役市场数为 0——聚合面空了，这条会假绿，先修取数再谈上限"
        wall = _pytestWallClock()
        assert budget * 2 <= wall, f"单市场预算 {budget}s 连两次往返都放不下（墙钟 {wall}s）"
        assert aggregate < wall, f"聚合截止线 {aggregate}s 不小于墙钟 {wall}s——又会击杀整场"
        assert aggregate <= markets * budget, (
            f"截止线 {aggregate}s 比全跑一遍 {markets * budget:.1f}s 还宽，等于没有截止线")
        # 最坏值＝截止线内已开跑的那一只仍在飞的调用 + 一只的预算（截止线只决定"还开不开新的"）
        assert aggregate + budget <= wall, (
            f"截止线 {aggregate}s + 在飞的一只 {budget}s = {aggregate + budget}s "
            f"已超过跑测墙钟 {wall}s——慢远端仍会把整场跑测打死")

    def testExpiredAggregateStopsOpeningNewMarketsAndNamesThem(self, monkeypatch, tmp_path):
        """截止线的诚实形状：**到点不再开新的市场**，已开跑的那一只仍由每市场预算兜。

        夹具里三只：快的立刻回；中等的在截止线**之前**开跑（它 overshoot 不归截止线管）；
        第三只必须**没被开跑**且被点名——把这三档分开，才不至于对着"假适配器无视 socket 超时"
        过度声称，也不至于把"跳过"写成静默。
        """
        import neurova.skills.market_searcher as MS

        from neurova.skills.market_adapters import SkillInfo

        startedMarket: list[str] = []

        class FastAdapter:
            market_name = "fast"

            def search(self, query, limit=10):
                startedMarket.append("fast")
                # 用真 SkillInfo 构造，不在夹具里自造字段形状（自造的键会让判据与生产不同形）
                return [SkillInfo(name="hit", source="fast", description="d",
                                  url="https://e.invalid/x")]

        class MiddleAdapter:
            market_name = "middle"

            def search(self, query, limit=10):
                startedMarket.append("middle")
                time.sleep(0.6)          # 在 0.5s 线**之前**已开跑，到点也不该被强行掐断
                return []

        class NeverAdapter:
            market_name = "never"

            def search(self, query, limit=10):
                startedMarket.append("never")
                return []

        registry = type("R", (), {
            "adapters": {"fast": FastAdapter(), "middle": MiddleAdapter(),
                         "never": NeverAdapter()},
            "list_markets": lambda self: list(self.adapters),
            "get_adapter": lambda self, name: self.adapters[name],
        })()
        monkeypatch.setattr(MS, AGGREGATE_NAME, 0.5, raising=False)
        search = MS.SkillMarketSearcher(cache_dir=str(tmp_path), registry=registry)

        records: list[str] = []

        class Collector(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Collector()
        MS.logger.addHandler(handler)
        try:
            results = search.search_all_markets("anything", limit_per_market=3)
        finally:
            MS.logger.removeHandler(handler)

        assert "never" not in startedMarket, (
            f"截止线到点后还开了新的市场（开跑序列 {startedMarket}）——截止线没管事")
        assert results, "快的市场已经返回了结果，聚合却因为后面慢的把结果一起丢掉"
        assert any("never" in m or "跳过" in m for m in records), (
            f"到点跳过却没留下任何读数（日志 {records}）——§2 不许把失败写成没事")
