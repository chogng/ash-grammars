"""Build, stage, verify and download the pinned Ash grammar artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/chogng/ash-grammars"
TARGETS = {
    "x86_64-pc-windows-msvc",
    "aarch64-pc-windows-msvc",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl",
}


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def load_lock() -> dict:
    lock = json.loads((ROOT / "grammars.lock.json").read_text(encoding="utf-8"))
    if lock["schemaVersion"] != 1 or not re.fullmatch(
        r"\d+\.\d+\.\d+", lock["version"]
    ):
        raise ValueError("Unsupported grammar source lock")
    names = set()
    symbols = set()
    for name, source in lock["sources"].items():
        if (
            not re.fullmatch(r"tree-sitter-[a-z0-9-]+", name)
            or Path(source["archive"]).name != source["archive"]
            or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
        ):
            raise ValueError("Invalid pinned source")
    for grammar in lock["grammars"]:
        path = PurePosixPath(grammar["root"])
        if (
            grammar["name"] in names
            or grammar["symbol"] in symbols
            or grammar["crate"] not in lock["sources"]
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in grammar["root"]
        ):
            raise ValueError("Invalid or duplicate grammar")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", grammar["name"]) or not re.fullmatch(
            r"tree_sitter_[a-z0-9_]+", grammar["symbol"]
        ):
            raise ValueError("Invalid grammar identifier")
        names.add(grammar["name"])
        symbols.add(grammar["symbol"])
    return lock


def unpack(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    seen = set()
    total = 0
    with tarfile.open(archive, "r:gz") as contents:
        for member in contents:
            path = PurePosixPath(member.name)
            total += member.size
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or ":" in member.name
                or member.name in seen
                or total > 1024 * 1024 * 1024
            ):
                raise ValueError(f"Unsafe archive member: {member.name}")
            seen.add(member.name)
            output = destination.joinpath(*path.parts)
            if not output.resolve().is_relative_to(destination.resolve()):
                raise ValueError(
                    f"Archive destination follows a symlink: {member.name}"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            with contents.extractfile(member) as source, output.open("wb") as sink:
                shutil.copyfileobj(source, sink)


def source_directories(lock: dict) -> dict[str, Path]:
    directories = {}
    for name, source in lock["sources"].items():
        archive = ROOT / "sources" / source["archive"]
        if sha256(archive) != source["sha256"]:
            raise ValueError(f"Source checksum mismatch: {name}")
        destination = ROOT / ".build/sources" / source["sha256"]
        files = source["files"]
        valid = all(
            (destination / path).is_file() and sha256(destination / path) == digest
            for path, digest in files.items()
        )
        if not valid:
            unpack(archive, destination)
        actual = {
            file.relative_to(destination).as_posix()
            for file in destination.rglob("*")
            if file.is_file() and file.name != ".files.json"
        }
        if actual != files.keys() or not all(
            sha256(destination / path) == digest for path, digest in files.items()
        ):
            raise ValueError(
                f"Source cache does not match the locked inventory: {name}"
            )
        directories[name] = destination
    return directories


def write_archive(name: str, files: dict[str, Path]) -> dict:
    output = ROOT / "dist" / name
    output.parent.mkdir(exist_ok=True)
    with (
        output.open("wb") as sink,
        gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as compressed,
    ):
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, path in sorted(files.items()):
                member = tarfile.TarInfo(name)
                member.size = path.stat().st_size
                member.mode = 0o644
                with path.open("rb") as source:
                    archive.addfile(member, source)
    record = {
        "name": output.name,
        "size": output.stat().st_size,
        "sha256": sha256(output),
    }
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def build(target: str) -> None:
    lock = load_lock()
    sources = source_directories(lock)
    files = []
    for grammar in lock["grammars"]:
        directory = sources[grammar["crate"]] / grammar["root"] / "src"
        parser = directory / "parser.c"
        if not parser.is_file():
            raise ValueError(f"Missing parser: {grammar['name']}")
        files.append(parser)
        files.extend(file for file in [directory / "scanner.c"] if file.is_file())
    listing = ROOT / ".build/source-inputs.txt"
    listing.write_text(
        "\n".join(str(file.resolve()) for file in files) + "\n", encoding="utf-8"
    )
    environment = dict(os.environ, ASH_GRAMMAR_SOURCE_LIST=str(listing.resolve()))
    result = subprocess.run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--manifest-path",
            str(ROOT / "producer/Cargo.toml"),
            "--target",
            target,
            "--jobs",
            "2",
            "--message-format=json-render-diagnostics",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        check=False,
    )
    result.check_returncode()
    output = None
    for line in result.stdout.splitlines():
        message = json.loads(line)
        if (
            message.get("reason") == "build-script-executed"
            and "ash-grammar-producer" in message["package_id"]
        ):
            output = Path(message["out_dir"])
    if output is None:
        raise RuntimeError("Cargo did not report the grammar build output")
    name = "ash_grammars.lib" if "windows-msvc" in target else "libash_grammars.a"
    library = output / name
    staging = ROOT / ".build/prepared" / target / "lib"
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(library, staging / name)
    manifest = {
        "version": lock["version"],
        "target": target,
        "sha256": sha256(library),
        "sourceLockSha256": sha256(ROOT / "grammars.lock.json"),
        "grammars": [grammar["name"] for grammar in lock["grammars"]],
    }
    (staging / "bundle.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    packed = {f"lib/{file.name}": file for file in staging.iterdir() if file.is_file()}
    packed.update(
        {
            f"licenses/{file.name}": file
            for file in (ROOT / "licenses").iterdir()
            if file.is_file()
        }
    )
    record = write_archive(f"ash-grammars-v{lock['version']}-{target}.tar.gz", packed)
    print(json.dumps(record))


def download(record: dict, destination: Path, base: str) -> None:
    if (
        Path(record["name"]).name != record["name"]
        or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
        or type(record["size"]) is not int
        or not 0 < record["size"] < 512 * 1024 * 1024
    ):
        raise ValueError("Invalid artifact record")
    if (
        destination.is_file()
        and destination.stat().st_size == record["size"]
        and sha256(destination) == record["sha256"]
    ):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            request = Request(
                f"{base}/{record['name']}", headers={"User-Agent": "ash-grammars"}
            )
            with urlopen(request, timeout=120) as source:
                size = 0
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if size > record["size"]:
                        raise ValueError("Artifact exceeds locked size")
                    temporary.write(block)
            temporary.flush()
            if size != record["size"] or sha256(path) != record["sha256"]:
                raise ValueError("Artifact checksum mismatch")
        finally:
            temporary.close()
            if path.exists() and (
                path.stat().st_size != record["size"]
                or sha256(path) != record["sha256"]
            ):
                path.unlink()
    path.replace(destination)


def prepare(target: str, manifest_path: Path) -> None:
    lock = load_lock()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["version"] != lock["version"] or manifest["sourceLockSha256"] != sha256(
        ROOT / "grammars.lock.json"
    ):
        raise ValueError("Artifact manifest does not match source lock")
    record = manifest["targets"][target]
    archive = ROOT / ".build/downloads" / record["name"]
    download(record, archive, f"{REPOSITORY}/releases/download/v{lock['version']}")
    destination = ROOT / ".build/prepared" / target
    unpack(archive, destination)
    print(destination / "lib")


def aggregate(directory: Path) -> None:
    lock = load_lock()
    targets = {}
    wasm = None
    for path in directory.glob("*.tar.gz.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        archive = directory / record["name"]
        if (
            archive.stat().st_size != record["size"]
            or sha256(archive) != record["sha256"]
        ):
            raise ValueError(f"Artifact checksum mismatch: {archive}")
        prefix = f"ash-grammars-v{lock['version']}-"
        if not record["name"].startswith(prefix):
            raise ValueError("Artifact version mismatch")
        target = record["name"].removeprefix(prefix).removesuffix(".tar.gz")
        if target == "wasm":
            wasm = record
        elif target in TARGETS and target not in targets:
            targets[target] = record
        else:
            raise ValueError(f"Unexpected artifact: {target}")
    if targets.keys() != TARGETS or wasm is None:
        raise ValueError("Release requires all eight targets and WASM")
    manifest = {
        "schemaVersion": 1,
        "version": lock["version"],
        "sourceLockSha256": sha256(ROOT / "grammars.lock.json"),
        "targets": targets,
        "wasm": wasm,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{sha256(path)}  {path.name}\n"
            for path in sorted(directory.iterdir())
            if path.is_file() and path.name != "SHA256SUMS"
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify")
    builder = commands.add_parser("build")
    builder.add_argument("--target", choices=sorted(TARGETS), required=True)
    consumer = commands.add_parser("prepare")
    consumer.add_argument("--target", choices=sorted(TARGETS), required=True)
    consumer.add_argument("--manifest", type=Path, required=True)
    merger = commands.add_parser("aggregate")
    merger.add_argument("directory", type=Path)
    wasm = commands.add_parser("wasm")
    wasm.add_argument("--sdk", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "verify":
        lock = load_lock()
        source_directories(lock)
        print(f"Verified {len(lock['grammars'])} grammar sources")
    elif arguments.command == "build":
        build(arguments.target)
    elif arguments.command == "prepare":
        prepare(arguments.target, arguments.manifest)
    elif arguments.command == "aggregate":
        aggregate(arguments.directory)
    else:
        from wasm import build_wasm

        build_wasm(arguments.sdk)


if __name__ == "__main__":
    main()
