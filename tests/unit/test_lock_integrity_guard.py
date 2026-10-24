# -*- coding: utf-8 -*-
"""依赖锁完整性守卫（Issue #56 收口：锁文件漂移必须被门禁抓住）。

背景（Issue #56 实跑发现，均为"锁与声明各走各的"导致的真事故）：

1. **声明有、锁里没有** —— `prometheus_client>=0.20` 在 requirements-ci.txt，
   但 requirements-ci.lock 一条都没有 → `uv pip install -r requirements-ci.lock`
   （ci.yml unit-tests job 正是这么装的）装不上它，而 neurova/core/metrics.py:17
   是裸 import。E2E job 曾用显式 `pip install ... prometheus_client` 打补丁绕开，
   等于承认缺口却没修锁。
2. **锁有、声明没有** —— `litellm==1.98.0` 在锁里标 `# via -r requirements-ci.txt`，
   但 txt 已删 litellm（改 openai 3.x 原生通道）→ 锁按旧版 txt 编译，txt 改了没重编。
3. **锁违反自己声明的约束** —— txt 写 `openai>=3.9.0`，锁里 `openai==2.54.0`。

本守卫锁死三条不变量（对 requirements-ci.txt↔.lock 与 requirements.txt↔full.lock 都跑）：

- **无缺失 pin**：txt 里每个顶层包都必须在锁里有 `==` pin（否则 uv 装锁即缺包）
- **无幽灵 root**：锁里标 `# via -r <txt>` 的包必须真在该 txt 里（否则是旧 txt 编译残留）
- **无孤儿包**：锁里每个 pin 要么是 root，要么可经 `# via` 链从 root 可达
  （不可达 = 依赖树里已消失的残留，会白装+白扫）

契约：改任一 txt 必须同步重编对应锁 —— `uv pip compile --universal <txt> -o <lock>`。
"""

import io
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# (声明 txt, 锁文件, 锁头记录的编译命令)
LOCK_PAIRS = (
    ("requirements-ci.txt", "requirements-ci.lock", "uv pip compile --universal requirements-ci.txt"),
    ("requirements.txt", "requirements-full.lock", "uv pip compile --universal requirements.txt"),
)


def _read(*parts: str) -> str:
    return io.open(PROJECT_ROOT.joinpath(*parts), encoding="utf-8").read()


def _norm(name: str) -> str:
    """包名规范化：去 extras、小写、连字符↔下划线统一为连字符（PEP 503 等价形）。"""
    name = re.sub(r"\[.*?\]", "", name)
    return name.strip().lower().replace("_", "-")


def declared_top_packages(txt_name: str) -> set[str]:
    """txt 声明的顶层包名集合（忽略注释与空行）。"""
    out = set()
    for raw in _read(txt_name).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        out.add(_norm(re.split(r"[>=<!;~]", line)[0]))
    return out


def parse_lock(lock_name: str) -> dict[str, dict]:
    """解析 uv 锁：{规范化包名: {version, parents:[规范化名], roots:[txt 文件名]}}。

    uv 的 `# via` 段落有两种形态（缩进不同、可折行）：
        # via -r requirements-ci.txt          ← root（来自声明文件）
        # via fastapi                          ← 传递依赖父节点
        # via                                ← 多父节点折行
        #   anthropic
        #   mcp
    """
    entries: dict[str, dict] = {}
    cur: str | None = None
    collecting = False
    for raw in _read(lock_name).splitlines():
        line = raw.rstrip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", line)
        if m:
            cur = _norm(m.group(1))
            entries[cur] = {"version": m.group(2), "parents": [], "roots": []}
            collecting = False
            continue
        if cur is None:
            continue
        mv = re.match(r"^\s+#\s+via\s*(.*)$", line)
        if mv:
            collecting = True
            _feed(entries[cur], mv.group(1))
            continue
        if collecting:
            mc = re.match(r"^\s+#\s+(\S.*?)\s*$", line)
            if mc:
                _feed(entries[cur], mc.group(1))
                continue
            collecting = False
    return entries


def _feed(entry: dict, value: str) -> None:
    value = value.strip()
    if not value or value.lower() == "via":
        return
    if value.startswith("-r "):
        entry["roots"].append(value[3:].strip())
        return
    entry["parents"].append(_norm(value))


def reachable(entries: dict[str, dict]) -> set[str]:
    """从 root 出发沿 `# via` 反向边可达的包名集合。"""
    reach = {name for name, e in entries.items() if e["roots"]}
    changed = True
    while changed:
        changed = False
        for name, e in entries.items():
            if name in reach:
                continue
            if any(parent in reach for parent in e["parents"]):
                reach.add(name)
                changed = True
    return reach


@pytest.fixture(scope="module")
def ci_lock():
    return parse_lock("requirements-ci.lock")


@pytest.fixture(scope="module")
def full_lock():
    return parse_lock("requirements-full.lock")


class TestLockIntegrity:
    @pytest.mark.parametrize("txt,lock,cmd", LOCK_PAIRS)
    def test_declared_packages_are_pinned(self, txt, lock, cmd):
        """声明有、锁里没有 → uv 装锁即缺包（prometheus_client 事故形态）。"""
        declared = declared_top_packages(txt)
        pinned = set(parse_lock(lock))
        missing = sorted(declared - pinned)
        assert not missing, (
            f"{lock} 缺 {txt} 的声明 pin: {missing}\n"
            f"CI 用 `uv pip install -r {lock}` 装依赖，缺 pin 的包不会被装上，"
            "裸 import 即崩。修复：\n"
            f"  {cmd} -o {lock}"
        )

    @pytest.mark.parametrize("txt,lock,cmd", LOCK_PAIRS)
    def test_no_ghost_roots(self, txt, lock, cmd):
        """锁里标 `# via -r <txt>` 却已不在该 txt → 锁按旧版 txt 编译的残留。"""
        declared = declared_top_packages(txt)
        ghosts = sorted(
            name for name, e in parse_lock(lock).items()
            if e["roots"] and name not in declared
        )
        assert not ghosts, (
            f"{lock} 存在幽灵 root（标 `# via -r {txt}` 但 {txt} 已无此声明）: {ghosts}\n"
            "锁是按旧版 txt 编译的（改 txt 没重编），会带上已摘除的依赖。修复：\n"
            f"  {cmd} -o {lock}"
        )

    @pytest.mark.parametrize("txt,lock,cmd", LOCK_PAIRS)
    def test_no_orphan_packages(self, lock, txt, cmd):
        """锁里不可从任何 root 到达的 pin = 依赖树残留，白装且白扫漏洞。"""
        entries = parse_lock(lock)
        reach = reachable(entries)
        orphans = sorted(set(entries) - reach)
        assert not orphans, (
            f"{lock} 存在孤儿包（不可经 `# via` 链从 root 到达）: {orphans}\n"
            "说明锁与当前依赖树不同源（txt 改过而锁未重编）。修复：\n"
            f"  {cmd} -o {lock}"
        )


class TestKnownDriftsStayFixed:
    """Issue #56 三处实跑抓到的漂移，逐个钉死防复发。"""

    def test_prometheus_client_pinned_in_ci_lock(self, ci_lock):
        """#56-1：prometheus_client 此前在 txt 有、锁里零条 → unit-tests job 缺包。"""
        assert "prometheus-client" in ci_lock, (
            "requirements-ci.lock 缺 prometheus_client pin——"
            "unit-tests job（uv 装锁）会缺 neurova/core/metrics.py 的裸 import 依赖。\n"
            "修复：uv pip compile --universal requirements-ci.txt -o requirements-ci.lock"
        )

    def test_litellm_not_in_ci_lock(self, ci_lock):
        """#56-2：litellm 已从 txt 摘除（改 openai 3.x 原生通道），锁不得残留。"""
        assert "litellm" not in ci_lock, (
            "requirements-ci.lock 残留 litellm（txt 已摘除，锁按旧 txt 编译）——"
            "会连带带入 boto3/botocore/jinja2/tokenizers 等一整套无用依赖。\n"
            "修复：uv pip compile --universal requirements-ci.txt -o requirements-ci.lock"
        )

    def test_openai_lock_satisfies_declared_floor(self, ci_lock):
        """#56-3：锁里 openai 必须满足 txt 声明的下界（`>=3.9.0` vs 锁 2.54.0）。"""
        floors: dict[str, tuple[int, ...]] = {}
        for raw in _read("requirements-ci.txt").splitlines():
            line = raw.split("#", 1)[0].strip()
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*>=\s*([0-9][0-9.]*)", line)
            if m:
                floors[_norm(m.group(1))] = tuple(int(p) for p in m.group(2).split(".") if p.isdigit())
        violations = []
        for name, floor in floors.items():
            entry = ci_lock.get(name)
            if entry is None:
                continue
            actual = tuple(int(p) for p in re.split(r"[.\-+]", entry["version"]) if p.isdigit())
            if actual < floor:
                violations.append(f"{name}: 锁 {entry['version']} < 声明下界 {'.'.join(map(str, floor))}")
        assert not violations, (
            "锁违反 txt 自己声明的版本下界:\n  " + "\n  ".join(violations) +
            "\n修复：uv pip compile --universal requirements-ci.txt -o requirements-ci.lock"
        )

    def test_litellm_fully_removed_from_declarations(self):
        """litellm 摘除应三清单一致（无声明残留）。"""
        for name in ("requirements.txt", "requirements-ci.txt", "requirements-ci.lock", "requirements-full.lock"):
            content = _read(name)
            leaked = [
                line.strip() for line in content.splitlines()
                if re.match(r"^\s*litellm\s*(==|>=|<=|~=|>|<|\[)", line)
            ]
            assert not leaked, f"{name} 仍声明 litellm: {leaked}（应已由 openai 原生通道替代）"


class TestAuditBatchFloors:
    """2026-10 公告批的修复下界——锁不许回退到有公告的版本。

    为什么要单列一类：上面 `test_openai_lock_satisfies_declared_floor` 只核
    "锁 ≥ txt 自述下界"，而下界本身可能是旧的（`aiohttp>=3.9.0` 从 2023 年起
    没动过，锁停在 3.14.3 仍是"合规"）。公告晚于下界落地时，这条链就失效：
    dependency-audit 红一次、人改一次锁、下次漂移再红一次。故把**实际修掉的
    那批公告**逐条登记成机器可验的下界，与
    `tests/unit/tools/test_npx_runtime_pinning.py::TestNoKnownVulnerableRuntimePackages`
    同一口径（OSV 实扫发现 → 在此追加一条 → 回退即红）。

    下界来源（api.osv.dev 逐版本实查，2026-10-23）：
      aiohttp 3.14.3 → 8 条公告（GHSA-2g87-pp6c-29x5 等），3.14.4 起清零，落 3.14.5
      certifi 2026.7.22 → GHSA-6q48-6c7w-9gw2（emSign 中间 CA），2026.10.19 起清零，落 2026.10.23
      opentelemetry-api 1.44.0 → GHSA-xcq7-p3pf-p88h（tracestate 无界解析），1.45.1 起清零
      pillow 12.3.0 → 39 条（含 libtiff 编码器内存泄露 GHSA-xvh5-g6gv-559v），13.0.0 起清零
      pypdf 6.19.0 → 8 条（GHSA-39mj-jf6j-2qj3 等），6.21.1 起清零，落 6.21.2
      filelock 4.0.0 → 3 条（GHSA-v4x8-3wr5-3wq8 等 Windows 软锁/副作用文件），4.2.1 起清零，落 4.2.4
      setuptools 84.0.0 → GHSA-xmj3-9gf7-h52w（namespace_packages.txt 路径逃逸），84.1.0 起清零，落 84.2.1
    """

    _FLOORS = {
        "aiohttp": "3.14.4",
        "certifi": "2026.10.19",
        "opentelemetry-api": "1.45.1",
        "pillow": "13.0.0",
        "pypdf": "6.21.1",
        "filelock": "4.2.1",
        "setuptools": "84.1.0",
    }

    @staticmethod
    def _version_key(version: str) -> tuple:
        """版本比较键：按 `.` 与 `-` 切段，数字段恒排在非数字段之前。"""
        return tuple(
            (0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in version.replace("-", ".").split(".")
        )

    @pytest.mark.parametrize("lock", ["requirements-ci.lock", "requirements-full.lock"])
    def test_locked_versions_meet_audit_floors(self, lock):
        entries = parse_lock(lock)
        problems = []
        for name, floor in self._FLOORS.items():
            entry = entries.get(name)
            if entry is None:
                # 承载者被整体摘除（依赖被上游换掉）也是合格形态，不报红。
                continue
            if self._version_key(entry["version"]) < self._version_key(floor):
                problems.append(f"{name}: 锁 {entry['version']} < 已修公告的修复下界 {floor}")
        assert not problems, (
            f"{lock} 里出现已修公告的未修版本（会直接红 dependency-audit）:\n  "
            + "\n  ".join(problems)
            + "\n修复：在对应 txt 抬下界后重编锁（uv pip compile --universal <txt> -o <lock>）。"
        )

    def test_ci_lock_declares_pillow_itself(self):
        """Pillow 必须自有声明行，不能只靠 reportlab 传递进来。

        传递依赖的版本由父包下界决定（`reportlab>=4.0` → `pillow>=9.0.0`），
        锁解析停在哪个版本全凭上游惯性；本仓在 2026-10 那批公告里付出的代价就是
        "编辑不了下界、只能改锁"——声明面缺失使这次修复无法被 `uv pip compile` 复算。
        """
        assert "Pillow" in _read("requirements-ci.txt"), (
            "requirements-ci.txt 未声明 Pillow——CI 锁里的 pillow 将重新退化为"
            "reportlab 的传递依赖，修复下界失去声明面（无法用重编锁复现）。"
        )


class TestFullRuntimeLockExists:
    """#56 覆盖面缺口：生产全量依赖必须有锁且被审计（否则永远无人扫）。"""

    def test_full_lock_tracks_declared_runtime_set(self):
        full = parse_lock("requirements-full.lock")
        declared = declared_top_packages("requirements.txt")
        roots = {name for name, e in full.items() if e["roots"]}
        missing_roots = sorted(declared - roots)
        assert not missing_roots, (
            f"requirements-full.lock 缺 root 标记（不是按 requirements.txt 编译的）: {missing_roots}"
        )

    def test_heavy_runtime_deps_covered(self):
        """#56 点名的高风险运行时依赖必须进全量锁（此前全无覆盖）。"""
        full = parse_lock("requirements-full.lock")
        for pkg in ("curl-cffi", "onnxruntime", "transformers", "playwright", "paramiko", "pycryptodome"):
            assert pkg in full, (
                f"requirements-full.lock 缺 {pkg}——生产运行时依赖没进审计覆盖面"
            )

    @pytest.mark.parametrize("side", ["github", "cnb"])
    def test_ci_audits_full_lock(self, side):
        """CI 两侧都必须扫全量锁（只扫 CI 精简锁 = 覆盖面缺口）。"""
        path = ".github/workflows/ci.yml" if side == "github" else ".cnb.yml"
        assert "requirements-full.lock" in _read(path), (
            f"{path} 的 dependency-audit 未扫 requirements-full.lock——"
            "生产全量依赖（curl_cffi/onnxruntime/transformers/playwright/paramiko）"
            "又回到无人审计状态。"
        )

    @pytest.mark.parametrize("side", ["github", "cnb"])
    def test_frontend_audits_npm(self, side):
        """前端漏洞此前完全无人看（frontend job 只跑 vue-tsc + vitest）。"""
        path = ".github/workflows/ci.yml" if side == "github" else ".cnb.yml"
        assert "npm audit --audit-level=high" in _read(path), (
            f"{path} 的 frontend 门禁未跑 npm audit —— 前端依赖漏洞无人看。"
        )
