# -*- coding: utf-8 -*-
"""常驻棘轮：宽 `except` 不许把故障折成一个"结论"（台账 §6-126，用户 2026-10-10 裁定「改 4 处 + 上棘轮」）。

判形（AST，不按文本猜）：`except Exception` / `except BaseException` / 裸 `except` / 含它们的元组
的处理器里，出现下面任一形态即命中——

① 新建并抛出一个**"查无此类"家族**的错误对象（`NOT_FOUND` 系码或 `status_code=404`）：
   故障被改写成"这条不存在"；
② **返回成功载荷**（`success_response(...)`、`{"code": 0}`、`"message": "success"`）：
   故障被改写成"测过了，没有"。

② 比 ① 隐蔽：状态码仍是 200，前端与巡检都读不出异常，而"空"恰好是排查时最可信的信号。

基线是**已裁决的存量**（本轮改完 4 处 + 扫荡补上的 `logout` 之后，剩下 2 处：
一处半诚实、一处注释明写的有意设计），只降不升：
修好了必须从表里摘掉（有一格反向咬合），新增落点当场红。
"""

from __future__ import annotations

import ast
import pathlib

from tests import ast_scan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TARGET_ROOT = REPO_ROOT / 'neurova'

# 已知存量（2026-10-10 逐处人工分辨后登记；按 `文件::函数` 记账，行号会漂不写行号）：
# - `memory/emotion.py::get_emotion_summary`  —— 回 `message="获取成功(降级)"`：半诚实，
#   用户本轮裁定"改 4 处"未含它（第 4 项"把降级也升成失败"要动前端 200→500，未选）；
# - `neurflow_api.py::otel_status` —— 状态端点不 500 是注释明写的有意设计，且 data 里带 `error`；
# - `auth.py::logout` —— **已修，不在本表**：原注释自辩"登出幂等所以出错也回成功"，
#   而同函数内层 S-12 又 `raise HTTPException(500)` 并写着"不得谎报登出成功"。
#   HTTPException 是 Exception 的子类 ⇒ 那记 500 被外层 catch-all 吞掉，意图从未生效。
#   2026-10-10 按教义第 5 条（同根因全命中点扫荡）删掉外层兜底，行为判据见
#   `tests/unit/api/test_internalFaultIsNotReportedAsVerdict.py::TestLogoutDoesNotInvalidateNothingSilently`。
# 上一版的启发式还把 `multi_model_client.py` 的两处**误报**成命中（分类名字符串
# `'model_not_found'` 被当成"折成 404"）——改成按 AST 节点判之后消失；登记前先逐处分辨，
# 命中数不等于结论。
KNOWN_BASELINE = {
    'neurova/api/endpoints/memory/emotion.py::get_emotion_summary',
    'neurova/api/endpoints/neurflow_api.py::otel_status',
}


def _foldsIntoNotFound(handler: ast.ExceptHandler) -> bool:
    """按**节点**判，不按文本：`model_not_found` 这类分类名字符串不是"折成 404"。"""
    for sub in ast.walk(handler):
        if isinstance(sub, ast.Attribute) and sub.attr.endswith('NOT_FOUND'):
            return True
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Attribute) and fn.attr == 'not_found':
                return True
            for kw in sub.keywords:
                if kw.arg == 'status_code' and isinstance(kw.value, ast.Constant)                         and kw.value.value == 404:
                    return True
    return False


def _returnsSuccessPayload(handler: ast.ExceptHandler) -> bool:
    """宽 except 里 return 成功信封（`success_response(...)` / `{"code": 0, ...}`）。

    排除同一返回值里带 `success: False` 的——那是**诚实的失败载荷**（本仓另一种合法形态），
    第一版就是把 `multi_model_client.py` 里的分类名 `'model_not_found'` 误判成两格，
    登记前逐处人工分辨才发现：启发式的命中数不能当结论。
    """
    for sub in ast.walk(handler):
        if not isinstance(sub, ast.Return) or sub.value is None:
            continue
        txt = ast.unparse(sub.value).replace("'", '"')
        if '"success": False' in txt:
            continue
        if 'success_response(' in txt or '"code": 0' in txt or '"message": "success"' in txt:
            return True
    return False


def _isWide(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    t = handler.type
    if isinstance(t, ast.Name) and t.id in ('Exception', 'BaseException'):
        return True
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in ('Exception', 'BaseException')
                   for e in t.elts)
    return False


def _functionsIn(tree: ast.AST) -> list:
    """一棵树里的全部函数定义节点（**一趟** `ast.walk`，供下面反复取用）。"""
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _enclosingFunction(functions: list, node: ast.AST) -> str:
    """取最近的**外层**函数（按 lineno..end_lineno 区间判，不靠行号先后猜）。

    入参是**已算好的函数清单**而不是树：本判据的每个 wide `except` 都要问一次
    "我在哪个函数里"，而待测面实测有 3224 处。原实现每次调用都 `ast.walk(tree)`
    找候选 ⇒ 3224 × 整棵树，单跑 10.3s（`testRatchetMatchesTheRegisteredBaseline`
    实测 16.0s，30s 默认墙钟下共享机器即红）。函数清单按树算一趟就够了。
    """
    best = None
    for cand in functions:
        end = getattr(cand, 'end_lineno', cand.lineno)
        if cand.lineno <= node.lineno <= end:
            if best is None or cand.lineno > best.lineno:
                best = cand
    return best.name if best is not None else '<module>'


def scan(root: pathlib.Path):
    """扫描面：`root` 子树里的 `except` 处理体（枚举、解析与**词法遍历**都走共享预算）。

    Issue #148 的两半都在这里：判据原先自带 `rglob` + `ast.parse`，被
    `tests/unit/test_ci_ast_scan_budget_guard.py` 的形态门禁点名；改走 `parsedModules`
    之后解析那半归零，但**遍历**那半仍在判据自己身上 —— 本函数每跑一次就把整棵树
    `ast.walk` 一遍，而 `testRatchetMatchesTheRegisteredBaseline` 与
    `testTargetRootIsNotEmpty` 各调一次，于是同一份节点被走两遍（实测 16.0s + 11.7s；
    30s 默认墙钟下与其余受保护文件共享机器时即红，正是本判据要防的那条根因）。
    改走 `nodeScan`：遍历按文件整进程缓存，第二遍近零成本（`tests/ast_scan.py` 的
    `_cachedNodes`），且 `hints` 文本预筛把「没有 `except` 三个字的文件」整段跳过 ——
    谓词是 `ast.ExceptHandler`，不含该关键字的文件不可能命中，预筛不改变判据。

    节点只与自己所属的文件配用：`_enclosingFunction` 取的是待查节点所在的那棵树，
    这里必须传**本节点所属**的树，不能换成"当前遍历到的那一棵"。
    """
    hits = []
    for path, tree in ast_scan.parsedModules(root, hints=("except",)):
        rel = path.relative_to(root.parent).as_posix()
        functions = _functionsIn(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not _isWide(node):
                continue
            func = _enclosingFunction(functions, node)
            if _foldsIntoNotFound(node):
                hits.append((f'{rel}::{func}', node.lineno, '折成"查无此类"'))
            elif _returnsSuccessPayload(node):
                hits.append((f'{rel}::{func}', node.lineno, '返回成功载荷'))
    return hits


def testRatchetMatchesTheRegisteredBaseline():
    """现值必须与登记表逐条相等——多一格即"新长了假成功"，少一格即"该摘表没摘"。"""
    found = {h[0] for h in scan(TARGET_ROOT)}
    extra = sorted(found - KNOWN_BASELINE)
    stale = sorted(KNOWN_BASELINE - found)
    assert not extra, (
        '出现了新的"把故障折成结论"落点（宽 except 里抛 NOT_FOUND 或返回成功载荷）：%s\n'
        '要么改成显式失败（查不到→404/空、出错→5xx 并点名原因），要么在本格登记并说明为什么'
        % extra)
    assert not stale, (
        '这些存量已经修好了，却还留在基线表里替不存在的事背书：%s —— 摘掉它们再提交' % stale)


def testScannerReallyFindsBothShapes(tmp_path):
    """反空转：两种形态都必须被抓到，且真抛 HTTPException 404 的正常写法不误报。"""
    src = (
        'from fastapi import HTTPException\n'
        'def wide_not_found():\n'
        '    try:\n        pass\n'
        '    except Exception:\n        raise HTTPException(status_code=404, detail="x")\n'
        'def wide_success():\n'
        '    try:\n        pass\n'
        '    except Exception:\n        return {"code": 0, "message": "success"}\n'
        'def narrow_ok():\n'
        '    try:\n        pass\n'
        '    except KeyError:\n        raise HTTPException(status_code=404, detail="真查无此条")\n'
    )
    pkg = tmp_path / 'neurova' / 'probe'
    pkg.mkdir(parents=True)
    (pkg / 'mod.py').write_text(src, encoding='utf-8')

    found = {h[0].split('::')[-1] for h in scan(pkg)}
    assert {'wide_not_found', 'wide_success'} <= found, (
        '探测器漏抓两种形态之一（实测 %s）——那基线表里的"干净"毫无意义' % sorted(found))
    assert 'narrow_ok' not in found, (
        '窄 except（KeyError→404）是真·查无此条的正确写法，不该被算成故障折叠：%s' % sorted(found))


def testTargetRootIsNotEmpty():
    files = ast_scan.filesUnder(TARGET_ROOT)
    assert len(files) > 500, (
        '扫描面只剩 %d 个文件——这条守卫已经在扫半空目录，它的绿不代表任何事' % len(files))
