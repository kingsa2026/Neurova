# -*- coding: utf-8 -*-
"""生成 `docs/02-api/API_REFERENCE.md` 的「公开面清单」机器段（§6-399 裁定 A）。

## 为什么是生成物

附录原有一张**手写**的「无需认证」模块名单。2026-10-22 按真 `create_app()` 复算：它列的
60 个模块里 56 个能找到路由，其中只有 `health` 是全公开、**55 个至少有一条路由需认证**；
同一份文件里 `settings` 还留在"无需认证"行，而模块节已写"需认证"。手写派生表没有生成器、
没有守卫，漂移不会红——所以停用（裁定 B），改为本脚本产出 + 守卫逐字比对（裁定 A）。

## 口径（写进机器段，别只写在代码里）

- **路由表怎么读**：`create_app()` 顶层是 `_IncludedRouter`，其 `.path` 为空；全路径与
  **路由级依赖**在 `include_context.prefix` / `include_context.dependencies` 上，逐条展开再取
  `original_router.routes`。直接读顶层 `.path` 会得到"零路由"的假读数。
- **什么算"有门"**：路由依赖图（含路由级与函数依赖，递归）里出现 `auth`/`deps` 的身份与角色门
  ——`get_current_user`、`get_current_userWithQueryToken`、`get_optional_user`、
  `require_admin`、`require_role`、`requireIdentity*`。`require_admin()`/`require_role(...)`
  返回**每次新建的闭包**，按 qualname 认，不按函数对象注册表。
- **未覆盖的一类（明写）**：在 handler 体内自己校验 token/角色、而不经依赖的，本脚本**认不出来**；
  那一类只能靠真打请求（裁定 C 的抽样就是干这个）。
- 404/405 不算门——路径写错或方法不对，与"没门"是两件事；本脚本只读依赖图，不发请求。

用法：
`PYTHONPATH=$(git rev-parse --show-toplevel) python scripts/generate_api_auth_surface.py --write`
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOC = ROOT / "docs" / "02-api" / "API_REFERENCE.md"
BLOCK_BEGIN = "<!-- auth-surface:begin -->"
BLOCK_END = "<!-- auth-surface:end -->"
CAVEAT = ("口径：只认**路由依赖图**里的身份/角色门；在 handler 体内自验 token 的那一类**未覆盖**，"
          "要确认它只能真打请求。404/405 不算门。")

_AUTH_TOKENS = (
    "require_admin", "require_role", "requireIdentity", "require_identity",
    "get_current_user", "get_optional_user", "currentUserWithQueryToken",
)


def _isAuthLike(call) -> bool:
    if call is None:
        return False
    qual = getattr(call, "__qualname__", "") or ""
    module = getattr(call, "__module__", "") or ""
    if not module.startswith("neurova.api"):
        return False
    return any(token in qual for token in _AUTH_TOKENS)


def _depsGuarded(deps, depth: int = 0) -> bool:
    if depth > 12:
        return False
    for dep in deps or []:
        if _isAuthLike(getattr(dep, "call", None)):
            return True
        if _depsGuarded(getattr(dep, "dependencies", []), depth + 1):
            return True
    return False


def collect(app) -> List[Dict[str, Any]]:
    """逐路由：(method, path, guarded)。按 path/method 排序，保证生成物确定。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for inc in app.routes:
        if type(inc).__name__ != "_IncludedRouter":
            continue
        ctx = inc.include_context
        prefix = str(getattr(ctx, "prefix", "") or "")
        routerGuarded = _depsGuarded(getattr(ctx, "dependencies", []))
        for route in getattr(inc.original_router, "routes", []):
            path = prefix + (getattr(route, "path", "") or "")
            dependant = getattr(route, "dependant", None)
            deps = getattr(dependant, "dependencies", []) if dependant is not None else []
            guarded = routerGuarded or _depsGuarded(deps)
            for method in sorted(getattr(route, "methods", None) or []):
                if method in ("HEAD", "OPTIONS"):
                    continue
                # 同一 (方法, 路径) 被注册两次时，FastAPI 按**先注册**的那条匹配，后来的不可达。
                # 不去重的话，报告会把不可达的那条（碰巧没门）列成"公开"，而请求打到的是另一条。
                key = (method, path)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"method": method, "path": path, "guarded": bool(guarded)})
    rows.sort(key=lambda r: (r["path"], r["method"]))
    return rows


def _groupOf(path: str) -> str:
    if not path.startswith("/api/v1"):
        return path.split("/")[1] if path.startswith("/") and len(path) > 1 else "(root)"
    rest = path[len("/api/v1"):].strip("/")
    return rest.split("/")[0] if rest else "(root)"


def renderBlock(app) -> str:
    rows = collect(app)
    groups: Dict[str, Dict[str, int]] = {}
    for row in rows:
        g = groups.setdefault(_groupOf(row["path"]), {"total": 0, "guarded": 0, "open": 0})
        g["total"] += 1
        g["guarded" if row["guarded"] else "open"] += 1
    guarded = sum(1 for r in rows if r["guarded"])
    openRows = [r for r in rows if not r["guarded"]]

    lines = [
        BLOCK_BEGIN,
        "> 本段由 `scripts/generate_api_auth_surface.py`（`--write`）生成，**不要手改**：",
        "> 守卫 `tests/unit/api/test_authSurfaceFreshness.py` 逐字比对，漂移即红。",
        "> " + CAVEAT,
        "",
        "**汇总**：路由 %d 条（含方法展开）——需认证 **%d**、公开 **%d**。"
        % (len(rows), guarded, len(openRows)),
        "",
        "| 模块前缀 | 路由 | 需认证 | 公开 |",
        "|----------|------|--------|------|",
    ]
    for name in sorted(groups):
        g = groups[name]
        lines.append("| `%s` | %d | %d | %d |" % (name, g["total"], g["guarded"], g["open"]))
    lines += ["", "**依赖图里未见身份门的路由（候选集，不等于「无凭证可打」）**：", ""]
    if openRows:
        for row in openRows:
            lines.append("- `%s %s`" % (row["method"], row["path"]))
    else:
        lines.append("- （无）")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def applyBlock(text: str, block: str = None, app=None) -> str:
    """把机器段写回文档正文；缺标记或标记颠倒都直接抛（不静默追加第二段）。

    **行尾跟随文档**：API_REFERENCE 今天整档 CRLF；机器段按同一行尾拼回去，
    否则一次重写就把整档换成 LF（本卷记过的"整档换行尾"形态）。
    """
    if text.count(BLOCK_BEGIN) != 1 or text.count(BLOCK_END) != 1:
        raise ValueError("文档里 auth-surface 标记不是恰好一对：begin=%d end=%d"
                         % (text.count(BLOCK_BEGIN), text.count(BLOCK_END)))
    newline = "\r\n" if "\r\n" in text else "\n"
    begin = text.index(BLOCK_BEGIN)
    end = text.index(BLOCK_END) + len(BLOCK_END)
    if not block:
        if app is None:
            from neurova.api.app import create_app
            app = create_app()
        block = renderBlock(app)
    block = block.replace("\r\n", "\n").replace("\n", newline)
    return text[:begin] + block + text[end:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    raw = DOC.read_bytes().decode("utf-8")
    if args.write:
        DOC.write_bytes(applyBlock(raw).encode("utf-8"))
        print("公开面机器段已写入 %s" % DOC)
        return 0
    from neurova.api.app import create_app
    print(renderBlock(create_app()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
