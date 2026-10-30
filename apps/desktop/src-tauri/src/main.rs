// AutoMoto AI desktop app (Windows first; macOS and Linux build from the same code).
//
// The window opens on a small sign-in screen that ships inside the app (dist/). From there:
//   * AutoMoto account: sign in to an AutoMoto account server (hosted mode). Chats, files, memory and
//     usage time live on that server, so every device signed in to the account sees the same things.
//   * Local mode: no account; start (or open) the AutoMoto engine installed on this computer.
// Either way the window then shows the normal AutoMoto page. Those pages get no access to the app's
// native commands: only the bundled sign-in screen can call them (capabilities/default.json, and every
// command checks the caller again).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod account;
mod local;
mod settings;

use std::process::Child;
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_opener::OpenerExt;
use url::Url;

/// Default account server baked in at build time (repository variable AUTOMOTO_DEFAULT_SERVER in CI).
const DEFAULT_SERVER: Option<&str> = option_env!("AUTOMOTO_DEFAULT_SERVER");
const GUIDE: &str = "https://ymmiah.github.io/AutoMotoAI/GUI-GUIDE.html";
const LINKS: &[(&str, &str)] = &[
    ("guide", GUIDE),
    ("app-guide", "https://ymmiah.github.io/AutoMotoAI/GUI-GUIDE.html#0-the-windows-app"),
    ("install", "https://ymmiah.github.io/AutoMotoAI/INSTALL.html#windows-app"),
    ("hosting", "https://ymmiah.github.io/AutoMotoAI/HOSTING.html"),
    ("releases", "https://github.com/ymmiah/AutoMotoAI/releases/latest"),
];

struct AppState {
    home: Mutex<Option<Url>>,        // the bundled sign-in screen
    server: Mutex<Option<Url>>,      // the account server the window may show
    local_child: Mutex<Option<Child>>,
    launch_token: String,            // for the local engine this app starts
}

fn random_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::getrandom(&mut buf).expect("no OS random source");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn is_app_page(u: &Url) -> bool {
    u.scheme() == "tauri" || matches!(u.host_str(), Some("tauri.localhost"))
}

fn same_origin(a: &Url, b: &Url) -> bool {
    a.origin() == b.origin()
}

/// Where the window may go. Everything else opens in the normal web browser.
fn navigation_allowed(app: &AppHandle, u: &Url) -> bool {
    if is_app_page(u) || u.as_str() == "about:blank" {
        return true;
    }
    let st = app.state::<AppState>();
    if let Some(s) = st.server.lock().unwrap().as_ref() {
        if same_origin(s, u) {
            return true;
        }
    }
    let local = local::base_url();
    if same_origin(&local, u) || (u.scheme() == "http" && u.host_str() == Some("localhost") && u.port() == Some(local::PORT)) {
        return true;
    }
    if matches!(u.scheme(), "https" | "http" | "mailto") {
        let _ = app.opener().open_url(u.as_str(), None::<&str>);
    }
    false
}

fn main_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("main").ok_or_else(|| "no window".to_string())
}

/// Native commands are for the bundled sign-in screen only, never for a server's pages.
fn check_caller(w: &tauri::Webview) -> Result<(), String> {
    match w.url() {
        Ok(u) if is_app_page(&u) => Ok(()),
        _ => Err("not allowed from this page".into()),
    }
}

fn go_home(app: &AppHandle, note: &str) {
    let st = app.state::<AppState>();
    let home = st.home.lock().unwrap().clone();
    if let (Some(mut h), Ok(w)) = (home, main_window(app)) {
        h.set_query(Some(&format!("home=1{}", if note.is_empty() { String::new() } else { format!("&note={note}") })));
        let _ = w.navigate(h);
    }
}

fn device_default_name() -> String {
    let host = std::env::var("COMPUTERNAME").or_else(|_| std::env::var("HOSTNAME")).unwrap_or_else(|_| "This PC".into());
    let os = if cfg!(windows) { "Windows" } else if cfg!(target_os = "macos") { "Mac" } else { "Linux" };
    format!("{host} ({os} app)")
}

// -- commands for the sign-in screen -------------------------------------------------------------
#[tauri::command]
fn app_info(app: AppHandle, webview: tauri::Webview) -> Result<Value, String> {
    check_caller(&webview)?;
    let s = settings::load(&app);
    let server = if s.server.is_empty() { DEFAULT_SERVER.unwrap_or("").to_string() } else { s.server.clone() };
    let signed_in = account::server_origin(&server).ok().and_then(|o| account::load_token(&o)).is_some();
    let engine = local::find_engine();
    Ok(json!({
        "version": env!("CARGO_PKG_VERSION"),
        "default_server": DEFAULT_SERVER.unwrap_or(""),
        "server": server,
        "username": s.username,
        "device_name": if s.device_name.is_empty() { device_default_name() } else { s.device_name },
        "mode": s.mode,
        "signed_in": signed_in,
        "engine": engine.as_ref().map(|(p, how)| json!({"path": p.display().to_string(), "how": how})),
        "engine_running": local::port_busy(),
        "windows": cfg!(windows),
        "mac": cfg!(target_os = "macos"),
    }))
}

#[tauri::command]
async fn sign_in(app: AppHandle, webview: tauri::Webview, server: String, username: String, password: String,
                 device_name: String) -> Result<Value, String> {
    check_caller(&webview)?;
    let origin = account::server_origin(&server)?;
    let user = username.trim().to_lowercase();
    if user.is_empty() || password.is_empty() {
        return Err("Type your username and password".into());
    }
    let name = if device_name.trim().is_empty() { device_default_name() } else { device_name.trim().to_string() };
    let got = account::device_login(&origin, &user, &password, &name).await?;
    drop(password);
    account::save_token(&origin, &got.token)?;
    let mut s = settings::load(&app);
    s.server = account::origin_key(&origin);
    s.username = user;
    s.device_name = name;
    s.mode = "account".into();
    settings::save(&app, &s)?;
    Ok(json!({"ok": true, "user": got.user}))
}

#[tauri::command]
async fn open_account(app: AppHandle, webview: tauri::Webview) -> Result<Value, String> {
    check_caller(&webview)?;
    let mut s = settings::load(&app);
    let origin = account::server_origin(&s.server)?;
    let Some(token) = account::load_token(&origin) else {
        return Ok(json!({"signed_out": true, "message": "Sign in to continue"}));
    };
    match account::launch_url(&origin, &token).await? {
        account::Launch::SignedOut(msg) => {
            account::forget_token(&origin);
            Ok(json!({"signed_out": true, "message": msg}))
        }
        account::Launch::Url(link) => {
            *app.state::<AppState>().server.lock().unwrap() = Some(origin);
            s.mode = "account".into();
            let _ = settings::save(&app, &s);
            main_window(&app)?.navigate(link).map_err(|e| e.to_string())?;
            Ok(json!({"ok": true}))
        }
    }
}

#[tauri::command]
async fn sign_out(app: AppHandle, webview: tauri::Webview) -> Result<Value, String> {
    check_caller(&webview)?;
    sign_out_inner(&app).await;
    Ok(json!({"ok": true}))
}

async fn sign_out_inner(app: &AppHandle) {
    let mut s = settings::load(app);
    if let Ok(origin) = account::server_origin(&s.server) {
        if let Some(tok) = account::load_token(&origin) {
            account::device_logout(&origin, &tok).await; // the server forgets this device too
        }
        account::forget_token(&origin);
    }
    *app.state::<AppState>().server.lock().unwrap() = None;
    s.mode.clear();
    let _ = settings::save(app, &s);
}

#[tauri::command]
async fn start_local(app: AppHandle, webview: tauri::Webview) -> Result<Value, String> {
    check_caller(&webview)?;
    let link = start_local_inner(&app).await?;
    match link {
        None => Ok(json!({"missing": true})),
        Some(url) => {
            let mut s = settings::load(&app);
            s.mode = "local".into();
            let _ = settings::save(&app, &s);
            main_window(&app)?.navigate(url).map_err(|e| e.to_string())?;
            Ok(json!({"ok": true}))
        }
    }
}

async fn start_local_inner(app: &AppHandle) -> Result<Option<Url>, String> {
    let st = app.state::<AppState>();
    let ours = st.local_child.lock().unwrap().is_some();
    if local::port_busy() && !ours {
        return local::launch_running().await.map(Some);
    }
    if !ours {
        let Some((python, _)) = local::find_engine() else { return Ok(None) };
        let log = app.path().app_log_dir().ok().map(|d| {
            let _ = std::fs::create_dir_all(&d);
            d.join("local-engine.log")
        });
        let child = local::start(&python, &st.launch_token, log)?;
        *st.local_child.lock().unwrap() = Some(child);
    }
    let mut child = st.local_child.lock().unwrap().take();
    let res = local::wait_healthy(&mut child, 90).await;
    *st.local_child.lock().unwrap() = child;
    res?;
    let mut url = local::base_url();
    url.set_query(Some(&format!("launch={}&app=1", st.launch_token)));
    Ok(Some(url))
}

#[tauri::command]
fn install_engine(app: AppHandle, webview: tauri::Webview) -> Result<Value, String> {
    check_caller(&webview)?;
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let script = app
            .path()
            .resolve("resources/install.ps1", tauri::path::BaseDirectory::Resource)
            .map_err(|e| e.to_string())?;
        // a visible PowerShell window: the user sees (and answers) every step of the official installer
        std::process::Command::new("powershell.exe")
            .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File"])
            .arg(script)
            .creation_flags(0x0000_0010) // CREATE_NEW_CONSOLE
            .spawn()
            .map_err(|e| format!("Couldn't open PowerShell: {e}"))?;
        Ok(json!({"started": true}))
    }
    #[cfg(not(windows))]
    {
        let _ = app;
        Ok(json!({"started": false, "command": "bash scripts/install.sh"}))
    }
}

#[tauri::command]
fn open_link(app: AppHandle, webview: tauri::Webview, which: String) -> Result<(), String> {
    check_caller(&webview)?;
    let url = LINKS.iter().find(|(k, _)| *k == which).map(|(_, u)| *u).ok_or("unknown link")?;
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

// -- updates (signed; verified by the updater plugin with the public key in tauri.conf.json) ---------------
#[cfg(desktop)]
async fn check_updates(app: AppHandle, interactive: bool) {
    use tauri_plugin_updater::UpdaterExt;
    let res = match app.updater() {
        Ok(u) => u.check().await,
        Err(e) => Err(e),
    };
    match res {
        Ok(Some(update)) => {
            let version = update.version.clone();
            let app2 = app.clone();
            app.dialog()
                .message(format!("AutoMoto AI {version} is available (you have {}).\n\nInstall it now? The app restarts when it's done.",
                                 env!("CARGO_PKG_VERSION")))
                .title("Update available")
                .buttons(MessageDialogButtons::OkCancelCustom("Install update".into(), "Later".into()))
                .show(move |yes| {
                    if !yes {
                        return;
                    }
                    tauri::async_runtime::spawn(async move {
                        if let Err(e) = update.download_and_install(|_, _| {}, || {}).await {
                            app2.dialog().message(format!("The update failed: {e}")).title("Update").show(|_| {});
                            return;
                        }
                        app2.restart();
                    });
                });
        }
        Ok(None) => {
            if interactive {
                app.dialog().message(format!("You have the latest version ({}).", env!("CARGO_PKG_VERSION"))).title("Updates").show(|_| {});
            }
        }
        Err(e) => {
            if interactive {
                app.dialog().message(format!("Couldn't check for updates: {e}")).title("Updates").show(|_| {});
            }
        }
    }
}

fn build_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let file = Submenu::with_items(app, "AutoMoto", true, &[
        &MenuItem::with_id(app, "home", "Sign-in screen / switch mode", true, Some("CmdOrCtrl+Shift+H"))?,
        &MenuItem::with_id(app, "reload", "Reload", true, Some("CmdOrCtrl+R"))?,
        &PredefinedMenuItem::separator(app)?,
        &MenuItem::with_id(app, "updates", "Check for updates…", true, None::<&str>)?,
        &MenuItem::with_id(app, "signout", "Sign out of this device", true, None::<&str>)?,
        &PredefinedMenuItem::separator(app)?,
        &MenuItem::with_id(app, "quit", "Quit AutoMoto AI", true, Some("CmdOrCtrl+Q"))?,
    ])?;
    let edit = Submenu::with_items(app, "Edit", true, &[
        &PredefinedMenuItem::undo(app, None)?,
        &PredefinedMenuItem::redo(app, None)?,
        &PredefinedMenuItem::separator(app)?,
        &PredefinedMenuItem::cut(app, None)?,
        &PredefinedMenuItem::copy(app, None)?,
        &PredefinedMenuItem::paste(app, None)?,
        &PredefinedMenuItem::select_all(app, None)?,
    ])?;
    let help = Submenu::with_items(app, "Help", true, &[
        &MenuItem::with_id(app, "guide", "Step-by-step guide", true, Some("F1"))?,
        &MenuItem::with_id(app, "log", "Open the local engine log", true, None::<&str>)?,
        &MenuItem::with_id(app, "about", "About AutoMoto AI", true, None::<&str>)?,
    ])?;
    Menu::with_items(app, &[&file, &edit, &help])
}

fn on_menu(app: &AppHandle, id: &str) {
    match id {
        "home" => go_home(app, ""),
        "quit" => app.exit(0),
        "reload" => {
            if let Ok(w) = main_window(app) {
                let _ = w.reload();
            }
        }
        "updates" => {
            #[cfg(desktop)]
            tauri::async_runtime::spawn(check_updates(app.clone(), true));
        }
        "signout" => {
            let app = app.clone();
            tauri::async_runtime::spawn(async move {
                sign_out_inner(&app).await;
                go_home(&app, "signed-out");
            });
        }
        "guide" => {
            let _ = app.opener().open_url(GUIDE, None::<&str>);
        }
        "log" => {
            if let Ok(d) = app.path().app_log_dir() {
                let _ = std::fs::create_dir_all(&d);
                let _ = app.opener().open_path(d.display().to_string(), None::<&str>);
            }
        }
        "about" => {
            app.dialog()
                .message(format!("AutoMoto AI {}\n\nYour AI cousin - an agent that actually does the work.\n\n\
                                  Yasin Mohammed Miah, Student of BCU, BSc Computing Top-Up (Hons)\nMIT licence · github.com/ymmiah/AutoMotoAI",
                                 env!("CARGO_PKG_VERSION")))
                .title("About AutoMoto AI")
                .show(|_| {});
        }
        _ => {}
    }
}

fn main() {
    let local_flag = std::env::args().any(|a| a == "--local");
    let mut builder = tauri::Builder::default();
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Ok(w) = main_window(app) {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }));
    }
    let app = builder
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(AppState {
            home: Mutex::new(None),
            server: Mutex::new(None),
            local_child: Mutex::new(None),
            launch_token: random_token(),
        })
        .invoke_handler(tauri::generate_handler![app_info, sign_in, open_account, sign_out, start_local, install_engine, open_link])
        .setup(move |app| {
            #[cfg(desktop)]
            app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;
            let handle = app.handle().clone();
            let nav = handle.clone();
            let newwin = handle.clone();
            let start = if local_flag { "index.html?auto=local" } else { "index.html" };
            let menu = build_menu(&handle)?;
            let w = WebviewWindowBuilder::new(app, "main", WebviewUrl::App(start.into()))
                .title("AutoMoto AI")
                .inner_size(1200.0, 820.0)
                .min_inner_size(720.0, 520.0)
                .menu(menu)
                .on_navigation(move |u| navigation_allowed(&nav, u))
                .on_new_window(move |u, _features| {
                    // links with target=_blank (guide, chat links) open in the normal browser
                    if matches!(u.scheme(), "https" | "http" | "mailto") {
                        let _ = newwin.opener().open_url(u.as_str(), None::<&str>);
                    }
                    tauri::webview::NewWindowResponse::Deny
                })
                .build()?;
            if let Ok(mut u) = w.url() {
                u.set_query(None);
                u.set_fragment(None);
                *handle.state::<AppState>().home.lock().unwrap() = Some(u);
            }
            handle.on_menu_event(|app, ev| on_menu(app, ev.id().as_ref()));
            #[cfg(all(desktop, not(debug_assertions)))]
            {
                let h = handle.clone();
                tauri::async_runtime::spawn(async move {
                    std::thread::sleep(std::time::Duration::from_secs(4));
                    check_updates(h, false).await;
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the AutoMoto app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(c) = handle.state::<AppState>().local_child.lock().unwrap().take() {
                local::stop(c); // stop the local engine this app started
            }
        }
    });
}
