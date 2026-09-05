# Neurova WPF 安装器（QQ NT 式单文件 · Cosmic 登录页同款视觉）

**最终形态 = 单文件 exe**：`Neurova_Setup_<版本>_x64.exe`（~455MB）。
WPF 界面壳（net48）内嵌 NSIS 静默内核，安装逻辑（icacls/卸载器/重装
检测）100% 复用 NSIS 模板，零重写。

## 视觉（与前端登录页 Cosmic 皮肤同款）

- 无边框圆角窗 + 深空底 `#06080F` + 静态星点（固定种子）
- 品牌 Logo：**NEUROVA-installer-logo.png**（350x90 白色横版，原尺寸
  居中不缩放；内嵌资源 `neurova-logo.png`）
- 玻璃输入框：22% 白填充 + 35% 白描边；主色 `#6366F1`（--nr-primary
  cosmic dark）；文字 `#F2F5FF` / 次级 `#96A5DC`
- 按钮模板必须含 **ContentPresenter**（否则文字全空白——已踩）

## 四页流程

1. 欢迎：Logo + 立即安装（未勾协议 = 深灰蓝禁用 #333A55，勾选 =
   主色）+ 底部协议圆点 + 《软件许可协议》《隐私政策协议》链接 +
   "自定义选项 ⌄" 折叠（安装位置：历史注册表目录 > D:\Program
   Files\Neurova > C: 兜底）+ **链接行**（开源地址：/GitHub/CNB/官网
   四段全可点击 → github.com/kingsa2026/Neurova、
   cnb.cool/kingsa2026/neurova、www.neurova.top）+ v1.0.0 版本行
2. 管理员账号：**380px 玻璃背板卡片**（注册区收窄，玻璃 Border 定宽居中——宽高都别放在 StackPanel 上）+ 用户名（默认
   admin，1-32 位，禁 空格 `:/\<>|?*%$"`，对齐 NSIS
   ValidateAdminUsername）+ 设置/确认密码（两次输入，大小写敏感一致
   性校验，**≤16 位**，字段下方常显提示行）+ **amber 权限警示** +
   红色内联错误提示（非 MessageBox）+ 标签列 110px 保证「设置密码：」
   不换行
3. 进度：内核解压 0-15%（真实字节进度）→ NSIS /S 目录增长 15-95%
4. 完成：✓ + 立即运行 + 立即体验

**管理员凭据通道**：安装成功后写 `<安装目录>\backend\data\bootstrap_admin.ini`
（UTF-8 BOM，`[bootstrap]` username/password——与 NSIS PageAdminAccount
同格式，后端 `_read_ini_text` 多编码解析已契约验证），后端首启消费即删。

## 构建

```cmd
cd NeurUI\src-tauri\installer-wpf
build.cmd <kernel-setup.exe> <logo.png>    :: 内嵌模式 = 单文件安装器
build.cmd                                  :: 壳 only（开发迭代）
```

打包链路（自动化）：`scripts/desktop/package_installer_zip.py`
默认产出单 exe。**内核回收**：bundle 被清时可从既有单文件 exe
反提取内嵌内核（PowerShell Assembly.LoadFile → resource stream），
免重跑 tauri build。

## 已知坑（实测踩过）

- **csc 语法上限 C# 5**：`$""`、`?.`、`using var`、`1_000_000` 分隔符、
  `WindowChrome.IsHitTestVisibleInChrome = true`（初始化器点语法）全禁；
  附加属性用 `WindowChrome.SetIsHitTestVisibleInChrome(obj, true)`
- **build.cmd 必须 ASCII-only + CRLF 行尾**：LF 括号块被 cmd 啃碎
  （症状：`'not' 不是内部或外部命令`）；cmd 块内禁止自引用 `%VAR%`
  （parse-time 展开取进块前值——icon 曾因此静默丢失）
- **PS1 无 BOM**：PowerShell 5.1 按 GBK 读，中文路径变乱码——脚本内用
  `$PSScriptRoot` 消中文字面量
- 单文件 exe 运行时：内核先解压 `%TEMP%\NeurovaSetup\`（装完自清）；
  `NEUROVA_SETUP_DEV=1` 旁路管理员校验（UI 迭代用，正式包不设）
- 静默模式跳过 NSIS 管理员凭据页（NSIS 版）——WPF 版已接管该环节
- NSIS 卸载器延迟自删（/S 后目录数秒消失属正常）
- SVG→PNG 渲染：cairosvg 缺 libcairo 不可用，用 **Chrome headless
  --screenshot --default-background-color=00000000**（临时目录不可写时
  换可写盘路径）

## 相关

- NSIS 模板（内核逻辑 + nsDialogs 单页版，独立双击安装仍可用）：
  `NeurUI/src-tauri/nsis/installer.nsi`
- 美术资产：`scripts/desktop/gen_installer_art.py`
- 排障表：`~/.zcode/skills/neurova-installer-pack/SKILL.md`
