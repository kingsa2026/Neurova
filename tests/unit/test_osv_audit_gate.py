# -*- coding: utf-8 -*-
"""跨生态依赖审计门禁守卫（Issue #56 残留边界）。

pip-audit 只扫 Python 声明锁；npm audit 只扫 NeurUI。仓库里还有两片依赖面
此前**完全无人审计**，而它们都在生产执行路径上：

1. `NeurUI/src-tauri/Cargo.lock` —— Tauri 桌面壳 Rust 依赖树（447 crates）；
2. `tools/npx-runtime/package-lock.json` —— 运行时 `npx -y` 现拉的包。

本守卫锁定这套门禁的四条不变量：

- **双侧一致**：cnb 与 GitHub 都调同一命令（放行标准不分叉）；
- **阻塞**：不允许退化成非阻塞（扫描器跑不起来 ≠ 放行）；
- **允许清单有期限**：每条必须带 id + reason + ignoreUntil，且未过期
  （过期即重新报红是刻意设计，防"永久静音"）；
- **资产在位**：扫的目标与清单都在（删文件不等于解决漏洞）。

注意：本测试**不跑真实扫描**（要联网）。真实扫描由 CI 的
`python scripts/ci/osv_audit.py` 执行；这里只锁契约与配置。
"""

from __future__ import annotations

import datetime
import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
ALLOWLIST = PROJECT_ROOT / "scripts" / "ci" / "osv-allowlist.toml"
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "osv_audit.py"


class TestGateAssetsExist:
    """门禁的输入与实现必须在位——删掉它们不等于解决漏洞。"""

    def test_audit_script_exists(self):
        assert AUDIT_SCRIPT.is_file(), "scripts/ci/osv_audit.py 缺失——非 pip 依赖树无人审计"

    def test_allowlist_exists(self):
        assert ALLOWLIST.is_file(), "scripts/ci/osv-allowlist.toml 缺失（允许清单是门禁输入）"

    @pytest.mark.parametrize(
        "rel",
        ["NeurUI/src-tauri/Cargo.lock", "tools/npx-runtime/package-lock.json"],
    )
    def test_scan_targets_exist(self, rel):
        assert (PROJECT_ROOT / rel).is_file(), (
            f"审计目标 {rel} 不存在——门禁会因缺输入而失去意义"
        )


class TestBothSidesWireTheSameCommand:
    def _scripts(self, side: str) -> str:
        if side == "github":
            data = yaml.safe_load(io.open(GHW, encoding="utf-8").read())
            job = data["jobs"]["dependency-audit"]
            return "\n".join(
                str(s.get("run", "")) for s in job.get("steps", []) if isinstance(s, dict)
            )
        data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
        pipes = data["main"]["push"]
        pipe = next(p for p in pipes if isinstance(p, dict) and p.get("name") == "dependency-audit")
        return "\n".join(
            str(s.get("script", "")) for s in pipe.get("stages", []) if isinstance(s, dict)
        )

    @pytest.mark.parametrize("side", ["github", "cnb"])
    def test_osv_step_present(self, side):
        assert "python scripts/ci/osv_audit.py" in self._scripts(side), (
            f"{side} 侧的 dependency-audit 未跑 OSV 审计——"
            "Cargo.lock / 运行时 npx 包又回到无人可见状态。"
        )

    @pytest.mark.parametrize("side", ["github", "cnb"])
    def test_gate_is_blocking(self, side):
        """审计不得为非阻塞：跑不起来或不通过都必须拦合并。"""
        data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
        pipe = next(
            p for p in data["main"]["push"]
            if isinstance(p, dict) and p.get("name") == "dependency-audit"
        )
        assert not pipe.get("allowFailure"), "cnb dependency-audit 被放宽为非阻塞"

        gh = yaml.safe_load(io.open(GHW, encoding="utf-8").read())
        assert not gh["jobs"]["dependency-audit"].get("continue-on-error"), (
            "GitHub dependency-audit 被放宽为非阻塞"
        )


class TestAllowlistDiscipline:
    """允许清单是「有期限的技术债」，不是永久豁免。"""

    @staticmethod
    def _entries() -> list:
        """解析 .toml 的 [[IgnoredVulns]] 段（只取扁平键值，无需 toml 依赖）。"""
        text = io.open(ALLOWLIST, encoding="utf-8").read()
        blocks = re.split(r"\[\[IgnoredVulns\]\]", text)[1:]
        out = []
        for b in blocks:
            entry = {}
            # 值是字符串则去引号；裸日期（TOML date，如 ignoreUntil = 2027-03-31）
            # 直接取字面量——osv-scanner 要求日期为 date 类型，不能加引号。
            for m in re.finditer(
                r'^(\w+)\s*=\s*(?:"([^"]*)"|([0-9]{4}-[0-9]{2}-[0-9]{2}))', b, re.M
            ):
                entry[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
            out.append(entry)
        return out

    def test_entries_have_id_reason_and_expiry(self):
        entries = self._entries()
        assert entries, "允许清单为空——要么真的全清了（那就同步删掉本组断言），要么清单被清空绕过"
        for e in entries:
            assert e.get("id"), f"允许清单有条目缺 id: {e}"
            assert e.get("reason") and len(e["reason"]) > 20, (
                f"{e.get('id')} 的 reason 太短——必须写清「为什么允许」与复核条件"
            )
            assert e.get("ignoreUntil"), f"{e['id']} 缺 ignoreUntil（无期限=永久静音）"

    def test_no_entry_is_expired(self):
        today = datetime.date.today().isoformat()
        expired = [e["id"] for e in self._entries() if e.get("ignoreUntil", "") < today]
        assert not expired, (
            f"允许清单有过期条目: {expired}\n"
            "过期即重新报红是刻意设计——请复核：能升级则升级并删除条目，"
            "确不能则更新 ignoreUntil 并说明本轮复核结论。"
        )

    def test_no_unlisted_critical_ids(self):
        """清单里不得出现"没有 id 只有 reason"这类手滑（会让匹配失效）。"""
        for e in self._entries():
            assert re.fullmatch(r"(RUSTSEC|GHSA|CVE|PYSEC)-[\w\-]+", e["id"]), (
                f"id 格式可疑: {e['id']!r}"
            )


class TestAuditScriptContract:
    """脚本自身的契约（不联网即可验证的部分）。"""

    def test_script_is_importable_and_declares_targets(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("osv_audit", AUDIT_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.SCAN_TARGETS, "SCAN_TARGETS 为空——门禁没有扫描对象"
        for rel in mod.SCAN_TARGETS:
            assert (PROJECT_ROOT / rel).is_file(), f"SCAN_TARGETS 指向不存在的文件: {rel}"

    def test_binaries_have_pinned_sha256(self):
        """下载的扫描器必须校验指纹——不信任传输通道。"""
        import importlib.util

        spec = importlib.util.spec_from_file_location("osv_audit", AUDIT_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._BINARY_SHA256, "无二进制指纹表——下载后不校验 = 供应链敞开"
        for key, digest in mod._BINARY_SHA256.items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{key} 指纹不是 sha256: {digest}"
        assert mod.OSV_SCANNER_VERSION, "未钉扫描器版本（不同版本判定可能漂移）"

    def test_failure_is_not_silently_green(self):
        """脚本必须把"跑不起来"与"有漏洞"都当失败——安全门禁不能自我豁免。"""
        text = io.open(AUDIT_SCRIPT, encoding="utf-8").read()
        assert "return 1" in text and "return 2" in text, (
            "脚本未区分「有漏洞」与「基础设施错误」，两者都必须非 0"
        )
        # 允许清单缺失必须报错而非跳过
        assert "允许清单缺失" in text
