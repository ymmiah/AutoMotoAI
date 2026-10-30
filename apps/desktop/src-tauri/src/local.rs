// Local mode: AutoMoto on this computer only, no account. The app does not bundle Python; it starts the
// AutoMoto engine that the official installer (scripts/install.ps1 / install.sh) put on this computer,
// or signs in to one that is already running. See apps/desktop/README.md for why.
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;
use url::Url;

pub const PORT: u16 = 8765;
pub const ADDR: &str = "127.0.0.1:8765";

pub fn base_url() -> Url {
    Url::parse(&format!("http://127.0.0.1:{PORT}/")).expect("static url")
}

/// The Python that runs AutoMoto, in the order we look for it.
pub fn find_engine() -> Option<(PathBuf, &'static str)> {
    if let Ok(p) = std::env::var("AUTOMOTO_PYTHON") {
        let p = PathBuf::from(p);
        if p.is_file() {
            return Some((p, "AUTOMOTO_PYTHON"));
        }
    }
    #[cfg(windows)]
    {
        if let Ok(la) = std::env::var("LOCALAPPDATA") {
            let p = PathBuf::from(la).join("automoto-ai").join("venv").join("Scripts").join("python.exe");
            if p.is_file() {
                return Some((p, "installed by install.ps1"));
            }
        }
    }
    #[cfg(not(windows))]
    {
        let data = std::env::var("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".local/share"));
        let p = data.join("automoto-ai/venv/bin/python");
        if p.is_file() {
            return Some((p, "installed by install.sh"));
        }
    }
    None
}

pub fn port_busy() -> bool {
    TcpStream::connect_timeout(&ADDR.parse().expect("static addr"), Duration::from_millis(400)).is_ok()
}

pub fn start(python: &PathBuf, token: &str, log: Option<PathBuf>) -> Result<Child, String> {
    let mut cmd = Command::new(python);
    cmd.args(["-m", "automoto", "serve", "--no-browser", "--port", &PORT.to_string()])
        .env("AUTOMOTO_LAUNCH_TOKEN", token)
        .stdin(Stdio::null());
    if let Some(dir) = dirs_home() {
        cmd.current_dir(dir);
    }
    match log.and_then(|p| std::fs::File::create(p).ok()) {
        Some(f) => {
            let f2 = f.try_clone().map_err(|e| e.to_string())?;
            cmd.stdout(Stdio::from(f)).stderr(Stdio::from(f2));
        }
        None => {
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd.spawn().map_err(|e| format!("Couldn't start the AutoMoto engine ({}): {e}", python.display()))
}

/// Stop the engine and everything it started. On Windows the venv's python.exe is a small launcher that
/// runs the real interpreter as a child process, so the whole tree has to go.
pub fn stop(mut child: Child) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(0x0800_0000)
            .status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from)
}

pub async fn wait_healthy(child: &mut Option<Child>, secs: u64) -> Result<(), String> {
    let url = base_url().join("api/health").expect("static url");
    let http = reqwest::Client::builder().timeout(Duration::from_secs(3)).build().map_err(|e| e.to_string())?;
    let until = Instant::now() + Duration::from_secs(secs);
    while Instant::now() < until {
        if let Ok(r) = http.get(url.clone()).send().await {
            if r.status().is_success() {
                return Ok(());
            }
        }
        if let Some(c) = child.as_mut() {
            if let Ok(Some(status)) = c.try_wait() {
                return Err(format!("The AutoMoto engine stopped ({status}). See the log: Help > Open the local engine log."));
            }
        }
        tokio_sleep(500).await;
    }
    Err("The AutoMoto engine did not start within a minute and a half".into())
}

async fn tokio_sleep(ms: u64) {
    tauri::async_runtime::spawn_blocking(move || std::thread::sleep(Duration::from_millis(ms))).await.ok();
}

/// A server is already running (started from a terminal or at login): ask it for a one-time link using
/// the token it wrote for local apps in <data dir>/session.json (readable by this user only).
pub async fn launch_running() -> Result<Url, String> {
    let dir = std::env::var("AUTOMOTO_DATA_DIR")
        .map(PathBuf::from)
        .ok()
        .or_else(|| dirs_home().map(|h| h.join(".automoto")))
        .ok_or("no home folder")?;
    let raw = std::fs::read_to_string(dir.join("session.json"))
        .map_err(|_| "Port 8765 is in use, but not by an AutoMoto engine this app can open. Close the other program, or run `automoto open`.".to_string())?;
    let v: Value = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    let token = v.get("token").and_then(|t| t.as_str()).unwrap_or("");
    if token.len() < 20 {
        return Err("session.json has no token - restart AutoMoto".into());
    }
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|e| e.to_string())?;
    let r = http
        .post(base_url().join("api/session/launch").expect("static url"))
        .header("X-AutoMoto-Token", token)
        .json(&serde_json::json!({}))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err(format!("The running AutoMoto engine refused to open ({}) - restart it", r.status()));
    }
    let v: Value = r.json().await.map_err(|e| e.to_string())?;
    let mut link = Url::parse(v.get("url").and_then(|u| u.as_str()).unwrap_or("")).map_err(|e| e.to_string())?;
    // the token must never leave this computer: only accept a loopback link
    if link.scheme() != "http" || link.host_str() != Some("127.0.0.1") && link.host_str() != Some("localhost") {
        return Err("unexpected launch link".into());
    }
    link.query_pairs_mut().append_pair("app", "1");
    Ok(link)
}
