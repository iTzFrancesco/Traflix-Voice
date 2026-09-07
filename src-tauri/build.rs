fn main() {
    // Copy WebView2Loader.dll to the manifest directory so it can be bundled as a resource.
    // The DLL is produced by webview2-com-sys during its own build script.
    let dll_name = "WebView2Loader.dll";
    let out_dir = std::env::var("OUT_DIR").unwrap();
    let profile = std::env::var("PROFILE").unwrap_or_else(|_| "release".into());
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();

    // Walk up from OUT_DIR to find the profile-level build output directory
    let target_dir = std::path::Path::new(&out_dir)
        .ancestors()
        .find(|p| p.file_name().and_then(|n| n.to_str()) == Some(&profile))
        .unwrap_or_else(|| std::path::Path::new(&out_dir).parent().unwrap());

    let dll_src = target_dir.join(dll_name);
    let dll_dst = std::path::Path::new(&manifest_dir).join(dll_name);

    if dll_src.exists() {
        std::fs::copy(&dll_src, &dll_dst).ok();
        println!("cargo:rerun-if-changed={}", dll_src.display());
    }

    // The Android runtime plugins are implemented in the generated Tauri
    // project, so their commands must still be declared in the application
    // ACL. Without this manifest Tauri rejects every `plugin:voice-runtime`
    // invocation before the native plugin can handle it.
    const VOICE_RUNTIME_COMMANDS: &[&str] = &[
        "openAndroidSettings",
        "setRecordingMode",
        "getRecordingMode",
        "getRuntimeState",
        "setGroqApiKey",
        "setTranscriptionLanguage",
    ];
    const MOBILE_UPDATE_COMMANDS: &[&str] = &["checkMobileUpdate", "installMobileUpdate"];

    let attributes = tauri_build::Attributes::new()
        .plugin(
            "voice-runtime",
            tauri_build::InlinedPlugin::new()
                .commands(VOICE_RUNTIME_COMMANDS)
                .default_permission(tauri_build::DefaultPermissionRule::AllowAllCommands),
        )
        .plugin(
            "mobile-update",
            tauri_build::InlinedPlugin::new()
                .commands(MOBILE_UPDATE_COMMANDS)
                .default_permission(tauri_build::DefaultPermissionRule::AllowAllCommands),
        );

    tauri_build::try_build(attributes).expect("failed to run Tauri build script")
}
