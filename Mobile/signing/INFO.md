# Mobile 签名材料清单（不含任何机密，可提交）

> 机密文件（`*.p12` / 密码）不进 git：`passwords.local.md` 与两份 `.p12` 已被 `.gitignore` 覆盖。
> 密码只存在于本机 `passwords.local.md`，请转存到你的密码管理器。

创建日期：2026-11-15 · 工具：keytool（JDK 17，Microsoft OpenJDK）· 算法统一 RSA 2048 / SHA256withRSA / 有效期 10950 天（30 年）

## 安卓（Android release）

| 项 | 值 |
|---|---|
| 密钥库 | `Mobile/signing/android-release.p12`（PKCS12） |
| 别名 | `neurova-android-release` |
| 主题 | CN=Neurova Android Release, OU=Neurova, O=Neurova, L=Shanghai, ST=Shanghai, C=CN |
| 证书 SHA256 指纹 | `02:DD:40:10:33:BA:72:22:E3:0B:11:7D:72:45:60:ED:B6:59:93:93:5E:A9:05:22:FE:5D:88:7F:30:D0:88:56` |

用途：Gradle `signingConfig`（release 打包 APK/AAB）。应用市场/AGC 联录用上表 SHA256 指纹。

## 鸿蒙（HarmonyOS release，密钥对 + CSR 已备）

| 项 | 值 |
|---|---|
| 密钥库 | `Mobile/signing/harmony-release.p12`（PKCS12，openssl 生成） |
| 别名 | `neurova-harmony-release` |
| 主题 | C=CN, ST=Shanghai, L=Shanghai, O=Neurova, OU=Neurova, CN=Neurova Harmony Release |
| 密钥算法 | **ECC P-256（prime256v1）**，签名 SHA256withECDSA |
| 密钥对公钥 SHA256 指纹 | `D3:70:28:A8:06:EA:3F:75:5B:5A:BB:DD:5B:20:FF:9A:B6:45:93:6F:05:76:9C:13:69:56:D3:75:01:16:2C:BD` |
| CSR | `Mobile/signing/harmony-release.csr`（PKCS#10 标准 PEM 头，可提交 AGC，不含机密） |
| 发布证书 | `Mobile/signing/neurova-harmony-release.cer`（**3 张证书链**：叶子 CN=冯霏(2084200282144650689),Release → 华为 Developer Relations CA G2 → Huawei CBG Root CA G2；叶子公钥与 CSR 一致，已验证；有效期 2026-11-15 → 2029-11-15） |

> 生成记录：2026-11-15 三次迭代——① keytool RSA 2048（Java 风格 CSR 头被拒）；
> ② openssl RSA 2048 标准 CSR（服务端仍拒，错误码 205389875）；③ 依据 DevEco 签名手册
> （Sign alg 固定 SHA256withECDSA）改用 **ECC P-256** 全套重生成。**以本表现指纹为准**。

用途：把 CSR 上传 AppGallery Connect 换取发布证书（`.cer`）与 Profile（`.p7b`）后，
连同本 `.p12` 一起交给 DevEco Studio / hap-sign-tool 签 HAP。
**注意**：AGC 侧最终校验的"证书指纹"以 AGC 下发的 `.cer` 为准（与本表公钥指纹同源）。

## 命令行打包实录（2026-11-15，hvigor 6.26.9 + hap-sign-tool）

**安卓**（Capacitor 工程 `Mobile/android/android/`，JDK 21 + AGP 8.13）：
- `./gradlew assembleDebug` → `app-debug.apk`（4.1MB）✓
- `./gradlew assembleRelease` → `app-release.apk`（3.1MB，签名者 CN=Neurova Android Release，SHA-256 与上表一致，apksigner 验证）✓
- 产物归档：`Mobile/dist/android/`

**鸿蒙**（NeurovaHarmony 工程，经 ASCII 副本目录构建——hvigor 6 拒绝中文工程路径）：
- 构建：`hvigorw.bat --mode module -p product=default -p buildMode=release assembleHap`
  → `entry-default-unsigned.hap`（88KB）✓
- 签名：`java -jar hap-sign-tool.jar sign-app -mode localSign -inFile <unsigned> -outFile <signed>
  -inForm zip -keystoreFile <p12> -keystorePwd <密码> -keyAlias neurova-harmony-release
  -keyPwd <密码> -signAlg SHA256withECDSA -profileFile <p7b> -appCertFile <cer>`
  → `entry-default-signed.hap`（125KB）✓（注意参数为 `-keystoreFile/-keystorePwd` 全小写 s）
- 校验：`verify-app` 从签名 HAP 提取出证书链与 Profile ✓
- 产物归档：`Mobile/dist/harmony/`
- 签名密码密文：build-profile 的 storePassword/keyPassword = `passwords.local.md` 的
  `harmony_release_store_password_cipher`（hex）；解密需 `material/{fd,ac,ce}` 三目录
  （fd 含 3 个 16 字节文件、ac/ce 各 1 个；由 `gen-harmony-material.cjs` 生成）

## AGC 办理记录（2026-11-15 已完成）

| 项 | 值 |
|---|---|
| 华为开发者账号 | 已登录并实名认证（凭据在 `passwords.local.md`，不入 git） |
| 应用名称 / APP ID | Neurova / `6917621864918782165` |
| **鸿蒙包名（实际）** | **`com.neurova.mobile`**（`com.neurova.app.harmony`/`...ohos` 因含华为保留词 harmony/ohos 被拒） |
| 发布证书 | 已签发生效（2026-11-15 → 2029-11-15），证书链见上表，文件 `neurova-harmony-release.cer` |
| 发布 Profile | `neurova-release-profile` 已创建生效（2026-11-15 → 2029-11-15），**`.p7b` 已下载归置：`Mobile/signing/neurova-release-profileRelease.p7b`**（PKCS7 含华为根 CA 与 HOS Profile Management 签发链，已验证） |

## 历史待办（已完成项存档）

- [x] 包名：安卓 `com.neurova.app`（建议值，待安卓工程创建时登记）；鸿蒙实际注册为 `com.neurova.mobile`
- [x] 华为 AGC：创建应用 + 上传 CSR + 签发发布证书 + 创建发布 Profile + 下载 `.cer`/`.p7b`
- [x] `.cer`/`.p7b` 归置 `Mobile/signing/`（git 已忽略，规则 `Mobile/signing/*.cer|*.p7b`）
- [ ] 密码转存密码管理器
- [ ] 工程建成后：Gradle signingConfig / build-profile.json5 接线（§1.2 / §2.3）
