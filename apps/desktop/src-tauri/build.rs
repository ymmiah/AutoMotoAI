fn main() {
    // Only these commands exist for the app's own sign-in screen; capabilities/default.json grants them
    // to the bundled page only (server pages are remote and get nothing).
    let commands: &[&str] = &["app_info", "sign_in", "open_account", "sign_out", "start_local", "install_engine", "open_link"];
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(commands)),
    )
    .expect("failed to run the Tauri build script");
}
