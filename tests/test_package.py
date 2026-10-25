import tempfile
import unittest
import zipfile
from pathlib import Path
import sys
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from package import build_archive


class PackageTests(unittest.TestCase):
    def test_stock_engine_uses_exact_experiment_sources_and_no_fixture(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "channel.zip"
            build_archive(repo, archive)
            with zipfile.ZipFile(archive) as zf:
                names = set(zf.namelist())
                self.assertIn("components/SiloStockEngineTask.xml", names)
                self.assertEqual(
                    zf.read("components/SiloStockEngineTask.brs"),
                    (repo / "tools/experiments/onroku_audio/multi_app/components/LocalHttpTask.brs").read_bytes(),
                )
                self.assertEqual(
                    zf.read("source/StockDescriptor.brs"),
                    (repo / "tools/experiments/onroku_audio/multi_app/source/StockDescriptor.brs").read_bytes(),
                )
                self.assertNotIn("images/config.json", names)

    def test_stock_engine_mapping_reads_supplied_revision_and_rejects_missing_source(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "components").mkdir()
            (root / "manifest").write_text("title=Staged\n")
            (root / "source/main.brs").write_text("sub Main()\nend sub\n")
            shutil.copyfile(repo / "components/SiloUIScene.xml", root / "components/SiloUIScene.xml")
            shutil.copyfile(repo / "components/SiloStockEngineTask.xml", root / "components/SiloStockEngineTask.xml")
            archive = root / "dist/staged.zip"
            with self.assertRaisesRegex(ValueError, "stock engine source missing"):
                build_archive(root, archive)
            self.assertFalse(archive.exists())
            experiment = root / "tools/experiments/onroku_audio"
            for folder in ("multi_app/components", "multi_app/source", "app/source"):
                shutil.copytree(repo / "tools/experiments/onroku_audio" / folder, experiment / folder)
            shared = experiment / "multi_app/components/LocalHttpTask.brs"
            shared.write_bytes(b"' staged revision sentinel\n")
            build_archive(root, archive)
            with zipfile.ZipFile(archive) as zf:
                self.assertEqual(zf.read("components/SiloStockEngineTask.brs"), shared.read_bytes())

    def test_archive_contains_only_channel_files_at_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "components").mkdir()
            (root / "images").mkdir()
            (root / "docs").mkdir()
            (root / "manifest").write_text("title=Test\n", encoding="utf-8")
            (root / "source" / "main.brs").write_text("sub Main()\nend sub\n", encoding="utf-8")
            (root / "components" / "SiloUIScene.xml").write_text('<component name="SiloUIScene" extends="Scene"/>', encoding="utf-8")
            (root / "images" / "icon.png").write_bytes(b"image")
            (root / "docs" / "secret.txt").write_text("do not package", encoding="utf-8")
            archive = root / "dist" / "channel.zip"

            build_archive(root, archive)

            with zipfile.ZipFile(archive) as zf:
                self.assertEqual(set(zf.namelist()), {
                    "manifest", "source/main.brs", "components/SiloUIScene.xml", "images/icon.png"
                })
                self.assertEqual(zf.read("manifest"), b"title=Test\n")

    def test_missing_entry_point_fails_before_creating_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest").write_text("title=Test\n", encoding="utf-8")
            archive = root / "dist" / "channel.zip"

            with self.assertRaisesRegex(ValueError, "source/main.brs"):
                build_archive(root, archive)

            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
