import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import grammars


class PropertiesScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        lock = grammars.load_lock()
        source = (
            grammars.source_directories(
                {
                    "sources": {
                        "tree-sitter-properties": lock["sources"][
                            "tree-sitter-properties"
                        ]
                    }
                }
            )["tree-sitter-properties"]
            / "src"
        )
        cls.binary = Path(cls.temporary.name) / "properties-scanner"
        subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(source),
                str(source / "scanner.c"),
                str(Path(__file__).with_name("properties_scanner.c")),
                "-o",
                str(cls.binary),
            ],
            check=True,
            timeout=30,
        )

    def test_serialization_initializes_reported_bytes(self):
        subprocess.run([str(self.binary), "serialize"], check=True, timeout=10)

    def test_other_parser_cannot_reset_eof(self):
        subprocess.run([str(self.binary), "isolation"], check=True, timeout=10)

    def test_failed_scan_preserves_state_until_reset(self):
        subprocess.run([str(self.binary), "reset"], check=True, timeout=10)
