"""Installed identity and visible focus contrast for the requested Silo theme."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import struct
import zlib
import tempfile
import re

from tools.brightscript import run_function, run_brightscript
import json

ROOT = Path(__file__).resolve().parents[1]
BLUE = "0x7CD4FFFF"
DARK = "0x090A0DFF"


class SiloBrandThemeTests(unittest.TestCase):
    def test_installed_name_and_shipping_onboarding_use_silo_identity(self):
        fields = dict(line.split("=", 1) for line in (ROOT / "manifest").read_text().splitlines() if "=" in line)
        self.assertEqual("Silo", fields["title"])
        scene = ET.parse(ROOT / "components/SiloUIScene.xml").getroot()
        logo = scene.find(".//Poster[@id='obSiloLogo']")
        self.assertEqual("pkg:/images/brand/silo-wordmark-white.png", logo.get("uri"))
        self.assertTrue((ROOT / logo.get("uri").removeprefix("pkg:/")).is_file())

    def test_launch_art_uses_official_silo_masters_on_dark_fields(self):
        source = (ROOT / "tools/generate_assets.py").read_text()
        self.assertIn("silo-app-icon.svg", source)
        self.assertIn("silo-wordmark-white.svg", source)
        self.assertNotIn('"Silo"', source)
        self.assertNotIn('"ROKU PROTOTYPE"', source)
        for name in ("icon_hd.png", "icon_fhd.png", "splash_sd.png", "splash_hd.png", "splash_fhd.png"):
            data = (ROOT / "images" / name).read_bytes()
            self.assertEqual(2, data[25], "launch artwork must be RGB")
            chunks = []
            offset = 8
            while offset < len(data):
                length = struct.unpack(">I", data[offset:offset + 4])[0]
                if data[offset + 4:offset + 8] == b"IDAT":
                    chunks.append(data[offset + 8:offset + 8 + length])
                offset += 12 + length
            # For the first RGB pixel all PNG filter predictors are zero.
            expected = bytes((1, 13, 159)) if name.startswith("icon_") else bytes((0, 0, 0))
            self.assertEqual(expected, zlib.decompress(b"".join(chunks))[1:4])

    def test_native_buttons_use_blue_asset_and_dark_focused_text(self):
        buttons = []
        for path in (ROOT / "components").glob("*.xml"):
            buttons.extend(node for node in ET.parse(path).getroot().iter() if node.tag in ("Button", "ButtonGroup"))
        self.assertTrue(buttons)
        for button in buttons:
            with self.subTest(id=button.get("id")):
                self.assertEqual("pkg:/images/button_focus.9.png", button.get("focusBitmapUri"))
                self.assertEqual(DARK, button.get("focusedTextColor"))
        self.assertTrue((ROOT / "images/button_focus.9.png").is_file())

    def test_shipping_cards_show_focus_only_in_the_active_list(self):
        scene = ET.parse(ROOT / "components/SiloUIScene.xml").getroot()
        cards = [node for node in scene.iter() if node.get("itemComponentName") == "PosterCard"]
        self.assertTrue(cards)
        for node in cards:
            self.assertEqual("false", node.get("drawFocusFeedback"))
        with tempfile.TemporaryDirectory() as directory:
            output = run_brightscript([ROOT / "components/PosterCard.brs"], '''
                m.focusBorder={}
                m.top={focusPercent:1,gridHasFocus:false,rowListHasFocus:true,rowHasFocus:true}
                onFocus():states=[m.focusBorder.visible]
                m.top.rowListHasFocus=false:onFocus():states.Push(m.focusBorder.visible)
                m.top.gridHasFocus=true:onFocus():states.Push(m.focusBorder.visible)
                m.top.gridHasFocus=false:onFocus():states.Push(m.focusBorder.visible)
                m.top.rowListHasFocus=true:m.top.rowHasFocus=false:onFocus():states.Push(m.focusBorder.visible)
                m.top.rowHasFocus=true:m.top.focusPercent=0:onFocus():states.Push(m.focusBorder.visible)
                print FormatJson(states)
            ''', root=Path(directory))
        self.assertEqual([True, False, True, False, False, False], json.loads(output))

    def test_plex_identifies_silo_with_existing_installation_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            headers = run_function(ROOT / "source/adapters/PlexAdapter.brs", "PlexHeaders",
                                   [{"clientId": "existing-installation", "model": "fixture"}, False], root=Path(directory))
        self.assertEqual("Silo", headers["X-Plex-Product"])
        self.assertEqual("Silo Roku", headers["X-Plex-Device-Name"])
        self.assertEqual("existing-installation", headers["X-Plex-Client-Identifier"])

    def test_silo_identifies_current_brand_with_existing_device_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            headers = run_function(ROOT / "source/adapters/SiloAdapter.brs", "SiloClientHeaders",
                                   [{"deviceId": "existing-device", "model": "fixture"}], root=Path(directory))
        self.assertEqual("Silo", headers["X-Client-Name"])
        self.assertEqual("Silo Roku", headers["X-Silo-Client"])
        self.assertEqual("existing-device", headers["X-Device-ID"])

    def test_entry_shows_when_firmware_has_no_optional_palette_node(self):
        source = (ROOT / "source/main.brs").read_text().replace('CreateObject(', 'ThemeObject(')
        source = re.sub(r'(?im)^sub Main\(', 'sub ThemeMain(', source, count=1)
        source = source.replace('message = wait(0, port)', 'message = ThemeExit()')
        source = source.replace('messageType = type(message)', 'messageType = "roSGScreenEvent"')
        harness = '''
function ThemeObject(kind as String, extra = invalid as Dynamic) as Dynamic
    if kind="roMessagePort" then return {}
    if kind<>"roSGScreen" then return invalid
    return {SetMessagePort:sub(port as Object)
        end sub,CreateScene:function(name as String) as Object
            return {}
        end function,Show:sub()
            m.global.themeShown=true
        end sub,global:m}
end function
function ThemeExit() as Object
    return {IsScreenClosed:function() as Boolean
        return true
    end function}
end function
function ThemeEntry() as Boolean
    m.themeShown=false
    try
        ThemeMain()
    catch error
        return false
    end try
    return m.themeShown
end function
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entry.brs"
            path.write_text(source + harness)
            self.assertTrue(run_function(path, "ThemeEntry", [], root=Path(directory)))


if __name__ == "__main__":
    unittest.main()
