# -*- coding: utf-8 -*-
"""浏览器实测：知识库页 UI 导入 pptx → 列表刷新后是否可见 + 抓请求/控制台"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={'width': 1440, 'height': 900})
    reqs = []
    page.on('request', lambda r: reqs.append((r.method, r.url)) if '/knowledge' in r.url and '9527' in r.url else None)
    console = []
    page.on('console', lambda m: console.append(f'{m.type}: {m.text[:160]}'))

    page.goto('http://localhost:8100/login')
    page.wait_for_load_state('domcontentloaded')
    page.fill('.nr-auth-form input[autocomplete="username"]', 'admin')
    page.fill('.nr-auth-form input[autocomplete="current-password"]', 'Admin23@')
    page.locator('.nr-auth-form button').first.click()
    page.wait_for_timeout(3000)

    page.goto('http://localhost:8100/knowledge')
    page.wait_for_timeout(3500)
    page.screenshot(path='gui-test-screenshots/kb_before_import.png', full_page=True)
    rows = page.locator('.ant-table-row').count()
    print('rows before:', rows)

    # 打开导入弹窗 → 上传 pptx → 确认
    page.locator('button', has_text='导入').first.click()
    page.wait_for_timeout(800)
    page.set_input_files('input[type="file"]', 'scripts/tmp_kb_test.pptx')
    page.wait_for_timeout(500)
    # 弹窗内点导入按钮（modal footer）
    page.locator('.ant-modal button', has_text='导入').last.click()
    page.wait_for_timeout(4000)
    page.screenshot(path='gui-test-screenshots/kb_after_import.png', full_page=True)
    rows2 = page.locator('.ant-table-row').count()
    print('rows after:', rows2)
    txt = page.locator('.ant-table').inner_text()
    print('pptx visible in table:', 'tmp_kb_test' in txt)

    # 最近 8 条 knowledge 相关请求
    print('--- recent knowledge requests ---')
    for m, u in reqs[-8:]:
        print(m, u.replace('http://localhost:9527', ''))
    print('--- console errors ---')
    for c in console:
        if c.startswith('error') or 'Error' in c: print(c)
    b.close()
