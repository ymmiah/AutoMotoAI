// One AutoMoto account on every device: sign in to the account server (AutoMoto's hosted mode) once,
// keep a revocable device token in the OS credential store, and open the normal AutoMoto page in this
// window with a one-time link. The password is sent once, over HTTPS, and never stored.
use std::time::Duration;

use serde_json::{json, Value};
use url::Url;

pub const KEYRING_SERVICE: &str = "AutoMoto AI";

/// Normalise what the user typed into an origin. HTTPS is required, except for this computer itself.
pub fn server_origin(input: &str) -> Result<Url, String> {
    let raw = input.trim().trim_end_matches('/');
    if raw.is_empty() {
        return Err("Type your AutoMoto server address, e.g. https://automoto.example.org".into());
    }
    let with_scheme = if raw.contains("://") { raw.to_string() } else { format!("https://{raw}") };
    let u = Url::parse(&with_scheme).map_err(|_| format!("\"{raw}\" is not a web address"))?;
    if !u.username().is_empty() || u.password().is_some() {
        return Err("The server address must not contain a user name or password".into());
    }
    let host = u.host_str().unwrap_or("").to_ascii_lowercase();
    let local = matches!(host.as_str(), "localhost" | "127.0.0.1" | "[::1]" | "::1");
    match u.scheme() {
        "https" => {}
        "http" if local => {}
        "http" => return Err("Use https:// - your password and device key must not travel unencrypted".into()),
        _ => return Err("The server address must start with https://".into()),
    }
    if host.is_empty() {
        return Err("The server address has no host name".into());
    }
    let mut origin = u.clone();
    origin.set_path("/");
    origin.set_query(None);
    origin.set_fragment(None);
    Ok(origin)
}

pub fn origin_key(u: &Url) -> String {
    u.origin().ascii_serialization()
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(25))
        .connect_timeout(Duration::from_secs(10))
        .redirect(reqwest::redirect::Policy::none()) // never resend credentials to another address
        .user_agent(concat!("AutoMoto-Desktop/", env!("CARGO_PKG_VERSION")))
        .build()
        .map_err(|e| e.to_string())
}

fn detail(v: &Value, status: reqwest::StatusCode) -> String {
    match v.get("detail") {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Object(o)) => o.get("message").and_then(|m| m.as_str()).unwrap_or("request refused").to_string(),
        _ => format!("the server answered {status}"),
    }
}

async fn post(url: Url, token: Option<&str>, body: Value) -> Result<(reqwest::StatusCode, Value), String> {
    let mut req = client()?.post(url).json(&body);
    if let Some(t) = token {
        req = req.bearer_auth(t);
    }
    let resp = req.send().await.map_err(|e| {
        if e.is_connect() || e.is_timeout() {
            "Can't reach the AutoMoto server. Check the address and your internet connection.".to_string()
        } else {
            format!("Network error: {e}")
        }
    })?;
    let status = resp.status();
    if status.is_redirection() {
        return Err("The server redirected the request - check the address (it should be the AutoMoto page itself)".into());
    }
    let v: Value = resp.json().await.unwrap_or(Value::Null);
    Ok((status, v))
}

pub struct SignedIn {
    pub token: String,
    pub user: Value,
}

pub async fn device_login(origin: &Url, username: &str, password: &str, device: &str) -> Result<SignedIn, String> {
    let url = origin.join("api/auth/device/login").map_err(|e| e.to_string())?;
    let platform = if cfg!(windows) { "windows" } else if cfg!(target_os = "macos") { "macos" } else { "linux" };
    let (status, v) = post(url, None, json!({"username": username, "password": password,
                                              "device_name": device, "platform": platform})).await?;
    if status == reqwest::StatusCode::NOT_FOUND {
        return Err("That address is not an AutoMoto account server (hosted mode is off, or it is older than 5.6)".into());
    }
    if !status.is_success() {
        return Err(detail(&v, status));
    }
    let token = v.get("token").and_then(|t| t.as_str()).unwrap_or("").to_string();
    if !token.starts_with("amd_") {
        return Err("The server sent no device key".into());
    }
    Ok(SignedIn { token, user: v.get("user").cloned().unwrap_or(Value::Null) })
}

pub enum Launch {
    Url(Url),
    SignedOut(String),
}

pub async fn launch_url(origin: &Url, token: &str) -> Result<Launch, String> {
    let url = origin.join("api/auth/device/launch").map_err(|e| e.to_string())?;
    let (status, v) = post(url, Some(token), json!({})).await?;
    if status == reqwest::StatusCode::UNAUTHORIZED {
        return Ok(Launch::SignedOut(detail(&v, status)));
    }
    if !status.is_success() {
        return Err(detail(&v, status));
    }
    let path = v.get("path").and_then(|p| p.as_str()).unwrap_or("");
    if !path.starts_with("/?device_launch=") {
        return Err("The server sent an unexpected link".into());
    }
    let full = origin.join(path).map_err(|e| e.to_string())?;
    Ok(Launch::Url(full))
}

pub async fn device_logout(origin: &Url, token: &str) {
    if let Ok(url) = origin.join("api/auth/device/logout") {
        let _ = post(url, Some(token), json!({})).await;
    }
}

// -- the OS credential store (Windows Credential Manager, macOS Keychain) ------------------------------
pub fn save_token(origin: &Url, token: &str) -> Result<(), String> {
    keyring::Entry::new(KEYRING_SERVICE, &origin_key(origin))
        .and_then(|e| e.set_password(token))
        .map_err(|e| format!("Couldn't save the device key in the credential store: {e}"))
}

pub fn load_token(origin: &Url) -> Option<String> {
    keyring::Entry::new(KEYRING_SERVICE, &origin_key(origin)).ok()?.get_password().ok()
}

pub fn forget_token(origin: &Url) {
    if let Ok(e) = keyring::Entry::new(KEYRING_SERVICE, &origin_key(origin)) {
        let _ = e.delete_credential();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_is_required_except_for_this_computer() {
        assert_eq!(server_origin("automoto.example.org").unwrap().as_str(), "https://automoto.example.org/");
        assert_eq!(server_origin("https://a.example/some/page?x=1").unwrap().as_str(), "https://a.example/");
        assert_eq!(server_origin("http://127.0.0.1:8766/").unwrap().as_str(), "http://127.0.0.1:8766/");
        assert!(server_origin("http://localhost:8766").is_ok());
        assert!(server_origin("http://automoto.example.org").is_err());
        assert!(server_origin("http://192.168.1.20:8766").is_err());
        assert!(server_origin("https://user:pw@a.example").is_err());
        assert!(server_origin("ftp://a.example").is_err());
        assert!(server_origin("javascript:alert(1)").is_err());
        assert!(server_origin("").is_err());
    }
}
