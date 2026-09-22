# -*- coding: utf-8 -*-
"""Issue #62 收口守卫：开发机绝对路径 + MCP SDK 运行时声明。

两类"CI 全绿、线上挂"的偏差，各钉一条不变量：

1. **守卫测试静默不跑** —— 测试文件里写死「盘符 + 仓库目录」形态的
   Windows 开发机**绝对路径**后，在 Linux/CI 上不是断言失败而是
   `FileNotFoundError` 直接炸：守卫**根本没跑起来**。更隐蔽的一层是
   这些守卫当时还不在 `scripts/ci/protected_tests.txt` 里——CI 连炸都看不见。
   本类同时钉住：路径不得写死 + 受保护子集必须收录这些守卫。

2. **运行时依赖只写在 CI 清单** —— `mcp>=1.2.0` 原只在 requirements-ci.txt。
   生产按 requirements.txt 安装时 mcp 缺席，`mcp_client.connect_server`
   走 `_SDK_AVAILABLE=False` 分支：**不抛异常**，只把
   `last_error` 记成"mcp SDK 未安装"——真实连接失败原因被掩盖，MCP 全断
   而 CI 全绿。本类钉住运行时安装路径（requirements.txt + 全量锁）必须声明。

3. **守卫依赖 CI 镜像里没有的外部二进制** —— 同一"守卫静默不跑"根因的另一形态：
   `tests/unit/test_tool_call_breakpoints_v3.py` 用 `subprocess.run(["rg", ...])`
   做死代码扫描，而 python:3.11/3.12 镜像里没有 ripgrep → `FileNotFoundError`
   直接炸，文件其余断言全废。扫描类守卫必须用纯 Python（`Path.rglob` +
   字符串/`ast`），不得依赖 `rg` / `grep` 等宿主工具。
"""

import io
import re
import shutil
import subprocess
from pathlib import Path

from tests import ast_scan

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 开发机仓库根路径特征：盘符 + 仓库目录名（Neurova / 项目）。
# 只匹配"指向本项目"的形态，不误伤 C:\Windows 这类真实平台常量。
_DEV_PATH = re.compile(r"[A-Za-z]:[\\/][\\/]?\s*(?:项目|neurova\b)", re.IGNORECASE)

# 允许清单：写死盘符路径是**被测数据**而非"找仓库"的地方。
# 每条必须说明为什么不能改成 REPO_ROOT 推导。
_ALLOWED = {
    "tests/unit/core/test_ffmpeg_subtitle.py":
        "断言 ffmpeg filter 转义的输入夹具（含中文目录的 Windows 路径），"
        "本身就是被测数据，不是仓库定位",
}


def _iter_py_files(root):
    for path in sorted((PROJECT_ROOT / root).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


class TestNoHardcodedDevMachinePaths:
    def test_no_dev_repo_path_in_tests(self):
        offenders = []
        for path in _iter_py_files("tests"):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel in _ALLOWED:
                continue
            for lineno, line in enumerate(
                io.open(path, encoding="utf-8").read().splitlines(), 1
            ):
                if _DEV_PATH.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        assert not offenders, (
            "测试文件写死了开发机绝对路径（Linux/CI 上 open()/cwd= 直接 "
            "FileNotFoundError，守卫测试静默不跑）：\n  " + "\n  ".join(offenders) +
            "\n修复：改用 tests/repo_paths.py 的 REPO_ROOT / repo_path() / repo_str()。"
        )

    def test_repo_paths_helper_exists_and_points_at_repo(self):
        """共享助手必须存在且解析到真实仓库根（否则上面那条只是换了个写法）。"""
        from tests.repo_paths import REPO_ROOT, repo_path, repo_str

        assert (REPO_ROOT / "neurova").is_dir(), f"REPO_ROOT 未指向仓库根: {REPO_ROOT}"
        assert repo_path("neurova", "tool_layers", "tool_router.py").is_file()
        assert repo_str("neurova") == str(REPO_ROOT / "neurova")


class TestToolLayerGuardsAreInProtectedSubset:
    """守卫测试必须真进 CI 受保护子集——"绿"要和"跑过"是同一件事。"""

    # Issue #62 明确点名的守卫（tool_router 静默 except / falsy registry /
    # 死代码 import 三例），此前不在子集里，回归时 CI 静默放行。
    REQUIRED = (
        "tests/unit/tools/test_tool_layer_breakpoints_zoom_out.py",
        "tests/unit/test_arch_deepening_candidates.py",
        "tests/unit/test_tool_call_breakpoints.py",
        "tests/unit/test_tool_call_breakpoints_v2.py",
        "tests/unit/test_tool_call_breakpoints_v3.py",
    )

    def test_guards_listed_in_protected_tests(self):
        listed = set()
        for raw in io.open(
            PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt", encoding="utf-8"
        ).read().splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                listed.add(line)
        missing = [f for f in self.REQUIRED if f not in listed]
        assert not missing, (
            "受保护子集未收录工具层守卫测试——守卫写在那里但 CI 不跑，"
            f"回归静默放行：{missing}\n修复：加进 scripts/ci/protected_tests.txt。"
        )

    @pytest.mark.parametrize("rel", REQUIRED)
    def test_guard_module_has_no_unrunnable_paths(self, rel):
        """守卫测试 import 期不得依赖开发机路径（import 期炸 = 整个文件收集失败）。"""
        src = io.open(PROJECT_ROOT / rel, encoding="utf-8").read()
        assert not _DEV_PATH.search(src), f"{rel} 仍含开发机路径"


class TestMcpSdkDeclaredForRuntime:
    """MCP SDK 必须在**生产安装路径**上声明（不只是 CI 清单）。"""

    def test_declared_in_runtime_requirements(self):
        lines = io.open(PROJECT_ROOT / "requirements.txt", encoding="utf-8").read().splitlines()
        decl = [
            l.strip() for l in lines
            if re.match(r"^\s*mcp\s*[><=!~]", l.strip())
        ]
        assert decl, (
            "requirements.txt 未声明 mcp——生产（Dockerfile / install.py 都装这份）"
            "装上后 mcp_client 的 _SDK_AVAILABLE=False，所有 stdio/http MCP 服务器"
            "连接失败且 last_error 只记'SDK 未安装'，真实原因被掩盖。"
        )

    def test_pinned_in_full_runtime_lock(self):
        lock = io.open(PROJECT_ROOT / "requirements-full.lock", encoding="utf-8").read()
        assert re.search(r"(?m)^mcp==", lock), (
            "requirements-full.lock 缺 mcp pin——dependency-audit 与生产安装"
            "都以全量锁为准，锁里没有则声明等于没声明。\n"
            "修复：uv pip compile --universal requirements.txt -o requirements-full.lock"
        )

    def test_ci_declarations_agree(self):
        """CI 侧两清单同样必须声明（否则薄环境里 MCP 面测试静默跳过）。"""
        ci = io.open(PROJECT_ROOT / "requirements-ci.txt", encoding="utf-8").read()
        ci_lock = io.open(PROJECT_ROOT / "requirements-ci.lock", encoding="utf-8").read()
        assert re.search(r"(?m)^\s*mcp\s*[><=!~]", ci), "requirements-ci.txt 缺 mcp 声明"
        assert re.search(r"(?m)^mcp==", ci_lock), "requirements-ci.lock 缺 mcp pin"

    def test_missing_sdk_is_not_registered_as_graceful_optional(self):
        """mcp 缺失时"降级"是掩盖故障的——不得进 KNOWN_OPTIONAL_DEPS 而无人察觉。

        ci_static_gate 的 KNOWN_OPTIONAL_DEPS 收"缺失可优雅降级"项；mcp 缺席
        是**功能全断**（连接失败 + 错误原因被替换），登记进去等于让巡检闭嘴。
        """
        gate = io.open(PROJECT_ROOT / "scripts" / "ci_static_gate.py", encoding="utf-8").read()
        table = gate.split("KNOWN_OPTIONAL_DEPS = {", 1)[1].split("}", 1)[0]
        registered = set(re.findall(r'"([a-zA-Z_0-9]+)"', table))
        assert "mcp" not in registered, (
            "mcp 被登记为可优雅降级的可选依赖——它的缺席会让全部 MCP 服务器"
            "连接失败而 last_error 只说'SDK 未安装'，属于必须显式声明的运行时依赖。"
        )


class TestProtectedGuardsUseNoExternalBinaries:
    """受保护子集里的守卫不得依赖 CI 镜像未提供的外部二进制。

    实锤（Issue #62 收口后的首次 PR CI）：`test_tool_call_breakpoints_v3.py`
    的 `test_no_callers_of_build_tools_from_skills` 调 `subprocess.run(["rg", ...])`，
    python:* 镜像没有 ripgrep → `FileNotFoundError`。这类崩溃比"断言失败"更坏：
    守卫**根本没执行**，同文件的真实断言也一起被跳过。

    规则：扫描/搜索类守卫一律走纯 Python（`Path.rglob` + `ast` / 字符串匹配）。
    """

    # 允许的外部命令：仅"当前环境断言存在"的可执行文件（用 shutil.which 跳过）。
    # 白名单的语义是「已在使用点自证可达」，不是免检通道——由
    # test_allowed_binaries_are_proven_reachable_at_every_call_site 常驻校验。
    #   git —— 版本库状态判定（入库/ignore），CI 镜像内存在。
    #   sh  —— POSIX shell。`.cnb.yml` 的 node 分派本身就把桥命令交给 sh 执行
    #          （`sh scripts/ci/run_gate_under_node.sh ...`），守卫要复现的正是
    #          平台那条调用形态，故必须以 sh 起进程；使用点自证可达后跳过。
    ALLOWED = {"git", "sh"}

    def _protected_test_files(self):
        listed = []
        for raw in io.open(
            PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt", encoding="utf-8"
        ).read().splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                listed.append(line)
        return listed

    def test_no_bare_external_command_in_subprocess(self):
        import ast

        offenders = []
        for rel in self._protected_test_files():
            path = PROJECT_ROOT / rel
            tree = ast.parse(io.open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                attr = getattr(func, "attr", None)
                if attr not in {"run", "check_output", "Popen", "call", "check_call"}:
                    continue
                if "subprocess" not in ast.dump(getattr(func, "value", ast.Constant(None))):
                    continue
                if not node.args:
                    continue
                first = node.args[0]
                # 只查字面量命令名；sys.executable / 变量不在本守卫范围
                if isinstance(first, ast.List) and first.elts:
                    head = first.elts[0]
                elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                    head = first
                else:
                    continue
                if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
                    continue
                if head.value in self.ALLOWED:
                    continue
                offenders.append(f"{rel}:{node.lineno}: 直接执行外部命令 {head.value!r}")
        assert not offenders, (
            "受保护子集里的守卫依赖外部二进制——CI 镜像没有它时不是断言失败而是 "
            "FileNotFoundError，整个守卫（含同文件其他断言）静默不跑：\n  "
            + "\n  ".join(offenders)
            + "\n修复：扫描类守卫改用纯 Python（Path.rglob / ast），"
            "或把命令加进 ALLOWED 并说明镜像内确实存在。"
        )

    @staticmethod
    def _literalCommandsIn(source, command):
        """该源码里以**字面量**直接执行 `command` 的行号（AST 口径，不吃注释/字符串）。"""
        import ast

        lines = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return lines
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) not in {
                "run", "check_output", "Popen", "call", "check_call"
            }:
                continue
            if "subprocess" not in ast.dump(getattr(node.func, "value", ast.Constant(None))):
                continue
            if not node.args:
                continue
            first = node.args[0]
            head = None
            if isinstance(first, ast.List) and first.elts:
                head = first.elts[0]
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                head = first
            if isinstance(head, ast.Constant) and head.value == command:
                lines.append(node.lineno)
        return lines

    @staticmethod
    def _provesReachability(source, command):
        """源码里是否有 `shutil.which("<command>")` 调用（AST 口径）。"""
        import ast

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "attr", None) != "which":
                continue
            if "shutil" not in ast.dump(getattr(func, "value", ast.Constant(None))):
                continue
            if node.args and isinstance(node.args[0], ast.Constant):
                if node.args[0].value == command:
                    return True
        return False

    def _missingProbes(self, sources):
        """sources: {文件名: 源码} → 未自证可达的白名单命令使用点清单。"""
        problems = []
        for rel, source in sources.items():
            for command in sorted(self.ALLOWED):
                if self._literalCommandsIn(source, command) and not self._provesReachability(
                        source, command):
                    problems.append(f"{rel}: 直接执行 {command!r} 却无 shutil.which 探测")
        return problems

    def test_allowed_binaries_are_proven_reachable_at_every_call_site(self):
        """白名单不是免检通道：放行的命令必须**在每个使用点**自证可达。

        上一条判据的 `ALLOWED` 语义是「仅当前环境断言存在的外部命令」——
        断言存在的方式就是 `shutil.which(...)` + 缺席即显式 skip。
        本条把这个契约钉成判据：命令一旦进了 `ALLOWED`，受保护子集里任何
        直接执行它的文件都必须在**同一文件内**带上该命令的 which 调用。

        为何要单独钉（实锤）：构建 `cnb-abg-1k34ioaot` 的 unit-tests 双跑红在
        `test_no_bare_external_command_in_subprocess`——上一轮新入子集的守卫
        `tests/unit/ci/test_npc_script_interpreter_reachability.py` 写了字面量
        `subprocess.run(["sh", ...])`。白名单收 `git` 的同时，`git` 的四个使用点
        从不自证可达：白名单于是成了「把已知坏味道挪进去」，换镜像即复发。

        可证伪：删掉任一使用点的 `shutil.which("<命令>")` → 红。
        """
        sources = {
            rel: io.open(PROJECT_ROOT / rel, encoding="utf-8").read()
            for rel in self._protected_test_files()
        }
        problems = self._missingProbes(sources)
        assert not problems, (
            "白名单命令在受保护子集的使用点未自证可达——`ALLOWED` 的语义是"
            "「当前环境断言存在」，不探测就执行等于把 FileNotFoundError 留在原处"
            "（守卫静默不跑）：\n  " + "\n  ".join(problems)
            + "\n修复：在使用点加 `shutil.which(\"<命令>\")`，缺席即 pytest.skip。"
        )

    def test_reachabilityContractCriterionIsNotVacuous(self):
        """反向控制：判据真能咬住缺口，且不误伤已自证的写法（合成输入，不拿仓库现状当输入）。"""
        offender = 'import subprocess\nsubprocess.run(["git", "ls-files"])\n'
        proven = (
            'import shutil\nimport subprocess\n'
            'if shutil.which("git"):\n'
            '    subprocess.run(["git", "ls-files"])\n'
        )
        assert self._missingProbes({"synthetic_offender.py": offender}) == [
            "synthetic_offender.py: 直接执行 'git' 却无 shutil.which 探测"
        ], "缺口写法未被咬住 —— 判据空转"
        assert self._missingProbes({"synthetic_proven.py": proven}) == [], (
            "已自证的写法被误判 —— 判据过严，正常修复也会被拦"
        )

    def test_no_shell_out_to_ripgrep(self):
        """`rg` 是本次实锤的缺席二进制——全 tests/ 都不该硬依赖它。

        与上一条同口径：只看 AST 里真实的 `subprocess.[...](["rg", ...])`
        调用，不匹配文档/注释里的文字（否则守卫自己就成了违规样本）。
        """
        import ast

        offenders = []
        # 文本预筛：违规形态必然含 subprocess 调用与 "rg" 字面量，其余文件不解析；
        # 解析走 tests/ast_scan.py 的共享预算（Issue #148：全仓 ast.parse 单跑 4s，
        # 与受保护子集其余 170 个文件共享机器时撞 30s 默认墙钟）。
        for path, node in ast_scan.nodeScan(
                PROJECT_ROOT / "tests",
                hints=("subprocess", '"rg"', "'rg'")):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "attr", None) not in {
                "run", "check_output", "Popen", "call", "check_call"
            }:
                continue
            if "subprocess" not in ast.dump(getattr(func, "value", ast.Constant(None))):
                continue
            if not node.args:
                continue
            first = node.args[0]
            head = None
            if isinstance(first, ast.List) and first.elts:
                head = first.elts[0]
            elif isinstance(first, ast.Constant):
                head = first
            if isinstance(head, ast.Constant) and head.value == "rg":
                offenders.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
        assert not offenders, (
            "测试硬依赖 ripgrep（python:* CI 镜像里没有 rg，会 FileNotFoundError）：\n  "
            + "\n  ".join(offenders)
            + "\n修复：改用纯 Python 扫描（Path.rglob + ast / 字符串匹配）。"
        )


class TestCiTestRunnerAndFixtureDepsAreReal:
    """受保护子集"跑起来"的两个前提：pytest 版本 + conftest fixture 依赖。

    这两条都是"CI 报错与代码无关"的事故，且都在**同一个 job**里同时发作，
    因此合在一个类里钉住。

    4. **pytest 必须在安全下限之上（>=9.0.3），收集竞争的兜底不在版本号上** ——
       这里的口径在 2026-09-21 被 CVE-2025-71176 推翻过一次，记录完整推导：
         - 原先的"锁 <9"是为了绕开收集缓存按节点对象身份去重导致的
           `fixture 'xxx' not found`（收集竞争机制与最小触发集见
           `tests/unit/test_pytest_runner_guards.py` 的模块 docstring）；
         - 但 `<9` 全部落在 CVE-2025-71176 / PYSEC-2026-1845（fixed 9.0.3，
           扫全版本区间）里，`dependency-audit`（pip-audit）对 8.4.2 直接报红
           —— 两条约束撞在同一条依赖上，不能再拿"回避版本"换绿。
         - 正面修法是 `tests/unit/evolution/rsi/conftest.py`：在子包自己的
           conftest 里按名重导出父包 fixture，让可见性判据不再跨 collector
           身份求值。回归守卫用最小触发集实跑钉住（不靠版本回避）。
       本类只钉"声明与锁都在安全下限之上"。

    5. **受保护子集里"真跑渲染路径"的依赖必须在 CI 清单声明** ——
       `tests/unit/document/test_document_pdf.py` 与 `tests/unit/tools/test_write_pdf.py`
       断言 `"error" not in result`（即必须真出件），`neurova/document_pdf.py`
       缺 reportlab 即 `RenderUnavailable` → 26 个失败。只在 requirements.txt
       声明、不在 CI 清单声明，CI 薄环境就永远红。
    """

    def test_pytest_declared_at_or_above_security_floor(self):
        """requirements-ci.txt 的 pytest 下限必须 >=9.0.3（CVE-2025-71176）。"""
        text = io.open(PROJECT_ROOT / "requirements-ci.txt", encoding="utf-8").read()
        decls = [
            l.strip() for l in text.splitlines()
            if re.match(r"^\s*pytest\s*[><=!~]", l.strip())
        ]
        assert decls, "requirements-ci.txt 缺 pytest 声明"
        assert any(">=9.0.3" in d.replace(" ", "") for d in decls), (
            "requirements-ci.txt 未把 pytest 下限钉在 >=9.0.3。低于 9.0.3 落在\n"
            "CVE-2025-71176 / PYSEC-2026-1845（GHSA-6w46-j5rx-g56g，扫全版本区间）\n"
            "内，dependency-audit（pip-audit）必红——2026-09-21 把 8.4.2 锁进 CI 后\n"
            "实测 2 条漏洞。收集缓存的身份去重问题改由\n"
            "tests/unit/evolution/rsi/conftest.py 兜底，不再用版本回避。当前声明："
            f"{decls}"
        )
        assert not any("<9" in d.replace(" ", "") for d in decls), (
            "requirements-ci.txt 仍把 pytest 锁在 <9——该区间内有 CVE-2025-71176，"
            f"dependency-audit 必红。当前声明：{decls}"
        )

    def test_ci_lock_pins_pytest_at_or_above_security_floor(self):
        """锁文件必须与声明一致（CI 装的是锁，不是声明）。"""
        lock = io.open(PROJECT_ROOT / "requirements-ci.lock", encoding="utf-8").read()
        m = re.search(r"(?m)^pytest==(\d+)\.(\d+)\.(\d+)", lock)
        assert m, "requirements-ci.lock 缺 pytest pin"
        version = tuple(int(g) for g in m.groups())
        assert version >= (9, 0, 3), (
            f"requirements-ci.lock 把 pytest 锁在 {m.group(0)}——CI 装的是锁文件，"
            "低于 9.0.3 即落在 CVE-2025-71176 区间，dependency-audit 必红。\n"
            "修复：uv pip compile --universal requirements-ci.txt -o requirements-ci.lock"
        )

    def test_document_pdf_render_path_deps_declared_in_ci(self):
        """受保护子集里真跑 PDF 渲染的套件依赖 reportlab，CI 清单必须声明。"""
        ci = io.open(PROJECT_ROOT / "requirements-ci.txt", encoding="utf-8").read()
        assert re.search(r"(?m)^\s*reportlab\s*[><=!~]", ci), (
            "requirements-ci.txt 缺 reportlab 声明——tests/unit/document/test_document_pdf.py\n"
            "与 tests/unit/tools/test_write_pdf.py 在受保护子集里走真实渲染路径\n"
            "（断言 'error' not in result，不做 try 降级），缺席即 26 个失败。"
        )
        lock = io.open(PROJECT_ROOT / "requirements-ci.lock", encoding="utf-8").read()
        assert re.search(r"(?m)^reportlab==", lock), (
            "requirements-ci.lock 缺 reportlab pin——CI 装的是锁文件。\n"
            "修复：uv pip compile --universal requirements-ci.txt -o requirements-ci.lock"
        )

    def test_protected_subset_keeps_fixture_consumers(self):
        """本守卫自身的靶点必须留在受保护子集里，否则回归无人看。

        没有这一条，任何一次"清理"都能把上面两个套件移出子集，
        守卫退化成永远通过的空壳。
        """
        listed = io.open(
            PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt", encoding="utf-8"
        ).read()
        for rel in (
            "tests/unit/evolution/rsi/test_parameter_source_of_truth.py",
            "tests/unit/evolution/experience/test_pattern_lifecycle.py",
            "tests/unit/document/test_document_pdf.py",
            "tests/unit/tools/test_write_pdf.py",
            # 收集竞争兜底靶点：rsi 子包 conftest 重导出父包 fixture，
            # 少了本条目则守卫退化成空壳（见 test_pytest_runner_guards.py）。
            "tests/unit/test_pytest_runner_guards.py",
        ):
            assert rel in listed, (
                f"{rel} 不在受保护子集——它是 pytest<9 / reportlab 两条回归的靶点，"
                "移出后本守卫无法发现复发。"
            )


class TestProtectedSubsetEntriesAreTracked:
    """受保护子集的每个条目必须**真实存在且被 git 跟踪**。

    根因（2026-09-22 的 CI 事故，Issue #109 的 PR #117）：新增守卫
    `tests/unit/desktop/test_rust_vendor_patch_guard.py` 被 `.gitignore` 的
    临时脚本通配 `*_patch*.py` 吞掉，于是：

    - 本机工作区里文件在，单跑 pytest 全绿；
    - 提交后仓库里**根本没有该文件**（未跟踪），CI 的 unit-tests 拿到
      `ERROR: file or directory not found`，收集 0 项、退出码 4；
    - 更隐蔽的一层：`scripts/ci/protected_tests.txt` 里写着它——清单声称
      「这个守卫在跑」，而它从未被跑过。守卫缺席比守卫变红更危险。

    本类钉两件事：清单条目的存在性与跟踪状态；以及测试根不得再被
    「临时脚本通配」按名字吞掉（否则同类事故会以别的文件名复发）。
    """

    # 会被名单里那批通配命中的形态（见 .gitignore 的「调试和临时文件」「临时脚本」两节）。
    # 这些名字在仓库根/scripts 下是临时脚本的合理排除对象，但在唯一测试根下
    # 它们就是正当的测试文件名，不得被误吞。
    CANARY_NAMES = (
        "tests/unit/desktop/test_rust_vendor_patch_guard.py",
        "tests/unit/_probe_patch_notes.py",
        "tests/unit/x/test_debug_flow.py",
        "tests/unit/x/check_contract.py",
        "tests/unit/x/verify_binding.py",
        "tests/unit/x/run_pipeline.py",
    )

    @staticmethod
    def _protected_entries() -> list:
        raw = io.open(
            PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt", encoding="utf-8"
        ).read()
        return [
            line.split("#", 1)[0].strip()
            for line in raw.splitlines()
            if line.split("#", 1)[0].strip()
        ]

    @staticmethod
    def _git(*args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_git_available_for_tracking_checks(self):
        """反向控制：没有 git 时本类会静默变成空壳，必须显式跳过而不是假绿。"""
        if not shutil.which("git") or not (PROJECT_ROOT / ".git").exists():
            pytest.skip("非 git 工作区 / 无 git：跟踪状态无从判定")

    def test_every_protected_entry_exists_on_disk(self):
        """清单指向不存在的文件 = CI 必红（pytest 退出码 4），且断言无从执行。"""
        if not shutil.which("git") or not (PROJECT_ROOT / ".git").exists():
            pytest.skip("非 git 工作区 / 无 git")
        missing = [
            rel for rel in self._protected_entries()
            if not (PROJECT_ROOT / rel).exists()
        ]
        assert not missing, (
            "受保护子集指向不存在的文件——unit-tests 流水线会以 "
            "`ERROR: file or directory not found` 退出 4：\n  " + "\n  ".join(missing)
        )

    def test_every_protected_entry_is_tracked_by_git(self):
        """清单条目必须在库里被跟踪：本机有文件 ≠ 仓库里有文件。

        可证伪路径：把任一清单条目的文件从索引里摘掉（`git rm --cached <path>`）
        → 转红。本次事故正是"本机绿、仓库里没有"这一形态。
        """
        if not shutil.which("git") or not (PROJECT_ROOT / ".git").exists():
            pytest.skip("非 git 工作区 / 无 git")
        untracked = []
        for rel in self._protected_entries():
            proc = self._git("ls-files", "--error-unmatch", "--", rel)
            if proc.returncode != 0:
                untracked.append(rel)
        assert not untracked, (
            "受保护子集里有条目未被 git 跟踪——本机跑得通、克隆/CI 上文件不存在，"
            "门禁声称跑过而从未跑过（比变红更危险）：\n  " + "\n  ".join(untracked)
            + "\n修复：确认该文件未被 .gitignore 吞掉（测试根见下一条），"
            "再 `git add` 入库。"
        )

    @pytest.mark.parametrize("rel", CANARY_NAMES)
    def test_test_root_names_are_not_swallowed_by_adhoc_globs(self, rel):
        """测试根下的正当文件名不得被「临时脚本通配」吞掉。

        可证伪路径：删掉 `.gitignore` 的测试根豁免 → 前两条转红。
        """
        if not shutil.which("git") or not (PROJECT_ROOT / ".git").exists():
            pytest.skip("非 git 工作区 / 无 git")
        proc = self._git("check-ignore", "-q", "--", rel)
        assert proc.returncode != 0, (
            f"{rel} 仍被 .gitignore 忽略——它会被静默排除在提交之外，"
            "本机绿而 CI 上文件不存在。\n"
            "修复：在 .gitignore 里为唯一测试根加豁免（`!tests/**`），"
            "并单独重新忽略测试根下的缓存/产物。"
        )

    @pytest.mark.parametrize(
        "rel",
        (
            "tests/__pycache__/x.pyc",
            "tests/unit/x/__pycache__/y.pyc",
            "tests/unit/x/.pytest_cache/v/cache/lastfailed",
            "tests/unit/x/htmlcov/index.html",
        ),
    )
    def test_test_root_caches_stay_ignored(self, rel):
        """反向控制：豁免测试根**不得**顺手把缓存/产物放进来。

        可证伪路径：把 `.gitignore` 的测试根豁免写成一条无限定的
        `!tests/**` 而不同时重新忽略缓存 → 转红。
        """
        if not shutil.which("git") or not (PROJECT_ROOT / ".git").exists():
            pytest.skip("非 git 工作区 / 无 git")
        proc = self._git("check-ignore", "-q", "--", rel)
        assert proc.returncode == 0, (
            f"{rel} 不再被忽略——测试根豁免把跑测产物也放进了仓库。\n"
            "修复：豁免测试根后，单独重新忽略 __pycache__ / .pytest_cache / htmlcov。"
        )

    def test_guard_itself_is_in_protected_subset(self):
        """本守卫必须在受保护子集里，否则它的断言在 CI 上无人执行。"""
        rel = "tests/unit/test_dev_path_and_runtime_dep_guards.py"
        assert rel in self._protected_entries(), (
            f"{rel} 不在受保护子集——本类锁的『清单条目必须存在且被跟踪』"
            "在 CI 上不会被执行，同类事故会无声复发。"
        )
