# Neurova 鸿蒙应用签名配置指南

> 文档路径：`docs/HARMONYOS_SIGNING_GUIDE.md`
> 适用范围：NeurovaHarmony 鸿蒙 App（HarmonyOS 6.1 / API 13）
> 当前状态：`build-profile.json5` 中 `signingConfigs` 为空数组，需开发者按本指南完成配置后方可发布到华为应用市场。
> 更新日期：2026-06-25

---

## 目录

1. [签名类型与适用场景](#1-签名类型与适用场景)
2. [前置准备](#2-前置准备)
3. [调试签名配置（自动生成）](#3-调试签名配置自动生成)
4. [发布签名配置（手动申请）](#4-发布签名配置手动申请)
5. [build-profile.json5 配置示例](#5-build-profilejson5-配置示例)
6. [DevEco Studio GUI 配置流程](#6-deveco-studio-gui-配置流程)
7. [签名验证](#7-签名验证)
8. [常见问题排查](#8-常见问题排查)
9. [安全注意事项](#9-安全注意事项)

---

## 1. 签名类型与适用场景

HarmonyOS 应用签名分两类，必须区分使用：

| 类型 | 用途 | 证书来源 | 是否可发布应用市场 |
|------|------|----------|--------------------|
| **调试签名** | 真机调试、本地运行 | DevEco Studio 自动生成 | ❌ 不可 |
| **发布签名** | 上架华为应用市场、企业内测分发 | 华为开发者联盟申请 | ✅ 可以 |

> ⚠️ 禁止使用调试签名上传应用市场，会被审核拒绝。

---

## 2. 前置准备

### 2.1 账号与工具

- **华为开发者账号**：已实名认证的个人或企业账号（企业账号发布应用市场必备）
  - 注册地址：https://developer.huawei.com/consumer/cn/
- **DevEco Studio**：版本 ≥ 6.1（与 SDK 13 匹配）
- **Keytool**：JDK 自带（位于 `$JAVA_HOME/bin/keytool`，DevEco Studio 内置 JDK 已含）

### 2.2 应用基础信息

确认以下信息已配置（见 `entry/src/main/module.json5` 与 `AppScope/app.json5`）：

- **bundleName**：`com.neurova.app`（示例，需在华为开发者联盟注册时保持一致）
- **versionCode**：整数递增（如 `1`）
- **versionName**：版本显示名（如 `1.0.0`）

### 2.3 文件目录约定

建议在项目根目录创建（**不提交到 git**）：

```
NeurovaHarmony/
├── signing/                     # 签名文件目录（加入 .gitignore）
│   ├── neurova-release.p12      # 发布密钥库
│   ├── neurova-release.csr     # 证书请求文件（申请后可保留备份）
│   ├── neurova-release.cer     # 发布证书（华为签发）
│   └── neurova-profile.p7b     # Profile 文件（华为签发）
└── .gitignore                   # 追加 signing/*.p12 / signing/*.p7b / signing/*.cer
```

---

## 3. 调试签名配置（自动生成）

DevEco Studio 在首次运行到真机/模拟器时会自动生成调试签名，**无需手动操作**。

### 自动生成路径

- Windows：`C:\Users\<用户名>\.ohos\config\default_ohos_debug.p12`
- macOS：`~/.ohos/config/default_ohos_debug.p12`
- 密码：默认空（自动管理）

### 验证调试签名生效

1. 连接鸿蒙真机或启动模拟器
2. 点击 DevEco Studio 顶部 ▶ 运行按钮
3. 控制台输出 `Successfully signed the hap` 即表示调试签名已配置

> 调试签名仅用于本地开发，**不要**写入 `build-profile.json5` 的 `signingConfigs`。

---

## 4. 发布签名配置（手动申请）

### 4.1 步骤一：生成密钥库（.p12）

打开终端，执行：

```bash
keytool -genkeypair \
  -alias neurova-key \
  -keyalg EC \
  -keysize 256 \
  -sigalg SHA256withECDSA \
  -validity 9125 \
  -keystore neurova-release.p12 \
  -storetype PKCS12 \
  -storepass <你的密钥库密码> \
  -keypass <你的密钥密码> \
  -dname "CN=Neurova, OU=Dev, O=Neurova, L=Beijing, ST=Beijing, C=CN"
```

**参数说明**：

- `-alias`：密钥别名，后续申请证书与配置都用此别名
- `-keyalg EC`：使用 EC（椭圆曲线）密钥对，配合 `SHA256withECDSA` 签名算法（鸿蒙推荐）
- `-keysize 256`：256 位 EC 密钥，安全强度等同 3072 位 RSA，性能更优
- `-sigalg SHA256withECDSA`：签名算法，与第 5 章 `build-profile.json5` 中 `signAlg` 必须一致
- `-validity 9125`：25 年有效期（鸿蒙要求 ≥ 25 年）
- `-dname`：颁发者信息，按企业真实信息填写

> ⚠️ **算法一致性**：`-keyalg`、`-sigalg` 与 `build-profile.json5` 中 `material.signAlg` 三者必须匹配。
> 若使用 `-keyalg RSA`，则 `signAlg` 必须改为 `SHA256withRSA`；EC 密钥不可与 RSA 签名算法混用，反之亦然。

**输出**：`neurova-release.p12` 文件，**妥善备份**，丢失后无法更新应用。

### 4.2 步骤二：生成证书请求文件（CSR）

```bash
keytool -certreq \
  -alias neurova-key \
  -keystore neurova-release.p12 \
  -storepass <你的密钥库密码> \
  -file neurova-release.csr
```

**输出**：`neurova-release.csr`，用于提交给华为申请发布证书。

### 4.3 步骤三：华为开发者联盟申请发布证书

1. 登录华为开发者联盟：https://developer.huawei.com/consumer/cn/agconnect/
2. 进入「用户与访问」→「证书管理」→「新建证书」
3. 上传 `neurova-release.csr`
4. 选择证书类型为「发布证书」
5. 下载生成的 `.cer` 文件，重命名为 `neurova-release.cer`

### 4.4 步骤四：创建 Profile 文件

1. 在 AGC 控制台进入「HarmonyOS 应用」→「Profile 管理」→「新建 Profile」
2. 选择应用：Neurova（需先在 AGC 创建应用并填写 bundleName）
3. 选择证书：上传 `neurova-release.cer`
4. 选择设备类型：phone / tablet / 2in1（与 `module.json5` 中 `deviceTypes` 一致）
5. 下载 Profile 文件，重命名为 `neurova-profile.p7b`

---

## 5. build-profile.json5 配置示例

编辑 `NeurovaHarmony/build-profile.json5`，将空 `signingConfigs` 替换为：

```json5
{
  "app": {
    "signingConfigs": [
      {
        "name": "default",
        "type": "HarmonyOS",
        "material": {
          "certpath": "signing/neurova-release.cer",
          "storePassword": "<加密后的密钥库密码>",
          "keyAlias": "neurova-key",
          "keyPassword": "<加密后的密钥密码>",
          "profile": "signing/neurova-profile.p7b",
          "signAlg": "SHA256withECDSA",
          "storeFile": "signing/neurova-release.p12"
        }
      }
    ],
    "products": [
      {
        "name": "default",
        "signingConfig": "default",
        "compatibleSdkVersion": "6.1.0",
        "compileSdkVersion": "6.1.0",
        "targetSdkVersion": "6.1.0",
        "runtimeOS": "HarmonyOS"
      }
    ],
    "buildModeSet": [
      { "name": "debug" },
      { "name": "release" }
    ]
  },
  "modules": [
    {
      "name": "entry",
      "srcPath": "./entry",
      "targets": [
        {
          "name": "default",
          "applyToProducts": ["default"]
        }
      ]
    }
  ]
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| `name` | 签名配置名，需与 `products[].signingConfig` 对应 |
| `type` | 系统类型，固定 `HarmonyOS` |
| `material.certpath` | 发布证书 `.cer` 相对路径 |
| `material.storeFile` | 密钥库 `.p12` 相对路径 |
| `material.storePassword` | 密钥库密码（DevEco Studio 会自动加密存储） |
| `material.keyAlias` | 密钥别名，对应步骤 4.1 的 `-alias` |
| `material.keyPassword` | 密钥密码 |
| `material.profile` | Profile 文件 `.p7b` 相对路径 |
| `material.signAlg` | 签名算法，推荐 `SHA256withECDSA` |

> 💡 **建议**：使用 DevEco Studio GUI 配置，密码会自动加密；直接编辑 JSON 时密码为明文，仅本地使用，**勿提交 git**。

---

## 6. DevEco Studio GUI 配置流程

### 6.1 打开 Project Structure

菜单栏：`File` → `Project Structure` → `Signing Configs` → `HarmonyOS`

### 6.2 勾选 Automatically generate signature（仅调试用）

- 调试签名：勾选此项即可，DevEco Studio 自动管理
- **发布签名：取消勾选**，手动填入

### 6.3 填写发布签名

| 字段 | 填写内容 |
|------|----------|
| Signing Type | `HarmonyOS` |
| Store File | 选择 `signing/neurova-release.p12` |
| Store Password | 步骤 4.1 中设置的密钥库密码 |
| Key Alias | `neurova-key` |
| Key Password | 步骤 4.1 中设置的密钥密码 |
| Sign Alg | `SHA256withECDSA` |
| Profile File | 选择 `signing/neurova-profile.p7b` |
| Certpath File | 选择 `signing/neurova-release.cer` |

### 6.4 应用配置

点击 `Apply` → `OK`，DevEco Studio 会自动写入 `build-profile.json5` 并加密密码。

---

## 7. 签名验证

### 7.1 编译验证

```bash
# 在项目根目录执行
hvigorw assembleHap --mode release
```

成功输出：

```
> Task :entry:signHap
Successfully signed the hap: build/outputs/default/neurova-default-signed.hap
```

### 7.2 解析 hap 验证签名

```bash
# 解压 hap（hap 即 zip）
unzip neurova-default-signed.hap -d hap-extracted/

# 检查签名文件
ls hap-extracted/META-INF/
# 应包含：CERTIFICATE.CER、CERTIFICATE.EC、CERTIFICATE.SF、MANIFEST.MF
```

### 7.3 真机安装验证

```bash
hdc install neurova-default-signed.hap
# 输出：AppBundle: processing 1 file...
#       successfully installed hap.
```

---

## 8. 常见问题排查

### Q1：`signHap` 任务失败，提示 `Keystore was tampered with, or password was incorrect`

- **原因**：`storePassword` 或 `keyPassword` 错误
- **解决**：重新生成密钥库或重新输入密码；密码中含特殊字符（`$`、`\`）需转义

### Q2：`Certificate not yet valid` 或 `Certificate expired`

- **原因**：证书有效期未覆盖当前时间，或 `validity` < 25 年
- **解决**：重新生成密钥库，`-validity 9125`（25 年）

### Q3：`Profile does not match the bundle name`

- **原因**：AGC 中创建 Profile 时填写的 bundleName 与 `AppScope/app.json5` 中不一致
- **解决**：核对 `app.bundleName`，在 AGC 中重新生成 Profile

### Q4：`The profile is expired`

- **原因**：Profile 文件过期（默认有效期 1 年）
- **解决**：登录 AGC 重新生成 Profile 并下载

### Q5：上传应用市场提示「签名算法不合规」

- **原因 1**：使用了已废弃的 `SHA1withRSA`
- **解决 1**：改为 `SHA256withECDSA`（推荐）或 `SHA256withRSA`
- **原因 2**：`keytool -keyalg` 与 `signAlg` 不匹配（如 `-keyalg RSA` 配 `SHA256withECDSA`）
- **解决 2**：核对三者一致性：
  - EC 密钥：`-keyalg EC -sigalg SHA256withECDSA` → `signAlg: SHA256withECDSA`
  - RSA 密钥：`-keyalg RSA -sigalg SHA256withRSA` → `signAlg: SHA256withRSA`
- **原因 3**：密钥长度不足（如 RSA < 2048 或 EC < 256）
- **解决 3**：EC 用 `-keysize 256`，RSA 用 `-keysize 3072` 或 `4096`

### Q6：`hvigorw` 命令找不到

- **原因**：未通过 DevEco Studio 打开项目，或未配置环境变量
- **解决**：在 DevEco Studio 的 Terminal 中执行，或手动 `cd` 到项目根目录后调用 `<DevEco 安装目录>/tools/hvigor/bin/hvigorw`

---

## 9. 安全注意事项

1. **密钥库文件（.p12）禁止提交 git**：
   - 在 `NeurovaHarmony/.gitignore` 中追加：
     ```
     signing/
     *.p12
     *.p7b
     *.cer
     *.csr
     ```
2. **密码不入仓库**：`storePassword` 与 `keyPassword` 应通过 DevEco Studio 加密存储，或使用环境变量注入
3. **密钥库备份**：将 `neurova-release.p12` 加密备份到至少两个物理介质（U盘 + 加密硬盘），**丢失后无法继续更新应用**
4. **证书吊销**：若密钥泄露，立即在 AGC 控制台吊销证书并重新申请
5. **服务器禁止存储**：根据用户规则，签名文件不放置在服务器（192.168.10.132），仅在本地开发机配置

---

## 10. 当前项目状态

- `NeurovaHarmony/build-profile.json5` 中 `signingConfigs` 为空数组 `[]`
- `NeurovaHarmony/.gitignore` 需追加签名文件忽略规则（见 9.1）
- 完成本指南全部步骤后，执行 M5.3.3 上架检查清单

---

**文档版本**：v1.0
**作者**：Neurova 项目组
**下次更新触发**：DevEco Studio 升级或鸿蒙 API 版本变更时复核
