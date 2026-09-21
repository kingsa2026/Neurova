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
}

// ---- 子进程托管（Python + Node）----

struct ManagedChildren {
    python: Mutex<Option<Child>>,
    node: Mutex<Option<Child>>,
}

// ---- 下载状态文件 ----

const DOWNLOAD_STATUS_FILE: &str = ".download_status.json";

/// 下载状态是运行态，只能落在 runtime/ 下：开发态的后端根就是仓库根，
/// 拼在根上等于每次启动往仓库里写一个未跟踪文件。
fn download_status_path(root: &std::path::Path) -> std::path::PathBuf {
    root.join("runtime").join(DOWNLOAD_STATUS_FILE)
}

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
    let text = match std::fs::read_to_string(download_status_path(root)) {
        Ok(t) => t,
        Err(_) => return DownloadStatus::idle(),
    };
    match serde_json::from_str(&text) {
        Ok(s) => s,
        Err(_) => DownloadStatus::idle(),
    }
}

fn write_download_status(root: &std::path::Path, status: &DownloadStatus) {
    let path = download_status_path(root);
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let _ = std::fs::write(&path, serde_json::to_string_pretty(status).unwrap_or_default());
}

// ---- 模型清单 ----

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct ModelManifest {
    runtime: RuntimeSources,
    models: Vec<ModelEntry>,
}

/// 运行时供给清单：版本与候选下载源同源，lib.rs 不再抄第二份。
/// urls 是有序候选——国内镜像在前、官方源兜底。
#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct RuntimeSources {
    python: RuntimeSpec,
    node: RuntimeSpec,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct RuntimeSpec {
    version: String,
    urls: Vec<String>,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct ModelEntry {
    id: String,
    path: String,
    required: bool,
    source: String,
    size_mb: u64,
    repo_id: Option<String>,
    model_size: Option<String>,
}

fn read_model_manifest(root: &std::path::Path) -> Result<ModelManifest, String> {
    let path = root.join("models/MANIFEST.json");
    let text = std::fs::read_to_string(&path)
        .map_err(|e| format!("读 {} 失败: {}", path.display(), e))?;
    // 解析失败必须与「文件不存在」区分报出：字段对不上时表现也是「清单不存在」，
    // 排查会被引向文件缺失而非契约错位。
    serde_json::from_str(&text)
        .map_err(|e| format!("models/MANIFEST.json 解析失败: {}", e))
}

/// 清单里的 path 自带 models/ 前缀，一律相对后端根拼（相对 layout.models 拼
/// 会成 root/models/models/... 永不命中）。必需项缺席即未就绪，可选项不阻塞启动。
fn is_model_ready(layout: &RuntimeLayout) -> bool {
    let manifest = match read_model_manifest(&layout.root) {
        Ok(m) => m,
        Err(e) => {
            log::warn!("{}", e);
            return false;
        }
    };
    manifest
        .models
        .iter()
        .filter(|m| m.required)
        .all(|m| model_present(layout, m))
}

fn model_present(layout: &RuntimeLayout, entry: &ModelEntry) -> bool {
    let dir = layout.root.join(&entry.path);
    dir.exists() && dir.read_dir().map(|mut d| d.next().is_some()).unwrap_or(false)
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

/// 运行时布局解析（runtime/ 子目录）。模型位置由清单 path 自带 models/ 前缀，
/// 一律相对 root 拼，不在这里再挂一个 models 目录。
fn resolve_runtime(root: &std::path::Path) -> RuntimeLayout {
    RuntimeLayout {
        root: root.to_path_buf(),
        python: root.join("runtime/python/python.exe"),
        node: root.join("runtime/node/node.exe"),
    }
}

/// 后端根的唯一解析入口。命令侧一律经此取布局，不把 root 作为参数暴露给前端：
/// 前端一旦能传 root，就可能传出一个与 resource_dir/backend 不同层的目录，
/// 表现为「清单读不到 + 下载落错地方」这种极难归因的失败。
fn resolve_layout(app: &tauri::AppHandle) -> RuntimeLayout {
    resolve_runtime(&resolve_backend_root(app))
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

// ---- 归档落地（Python / Node 共用一种形状）----

/// 在解压目录里找「含可执行文件的那一层」。归档有两种布局：exe 直接在该层，
/// 或多一层 install/（python-build-standalone 的部分变体）。
fn find_payload_root(extract_dir: &std::path::Path, exe_name: &str) -> Option<std::path::PathBuf> {
    for entry in std::fs::read_dir(extract_dir).ok()? {
        let dir = entry.ok()?.path();
        if dir.join(exe_name).exists() {
            return Some(dir);
        }
        let nested = dir.join("install");
        if nested.join(exe_name).exists() {
            return Some(nested);
        }
    }
    None
}

/// 把 payload 层原子改名成运行时目录。目标必须先不存在：rename 与 PowerShell
/// Move-Item 在目标为已存在目录时都是「移入其内」，多出一层即永不命中。
fn relocate_payload(
    extract_dir: &std::path::Path,
    dst: &std::path::Path,
    exe_name: &str,
) -> Result<(), String> {
    let payload = find_payload_root(extract_dir, exe_name).ok_or_else(|| {
        format!(
            "解压产物里找不到 {exe_name}（{} 下内容不完整或格式不符）",
            extract_dir.display()
        )
    })?;
    if dst.exists() {
        std::fs::remove_dir_all(dst)
            .map_err(|e| format!("清理旧运行时目录 {} 失败: {e}", dst.display()))?;
    }
    if let Some(parent) = dst.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("创建 {} 失败: {e}", parent.display()))?;
    }
    std::fs::rename(&payload, dst)
        .map_err(|e| format!("落地 {} → {} 失败: {e}", payload.display(), dst.display()))
}

// ---- 运行时下载（ureq 同步下载 + 系统工具解压）----

fn download_file(
    url: &str,
    dest: &std::path::Path,
    on_progress: &mut dyn FnMut(u8),
) -> Result<(), String> {
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

/// 按候选顺序逐个尝试下载，全败才报错，且错误里点名试过的每一个源。
/// 只说「下载失败」而不说换过源，排查会被引向本机网络而不是某个源的 404。
fn download_with_fallback(
    urls: &[String],
    dest: &std::path::Path,
    mut on_progress: impl FnMut(u8),
) -> Result<(), String> {
    let mut failures: Vec<String> = Vec::new();
    for url in urls {
        match download_file(url, dest, &mut on_progress) {
            Ok(()) => return Ok(()),
            Err(e) => {
                log::warn!("候选源失败 {url}: {e}");
                failures.push(format!("{url} → {e}"));
            }
        }
    }
    Err(format!("{} 个候选源全部失败：{}", failures.len(), failures.join(" | ")))
}

fn download_python_runtime(layout: &RuntimeLayout, app: &tauri::AppHandle) -> Result<(), String> {
    // 候选源来自 models/MANIFEST.json 的 runtime.python.urls：镜像在前、官方兜底，
    // 版本与 URL 同源（守卫 tests/unit/desktop/test_route_b_runtime_download.py）。
    let urls = read_model_manifest(&layout.root)?.runtime.python.urls;
    let dest = layout.root.join("runtime/_python.tar.gz");
    let extract_dir = layout.root.join("runtime/_python_extract");

    write_download_status(&layout.root, &DownloadStatus {
        phase: "python".into(),
        progress: 0,
        message: "正在下载 Python 运行环境...".into(),
        error: None,
    });
    let _ = app.emit("runtime-status", "python:downloading");

    download_with_fallback(&urls, &dest, |p| {
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

    // 解压：Windows 10 1803+ 自带 bsdtar。tar 不可用或失败时把原因原样交出，
    // 不再兜一层结构上解不开 tar.gz 的 PowerShell 回退。
    let _ = std::fs::remove_dir_all(&extract_dir);
    std::fs::create_dir_all(&extract_dir).map_err(|e| e.to_string())?;
    let extracted = Command::new("tar")
        .args(["-xzf", &dest.display().to_string()])
        .current_dir(&extract_dir)
        .output()
        .map_or_else(
            |e| Err(format!("调用 tar 失败: {e}")),
            |out| {
                if out.status.success() {
                    Ok(())
                } else {
                    Err(format!(
                        "tar 解压失败: {}",
                        String::from_utf8_lossy(&out.stderr).trim()
                    ))
                }
            },
        );
    // 归档解开是 python/ 一层，与 Node 共用同一落地形状
    let python_dst = layout.root.join("runtime/python");
    let landed = extracted.and_then(|()| relocate_payload(&extract_dir, &python_dst, "python.exe"));

    // 清理临时文件
    let _ = std::fs::remove_file(&dest);
    let _ = std::fs::remove_dir_all(&extract_dir);

    if let Err(e) = landed {
        write_download_status(&layout.root, &DownloadStatus {
            phase: "python".into(),
            progress: 0,
            message: "".into(),
            error: Some(e.clone()),
        });
        return Err(e);
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
    let urls = read_model_manifest(&layout.root)?.runtime.node.urls;
    let dest = layout.root.join("runtime/_node.zip");
    let extract_dir = layout.root.join("runtime/_node_extract");

    write_download_status(&layout.root, &DownloadStatus {
        phase: "node".into(),
        progress: 0,
        message: "正在下载 Node.js...".into(),
        error: None,
    });
    let _ = app.emit("runtime-status", "node:downloading");

    download_with_fallback(&urls, &dest, |p| {
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

    // 解压只把归档摊平到临时目录，落地与 Python 走同一条 relocate_payload。
    // 曾经的 Move-Item 形态：目标 runtime/node 已被 create_dir_all 建出来，
    // PowerShell 语义变成「移入其内」，node.exe 落到多一层目录里，就绪判定恒不命中。
    let node_dst = layout.root.join("runtime/node");
    std::fs::create_dir_all(&extract_dir).map_err(|e| e.to_string())?;
    let ps_script = format!(
        r#"Expand-Archive -Path "{}" -DestinationPath "{}" -Force"#,
        dest.display(),
        extract_dir.display()
    );
    let output = Command::new("powershell")
        .args(["-Command", &ps_script])
        .output()
        .map_err(|e| e.to_string())?;
    let ps_stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let landed = relocate_payload(&extract_dir, &node_dst, "node.exe");

    let _ = std::fs::remove_file(&dest);
    let _ = std::fs::remove_dir_all(&extract_dir);

    let failure = match (output.status.success(), landed) {
        (true, Ok(())) => None,
        (false, _) => Some(format!("Node.js 解压失败: {ps_stderr}")),
        (_, Err(e)) => Some(e),
    };
    if let Some(error) = failure {
        write_download_status(&layout.root, &DownloadStatus {
            phase: "node".into(),
            progress: 0,
            message: "".into(),
            error: Some(error.clone()),
        });
        return Err(error);
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
    let manifest = read_model_manifest(&layout.root)?;

    write_download_status(&layout.root, &DownloadStatus {
        phase: "models".into(),
        progress: 0,
        message: format!("正在检查 {} 个模型...", manifest.models.len()),
        error: None,
    });
    let _ = app.emit("runtime-status", "models:checking");

    // 清单声明的是仓库级来源（repo_id / model_size），单次 download_file 拿不下
    // 一个仓库，也不再伪造 <id>.bin 单文件产物——缺席的按名点名交出。
    let blocking: Vec<String> = manifest
        .models
        .iter()
        .filter(|m| m.required && !model_present(layout, m))
        .map(|m| format!("{}（来源 {}）", m.id, m.source))
        .collect();
    if !blocking.is_empty() {
        return Err(format!("必需模型未就绪，仓库级拉取通道未接通: {}", blocking.join(", ")));
    }
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

/// 轮询 /health 直到就绪。后端进程中途退出即判失败——只看端口会把
/// 「解释器起来就崩」这种情况等满整个超时，首启要白等两分钟。
fn wait_backend_ready(children: &ManagedChildren, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(2)).build();
    while Instant::now() < deadline {
        let exited = children
            .python
            .lock()
            .unwrap()
            .as_mut()
            .map(|c| matches!(c.try_wait(), Ok(Some(_))))
            .unwrap_or(true);
        if exited {
            return false;
        }
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
    serde_json::json!({ "lines": lines, "offset": next_offset, "backend": backend, "logPath": backend_root.as_ref().map(|p| p.display().to_string()).unwrap_or_default() })
}

/// backend.log 绝对路径（spawn 成功后登记，boot_tail 拉取用）
static BOOT_LOG_PATH: Mutex<Option<std::path::PathBuf>> = Mutex::new(None);

/// 提示里给出的日志落点：以 BOOT_LOG_PATH 为唯一事实源，不再写死文件名。
/// 曾经写的是「安装目录 backend\backend.log」，而实际日志在 logs/backend-<日期>.log，
/// 用户照提示找不到任何文件。
fn backend_log_hint() -> String {
    BOOT_LOG_PATH
        .lock()
        .unwrap()
        .as_ref()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|| "logs/ 目录".to_string())
}

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
fn check_runtime_ready(app: tauri::AppHandle) -> serde_json::Value {
    let layout = resolve_layout(&app);
    let missing = get_missing(&layout);
    let download = read_download_status(&layout.root);
    serde_json::json!({
        "ready": missing.is_empty(),
        "missing": missing,
        "download": download,
    })
}

/// 触发后端启动（boot 页在运行时就绪后调用）。
#[tauri::command]
fn trigger_backend_start(app: tauri::AppHandle) -> Result<(), String> {
    let layout = resolve_layout(&app);
    std::thread::spawn(move || {
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
                let ready = wait_backend_ready(app.state::<ManagedChildren>().inner(), Duration::from_secs(120));
                log::info!("backend pid={pid} ready={ready} root={}", layout.root.display());
                let _ = app.emit(
                    "backend-status",
                    if ready { "ready" } else { "timeout" },
                );
                if ready {
                    finish_boot(&app, true, "启动完成，即将进入…");
                } else {
                    finish_boot(&app, false, &format!("后端未就绪，详见日志：{}", backend_log_hint()));
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
fn start_download(app: tauri::AppHandle, what: String) -> Result<(), String> {
    let layout = resolve_layout(&app);
    std::thread::spawn(move || {
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
                let layout = resolve_layout(&handle);
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
                        let ready = wait_backend_ready(handle.state::<ManagedChildren>().inner(), Duration::from_secs(120));
                        log::info!("backend pid={pid} ready={ready} root={}", layout.root.display());
                        let _ = handle.emit(
                            "backend-status",
                            if ready { "ready" } else { "timeout" },
                        );
                        if ready {
                            finish_boot(&handle, true, "启动完成，即将进入…");
                        } else {
                            finish_boot(&handle, false, &format!("后端未就绪，详见日志：{}", backend_log_hint()));
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

#[cfg(test)]
mod runtime_extract_tests {
    use super::*;

    /// 用例独占临时目录（进程内唯一）。E 盘 TEMP 有被残留填满的前科，
    /// 用例结束时必须自己收干净。
    fn temp_case(tag: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU32, Ordering};
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir()
            .join(format!("neurova-extract-{}-{}-{}", tag, std::process::id(), SEQ.fetch_add(1, Ordering::SeqCst)));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// Node 归档解开是「一层目录里放 node.exe」，落地后 node.exe 必须在
    /// runtime/node/ 根下——多一层就永远判不就绪（PowerShell Move-Item 目标
    /// 为已存在目录时是「移入其内」，正是多一层的来源）。
    #[test]
    fn payload_one_level_down_lands_exe_at_runtime_root() {
        let case = temp_case("node");
        let extract = case.join("runtime/_node_extract");
        let payload = extract.join("node-v24.16.0-win-x64");
        std::fs::create_dir_all(&payload).unwrap();
        std::fs::write(payload.join("node.exe"), b"x").unwrap();

        let dst = case.join("runtime/node");
        std::fs::create_dir_all(&dst).unwrap();

        relocate_payload(&extract, &dst, "node.exe").expect("落地失败");

        assert!(dst.join("node.exe").exists(), "node.exe 未落在 dst 根下");
        let _ = std::fs::remove_dir_all(&case);
    }

    /// python-build-standalone 的部分构建把解释器藏在多一层 install/ 下，
    /// 落地时必须认得这种布局（原实现有此容错，收敛后由本用例锁住）。
    #[test]
    fn payload_nested_under_install_dir_is_recognised() {
        let case = temp_case("pbs");
        let extract = case.join("runtime/_python_extract");
        let payload = extract.join("cpython-3.12.14+20260901").join("install");
        std::fs::create_dir_all(&payload).unwrap();
        std::fs::write(payload.join("python.exe"), b"x").unwrap();

        let dst = case.join("runtime/python");
        relocate_payload(&extract, &dst, "python.exe").expect("落地失败");

        assert!(dst.join("python.exe").exists(), "python.exe 未落在 dst 根下");
        let _ = std::fs::remove_dir_all(&case);
    }

    /// 候选源全部失败时，错误必须点名每一个源——否则用户与排查者都不知道
    /// 换过源、也不知道最后一个坏在哪。
    #[test]
    fn exhausted_candidates_name_every_source() {
        let case = temp_case("fallback");
        let urls = vec![
            "http://127.0.0.1:9/first.tar.gz".to_string(),
            "http://127.0.0.1:8/second.tar.gz".to_string(),
        ];
        let err = download_with_fallback(&urls, &case.join("payload"), |_| {}).unwrap_err();
        let _ = std::fs::remove_dir_all(&case);

        assert!(err.contains("127.0.0.1:9") && err.contains("127.0.0.1:8"), "未点名两个源: {err}");
        assert!(err.starts_with("2 个候选源全部失败"), "计数不对: {err}");
    }

    /// 后端进程已经退出时，就绪轮询必须立刻返回 false。真机取证：下载来的裸
    /// CPython 缺 uvicorn，start_server.py 秒退，而轮询只看 /health，于是首启
    /// 白等满 120 秒才把失败摆出来。
    #[test]
    fn dead_backend_child_ends_the_readiness_wait() {
        let mut cmd = Command::new("cmd");
        cmd.args(["/c", "exit 3"]);
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000);
        }
        let child = cmd.spawn().expect("探针子进程启动失败");
        let state = ManagedChildren {
            python: Mutex::new(Some(child)),
            node: Mutex::new(None),
        };

        let started = Instant::now();
        let ready = wait_backend_ready(&state, Duration::from_secs(30));

        assert!(!ready, "子进程都退了，不该报就绪");
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "未提前结束等待，耗时 {:?}",
            started.elapsed()
        );
    }

    /// 归档解开后 dst 已有旧运行时（重试下载的情形）：必须先清再改名，
    /// 否则 rename 到已存在目录会失败——这正是 Move-Item 那次的同一前提。
    #[test]
    fn stale_runtime_dir_is_replaced_not_merged() {
        let case = temp_case("stale");
        let extract = case.join("runtime/_node_extract");
        let payload = extract.join("node-v24.16.0-win-x64");
        std::fs::create_dir_all(&payload).unwrap();
        std::fs::write(payload.join("node.exe"), b"x").unwrap();

        let dst = case.join("runtime/node");
        std::fs::create_dir_all(&dst).unwrap();
        std::fs::write(dst.join("leftover.txt"), b"old").unwrap();

        relocate_payload(&extract, &dst, "node.exe").expect("落地失败");

        assert!(dst.join("node.exe").exists());
        assert!(!dst.join("leftover.txt").exists(), "旧运行时残留，说明是合并而非替换");
        let _ = std::fs::remove_dir_all(&case);
    }
}

#[cfg(test)]
mod manifest_contract_tests {
    use super::*;

    /// 直读真清单验一次反序列化。清单字段与 ModelEntry 错位时，运行期表现是
    /// 「models/MANIFEST.json 不存在」，静态检查只能证明字段名对得上，证明不了
    /// 类型也对——所以这里编译期取文件、跑期解析，才算把契约钉住。
    #[test]
    fn real_manifest_matches_model_entry_contract() {
        const REAL: &str = include_str!("../../../models/MANIFEST.json");
        let manifest: ModelManifest =
            serde_json::from_str(REAL).expect("models/MANIFEST.json 与 ModelEntry 契约不一致");
        assert!(manifest.models.iter().any(|m| m.required));
        assert!(manifest.models.iter().all(|m| m.path.starts_with("models/")),
            "清单 path 必须自带 models/ 前缀（is_model_ready 按 root 拼）");
    }
}
