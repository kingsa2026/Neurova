fn main() {
  tauri_build::build();
  inject_boot_icon_env();
}

/// boot 页品牌 LOGO：编译期读取并 base64 注入环境变量（boot 页必须零外部
/// 资产依赖，dist 缺文件时 boot 窗白屏——白屏回归的根因）。取安装器同款
/// 白色 LOGO NEUROVA-LOGO350white.png（2026-09-21 用户要求 boot 页与安装器
/// 共用「我提供给你的白色 LOGO」；09-11 曾误用纯文字字标 WORDMARK——无图标，
/// 与欢迎页/进度页/侧边栏三处构图不一致），回退 NEUROVA-white.png / 打包
/// icons/128x128.png。
fn inject_boot_icon_env() {
  use std::path::PathBuf;

  let candidates = [
    PathBuf::from("../public/img/NEUROVA-LOGO350white.png"),
    PathBuf::from("../public/img/NEUROVA-white.png"),
    PathBuf::from("icons/128x128.png"),
  ];
  let icon = candidates
    .iter()
    .find(|p| p.exists())
    .expect("boot 页品牌图标缺失：public/img/neurova-icon.png 与 icons/128x128.png 均不存在");
  println!("cargo:rerun-if-changed={}", icon.display());
  println!("cargo:rerun-if-changed=src/boot_page.html");

  let bytes = std::fs::read(icon).expect("读取 boot 页品牌字标失败");
  let b64 = base64_encode(&bytes);
  println!("cargo:rustc-env=NEUROVA_WORDMARK_B64={b64}");
}

/// 最小 base64（标准字母表 + padding），避免引入构建依赖。
fn base64_encode(data: &[u8]) -> String {
  const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
  for chunk in data.chunks(3) {
    let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
    let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
    out.push(TABLE[(n >> 18) as usize & 63] as char);
    out.push(TABLE[(n >> 12) as usize & 63] as char);
    out.push(if chunk.len() > 1 { TABLE[(n >> 6) as usize & 63] as char } else { '=' });
    out.push(if chunk.len() > 2 { TABLE[n as usize & 63] as char } else { '=' });
  }
  out
}
