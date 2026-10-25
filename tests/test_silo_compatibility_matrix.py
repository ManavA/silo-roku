"""Real capability negotiation against native API fixtures, not model badges."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function

ROOT=Path(__file__).resolve().parents[1]
BRIDGE='''
function CompatibilityMatrix(cases as Object, servers as Object) as Object
 results=[]
 for each config in cases
  device={config:config,
   CanDecodeVideo:function(format as Object) as Dynamic
    if format.codec="hevc"
     if format.profile="main 10" then return {result:m.config.main10}
     return {result:m.config.hevc}
    end if
    return {result:true}
   end function,
   CanDecodeAudio:function(format as Object) as Dynamic
    if m.config.audioUnknown then return invalid
    codecs=m.config.decode
    if format.passthru=1 then codecs=m.config.passthrough
    return {result:SiloContains(codecs,format.codec)}
   end function,
   GetVideoMode:function() as String
    return m.config.mode
   end function,
   GetDisplayProperties:function() as Object
    return m.config.display
   end function,
   GetModel:function() as String
    return m.config.model
   end function,
   GetModelType:function() as String
    return m.config.kind
   end function,
   GetModelDetails:function() as Object
    return {ModelNumber:m.config.number}
   end function,
   GetOSVersion:function() as Object
    if m.config.os <> invalid then return m.config.os
    return {major:"15",minor:"3",revision:"4",build:"2402"}
   end function}
  rows=[]
  for each server in servers
   caps=TaskRokuSiloCapabilities(device)
   context=TaskRokuSiloContext(device,caps)
   context=TaskNegotiateSiloHLS(context,device,server,caps)
   rows.Push({caps:caps,hls:context.deliveries.hls,deliveries:context.deliveries})
  end for
  results.Push(rows)
 end for
 return results
end function
'''

class CompatibilityMatrixTests(unittest.TestCase):
 def test_current_and_updatable_4k_families_negotiate_each_server_recipe(self):
  # Model families from Roku's 2026-10-16 hardware table. Native answers here
  # are synthetic boundaries, not device certifications or retail SKU guesses.
  dv_players=['3820X2','3821X2','4850X','4800X','3820X','3821X']
  hdr_players=['3830X','9104X','9100X','9102X','3940X2','3941X2','3942X2',
               '3810X','3811X','3940X','3941X','4630X','3920X','3921X',
               '4640X','4660X','4662X','4670X']
  dv_tvs=['J000X','7000X','A000X','C000X','G000X','L000X','M000X','P000X','C000GB']
  sdr_models=['4620X','6000X']
  models=dv_players+hdr_players+dv_tvs+sdr_models
  self.assertEqual(35,len(set(models)))
  cases=[]
  for model in models:
   display={} if model in sdr_models else {'Hdr10':True}
   if model in dv_players+dv_tvs: display['DolbyVision']=True
   cases.append(dict(hevc=True,main10=True,decode=['aac'],passthrough=[],audioUnknown=False,
                     mode='2160p60',model=model,number=model,display=display,
                     kind='TV' if model in dv_tvs+['6000X'] else 'STB'))
  servers=[{}, {'deliveries':['server_transcode_hls']},
           {'deliveries':['server_remux_hls'],'features':['native_hls_mpegts_v1']},
           {'deliveries':['server_remux_hls'],'features':['native_hls_separate_audio_v1']},
           {'deliveries':['server_remux_hls','server_transcode_hls'],
            'features':['native_hls_mpegts_v1','native_hls_separate_audio_v1','server_dv7_to_dv81_v1']}]
  files=[ROOT/'source/core/RuntimeIdentity.brs',ROOT/'components/ApiTask.brs',
         ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',
         ROOT/'source/core/PlaybackPolicy.brs']
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'boundary.brs';p.write_text(BRIDGE)
   rows=run_function([*files,p],'CompatibilityMatrix',[cases,servers],root=Path(directory))
  for model,device_rows in zip(models,rows):
   with self.subTest(model=model):
    for row in device_rows:
     self.assertEqual('2160p',row['caps']['max_resolution'])
     self.assertIn('hevc',row['deliveries']['original_http']['video_codecs'])
     self.assertIn('hevc',row['deliveries']['progressive']['video_codecs'])
     self.assertTrue(row['deliveries']['original_http']['enabled'])
     self.assertFalse(row['deliveries']['progressive']['enabled'])
    self.assertFalse(device_rows[0]['hls']['enabled'])
    self.assertEqual(['h264'],device_rows[1]['hls']['video_codecs'])
    self.assertNotIn('hdr_details',device_rows[1]['hls'])
    for index in (2,3,4):
     self.assertEqual(['h264','hevc'],device_rows[index]['hls']['video_codecs'])
     self.assertNotIn('server_dv7_to_dv81_v1',device_rows[index]['hls']['features'])
    self.assertEqual([],device_rows[2]['hls'].get('hdr_details',{}).get('dolby_vision_profiles',[]))
    expected=[5] if model in dv_players+dv_tvs else []
    for index in (3,4):
     self.assertEqual(expected,device_rows[index]['hls'].get('hdr_details',{}).get('dolby_vision_profiles',[]))

 def test_hd_tv_4k_tv_box_and_unknown_audio_negotiate_with_old_and_patched_servers(self):
  common=dict(hevc=False,main10=False,decode=['aac'],passthrough=[],audioUnknown=False,
              model='3930X',kind='STB',number='3930X',display={},mode='720p')
  cases=[common,
         {**common,'mode':'1080p','hevc':True,'kind':'TV','display':{'hdr10':True},'passthrough':['eac3']},
         {**common,'mode':'2160p60','hevc':True,'main10':True,'model':'4850X','number':'4850X','display':{'hdr10':True,'DolbyVision':True}},
         {**common,'mode':'2160p60','hevc':True,'main10':True,'model':'C000X','number':'C208X','kind':'TV','display':{'hdr10':True,'DolbyVision':True}},
         {**common,'mode':'','audioUnknown':True}]
  servers=[{}, {'deliveries':['server_transcode_hls']},
           {'deliveries':['server_remux_hls','server_transcode_hls'],
            'features':['native_hls_mpegts_v1','native_hls_separate_audio_v1','server_dv7_to_dv81_v1','unknown_future_feature']}]
  files=[ROOT/'source/core/RuntimeIdentity.brs', ROOT/'components/ApiTask.brs',ROOT/'source/adapters/SiloAdapter.brs',
         ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'source/core/PlaybackPolicy.brs']
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'boundary.brs';p.write_text(BRIDGE)
   rows=run_function([*files,p],'CompatibilityMatrix',[cases,servers],root=Path(directory))
  self.assertEqual('720p',rows[0][0]['caps']['max_resolution'])
  self.assertEqual('1080p',rows[1][0]['caps']['max_resolution'])
  self.assertFalse(rows[1][2]['caps']['hdr'])
  for index in range(4):
   self.assertFalse(rows[index][0]['hls']['enabled'])
   old=rows[index][1]['hls']
   self.assertTrue(old['enabled'])
   self.assertEqual(['h264'],old['video_codecs'])
   self.assertEqual(['native_hls_playback_v1'],old['features'])
   self.assertNotIn('hdr_details',old)
   self.assertNotIn('unknown_future_feature',rows[index][2]['hls']['features'])
  self.assertEqual(['h264'],rows[0][2]['hls']['video_codecs'])
  self.assertEqual([5],rows[2][2]['hls']['hdr_details']['dolby_vision_profiles'])
  self.assertEqual([5,8],rows[3][2]['hls']['hdr_details']['dolby_vision_profiles'])
  for row in rows[4]:
   self.assertFalse(row['hls']['enabled'])
   self.assertEqual([],row['caps']['containers'])

 def test_ultra_4k_output_modes_and_firmware_do_not_remove_hevc_routes(self):
  # Synthetic native answers, not captures from the reporting tester's Ultra.
  # Output spellings follow Roku ifDeviceInfo; OS16 is an API-shape case only.
  base=dict(hevc=True,main10=True,decode=['aac'],passthrough=['eac3'],audioUnknown=False,
            model='4850X',kind='STB',number='4850X',display={'Hdr10':True,'DolbyVision':True})
  cases=[]
  for os in ({'major':'15','minor':'3','revision':'4','build':'2402'},
             {'major':'16','minor':'0','revision':'0','build':'1'}):
   for mode in ('2160p60','2160p60b10','2160p60Dv'):
    cases.append({**base,'mode':mode,'os':os})
  cases.append({**base,'mode':'2160p60','display':{}})
  cases.append({**base,'mode':'1080p60b10'})
  servers=[{'deliveries':['server_transcode_hls'],'features':[]},
           {'deliveries':['server_remux_hls','server_transcode_hls'],
            'features':['native_hls_mpegts_v1','native_hls_separate_audio_v1','server_dv7_to_dv81_v1']}]
  files=[ROOT/'source/core/RuntimeIdentity.brs',ROOT/'components/ApiTask.brs',
         ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',
         ROOT/'source/core/PlaybackPolicy.brs']
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'boundary.brs';p.write_text(BRIDGE)
   rows=run_function([*files,p],'CompatibilityMatrix',[cases,servers],root=Path(directory))
  for index in range(7):
   with self.subTest(index=index):
    old,patched=rows[index]
    for row in (old,patched):
     self.assertEqual('2160p',row['caps']['max_resolution'])
     self.assertIn('hevc',row['caps']['codecs_video'])
     for name in ('original_http','progressive'):
      self.assertIn('hevc',row['deliveries'][name]['video_codecs'])
     self.assertTrue(row['deliveries']['original_http']['enabled'])
     self.assertFalse(row['deliveries']['progressive']['enabled'])
    self.assertEqual(['h264'],old['hls']['video_codecs'])
    self.assertNotIn('hdr_details',old['hls'])
    self.assertEqual([],old['caps'].get('hdr_details',{}).get('dolby_vision_profiles',[]))
    for name in ('original_http','progressive'):
     self.assertEqual([],old['deliveries'][name].get('hdr_details',{}).get('dolby_vision_profiles',[]))
    self.assertEqual(['h264','hevc'],patched['hls']['video_codecs'])
    self.assertIn('native_hls_mpegts_v1',patched['hls']['features'])
    self.assertIn('native_hls_separate_audio_v1',patched['hls']['features'])
    self.assertNotIn('server_dv7_to_dv81_v1',patched['hls']['features'])
  self.assertEqual([5],rows[0][1]['hls']['hdr_details']['dolby_vision_profiles'])
  self.assertNotIn('hdr_details',rows[6][1]['hls'])
  self.assertEqual('1080p',rows[7][0]['caps']['max_resolution'])
  self.assertEqual('1080p',rows[7][1]['caps']['max_resolution'])

if __name__=='__main__':unittest.main()
