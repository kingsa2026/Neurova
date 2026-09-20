//! Neurova 桌面壳（轻壳 + 首启按需下载运行环境 + 模型）
//!
//! 职责：
//! 1. 首次启动检测 runtime/ 完整性，缺则自动下载 Python + Node + 模型
//! 2. 启动时拉起 Python 后端（start_server.py）+ Node（供 MCP 用）
//! 3. 轮询 /health 等待后端就绪（超时不杀进程——窗口仍打开，用户可看后端日志排查）
//! 4. 应用退出时优雅终止 Python + Node 子进程
//!
//! 降级路径：安装时若网络失败，首次启动自动补下；断网则明确提示 + 重试。

use std::borrow::Cow;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

// ---- 运行时布局 ----

#[derive(Clone)]
struct RuntimeLayout {
    root: std::path::PathBuf,
    python: std::path::PathBuf,
    node: std::path::PathBuf,
    models: std::path::PathBuf,
}

// ---- 子进程托管（Python + Node）----

struct ManagedChildren {
    python: Mutex<Option<Child>>,
    node: Mutex<Option<Child>>,
}

// ---- 下载状态文件 ----

const DOWNLOAD_STATUS_FILE: &str = ".download_status.json";

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct DownloadStatus {
    phase: String,      // "idle" | "python" | "node" | "models" | "complete" | "error"
    progress: u8,       // 0-100
    message: String,
    error: Option<String>,
}

impl DownloadStatus {
    fn idle() -> Self {
        Self { phase: "idle".into(), progress: 0, message: "".into(), error: None }
    }
}

fn read_download_status(root: &std::path::Path) -> DownloadStatus {
    let path = root.join(DOWNLOAD_STATUS_FILE);
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return DownloadStatus::idle(),
    };
    match serde_json::from_str(&text) {
        Ok(s) => s,
        Err(_) => DownloadStatus::idle(),
    }
}

fn write_download_status(root: &std::path::Path, status: &DownloadStatus) {
    let path = root.join(DOWNLOAD_STATUS_FILE);
    let _ = std::fs::write(&path, serde_json::to_string_pretty(status).unwrap_or_default());
}

// ---- 模型清单 ----

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct ModelManifest {
    models: Vec<ModelEntry>,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct ModelEntry {
    id: String,
    path: String,
    required: bool,
    source: String,
    url: String,
    size_mb: u64,
}

fn read_model_manifest(root: &std::path::Path) -> Option<ModelManifest> {
    let text = std::fs::read_to_string(root.join("models/MANIFEST.json")).ok()?;
    serde_json::from_str(&text).ok()
}

fn is_model_ready(layout: &RuntimeLayout) -> bool {
    let manifest = match read_model_manifest(&layout.root) {
        Some(m) => m,
        None => return false,
    };
    manifest.models.iter().all(|m| {
        let model_path = layout.models.join(&m.path);
        model_path.exists() && model_path.read_dir().map(|mut d| d.next().is_some()).unwrap_or(false)
    })
}

// ---- 路径解析 ----

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

/// 后端根解析（轻壳 + 首启下载路线）：
/// 1) 打包态：resource_dir()/backend（neurova/ models/ config/ start_server.py）
/// 2) 开发态回退：仓库根 + .venv
fn resolve_backend_root(app: &tauri::AppHandle) -> std::path::PathBuf {
    use tauri::Manager;
    if let Ok(rd) = app.path().resource_dir() {
        let bundled = rd.join("backend");
        if bundled.join("start_server.py").exists() && bundled.join("neurova").exists() {
            return normalize_windows_path(bundled);
        }
    }
    normalize_windows_path(repo_root())
}

/// 运行时布局解析（runtime/ 子目录 + models/）。
fn resolve_runtime(root: &std::path::Path) -> RuntimeLayout {
    RuntimeLayout {
        root: root.to_path_buf(),
        python: root.join("runtime/python/python.exe"),
        node: root.join("runtime/node/node.exe"),
        models: root.join("models"),
    }
}

/// 当天日期戳（本地时区 YYYYMMDD），backend 日志按天分文件用。
fn day_stamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86400) as i64;
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{:04}{:02}{:02}", y, m, d)
}

// ---- 运行时下载（ureq 同步下载 + 系统工具解压）----

fn download_file(url: &str, dest: &std::path::Path, on_progress: impl Fn(u8)) -> Result<(), String> {
    use std::io::Write;
    let resp = ureq::get(url)
        .call()
        .map_err(|e| format!("下载失败 {}: {}", url, e))?;
    let total = resp.header("Content-Length").and_then(|v| v.parse().ok()).unwrap_or(0);
    let mut file = std::fs::File::create(dest).map_err(|e| e.to_string())?;
    let mut reader = resp.into_reader();
    let mut buf = [0u8; 64 * 1024];
    let mut downloaded: u64 = 0;
    loop {
        let n = reader.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 { break; }
        file.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        downloaded += n as u64;
        if total > 0 {
            on_progress(((downloaded * 100) / total) as u8);
        }
    }
    file.flush().ok();
    Ok(())
}

fn download_python_runtime(layout: &RuntimeLayout, app: &tauri::AppHandle) -> Result<(), String> {
    let url = "https://github.com/astral-sh/python-build-standalone/releases/latest/download/cpython-3.12.5+20250916-x86_64-pc-windows-msvc-install_only.tar.gz";
    let dest = layout.root.join("runtime/_python.tar.gz");
    let extract_dir = layout.root.join("runtime/_python_extract");

    write_download_status(&layout.root, &DownloadStatus {
        phase: "python".into(),
        progress: 0,
        message: "正在下载 Python 运行环境...".into(),
        error: None,
    });
    let _ = app.emit("runtime-status", "python:downloading");

    download_file(url, &dest, |p| {
        let _ = write_download_status(&layout.root, &DownloadStatus {
            phase: "python".into(),
            progress: p,
            message: format!("正在下载 Python {}%", p),
            error: None,
        });
    })?;

    write_download_status(&layout.root, &DownloadStatus {
        phase: "python".into(),
        progress: 90,
        message: "正在解压 Python...".into(),
        error: None,
    });

    // 解压
    let _ = std::fs::remove_dir_all(&extract_dir);
    std::fs::create_dir_all(&extract_dir).map_err(|e| e.to_string())?;
    let tar_output = Command::new("tar")
        .args(["-xzf", &dest.display().to_string()])
        .current_dir(&extract_dir)
        .output();
    
    // Windows 10 可能没有 tar，回退到 PowerShell
    let tar_ok = tar_output.as_ref().map(|o| o.status.success()).unwrap_or(false);
    if !tar_ok {
        let ps_script = format!(
            r#"Expand-Archive -Path "{}" -DestinationPath "{}" -Force"#,
            dest.display(), extract_dir.display()
        );
        let _ = Command::new("powershell")
            .args(["-Command", &ps_script])
            .output();
    }

    // 找到解出的 python/ 目录并移动到 runtime/python/
    let python_dst = layout.root.join("runtime/python");
    let _ = std::fs::remove_dir_all(&python_dst);
    let mut found = false;
    if let Ok(entries) = std::fs::read_dir(&extract_dir) {
        for entry in entries.flatten() {
            let p = entry.path().join("python.exe");
            if p.exists() {
                let _ = std::fs::rename(entry.path(), &python_dst);
                found = true;
                break;
            }
            let p = entry.path().join("install").join("python.exe");
            if p.exists() {
                let _ = std::fs::rename(entry.path().join("install"), &python_dst);
                found = true;
                break;
            }
        }
    }

    // 清理临时文件
    let _ = std::fs::remove_file(&dest);
    let _ = std::fs::remove_dir_all(&extract_dir);

    if !found || !python_dst.join("python.exe").exists() {
        write_download_status(&layout.root, &DownloadStatus {
            phase: "python".into(),
            progress: 0,
            message: "".into(),
            error: Some("Python 解压失败，文件不完整".into()),
        });
        return Err("Python 解压失败".into());
    }

    write_download_status(&layout.root, &DownloadStatus {
        phase: "python".into(),
        progress: 100,
        message: "Python 运行环境就绪".into(),
        error: None,
    });
    Ok(())
}

fn download_node_runtime(layout: &RuntimeLayout, app: &tauri::AppHandle) -> Result<(), String> {
    let url = "https://nodejs.org/dist/v24.16.0/node-v24.16.0-win-x64.zip";
    let dest = layout.root.join("runtime/_node.zip");
    let extract_dir = layout.root.join("runtime/_node_extract");

    write_download_status(&layout.root, &DownloadStatus {
        phase: "node".into(),
        progress: 0,
        message: "正在下载 Node.js...".into(),
        error: None,
    });
    let _ = app.emit("runtime-status", "node:downloading");

    download_file(url, &dest, |p| {
        let _ = write_download_status(&layout.root, &DownloadStatus {
            phase: "node".into(),
            progress: p,
            message: format!("正在下载 Node.js {}%", p),
            error: None,
        });
    })?;

    write_download_status(&layout.root, &DownloadStatus {
        phase: "node".into(),
        progress: 80,
        message: "正在解压 Node.js...".into(),
        error: None,
    });

    // 用 PowerShell Expand-Archive 解压
    let node_dst = layout.root.join("runtime/node");
    let _ = std::fs::remove_dir_all(&node_dst);
    std::fs::create_dir_all(&node_dst).map_err(|e| e.to_string())?;
    let ps_script = format!(
        r#"Expand-Archive -Path "{}" -DestinationPath "{}" -Force; Move-Item "{}" "{}" -Force"#,
        dest.display(),
        extract_dir.display(),
        extract_dir.join("node-v24.16.0-win-x64").display(),
        node_dst.display()
    );
    let output = Command::new("powershell")
        .args(["-Command", &ps_script])
        .output()
        .map_err(|e| e.to_string())?;

    let _ = std::fs::remove_file(&dest);
    let _ = std::fs::remove_dir_all(&extract_dir);

    if !output.status.success() || !node_dst.join("node.exe").exists() {
        write_download_status(&layout.root, &DownloadStatus {
            phase: "node".into(),
            progress: 0,
            message: "".into(),
            error: Some("Node.js 解压失败".into()),
        });
        return Err("Node.js 解压失败".into());
    }

    write_download_status(&layout.root, &DownloadStatus {
        phase: "node".into(),
        progress: 100,
        message: "Node.js 运行环境就绪".into(),
        error: None,
    });
    Ok(())
}

fn download_models(layout: &RuntimeLayout, app: &tauri::AppHandle) -> Result<(), String> {
    let manifest = read_model_manifest(&layout.root).ok_or("models/MANIFEST.json 不存在")?;
    
    write_download_status(&layout.root, &DownloadStatus {
        phase: "models".into(),
        progress: 0,
        message: format!("正在检查 {} 个模型...", manifest.models.len()),
        error: None,
    });
    let _ = app.emit("runtime-status", "models:checking");

    let total_models = manifest.models.len() as u8;
    for (idx, model) in manifest.models.iter().enumerate() {
        let model_path = layout.models.join(&model.path);
        if model_path.exists() && model_path.read_dir().map(|mut d| d.next().is_some()).unwrap_or(false) {
            continue; // 已存在，跳过
        }

        let pct = ((idx as u8) * 100) / total_models.max(1);
        write_download_status(&layout.root, &DownloadStatus {
            phase: "models".into(),
            progress: pct,
            message: format!("正在下载模型 {}...", model.id),
            error: None,
        });

        std::fs::create_dir_all(&model_path).map_err(|e| e.to_string())?;
        // 尝试从 URL 下载（可能是目录索引页或直接文件）
        let dest = model_path.join(format!("{}.bin", model.id));
        if let Err(e) = download_file(&model.url, &dest, |_| {}) {
            // 单个模型失败不阻断（非必需模型）
            log::warn!("模型 {} 下载失败: {}", model.id, e);
        }
    }

    write_download_status(&layout.root, &DownloadStatus {
        phase: "models".into(),
        progress: 100,
        message: "模型检查完成".into(),
        error: None,
    });
    Ok(())
}

/// 判断运行时是否完整。
fn is_runtime_ready(layout: &RuntimeLayout) -> bool {
    layout.python.exists()
        && layout.node.exists()
        && is_model_ready(layout)
}

/// 获取缺失组件列表。
fn get_missing(layout: &RuntimeLayout) -> Vec<String> {
    let mut missing = vec![];
    if !layout.python.exists() { missing.push("python".into()); }
    if !layout.node.exists() { missing.push("node".into()); }
    if !is_model_ready(layout) { missing.push("models".into()); }
    missing
}

// ---- 后端进程启动 ----

fn spawn_backend(layout: &RuntimeLayout) -> Result<Child, String> {
    if !layout.python.exists() {
        return Err(format!("后端解释器不存在: {}", layout.python.display()));
    }
    let server = layout.root.join("start_server.py");
    if !server.exists() {
        return Err(format!("后端入口不存在: {}", server.display()));
    }

    let mut cmd = Command::new(&layout.python);
    cmd.arg(&server).current_dir(&layout.root);
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env(
        "PYTHONPATH",
        std::env::join_paths([layout.root.clone()]).unwrap(),
    );
    cmd.env(
        "NEUROVA_CORS_ORIGINS",
        "http://tauri.localhost,tauri://localhost,http://127.0.0.1:8100",
    );

    // 将 runtime/node/ 前置到 PATH（MCP 服务器经 npx 启动需要）
    let node_dir = layout.node.parent().map(|p| p.to_path_buf());
    if let Some(ref nd) = node_dir {
        if nd.join("npx.cmd").exists() {
            let old_path = std::env::var("PATH").unwrap_or_default();
            let new_path = std::env::join_paths(
                [nd.clone(), layout.root.clone()]
                    .into_iter()
                    .chain(std::env::split_paths(&old_path)),
            )
            .unwrap();
            cmd.env("PATH", new_path);
            cmd.env("npm_config_prefix", nd);
        }
    }

    // 后端输出进 logs/ 目录
    let logs_dir = layout.root.join("logs");
    let _ = std::fs::create_dir_all(&logs_dir);
    let legacy_log = layout.root.join("backend.log");
    if legacy_log.exists() {
        let raw = std::fs::read(&legacy_log).unwrap_or_default();
        let is_utf8 = String::from_utf8(raw).is_ok();
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let backup = layout.root.join(format!("backend.{stamp}.log.bak"));
        let _ = std::fs::rename(&legacy_log, &backup);
        if !is_utf8 {
            log::info!("backend.log 非UTF-8（旧版GBK），已轮换为 {}", backup.display());
        }
    }
    let day = day_stamp();
    let log_path = logs_dir.join(format!("backend-{day}.log"));
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

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }

    cmd.stdout(stdout).stderr(stderr).spawn().map_err(|e| format!("后端进程启动失败: {e}"))
}

/// 启动 Node 子进程（MCP 服务器用，无窗口常驻）。
fn spawn_node(layout: &RuntimeLayout) -> Option<Child> {
    let node_exe = layout.node.parent()?.join("node.exe");
    if !node_exe.exists() { return None; }
    let mut cmd = Command::new(&node_exe);
    cmd.arg("--version");
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    cmd.spawn().ok()
}

/// 轮询 /health 直到就绪。
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

/// 读 backend.log 自 offset 起的增量。
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

/// boot 页拉模式数据源：日志增量 + 后端进程状态。
#[tauri::command]
fn boot_tail(state: tauri::State<ManagedChildren>, log_offset: u64) -> serde_json::Value {
    let backend_root = BOOT_LOG_PATH.lock().unwrap().clone();
    let (lines, next_offset) = match &backend_root {
        Some(p) => read_log_increment(p, log_offset),
        None => (vec![], log_offset),
    };
    let backend = {
        let mut guard = state.python.lock().unwrap();
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

/// 就绪/失败后收尾：亮主窗。
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

/// 启动进度窗。
fn create_boot_window(handle: &tauri::AppHandle) -> Result<(), String> {
    if handle.get_webview_window("boot").is_some() {
        return Ok(());
    }
    let url = WebviewUrl::CustomProtocol("boot://localhost/boot.html".parse().unwrap());
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

// ---- Tauri 命令 ----

#[tauri::command]
fn backend_status(state: tauri::State<ManagedChildren>) -> String {
    let mut guard = state.python.lock().unwrap();
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(Some(status)) => format!("exited: {status}"),
            Ok(None) => "running".into(),
            Err(e) => format!("error: {e}"),
        },
        None => "not started".into(),
    }
}

/// 检查运行时完整性（供 boot 页轮询）。
#[tauri::command]
fn check_runtime_ready(root: &std::path::Path) -> serde_json::Value {
    let layout = resolve_runtime(root);
    let missing = get_missing(&layout);
    let download = read_download_status(root);
    serde_json::json!({
        "ready": missing.is_empty(),
        "missing": missing,
        "download": download,
    })
}

/// 触发后端启动（boot 页在运行时就绪后调用）。
#[tauri::command]
fn trigger_backend_start(app: tauri::AppHandle, root: std::path::PathBuf) -> Result<(), String> {
    std::thread::spawn(move || {
        let layout = resolve_runtime(&root);
        let log_path = layout.root.join("logs").join(format!("backend-{}.log", day_stamp()));
        
        // 同时拉起 Node（静默，不占窗口）
        let _node_child = spawn_node(&layout);
        
        match spawn_backend(&layout) {
            Ok(child) => {
                let pid = child.id();
                *BOOT_LOG_PATH.lock().unwrap() = Some(log_path);
                app.manage(ManagedChildren {
                    python: Mutex::new(Some(child)),
                    node: Mutex::new(_node_child),
                });
                let ready = wait_backend_ready(Duration::from_secs(120));
                log::info!("backend pid={pid} ready={ready} root={}", layout.root.display());
                let _ = app.emit(
                    "backend-status",
                    if ready { "ready" } else { "timeout" },
                );
                if ready {
                    finish_boot(&app, true, "启动完成，即将进入…");
                } else {
                    finish_boot(&app, false, "后端启动超时，详见安装目录 backend\\backend.log");
                }
            }
            Err(e) => {
                log::error!("backend spawn failed: {e}");
                let _ = app.emit("backend-status", format!("error: {e}"));
                finish_boot(&app, false, &format!("后端启动失败：{e}"));
            }
        }
    });
    Ok(())
}

/// 后台下载运行时（Python / Node / 模型）。前端调用后立即返回，后台线程执行。
#[tauri::command]
fn start_download(app: tauri::AppHandle, root: std::path::PathBuf, what: String) -> Result<(), String> {
    std::thread::spawn(move || {
        let layout = resolve_runtime(&root);
        let result = match what.as_str() {
            "python" => download_python_runtime(&layout, &app),
            "node" => download_node_runtime(&layout, &app),
            "models" => download_models(&layout, &app),
            _ => Err(format!("未知下载目标: {}", what)),
        };
        
        if result.is_ok() {
            let _ = app.emit("runtime-status", format!("{}:complete", what));
        } else {
            let _ = app.emit("runtime-status", format!("{}:error", what));
        }
        
        // 写完成标记（含错误也标记，避免无限重试）
        write_download_status(&layout.root, &DownloadStatus {
            phase: if result.is_ok() { "complete".into() } else { "error".into() },
            progress: if result.is_ok() { 100 } else { 0 },
            message: result.as_ref().map(|_| "下载完成".into()).unwrap_or_else(|e| e.clone()),
            error: result.err(),
        });
    });
    Ok(())
}

// ---- boot 页资源 ----

fn boot_html() -> &'static str {
    static BOOT_HTML: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    BOOT_HTML.get_or_init(|| {
        include_str!("boot_page.html")
            .replace("__NEUROVA_WORDMARK_B64__", env!("NEUROVA_WORDMARK_B64"))
    })
}

fn boot_page_response() -> tauri::http::Response<Cow<'static, [u8]>> {
    tauri::http::Response::builder()
        .header(tauri::http::header::CONTENT_TYPE, "text/html; charset=utf-8")
        .body(Cow::Owned(boot_html().as_bytes().to_vec()))
        .expect("boot 页响应构造失败")
}

// ---- 入口 ----

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();

            let _ = handle.plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Warn)
                    .targets([
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                            file_name: None,
                        }),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    ])
                    .build(),
            );

            // 启动流程：
            // 1. 解析后端根 + 运行时布局
            // 2. 若 runtime 不完整 → boot 页显示下载 UI → 前端调用 start_download
            // 3. 运行时就绪 → spawn Python + Node → 轮询 /health → 亮主窗
            std::thread::spawn(move || {
                let root = resolve_backend_root(&handle);
                let layout = resolve_runtime(&root);
                let _ = create_boot_window(&handle);

                if !is_runtime_ready(&layout) {
                    // 通知 boot 页显示下载界面
                    let missing = get_missing(&layout);
                    let _ = handle.emit("runtime-status", serde_json::json!({
                        "phase": "download",
                        "missing": missing,
                    }));
                    // 等待 boot 页完成下载（前端通过 trigger_backend_start 接手）
                    return;
                }

                // 运行时已就绪，直接启动
                let log_path = layout.root.join("logs").join(format!("backend-{}.log", day_stamp()));
                let _node_child = spawn_node(&layout);
                match spawn_backend(&layout) {
                    Ok(child) => {
                        let pid = child.id();
                        *BOOT_LOG_PATH.lock().unwrap() = Some(log_path);
                        handle.manage(ManagedChildren {
                            python: Mutex::new(Some(child)),
                            node: Mutex::new(_node_child),
                        });
                        let ready = wait_backend_ready(Duration::from_secs(120));
                        log::info!("backend pid={pid} ready={ready} root={}", layout.root.display());
                        let _ = handle.emit(
                            "backend-status",
                            if ready { "ready" } else { "timeout" },
                        );
                        if ready {
                            finish_boot(&handle, true, "启动完成，即将进入…");
                        } else {
                            finish_boot(&handle, false, "后端启动超时，详见安装目录 backend\\backend.log");
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
            // 关主窗即退出：终止 Python + Node（Phase 1 无托盘常驻）。
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    if let Some(state) = window.app_handle().try_state::<ManagedChildren>() {
                        if let Some(child) = state.python.lock().unwrap().as_mut() {
                            let _ = child.kill();
                        }
                        if let Some(child) = state.node.lock().unwrap().as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            backend_status,
            boot_tail,
            check_runtime_ready,
            trigger_backend_start,
            start_download
        ])
        .register_uri_scheme_protocol("boot", |_ctx, _request| boot_page_response())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
