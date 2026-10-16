fn main() {
    println!("cargo:rerun-if-env-changed=ASH_GRAMMAR_SOURCE_LIST");
    let list = std::env::var("ASH_GRAMMAR_SOURCE_LIST").expect("Run scripts/grammars.py build");
    println!("cargo:rerun-if-changed={list}");
    let mut groups =
        std::collections::BTreeMap::<std::path::PathBuf, Vec<std::path::PathBuf>>::new();
    for line in std::fs::read_to_string(list)
        .expect("Grammar source inventory")
        .lines()
    {
        let file = std::path::Path::new(line);
        groups
            .entry(file.parent().expect("Source directory").to_path_buf())
            .or_default()
            .push(file.to_path_buf());
        println!("cargo:rerun-if-changed={line}");
    }
    let mut objects = Vec::new();
    for (directory, files) in groups {
        // Generated parser headers differ across grammar ABI versions. Each
        // grammar must compile with its own include directory before archiving.
        let mut compiler = cc::Build::new();
        compiler
            .std("c11")
            .opt_level(2)
            .debug(false)
            .warnings(false);
        compiler.flag_if_supported("-utf-8");
        if std::env::var("TARGET")
            .expect("Cargo target")
            .contains("windows-msvc")
        {
            compiler.static_crt(true);
        }
        compiler.include(directory).files(files);
        objects.extend(compiler.compile_intermediates());
    }
    cc::Build::new().objects(objects).compile("ash_grammars");
}
