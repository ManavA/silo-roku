"""Explicit metadata configuration is independent of provider credentials."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT = Path(__file__).resolve().parents[1]

class MetadataConfigurationTests(unittest.TestCase):
    def test_empty_default_and_malformed_edits_cannot_enable_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            store=root/'store.brs'
            path=ROOT/'source/auth/MetadataStore.brs'
            self.assertTrue(path.is_file(), 'metadata configuration store is missing')
            store.write_text(path.read_text().replace('CreateObject("roRegistrySection", "silo.metadata")','FixtureMetadataSection()'))
            stub=root/'stub.brs'
            stub.write_text('''
function FixtureMetadataSection()
    g=GetGlobalAA()
    return {Read:function(key)
        return m.global.metadataUrl
    end function,Write:function(key,value)
        m.global.metadataUrl=value
        return true
    end function,Flush:function()
        return true
    end function,global:g}
end function
''')
            output=run_brightscript([ROOT/'source/adapters/MetadataAdapter.brs',store,stub],'''
g=GetGlobalAA():g.metadataUrl=""
results=[]
results.Push(BuildMetadataRequest("home_rows",MetadataRequestConfig("0.2.42"),{}))
results.Push(SaveMetadataUrl("https://user:secret@invalid.example"))
results.Push(SaveMetadataUrl("https://custom.example:8443/metadata/"))
results.Push(BuildMetadataRequest("home_rows",MetadataRequestConfig("0.2.42"),{}))
results.Push(SaveMetadataUrl(""))
results.Push(BuildMetadataRequest("home_rows",MetadataRequestConfig("0.2.42"),{}))
print FormatJson(results)
''',root=root)
        values=json.loads(output)
        self.assertEqual('metadata_disabled',values[0]['errorCode'])
        self.assertFalse(values[1])
        self.assertTrue(values[2])
        self.assertEqual('https://custom.example:8443/metadata/v1/catalog/home/rows?v=20260814-showcase-v7&format=compact',values[3]['url'])
        self.assertNotIn('Authorization',values[3]['headers'])
        self.assertTrue(values[4])
        self.assertEqual('metadata_disabled',values[5]['errorCode'])
