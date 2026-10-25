"""Explicit source audio selectors require fresh same-file wire identities."""
import copy
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
from tests.test_silo_playback_policy import context, detail
ROOT=Path(__file__).resolve().parents[1]
class SiloUIPlaybackChoicesPolicyTests(unittest.TestCase):
 def call(self,name,*args):
  with tempfile.TemporaryDirectory() as d:
   return run_function([ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'source/core/SiloUIPlaybackChoicesPolicy.brs'],name,list(args),root=Path(d))
 def test_user_audio_requires_fresh_exact_wire_index_not_fallback_ordinal(self):
  d=detail();audio={'id':'2','index':2,'codec':'aac','channels':2,'language':'eng'};d['versions'][1]['audioTracks']=[audio]
  wire={'content_id':'c1','versions':[{'file_id':'f1','audio_tracks':[{'index':2,'codec':'aac','channels':2}]}]}
  self.assertEqual(self.call('SiloUserAudioSelection',context(),d,wire,2),audio)
  missing=copy.deepcopy(wire);del missing['versions'][0]['audio_tracks'][0]['index']
  self.assertIsNone(self.call('SiloUserAudioSelection',context(),d,missing,2))
  duplicate=copy.deepcopy(wire);duplicate['versions'][0]['audio_tracks']*=2
  self.assertIsNone(self.call('SiloUserAudioSelection',context(),d,duplicate,2))
  wire['versions'][0]['file_id']='another-file'
  self.assertIsNone(self.call('SiloUserAudioSelection',context(),d,wire,2))
 def test_official_audio_without_wire_indices_uses_complete_audio_array_ordinal(self):
  d=detail();first={'id':'0','index':0,'codec':'truehd','channels':8,'language':'en'};chosen={'id':'1','index':1,'codec':'ac3','channels':6,'language':'en'}
  d['versions'][1]['audioTracks']=[first,chosen]
  wire={'content_id':'c1','versions':[{'file_id':'f1','audio_tracks':[{'codec':'truehd','channels':8,'language':'en'},{'codec':'ac3','channels':6,'language':'en'}]}]}
  self.assertEqual(self.call('SiloUserAudioSelection',context(),d,wire,1),chosen)
  wire['versions'][0]['audio_tracks'][0]['index']=9
  self.assertIsNone(self.call('SiloUserAudioSelection',context(),d,wire,1))
