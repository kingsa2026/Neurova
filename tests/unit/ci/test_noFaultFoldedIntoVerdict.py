# -*- coding: utf-8 -*-
"""常驻棘轮：宽 `except` 不许把故障折成一个"结论"（台账 §6-126，用户 2026-10-10 裁定「改 4 处 + 上棘轮」）。

判形（AST，不按文本猜）：`except Exception` / `except BaseException` / 裸 `except` / 含它们的元组
的处理器里，出现下面任一形态即命中——

① 新建并抛出一个**"查无此类"家族**的错误对象（`NOT_FOUND` 系码或 `status_code=404`）：
   故障被改写成"这条不存在"；
② **返回成功载荷**（`success_response(...)`、`{"code": 0}`、`"message": "success"`）：
   故障被改写成"测过了，没有"。

② 比 ① 隐蔽：状态码仍是 200，前端与巡检都读不出异常，而"空"恰好是排查时最可信的信号。

基线是**已裁决的存量**（本轮改完 4 处后剩下的 2 处半诚实），只降不升：
修好了必须从表里摘掉（有一格反向咬合），新增落点当场红。
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TARGET_ROOT = REPO_ROOT / 'neurova'

# 已知存量（2026-10-10 逐处人工分辨后登记；按 `文件::函数` 记账，行号会漂不写行号）：
# - `memory/emotion.py::get_emotion_summary`  —— 回 `message="获取成功(降级)"`：半诚实，
#   用户本轮裁定"改 4 处"未含它（第 4 项"把降级也升成失败"要动前端 200→500，未选）；
# - `neurflow_api.py::otel_status` —— 状态端点不 500 是注释明写的有意设计，且 data 里带 `error`；
# - `auth.py::logout` —— 注释自辩"登出幂等所以出错也回成功"。**这条登记为存疑**：
#   token 吊销失败被吞成"登出成功"是安全面（会话服务端仍有效），与 §6-126 的"空"同族但性质更重，
#   已在台账 §6-126 另笔登记，等裁"登出是否必须服务端吊销成功才算成功"。
# 上一版的启发式还把 `multi_model_client.py` 的两处**误报**成命中（分类名字符串
# `'model_not_found'` 被当成"折成 404"）——改成按 AST 节点判之后消失；登记前先逐处分辨，
# 命中数不等于结论。
KNOWN_BASELINE = {
    'neurova/api/endpoints/memory/emotion.py::get_emotion_summary',
    'neurova/api/endpoints/neurflow_api.py::otel_status',
    'neurova/api/endpoints/auth.py::logout',
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


def _enclosingFunction(tree: ast.AST, node: ast.AST) -> str:
    """取最近的**外层**函数（按 lineno..end_lineno 区间判，不靠行号先后猜）。"""
    best = None
    for cand in ast.walk(tree):
        if not isinstance(cand, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(cand, 'end_lineno', cand.lineno)
        if cand.lineno <= node.lineno <= end:
            if best is None or cand.lineno > best.lineno:
                best = cand
    return best.name if best is not None else '<module>'


def scan(root: pathlib.Path):
    hits = []
    for path in sorted(root.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root.parent).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not _isWide(node):
                continue
            func = _enclosingFunction(tree, node)
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
    files = [p for p in TARGET_ROOT.rglob('*.py') if '__pycache__' not in p.parts]
    assert len(files) > 500, (
        '扫描面只剩 %d 个文件——这条守卫已经在扫半空目录，它的绿不代表任何事' % len(files))
