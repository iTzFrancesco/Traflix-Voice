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

    tauri_build::build()
}
