"""Source codec labels at public format/adapter/card callback boundaries."""
import json,tempfile,unittest
from pathlib import Path
from tools.brightscript import run_function,run_brightscript
ROOT=Path(__file__).resolve().parents[1]
FORMAT=ROOT/'source/core/SiloUIFormat.brs'
class CodecLabels(unittest.TestCase):
 def call(self,name,*args):return run_function(FORMAT,name,list(args))
 def test_known_codec_aliases_are_source_labels_and_unknowns_stay_blank(self):
  for codec,label in [('h264','H.264'),('avc','H.264'),('H.265','HEVC'),('hevc','HEVC'),('av1','AV1'),('vp9','VP9'),('unknown',''),('https://private.invalid/file',''),(None,'')]:
   with self.subTest(codec=codec):self.assertEqual(label,self.call('VideoCodecLabel',codec))
 def test_catalog_adapters_keep_existing_video_codec_facts_without_detail_requests(self):
  badges=run_function(ROOT/'source/adapters/SiloAdapter.brs','SiloBadges',[{'overlay_summary':{'video_codec':'H.265','resolution':'2160p'}}])
  self.assertEqual('H.265',badges.get('videoCodec'))
  item=run_function(ROOT/'source/adapters/PlexAdapter.brs','PlexNormalizeItem',[{'ratingKey':'1','type':'movie','Media':[{'videoCodec':'h264'},{'videoCodec':'hevc'}]},'plex:one'])
  self.assertEqual(['h264','hevc'],item['badges']['videoCodecs'])
 def test_detail_names_auto_inventory_and_exact_pinned_version_without_mixing_files(self):
  item={'type':'movie','badges':{'resolution':'2160p','videoCodec':'hevc'}}
  rows=[{'versionId':'a','resolution':'1080p','videoCodec':'h264','container':'mp4'},{'versionId':'b','resolution':'2160p','videoCodec':'hevc','container':'mkv'}]
  self.assertEqual('Auto  ·  2 versions  ·  H.264 / HEVC',self.call('DetailSourceHeading',item,rows,''))
  self.assertEqual('Selected source  ·  1080P  ·  H.264  ·  MP4',self.call('DetailSourceQuality',item,rows,'a'))
  self.assertEqual('Selected source  ·  4K  ·  HEVC  ·  MKV',self.call('DetailSourceQuality',item,rows,'b'))
  self.assertEqual('Source unavailable',self.call('DetailSourceQuality',item,rows,'gone'))
  self.assertEqual('',self.call('DetailSourceQuality',{'type':'series'},rows,''))
 def test_actual_card_recycles_codec_and_keeps_it_below_rating_above_progress(self):
  body='''
   nodes={}
   for each id in ["bg","art","fallback","chipLeft","chipLeftBg","chipRight","chipRightBg","codec","codecBg","progressTrack","progress","caption","focusBorder","focusTop","focusBottom","focusLeft","focusRight"]
    nodes[id]={text:"",visible:true,loadStatus:"loading"}
   end for
   nodes.art.observeField=sub(a,b)
   end sub
   c={title:"Synthetic",landscape:false,badges:{resolution:"1080p",imdb:8.2,videoCodec:"h264"},observeField:sub(a,b)
   end sub,unobserveField:sub(a)
   end sub}
   m.top={width:150,height:225,itemContent:c,nodes:nodes,findNode:function(id)
    return m.nodes[id]
   end function}
   init():m.top.height=0:onContent():earlyHidden=not m.codecBg.visible
   m.top.height=225:onLayout()
   first={text:m.codec.text,width:m.codec.width,y:m.codec.translation[1],ratingY:m.chipRight.translation[1],progressY:m.progress.translation[1],visible:m.codecBg.visible}
   c.badges={videoCodec:"unknown"}:onContent():cleared=m.codec.text="" and not m.codecBg.visible
   c.badges={videoCodec:"hevc"}:onContent():m.top.itemContent=invalid:onContent()
   print FormatJson({earlyHidden:earlyHidden,first:first,cleared:cleared,invalidCleared:m.codec.text="" and not m.codecBg.visible})
  '''
  with tempfile.TemporaryDirectory() as d:
   r=json.loads(run_brightscript([FORMAT,ROOT/'components/PosterCard.brs'],body,root=Path(d)))
  self.assertTrue(r['earlyHidden'])
  self.assertEqual('H.264',r['first']['text']);self.assertTrue(r['first']['visible']);self.assertLessEqual(r['first']['width'],134)
  self.assertGreater(r['first']['y'],r['first']['ratingY']+22);self.assertLess(r['first']['y']+22,r['first']['progressY'])
  self.assertTrue(r['cleared']);self.assertTrue(r['invalidCleared'])
 def test_selected_source_preserves_proven_range_audio_and_unknown_codec_is_explicit(self):
  row={'versionId':'b','resolution':'2160p','videoCodec':'hevc','container':'mkv','hdr':True,'videoTracks':[{'dv_profile':7,'dv_bl_compat_id':6,'dv_bl_present':True}], 'audioCodec':'truehd','audioTracks':[{'codec':'truehd','channels':8,'isDefault':True}]}
  label=self.call('DetailSourceQuality',{'badges':{'hdr':'HDR10','audio':'AAC'}},[row],'b')
  self.assertIn('DV P7',label);self.assertIn('TrueHD',label);self.assertIn('7.1',label);self.assertNotIn('AAC',label)
  self.assertIn('Codec unknown',self.call('SourceVersionQuality',{'videoCodec':'mystery'}))
 def test_auto_labels_library_metadata_without_claiming_playback_output(self):
  item={'badges':{'resolution':'2160p','videoCodec':'hevc','hdr':'DV','audio':'TrueHD Atmos','audio_channels':'7.1'}}
  rows=[{'versionId':'a','videoCodec':'h264'},{'versionId':'b','videoCodec':'hevc'}]
  self.assertEqual('Library includes  ·  4K  ·  HEVC  ·  DV  ·  TrueHD Atmos  ·  7.1',self.call('DetailSourceQuality',item,rows,''))
 def test_actual_detail_version_picker_uses_canonical_source_labels(self):
  import xml.etree.ElementTree as ET
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);files=[]
   for script in ET.parse(ROOT/'components/SiloUIScene.xml').getroot().findall('script'):
    path=script.get('uri').removeprefix('pkg:/');text=(ROOT/path).read_text()
    if path=='components/SiloUIDetail.brs':
     text=text.replace('CreateObject("roSGNode", "Dialog")','FixtureCodecDialog()')
    target=root/Path(path).name;target.write_text(text);files.append(target)
   sdk=root/'SDK.brs';sdk.write_text('''function FixtureCodecDialog() as Object
 return {observeField:sub(a,b)
 end sub}
end function
''');files.append(sdk)
   body='''m.top={}:m.detailToken=4:m.prebuf=invalid:m.detailSelectedVersion="b"
   m.detailVersions=[{versionId:"a",resolution:"2160p",videoCodec:"hevc",container:"mkv",bitrateKbps:45000},{versionId:"b",resolution:"2160p",videoCodec:"hevc",container:"mkv",bitrateKbps:60000}]
   DetailVersionPicker()
   print FormatJson({buttons:m.detailVersionDialog.buttons,message:m.detailVersionDialog.message})'''
   result=json.loads(run_brightscript(files,body,root=root))
  self.assertEqual(['Auto','Version 1  ·  4K  ·  HEVC  ·  MKV  ·  45 Mbps','Version 2 (selected)  ·  4K  ·  HEVC  ·  MKV  ·  60 Mbps','Cancel'],result['buttons'])
  self.assertEqual('Auto may use another file. Selecting a version keeps that file.',result['message'])
