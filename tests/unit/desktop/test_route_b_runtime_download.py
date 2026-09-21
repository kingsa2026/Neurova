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
6. 归档落地只允许一种形状——PowerShell Move-Item 的目标若是已存在目录就把源
   「移入其内」，node.exe 落到多一层目录里，就绪判定恒不命中（本机实测）；
   Python 与 Node 因此共用 relocate_payload。
7. 后端根只有一个出处——boot 页曾用 v1 的 invoke('tauri', {__tauriModule:'path'})
   自行解析，v2 下该命令不存在即落 catch 返回 '.'，与 Rust 的
   resource_dir/backend 差一层：清单读不到、下载落错目录、后端入口找不到。
   命令面上不再有 root 参数，前端才没有可传错的东西。
8. 下载源也在清单里——URL 硬编码在 lib.rs 就要与清单各存一份版本；镜像在前、
   官方兜底的有序候选必须是同一份声明。
9. tar.gz 不许交给 Expand-Archive（实测只认 .zip），且 tar 失败必须交出 stderr
   原文，不许抹成「文件不完整」。
10. 后端进程退了就必须立刻结束就绪轮询。真机取证：裸 CPython 缺 uvicorn 秒退，
    轮询只看 /health 于是首启白等满 120 秒才报错。
11. 失败提示里的日志路径只能来自 BOOT_LOG_PATH，且 boot 页拉日志要推进 offset——
    写死的 backend\\backend.log 让用户照着找不到文件，固定 logOffset: 0 则每
    700ms 重读整份日志。
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LIB_RS = _REPO / "NeurUI" / "src-tauri" / "src" / "lib.rs"
_MANIFEST = _REPO / "models" / "MANIFEST.json"
_BOOT_PAGE = _REPO / "NeurUI" / "src-tauri" / "src" / "boot_page.html"

_SRC = _LIB_RS.read_text(encoding="utf-8")
_BOOT_SRC = _BOOT_PAGE.read_text(encoding="utf-8")


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _code_only(src: str) -> str:
    """滤掉整行注释：守卫要禁的是调用，不是「为什么不用它」的说明。

    代价是注释掉的调用能蒙混过关——这两处守卫盯的 PowerShell 行为都发生在
    字符串字面量里，真被注释掉就不再是行为。
    """
    return "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("//")
    )


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

    def test_manifest_declares_runtime_specs(self):
        """清单是运行时版本与下载源的单源，缺了这个出处下面的守卫无从校验。"""
        runtime = _manifest().get("runtime") or {}
        for component in ("python", "node"):
            spec = runtime.get(component) or {}
            assert spec.get("version"), f"清单 runtime.{component}.version 缺失"
            assert spec.get("urls"), f"清单 runtime.{component}.urls 缺失"


class TestRuntimeSourceCandidates:
    """下载源的唯一出处是清单，且每个组件都带「国内镜像在前、官方源兜底」的有序候选。

    搬运原因：URL 硬编码在 lib.rs，版本就得在 lib.rs 与清单各存一份，抄慢一步即
    404（第 2、3 条守卫就是为此而生）。国内直连 GitHub Releases / nodejs.org 不稳
    是这条链路的首要失败因，所以镜像与官方源必须是同一份声明里的有序候选，
    而不是在 Rust 里再开一份常量。
    """

    OFFICIAL = {
        "python": "github.com/astral-sh/python-build-standalone",
        "node": "nodejs.org",
    }

    def _spec(self, component: str) -> dict:
        return (_manifest().get("runtime") or {}).get(component) or {}

    @pytest.mark.parametrize("component", ["python", "node"])
    def test_candidates_are_ordered_mirror_then_official(self, component):
        urls = self._spec(component).get("urls") or []
        assert len(urls) >= 2, f"runtime.{component}.urls 至少要一个镜像 + 一个官方源: {urls}"
        assert self.OFFICIAL[component] in urls[-1], (
            f"末位必须是官方源兜底，实际: {urls[-1]}"
        )
        assert self.OFFICIAL[component] not in urls[0], (
            f"首位应是国内镜像（默认下载体验），官方源不该排第一: {urls[0]}"
        )

    @pytest.mark.parametrize("component", ["python", "node"])
    def test_every_candidate_carries_the_declared_version(self, component):
        spec = self._spec(component)
        for url in spec.get("urls") or []:
            assert url.startswith("https://"), f"运行时二进制必须走 HTTPS: {url}"
            assert spec["version"] in url, (
                f"候选源版本与 runtime.{component}.version={spec['version']} 不一致: {url}"
            )

    def test_python_candidates_are_tag_self_consistent(self):
        """资产名内嵌的构建号必须等于所在 release 目录段，且不得借道 latest。

        形状与源无关：官方是 …/releases/download/<tag>/<asset>，镜像是自定义
        目录，但「<tag> 段 == 资产名里的 +<build>」这一条对两者同等成立——
        它才是 404 的真正防线（latest 会漂移，带日期的资产名钉在某一次构建上）。
        """
        for url in self._spec("python").get("urls") or []:
            assert "/latest/" not in url, f"latest 会随上游发版漂移：{url}"
            head, _, asset = url.rpartition("/")
            m = re.search(r"cpython-([\d.]+)\+(\d+)-", asset)
            assert m, f"资产名里没有 版本+构建号，无法核对是否悬空: {url}"
            assert m.group(2) == head.rsplit("/", 1)[-1], (
                f"资产构建号 {m.group(2)} 与所在目录段不一致: {url}"
            )

    def test_lib_rs_has_no_hardcoded_release_url(self):
        offenders = re.findall(
            r'"(https://[^"]*(?:python-build-standalone|nodejs\.org)[^"]*)"', _SRC
        )
        assert not offenders, (
            f"lib.rs 内仍硬编码下载源，版本又要变成两份抄本: {offenders}"
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


class TestPayloadRelocation:
    """归档落地只允许一种形状：含 exe 的那一层原子改名成 runtime/<组件>/。

    断裂实证：download_node_runtime 先 create_dir_all(runtime/node) 再让
    PowerShell `Move-Item …\\node-v24.16.0-win-x64 runtime\\node`。Move-Item 的
    语义是「目标为已存在目录时移入其内」，产物于是落在
    runtime/node/node-v24.16.0-win-x64/node.exe，而就绪判定读的是
    runtime/node/node.exe → 恒判失败，30MB 反复重下（本机实测：
    node.exe at root: False / nested: True）。Python 侧走 fs::rename 却是对的，
    两条路径形状分叉正是这类 bug 的温床，故收敛为单一 relocate_payload。
    """

    def _body(self, fn: str) -> str:
        m = re.search(rf"fn {fn}\(.*?\n\}}", _SRC, re.S)
        assert m, f"lib.rs 找不到 {fn}"
        return m.group(0)

    def test_no_powershell_move_item_remains(self):
        assert "Move-Item" not in _code_only(_SRC), (
            "lib.rs 仍用 PowerShell Move-Item 落地运行时：目标为已存在目录时它把源"
            "移入其内，产物多一层导致就绪判定永不命中"
        )

    @pytest.mark.parametrize("fn", ["download_python_runtime", "download_node_runtime"])
    def test_both_runtimes_land_through_one_helper(self, fn):
        body = self._body(fn)
        assert "relocate_payload" in body, (
            f"{fn} 未走 relocate_payload，两条运行时落地路径又分叉了"
        )

    def test_relocate_removes_stale_dst_before_rename(self):
        """rename 到已存在目录会失败或移入其内，落地前必须先清 dst。"""
        m = re.search(r"fn relocate_payload\(.*?\n\}", _SRC, re.S)
        assert m, "lib.rs 找不到 relocate_payload"
        body = m.group(0)
        assert "remove_dir_all(dst)" in body, "relocate_payload 未清理已存在的 dst"
        assert body.index("remove_dir_all(dst)") < body.index("rename"), (
            "必须先清 dst 再 rename，顺序反了就把 bug 留在原地"
        )


class TestBackendRootSingleSource:
    """后端根只允许一个出处：Rust 的 resolve_backend_root。

    断裂实证：boot 页 getRoot() 调 invoke('tauri', {__tauriModule:'path',
    cmd:'resolveResource', path:'backend'})——那是 v1 的远程命令形态，v2 的 path
    API 走 plugin:path|resolve_directory（见 @tauri-apps/api/path.js），命令不
    存在即落 catch 返回 '.'。打包态 '.' 是 exe 目录，后端却在 <exe 同级>/backend
    （installer.nsi 把 resources 拷到 $INSTDIR\\backend）——差一层的后果是清单读
    不到（误报缺模型）、下载落到 <exe>\\runtime、trigger_backend_start 找不到
    start_server.py。把 root 从命令参数面上删掉，前端就没有可传错的东西。
    """

    _ROOT_TAKERS = ("check_runtime_ready", "start_download", "trigger_backend_start")

    def test_boot_page_no_longer_resolves_root_itself(self):
        offenders = [
            needle for needle in ("__tauriModule", "resolveResource", "function getRoot")
            if needle in _BOOT_SRC
        ]
        assert not offenders, (
            f"boot 页仍在自行解析后端根: {offenders}——v1 形态在 v2 下必然落 catch 返回 '.'"
        )

    @pytest.mark.parametrize("fn", _ROOT_TAKERS)
    def test_command_signature_takes_no_root(self, fn):
        m = re.search(rf"fn {fn}\((.*?)\)\s*(->|\{{)", _SRC, re.S)
        assert m, f"lib.rs 找不到 {fn}"
        sig = m.group(1)
        assert "root" not in sig, f"{fn} 仍从前端收 root，等于保留第二个出处"
        assert "tauri::AppHandle" in sig, f"{fn} 需要 AppHandle 才能自行解析 root"

    @pytest.mark.parametrize("fn", _ROOT_TAKERS)
    def test_boot_page_invokes_without_root(self, fn):
        for call in re.findall(rf"invoke\(\s*'{fn}'\s*,\s*(\{{.*?\}})", _BOOT_SRC, re.S):
            assert "root" not in call, f"boot 页仍在给 {fn} 传 root: {call}"


class TestPythonArchiveExtraction:
    """.tar.gz 只有 tar/bsdtar 解得开，Expand-Archive 结构上不支持它。

    本机实测：Expand-Archive 对 gzip 报「.gz 不是支持的存档文件格式，只有 .zip
    扩展名支持」。原实现把这条回退挂在 tar 失败之后，且 .output() 结果用 let _ =
    丢弃，于是真因（缺 tar / 格式不支持）在状态文件里被统一抹成「Python 解压失败，
    文件不完整」——按修复教义第 3 条属表面抹除，必须把 stderr 原文交出来。
    """

    def _body(self) -> str:
        m = re.search(r"fn download_python_runtime\(.*?\n\}\n", _SRC, re.S)
        assert m, "lib.rs 找不到 download_python_runtime"
        return _code_only(m.group(0))

    def test_no_powershell_in_python_path(self):
        body = self._body().lower()
        offenders = [needle for needle in ("expand-archive", "powershell") if needle in body]
        assert not offenders, (
            f"download_python_runtime 仍依赖 {offenders} 解 tar.gz：该 cmdlet 只认 .zip"
        )

    def test_tar_failure_surfaces_stderr(self):
        body = self._body()
        assert "stderr" in body, (
            "tar 失败时未取 stderr，真因会被抹成「文件不完整」"
        )
        assert not re.search(r'let _ = Command::new\("tar"\)', body), "tar 的调用结果被 let _ = 丢弃"


class TestBackendFailureIsVisible:
    """首启失败要说清「去哪儿看日志」，而且路径必须是真的。

    真机取证：后端秒退（下载来的裸 CPython 缺 uvicorn），提示却写着「详见安装
    目录 backend\\backend.log」——实际日志在 <后端根>/logs/backend-<YYYYMMDD>.log，
    用户照提示找不到任何文件。路径的唯一事实源是 Rust 的 BOOT_LOG_PATH，
    由 boot_tail 一并回吐给页面。
    """

    def test_no_hint_points_at_a_stale_log_file(self):
        for name, src in (("lib.rs", _SRC), ("boot_page.html", _BOOT_SRC)):
            offenders = [
                line.strip() for line in src.splitlines()
                if "详见" in line and "backend.log" in line
            ]
            assert not offenders, f"{name} 的提示仍指向写死的旧日志名: {offenders}"

    def test_log_path_reaches_the_page_from_rust(self):
        assert re.search(r'"logPath"', _SRC), "boot_tail 没把真实日志路径回吐给页面"
        assert "logPath" in _BOOT_SRC, "boot 页仍在自己编日志路径"


class TestBootLogTailing:
    """boot 页拉日志必须推进 offset。

    固定传 logOffset: 0 会让每 700ms 一次的轮询把整份日志从头重读并重贴一遍，
    后端日志越长越卡，而用户看到的还是同一批行。
    """

    def test_offset_is_advanced_not_pinned_at_zero(self):
        assert not re.search(r"invoke\(\s*'boot_tail'\s*,\s*\{\s*logOffset:\s*0\s*\}\s*\)", _BOOT_SRC), (
            "boot 页每次都用 logOffset: 0 拉日志，等于反复重读整份文件"
        )
        assert "p.offset" in _BOOT_SRC, "未消费 boot_tail 回吐的 next offset"


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
