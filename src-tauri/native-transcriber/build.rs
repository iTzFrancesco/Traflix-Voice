use std::{env, fs, path::PathBuf};
fn main() {
    let runtime = env::var("DEP_TRANSCRIBE_CPP_RUNTIME_DIR").expect("native runtime directory");
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    fs::write(out.join("runtime-path.txt"), &runtime).unwrap();
    if env::var("CARGO_CFG_TARGET_OS").unwrap() == "windows" {
        if let Some(sdk) = env::var_os("VULKAN_SDK") {
            println!(
                "cargo:rustc-link-search=native={}",
                PathBuf::from(sdk).join("Lib").display()
            );
        }
    }
    // The shipped executable resolves its libraries beside itself.
    if env::var("CARGO_CFG_TARGET_OS").unwrap() == "linux" {
        println!("cargo:rustc-link-arg=-Wl,-rpath,$ORIGIN");
        println!("cargo:rustc-link-arg=-Wl,-rpath,{runtime}");
    }
    println!("cargo:rerun-if-env-changed=DEP_TRANSCRIBE_CPP_RUNTIME_DIR");
}
