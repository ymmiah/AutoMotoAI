// AutoMoto AI desktop shell (Windows / macOS / Linux).
//
// The Python package is the brain: this shell starts `python -m automoto serve`
// on 127.0.0.1:8765 (unless one is already running), shows the loading page,
// and stops the server again when the window closes. No API keys live here.
//
// Security: the shell makes a random launch token, gives it to the server it starts
// (AUTOMOTO_LAUNCH_TOKEN) and to its own window only, so the window can sign in
// (HttpOnly session cookie) while other local programs and web pages can't.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const ADDR: &str = "127.0.0.1:8765";

struct Server(Mutex<Option<Child>>);

fn python() -> String {
    std::env::var("AUTOMOTO_PYTHON").unwrap_or_else(|_| {
        if cfg!(target_os = "windows") { "python".into() } else { "python3".into() }
    })
}

fn launch_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::getrandom(&mut buf).expect("no OS random source");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn start_server(token: &str) -> Option<Child> {
    if TcpStream::connect(ADDR).is_ok() {
        return None; // already running (e.g. started from a terminal)
    }
    let home = std::env::var("AUTOMOTO_HOME").unwrap_or_else(|_| ".".into());
    let mut cmd = Command::new(python());
    cmd.args(["-m", "automoto", "serve", "--no-browser", "--port", "8765"])
        .current_dir(home)
        .env("AUTOMOTO_LAUNCH_TOKEN", token)
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
    let token = launch_token();
    let child = start_server(&token);
    // If a server was already running we don't know its token: the window then shows the
    // lock page, and `python -m automoto open` signs in a browser instead.
    let script = if child.is_some() {
        format!("window.__AUTOMOTO_LAUNCH = \"{token}\";")
    } else {
        String::new()
    };
    let app = tauri::Builder::default()
        .manage(Server(Mutex::new(child)))
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("AutoMoto AI")
                .inner_size(1180.0, 800.0)
                .min_inner_size(720.0, 520.0)
                .initialization_script(&script)
                .build()?;
            Ok(())
        })
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
