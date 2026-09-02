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
use tauri::{Emitter, Manager};

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

/// 后端根解析（补课 P3-a 路线 A 全量打包）：
/// 1) 打包态：resource_dir()/backend（python/ neurova/ models/ config/ start_server.py）
/// 2) 开发态回退：仓库根 + .venv
fn resolve_backend_root(app: &tauri::AppHandle) -> std::path::PathBuf {
    use tauri::Manager;
    if let Ok(rd) = app.path().resource_dir() {
        let bundled = rd.join("backend");
        if bundled.join("start_server.py").exists() && bundled.join("python/python.exe").exists() {
            return bundled;
        }
    }
    repo_root()
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
    cmd.stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("后端进程启动失败: {e}"))
}

/// 轮询 /health 直到就绪（最多 120s——冷启动含 MoE 渐进索引）。
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

            // 后端拉起放独立线程：不阻塞窗口首帧；就绪与否前端自行降级。
            // 子进程句柄经 app.manage(BackendChild) 交给 Tauri 状态表托管，
            // 退出清理时从那里取回。
            std::thread::spawn(move || {
                let root = resolve_backend_root(&handle);
                match spawn_backend(&root) {
                    Ok(child) => {
                        let pid = child.id();
                        let ready = wait_backend_ready(Duration::from_secs(120));
                        log::info!("backend pid={pid} ready={ready}");
                        let _ = handle.emit(
                            "backend-status",
                            if ready { "ready" } else { "timeout" },
                        );
                        handle.manage(BackendChild(Mutex::new(Some(child))));
                    }
                    Err(e) => {
                        log::error!("backend spawn failed: {e}");
                        let _ = handle.emit("backend-status", format!("error: {e}"));
                    }
                }
            });

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // 关窗即退出：终止后端（Phase 1 无托盘常驻）
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<BackendChild>() {
                    if let Some(child) = state.0.lock().unwrap().as_mut() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![backend_status])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
