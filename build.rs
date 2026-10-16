use sha2::Digest;
use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-env-changed=ASH_GRAMMARS_LIB_DIR");
    let target = std::env::var("TARGET").expect("Cargo target");
    let directory = std::env::var_os("ASH_GRAMMARS_LIB_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(format!(".build/prepared/{target}/lib")));
    let manifest_path = directory.join("bundle.json");
    let manifest: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&manifest_path)
            .expect("Run python scripts/grammars.py prepare --target <target> before Cargo"),
    )
    .expect("Grammar bundle manifest");
    let source_digest = format!(
        "{:x}",
        sha2::Sha256::digest(include_bytes!("grammars.lock.json"))
    );
    assert_eq!(
        manifest["sourceLockSha256"].as_str(),
        Some(source_digest.as_str()),
        "Grammar source identity mismatch"
    );
    assert_eq!(
        manifest["target"].as_str(),
        Some(target.as_str()),
        "Grammar target mismatch"
    );
    assert_eq!(
        manifest["version"].as_str(),
        Some(env!("CARGO_PKG_VERSION")),
        "Grammar version mismatch"
    );
    let name = if target.contains("windows-msvc") {
        "ash_grammars.lib"
    } else {
        "libash_grammars.a"
    };
    let archive = directory.join(name);
    let bytes = std::fs::read(&archive).expect("Grammar static library");
    let digest = format!("{:x}", sha2::Sha256::digest(bytes));
    assert_eq!(
        manifest["sha256"].as_str(),
        Some(digest.as_str()),
        "Grammar library checksum mismatch"
    );
    println!("cargo:rerun-if-changed={}", manifest_path.display());
    println!("cargo:rerun-if-changed={}", archive.display());
    println!(
        "cargo:rustc-link-search={}",
        directory
            .canonicalize()
            .expect("Grammar library directory")
            .display()
    );
    println!("cargo:rustc-link-lib=static=ash_grammars");
}
