# -*- coding: utf-8 -*-
"""运行时 npx 包版本登记（Issue #56 残留边界收口）。

问题（实跑确认）：仓库里多处用 `npx -y <pkg>` 拉起 Node 服务，而 **npx 不带
版本号时每次解析 latest**：

    npx -y @askjo/camofox-browser      # → 今天 1.16.0，明天可能是 1.17.x

这意味着：
1. **不可复现**——同一个 Neurova 版本，在不同日期/不同机器上跑的是不同的
   第三方代码，出问题无法归因。
2. **不在审计覆盖面内**——这些包由 npx 现拉现跑，既不进 package.json，
   也不进任何锁文件，pip-audit / npm audit / OSV 都看不到它们。
3. **首跑即最新**——上游发新版（含回归或投毒）会在用户机器上即时生效，
   没有评审窗口。

处置：把"该跑哪个版本"从 npx 的隐式 latest 改成显式登记，本模块是**唯一
事实源**：

- `PINNED`：包名 → 精确版本。所有 `npx -y <pkg>` 调用点必须经
  `pinned_spec(pkg)` 取 spec，不得再写裸包名。
- `to_package_json_dependencies()`：导出给 `tools/npx-runtime/package.json`
  ——该清单**只用于生成锁文件并被 OSV 审计**，不被 npm 安装执行（`--ignore-scripts`
  且无 node_modules 入库）。审计覆盖面由此闭合。
- `scripts/ci/osv_audit.py` 扫 `tools/npx-runtime/package-lock.json`。

升级流程（契约）：
    1. 改本模块 PINNED 的版本号；
    2. `cd tools/npx-runtime && npm install --package-lock-only --no-audit --ignore-scripts`
    3. `python scripts/ci/osv_audit.py`（必须无未允许漏洞）
    守卫测试 tests/unit/tools/test_npx_runtime_pinning.py 会锁死三者一致，
    在 CI 里双向校验（改一处漏改另一处即红）。
"""

from __future__ import annotations

from typing import Dict

# ── 唯一事实源：运行时经 npx 拉起的包与其钉死版本 ──────────────────────────
# 版本取值 = 2026-09-18 各包 npm latest（登记当时的现状，不引入行为变更），
# 之后由 Dependabot / 人工按上面的「升级流程」推进。
PINNED: Dict[str, str] = {
    # 反检测浏览器服务（neurova/computer_use/camofox_supervisor.py 常驻拉起）
    "@askjo/camofox-browser": "1.16.0",
    # MCP 白名单目录：context7 库文档检索（neurova/tool_layers/mcp_catalog.py）
    "@upstash/context7-mcp": "4.1.1",
    # MCP 白名单目录：dbhub 只读 SQL（同文件）
    "@bytebase/dbhub": "1.2.5",
    # 共享配置默认模板里的 filesystem MCP server（neurova/shared_config.py）
    "@modelcontextprotocol/server-filesystem": "2026.8.31",
}


def pinned_spec(package: str) -> str:
    """返回带精确版本的 npx spec（`pkg@x.y.z`）；未登记包直接抛错。

    "未登记包抛错"是刻意的：新增一个运行时拉取的包而忘了登记，就等于悄悄
    新增一块无审计覆盖面，必须在开发期就炸掉，而不是等到线上出事。
    """
    version = PINNED.get(package)
    if not version:
        raise KeyError(
            f"运行时 npx 包未登记: {package!r}\n"
            "请在本模块 PINNED 中登记精确版本（并同步 "
            "tools/npx-runtime/package.json 与锁文件，见模块 docstring）。"
        )
    return f"{package}@{version}"


def pinned_npx_args(package: str, *rest: str) -> list:
    """构造 `npx -y pkg@ver ...` 的 args 列表（钉版本 + 透传其余参数）。"""
    return ["-y", pinned_spec(package), *rest]


def to_package_json_dependencies() -> Dict[str, str]:
    """导出 package.json dependencies（精确版本，非 ^ 区间）。"""
    return dict(PINNED)
