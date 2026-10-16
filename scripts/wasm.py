"""Compile all locked parsers as portable Tree-sitter side modules."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from grammars import ROOT, load_lock, sha256, source_directories, write_archive


def build_wasm(sdk: Path) -> None:
    lock = load_lock()
    sources = source_directories(lock)
    compiler = sdk.resolve() / "bin/clang"
    archiver = sdk.resolve() / "bin/llvm-ar"
    output = ROOT / ".build/wasm"
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    manifest = {}
    for grammar in lock["grammars"]:
        directory = sources[grammar["crate"]] / grammar["root"]
        staging = ROOT / ".build/wasm-sources" / grammar["name"]
        shutil.copytree(directory, staging, dirs_exist_ok=True)
        parser = staging / "src/parser.c"
        if grammar["wasm"].get("splitLexer"):
            subprocess.run(
                ["node", str(ROOT / "scripts/treeSitterLexer.ts"), str(parser)],
                check=True,
            )
        inputs = [parser]
        if (staging / "src/scanner.c").is_file():
            inputs.append(staging / "src/scanner.c")
        for symbol in grammar["wasm"].get("libc", []):
            if not symbol.isalpha():
                raise ValueError("Invalid WASI libc symbol")
            libc = (
                subprocess.check_output([str(compiler), "-print-file-name=libc.a"])
                .decode()
                .strip()
            )
            member = staging / f"{symbol}.o"
            member.write_bytes(
                subprocess.check_output([str(archiver), "p", libc, f"{symbol}.o"])
            )
            inputs.append(member)
        file = output / f"{grammar['name']}.wasm"
        subprocess.run(
            [
                str(compiler),
                "-o",
                str(file),
                "-fPIC",
                "-shared",
                "-Os",
                f"-Wl,--export={grammar['symbol']}",
                "-Wl,--allow-undefined",
                "-Wl,--no-entry",
                "-nostdlib",
                "-fno-exceptions",
                "-fvisibility=hidden",
                "-I",
                str(staging / "src"),
                *(str(path) for path in inputs),
            ],
            check=True,
        )
        files[f"wasm/{file.name}"] = file
        manifest[grammar["name"]] = {
            "path": f"wasm/{file.name}",
            "size": file.stat().st_size,
            "sha256": sha256(file),
        }
        print(f"Built {grammar['name']}", flush=True)
    metadata = output / "grammars.json"
    metadata.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    files["grammars.json"] = metadata
    files.update(
        {
            f"licenses/{file.name}": file
            for file in (ROOT / "licenses").iterdir()
            if file.is_file()
        }
    )
    write_archive(f"ash-grammars-v{lock['version']}-wasm.tar.gz", files)
