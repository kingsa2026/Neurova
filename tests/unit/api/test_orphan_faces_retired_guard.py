# -*- coding: utf-8 -*-
"""孤儿面退役守卫（Issue #112 后续：新发现的两条包外命中点）。

根因（不是形状）：`scripts/generate_api_inventory.py` 的收录口径扩到**全仓**后，
两条包外命中点第一次被看见——`neurova.api.openplatform.routes`（19 条路由、四域）
与 `neurova.core.acp_server`（`ACPServer` 自持 5 条 `/acp/sessions*`）。二者形态
相同，都不是「待接线」，而是**第二份平行实现**：

- `openplatform.routes`：自带 apps / webhooks / keys 三套资源面，全仓零
  `include_router` 消费者，且整个 router **无任何 `Depends`**（挂上去等于把应用与
  Webhook 管理面对匿名请求开放）。前端 `modules/openplatform.ts` 的 BASE 是
  `/openplatform`，实际命中的却是**同名不同物**的 `endpoints/openplatform_keys.py`
  （只做密钥管理），8 条调用里 5 条在后端无对应路由。
- `core.acp_server`：`ACPServer.chat_stream()` 是**模拟实现**（返回
  「这是对您消息的回复: …」，不调任何 LLM），默认模型表是幻影条目；
  生产链路走的是 `endpoints/acp_api.py` + `agent/protocols/acp_runtime.py`。
  即「以假形态冒充能力」——挂上去是对外提供一圈假接口，不挂则是无人消费的死面。

处置（教义第 1 / 2 / 6 条）：在**产生第二份事实源的那一侧**删除，而不是给它补
判空、补鉴权、补接线——补接线只会让同一件事长期有两个写入点；保留一个「看起来
能用」的假面，则会训练人把假读数当事实。

本守卫锁四件事，全部机器可验：

1. **退役面无复活**：模块不可导入、文件不存在（`openplatform` 整包 +
   `core/acp_server.py`）；
2. **真面仍在**：`endpoints/openplatform_keys.py` 挂在 `/api/v1/openplatform`、
   `endpoints/acp_api.py` 挂在 `/api/acp` —— 删除不得连带真面（反向断言，
   防「一刀切删干净」把在用的服务面也删掉）；
3. **零引用**：生产代码与测试都不得再 import 退役模块（引用会成为「洞换个位置」）；
4. **不得回到台账**：两张脸已在台账中销账（`tests/unit/endpointWiringBaseline.txt`
   只降不升），若又被登记回去，说明有人把「删除」回退成了「登记待办」。
"""
from __future__ import annotations

import ast
import importlib.util
import io
import sys
from pathlib import Path

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 退役的两条包外孤儿面（模块路径 → 仓内文件）
RETIRED_MODULES = {
    "neurova.api.openplatform.routes": "neurova/api/openplatform/routes.py",
    "neurova.api.openplatform.events": "neurova/api/openplatform/events.py",
    "neurova.api.openplatform.models": "neurova/api/openplatform/models.py",
    "neurova.core.acp_server": "neurova/core/acp_server.py",
}

#: 退役后仍在服务的真面（退役不得误伤）
LIVE_FACES = {
    "neurova.api.endpoints.openplatform_keys": "/api/v1/openplatform",
    "neurova.api.endpoints.acp_api": "/api/acp",
}

#: 退役的前端死客户端（0 引用 + 5/8 调用在后端无对应路由）
RETIRED_FRONTEND = ("NeurUI/src/api/modules/openplatform.ts",)

WIRING_LEDGER = PROJECT_ROOT / "tests" / "unit" / "endpointWiringBaseline.txt"


def _retiredModuleTexts() -> tuple:
    """文本预筛词 = 退役模块的**全名**。

    这是**严格超集**而非启发式：被判为引用的两种形态（`import X` / `from X…`）
    在源码文本里必然逐字含 `X` 的全名——只要语句没被换行拆断。判据的判定面
    没有因此变窄：预筛只缩"要解析哪些文件"，不参与"怎么判"。
    """
    return tuple(sorted(RETIRED_MODULES))


def _importable(module: str) -> bool:
    """模块是否可导入（父包已删时 `find_spec` 会抛 ModuleNotFoundError，按不可导入计）。"""
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


class TestRetiredFacesAreGone:
    def test_modules_are_unimportable(self):
        alive = [name for name in RETIRED_MODULES if _importable(name)]
        assert not alive, (
            "孤儿面复活了（定义了路由、装配后一条都不可达，且与在用的真面并行）：\n  "
            + "\n  ".join(alive)
            + "\n它们不是「待接线」——接线只会让同一件事多一个写入点。"
        )

    def test_files_are_absent(self):
        present = [rel for rel in RETIRED_MODULES.values() if (PROJECT_ROOT / rel).is_file()]
        assert not present, "退役文件仍在盘上:\n  " + "\n  ".join(present)

    def test_dead_frontend_client_is_absent(self):
        present = [rel for rel in RETIRED_FRONTEND if (PROJECT_ROOT / rel).is_file()]
        assert not present, (
            "前端死客户端仍在盘上（仓内 0 引用、且 8 条调用中 5 条在后端无对应路由）:"
            + str(present)
        )

    def test_barrel_no_longer_exports_the_retired_client(self):
        barrel = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "index.ts"
        src = barrel.read_text(encoding="utf-8")
        assert "openplatform" not in src, (
            "barrel 仍在导出已退役的开放平台客户端——导出即「看起来能用」。"
        )


class TestLiveFacesSurvive:
    """反向断言：退役不得连带真面。缺了这条，「删除」会退化成「一刀切」。"""

    def test_live_modules_are_still_importable(self):
        for name in LIVE_FACES:
            assert _importable(name), (
                f"{name} 是仍在服务的真面，被连带删除了——退役不得误伤在用的端点面。"
            )

    def test_live_routes_are_reachable_in_the_assembled_app(self):
        import importlib

        generator = importlib.import_module("scripts.generate_api_inventory")
        served = generator.servedModules()
        for module, prefix in LIVE_FACES.items():
            assert module in served, (
                f"{module} 未出现在装配后的路由表里（应挂在 {prefix}）——"
                "真面必须继续由真装配路径提供服务。"
            )

    def test_negative_control_live_face_is_not_reported_as_retired(self):
        """门禁不得空转：真面既没被删、也不该出现在退役名单里。"""
        import importlib

        generator = importlib.import_module("scripts.generate_api_inventory")
        unwired = set(generator.unwiredEndpointModuleNames())
        for module in LIVE_FACES:
            assert module not in unwired, (
                f"{module} 被报成未接线——判据认错了接线形态（假阳性）。"
            )


class TestNoReferenceToRetiredFaces:
    """引用若留着，就是「洞换个位置」：报错从「模块存在但没接线」变成「导入失败」。"""

    def _references(self) -> list:
        """生产树 + tests 树里对退役模块的 import 引用。

        取数走本仓唯一 AST 入口 `tests/ast_scan`（Issue #148 / #197）：
        本判据原先自己 `rglob("*.py")` + `ast.parse()` 把 2905 个文件全量解析
        一遍（实测单次 5.2s），与受保护子集其余 260 余个文件共享机器时，
        成本随**代码总量**增长——判据本身与代码总量毫无关系（教义第 2 条）。
        改走共享预算后按 `_retiredModuleTexts()` 预筛（退役名必然以文本出现在
        `import` 语句里），解析量与文件总数脱钩，且与其余判据复用同一份
        `_cachedCode` / `_cachedParse` 缓存。
        """
        retired = set(RETIRED_MODULES)
        found = []
        own = Path(__file__).name
        for root in (ast_scan.PRODUCTION_ROOT, PROJECT_ROOT / "tests"):
            for path, node in ast_scan.nodeScan(root, hints=_retiredModuleTexts()):
                if path.name == own:
                    continue
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module in retired or any(module.startswith(r + ".") for r in retired):
                        found.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in retired:
                            found.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
        return found

    def test_no_reference_remains(self):
        offenders = self._references()
        assert not offenders, (
            "仍有代码/测试引用已退役的孤儿面:\n  " + "\n  ".join(offenders)
            + "\n修法：改用真面（openplatform_keys / acp_api），不要留悬空引用。"
        )


class TestRetiredFacesDoNotReturnToTheLedger:
    """销账必须落在台账上：只降不升。又登记回去，等于把「删除」回退成「待办」。"""

    def test_ledger_does_not_relist_them(self):
        assert WIRING_LEDGER.is_file(), "未挂载路由台账丢失"
        registered = set()
        for line in io.open(WIRING_LEDGER, encoding="utf-8"):
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                registered.add(stripped)
        relisted = sorted(set(RETIRED_MODULES) & registered)
        assert not relisted, (
            "已退役的孤儿面又被登记回台账:\n  " + "\n  ".join(relisted)
            + "\n台账是「尚未处置」的清单；删除后再登记，读者会以为它还活着。"
        )
