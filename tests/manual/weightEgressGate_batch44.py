# -*- coding: utf-8 -*-
"""批 44 活体自证：跑测层「真权重出网」门与预热泄漏，按 A/B 那个形状取终局读数。

为什么必须这么跑：这个缺陷的破坏方式不是「某格红」，而是**整场拿不到汇总行**——
`pytest-timeout` 的 thread 法一到 30s 就把进程打死。所以自证只看终局读数
（有没有汇总行、有没有落权重字节、缺件侧是 skip 还是 fail），单格绿不算证据。

读数：
[1] 干净仓外 worktree + 本批测试层跑 `tests/unit/tts` ⇒ 有汇总行、零 `.data` 落盘、
    `~/.cache/modelscope` 字节数不变、缺件那几格 SKIPPED 且点名原因、无 FAILED/ERROR。
[2] 同一棵 worktree 上的假前置对照：目录存在（5 只 .onnx 入 git）而为权重不齐
    （两份 .data 未跟踪）⇒ 旧 `skipif(目录存在)` 会放行，新门 skip。
[3] 本树权重齐 ⇒ real_model 那 7 格真跑真过，不是被门顺手跳掉。
[4] 泄漏格 `test_ttl_release_switches_to_light_engine` 在干净侧的单格耗时读数。
[5] 门的登记表与 AST 扫出的下载点逐处相等。
[6] 直接敲门的三处：点名拒绝、零字节落盘、门记了账。
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv/Scripts/python.exe")
BATCH_FILES = (
    "tests/conftest.py",
    "pyproject.toml",
    "tests/unit/tts/conftest.py",
    "tests/unit/tts/_fakeEngines.py",
    "tests/unit/tts/test_tts_lazy_release.py",
    "tests/unit/tts/test_tts_engine_kwargs_contract.py",
    "tests/unit/tts/test_unitTierNeverPaysForRealWeights.py",
    "tests/unit/test_weightEgressGateRefusesBeforeBytes.py",
)
MOSS_DIR = "models/tts/moss-nano"
SUMMARY_RE = re.compile(r"=+ [^=\n]*(passed|failed|error)[^=\n]*=+")

READINGS = []


def check(title, ok, detail=""):
    READINGS.append((bool(ok), title))
    print(("[OK]   " if ok else "[FAIL] ") + title + (f" | {detail}" if detail else ""))


def _env(root):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def runPytest(root, *args):
    r = subprocess.run([PY, "-m", "pytest", *args], cwd=str(root), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=_env(root),
                       timeout=900)
    return r.stdout + r.stderr


def _cacheBytes():
    root = Path.home() / ".cache" / "modelscope"
    if not root.exists():
        return 0
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def _weightBytes(root):
    d = Path(root) / MOSS_DIR
    return sorted(p.name for p in d.glob("*.data")) if d.is_dir() else []


def _durationOf(out, nodeName):
    m = re.search(r"([\d.]+)s call\s+\S*::" + re.escape(nodeName), out)
    return float(m.group(1)) if m else None


def _isModelAvailable(root):
    code = ("from neurova.tts.model_downloader import ModelDownloader;"
            "print(ModelDownloader(base_dir='.').is_model_available('moss-tts-nano'))")
    r = subprocess.run([PY, "-c", code], cwd=str(root), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=_env(root))
    return r.stdout.strip() == "True"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"repo={REPO}")

    wt = Path(tempfile.mkdtemp(prefix="b44-live-")).resolve()
    add = subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), "HEAD"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("[1a] 干净仓外 worktree 建得起", add.returncode == 0, add.stderr.strip()[:120])
    try:
        for rel in BATCH_FILES:
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((REPO / rel).read_bytes())

        cacheBefore = _cacheBytes()
        out = runPytest(wt, "-q", "-p", "no:cacheprovider", "--no-header", "-rs", "tests/unit/tts")
        summ = SUMMARY_RE.search(out)
        check("[1b] 整场产出汇总行（没被打死）", bool(summ), summ.group(0)[:150] if summ else out[-200:])
        check("[1c] 全程零权重落盘、modelscope 缓存字节不变",
              _weightBytes(wt) == [] and _cacheBytes() == cacheBefore,
              f"worktree .data={_weightBytes(wt)} 缓存字节 {cacheBefore}→{_cacheBytes()}")
        skipLines = re.findall(r"SKIPPED.*真权重不齐", out)
        skipped = re.search(r"\b(\d+) skipped", out)
        check("[1d] 缺件侧是 SKIPPED 且点名「真权重不齐」",
              len(skipLines) >= 1 and skipped is not None,
              f"点名行数={len(skipLines)} 汇总 skip={skipped.group(1) if skipped else '无'}")
        check("[1e] 该侧无 FAILED/ERROR", not re.search(r"^(FAILED|ERROR)\s", out, re.M))

        dirExists = (wt / MOSS_DIR).is_dir()
        available = _isModelAvailable(wt)
        check("[2] 旧前置「目录存在」为真而单源完整性谓词为假 ⇒ 旧 skipif 放行、新门 skip",
              dirExists and not available, f"目录存在={dirExists} is_model_available={available}")

        # --durations=N -vv：pytest 默认把 <0.005s 的那一相藏起来，正是要取「call 归零」这个读数
        out3 = runPytest(wt, "-q", "-p", "no:cacheprovider", "--no-header",
                         "--durations=10", "-vv",
                         "-k", "test_ttl_release_switches_to_light_engine",
                         "tests/unit/tts/test_tts_lazy_release.py")
        leak = _durationOf(out3, "test_ttl_release_switches_to_light_engine")
        check("[4] 泄漏格不再载真权重（单格 < 5s，改动前实测 31s/19.32s）",
              leak is not None and leak < 5.0, f"实测 {leak}s")
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

    out4 = runPytest(REPO, "-q", "-p", "no:cacheprovider", "--no-header", "-rs",
                     "tests/unit/tts/test_tts_engine_kwargs_contract.py")
    passed = re.search(r"\b(\d+) passed", out4)
    nSkip = len(re.findall(r"^SKIPPED", out4, re.M))
    check("[3] 本树权重齐 ⇒ real_model 那 7 格真跑真过（门没顺手跳掉契约）",
          nSkip == 0 and bool(passed),
          f"passed={passed.group(1) if passed else '无'} skipped={nSkip}")

    sys.path.insert(0, str(REPO))
    import importlib

    conf = importlib.import_module("tests.conftest")
    from tests.unit.test_weightEgressGateRefusesBeforeBytes import _scanEgressCallSites

    gate = conf._weightEgressGate
    found = _scanEgressCallSites()
    check("[5] 门的登记表与 AST 扫出的下载点逐处相等",
          set(gate.sites) == found,
          f"登记表={sorted(a for _m, a in gate.sites)} 扫出={sorted(a for _m, a in found)}")

    refused, wrote = 0, []
    tripsBefore = len(gate.trips)
    with tempfile.TemporaryDirectory() as td:
        for moduleName, attr in gate.sites:
            mod = importlib.import_module(moduleName)
            # 按夹具那个动作把拒绝桩装上——不装就是直接调真下载函数（本脚本自己就会发真出网）
            setattr(mod, attr, gate.refusalFor(moduleName, attr))
            assert getattr(mod, attr).__name__ == "_refuse", f"{attr} 装不上拒绝桩"
            try:
                getattr(mod, attr)({}, Path(td, attr), None)
            except RuntimeError as e:
                refused += 1 if "跑测层禁止真出网取权重" in str(e) else 0
                if (Path(td, attr)).exists():
                    wrote.append(attr)
    check("[6] 三处下载点逐个点名拒绝、零字节落盘、门记了账",
          refused == len(gate.sites) and not wrote
          and len(gate.trips) - tripsBefore == len(gate.sites),
          f"拒绝 {refused}/{len(gate.sites)} 落盘={wrote} 新记账={len(gate.trips) - tripsBefore}")

    bad = [t for ok, t in READINGS if not ok]
    print(f"\n读数 {len(READINGS)} 条，不成立 {len(bad)} 条" + (f"：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
