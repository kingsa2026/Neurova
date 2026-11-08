# -*- coding: utf-8 -*-
"""许可面守卫——AGPL/GPL 族强传染依赖在 requirements 与发行物两面的下界钉。

背景（2026-11-08 许可审计报告）：PyMuPDF（pypi:pymupdf，AGPL-3.0-or-later 或
Artifex 商业双许可，审计侧归并口径 GPL-3.0-PLUS）被标高风险。处置拍板：
- 用法面（document_pipeline 的 PDF 元数据 + OCR 页渲染两触点）迁移
  pypdfium2（BSD-3-Clause / Apache-2.0，PDFium 同级内核），requirements 摘除
  PyMuPDF——高风险标记彻底闭口；
- 发行物纯净性：Neurova 安装包（tauri bundle，见 MANIFEST.json）只携带自家
  源码树与 requirements.txt，第三方 Python 产物一律由用户机从 PyPI 取得——
  「引用不构成分发」姿态钉成本守卫，发行物一旦混入第三方 wheel/二进制即红。

登记关注（不在 denylist，保留须先在此写明理由）：
- edge-tts（LGPL-3.0，v7 起由 GPL 放宽）：库形态引用、TTS fallback 主链路，
  替换代价与风险不成比例；
- MouseInfo（GPLv3+）：pyautogui（BSD-3）的传递依赖，本仓无直接 import；
- odfpy（Apache-2.0 / GPL / LGPL 多许可）：按 Apache-2.0 选举消费。
"""

import io
from pathlib import Path

RULE_ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = RULE_ROOT / "requirements.txt"
TAURI_BACKEND = RULE_ROOT / "NeurUI" / "src-tauri" / "resources" / "backend"

#: requirements 中不允许出现的强传染直接依赖（小写归一）。新增候选先进
#: docstring 登记关注评估平替可行性；确认须保留的在此说明理由，不进本表。
_DENYLIST = {"pymupdf"}

#: 发行物里不允许出现的第三方 Python 产物形态（文件/目录名小写包含）。
_PURITY_DENY_PATTERNS = ("site-packages", "mupdf", ".whl", ".pyd")


def _declared_names(path: Path) -> list:
    names = []
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        head = line.split("#")[0].split(";")[0]
        for sep in (">=", "==", "<", ">", "["):
            head = head.split(sep)[0]
        names.append(head.strip().lower())
    return names


class TestRequirementsNoHighRiskCopyleft:
    def test_declared_deps_denylist(self):
        declared = _declared_names(REQUIREMENTS)
        hit = sorted(set(declared) & _DENYLIST)
        assert not hit, (
            f"requirements.txt 声明了强传染依赖: {', '.join(hit)}——"
            "AGPL/GPL 族须平替（pymupdf→pypdfium2 先例）或走商业许可；"
            "确需保留的先在模块 docstring 登记关注并写明理由，再移出本表"
        )

    def test_denylist_names_actually_parse(self):
        """防空账：denylist 里的名字若在声明面永远匹配不上，守卫就是摆设。"""
        declared = set(_declared_names(REQUIREMENTS))
        known = {"pypdfium2"}
        assert known <= declared, (
            f"本守卫的锚点包 {sorted(known)} 已不在 requirements 声明面——"
            "依赖面结构变更须同步修订本守卫的锚点"
        )


class TestTauriBundleStaysPure:
    def test_bundle_carries_no_third_party_python_artifacts(self):
        assert TAURI_BACKEND.is_dir(), (
            "发行物 backend 目录不存在——Neurova 打包结构变更须同步修订本守卫的落点"
        )
        hit = []
        for path in sorted(TAURI_BACKEND.rglob("*")):
            name_lower = path.name.lower()
            if any(pattern in name_lower for pattern in _PURITY_DENY_PATTERNS):
                hit.append(str(path.relative_to(TAURI_BACKEND)))
        assert not hit, (
            "发行物混入第三方 Python 产物（引用不构成分发的姿态被破坏）:\n  "
            + "\n  ".join(hit[:20])
        )
