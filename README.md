# Ash grammars

Pinned Tree-sitter grammars compiled ahead of Ash's product builds. A release
contains 48 parsers as eight platform static-library archives, a portable WASM
archive, a machine-readable artifact manifest and SHA-256 checksums. Consumers
link prepared libraries; ordinary Cargo builds never compile grammar C.

`grammars.lock.json` owns the source inventory. It records each upstream version
or Git revision, the complete source snapshot's SHA-256 and individual file
hashes. `sources/` contains compressed, reproducible source snapshots so the
producer can build offline after fetching its locked Rust build dependencies.
The six Ash-owned grammar bindings record the importing Ash revision and path.
Upstream license texts and declarations are preserved under `licenses/` and in
the source snapshots. The repository's MIT license applies to its own tooling
and binding implementation, not to third-party grammar code.

## Use a release

Download `manifest.json` from the matching release and pin its SHA-256 in the
consuming repository alongside the selected release. The prepare command checks
the release version, source-lock identity, archive size and SHA-256. Its output
includes `lib/bundle.json`; the Rust build script independently checks the
target, version and library digest before linking.

```sh
python scripts/grammars.py prepare --target x86_64-pc-windows-msvc --manifest manifest.json
cargo test --locked --target x86_64-pc-windows-msvc
```

A separate Cargo consumer depends on `ash-grammars` from this Git repository,
pins its revision through Cargo.lock, and sets `ASH_GRAMMARS_LIB_DIR` to the
absolute `lib` directory unpacked by its own preparation owner. No Rust compiler
version matching is required for the archive: the distributed objects contain
C grammar code, and the thin Rust binding compiles with the consumer's toolchain.
Windows objects use the static MSVC CRT; Linux GNU, Linux musl and macOS objects
are distinct artifacts. macOS targets use a deployment target of 11.0; GNU
artifacts use the libc baseline of their pinned CI runner image.

```rust
let language = ash_grammars::language("typescript").expect("bundled grammar");
parser.set_language(&language.into())?;
```

`GRAMMARS` lists the identifiers. `query` exposes only the upstream query
constants used by Ash's persisted syntax snapshots. Editor aliases, user
settings, highlight extensions and language-service state remain in Ash.

The WASM archive contains `grammars.json` with each module's name, relative path,
size and SHA-256, plus the modules under `wasm/`. These side modules target the
Tree-sitter WASM loader; they do not contain the parser runtime itself.

## Build and validate

Python 3.12+, the pinned Rust toolchain, and a C compiler for the selected target
are required. The WASM producer also uses Node 24 and WASI SDK 29. Every build
checks source snapshot and extracted-file hashes before invoking the compiler.

```sh
python scripts/grammars.py verify
python -m unittest discover -s tests -v
python scripts/grammars.py build --target x86_64-pc-windows-msvc
cargo test --locked --target x86_64-pc-windows-msvc
```

```sh
python scripts/grammars.py wasm --sdk /opt/wasi-sdk-29.0-x86_64-linux
npm ci --ignore-scripts
node scripts/check-wasm.mjs
```

Each static-library job loads and parses with all 48 grammars on its target
host. Windows ARM64 receives a cross-target link check. The WASM job loads and
parses with all 48 modules in `web-tree-sitter`. Archive tests reject tampering,
traversal and links. Release aggregation requires every target and the WASM
archive; only successful release runs can publish.

## Update the inventory

After intentionally updating Ash's grammar selections, import that exact
checkout with `python scripts/import_ash.py ../ash`. The importer preserves
third-party source and license notices and generates the Rust entrypoint map.
Review source, license and query changes, then format the Rust files and run the
checks above. Bump the root crate, producer and source-lock versions together.
Create a new version tag only after that source is committed; published release
assets must not be replaced. Updating a grammar requires a new release and a
reviewed consumer lock update. Source compilation is an explicit producer task,
never an automatic fallback for a missing or invalid consumer artifact.
