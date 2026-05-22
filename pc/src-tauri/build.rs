// CyberStream PC build script
//
// Two jobs:
//   1. Run tauri-build (icon resources, capability codegen).
//   2. On Windows, hook the linker to libmpv-2.lib that we ship in
//      ../vendor/mpv-dev/. This lets src/native_player/ffi.rs declare
//      the libmpv C ABI via `extern "C"` blocks and let the linker
//      resolve them against the import library.
//
// The matching DLL (libmpv-2.dll) must sit next to the final exe at
// runtime — handled by the MSI bundler via tauri.conf.json's
// `bundle.resources`.

fn main() {
    tauri_build::build();

    #[cfg(target_os = "windows")]
    {
        let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();
        let vendor = std::path::Path::new(&manifest_dir)
            .join("..")
            .join("vendor")
            .join("mpv-dev");
        let canonical = vendor
            .canonicalize()
            .expect("pc/vendor/mpv-dev not found — see plan v3 §3 (libmpv-2 deps)");
        // Tell rustc where to find libmpv-2.lib at link time.
        println!("cargo:rustc-link-search=native={}", canonical.display());
        // The import library is named libmpv-2.lib (the leading `lib` is
        // part of the file name on MSVC). `cargo:rustc-link-lib` adds the
        // `.lib` extension itself, so we pass the bare stem.
        println!("cargo:rustc-link-lib=dylib=libmpv-2");
        // Re-run if the vendor folder changes (e.g. someone bumps libmpv).
        println!("cargo:rerun-if-changed={}", canonical.display());

        // Copy libmpv-2.dll next to the produced exe so dev runs (and
        // `cargo tauri dev`) can find it. For MSI bundling, the same DLL
        // is also referenced via tauri.conf.json `bundle.resources`,
        // which lays it out next to the installed exe.
        if let Ok(out_dir) = std::env::var("OUT_DIR") {
            let dll = canonical.join("libmpv-2.dll");
            if dll.exists() {
                // OUT_DIR is .../target/debug/build/<crate>-<hash>/out
                // We need to walk up to .../target/debug/ where the exe
                // actually lives.
                let target_dir = std::path::Path::new(&out_dir)
                    .ancestors()
                    .nth(3) // out → <crate>-<hash> → build → debug
                    .map(|p| p.to_path_buf());
                if let Some(target) = target_dir {
                    let dest = target.join("libmpv-2.dll");
                    let needs_copy = match (std::fs::metadata(&dll), std::fs::metadata(&dest)) {
                        (Ok(src), Ok(dst)) => {
                            src.len() != dst.len()
                                || src.modified().ok() > dst.modified().ok()
                        }
                        _ => true,
                    };
                    if needs_copy {
                        let _ = std::fs::copy(&dll, &dest);
                    }
                }
            }
        }
    }
}
