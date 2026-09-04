fn main() {
  tauri_build::build();
  inject_boot_icon_env();
}

/// boot 页品牌图标：编译期读取并 base64 注入环境变量（boot 页必须零外部
/// 资产依赖，dist 缺文件时 boot 窗白屏——白屏回归的根因）。图标优先取
/// public/img/neurova-icon.png，缺失回退打包 icons/128x128.png。
fn inject_boot_icon_env() {
  use std::path::PathBuf;

  let candidates = [
    PathBuf::from("../public/img/neurova-icon.png"),
    PathBuf::from("icons/128x128.png"),
  ];
  let icon = candidates
    .iter()
    .find(|p| p.exists())
    .expect("boot 页品牌图标缺失：public/img/neurova-icon.png 与 icons/128x128.png 均不存在");
  println!("cargo:rerun-if-changed={}", icon.display());
  println!("cargo:rerun-if-changed=src/boot_page.html");

  let bytes = std::fs::read(icon).expect("读取 boot 页品牌图标失败");
  let b64 = base64_encode(&bytes);
  println!("cargo:rustc-env=NEUROVA_ICON_B64={b64}");
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
