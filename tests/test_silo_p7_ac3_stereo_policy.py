"""P7 stereo copy policy from the unchanged source-shaped 49-stream fixture.

Synthetic identities and SDK answers only; no media, server or device execution.
"""
import copy
import json
import unittest
from pathlib import Path
from tests import test_silo_p7_hdr10_compat_policy as p7

ROOT=Path(__file__).resolve().parents[1]
SOURCE='03000000-0000-0000-0000-0000000002db'

class P7AC3StereoPolicy(unittest.TestCase):
    def case(self):
        technical=json.loads((ROOT/'tests/fixtures/silo/stock_p7_hdr10_technical_metadata.json').read_text())
        version=copy.deepcopy(technical['native_version']);version['file_id']='731'
        raw=dict(content_id='fixture-item',type='movie',title='Synthetic P7',versions=[version])
        metadata={'MediaSources':[copy.deepcopy(technical['compat_metadata'])]}
        receipt={'PlaySessionId':'play-fixture','MediaSources':[copy.deepcopy(technical['compat_receipt'])]}
        metadata['MediaSources'][0]['Id']=SOURCE
        selected=receipt['MediaSources'][0];selected['Id']=SOURCE;selected['DefaultAudioStreamIndex']=3
        selected['TranscodingUrl']='/Videos/'+SOURCE+'/remux-dv-v1/master.m3u8?PlaySessionId=play-fixture&MediaSourceId='+SOURCE
        for track in selected['MediaStreams']:
            if track['Type']=='Audio':track['IsDefault']=track['Index']==3
        c=p7.P7HDR10Policy().data()
        c['params'].update(audioTrackIndex=2,audioTrackId='file:731:audio:2')
        return dict(raw=raw,metadata=metadata,receipt=receipt,params=c['params'],owner=c['owner'],kind=p7.KIND)

    def evaluate(self,case=None,config=None,mutate=''):
        c=case or self.case();config=config or p7.P7HDR10Policy().config()
        body='c='+p7.literal(c)+'\nGetGlobalAA().config='+p7.literal(config)+'\nGetGlobalAA().queries=[]\n'
        body+='''decoded=DecodeSiloResponse("detail",FormatJson(c.raw),{sourceId:c.owner.sourceId})
 detail=ScopeCatalogData(decoded.data,c.owner.sourceId)
 audio=detail.versions[0].audioTracks[c.params.audioTrackIndex]
 snapshot=SiloCompatSnapshotForKind(Device(),audio,c.kind,detail.versions[0].videoTracks[0])
'''+mutate+'''
 proof=SiloCompatCandidate(detail,c.owner,c.params,snapshot,c.kind)
 result={proof:proof,snapshot:snapshot,queries:GetGlobalAA().queries}
 if proof<>invalid
  result["metadata"]=SiloCompatSourceMetadata(c.metadata,proof)
  result["receipt"]=SiloCompatPlaybackReceipt(c.receipt,proof,"http://fixture.invalid",3)
  result["profile"]=SiloCompatDeviceProfile(proof)
 end if
 print FormatJson(result)'''
        return p7.P7HDR10Policy().execute(body)

    def test_exact_mp4_stereo_source_pair_accepts_full_metadata_profile_and_receipt(self):
        c=self.case();result=self.evaluate(c)
        proof=result['proof']
        self.assertIsNotNone(proof,result)
        self.assertEqual((p7.KIND,2,'ac3',2),(proof['eligibilityKind'],proof['audioOrdinal'],proof['audio']['codec'],proof['audio']['channels']))
        self.assertEqual([8,6,2],[t['channels'] for t in proof['audioInventory']])
        self.assertEqual([True,False,False],[t['isDefault'] for t in proof['audioInventory']])
        self.assertEqual(45,len(proof['subtitleInventory']))
        self.assertEqual([dict(codec='hevc',container='mp4',profile='main 10',level='5.1'),
                          dict(codec='ac3',container='mp4',chcnt=2,passthru=0),
                          dict(codec='ac3',container='mp4',chcnt=2,passthru=1)],result['queries'])
        self.assertEqual(2,result['snapshot']['audioChannels'])
        self.assertEqual(3,result['metadata']['audioStreamIndex'])
        self.assertEqual(49,len(result['metadata']['source']['MediaStreams']))
        profile=result['profile']['TranscodingProfiles'][0]
        self.assertEqual(('mp4','ac3','2'),(profile['Container'],profile['audioCodec'],profile['MaxAudioChannels']))
        self.assertEqual('copied_p7_hdr10_fmp4',result['receipt']['class'])
        self.assertEqual(3,result['receipt']['audioStreamIndex'])
        self.assertFalse(result['receipt']['physicalHDRVerified'])
        self.assertEqual([True,False,False],[t['IsDefault'] for t in c['metadata']['MediaSources'][0]['MediaStreams'] if t['Type']=='Audio'])
        self.assertEqual([False,False,True],[t['IsDefault'] for t in c['receipt']['MediaSources'][0]['MediaStreams'] if t['Type']=='Audio'])

    def test_wrong_six_snapshot_aac_or_canonical_ordinal_does_not_match_stereo(self):
        for mutation in ('snapshot.audioChannels=6','snapshot.audioCodec="aac"',
                         'c.params.audioTrackId="file:731:audio:1"'):
            with self.subTest(mutation=mutation):
                self.assertIsNone(self.evaluate(mutate=mutation)['proof'])
        c=self.case();c['raw']['versions'][0]['audio_tracks'][2]['channels']=4
        result=self.evaluate(c)
        self.assertIsNone(result['proof'])
        self.assertEqual([],result['queries'])

    def test_stereo_receipt_refuses_aac_replacement_wrong_selection_and_off_contradiction(self):
        for mutation in ('aac','selection','off'):
            c=self.case();source=c['receipt']['MediaSources'][0]
            if mutation=='aac':source['MediaStreams'][3]['Codec']='aac'
            elif mutation=='selection':source['DefaultAudioStreamIndex']=2
            else:source['MediaStreams'][4]['IsDefault']=True
            with self.subTest(mutation=mutation):
                result=self.evaluate(c)
                self.assertIsNotNone(result['proof'])
                self.assertIsNotNone(result['metadata'])
                self.assertIsNone(result['receipt'])

    def test_exact_two_channel_directions_are_independent_and_unknown_is_not_support(self):
        config=p7.P7HDR10Policy().config()
        config.update(decode={'result':True},passthrough={'result':False})
        self.assertIsNotNone(self.evaluate(config=config)['proof'])
        config.update(decode={'result':None},passthrough={'result':False})
        self.assertIsNone(self.evaluate(config=config)['proof'])
        config.update(decode={'result':False},passthrough={'result':True})
        self.assertIsNotNone(self.evaluate(config=config)['proof'])
