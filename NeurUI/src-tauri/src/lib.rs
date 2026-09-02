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
use tauri::Emitter;

struct BackendChild(Mutex<Option<Child>>);

/// 仓库根 = src-tauri 的上两级（NeurUI/src-tauri → Neurova）。
fn repo_root() -> std::path::PathBuf {
    let manifest = env!("CARGO_MANIFEST_DIR");
    std::path::Path::new(manifest)
        .parent() // NeurUI
        .and_then(|p| p.parent()) // Neurova
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::path::PathBuf::from("."))
}

fn spawn_backend() -> Result<Child, String> {
    let root = repo_root();
    let python = root.join(".venv/Scripts/python.exe");
    if !python.exists() {
        return Err(format!("后端解释器不存在: {}", python.display()));
    }
    let server = root.join("start_server.py");
    if !server.exists() {
        return Err(format!("后端入口不存在: {}", server.display()));
    }
    Command::new(&python)
        .arg(&server)
        .current_dir(&root) // start_server 按仓库根解析 data/ logs/ 等相对路径
        .stdout(Stdio::null())
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
                match spawn_backend() {
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
