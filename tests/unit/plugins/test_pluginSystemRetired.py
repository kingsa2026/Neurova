# -*- coding: utf-8 -*-
"""插件体系退役判据（用户 2026-10-10 裁定「不做插件体系」→ 整批退役，台账 §6-131）。

退役的不是 2206 行死码本身，而是"这个仓支持第三方插件"这项能力：
`plugin_manager.py:377-384` 是全仓唯一能把 manifest 变成可执行插件的实现
（`spec_from_file_location` + `sys.modules` 注册 + `exec_module`，另有依赖反查与拓扑加载序），
`plugin_manifest.py` 另有 semver/版本约束/8 项权限枚举——现役端点一样都没有（只翻内存字典）。
零消费者 + 无替代不构成删除理由，构成**必须由人拍板**的理由；拍板结果是"不做"。

四条都可失败：
① 包不得复活（复活即要重开这项能力，得先有新的裁定）；
② 架构文档不得继续把它陈述成"已实现"——**"文档声称有、代码没有"比留个空文件更坏**
   （§6-115 的教训），凡引用该路径处必须带已退役标注；
③ 面向前端的 `/v1/plugins` 那组路由**必须还在**（`NeurUI/src/api/modules/plugins.ts` 在用），
   退役的是加载器不是记账面；同时钉住它"只记账不加载"的实况，别让下一个人以为再接上就行；
④ 反空转：②的探测器对"未标注的新引用"必须抓到。
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ARCH_ROOT = REPO_ROOT / 'docs' / '01-architecture'
PLUGIN_MENTION = re.compile(r'neurova[/\.]plugins')
RETIRED_MARK = '已退役'


def _unmarkedPluginRefs(archRoot: pathlib.Path) -> list:
    """架构文档里提到 `neurova/plugins` 却**没有**已退役标注的行。"""
    bad = []
    for md in sorted(archRoot.rglob('*.md')):
        lines = md.read_text(encoding='utf-8', errors='replace').splitlines()
        for i, line in enumerate(lines):
            if not PLUGIN_MENTION.search(line):
                continue
            window = '\n'.join(lines[max(0, i - 3):i + 4])
            head = '\n'.join(lines[:15])
            if RETIRED_MARK not in window and RETIRED_MARK not in head:
                bad.append(f'{md.relative_to(archRoot.parent.parent).as_posix()}:{i + 1}')
    return bad


def testPluginPackageIsGone():
    pkg = REPO_ROOT / 'neurova' / 'plugins'
    assert not pkg.exists(), (
        f'{pkg.relative_to(REPO_ROOT)} 又回到了仓里——它随 2026-10-10 的裁定退役（台账 §6-131）；'
        '要复活"第三方插件体系"这项能力得先重新拍板，不是顺手把目录搬回来')
    assert not (REPO_ROOT / 'neurova' / 'plugins').is_dir()


def testArchitectureDocsDoNotPresentItAsImplemented():
    bad = _unmarkedPluginRefs(ARCH_ROOT)
    assert not bad, (
        '架构文档仍把插件体系陈述成现役（引用处附近找不到「已退役」标注）：\n  ' + '\n  '.join(bad)
        + '\n——按 §6-115 的教训，"文档声称有、代码没有"比空文件更坏：按文档找实现的人会以为这套能力在线')


def testPluginEndpointsStayAliveButOnlyLedger(monkeypatch):
    """记账面必须仍在役（前端在用），并钉住它"不加载模块"的实况。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api import auth
    from neurova.api.endpoints import plugin as plugin_api

    app = FastAPI()
    app.include_router(plugin_api.router, prefix='/api/v1/plugins')
    # 路由级依赖会先于路径匹配跑，未鉴权时任何路径都是 401——拿 404 做校准就必须
    # 先过鉴权，否则"≠404"这句话在任何改法下都恒成立（判据形态清单同族）。
    app.dependency_overrides[auth.get_current_user] = lambda: {
        'user_id': '1', 'username': 'tester', 'role': 'admin'}
    client = TestClient(app)

    assert client.get('/api/v1/plugins/').status_code == 200, (
        '前端的插件页依赖这组路由；退役的是加载器，不是记账面')
    assert client.get('/api/v1/plugins/no-such-plugin/modules').status_code == 404, (
        '404 校准不成立——上一条断言的 200 就无从区分"面在"与"面没了"')

    doc = (plugin_api.__doc__ or '')
    assert '记账' in doc, (
        '模块 docstring 没写明"只记账、不加载模块"——下一个人会以为装了插件就有代码在执行，'
        '这段实况必须留在被读到的地方：%r' % doc[:120])


def testUnmarkedDocRefIsDetected(tmp_path):
    """反空转：未标注的新引用必须被抓到，已标注的不许误报。"""
    docs = tmp_path / 'docs' / '01-architecture' / 'probe'
    docs.mkdir(parents=True)
    (docs / 'claim.md').write_text(
        '# 某设计\n\n本仓的插件系统位于 `neurova/plugins/`，可直接使用。\n', encoding='utf-8')
    (docs / 'marked.md').write_text(
        '# 某设计\n\n> 状态：已退役（2026-10-10）\n\n`neurova/plugins/` 已随裁定删除。\n',
        encoding='utf-8')

    bad = _unmarkedPluginRefs(tmp_path / 'docs' / '01-architecture')
    assert any('claim.md' in b for b in bad), (
        f'探测器漏掉了未标注的现役陈述：{bad} —— 那 ② 的"干净"没有任何意义')
    assert not any('marked.md' in b for b in bad), (
        f'已带退役标注的文件被误报：{bad}')
