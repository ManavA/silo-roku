"""Restored server scope resolves relative card and hero artwork together."""
from pathlib import Path
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]

class RelativeArtworkTests(unittest.TestCase):
    def test_server_restore_and_switch_resolve_cards_and_hero_on_current_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for script in ET.parse(ROOT/'components/SiloUIScene.xml').getroot().findall('script'):
                source = ROOT/script.attrib['uri'].removeprefix('pkg:/')
                text = source.read_text()
                for name in ['PlexClearImages','ShowView','HomeLoad','LibrariesNavigation','Api']:
                    text = re.sub(r'(?im)^sub '+name+r'\(', 'sub Unused'+name+'(', text, count=1)
                text = text.replace('AppRegistrySection("preferences")','FixturePreferences()')
                local = root/source.name
                local.write_text(text)
                files.append(local)
            boundary = root/'boundary.brs'
            boundary.write_text('''function FixturePreferences() as Object
 return {Read:function(key as String) as String
 return ""
 end function}
end function
sub LibrariesNavigation()
end sub
sub PlexClearImages()
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub HomeLoad()
end sub
sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
 ' Source restoration may request effective settings. No transport belongs in
 ' the artwork-resolution seam; the real settings policy still initializes.
end sub
''')
            files.append(boundary)
            output = run_brightscript(files, '''m.generation=1:m.avatarText={}:m.navSource={}:m.pillGroups={nav:{index:0}}
 art={poster:"/images/poster.jpg?signature=fixture",backdrop:"/images/backdrop.jpg?signature=fixture"}
 rows=[]
 for each source in ["silo:https://first.example","silo:http://second.example:8096","silo:opaque"]
  EnterSource("silo",{sourceId:source,profileId:"profile"})
  fields=SiloUIItemFields({title:"Film",type:"movie"},art,false,TextOr(m.baseUrl))
  rows.Push({base:TextOr(m.baseUrl),poster:fields.HDPosterUrl,hero:ArtField(art,"backdrop")})
 end for
 print FormatJson(rows)
''', root=root)
            result = json.loads(output.strip().splitlines()[-1])
            for row, base in zip(result[:2], ['https://first.example','http://second.example:8096']):
                self.assertEqual(base, row['base'])
                self.assertEqual(base+'/images/poster.jpg?signature=fixture',row['poster'])
                self.assertEqual(base+'/images/backdrop.jpg?signature=fixture',row['hero'])
            self.assertEqual('',result[-1]['base'])

if __name__ == '__main__':
    unittest.main()
