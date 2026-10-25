"""The shipping package supports only SiloUIScene."""

import inspect
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from tools.package import build_archive


class RebuildPackageTests(unittest.TestCase):
    def project(self, root):
        (root / "source").mkdir()
        (root / "components").mkdir()
        (root / "manifest").write_text("title=Test\n")
        (root / "source/main.brs").write_text('sub Main()\n scene = screen.CreateScene("SiloUIScene")\nend sub\n')
        (root / "components/MainScene.xml").write_text('<component name="MainScene" extends="Scene"/>')
        (root / "components/AppScene.xml").write_text('<component name="AppScene" extends="Scene"/>')
        (root / "components/SiloUIScene.xml").write_text('<component name="SiloUIScene" extends="Scene"/>')

    def test_default_archive_launches_silo_ui_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.project(root)
            build_archive(root, root / "dist/app.zip")
            with ZipFile(root / "dist/app.zip") as archive:
                self.assertIn(b'CreateScene("SiloUIScene")', archive.read("source/main.brs"))

    def test_legacy_scenes_are_rejected_before_creating_an_archive(self):
        for scene in ("MainScene", "AppScene"):
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.project(root)
                with self.assertRaisesRegex(ValueError, "unsupported Roku entry scene"):
                    build_archive(root, root / "dist/legacy.zip", scene=scene)
                self.assertFalse((root / "dist/legacy.zip").exists())

    def test_unknown_scene_is_rejected(self):
        self.assertIn("scene", inspect.signature(build_archive).parameters, "rebuild package selection is missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.project(root)
            with self.assertRaisesRegex(ValueError, "scene"):
                build_archive(root, root / "dist/rebuild.zip", scene="../Other")


if __name__ == "__main__":
    unittest.main()
