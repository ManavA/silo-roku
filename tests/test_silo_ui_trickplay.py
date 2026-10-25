"""Scrub previews validate the selected file and map source time to one safe tile."""
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT/'source/core/ArtworkPolicy.brs', ROOT/'source/core/SiloUITrickplayPolicy.brs', ROOT/'source/adapters/SiloAdapter.brs']

class TrickplayTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as tmp:
            return run_function(FILES, name, list(args), root=Path(tmp))

    def manifest(self):
        return dict(file_id='42', interval_ms=10000, thumbnail_width=300,
                    thumbnail_height=126, tile_columns=10, tile_rows=10,
                    thumbnail_count=102, expires_at='2030-01-01T00:00:00Z',
                    sheets=[dict(index=i, url=f'/api/v2/artwork/trickplay/42/1/{i}.1.jpg?exp=1893456000&sig=fixture') for i in range(2)])

    def test_manifest_maps_sheet_boundary_and_last_partial_sheet(self):
        value = self.call('SiloUITrickplayManifest', self.manifest(), '42', 'https://media.example', 1893450000)
        self.assertTrue(value['ok'])
        tile = self.call('SiloUITrickplayTile', value, 1000000)
        self.assertEqual(tile, dict(ok=True, sheet=1, x=0, y=0))
        self.assertEqual(self.call('SiloUITrickplayTile', value, 999999999), dict(ok=True, sheet=1, x=300, y=0))

    def test_manifest_rejects_wrong_file_expiry_geometry_and_untrusted_sheet(self):
        mutations = [dict(file_id='43'), dict(thumbnail_width=0), dict(tile_rows=20),
                     dict(thumbnail_width=640, thumbnail_height=360), dict(interval_ms=1),
                     dict(expires_at='1970-01-01T00:00:00Z'), dict(sheets=[]),
                     dict(sheets=[dict(index=0,url='https://other.example/api/v2/artwork/trickplay/42/1/0.1.jpg?sig=x'),self.manifest()['sheets'][1]])]
        for patch in mutations:
            raw=self.manifest();raw.update(patch)
            with self.subTest(patch=patch):
                self.assertFalse(self.call('SiloUITrickplayManifest', raw,'42','https://media.example',1893450000)['ok'])

    def test_jpeg_dimensions_must_match_admitted_sheet_before_decode(self):
        header=[255,216,255,224,0,4,0,0,255,192,0,17,8,4,236,11,184,3,1,17,0,2,17,0,3,17,0]
        self.assertTrue(self.call('SiloUITrickplayJpeg',header,3000,1260))
        self.assertFalse(self.call('SiloUITrickplayJpeg',header,300,126))
        self.assertFalse(self.call('SiloUITrickplayJpeg',header[:15],3000,1260))

    def test_production_default_sheet_fits_source_pixel_budget(self):
        raw=self.manifest();raw.update(thumbnail_height=168,tile_rows=8)
        value=self.call('SiloUITrickplayManifest',raw,'42','https://media.example',1893450000)
        self.assertTrue(value['ok'])
        self.assertEqual((3000,1344),(value['sheetWidth'],value['sheetHeight']))
        raw['thumbnail_height']=225
        self.assertFalse(self.call('SiloUITrickplayManifest',raw,'42','https://media.example',1893450000)['ok'])

    def test_configured_origin_accepts_http_default_ports_and_ipv6(self):
        cases=[('http://192.168.1.4:8096',None),
               ('http://MEDIA.local','http://media.local:80'),
               ('https://MEDIA.example','https://media.example:443'),
               ('http://[::1]:8096','http://[::1]:8096'),
               ('https://[::1]:443','https://[::1]')]
        for base,authority in cases:
            with self.subTest(base=base,authority=authority):
                raw=self.manifest()
                if authority:
                    for sheet in raw['sheets']: sheet['url']=authority+sheet['url']
                value=self.call('SiloUITrickplayManifest',raw,'42',base,1893450000)
                self.assertTrue(value['ok'])
                self.assertEqual((authority or base)+self.manifest()['sheets'][0]['url'],value['urls'][0])

    def test_sheet_cannot_change_scheme_host_port_or_selected_file_path(self):
        for authority in ['http://media.example:8443','https://other.example:8443','https://media.example:443','https://media.example:84430']:
            with self.subTest(authority=authority):
                raw=self.manifest();raw['sheets'][0]['url']=authority+raw['sheets'][0]['url']
                self.assertFalse(self.call('SiloUITrickplayManifest',raw,'42','https://media.example:8443',1893450000)['ok'])
        for path in ['/api/v2/artwork/trickplay/43/1/0.1.jpg?sig=x','/api/v2/artwork/trickplay/42/../1/0.1.jpg?sig=x','//media.example/api/v2/artwork/trickplay/42/1/0.1.jpg?sig=x']:
            with self.subTest(path=path):
                raw=self.manifest();raw['sheets'][0]['url']=path
                self.assertFalse(self.call('SiloUITrickplayManifest',raw,'42','https://media.example',1893450000)['ok'])

if __name__ == '__main__':
    unittest.main()
