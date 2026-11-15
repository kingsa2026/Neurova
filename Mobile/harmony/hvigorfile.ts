// 鸿蒙工程构建脚本 - HarmonyOS 6.1 (API 13)
//
// 签名材料不写在本文件（本文件入库，密码不得入库）：
// 命令行构建前由构建脚本把 `Mobile/signing/` 的证书/Profile/密码
// 注入 build-profile.json5 的 signingConfigs（见 Mobile/signing/INFO.md），
// 构建完成后还原为空配置。密码本体只存在于本机 `passwords.local.md`（已 gitignore）。
import { appTasks } from '@ohos/hvigor-ohos-plugin';

export default {
    system: appTasks,
    plugins: []
};
