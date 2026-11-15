# 移动端签名获取指南（鸿蒙 + 安卓）

> 归属：`docs/10-configuration/`（部署/配置事实源）。配合
> [`docs/04-plans/2026-11-15-Neurova手机客户端设计方案.md`](../04-plans/2026-11-15-Neurova手机客户端设计方案.md)
> 的 D1 裁定（两端：鸿蒙 + 安卓，构建物统一 `Mobile/`）。
> 本地材料清单（含指纹，无机密）：[`Mobile/signing/INFO.md`](../../../Mobile/signing/INFO.md)。

## 0. 现状速览（2026-11-15 已备）

| 材料 | 位置 | 状态 |
|---|---|---|
| 安卓发布密钥库 | `Mobile/signing/android-release.p12`（PKCS12，别名 `neurova-android-release`，RSA 2048，30 年） | ✅ 已生成（本机 keytool） |
| 鸿蒙发布密钥对 | `Mobile/signing/harmony-release.p12`（PKCS12，别名 `neurova-harmony-release`，RSA 2048，30 年） | ✅ 已生成（本机 keytool） |
| 鸿蒙 CSR | `Mobile/signing/harmony-release.csr`（PKCS#10） | ✅ 已生成，待上传 AGC |
| 密码 | `Mobile/signing/passwords.local.md` | ✅ 本机存放，**不入 git**（已 `.gitignore`） |
| 鸿蒙发布证书 `.cer` + Profile `.p7b` | 约定落 `Mobile/signing/harmony/` | ⬜ 需华为 AGC 办理（§2） |
| 安卓包名（applicationId） | — | ⬜ 待确认（建议 `com.neurova.app`） |

工具链现状：JDK 17（keytool）✅；Node 24 ✅；Android SDK 未安装（打包时需装）；
DevEco Studio 未安装（鸿蒙打包需装）。本指南的"生成密钥"部分不依赖后两者。

---

## 1. 安卓（Android）签名

### 1.1 已完成

`android-release.p12` 已用 JDK keytool 生成：RSA 2048 / SHA256withRSA / 有效期 30 年。
PKCS12 是 Android 官方当前推荐的密钥库格式，Gradle 可直接消费。

### 1.2 Gradle 接线（工程建成后）

在 `Mobile/android/` 的 `app/build.gradle`（或 `build.gradle.kts`）加 signingConfig：

```groovy
android {
    signingConfigs {
        release {
            storeFile file("../../signing/android-release.p12")   // 相对 app 模块指向 Mobile/signing/
            storePassword System.getenv("NEUROVA_ANDROID_STORE_PWD")
            keyAlias "neurova-android-release"
            keyPassword System.getenv("NEUROVA_ANDROID_STORE_PWD")
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.release
            minifyEnabled false
        }
    }
}
```

- 密码**不进代码库**：从环境变量（CI 上用 secret 注入 `NEUROVA_ANDROID_STORE_PWD`）或
  本机 `gradle.properties`（不入 git）读取。
- 验证：`./gradlew :app:signingReport` 应显示 release 配置命中 `neurova-android-release`。
- 打包：`./gradlew :app:assembleRelease`（APK）/ `bundleRelease`（AAB）。

### 1.3 渠道差异（如实说明）

- **国内应用市场**（华为/小米/OPPO/vivo 等）：直接用本 keystore 签名发布；**换签即换应用**，
  keystore 一旦启用就不可更换，务必备份 `android-release.p12` + 密码。
- **Google Play**：采用 Play App Signing——上传密钥（即本 keystore）只用于签上传包，
  应用签名密钥由 Google 托管；首次上传后可在 Play Console 重置上传密钥。
  两种渠道可共用本 keystore 作为上传/发布密钥。

### 1.4 指纹用途

`INFO.md` 里的 SHA256 指纹用于：应用市场后台登记、微信/地图等三方 SDK 的签名校验、
AGC 联调登记。修改 keystore 即指纹失效，三方登记要跟着重配。

---

## 2. 鸿蒙（HarmonyOS）签名

### 2.1 已完成（本地可做部分）

HarmonyOS 应用签名的本地材料 = **密钥对（.p12）+ CSR**，已用 keytool 生成完毕
（RSA 2048 是 AGC 支持的算法；CSR 为标准 PKCS#10，AGC 直接接受）。

### 2.2 需要华为侧办理的步骤（需开发者账号，本机无法代办）

1. **开发者账号**：注册华为开发者账号并完成实名认证（个人或企业；上架应用市场建议企业）。
2. **创建应用**：AppGallery Connect（现已并入 HarmonyOS 开发者中心）→ 创建 APP ID：
   - 包名（实际注册）：**`com.neurova.mobile`**（安卓侧登记 `com.neurova.app`；`harmony`/`ohos` 是 AGC 包名保留词，不可用）；
   - 应用类型选 App（HarmonyOS应用），分类"应用"，支持设备按需勾选。
3. **申请发布证书**：AGC → 证书、APP ID 与 Profile → 证书 → 新增证书 →
   上传 `Mobile/signing/harmony-release.csr` → 下载发布证书 **`.cer`**。
   （一个账号证书数量有限额，调试/发布各一张即可。）
   **格式坑（2026-11-15 实测三连）**：
   ① keytool 生成的 CSR 是 Java 风格 PEM 头 `-----BEGIN NEW CERTIFICATE REQUEST-----`，
   AGC 报"上传的CSR文件无效"——须 openssl 重写为标准头 `-----BEGIN CERTIFICATE REQUEST-----`；
   ② 标准 RSA CSR（2048/3072）**仍被拒**（错误码 205389875）——HarmonyOS 签名体系是
   **ECC（SHA256withECDSA，见 DevEco 签名手册 Sign alg 固定值）**，密钥须用
   `openssl ecparam -name prime256v1 -genkey` 生成 ECC P-256；
   ③ 包名保留词：`harmony`、`ohos` 均不可用于包名（AGC 建包名校验直接拒绝）。
   最终可用组合：**ECC P-256 + 标准 PEM 头 CSR + 包名 `com.neurova.mobile`**。
4. **申请 Profile**：同页 → Profile → 新增（发布 Profile，绑定第 2 步的包名）→
   下载 **`.p7b`**。
5. **材料归置**：`.cer` 与 `.p7b` 放 `Mobile/signing/harmony/`
   （这两个文件不含私钥，可提交；`.p12` 永远只在 `Mobile/signing/` 本地）。
6. **执行签名**（工程建成后任选其一）：
   - DevEco Studio：`File → Project Structure → Signing Configs` 配置
     （或直接填 `build-profile.json5`）；
   - 命令行 hap-sign-tool（DevEco 自带，也可独立使用）。

### 2.3 build-profile.json5 签名配置样例

```json5
{
  "app": {
    "signingConfigs": [
      {
        "name": "release",
        "type": "HarmonyOS",
        "material": {
          "certpath": "Mobile/signing/neurova-harmony-release.cer",
          "keyAlias": "neurova-harmony-release",
          "keyPassword": "0000...",   // 从本地环境变量/不入库文件取，不硬编码
          "profile": "Mobile/signing/neurova-release-profileRelease.p7b",
          "signAlg": "SHA256withECDSA",
          "storeFile": "Mobile/signing/harmony-release.p12",
          "storePassword": "0000..."
        }
      }
    ],
    "buildModeSet": [{ "name": "release" }]
  }
}
```

### 2.4 命令行构建与签名实录（2026-11-15，DevEco 26.0.0.865 / hvigor 6.26.9）

**工程结构要求（hvigor 6）**：工程根需有 `hvigor/hvigor-config.json5`（`modelVersion`）、
根 `package.json` 可选、`oh-package.json5`、`build-profile.json5`、`hvigorfile.ts`
（`import { appTasks } from '@ohos/hvigor-ohos-plugin'; export default { system: appTasks, plugins: [] }`）。
SDK 版本写法：hvigor 6 要求 `compatibleSdkVersion/compileSdkVersion/targetSdkVersion`
用 `'26.0.0'` 新格式（旧 `'6.1.0'` 报 00306042）。

**构建命令**（DevEco 自带 hvigor，无需 npm install）：

```
"D:/Program Files/Huawei/DevEco Studio/tools/hvigor/bin/hvigorw.bat" --mode module -p product=default -p buildMode=release assembleHap
```

- 工程路径**不得含非 ASCII 字符**（hvigor 6 校验 00306003，无绕过开关）——
  本仓路径含中文，实际构建在 ASCII 副本目录进行（`Mobile/dist/harmony/` 收产物）。
- 构建产物：`entry/build/default/outputs/default/entry-default-unsigned.hap`。

**签名命令**（hap-sign-tool，SDK toolchains 内）：

```
java -jar <SDK>/toolchains/lib/hap-sign-tool.jar sign-app -mode localSign \
  -inFile <unsigned.hap> -outFile <signed.hap> -inForm zip \
  -keystoreFile <p12> -keystorePwd <密码> -keyAlias neurova-harmony-release \
  -keyPwd <密码> -signAlg SHA256withECDSA -profileFile <p7b> -appCertFile <cer>
```

- 参数名为**全小写 keystoreFile/keystorePwd**（`-keyStoreFile` 大写 S 报 11011005 Param is not trusted）。
- **密码密文体系**：build-profile 的 storePassword/keyPassword 必须是 **≥32 位偶数长度的密文**
  （明文密码不可用），且 keystore 同目录需有 `material/{fd,ac,ce}` 三个材料目录
  （fd 内 3 个 16 字节文件、ac/ce 各 1 个）——hvigor 解密密文时校验。材料由
  `gen-harmony-material.cjs` 生成（含自洽验证）。
- 校验：`verify-app -inFile <signed.hap> -outCertChain <out.cer> -outProfile <out.p7b> -inForm zip`。

### 2.5 调试 vs 发布

| | 调试（debug） | 发布（release） |
|---|---|---|
| 证书 | AGC 调试证书（同样由 CSR 换发） | AGC 发布证书 |
| Profile | 调试 Profile（可绑手工登记的设备 UDID） | 发布 Profile（不绑设备） |
| 用途 | 真机联调 | 上架/分发 |

调试证书可用同一份 CSR 再换一张；流程同 §2.2 第 3–4 步，选"调试"类型。

---

## 3. 安全纪律（与仓库红线对齐）

- 私钥文件（`*.p12`/`*.jks`）与密码（`passwords.local.md`）**永不入库**——
  `.gitignore` 已钉住；提交前 `git status` 确认它们不出现在待提交清单。
- 密码请从 `passwords.local.md` 转存到你的密码管理器；该文件本身只作本机过渡。
- keystore 丢失/泄露的后果：安卓换签=应用市场视为新应用；鸿蒙证书由 AGC 吊销重发，
  但已分发版本不可补签。**先备份再使用**。
- CSR（`.csr`）与 AGC 下发的 `.cer`/`.p7b` 不含私钥，可以入库留存。

## 4. 待办清单（2026-11-15 办理结果）

- [x] 包名已确认：**安卓 `com.neurova.app`**（建议值，工程创建时登记）；**鸿蒙 `com.neurova.mobile`**
      （`harmony`/`ohos` 均为 AGC 包名保留词，不可用——实测被拒）
- [x] 华为 AGC：应用 **Neurova / APP ID 6917621864918782165** 已创建；
      CSR 上传后发布证书已签发（**ECC P-256**，见 §2.2 格式坑）；
      发布 Profile `neurova-release-profile` 已创建
- [x] `.cer`（`neurova-harmony-release.cer`，含 3 级证书链）与 `.p7b`
      （`neurova-release-profileRelease.p7b`）已归置 `Mobile/signing/`（不入 git）
- [ ] 密码转存密码管理器（当前在本机 `Mobile/signing/passwords.local.md`，已 gitignore）
- [ ] 工程建成后：Gradle signingConfig / build-profile.json5 接线（§1.2 / §2.3），
      密码走环境变量或本地不入库文件
