import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from package import build_archive


class SourceSetupContractTests(unittest.TestCase):
    def test_source_picker_declares_native_focus_control_and_events(self):
        component = ET.parse(ROOT / "components" / "SourceSetup.xml").getroot()
        self.assertEqual(component.attrib["name"], "SourceSetup")
        self.assertIsNotNone(component.find("./children/ButtonGroup[@id='sourceButtons']"))

        fields = {field.attrib["id"]: field.attrib for field in component.findall("./interface/field")}
        self.assertEqual(fields["focusedSource"]["type"], "string")
        self.assertEqual(fields["sourceSelected"]["type"], "string")
        self.assertEqual(fields["sourceSelected"]["alwaysNotify"], "true")

    def test_shipping_scene_has_onboarding_and_native_player(self):
        scene = ET.parse(ROOT / "components/SiloUIScene.xml").getroot()
        self.assertEqual("SiloUIScene", scene.get("name"))
        self.assertIsNotNone(scene.find(".//Group[@id='onboarding']"))
        self.assertIsNotNone(scene.find(".//Video[@id='video']"))

    def test_package_contains_shipping_component_closure_without_legacy_scenes(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "channel.zip"
            build_archive(ROOT, archive)
            with zipfile.ZipFile(archive) as zf:
                names = set(zf.namelist())
                for component in ("SiloUIScene", "PosterCard", "CastCard", "ApiTask", "PersonPhotoTask"):
                    self.assertIn("components/" + component + ".xml", names)
                for component in ("MainScene", "AppScene", "NativePlayer", "BrowseScreen"):
                    self.assertNotIn("components/" + component + ".xml", names)
                self.assertIsNone(zf.testzip())

    def test_scenegraph_script_references_are_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "channel.zip"
            build_archive(ROOT, archive)
            with zipfile.ZipFile(archive) as zf:
                names = set(zf.namelist())
                self.assertIn("manifest", names)
                for path in (ROOT / "components").glob("*.xml"):
                    component = ET.parse(path).getroot()
                    self.assertEqual(component.tag, "component")
                    for script in component.findall("script"):
                        uri = script.attrib["uri"]
                        self.assertTrue(uri.startswith("pkg:/"), uri)
                        self.assertIn(uri.removeprefix("pkg:/"), names)

    def test_manifest_declares_the_implemented_hd_layout(self):
        manifest = (ROOT / "manifest").read_text(encoding="utf-8")
        self.assertTrue(manifest.endswith("\n"))
        self.assertIn("ui_resolutions=hd\n", manifest)
        self.assertNotIn("ui_resolutions=hd,fhd", manifest)
        self.assertIn("rsg_version=1.3\n", manifest)


if __name__ == "__main__":
    unittest.main()
