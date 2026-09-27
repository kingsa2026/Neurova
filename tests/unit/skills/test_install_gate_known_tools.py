# -*- coding: utf-8 -*-
"""安装门的「已知工具全集」必须覆盖整个注册面（Issue #271 M5 尾巴·第五命中点）。

## 根因（放大视角扫同契约消费方时逮到，本片新发现）

`skills/skill_install_gate.py` 判断技能白名单里的工具名是否合法时，用的是一个
**手写探针清单**（41 个名字），并在注释里自陈理由：

    # 注册表探针：知名工具逐个验证（注册表无直接列表 API）

但这个理由**不成立**：`builtin_tools.get_registered_tool_names()` 就是那份
「直接列表 API」，且它自己的 docstring 明确写着「**单源**读侧」且「不得各自持有
一份名字表——第二份表就是幻名的温床（教义第 6 条）」。手写探针清单正是那份
被点名禁止的第二份表，实测漏掉 **30/71** 个真内置工具。

## 后果（实测，不是理论）

安装门会把真内置工具判成「未知工具」而**拒绝安装技能**：

    tools.allow=['deep_research']     → blocked: 含未知工具: 'deep_research'
    tools.allow=['write_stdin']       → blocked: 含未知工具: 'write_stdin'
    tools.allow=['query_database']    → blocked: 含未知工具: 'query_database'
    tools.allow=['orchestrate_tools'] → blocked: 含未知工具: 'orchestrate_tools'

即：技能的声明完全合法、工具确实存在，却装不上。而漏掉的 30 个里既有整族桌面
工具（`computer_dom_snapshot` / `computer_click_mark` / `computer_ssh_exec` …），
也有画布族、`git`、`file_parse`、`exec_command`、`write_pdf`。

## 处置

「已知工具全集」= **注册面读侧 ∪ 能力面登记**，手写探针清单删净。
判据逐名复算：注册面里每一个工具，安装门都必须认它合法。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neurova.builtin_tools import get_registered_tool_names, _BUILTIN_SCHEMAS
from neurova.skills.skill_install_gate import validate_permissions_for_install

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = REPO_ROOT / "neurova" / "skills" / "skill_install_gate.py"


def _errs(tool: str):
    out = validate_permissions_for_install({"tools": {"enabled": True, "allow": [tool]}})
    assert isinstance(out, dict), out
    return out.get("errors") or []


# ═══════════════════════════════════════════════════════════════
# 一、每一个真内置工具都必须被认合法（本片的核心：漏登在这一组上红）
# ═══════════════════════════════════════════════════════════════


class TestEveryRegisteredToolIsKnown:
    def test_registeredSurfaceIsNotEmpty(self):
        """反向锁：注册面确实有成员（空集会让下一条变成恒真）。"""
        assert len(get_registered_tool_names()) >= 60

    def test_installGateAcceptsEveryRegisteredTool(self):
        offenders = {}
        for name in get_registered_tool_names():
            errs = _errs(name)
            if errs:
                offenders[name] = errs
        assert offenders == {}, (
            "这些工具确实注册在册（内置），安装门却把它们判成未知工具而拒绝安装："
            f"{sorted(offenders)}"
        )

    @pytest.mark.parametrize(
        "name",
        ["deep_research", "write_stdin", "query_database", "orchestrate_tools",
         "computer_ssh_exec", "computer_click_mark", "git", "file_parse", "write_pdf"],
    )
    def test_previouslyRejectedToolsNowPass(self, name):
        """点名本片修掉的那 30 个漏登：改前它们全被判「未知工具」。"""
        assert name in set(get_registered_tool_names())
        assert _errs(name) == [], f"{name} 仍被安装门误拒：{_errs(name)}"


# ═══════════════════════════════════════════════════════════════
# 二、反向控制：真未知的名字仍必须被拒（不许把门开成恒过）
# ═══════════════════════════════════════════════════════════════


class TestStillRejectsUnknownTools:
    def test_unknownNameIsRejected(self):
        for bogus in ("no_such_tool_xyz", "get_time", "time_now", ""):
            errs = _errs(bogus)
            assert errs, f"{bogus!r} 是未知工具名，安装门必须拒"

    def test_mcpWhitelistStillNeedsNetworkDeclaration(self):
        """MCP 名仍走「必须有 network 声明配套」的既有口径。"""
        errs = _errs("mcp.filesystem.read")
        assert any("network" in e for e in errs), errs
        ok = validate_permissions_for_install({
            "tools": {"enabled": True, "allow": ["mcp.filesystem.read"]},
            "network": True,
        })
        assert not (ok.get("errors") or []), ok


# ═══════════════════════════════════════════════════════════════
# 三、第二份名字表不得再出现
# ═══════════════════════════════════════════════════════════════


class TestNoSecondNameTable:
    def test_gateDoesNotHoldItsOwnProbeList(self):
        """AST 判据：安装门里不得再出现「一堆内置工具名的字符串字面量集合」。

        判定形态：一个集合/列表字面量里含 ≥5 个**注册工具名**字面量——那正是
        第二份名字表的形状（单点引用不算，`get_builtin_tool_params(name)` 的
        探针调用在重建后不存在）。
        """
        registered = set(get_registered_tool_names())
        tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"), filename=str(GATE_PATH))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Set, ast.List)):
                continue
            literals = {
                elt.value for elt in node.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
            hit = literals & registered
            if len(hit) >= 5:
                offenders.append((node.lineno, sorted(hit)[:5]))
        assert offenders == [], (
            "安装门里又出现了一份手写工具名表（注册面已有单源读侧）："
            f"{offenders}"
        )

    def test_gateReadsTheSingleSource(self):
        src = GATE_PATH.read_text(encoding="utf-8")
        assert "get_registered_tool_names" in src, (
            "安装门没有读注册面单源（`get_registered_tool_names`）"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
