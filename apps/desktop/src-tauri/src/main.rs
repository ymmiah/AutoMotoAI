// AutoMoto AI v4 desktop shell (Windows / macOS / Linux).
//
// The Python package is the brain: this shell starts `python -m automoto serve`
// on 127.0.0.1:8765 (unless one is already running), shows the loading page,
// and stops the server again when the window closes. No API keys live here.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

const ADDR: &str = "127.0.0.1:8765";

struct Server(Mutex<Option<Child>>);

fn python() -> String {
    std::env::var("AUTOMOTO_PYTHON").unwrap_or_else(|_| {
        if cfg!(target_os = "windows") { "python".into() } else { "python3".into() }
    })
}

fn start_server() -> Option<Child> {
    if TcpStream::connect(ADDR).is_ok() {
        return None; // already running (e.g. started from a terminal)
    }
    let home = std::env::var("AUTOMOTO_HOME").unwrap_or_else(|_| ".".into());
    let mut cmd = Command::new(python());
    cmd.args(["-m", "automoto", "serve", "--no-browser", "--port", "8765"])
        .current_dir(home)
        .stdout(Stdio::null())
        .stderr(Stdio::inherit());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(err) => {
            eprintln!("AutoMoto: could not start python server: {err}");
            None
        }
    }
}

fn main() {
    let child = start_server();
    let app = tauri::Builder::default()
        .manage(Server(Mutex::new(child)))
        .build(tauri::generate_context!())
        .expect("failed to build AutoMoto desktop shell");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut c) = handle.state::<Server>().0.lock().unwrap().take() {
                let _ = c.kill();
            }
        }
    });
}
