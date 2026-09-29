# -*- coding: utf-8 -*-
"""浏览器级 live-verify：迁移弹层的源选择与渠道勾选（Issue #326 第 3 条）。

## 为什么单靠组件级判据不够（教义第 4 条）

`ChannelMigrationDialog.test.ts` 判的是**组件契约**：它用 `@vue/test-utils` 挂载
组件、把 antdv 的 `a-modal` / `a-select` / `a-checkbox` 换成桩。桩能证明"事件线
接对了"，但证明不了真渲染——弹层到底有没有画出来、下拉有没有展开、勾选有没有
真的落到屏上，只有真浏览器里才算数（`a-modal` 靠 Teleport 到 body，桩根本
不经历这一段）。

本脚本走**真构建 + 真 Chromium**：

1. 在临时目录生成最小脚手架（`vite` 直引仓库源码，渠道 API 换成固定数据的桩——
   真后端链路由 `channel_ownership_gate_290.py` 判），构建出静态产物；
2. 同进程内起一个静态服务（线程内 `serve_forever`，渲染前已 listen），
   用真 Chromium 打开、逐步操作并断言；
3. 每一步截图落 `/tmp/neurovaChannelMigrationDialog326/`，供人眼复核。

无等待语义：服务在同一进程内、渲染前已 listen（构建纪律禁止轮询等待外部服务）。

跑法：`python tests/manual/channel_migration_dialog_326.py`
依赖：`NeurUI/node_modules`（`npm ci`）、`playwright` 与 Chromium 二进制。
两项缺席都**点名**退出，不静默跳过。
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "NeurUI"
SHOTS = Path("/tmp/neurovaChannelMigrationDialog326")
CHROMIUM = Path("/opt/ms-playwright/chromium-1243/chrome-linux64/chrome")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


HARNESS_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" /><title>迁移弹层 · 浏览器自证</title></head>
<body><div id="app"></div><script type="module" src="./dialog.ts"></script></body></html>
"""

#: 渠道 API 的桩：只回固定数据（真后端链路另由 channel_ownership_gate_290.py 判）。
HARNESS_STUB = """export function listChannelMigrationSources(_to?: string) {
  return Promise.resolve({ data: { sources: [
    { agent_id: 'default', channels: ['dingtalk', 'feishu', 'qq'] },
    { agent_id: 'legacy-agent', channels: ['telegram'] },
  ] } })
}
export function migrateAgentChannelConfigs(from: string, to: string, types?: string[]) {
  return Promise.resolve({ data: { success: true, from_agent_id: from, to_agent_id: to, migrated: types ?? [] } })
}
"""

#: 脚手架与真实页面的接线一致：两页都在 `@migrated` 里关闭弹层，故这里也关。
HARNESS_ENTRY = """import { createApp, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import zhCN from '@/i18n/locales/zh-CN'
import ChannelMigrationDialog from '@/components/ChannelMigrationDialog.vue'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
const app = createApp({
  setup() {
    const open = ref(false)
    return () => h('div', { style: 'padding:24px;background:#0b0d16;min-height:100vh' }, [
      h('button', { id: 'open', style: 'padding:8px 16px', onClick: () => (open.value = true) },
        '迁移存量渠道到当前智能体'),
      h(ChannelMigrationDialog, {
        open: open.value, targetAgentId: 'kai',
        onClose: () => (open.value = false),
        onMigrated: () => (open.value = false),
      }),
    ])
  },
})
app.use(i18n)
app.use(Antd)
app.mount('#app')
"""

HARNESS_CONFIG = """import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const ROOT = %(root)r

export default defineConfig({
  root: ROOT,
  base: './',
  plugins: [vue()],
  resolve: {
    alias: [
      { find: '@/api/modules/channel-configs', replacement: resolve(ROOT, '%(stage)s/channel-configs.stub.ts') },
      { find: '@', replacement: resolve(ROOT, 'src') },
    ],
  },
  build: { outDir: %(out)r, emptyOutDir: true, rollupOptions: { input: resolve(ROOT, '%(stage)s/dialog.html') } },
})
"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # 服务日志与本步判据无关，静音
        pass


def buildHarness(stage: Path, outDir: Path) -> bool:
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "dialog.html").write_text(HARNESS_HTML, encoding="utf-8")
    (stage / "dialog.ts").write_text(HARNESS_ENTRY, encoding="utf-8")
    (stage / "channel-configs.stub.ts").write_text(HARNESS_STUB, encoding="utf-8")
    (stage / "vite.config.ts").write_text(
        HARNESS_CONFIG % {"root": str(FRONTEND), "out": str(outDir), "stage": stage.name},
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["npx", "vite", "build", "--config", f"{stage.name}/vite.config.ts"],
        cwd=str(FRONTEND), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
    return proc.returncode == 0


def render(outDir: Path) -> int:
    from playwright.sync_api import sync_playwright

    srv = socketserver.ThreadingTCPServer(
        ("127.0.0.1", 0), functools.partial(_Quiet, directory=str(outDir)),
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROMIUM), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
            errors: list[str] = []
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

            page.goto(f"http://127.0.0.1:{port}/{os.environ['HARNESS_STAGE']}/dialog.html")
            page.wait_for_selector("#open", timeout=15000)
            page.screenshot(path=str(SHOTS / "0-entry.png"))

            page.click("#open")
            page.wait_for_selector('[data-testid="migration-select-all"]', state="hidden", timeout=2000)
            page.wait_for_selector(".ant-modal .nr-mig-field", state="visible", timeout=10000)
            page.wait_for_timeout(400)
            page.screenshot(path=str(SHOTS / "1-dialog-before-source.png"))
            body = page.inner_text(".ant-modal")
            check("[1] 弹层真渲染出来（真 Teleport 到 body）", "迁移存量渠道" in body)
            check("[2] 未选源时不出现渠道面（没选源就没有「要迁哪些」）",
                  "选择要迁移的渠道" not in body)

            page.click(".ant-select-selector")
            page.wait_for_timeout(400)
            options = page.locator(".ant-select-item-option").all_inner_texts()
            page.screenshot(path=str(SHOTS / "2-source-dropdown.png"))
            check("[3] 源下拉展开且候选来自服务端（不硬编码 default）",
                  len(options) == 2 and any("legacy-agent" in o for o in options), str(options))

            page.locator(".ant-select-item-option", has_text="default").first.click()
            page.wait_for_timeout(400)
            page.screenshot(path=str(SHOTS / "3-source-picked.png"))
            body = page.inner_text(".ant-modal")
            shown = [c for c in ("dingtalk", "feishu", "qq") if c in body]
            check("[4] 选定源后列出该源的渠道", shown == ["dingtalk", "feishu", "qq"], str(shown))

            page.click('[data-testid="migration-select-all"]')
            page.wait_for_timeout(300)
            page.screenshot(path=str(SHOTS / "4-select-all.png"))
            picked = page.locator(".ant-checkbox-checked").count()
            check("[5] 全选一次勾上全部渠道", picked == 3, f"勾选数={picked}")

            confirm = page.locator('[data-testid="migration-confirm"]')
            check("[6] 有选中项时提交可用", confirm.is_enabled(), confirm.inner_text())
            confirm.click()
            page.wait_for_timeout(900)
            page.screenshot(path=str(SHOTS / "5-after-confirm.png"))
            hidden = page.locator(".ant-modal-wrap").first.is_hidden() \
                if page.locator(".ant-modal-wrap").count() else True
            check("[7] 确认后弹层关闭（@migrated 接线与真实页面一致）", bool(hidden))

            check("[8] 全程无 console 错误", not errors, str(errors[:5]))
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


def main() -> int:
    print(f"截图落点: {SHOTS}")
    SHOTS.mkdir(parents=True, exist_ok=True)

    if not (FRONTEND / "node_modules").is_dir():
        print("NeurUI/node_modules 缺席：先 cd NeurUI && npm ci（点名退出，不静默跳过）", file=sys.stderr)
        return 2
    if not CHROMIUM.exists():
        print(f"Chromium 二进制缺席：{CHROMIUM}（点名退出，不静默跳过）", file=sys.stderr)
        return 2

    # 脚手架建在仓库内的临时目录（vite 要求 input 在 root 内），跑完即删。
    stage = FRONTEND / f".smoke-migration-{os.getpid()}"
    outDir = Path(f"/tmp/neurovaChannelMigrationDialog326-dist-{os.getpid()}")
    os.environ["HARNESS_STAGE"] = stage.name
    try:
        if not buildHarness(stage, outDir):
            check("[0] 前端构建成功", False, "vite build 非零退出（见上方输出）")
            return 1
        check("[0] 前端构建成功", True)
        render(outDir)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(outDir, ignore_errors=True)

    print()
    if failures:
        print("LIVE-VERIFY FAILED / Issue #326 迁移弹层（浏览器级）：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / Issue #326 迁移弹层（浏览器级 · 真 Chromium）")
    print(json.dumps({"screenshots": sorted(p.name for p in SHOTS.glob("*.png"))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
