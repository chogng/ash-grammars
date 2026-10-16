"""Import the exact grammar sources selected by an Ash checkout, without its product state."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tomllib
from urllib.request import urlopen
from urllib.error import HTTPError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def import_sources(ash: Path) -> None:
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--format-version=1"], cwd=ash
        )
    )
    packages = {package["name"]: package for package in metadata["packages"]}
    revision = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ash).decode().strip()
    )
    (ROOT / "sources").mkdir(exist_ok=True)
    (ROOT / "licenses").mkdir(exist_ok=True)
    entries = []
    sources = {}
    queries = {}
    for manifest in sorted((ash / "extensions").glob("*/tree-sitter/grammars.json")):
        for grammar in json.loads(manifest.read_text(encoding="utf-8")):
            package = packages[grammar["source"]["crate"]]
            base = Path(package["manifest_path"]).parent
            if package["name"] not in sources:
                buffer = io.BytesIO()
                file_hashes = {}
                # Normalize metadata so the same bytes produce the same source snapshot.
                with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w") as archive:
                        for file in sorted(base.rglob("*")):
                            if not file.is_file() or any(
                                part
                                in {
                                    ".git",
                                    "target",
                                    "build",
                                    "node_modules",
                                    "test",
                                    "tests",
                                    "testdata",
                                    "test_data",
                                    "corpus",
                                }
                                for part in file.relative_to(base).parts
                            ):
                                continue
                            data = file.read_bytes()
                            member = tarfile.TarInfo(file.relative_to(base).as_posix())
                            member.size = len(data)
                            member.mode = 0o644
                            archive.addfile(member, io.BytesIO(data))
                            file_hashes[member.name] = digest(data)
                data = buffer.getvalue()
                name = f"{package['name']}-{package['version']}.tar.gz"
                (ROOT / "sources" / name).write_bytes(data)
                licenses = [
                    file
                    for file in base.rglob("*")
                    if file.is_file()
                    and file.name.lower().startswith(("license", "copying"))
                ]
                if not licenses:
                    vcs = base / ".cargo_vcs_info.json"
                    source_revision = (
                        json.loads(vcs.read_text(encoding="utf-8"))["git"]["sha1"]
                        if vcs.is_file()
                        else package["source"].rsplit("#", 1)[1]
                    )
                    origin = (
                        package["source"].removeprefix("git+").split("?", 1)[0]
                        if package["source"].startswith("git+")
                        else package["repository"]
                    )
                    repository = origin.removesuffix(".git").replace(
                        "https://github.com/", "https://raw.githubusercontent.com/"
                    )
                    license_file = ROOT / "licenses" / f"{package['name']}-upstream.txt"
                    if not license_file.is_file():
                        for candidate in [
                            "LICENSE",
                            "LICENSE.txt",
                            "LICENSE.md",
                            "COPYING",
                        ]:
                            try:
                                with urlopen(
                                    f"{repository}/{source_revision}/{candidate}",
                                    timeout=30,
                                ) as response:
                                    license_file.write_bytes(response.read())
                                break
                            except HTTPError as error:
                                if error.code != 404:
                                    raise
                        else:
                            license_file.write_text(
                                f"{package['name']} {package['version']}\nSPDX license declaration: {package['license']}\n"
                                f"Source: {origin} at {source_revision}\nAuthors: {', '.join(package['authors'])}\n"
                                "The pinned source declares this license in Cargo.toml and supplies no separate license file.\n"
                                "The source snapshot preserves that original manifest.\n",
                                encoding="utf-8",
                            )
                    licenses = [license_file]
                for index, file in enumerate(sorted(licenses)):
                    (ROOT / "licenses" / f"{package['name']}-{index}.txt").write_bytes(
                        file.read_bytes()
                    )
                sources[package["name"]] = {
                    "version": package["version"],
                    "archive": name,
                    "sha256": digest(data),
                    "origin": package["source"]
                    or f"https://github.com/chogng/ash/tree/{revision}/{base.relative_to(ash).as_posix()}",
                    "license": package["license"],
                    "files": file_hashes,
                }
            source = base / grammar["source"]["root"]
            parser = (source / "src/parser.c").read_text(encoding="utf-8")
            symbols = re.findall(
                r"\bconst TSLanguage\s*\*\s*(tree_sitter_[a-z0-9_]+)\((?:void)?\)",
                parser,
            )
            if len(symbols) != 1:
                raise RuntimeError(
                    f"Expected one grammar entrypoint: {grammar['name']}: {symbols}"
                )
            entries.append(
                {
                    "name": grammar["name"],
                    "crate": package["name"],
                    "root": grammar["source"]["root"],
                    "symbol": symbols[0],
                    "wasm": {
                        key: value
                        for key, value in grammar["wasm"].items()
                        if key in {"splitLexer", "libc"}
                    },
                }
            )
            bindings = Path(
                next(
                    target["src_path"]
                    for target in package["targets"]
                    if "lib" in target["kind"]
                )
            )
            rust = bindings.read_text(encoding="utf-8")
            for key in [
                *grammar["rust"].get("snapshotHighlights", []),
                *grammar["rust"].get("snapshotTags", []),
            ]:
                constant = key.split("::")[1]
                match = re.search(
                    rf"pub const {constant}:\s*&str\s*=\s*include_str!\(\s*\"([^\"]+)\"\s*\)",
                    rust,
                )
                if not match:
                    raise RuntimeError(f"Unsupported upstream query binding: {key}")
                queries[key] = (bindings.parent / match[1]).read_text(encoding="utf-8")
    lock = {
        "schemaVersion": 1,
        "version": tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))[
            "package"
        ]["version"],
        "treeSitterAbi": {"minimum": 13, "maximum": 15},
        "importedFrom": {
            "repository": "https://github.com/chogng/ash",
            "revision": revision,
        },
        "sources": sources,
        "grammars": entries,
    }
    (ROOT / "grammars.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8"
    )
    code = [
        "// Generated by scripts/import_ash.py; source inventory: grammars.lock.json.\nuse tree_sitter_language::LanguageFn;\n",
        'unsafe extern "C" {',
    ]
    code.extend(f"    fn {entry['symbol']}() -> *const ();" for entry in entries)
    code.append(
        "}\n\n/// Grammar identifiers provided by the matching platform archive.\npub const GRAMMARS: &[&str] = &["
    )
    code.extend(f"    {json.dumps(entry['name'])}," for entry in entries)
    code.append(
        "];\n\n/// Returns a process-lifetime language function for a bundled grammar.\npub fn language(name: &str) -> Option<LanguageFn> {\n    match name {"
    )
    code.extend(
        f"        {json.dumps(entry['name'])} => Some(unsafe {{ LanguageFn::from_raw({entry['symbol']}) }}),"
        for entry in entries
    )
    code.append(
        "        _ => None,\n    }\n}\n\n/// Original upstream queries used by Ash's persisted syntax snapshots.\npub fn query(binding: &str) -> Option<&'static str> {\n    match binding {"
    )
    code.extend(
        f"        {json.dumps(key)} => Some({json.dumps(value, ensure_ascii=False)}),"
        for key, value in sorted(queries.items())
    )
    code.append("        _ => None,\n    }\n}\n")
    (ROOT / "src/languages.generated.rs").write_text("\n".join(code), encoding="utf-8")
    print(f"Imported {len(entries)} grammars from {len(sources)} pinned sources")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ash", type=Path)
    import_sources(parser.parse_args().ash.resolve())
