# Neurova 鸿蒙应用上架发布检查清单

> 文档路径：`docs/HARMONYOS_RELEASE_CHECKLIST.md`
> 适用范围：NeurovaHarmony 鸿蒙 App（HarmonyOS 6.1 / API 13）
> 用途：上架华为应用市场前的全面自检清单，确保每次发布版本均通过
> 更新日期：2026-06-25

---

## 使用说明

- 本清单为**发布前必检**项目，所有项必须勾选通过方可上传应用市场
- 每项含「检查方法」与「通过标准」
- 任一项未通过则**禁止发布**，需修复后重新走查
- 推荐在每次版本号变更时复制本清单为 `release-vX.Y.Z-checklist.md` 归档

---

## 一、应用基本信息核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 1.1 | bundleName 唯一性 | 查看 `AppScope/app.json5` 的 `app.bundleName` | 与 AGC 注册应用一致，格式 `com.neurova.app` | ☐ |
| 1.2 | versionCode 递增 | 查看 `AppScope/app.json5` 的 `app.versionCode` | 整数，比上一发布版本大 | ☐ |
| 1.3 | versionName 规范 | 查看 `app.versionName` | 符合语义化版本 `MAJOR.MINOR.PATCH`（如 `1.0.0`） | ☐ |
| 1.4 | 应用名称 | `AppScope/resources/base/element/string.json` 的 `App_name` | 不含「测试」「demo」等字样 | ☐ |
| 1.5 | 应用描述 | `AppScope/app.json5` 的 `app.label` 与 AGC 中的应用介绍 | 描述准确，无敏感词 | ☐ |
| 1.6 | vendor 厂商 | `AppScope/app.json5` 的 `app.vendor` | 填写真实企业或开发者名 | ☐ |
| 1.7 | 设备类型 | `entry/src/main/module.json5` 的 `module.deviceTypes` | 至少 `phone`，按需 `tablet`、`2in1` | ☐ |

---

## 二、资源完整性核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 2.1 | 应用图标 | `AppScope/resources/base/media/app_icon.png` | 1024×1024 PNG，无透明通道，无圆角 | ☐ |
| 2.2 | 启动页图标 | `entry/src/main/resources/base/media/start_icon.png` | 192×192 PNG | ☐ |
| 2.3 | 启动页背景 | `entry/src/main/resources/base/element/color.json` 的 `start_window_background` | 与首屏背景色一致，无白屏闪烁 | ☐ |
| 2.4 | 多语言字符串 | `resources/<locale>/element/string.json` | 至少包含 `zh-CN` 与 `en-US` | ☐ |
| 2.5 | 字符串完整性 | grep `\$string:` 引用 | 所有 `$string:xxx` 在 resources 中均有定义 | ☐ |
| 2.6 | 多语言图标（按需） | `resources/<locale>/media/` | 不同语言无差异化需求时复用 base | ☐ |
| 2.7 | 权限说明字符串 | `reason_internet`、`reason_network_info`、`reason_camera` | 三个权限说明均已定义且用户可读 | ☐ |

---

## 三、权限合规性核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 3.1 | 权限最小化 | `module.json5` 的 `requestPermissions` | 仅声明实际使用的权限，无冗余 | ☐ |
| 3.2 | 权限说明文案 | 每项权限的 `reason` 字段 | 用户可读，说明使用场景与必要性 | ☐ |
| 3.3 | 权限使用时机 | 每项权限的 `usedScene.when` | `always` 仅用于必要场景，`inuse` 用于按需 | ☐ |
| 3.4 | INTERNET 权限 | `ohos.permission.INTERNET` | `when: always`，reason 说明用于 API 与 WS 通信 | ☐ |
| 3.5 | GET_NETWORK_INFO | `ohos.permission.GET_NETWORK_INFO` | `when: always`，reason 说明用于网络状态监测 | ☐ |
| 3.6 | CAMERA 权限 | `ohos.permission.CAMERA` | `when: inuse`，reason 说明用于扫码配对（与 `string.json` 中 `reason_camera` 一致） | ☐ |
| 3.7 | 敏感权限 | 检查是否使用 `ohos.permission.READ_*` / `WRITE_*` | 未使用任何位置、通讯录、文件等敏感权限 | ☐ |
| 3.8 | 权限与隐私政策一致 | 对照 `docs/HARMONYOS_PRIVACY_POLICY.md` 第二章 | 文档中列出的权限与 `module.json5` 一致 | ☐ |

---

## 四、隐私政策合规

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 4.1 | 隐私政策文档存在 | `docs/HARMONYOS_PRIVACY_POLICY.md` | 文件存在且内容完整（9 章节） | ☐ |
| 4.2 | 隐私政策 URL 可访问 | 将文档部署到公开 URL | 应用市场审核需可访问的 HTTPS URL | ☐ |
| 4.3 | AGC 隐私政策 URL | AGC 控制台 → 应用信息 → 隐私政策 | 已填写可访问 URL，与 4.2 一致 | ☐ |
| 4.4 | 用户首次启动提示 | 应用首次启动时弹窗 | 显示隐私政策摘要 + 「同意」/「不同意」按钮 | ☐ |
| 4.5 | 用户不同意处理 | 点击「不同意」时 | 退出应用，不进入主功能 | ☐ |
| 4.6 | 用户撤回同意入口 | 设置页提供「撤回隐私政策同意」 | 撤回后清除本地数据并退出 | ☐ |
| 4.7 | 未成年人保护 | 隐私政策第七章 | 已说明未成年人保护措施 | ☐ |
| 4.8 | 第三方 SDK 披露 | 隐私政策信息共享章节 | 列出所有第三方 SDK 与用途 | ☐ |

---

## 五、签名配置核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 5.1 | 签名配置文档 | `docs/HARMONYOS_SIGNING_GUIDE.md` | 已按指南完成全部步骤 | ☐ |
| 5.2 | 密钥库文件存在 | `NeurovaHarmony/signing/neurova-release.p12` | 文件存在且未损坏 | ☐ |
| 5.3 | 发布证书存在 | `signing/neurova-release.cer` | 华为签发，未过期 | ☐ |
| 5.4 | Profile 文件存在 | `signing/neurova-profile.p7b` | 华为签发，未过期（默认 1 年） | ☐ |
| 5.5 | build-profile.json5 配置 | `NeurovaHarmony/build-profile.json5` 的 `signingConfigs` | 非空数组，`material` 字段完整 | ☐ |
| 5.6 | signingConfig 关联 | `products[].signingConfig` | 与 `signingConfigs[].name` 一致 | ☐ |
| 5.7 | 密码已加密 | DevEco Studio 中查看 | 密码字段显示为密文（非明文） | ☐ |
| 5.8 | 签名算法合规 | `material.signAlg` | `SHA256withECDSA` | ☐ |
| 5.9 | git 忽略规则 | `.gitignore` 包含 `signing/`、`*.p12` 等 | 签名文件不会误提交 | ☐ |
| 5.10 | 编译签名通过 | `hvigorw assembleHap --mode release` | 输出 `Successfully signed the hap` | ☐ |

---

## 六、代码质量核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 6.1 | TypeScript 类型检查 | `hvigorw check` 或 DevEco Studio Inspect | 无类型错误 | ☐ |
| 6.2 | 无 TODO 标注 | grep `TODO M6` 或 `TODO` | 上架前 P0/P1 TODO 已全部解决；P2 TODO 已记录 | ☐ |
| 6.3 | 无 console.log | grep `console.log` | 全部替换为 `Logger` 调用 | ☐ |
| 6.4 | 无硬编码密码 | grep 常见密码字段 | 无 `password`、`token`、`secret` 硬编码值 | ☐ |
| 6.5 | 无硬编码 IP | grep `192.168.` `127.0.0.1` | 全部走 `ConfigManager` 配置 | ☐ |
| 6.6 | 无未使用 import | IDE 检查 | 移除所有 unused import | ☐ |
| 6.7 | 代码混淆启用 | `entry/build-profile.json5` 的 `obfuscation.ruleOptions.enable` | `true`，且 `obfuscation-rules.txt` 完整 | ☐ |
| 6.8 | 单元测试通过 | DevEco Studio 运行 ohosTest | 全部测试用例通过 | ☐ |
| 6.9 | ArkTS 严格模式 | `buildOption.arkOptions.runtimeOnly` | 按需配置，未启用 strict 时排除动态特性 | ☐ |

---

## 七、功能完整性核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 7.1 | 登录页 | 启动应用 → 登录页 | 可正常输入、登录、跳转主页 | ☐ |
| 7.2 | 主面板 | 登录后 → Dashboard | 显示概览卡片、数据加载正常 | ☐ |
| 7.3 | 对话页 | 进入对话 → 发送消息 | WS 连接、流式响应、停止生成均正常 | ☐ |
| 7.4 | 智能体列表 | 进入 AgentListPage | 列表加载、LazyForEach 滚动流畅 | ☐ |
| 7.5 | 记忆管理 | 进入 MemoryPage | 列表加载、筛选、搜索、删除均正常 | ☐ |
| 7.6 | 路由守卫 | 未登录访问受保护页 | 自动跳转登录页 | ☐ |
| 7.7 | 网络异常处理 | 断网状态下操作 | 显示友好错误提示，不崩溃 | ☐ |
| 7.8 | WS 断线重连 | WS 连接中断 | 自动重连，恢复后可继续对话 | ☐ |
| 7.9 | 多设备适配 | phone / tablet / 2in1 | UI 在不同尺寸下不变形 | ☐ |
| 7.10 | 后台返回前台 | 切到后台再返回 | 状态恢复，WS 自动重连 | ☐ |

---

## 八、性能指标核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 8.1 | 冷启动时间 | DevEco Studio Profiler | ≤ 2 秒（中端设备） | ☐ |
| 8.2 | 首页渲染时间 | Profiler → 渲染 | ≤ 500ms | ☐ |
| 8.3 | 消息列表滚动 | FPS 监测 | ≥ 55 FPS（LazyForEach 生效） | ☐ |
| 8.4 | WS 流式响应延迟 | ChunkBatcher 60ms 窗口 | 首 token 到达后 ≤ 60ms 显示 | ☐ |
| 8.5 | 内存占用 | Profiler → 内存 | 峰值 ≤ 200MB | ☐ |
| 8.6 | 包体积 | `assembleHap` 输出 | HAP ≤ 30MB（启用混淆后） | ☐ |
| 8.7 | 电量消耗 | 真机使用 1 小时 | 后台不耗电，前台正常 | ☐ |
| 8.8 | 无内存泄漏 | Profiler → 内存 → 反复进出页面 | 内存稳定，无明显增长 | ☐ |

---

## 九、安全合规核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 9.1 | HTTPS 强制 | 抓包 API 与 WS 流量 | 全部走 HTTPS/WSS，无明文 HTTP | ☐ |
| 9.2 | Token 存储 | 检查 `AuthStore` 实现 | accessToken 通过 `preferences` 加密存储 | ☐ |
| 9.3 | Token 过期处理 | 模拟 token 过期 | 自动跳转登录页，不卡死 | ☐ |
| 9.4 | 输入校验 | XSS / SQL 注入测试 | 用户输入做转义与长度限制 | ☐ |
| 9.5 | 敏感信息日志 | grep `Logger.*token` / `Logger.*password` | 敏感信息不入日志 | ☐ |
| 9.6 | 反编译防护 | 代码混淆已启用 | 反编译后符号名不可读 | ☐ |
| 9.7 | 调试日志关闭 | release 模式下 Logger | release 模式仅输出 ERROR 级别 | ☐ |
| 9.8 | 网络超时 | API 客户端配置 | 所有请求有超时设置（默认 30s） | ☐ |
| 9.9 | 防 SSL Pinning（按需） | 高安全场景 | 已实施证书锁定 | ☐ |
| 9.10 | 不收集无关数据 | 对照隐私政策 | 实际收集范围 ≤ 政策声明范围 | ☐ |

---

## 十、应用市场元数据核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 10.1 | 应用截图 | 5 张以上，分辨率 1080×1920+ | 含首页、对话、记忆管理、设置等核心页 | ☐ |
| 10.2 | 应用介绍文案 | 100-500 字 | 描述应用功能、特色、目标用户 | ☐ |
| 10.3 | 应用分类 | AGC 控制台选择 | 选择最贴近的分类（如「工具」或「效率」） | ☐ |
| 10.4 | 内容分级 | ICS 内容分级问卷 | 完成问卷，获得分级标签 | ☐ |
| 10.5 | 年龄分级 | 根据内容 | 建议所有人（无暴力、无成人内容） | ☐ |
| 10.6 | 版权信息 | AGC 控制台填写 | 软件著作权或自主开发声明 | ☐ |
| 10.7 | 上架地区 | AGC 控制台选择 | 中国大陆（按需扩展海外） | ☐ |
| 10.8 | 价格策略 | AGC 控制台 | 免费（按商业模式调整） | ☐ |
| 10.9 | 隐私政策 URL | AGC 控制台填写 | 与 4.3 一致 | ☐ |
| 10.10 | 应用权限说明 | AGC 控制台填写 | 列出所有权限及用途 | ☐ |

---

## 十一、测试通过证明

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 11.1 | 单元测试 | DevEco Studio → ohosTest | 全部测试用例通过（含 ChunkBatcher / SimpleDataSource / MemoryViewHelper 等） | ☐ |
| 11.2 | UI 测试 | 真机走查全部页面 | 所有页面可正常渲染与交互 | ☐ |
| 11.3 | 兼容性测试 | 华为云真机测试服务 | 覆盖 ≥ 5 款主流机型 | ☐ |
| 11.4 | 安全测试 | 华为应用市场安全检测 | 自动扫描通过 | ☐ |
| 11.5 | 性能测试 | Profiler 实测 | 满足第八章指标 | ☐ |
| 11.6 | 长时间稳定性 | 真机运行 30 分钟 | 无崩溃、无内存泄漏 | ☐ |
| 11.7 | 弱网测试 | 模拟 2G/3G 网络 | 应用不崩溃，提示友好 | ☐ |
| 11.8 | 异常恢复测试 | 强杀后重启 | 状态恢复正常 | ☐ |

---

## 十二、构建产物核验

| # | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|--------|----------|----------|------|
| 12.1 | 构建命令 | `hvigorw assembleApp --mode release` | 成功输出 `.app` 包 | ☐ |
| 12.2 | HAP 文件签名 | `unzip -l *.hap` 含 `META-INF/CERTIFICATE.*` | 签名完整 | ☐ |
| 12.3 | 包大小 | `ls -lh *.hap` | ≤ 30MB（启用混淆） | ☐ |
| 12.4 | 版本号正确 | HAP 内 `app.json5` 的 versionCode/versionName | 与计划发布版本一致 | ☐ |
| 12.5 | 构建产物备份 | 归档到 `releases/vX.Y.Z/` | 含 HAP、APP、构建日志 | ☐ |
| 12.6 | 构建可重现 | 清理后重新构建 | hash 一致（可选） | ☐ |

---

## 十三、发布流程

### 13.1 上传到华为应用市场

1. 登录 AGC：https://developer.huawei.com/consumer/cn/agconnect/
2. 「HarmonyOS 应用」→「我的应用」→「Neurova」→「版本信息」→「新建版本」
3. 上传 HAP / APP 包
4. 填写版本说明（中英文）
5. 上传截图与介绍（第十章已准备）
6. 提交审核

### 13.2 审核周期

- 首次审核：3-5 个工作日
- 后续版本更新审核：1-3 个工作日
- 紧急修复可申请加急

### 13.3 审核结果处理

- **通过**：自动上架，进入「已上架」状态
- **拒绝**：查看拒绝原因 → 修复 → 重新提交
- 常见拒绝原因：
  - 隐私政策不合规
  - 权限说明不充分
  - 应用崩溃或核心功能不可用
  - 内容违规

### 13.4 上架后监控

- 7 日内密切关注崩溃日志（AGC → 质量 → 崩溃分析）
- 收集用户反馈与应用市场评论
- 监控日活、留存等核心指标
- 准备紧急修复版本（如有 P0 bug）

---

## 十四、回滚预案

| # | 检查项 | 通过标准 | 状态 |
|---|--------|----------|------|
| 14.1 | 上一稳定版本 HAP 已归档 | 可立即回滚 | ☐ |
| 14.2 | 回滚操作流程文档化 | AGC 控制台「版本回退」 | ☐ |
| 14.3 | 数据库 migration 兼容性 | 回滚后数据不丢失 | ☐ |
| 14.4 | 服务端 API 兼容性 | 旧版本 App 可继续访问新 API | ☐ |

---

## 发布签字

| 角色 | 姓名 | 日期 | 备注 |
|------|------|------|------|
| 开发负责人 | | | 完成全部检查项 |
| 测试负责人 | | | 测试通过证明 |
| 产品负责人 | | | 业务验收 |
| 运维负责人 | | | 上架执行 |

---

## 附录 A：常用命令速查

```bash
# 构建调试包
hvigorw assembleHap --mode debug

# 构建发布包
hvigorw assembleHap --mode release

# 构建 App 包（应用市场提交）
hvigorw assembleApp --mode release

# 安装到真机
hdc install <hap-path>

# 查看签名信息
unzip -p <hap-path> META-INF/CERTIFICATE.CER | keytool -printcert

# 运行单元测试
hvigorw ohosTest
```

## 附录 B：相关文档索引

- 设计文档：`docs/HARMONYOS_DESIGN.md`
- 隐私政策：`docs/HARMONYOS_PRIVACY_POLICY.md`
- 签名指南：`docs/HARMONYOS_SIGNING_GUIDE.md`
- 执行计划：`.trae/documents/harmonyos-rewrite-execution-plan.md`
- 项目说明：`AGENTS.md`

---

**文档版本**：v1.0
**适用版本**：NeurovaHarmony v1.0.0
**下次复核触发**：每次版本发布前
