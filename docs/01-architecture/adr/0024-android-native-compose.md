# ADR 0024: 安卓端由 Capacitor 壳转向原生 Compose 工程

- **Status**: Accepted
- **Date**: 2026-11-16
- **Decision Maker**: 无人值守实施批（承接《手机客户端设计方案》D1）

## Context

《手机客户端设计方案》（2026-11-15，§7 D1）裁定安卓端 = Vue3 + Capacitor
（`Mobile/android/`，M2/M3 已实施：对话双通道、知识/文件/任务/通知均接线真端点）。
该裁定的权重排序是「复用面最大、技能栈匹配」——在当时只有功能范围（§6.1）而无移动端
界面形态规划的前提下成立。

2026-11-16，《鸿蒙端界面布局规划》定稿（18 屏、星穹玻璃视觉、原生交互形态），
随即产出对齐鸿蒙版的《安卓端界面布局规划》（同一视觉基线、Material 3 承载、
WindowSizeClass 换轨、RenderEffect 玻璃导航、CameraX 扫码、Tabletop 半开姿态）。
该规划的**每一项体验落点都是 WebView 壳无法承载或承载不良的**：

| 规划落点 | Capacitor 壳承载面 | 原生 Compose 承载面 |
|---|---|---|
| 玻璃悬浮导航 + backdrop blur | DOM 模拟，无系统材质 | RenderEffect（API 31+）/ 后续窗口级 blur |
| WindowSizeClass 三档换轨（底栏/侧栏/双栏） | WebView 视口 media query，无 NavigationSuite | NavigationSuiteScaffold + ListDetailPaneScaffold 原生换轨 |
| 折叠姿态 Tabletop 上下分区 | WebView 无姿态事件 | androidx.window WindowInfoTracker |
| CameraX 一扫配全 + 相机权限流 | 插件桥接，多一层抽象 | 原生相机栈 |
| SSE/WS 弱网降级、手势条 edge-to-edge | 已实施（可用），体验受 WebView 限制 | 同协议原生实现（OkHttp） |

## Decision

1. 新建原生工程 `Mobile/android-native/`（Kotlin + Jetpack Compose + Material 3），
   按《安卓端界面布局规划》18 屏分期实施；协议层**零新建**——端点、配对三步、
   SSE/WS 事件映射、401 单飞续签全部对齐既有事实源（后端 `ENDPOINT_MODULES`
   与两端既有实现同源），不引入第二套协议口径。
2. **凭证存储按设计方案 §9.2 分仓**：JWT 与 device_secret 走 Android Keystore
   （EncryptedSharedPreferences），connect_ticket 仅内存；备份与设备迁移全量排除。
3. 命名与分层对齐鸿蒙端既有词汇（HttpChannel/WebSocketAdapter→MobileWsChannel/
   AuthStore/ServersStore/PairingStore），两端共享协议与状态机口径，不强行同构代码。

## 与 D1 的关系（偏离登记）

- 本 ADR **不推翻 D1 的两端结论**（鸿蒙 + 安卓），只更换安卓端的承载形态；
- D1 的四条理由中，「复用面最大」「技能栈匹配」在界面形态规划出现后权重下降——
  规划锁定的是**原生体验形态**，WebView 内无论怎么调都无法达标；
- 《手机客户端设计方案》§7 的形态选型表述待下一次文档批同步为「安卓端双轨：
  Capacitor（已实施功能基线）/ 原生 Compose（界面形态基线）」，收口时机见 Consequences。

## Consequences

- **短期双轨并存**（Capacitor 与 android-native），违反教义第 7 条「不许并存」的临时豁免：
  退役判据 = 原生端完成 §11 全部分期（M1-M4）并通过 live-verify 后，Capacitor 工程
  收口退役（`Mobile/android/` 归档、`Mobile/dist/android` 构建物切换）。退役属结构改动，
  需用户拍板后另批执行，本批不静默删除任何既有工程。（已拍板执行，见文末收口记录。）
- 首批实施范围（P1-P4）：工程骨架、星穹玻璃令牌主题（深/浅）、五 Tab 导航壳
  （NavigationSuiteScaffold）、F1 登录、F2 扫码配对（CameraX + 手动兜底）、
  网络层（HttpChannel/ChatSseChannel/MobileWsChannel/配对三端点/401 单飞续签）。
- 安卓端单元测试随 Gradle 模块放置（`app/src/test/kotlin/`），不进仓根 `tests/`
  ——与鸿蒙端 `ohosTest` 同一先例：平台工具链承载平台测试，仓根测试根服务 Python/TS 面。
- 工具链事实：本机 SDK 于 `D:\Android\Sdk`（环境变量未注册），模拟器 AVD `neurova35`
  （API 35 x86_64）；首次构建在 Gradle 8.14.3 + AGP 8.7.3 + compileSdk 35 下通过。

## 收口记录（2026-11-16）

退役判据已满足（原生端 P0–P9 全部落地并 live-verify，覆盖 §11 M1-M4 功能面），经用户拍板执行：

- 删除 `Mobile/android/`（Capacitor + Vue3 工程，125 个跟踪文件）与 `Mobile/dist/android/` 构建物；
  `Mobile/` 现役目录收敛为 `android-native/`（安卓）、`harmony/`（鸿蒙）、`signing/`、`dist/`（仅鸿蒙产物）。
- CORS 白名单随壳退役移除 Capacitor 专用 origin（裸 `http://localhost` / `https://localhost`，
  即 androidScheme=https 的 WebView 来源）——`neurova/api/cors_policy.py` 与 `config/cors.json`
  同批移除，单源等值判据 `testAllowSetsAreByteIdenticalToWhatTheRepoConfigShips` 继续咬合。
- 签名材料 `Mobile/signing/android-release.p12` 保留，原生工程 release 接线继续复用
  （包名 `top.neurova.mobile`）。
