# -*- coding: utf-8 -*-
"""展开 installer.nsi 模板占位符/条件块，供 makensis 独立编译验证。

Tauri 打包时由 bundler 注入（handlebars 子集：{{#if}}/{{#unless}}/{{var}}）。
本脚本按 tauri.conf.json + 构建假值复现同一注入，产出 /tmp/nsis_verify/installer_expanded.nsi。
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
NSI = REPO / "NeurUI" / "src-tauri" / "nsis" / "installer.nsi"
CONF = REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
OUT_DIR = Path(r"C:\Users\xccoo\AppData\Local\Temp\nsis_verify")
OUT_FILE = OUT_DIR / "installer_expanded.nsi"


def main() -> int:
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    product = conf.get("productName", "Neurova")
    version = conf.get("version", "1.0.0")
    identifier = conf.get("identifier", "top.neurova.app")

    # 模板变量（与 tauri-bundler 注入语义一致；验证用假值/真实路径混排）
    ctx = {
        "product_name": product,
        "product_version": version,
        "product_version_with_build": "1.0.0.0",
        "version": version,
        "version_with_build": "1.0.0.0",
        "publisher": "Neurova",
        "manufacturer": "Neurova",
        "copyright": "© 2026 Neurova",
        "main_binary_name": "Neurova",
        "main_binary_path": "C:\\Users\\xccoo\\AppData\\Local\\Temp\\nsis_verify\\Neurova.exe",
        "install_mode": "perMachine",
        "arch": "x64",
        "bundle_id": identifier,
        "homepage": "https://www.neurova.top",
        "license": "",  # 空 → License 页条件关闭
        "installer_icon": str(REPO / "NeurUI" / "src-tauri" / "icons" / "icon.ico"),
        "uninstaller_icon": str(REPO / "NeurUI" / "src-tauri" / "icons" / "icon.ico"),
        "header_image": str(REPO / "NeurUI" / "src-tauri" / "nsis" / "header.bmp"),
        "sidebar_image": str(REPO / "NeurUI" / "src-tauri" / "nsis" / "sidebar.bmp"),
        "uninstaller_header_image": str(REPO / "NeurUI" / "src-tauri" / "nsis" / "header.bmp"),
        "out_file": str(OUT_DIR / "Neurova-setup-test.exe"),
        "compression": "lzma",
        "min_version": "10.0",
        "display_language_selector": "true",
        "uninstall_display_name": product,
        "installer_hooks": "",
        # bundler 语义：additional_plugins_path 指向只含附加插件的干净目录
        # （标准 NSIS 插件混入会触发 "Plugin command conflicts" 编译错）。
        # 验证目录 plugins/ 仅含 nsis_tauri_utils.dll。
        "additional_plugins_path": "C:\\Users\\xccoo\\AppData\\Local\\Temp\\nsis_verify\\plugins",
        "signed_plugins_path": "",
        "allow_downgrades": "true",
        "estimated_size": "5000",
        "ext": "exe",
        "start_menu_folder": product,
        "protocol": "neurova",
        "tagline": "personal AI agent",
        "this": "",
        "uninstaller_sign_cmd": "",
        "webview2_wversion": "120.0",
        "webview2_installer": "",
        "install_webview2_mode": "downloadBootstrapper",
        "minimum_webview2_version": "120.0.0.0",
        "webview2_bootstrapper_path": "",
        "webview2_installer_path": "",
        "webview2_installer_args": "",
        # 页面资产编译期目录（{{assets_dir}}）：bundler 实际不注入此变量——
        # 真实构建走模板相对路径。为此 expand 前先把 {{assets_dir}} 还原成
        # bundler 的 cwd 相对路径 ..\nsis\assets（见下方 assets_dir 处理）。
        "assets_dir": str(REPO / "NeurUI" / "src-tauri" / "nsis" / "assets"),
        "PLACEHOLDER_INSTALL_DIR": "",
    }
    # tauri.conf nsis.template 自定义模板还可能引用这些
    for k in ("languages", "custom_template", "nsis"):
        ctx.setdefault(k, "")

    src = NSI.read_text(encoding="utf-8")

    # {{#if X}}...{{/if}} / {{#unless X}}...{{/if}}（无嵌套，实测只有 2 处单层 if）
    def cond(m: re.Match) -> str:
        neg = m.group(1) == "unless"
        key = m.group(2)
        val = ctx.get(key, "")
        truthy = bool(val)  # tauri 语义：空串 = false
        if neg:
            truthy = not truthy
        return m.group(3) if truthy else ""

    src = re.sub(r"\{\{#(if|unless) ([a-z_]+)\}\}(.*?)\{\{/if\}\}", cond, src, flags=re.S)

    # {{#each X}}...{{/each}}：语言数组真实展开；其余（resources/binaries 等
    # 含 {{no-escape @key}} 复杂表达式）整块置空——资源 File 指令对"语法验证"
    # 无意义（真实构建由 bundler 注入成百上千条 File 行）。
    arrays = {
        "languages": ["English", "SimpChinese"],
        "language_files": ["English.nsh", "SimpChinese.nsh"],
    }

    def each(m: re.Match) -> str:
        key = m.group(1)
        body = m.group(2)
        items = arrays.get(key)
        if items is None:
            return ""
        return "".join(
            re.sub(r"\{\{this\}\}", it, body) for it in items
        )

    src = re.sub(r"\{\{#each ([a-z_]+)\}\}(.*?)\{\{/each\}\}", each, src, flags=re.S)
    # 嵌套 each（file_associations → association.ext）：内层先消化后再跑一遍
    # 单层正则即可清掉外层残余；as |x| 变体与残留复杂表达式整块置空。
    for _ in range(3):
        src = re.sub(r"\{\{#each [a-z_]+( as \|(\w+)\| ~?)?\}\}(.*?)\{\{/each\}\}", "", src, flags=re.S)
    # 嵌套 each 消化后的孤儿 {{/each}}（配对正则固有缺陷）直接删除
    src = re.sub(r"^\s*\{\{/each\}\}\s*$", "", src, flags=re.M)
    # 残留的复杂 handlebars 表达式（@key/or/no-escape 等）逐个置空
    src = re.sub(r"\{\{[^}]*@[a-z_]+[^}]*\}\}", "", src)

    # {{var}} 替换（未定义的保持原样并告警）
    def var(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return ctx[key]
        print(f"WARN: 未定义占位符 {{{{{key}}}}}（保持原样）")
        return m.group(0)

    src = re.sub(r"\{\{([a-z_]+)\}\}", var, src)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(src, encoding="utf-8")
    print(f"展开完成 → {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
