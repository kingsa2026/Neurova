"""
技能导入功能架构深化 — TDD red 测试

覆盖 ADR 0012/0013 的 6 个深化候选：
1. 激活 SkillHubClient（替换 stub MarketImporter）
2. 激活 SkillService（替换 stub SkillNeedAnalyzer._install_skill）
3. 修复 ChatPipeline async 断链
4. 修复 AgentSkillManager 签名三重不匹配
5. 统一 4 套市场端点→1 套
6. 对齐前端 skill-pool.ts 路由

所有测试在修复前应为 RED（失败），修复后变 GREEN。
"""

import asyncio
import importlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════
# 候选 1：激活 SkillHubClient 深度模块（替换 stub MarketImporter）
# ══════════════════════════════════════════════════════════════════

class TestSkillHubClientActivated:
    """验证 AgentSkillManager 持有 SkillHubClient（而非 stub MarketImporter）。"""

    def test_agent_skill_manager_uses_skill_hub_client(self):
        """AgentSkillManager 应持有 SkillHubClient 实例，而非 stub MarketImporter。"""
        from neurova.skills.agent_skill_manager import AgentSkillManager
        from neurova.skills.hub_client import SkillHubClient

        mgr = AgentSkillManager.__new__(AgentSkillManager)
        mgr._init_importer()

        # importer 应为 SkillHubClient 实例
        assert isinstance(mgr.importer, SkillHubClient), (
            f"期望 SkillHubClient 实例，实际 {type(mgr.importer).__name__}"
        )

    def test_market_importer_not_stub(self):
        """MarketImporter 的 search_skills 不应返回硬编码数据。"""
        from neurova.skills.market_importer import MarketImporter

        importer = MarketImporter(skills_dir=Path(".agents/skills"))
        results = importer.search_skills("test_query")

        # stub 返回固定的 2 条硬编码结果；真实实现不应有固定长度
        # 如果 MarketImporter 变为 SkillHubClient 的 Adapter，结果应来自 HTTP
        source = importer.__class__.__name__
        assert not (len(results) == 2 and "模拟" in str(results[0])), (
            f"search_skills 仍返回硬编码 stub 数据（source={source}）"
        )


# ══════════════════════════════════════════════════════════════════
# 候选 2：激活 SkillService 深度模块（替换 stub SkillNeedAnalyzer）
# ══════════════════════════════════════════════════════════════════

class TestSkillServiceActivated:
    """验证 SkillNeedAnalyzer 持有 SkillService，_install_skill 委托真实安装。"""

    def test_skill_need_analyzer_has_skill_service(self):
        """SkillNeedAnalyzer 应持有 SkillService 实例。"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer
        from neurova.skills.skill_service import SkillService

        analyzer = SkillNeedAnalyzer()
        assert hasattr(analyzer, "skill_service"), "SkillNeedAnalyzer 应有 skill_service 属性"
        assert isinstance(getattr(analyzer, "skill_service"), SkillService), (
            f"期望 SkillService 实例，实际 {type(getattr(analyzer, 'skill_service', None)).__name__}"
        )

    def test_install_skill_not_stub(self):
        """_install_skill 不应是 time.sleep + 内存 dict stub。"""
        import time
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer

        analyzer = SkillNeedAnalyzer()
        # 记录开始时间
        start = time.time()
        # 调用 _install_skill（mock 内部依赖避免真实安装）
        with patch.object(analyzer, "skill_service") as mock_service:
            mock_service.install_skill.return_value = {"success": True, "skill_id": "test"}
            with patch.object(analyzer, "market_searcher"):
                analyzer._install_skill(
                    skill_name="test_skill",
                    skill_info={"id": "test", "source_url": "http://example.com/test.zip"},
                )
        elapsed = time.time() - start
        # stub 实现会 time.sleep(0.1)，耗时 >= 0.1s
        # 真实委托给 SkillService 的实现不应有固定 sleep
        assert elapsed < 0.09, (
            f"_install_skill 仍含 time.sleep stub（耗时 {elapsed:.3f}s >= 0.1s）"
        )

    def test_is_skill_installed_delegates_to_service(self):
        """_is_skill_installed 应委托 SkillService.is_installed，非永远返回 False。"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer

        analyzer = SkillNeedAnalyzer()
        with patch.object(analyzer, "skill_service") as mock_service:
            mock_service.is_installed = MagicMock(return_value=True)
            result = analyzer._is_skill_installed("test_skill")
        assert result is True, "_is_skill_installed 应委托 SkillService，而非永远返回 False"


# ══════════════════════════════════════════════════════════════════
# 候选 3：修复 ChatPipeline async 断链
# ══════════════════════════════════════════════════════════════════

class TestChatPipelineAsyncFixed:
    """验证 _check_skill_acquisition 正确 await analyze_task。"""

    def test_analyze_task_is_awaited(self):
        """_check_skill_acquisition 应 await analyze_task（非同步调用）。"""
        from neurova.agent.chat_pipeline import ChatPipeline

        source = inspect.getsource(ChatPipeline._check_skill_acquisition)
        # 不应出现未 await 的同步调用
        assert "result = self.skill_manager.analyze_task(" not in source or "await" in source.split("analyze_task")[0].split("\n")[-1], (
            "analyze_task 是 async def，必须 await — 当前未 await 导致返回 coroutine"
        )

    def test_check_skill_acquisition_uses_correct_return_fields(self):
        """应使用 analyze_task 返回的真实字段（skills_needed/auto_acquire），非 success_count。"""
        from neurova.agent.chat_pipeline import ChatPipeline

        source = inspect.getsource(ChatPipeline._check_skill_acquisition)
        # analyze_task 返回 {"success", "skills_needed", "auto_acquire"}
        # 不应使用不存在的 success_count / acquisition_results 字段
        assert "success_count" not in source, (
            "_check_skill_acquisition 使用了 analyze_task 不返回的 success_count 字段"
        )

    def test_check_skill_acquisition_does_not_silently_swallow(self):
        """except 不应静默吞掉 coroutine AttributeError。"""
        from neurova.agent.chat_pipeline import ChatPipeline

        source = inspect.getsource(ChatPipeline._check_skill_acquisition)
        # 修复后应有 logger.exception 或更具体的错误处理
        # 当前是 logger.warning（吞掉 coroutine 的 AttributeError）
        assert "logger.exception" in source or "raise" in source, (
            "except 应使用 logger.exception 记录完整 traceback，而非 logger.warning 静默吞掉"
        )


# ══════════════════════════════════════════════════════════════════
# 候选 4：修复 AgentSkillManager 签名三重不匹配
# ══════════════════════════════════════════════════════════════════

class TestAgentSkillManagerSignatureFixed:
    """验证 acquire_skill/search_skill 的调用签名与下游真实 Interface 匹配。"""

    def test_search_skill_does_not_await_sync_method(self):
        """search_skill 不应用 await 调用同步方法 search_all_markets。"""
        from neurova.skills.agent_skill_manager import AgentSkillManager

        source = inspect.getsource(AgentSkillManager.search_skill)
        # search_all_markets 是同步方法，不应被 await
        if "search_all_markets" in source:
            line_with_await = [l for l in source.split("\n") if "search_all_markets" in l and "await" in l]
            assert len(line_with_await) == 0, (
                f"search_all_markets 是同步方法，不应 await — 当前: {line_with_await}"
            )

    def test_search_skill_no_invalid_params(self):
        """search_skill 不应传不存在的 markets/limit_per_market 参数。"""
        from neurova.skills.agent_skill_manager import AgentSkillManager

        source = inspect.getsource(AgentSkillManager.search_skill)
        if "search_all_markets" in source:
            assert "markets=" not in source, "search_all_markets 无 markets 参数"
            assert "limit_per_market=" not in source, "search_all_markets 无 limit_per_market 参数（应为 limit）"

    def test_acquire_skill_no_phantom_method(self):
        """acquire_skill 不应调用不存在的 import_from_market 方法。"""
        from neurova.skills.agent_skill_manager import AgentSkillManager

        source = inspect.getsource(AgentSkillManager.acquire_skill)
        assert "import_from_market" not in source, (
            "import_from_market 是幻影方法（全项目无定义），应改用真实 install_skill 或 SkillHubClient.install_skill"
        )

    def test_acquire_skill_uses_real_install(self):
        """acquire_skill 应调用真实存在的安装方法。"""
        from neurova.skills.agent_skill_manager import AgentSkillManager

        source = inspect.getsource(AgentSkillManager.acquire_skill)
        # 应调用 install_skill 或 SkillHubClient 的 install 方法
        assert "install_skill" in source or "importer.install" in source, (
            "acquire_skill 应调用真实存在的安装方法（install_skill），而非幻影 import_from_market"
        )


# ══════════════════════════════════════════════════════════════════
# 候选 5：统一 4 套市场端点→1 套
# ══════════════════════════════════════════════════════════════════

class TestMarketEndpointsUnified:
    """验证 4 套市场端点收敛到 1 套。"""

    def test_skill_market_endpoint_removed(self):
        """stub 端点 skill_market.py 应被删除或不再注册。"""
        try:
            mod = importlib.import_module("neurova.api.endpoints.skill_market")
            # 如果模块仍存在，检查是否被标记 deprecated
            assert hasattr(mod, "_DEPRECATED") or hasattr(mod, "DEPRECATED"), (
                "skill_market.py stub 端点应被删除或标记 deprecated"
            )
        except ImportError:
            pass  # 已删除 — 通过

    def test_skills_market_endpoint_removed(self):
        """demo 端点 skills_market.py 应被删除或不再注册。"""
        try:
            mod = importlib.import_module("neurova.api.endpoints.skills_market")
            assert hasattr(mod, "_DEPRECATED") or hasattr(mod, "DEPRECATED"), (
                "skills_market.py demo 端点应被删除或标记 deprecated"
            )
        except ImportError:
            pass  # 已删除 — 通过

    def test_marketplace_endpoint_removed(self):
        """调 stub importer 的 marketplace.py 应被删除或不再注册。"""
        try:
            mod = importlib.import_module("neurova.api.endpoints.marketplace")
            assert hasattr(mod, "_DEPRECATED") or hasattr(mod, "DEPRECATED"), (
                "marketplace.py 端点应被删除或标记 deprecated"
            )
        except ImportError:
            pass  # 已删除 — 通过

    def test_skill_pool_api_is_canonical(self):
        """skill_pool_api.py 应为唯一规范端点。"""
        mod = importlib.import_module("neurova.api.endpoints.skill_pool_api")
        assert hasattr(mod, "router"), "skill_pool_api.py 应有 router"


# ══════════════════════════════════════════════════════════════════
# 候选 6：对齐前端 skill-pool.ts 路由
# ══════════════════════════════════════════════════════════════════

class TestFrontendRouteAlignment:
    """验证前端 skill-pool.ts 路由与后端匹配。"""

    def test_install_skill_route_matches(self):
        """前端 installSkill 路由应与后端 skill_pool_api 路由匹配。"""
        frontend_path = Path("NeurUI/src/api/modules/skill-pool.ts")
        if not frontend_path.exists():
            pytest.skip("前端文件不存在")
        content = frontend_path.read_text(encoding="utf-8")

        # 前端不应调用已删除的 /skill-market/install stub 端点
        assert "/skill-market/install" not in content, (
            "前端仍调用已删除的 /skill-market/install stub 端点"
        )

    def test_no_404_routes(self):
        """前端不应有必然 404 的路由（如缺少 /public 段的 install）。"""
        frontend_path = Path("NeurUI/src/api/modules/skill-pool.ts")
        if not frontend_path.exists():
            pytest.skip("前端文件不存在")
        content = frontend_path.read_text(encoding="utf-8")

        # 前端 createSkill POST /skill-pool 应有对应后端路由
        # 前端 installSkill POST /skill-pool/{id}/install 应有对应后端路由
        # 检查是否还存在路径不匹配（前端无 /public 段但后端有）
        backend_path = Path("neurova/api/endpoints/skill_pool_api.py")
        if backend_path.exists():
            backend_content = backend_path.read_text(encoding="utf-8")
            # 如果后端路由含 /public/{id}/install，前端也应含 /public/
            if "/public/{skill_id}/install" in backend_content:
                # 前端 installSkill 应包含 /public/
                install_lines = [l for l in content.split("\n") if "install" in l.lower() and "post" in l.lower()]
                for line in install_lines:
                    if "/skill-pool/" in line and "/public/" not in line:
                        pytest.fail(
                            f"前端路由路径不匹配后端: {line.strip()} — 后端含 /public/ 段"
                        )


# ══════════════════════════════════════════════════════════════════
# 端到端验证：完整调用链走通
# ══════════════════════════════════════════════════════════════════

class TestEndToEndSkillAcquisitionChain:
    """端到端验证：ChatPipeline → AgentSkillManager → SkillHubClient → SkillService。"""

    def test_analyze_task_returns_correct_fields(self):
        """analyze_task 返回的字段应与 _check_skill_acquisition 期望一致。"""
        from neurova.skills.agent_skill_manager import AgentSkillManager

        source = inspect.getsource(AgentSkillManager.analyze_task)
        # analyze_task 返回字典的键应包含 skills_needed / auto_acquire
        # 而非 success_count / acquisition_results
        assert "skills_needed" in source, "analyze_task 应返回 skills_needed 字段"
        assert "auto_acquire" in source, "analyze_task 应返回 auto_acquire 字段"

    def test_skills_init_exports_modules(self):
        """skills/__init__.py 应实际导入 hub_client/skill_service，而非空 pass。"""
        init_path = Path("neurova/skills/__init__.py")
        content = init_path.read_text(encoding="utf-8")
        # 不应有空 try: pass except ImportError 块
        # 检查是否有实际 import 语句
        assert "from neurova.skills.hub_client import" in content or "import hub_client" in content, (
            "skills/__init__.py 应导入 hub_client 模块（当前是空 pass）"
        )
        assert "from neurova.skills.skill_service import" in content or "import skill_service" in content, (
            "skills/__init__.py 应导入 skill_service 模块（当前是空 pass）"
        )


# ══════════════════════════════════════════════════════════════════
# 阻塞修复 2：SkillService.install_skill 远程 URL 处理
# ══════════════════════════════════════════════════════════════════

class TestSkillServiceRemoteUrlHandling:
    """验证 SkillService.install_skill 能处理远程 URL（github/clawhub/lobehub）。

    根因：原代码 skill_path = Path(skill_path); if not skill_path.exists():
    Path("https://github.com/...").exists() 必然 False，导致远程 URL 安装永远失败。
    """

    def test_install_skill_with_url_does_not_return_path_not_found(self):
        """传 URL 给 install_skill 不应返回 'path not found'。"""
        from neurova.skills.skill_service import SkillService

        svc = SkillService.__new__(SkillService)
        # 不调用 __init__，避免创建目录
        svc.agent_id = "test"
        svc.skills_dir = Path("/tmp/test_skills")
        svc.manifest_path = svc.skills_dir / "manifest.json"
        svc._skills = {}
        from neurova.core.logger import get_logger
        svc._logger = get_logger("test")

        # 直接调用 install_skill with URL
        url = "https://github.com/example/skill/archive/main.zip"
        result = svc.install_skill(skill_path=url, skill_id="test-skill")
        # 不应返回 path not found 错误
        assert not (isinstance(result, dict) and "path not found" in str(result.get("error", "")).lower()), (
            f"URL 安装不应返回 path not found 错误: {result}"
        )

    def test_install_skill_delegates_url_to_hub_client(self):
        """URL 安装应委托给 SkillHubClient（已有 HTTP 下载能力）。"""
        source = inspect.getsource(__import__("neurova.skills.skill_service", fromlist=["SkillService"]).SkillService.install_skill)
        # 应检测 URL 前缀并委托
        assert "http://" in source or "https://" in source or "startswith" in source, (
            "install_skill 应检测 URL 前缀（http:// 或 https://）"
        )


# ══════════════════════════════════════════════════════════════════
# 阻塞修复 3：3 个激活模块加 RLock 线程安全保护
# ══════════════════════════════════════════════════════════════════

class TestActivatedModulesThreadSafety:
    """验证 3 个激活模块都有 threading.RLock 保护共享可变状态。

    AGENTS.md 规定：threading.RLock 用于共享状态。
    对照组：pool_service.py:70, market_importer.py:100, evolution_engine.py:99 都有 RLock。

    增强断言：不只验证 RLock 字段存在，还要验证至少有一个方法用 `with self._lock:` 实际使用。
    """

    def test_skill_service_has_rlock(self):
        """SkillService 应有 _lock 字段且为 RLock 类型。"""
        import threading
        from neurova.skills.skill_service import SkillService

        svc = SkillService.__new__(SkillService)
        svc.agent_id = "test"
        svc.skills_dir = Path("/tmp/test_skills")
        svc.manifest_path = svc.skills_dir / "manifest.json"
        svc._skills = {}
        from neurova.core.logger import get_logger
        svc._logger = get_logger("test")

        # 调用 _init_lock（如果存在）或检查 __init__ 源码
        source = inspect.getsource(SkillService.__init__)
        assert "RLock" in source, (
            "SkillService.__init__ 应初始化 self._lock = threading.RLock() — "
            "对照 pool_service.py:70 / market_importer.py:100 / evolution_engine.py:99"
        )

    def test_skill_service_lock_actually_used(self):
        """SkillService 应至少有一个方法用 `with self._lock:` 实际使用锁。"""
        from neurova.skills.skill_service import SkillService

        # 至少 install_skill / uninstall_skill / enable_skill / disable_skill 等方法之一用锁
        used_count = 0
        for method_name in ("install_skill", "uninstall_skill", "enable_skill",
                            "disable_skill", "list_skills", "get_skill_info"):
            method = getattr(SkillService, method_name, None)
            if method and callable(method):
                try:
                    src = inspect.getsource(method)
                    if "with self._lock" in src:
                        used_count += 1
                except (OSError, TypeError):
                    pass
        assert used_count >= 3, (
            f"SkillService 应至少有 3 个方法使用 `with self._lock:`，实际 {used_count} 个 — "
            "字段存在但未实际使用是假阳性"
        )

    def test_skill_hub_client_has_rlock(self):
        """SkillHubClient 应有 _lock 字段且为 RLock 类型。"""
        from neurova.skills.hub_client import SkillHubClient

        source = inspect.getsource(SkillHubClient.__init__)
        assert "RLock" in source, (
            "SkillHubClient.__init__ 应初始化 self._lock = threading.RLock() — "
            "保护 _cache/_cache_ttl/_sources 共享状态"
        )

    def test_skill_hub_client_lock_actually_used(self):
        """SkillHubClient 应至少有一个方法用 `with self._lock:` 实际使用锁。"""
        from neurova.skills.hub_client import SkillHubClient

        used_count = 0
        for method_name in ("register_source", "search_skills", "install_skill"):
            method = getattr(SkillHubClient, method_name, None)
            if method and callable(method):
                try:
                    src = inspect.getsource(method)
                    if "with self._lock" in src:
                        used_count += 1
                except (OSError, TypeError):
                    pass
        assert used_count >= 1, (
            f"SkillHubClient 应至少有 1 个方法使用 `with self._lock:`，实际 {used_count} 个 — "
            "字段存在但未实际使用是假阳性"
        )

    def test_skill_need_analyzer_has_rlock(self):
        """SkillNeedAnalyzer 应有 _lock 字段且为 RLock 类型。"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer

        source = inspect.getsource(SkillNeedAnalyzer.__init__)
        assert "RLock" in source, (
            "SkillNeedAnalyzer.__init__ 应初始化 self._lock = threading.RLock() — "
            "保护 _installed_cache/_installed_skills/_acquisition_history 共享状态"
        )

    def test_skill_need_analyzer_lock_actually_used(self):
        """SkillNeedAnalyzer 应至少有一个方法用 `with self._lock:` 实际使用锁。"""
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer

        used_count = 0
        for method_name in ("analyze_and_acquire", "_is_skill_installed", "_acquire_skill",
                            "_install_skill", "clear_history", "get_acquisition_history"):
            method = getattr(SkillNeedAnalyzer, method_name, None)
            if method and callable(method):
                try:
                    src = inspect.getsource(method)
                    if "with self._lock" in src:
                        used_count += 1
                except (OSError, TypeError):
                    pass
        assert used_count >= 3, (
            f"SkillNeedAnalyzer 应至少有 3 个方法使用 `with self._lock:`，实际 {used_count} 个 — "
            "字段存在但未实际使用是假阳性"
        )

    def test_skill_service_url_install_updates_manifest(self):
        """SkillService._install_from_url 成功后应更新 self._skills 字典。

        审计发现：原实现只委托 SkillHubClient 但不更新本地清单，
        导致 list_skills/call_skill/uninstall_skill 无法找到 URL 安装的技能。
        """
        from neurova.skills.skill_service import SkillService

        source = inspect.getsource(SkillService._install_from_url)
        # 成功分支应更新 _skills 字典
        assert "self._skills[" in source, (
            "_install_from_url 成功分支应更新 self._skills 字典 — "
            "否则 URL 安装的技能在 list_skills/call_skill 中找不到"
        )
        assert "self._save_manifest()" in source, (
            "_install_from_url 成功分支应调用 self._save_manifest() — "
            "否则 URL 安装的技能重启后丢失"
        )
