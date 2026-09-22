# -*- coding: utf-8 -*-
"""前端 API 清单新鲜度守卫（Issue #112：整篇级过期，重生成销账）。

背景（根因，不是形状）：`docs/09-dev-progress/api_inventory.md` 是一篇**专职指路文档**
（标题即「清单」，被 `docs/0-index/README.md` 列为 `09-dev-progress` 领域入口，导航可达）。
它自述生成于 2026-05-14、更新于 2026-06-06，实测与现行代码树整篇脱节：
声明的 71 个前端模块里 29 个已不存在，`NeurUI/src/api/modules/` 现行 61 个模块里 20 个未列出。

逐条补路径只能得到一份「半对半错」的清单——**清单的价值全部在于可信**。
故本轮不是「改路径」，是**重生成**：清单由脚本对现行代码树取一次全集产出，
守卫只做「重算 + 比对 + 负向控制」，判据单源在 `scripts/generate_api_inventory.py`。

本守卫锁四件事：

1. **双向差集为空**：文档声明的前端模块集合 == `NeurUI/src/api/modules/*.ts` 全集（排除 barrel）；
2. **前缀可信**：文档声明的后端挂载前缀集合 == `neurova/api/endpoints/__init__.py` 注册表的实际挂载点；
3. **快照纪律**：头部含生成命令与生成日期——读者任何时候都知道这份东西什么时候生的、怎么再生成；
4. **生成入口真实**：机器区由生成器产出且幂等（写回当前文档逐字节不变），
   否则「重跑命令」就是一句做不到的空话（教义第 2 条）。
"""
from __future__ import annotations

import functools
import importlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INVENTORY = PROJECT_ROOT / "docs" / "09-dev-progress" / "api_inventory.md"
LEDGER = PROJECT_ROOT / "docs" / "06-bugfix" / "历史悬空引用登记台账_2026-09-21.md"
GENERATOR_NAME = "scripts.generate_api_inventory"
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def _generator():
    """生成器模块。缺失即红灯——不许用 importorskip 把它变成静默跳过。"""
    return importlib.import_module(GENERATOR_NAME)


def _inventory_text() -> str:
    assert INVENTORY.is_file(), f"清单不存在: {INVENTORY.relative_to(PROJECT_ROOT)}"
    return io.open(INVENTORY, encoding="utf-8").read()


def _ledger_text() -> str:
    assert LEDGER.is_file(), f"台账不存在: {LEDGER.relative_to(PROJECT_ROOT)}"
    return io.open(LEDGER, encoding="utf-8").read()


_APP_PROBE = (
    "import sys, warnings, json; sys.path.insert(0, '.'); "
    "warnings.filterwarnings('ignore')"
    "\n"
    "from neurova.api.app import create_app"
    "\n"
    "app = create_app(enable_memory=False, enable_channels=False)"
    "\n"
    "print(json.dumps(sorted(app.openapi()['paths'])))"
)


@functools.lru_cache(maxsize=1)
def _runtimeRoutePaths() -> frozenset:
    """真实链路读数：启动真应用，取它注册出来的路由表（只跑一次）。"""
    proc = subprocess.run([sys.executable, "-c", _APP_PROBE], cwd=str(PROJECT_ROOT),
                          capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, f"应用创建失败：{proc.stderr[-800:]}"
    paths = json.loads(proc.stdout.strip().splitlines()[-1])
    return frozenset(path.rstrip("/") or "/" for path in paths)


def _normalize(path: str) -> str:
    """路径参数段统一成 `*`，只比结构不比参数名。"""
    return "/".join("*" if part.startswith("{") else part for part in path.split("/"))



class TestGeneratorExists:
    def test_generator_exposes_its_surface(self):
        module = _generator()
        for name in ("INVENTORY_PATH", "frontendModuleFiles", "declaredFrontendModules",
                     "registeredBackendPrefixes", "declaredBackendPrefixes",
                     "renderInventory", "applyInventory"):
            assert hasattr(module, name), (
                f"生成器未提供 {name}：清单的判据缺位，守卫会退化成一条空规则。"
            )

    def test_inventory_path_is_the_navigation_entry_document(self):
        module = _generator()
        assert Path(module.INVENTORY_PATH).resolve() == INVENTORY.resolve(), (
            "生成器写的不是 `docs/0-index/README.md` 列为领域入口的那一篇——"
            "生成到别处等于原地留下过期清单。"
        )


class TestBidirectionalDifferenceIsEmpty:
    def test_frontend_module_set_matches_code_tree(self):
        module = _generator()
        declared = module.declaredFrontendModules(_inventory_text())
        actual = module.frontendModuleFiles()
        assert declared == actual, (
            "清单声明的前端模块与代码树不是同一集合（双向差集必须为空）：\n"
            f"  只在清单里（已不存在）: {sorted(set(declared) - set(actual))[:10]}\n"
            f"  只在代码树里（未列出）: {sorted(set(actual) - set(declared))[:10]}\n"
            "修法：python scripts/generate_api_inventory.py --write"
        )

    def test_backend_prefix_table_matches_registry(self):
        module = _generator()
        declared = module.declaredBackendPrefixes(_inventory_text())
        registered = module.registeredBackendPrefixes()
        assert declared == registered, (
            "清单声明的后端挂载前缀与注册表不一致：\n"
            f"  只在清单里: {sorted(set(declared) - set(registered))[:10]}\n"
            f"  只在注册表里: {sorted(set(registered) - set(declared))[:10]}\n"
            "修法：python scripts/generate_api_inventory.py --write"
        )

    def test_code_tree_set_is_not_vacuous(self):
        """反向控制：代码树取全集不得退化成空集（否则第一条断言白通过）。"""
        module = _generator()
        files = module.frontendModuleFiles()
        assert len(files) > 40, f"只扫到 {len(files)} 个前端模块，范围疑似失效"
        assert any(name.endswith("health.ts") for name in files), (
            "`health.ts` 这类现行模块都扫不到，说明取全集的口径错了"
        )


class TestRouteFactsMatchTheRuntime:
    """路由事实只有一个来源：**装配后的真实路由表**。

    本仓历史上同时存在两套路由事实——`endpoint_modules` 注册表 + 各模块
    `APIRouter(prefix=...)` 自述前缀的静态重建，与 `create_app()` 装配结果。
    两套各写一半，正是「零路由挂载 / 前缀重复 / 挂载层错位」三类矛盾的土壤。
    收口后静态重建已删除（教义第 6 条：不新造平行体系），故这里不来比对
    「静态 vs 运行时」，而是**禁止第二套静态重建复活**，并用运行时读数自证判据。
    """

    def test_no_second_static_route_reconstruction(self):
        """不得再出现「静态重建路由表」的第二套实现。"""
        module = _generator()
        for retired in ("backendRoutePaths", "routerRoutePaths", "routerRoutePaths",
                        "registrationRows", "mountPoint", "moduleRouterPrefix"):
            assert not hasattr(module, retired), (
                f"生成器又出现了 {retired}()：那是静态重建路由的二套实现，"
                "与 `create_app()` 装配结果必然逐版漂移（教义第 6 条）。"
            )

    def test_zero_route_mount_points_match_the_runtime(self):
        """空 router 判据必须与运行时一致：点名的挂载点在真实路由表里零命中。"""
        module = _generator()
        runtime = _runtimeRoutePaths()
        for point in module.zeroRouteMountPoints():
            hits = [path for path in runtime
                    if path == point or path.startswith(point.rstrip("/") + "/")]
            assert not hits, (
                f"被判为零路由的挂载点 {point} 在运行时其实有 {len(hits)} 条路由——判据给了假阳性。"
            )

    def test_mount_table_matches_the_runtime(self):
        """清单挂载表里的每条前缀都必须在真实路由表里有命中。"""
        module = _generator()
        runtime = {_normalize(path) for path in _runtimeRoutePaths()}
        for point, _ownPrefix, _module in module.backendMountPoints():
            if point in ("/api/v1", "/api"):
                continue  # 伞形前缀：其下各子挂载点是逐条列出的
            hits = [path for path in runtime
                    if path == point or path.startswith(point.rstrip("/") + "/")]
            assert hits, (
                f"挂载表列出的 {point} 在真实路由表里零命中——表在报一个并不存在的挂载点。"
            )

    def test_frontend_contract_breaks_are_real(self):
        """被点名为契约断点的前缀，必须在真实路由表里零命中（否则清单在冤枉后端）。"""
        module = _generator()
        runtime = _runtimeRoutePaths()
        for relative, expected in module.frontendContractBreaks():
            hits = [path for path in runtime
                    if path == expected or path.startswith(expected + "/")]
            assert not hits, (
                f"{relative} 请求的 {expected} 被判为断点，但运行时其实有 {len(hits)} 条路由。"
            )


class TestBreakpointsAreNamedNotBuried:
    """断点必须点名：零路由挂载点与前后端契约断点都不得靠「大致一致」带过。"""

    def test_zero_route_mount_points_are_listed_apart(self):
        module = _generator()
        text = _inventory_text()
        for point in module.zeroRouteMountPoints():
            assert point not in module.declaredBackendPrefixes(text), (
                f"零路由挂载点 {point} 被列进了「后端挂载前缀」表——"
                "读者会以为它可用，实际 404。"
            )

    def test_known_empty_mount_points_become_visible(self):
        """判据不空转：注入一个零路由 router，清单侧必须报得出来。

        （本轮已把实测存在的 `/api`、`/api/evolution`、`/api/rag` 三个零路由挂载退役，
        当前列表为空是**修好了**，不是判据失效——故这里用注入自证，不靠残留读数。）
        """
        from fastapi import APIRouter, FastAPI

        module = _generator()
        app = FastAPI()
        app.include_router(APIRouter(prefix="/zzz-probe"), prefix="/api/zzz-probe")
        audit = module.auditMountsFor(app)
        assert audit["零路由挂载"], (
            "注入零路由 router 后审计仍为空——判据失效，断点会被静默吞掉。"
        )

    def test_unmounted_endpoint_modules_are_exposed(self, tmp_path, monkeypatch):
        """定义了路由却从未挂载的模块必须点名（判据不空转，用注入自证）。

        本轮已把实测的六个未挂载模块各自收口（四个删除、两个接线），
        故这里以注入自证判据仍咬得住，而不是拿某个残留孤儿当锚点——
        那会反过来要求孤儿继续存在。
        """
        module = _generator()
        probe = tmp_path / "neurova" / "api" / "endpoints"
        probe.mkdir(parents=True)
        (probe / "zzz_orphan.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter(prefix='/zzz')\n\n"
            "@router.get('/x')\n"
            "def _x():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(module, "SOURCE_ROOTS", ("neurova",))
        assert module.unmountedEndpointModules() == ["neurova.api.endpoints.zzz_orphan"], (
            "注入的孤儿端点模块未被点名——取数口径失效，断点会被静默吞掉。"
        )

    def test_delta_section_names_every_breakpoint(self):
        module = _generator()
        text = _inventory_text()
        delta = text.split("## 三、差集")[-1].split(module.BLOCK_END)[0]
        for point in module.zeroRouteMountPoints():
            assert point in delta, (
                f"零路由挂载点 {point} 未在差集节显式点名——断点必须暴露。"
            )
        for relative, expected in module.frontendContractBreaks():
            assert expected in delta, (
                f"{relative} 请求的 {expected} 在后端无对应路由（必 404），"
                "差集节必须点名，不得用「大致一致」带过。"
            )
        for _module, name, point in module.unwiredRouters():
            assert name in delta, (
                f"未接线 router `{name}`（挂 `{point}`）未在差集节点名。"
            )


class TestSnapshotDisciplineIsOnTheHeader:
    def test_header_declares_generation_command(self):
        head = "\n".join(_inventory_text().splitlines()[:24])
        assert "scripts/generate_api_inventory.py" in head, (
            "头部未写明生成命令——读者无法自行对齐，清单过期时只能猜。"
        )

    def test_header_declares_generation_date(self):
        head = "\n".join(_inventory_text().splitlines()[:24])
        assert DATE_PATTERN.search(head), "头部未写明生成日期（快照纪律要求）"

    def test_header_names_the_fact_sources(self):
        head = "\n".join(_inventory_text().splitlines()[:24])
        assert "NeurUI/src/api/modules/" in head, "头部未指明前端模块的现行事实源"
        assert "neurova/api/endpoints/" in head, "头部未指明后端端点的现行事实源"


class TestGeneratedBlockIsWritableAndIdempotent:
    def test_block_markers_are_present(self):
        module = _generator()
        text = _inventory_text()
        assert text.count(module.BLOCK_BEGIN) == 1 and text.count(module.BLOCK_END) == 1, (
            "机器区标记缺失或重复——生成器定位不到该写哪里。"
        )

    def test_writer_is_idempotent_on_the_shipped_document(self):
        module = _generator()
        original = _inventory_text()
        assert module.applyInventory(original) == original, (
            "清单与生成器已不同步：把生成结果写回后正文仍会变。\n"
            "修法：python scripts/generate_api_inventory.py --write"
        )

    def test_writer_restores_a_drifted_block(self):
        """负向控制：注入漂移 → 生成器必须把它拉回真值（门禁不空转）。"""
        module = _generator()
        original = _inventory_text()
        drifted = original.replace(
            module.BLOCK_BEGIN, module.BLOCK_BEGIN + "\n陈旧行：`src/api/modules/removed_zzz.ts`"
        )
        assert drifted != original, "注入漂移失败"
        restored = module.applyInventory(drifted)
        assert "removed_zzz" not in restored, (
            "生成器未能把漂移区块拉回真值（替换不彻底，门禁会空转）。"
        )
        assert restored == original, "生成器写回后的正文与真值不一致"


class TestScreeningAccountIsSettled:
    """销账闭环：清单不再把人指错 → 指路条目入筛数归零，棘轮同步下调。"""

    def test_pointer_entries_drop_to_zero(self):
        scanner = importlib.import_module("scripts.scan_docs_refs")
        rows = [row for row in scanner.navigationImpactRefs()
                if row["form"] == scanner.IMPACT_FORM_POINTER]
        assert not rows, (
            f"重生成后仍有 {len(rows)} 条指路条目入筛——清单里还有不可解析的路径引用，"
            "读者会顺着它走错路。"
        )

    def test_pointer_ratchet_is_lowered(self):
        scanner = importlib.import_module("scripts.scan_docs_refs")
        limit = int(io.open(scanner.POINTER_ENTRY_BASELINE, encoding="utf-8").read().strip())
        assert limit == 0, (
            f"棘轮基线仍为 {limit}：销账必须同批下调到 0（Issue #112 验收）。"
        )

    def test_ledger_records_regeneration_and_snapshot_date(self):
        text = _ledger_text()
        section = text.split("### 8.5")[-1].split("## 九")[0]
        assert "已重生成" in section and DATE_PATTERN.search(section), (
            "台账第八节未把该行改记为「已重生成 + 快照日期」——销账没落账。"
        )

    def test_navigation_placement_is_decided_and_recorded(self):
        """导航归属必须做出决定并写下来：留作现行清单，或降级为历史快照。"""
        text = _ledger_text()
        section = text.split("### 8.5")[-1].split("## 九")[0]
        assert "0-index/README.md" in section, (
            "未记录导航归属的裁定（是否仍留在 `docs/0-index/README.md` 的领域入口表里）。"
        )
