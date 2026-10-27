# -*- coding: utf-8 -*-
"""`neurova/media/manager.py`(184) 已按甲方案退役（§6-139）。

它此前是通用 KV 之外那对"同职两份"的一半：资产索引。REST 端点自持另一半
（`api/endpoints/media.py` 的 `media_index.json`），而 manager 那份**生产零消费者**、
唯一用者是它自己的测试。§6-128 一度把它列进"可径退役"，逐格比对后撤回——它握着端点没有的
**落盘字节 sha256 校验位**。用户裁甲：先取长补短再退。

已并过去的：① 校验位（上传时随字节流算，索引里存 `checksum`，
`GET /{media_id}/metadata` 真读盘重算回 `checksum_ok`）；② 索引写侧的锁
（manager 那份有 `self._lock`，端点这份此前是裸 dict + 裸 dump，两路并发上传会互相覆盖条目）。
**没有并过去的**：`update_media()`（改任意元数据字段，零消费者、无需求，按 §6-125 对 `clear()`
同口径处理——不因为"原来有"就搬家）；`get_stats()` 不需并（端点早有 `GET /stats/{agent_id}`）。

本文件钉"别再长出第二份资产索引"，并反向钉住在役那两件不许被这波带走。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "neurova"
TESTS = REPO / "tests"
RETIRED = "neurova.media.manager"

pytestmark = pytest.mark.timeout(60)


def _importers(root: Path) -> list[str]:
    """子树里仍 import 已退役面的文件清单。

    取数走 `tests/ast_scan` 的共享解析预算（`sourceRefsUnder` + 文本预筛），
    不私有 `rglob + ast.parse`——后者把判据成本绑在代码总量上
    （`tests/unit/test_ci_ast_scan_budget_guard.py` 判红的正是这处）。
    预筛词是判据的**充分条件**：连退役模块名都没出现的文件不可能 import 它。
    """
    out = []
    for ref in ast_scan.sourceRefsUnder(root, ".py", ast_scan.textHints(RETIRED)):
        try:
            tree = parseSource(ref.code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if any(n == RETIRED or n.startswith(RETIRED + ".") for n in names):
                try:
                    out.append(ref.path.relative_to(REPO).as_posix())
                except ValueError:
                    out.append(ref.path.name)
                break
    return out


def test_retiredFileIsGone():
    assert not (PKG / "media" / "manager.py").is_file(), "第二份资产索引又回到包里"


def test_nobodyImportsIt():
    found = _importers(PKG) + _importers(TESTS)
    assert not found, f"退役的 MediaManager 又被人引用：{found}"


def test_survivingFacesUntouched():
    """反向对照（防删过头）：并过去的格子与仍在役的另一半必须在位。"""
    ep = (PKG / "api" / "endpoints" / "media.py").read_text(encoding="utf-8")
    assert "hashlib.sha256" in ep, "校验位的写侧没了"
    assert "checksum_ok" in ep, "校验位的读侧判定没了"
    assert "_INDEX_LOCK" in ep, "索引写侧的锁没了——并发上传会互相覆盖条目"
    assert (PKG / "media" / "config.py").is_file(), (
        "media/config.py 属需人裁（§6-128），不许被这波顺手带走")
    assert (TESTS / "unit" / "api" / "test_mediaChecksumIsRecorded.py").is_file(), (
        "并过来的能力判据不在了")


def test_scannerCatchesARevival(tmp_path):
    bad = tmp_path / "revival.py"
    bad.write_text(f"from {RETIRED} import MediaManager\n", encoding="utf-8")
    assert _importers(tmp_path) == ["revival.py"]
    bad.unlink()
    assert not _importers(tmp_path)
