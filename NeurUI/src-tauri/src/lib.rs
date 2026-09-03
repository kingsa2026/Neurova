//! Neurova 桌面壳（补课清单 P3-a Phase 1：最小壳）
//!
//! 职责：
//! 1. 启动时拉起 Python 后端（start_server.py，依赖解释器已装于本机 venv）
//! 2. 轮询 /health 等待后端就绪（超时不杀进程——窗口仍打开，用户可看后端日志排查）
//! 3. 应用退出时优雅终止后端子进程
//!
//! 诚实边界（Phase 1）：不捆绑 Python 运行时与依赖——要求本机已有
//! `.venv`（仓库根）。后续 Phase 3 再决定"轻壳+首启下载"或"全量打包"。

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

struct BackendChild(Mutex<Option<Child>>);

/// 仓库根 = src-tauri 的上两级（NeurUI/src-tauri → Neurova）。仅 dev 回退用。
fn repo_root() -> std::path::PathBuf {
    let manifest = env!("CARGO_MANIFEST_DIR");
    std::path::Path::new(manifest)
        .parent() // NeurUI
        .and_then(|p| p.parent()) // Neurova
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::path::PathBuf::from("."))
}

/// 去掉 Windows verbatim 前缀（\\?\）：打包态 resource_dir() 返回 verbatim
/// 路径，作为子进程 CWD 会让 Python 的 os.getcwd() 也带前缀，与源码里的
/// 相对路径成分（..\..\agent_workspaces）拼接触发 WinError 123 启动即崩。
fn normalize_windows_path(p: std::path::PathBuf) -> std::path::PathBuf {
    let s = p.as_os_str().to_string_lossy();
    if let Some(rest) = s.strip_prefix(r"\\?\UNC\") {
        return std::path::PathBuf::from(format!(r"\\{}", rest));
    }
    if let Some(rest) = s.strip_prefix(r"\\?\") {
        return std::path::PathBuf::from(rest.to_string());
    }
    p
}

/// 后端根解析（补课 P3-a 路线 A 全量打包）：
/// 1) 打包态：resource_dir()/backend（python/ neurova/ models/ config/ start_server.py）
/// 2) 开发态回退：仓库根 + .venv
fn resolve_backend_root(app: &tauri::AppHandle) -> std::path::PathBuf {
    use tauri::Manager;
    if let Ok(rd) = app.path().resource_dir() {
        let bundled = rd.join("backend");
        if bundled.join("start_server.py").exists() && bundled.join("python/python.exe").exists() {
            return normalize_windows_path(bundled);
        }
    }
    normalize_windows_path(repo_root())
}

fn is_bundled(root: &std::path::Path) -> bool {
    root.join("python/python.exe").exists()
}

fn spawn_backend(root: &std::path::Path) -> Result<Child, String> {
    let bundled = is_bundled(root);
    let python = if bundled {
        root.join("python/python.exe")
    } else {
        root.join(".venv/Scripts/python.exe")
    };
    if !python.exists() {
        return Err(format!("后端解释器不存在: {}", python.display()));
    }
    let server = root.join("start_server.py");
    if !server.exists() {
        return Err(format!("后端入口不存在: {}", server.display()));
    }

    let mut cmd = Command::new(&python);
    cmd.arg(&server).current_dir(root);
    // 强制 Python 全程 UTF-8：stdout/stderr 重定向到文件时默认用系统 ANSI
    // 代码页（中文 Windows = GBK），boot 进度窗按 UTF-8 读会乱码。
    // PYTHONUTF8=1（PEP 540）+ PYTHONIOENCODING 双保险，dev/打包都生效。
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    if bundled {
        // 打包态：PYTHONPATH 指向后端根（neurova 包）；CORS 放行 Tauri WebView origin
        // （Windows 默认 origin=http://tauri.localhost；macOS/Linux 为 tauri://localhost）
        cmd.env(
            "PYTHONPATH",
            std::env::join_paths([root.to_path_buf()]).unwrap(),
        );
        cmd.env(
            "NEUROVA_CORS_ORIGINS",
            "http://tauri.localhost,tauri://localhost,http://127.0.0.1:8100",
        );
    }
    // 后端输出进文件：崩溃/导入错误/启动日志可追溯（此前 Stdio::null 吞掉
    // 全部输出，装机现场后端起不来自查无门）。backend.log 位于安装目录，
    // icacls 已授 Users 组修改权，普通用户可写；打开失败则退回 null。
    // 旧日志轮换：历史版本以 GBK 写过，按 UTF-8 读会乱码 → 移为 .gbk.bak
    // （供需要时人工查证），新日志从干净 UTF-8 开始。
    let log_path = root.join("backend.log");
    if log_path.exists() {
        let raw = std::fs::read(&log_path).unwrap_or_default();
        let is_utf8 = String::from_utf8(raw).is_ok();
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let backup = root.join(format!("backend.{stamp}.log.bak"));
        let _ = std::fs::rename(&log_path, &backup);
        if !is_utf8 {
            log::info!("backend.log 非UTF-8（旧版GBK），已轮换为 {}", backup.display());
        }
    }
    let backend_log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .ok();
    let stdout = backend_log
        .as_ref()
        .and_then(|f| f.try_clone().ok())
        .map(Stdio::from)
        .unwrap_or(Stdio::null());
    let stderr = backend_log.map(Stdio::from).unwrap_or(Stdio::null());

    // Windows 打包态不弹后端控制台窗口（python.exe 是控制台程序，默认自带
    // 窗口且随服务常驻）。CREATE_NO_WINDOW 抑制窗口但不影响管道重定向。
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }

    cmd.stdout(stdout).stderr(stderr).spawn().map_err(|e| format!("后端进程启动失败: {e}"))
}

/// 轮询 /health 直到就绪（日志增量由 boot 页经 boot_tail 命令拉取）。
fn wait_backend_ready(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(2)).build();
    while Instant::now() < deadline {
        if let Ok(resp) = agent.get("http://127.0.0.1:9527/health").call() {
            if resp.status() == 200 {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

/// 读 backend.log 自 offset 起的增量（拉模式：boot 页定时 invoke boot_tail）。
/// 返回 (新行列表, 新 offset)。
fn read_log_increment(log_path: &std::path::Path, offset: u64) -> (Vec<String>, u64) {
    use std::io::{Read, Seek, SeekFrom};
    let Ok(meta) = std::fs::metadata(log_path) else { return (vec![], offset) };
    let len = meta.len();
    if len <= offset { return (vec![], offset); }
    let mut file = match std::fs::File::open(log_path) { Ok(f) => f, Err(_) => return (vec![], offset) };
    if file.seek(SeekFrom::Start(offset)).is_err() { return (vec![], offset); }
    let take = (len - offset).min(128 * 1024) as usize;
    let mut buf = vec![0u8; take];
    let Ok(n) = file.read(&mut buf) else { return (vec![], offset) };
    let text = String::from_utf8_lossy(&buf[..n]);
    let lines: Vec<String> = text.lines().map(|s| s.chars().take(500).collect()).collect();
    (lines, offset + n as u64)
}

/// boot 页拉模式数据源：日志增量（按前端上报的 offset）+ 后端进程状态。
#[tauri::command]
fn boot_tail(state: tauri::State<BackendChild>, log_offset: u64) -> serde_json::Value {
    let backend_root = BOOT_LOG_PATH.lock().unwrap().clone();
    let (lines, next_offset) = match &backend_root {
        Some(p) => read_log_increment(p, log_offset),
        None => (vec![], log_offset),
    };
    let backend = {
        let mut guard = state.0.lock().unwrap();
        match guard.as_mut() {
            Some(child) => match child.try_wait() {
                Ok(Some(status)) => format!("exited: {status}"),
                Ok(None) => "running".into(),
                Err(e) => format!("error: {e}"),
            },
            None => "not started".into(),
        }
    };
    serde_json::json!({ "lines": lines, "offset": next_offset, "backend": backend })
}

/// backend.log 绝对路径（spawn 成功后登记，boot_tail 拉取用）
static BOOT_LOG_PATH: Mutex<Option<std::path::PathBuf>> = Mutex::new(None);

/// 就绪/失败后收尾：亮主窗（boot 页轮询到 backend 状态变化会自行放完动画自关；
/// 壳侧延迟兜底关一次，幂等）。
fn finish_boot(handle: &tauri::AppHandle, ok: bool, msg: &str) {
    log::info!("boot finish: ok={ok} msg={msg}");
    std::thread::sleep(Duration::from_millis(if ok { 900 } else { 3000 }));
    if let Some(w) = handle.get_webview_window("boot") {
        let _ = w.close();
    }
    if let Some(m) = handle.get_webview_window("main") {
        let _ = m.show();
        let _ = m.set_focus();
    }
}

/// 启动进度窗：380x460 无边框小窗，加载打包产物里的 boot.html
/// （品牌头 + 阶段行 + 进度条 + 后端日志滚动）。创建失败不致命——主窗照常亮。
fn create_boot_window(handle: &tauri::AppHandle) -> Result<(), String> {
    if handle.get_webview_window("boot").is_some() {
        return Ok(());
    }
    // 打包态 dist 里带 boot.html；开发态走 devUrl 根路径也行（页面会自降级）
    let bundled = handle.path().resource_dir().map(|rd| rd.join("backend")).is_ok();
    let url = if bundled {
        WebviewUrl::App("boot.html".into())
    } else {
        WebviewUrl::External("http://localhost:8100/boot.html".parse().unwrap())
    };
    WebviewWindowBuilder::new(handle, "boot", url)
        .title("Neurova 启动中")
        .inner_size(400.0, 480.0)
        .resizable(false)
        .decorations(false)
        .center()
        .build()
        .map(|_| ())
        .map_err(|e| format!("boot window: {e}"))
}

#[tauri::command]
fn backend_status(state: tauri::State<BackendChild>) -> String {
    let mut guard = state.0.lock().unwrap();
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(Some(status)) => format!("exited: {status}"),
            Ok(None) => "running".into(),
            Err(e) => format!("error: {e}"),
        },
        None => "not started".into(),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();

            // 日志落盘（release 也开）：appData/logs/ 下——排查装机现场
            // "Network Error"（后端 spawn 失败/就绪超时都有迹可循）。
            let log_handle = handle.clone();
            let _ = log_handle.plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Info)
                    .targets([
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                            file_name: None,
                        }),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    ])
                    .build(),
            );

            // 后端拉起放独立线程：不阻塞窗口首帧。流程 =
            // 建 boot 进度窗（默认隐藏主窗的替代可见面）→ spawn 后端 →
            // 轮询 /health 并实时推送 backend.log 增量 → 就绪关 boot 亮主窗；
            // 超时/失败也亮主窗（登录页诊断会指路 backend.log）。
            std::thread::spawn(move || {
                let root = resolve_backend_root(&handle);
                let log_path = root.join("backend.log");
                let _ = create_boot_window(&handle);
                match spawn_backend(&root) {
                    Ok(child) => {
                        let pid = child.id();
                        *BOOT_LOG_PATH.lock().unwrap() = Some(log_path);
                        // 先托管再等待：启动期内 backend_status/boot_tail 可见 "running"
                        handle.manage(BackendChild(Mutex::new(Some(child))));
                        let ready = wait_backend_ready(Duration::from_secs(120));
                        log::info!("backend pid={pid} ready={ready} root={}", root.display());
                        let _ = handle.emit(
                            "backend-status",
                            if ready { "ready" } else { "timeout" },
                        );
                        if ready {
                            finish_boot(&handle, true, "启动完成，即将进入…");
                        } else {
                            finish_boot(
                                &handle,
                                false,
                                "后端启动超时，详见安装目录 backend\\backend.log",
                            );
                        }
                    }
                    Err(e) => {
                        log::error!("backend spawn failed: {e}");
                        let _ = handle.emit("backend-status", format!("error: {e}"));
                        finish_boot(&handle, false, &format!("后端启动失败：{e}"));
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // 关主窗即退出：终止后端（Phase 1 无托盘常驻）。
            // 注意只认主窗——boot 进度窗销毁（正常收尾动作）不得误杀后端。
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    if let Some(state) = window.app_handle().try_state::<BackendChild>() {
                        if let Some(child) = state.0.lock().unwrap().as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![backend_status, boot_tail])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
