import re
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from package import build_archive


class ChannelIntegrityTests(unittest.TestCase):
    def test_manifest_artwork_exists_and_has_expected_png_dimensions(self):
        lines = (ROOT / "manifest").read_text(encoding="utf-8").splitlines()
        fields = dict(line.split("=", 1) for line in lines if "=" in line)
        expected = {
            "mm_icon_focus_hd": (290, 218),
            "mm_icon_focus_fhd": (540, 405),
            "splash_screen_sd": (720, 480),
            "splash_screen_hd": (1280, 720),
            "splash_screen_fhd": (1920, 1080),
        }
        for key, dimensions in expected.items():
            with self.subTest(key=key):
                uri = fields[key]
                self.assertTrue(uri.startswith("pkg:/"), uri)
                image = ROOT / uri.removeprefix("pkg:/")
                data = image.read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", data[16:24]), dimensions)

    def test_archive_has_no_obvious_secrets_or_local_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "channel.zip"
            build_archive(ROOT, archive)
            with zipfile.ZipFile(archive) as zf:
                for name in zf.namelist():
                    with self.subTest(name=name):
                        self.assertFalse(
                            re.search(r"(?:^|/)(?:\.env(?:\..*)?|[^/]+\.(?:pem|p12|key))$", name, re.I),
                            name,
                        )
                        if not name.endswith((".brs", ".xml", "manifest")):
                            continue
                        body = zf.read(name).decode("utf-8")
                        self.assertNotRegex(body, r"-----BEGIN [^-]*PRIVATE KEY-----")
                        # Only the stock engine's fixed local playlist statements
                        # are exempt; provider defaults and other loopback URLs fail.
                        stock_statements = {
                            "components/SiloUICompatPlayback.brs": (
                                'url:"http://127.0.0.1:34831/g1/master.m3u8"',
                                'offer.localMasterUrl = "http://127.0.0.1:34831/g"+offer.generationId.ToStr()+"/master.m3u8"',
                            ),
                            "source/SeekHandoff.brs": (
                                'offer.localMasterUrl="http://127.0.0.1:34831/g"+r.generationId.ToStr()+"/master.m3u8"',
                            ),
                        }
                        endpoint_body = body
                        for statement in stock_statements.get(name, ()):
                            self.assertEqual(1, endpoint_body.count(statement))
                            endpoint_body = endpoint_body.replace(statement, "")
                        self.assertNotRegex(endpoint_body, r"https?://(?:localhost|127\.0\.0\.1|10\.\d+|192\.168\.\d+)")
                        self.assertNotRegex(body, re.compile(r"[?&](?:X-Plex-Token|access_token|token)=", re.I))


if __name__ == "__main__":
    unittest.main()
