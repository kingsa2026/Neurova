# -*- coding: utf-8 -*-
"""路线 B（轻壳 + 首启自动下载运行时）的下载链路契约。

这些不变式各自对应一个已发生的断裂：

1. models/MANIFEST.json 必须入库——lib.rs 读它是 ok_or 硬失败，文件不在版本库
   就等于干净检出的安装包永远起不来（工作树里有，HEAD 里没有，正是最容易被
   掩护的一类断链）；
2. 运行时版本只允许有一个出处——清单声明 runtime.python/runtime.node，
   下载 URL 里再抄一份具体版本，抄慢一步就是 404（实测：URL 写死
   cpython-3.12.5+20250916 挂在 releases/latest 下，而 latest 资产是
   cpython-3.12.14+20260901）；
3. latest 语义不能和「资产名内嵌构建日期」混用——latest 会随上游发版漂移，
   而带日期的资产名钉死在某一次构建上，二者拼在一起必然悬空，
   所以 URL 必须是 releases/download/<tag>/<同一 tag 的资产名> 自洽形式；
4. 下载状态是运行态，不得落在后端根目录——开发态后端根就是仓库根，
   一次失败的下载会把错误现场写成仓库根下一个未跟踪文件；
5. Rust 侧的清单结构必须能吃下真清单——字段对不上时 serde 整体失败，
   表现是「清单不存在」，比直接报错更难查；清单里的 path 自带 models/
   前缀，再往 models 目录上拼就变成双前缀，永远判为未就绪。
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LIB_RS = _REPO / "NeurUI" / "src-tauri" / "src" / "lib.rs"
_MANIFEST = _REPO / "models" / "MANIFEST.json"

_SRC = _LIB_RS.read_text(encoding="utf-8")


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


class TestManifestIsCommitted:
    def test_model_manifest_is_tracked(self):
        """问 git 不问磁盘：文件在工作树里存在不代表它进了 HEAD。"""
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "models/MANIFEST.json"],
            cwd=_REPO, capture_output=True,
        )
        assert r.returncode == 0, (
            "models/MANIFEST.json 未入库，但 lib.rs 读它是硬失败 → "
            "干净检出的路线 B 起不来。git 说："
            + r.stderr.decode("utf-8", "replace").strip()
        )

    def test_manifest_declares_runtime_versions(self):
        """清单是运行时版本的单源，缺了这个出处，第 2 条守卫无从校验。"""
        runtime = _manifest().get("runtime") or {}
        assert runtime.get("python"), "清单 runtime.python 缺失"
        assert runtime.get("node"), "清单 runtime.node 缺失"


class TestRuntimeDownloadUrl:
    def _url(self, needle: str) -> str:
        m = re.search(r'"(https://[^"]*%s[^"]*)"' % re.escape(needle), _SRC)
        assert m, f"lib.rs 里找不到 {needle} 的下载 URL"
        return m.group(1)

    def test_python_url_is_tag_and_asset_self_consistent(self):
        """必须是 releases/download/<tag>/<同名 tag 的资产>，不得借道 latest。"""
        url = self._url("python-build-standalone")
        assert "/releases/latest/" not in url, (
            f"latest 会随上游发版漂移，与内嵌构建日期的资产名拼在一起必然 404：{url}"
        )
        m = re.search(r"/releases/download/(\d+)/cpython-([\d.]+)\+(\d+)-", url)
        assert m, f"URL 不是 tag 自洽形式：{url}"
        assert m.group(1) == m.group(3), (
            f"release tag {m.group(1)} 与资产内构建号 {m.group(3)} 不一致：{url}"
        )

    def test_runtime_versions_are_not_mirrored_from_manifest(self):
        """URL 里的版本必须等于清单声明的版本——一处改动即可，不许两份抄本。"""
        declared = _manifest()["runtime"]
        py = re.search(r"cpython-([\d.]+)\+", self._url("python-build-standalone"))
        assert py and py.group(1) == declared["python"], (
            f"Python 版本漂移：URL={py and py.group(1)} 清单={declared['python']}"
        )
        node = re.search(r"node-v(\d+\.\d+\.\d+)-win", self._url("nodejs.org"))
        assert node and node.group(1) == declared["node"], (
            f"Node 版本漂移：URL={node and node.group(1)} 清单={declared['node']}"
        )


class TestDownloadStatusLocation:
    def test_status_file_lives_under_runtime_dir(self):
        """读与写都必须落在 runtime/ 下，不得污染后端根（开发态即仓库根）。"""
        for fn in ("read_download_status", "write_download_status"):
            body = re.search(rf"fn {fn}\(.*?\n\}}", _SRC, re.S)
            assert body, f"lib.rs 找不到 {fn}"
            joined = re.findall(r"root\.join\(([^)]*)\)", body.group(0))
            offenders = [j for j in joined if "runtime" not in j]
            assert not offenders, (
                f"{fn} 直接把状态文件拼在 root 下（dev 态 root=仓库根）: {offenders}"
            )

    def test_repo_root_has_no_stray_status_file(self):
        """运行态不该出现在仓库根——它一旦被看见，就该被清掉或忽略。"""
        stray = _REPO / ".download_status.json"
        assert not stray.exists(), (
            f"仓库根残留下载状态文件 {stray}：它已被移出写入位置，应删除"
        )


class TestManifestReadContract:
    """Rust 结构体与真清单的字段/路径交叉校验。"""

    def _required_fields(self) -> set:
        body = re.search(r"struct ModelEntry \{(.*?)\n\}", _SRC, re.S)
        assert body, "lib.rs 找不到 struct ModelEntry"
        required = set()
        for line in body.group(1).splitlines():
            if not line.strip() or line.strip().startswith("//"):
                continue
            f = re.match(r"\s*(\w+): (.+?),\s*$", line)
            assert f, f"ModelEntry 有解析不了的字段行: {line!r}"
            if not f.group(2).startswith("Option<"):
                required.add(f.group(1))
        return required

    def test_every_manifest_entry_satisfies_the_struct(self):
        """非 Option 字段必须在每个条目里都有，否则 serde 整体失败。"""
        required = self._required_fields()
        for entry in _manifest()["models"]:
            absent = required - set(entry)
            assert not absent, (
                f"模型 {entry.get('id')} 缺必填字段 {sorted(absent)} → "
                "read_model_manifest 会整体反序列化失败，表现得像清单不存在"
            )

    def test_model_paths_are_joined_against_root_not_models_dir(self):
        """清单 path 自带 models/ 前缀，再拼 layout.models 就是双前缀。"""
        prefixed = [
            e["path"] for e in _manifest()["models"] if e["path"].startswith("models/")
        ]
        assert len(prefixed) == len(_manifest()["models"]), (
            f"清单约定是 path 含 models/ 前缀，出现例外: {prefixed}"
        )
        doubled = re.findall(r"layout\.models\.join\(&?\s*(?:m|model|entry)\.path\)", _SRC)
        assert not doubled, (
            "模型路径拼成 root/models/models/... 会永远判为未就绪，改用 layout.root 拼"
        )
