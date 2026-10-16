import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import grammars


class ArtifactTests(unittest.TestCase):
    def test_source_archive_detects_modified_bytes(self):
        lock = grammars.load_lock()
        name, entry = next(iter(lock["sources"].items()))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sources").mkdir()
            (root / "sources" / entry["archive"]).write_bytes(b"tampered")
            with patch.object(grammars, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    grammars.source_directories({"sources": {name: entry}})

    def test_archives_reject_traversal_and_links(self):
        for name, kind in [
            ("../outside", tarfile.REGTYPE),
            ("/absolute", tarfile.REGTYPE),
            ("lib/link", tarfile.SYMTYPE),
        ]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "unsafe.tar.gz"
                with tarfile.open(archive, "w:gz") as contents:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "../../outside"
                    contents.addfile(member)
                with self.assertRaisesRegex(ValueError, "Unsafe archive"):
                    grammars.unpack(archive, root / "output")
                self.assertFalse((root / "outside").exists())

    def test_release_requires_every_target_and_wasm(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "all eight targets"):
                grammars.aggregate(Path(temporary))

    def test_release_rejects_artifact_tampering(self):
        lock = grammars.load_lock()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = f"ash-grammars-v{lock['version']}-x86_64-pc-windows-msvc.tar.gz"
            (root / name).write_bytes(b"changed")
            (root / f"{name}.json").write_text(
                json.dumps({"name": name, "size": 7, "sha256": "0" * 64})
            )
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                grammars.aggregate(root)

    def test_release_aggregation_and_archive_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "library"
            source.write_bytes(b"synthetic library")
            with patch.object(grammars, "ROOT", root):
                record = grammars.write_archive("test.tar.gz", {"lib/test.a": source})
                grammars.unpack(root / "dist/test.tar.gz", root / "unpacked")
            self.assertEqual(
                (root / "unpacked/lib/test.a").read_bytes(), source.read_bytes()
            )
            self.assertEqual(
                record["sha256"], grammars.sha256(root / "dist/test.tar.gz")
            )


if __name__ == "__main__":
    unittest.main()
