"""产物 kind 分派的两份表必须同映射（工单 007 的防分叉锁）

后端 `neurova/api/endpoints/artifacts_api.py::_KIND_BY_EXT` 与前端
`NeurUI/src/utils/artifacts.ts::KIND_BY_EXT` 是同一张表的两个副本，两边注释都写着
"与对方对齐"——但注释不是约束。PDF 就是漏网的一例：两处都没登记，产物卡点开 PDF
掉进 text 面板按文本渲染二进制。

本文件纯静态解析两份表（不 import 应用、不起前端），因此不受依赖与环境影响：
守卫若因缺依赖而跑不起来，就等于没有守卫（Issue #62 的教训）。
"""

import re

from tests.repo_paths import repo_path

_PAIR_RE = re.compile(r"""["']?\.?([a-z0-9]+)["']?\s*[:=]\s*["']([a-z]+)["']""")


def _block(rel: str, marker: str) -> str:
    text = repo_path(rel).read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    return text[start : text.index("}", start)]


def _backend_map() -> dict:
    return {ext.lstrip("."): kind for ext, kind in _PAIR_RE.findall(_block(
        "neurova/api/endpoints/artifacts_api.py", "_KIND_BY_EXT = {"
    ))}


def _frontend_map() -> dict:
    return dict(_PAIR_RE.findall(_block("NeurUI/src/utils/artifacts.ts", "const KIND_BY_EXT")))


def test_pdf_is_routed_to_its_own_kind_not_text():
    """回归锁：pdf 曾缺席两张表，退化成 text 面板渲染二进制。"""
    assert _backend_map().get("pdf") == "pdf"
    assert _frontend_map().get("pdf") == "pdf"


def test_both_kind_tables_agree():
    backend, frontend = _backend_map(), _frontend_map()
    only_backend = {k: v for k, v in backend.items() if frontend.get(k) != v}
    only_frontend = {k: v for k, v in frontend.items() if backend.get(k) != v}
    assert not only_backend and not only_frontend, f"分派表分叉: 仅后端={only_backend} 仅前端={only_frontend}"
