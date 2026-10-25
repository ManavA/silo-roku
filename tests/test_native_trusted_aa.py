"""Pure preference/intent policies preserve Roku lowercase trusted-AA values."""
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import ROOT as REPO, run_function
ROOT = Path(__file__).resolve().parents[1]
SCOPE = {'provider':'plex','sourceId':'plex:fixture','profileId':'owner','generation':7}
PREF = {'schemaVersion':1,'sourceId':SCOPE['sourceId'],'profileId':'owner','subtitleMode':'auto',
        'subtitleLanguage':'eng','subtitleName':'','audioLanguage':'','audioName':''}
INTENT = {'schemaVersion':1,'sourceId':SCOPE['sourceId'],'itemId':'1','versionId':'file-1','owedStartMs':90000,
          'forceCompatible':True,'maxVideoBitrate':8000,'videoResolution':'1920x1080','audioStreamId':'22'}
# These are real normal AAs/values. Only the native enumeration behavior is
# supplied at the boundary; untrusted case-sensitive records stay untouched.
BOUNDARY = '''
function NativeTrusted(value as Dynamic) as Dynamic
    if type(value)="roAssociativeArray"
        out={}
        for each key in value.Keys()
            out[LCase(key)]=NativeTrusted(value[key])
        end for
        return out
    else if type(value)="roArray"
        out=[]
        for each child in value
            out.Push(NativeTrusted(child))
        end for
        return out
    end if
    return value
end function
function NativePreferenceModel(scope as Object) as Object
    trusted=NativeTrusted(TpoCreate(scope))
    trusted["manualepoch"]=7
    copied=TpoCopy(trusted)
    first=TpoReduce(trusted,{kind:"load"})
    second=TpoReduce(first.state,{kind:"load"})
    manual=TpoReduce(first.state,{kind:"manual_intent"})
    return {epoch:TpoField(copied,"manualEpoch",-1),first:first.effects.Count(),second:second.effects.Count(),
        pending:TpoField(first.state,"readPending",invalid),manualEpoch:TpoField(manual.state,"manualEpoch",-1),
        pendingMode:TpoField(manual.state,"pendingMode","missing")}
end function
function NativePlexIntent(raw as Object) as Object
    trusted=NativeTrusted(raw)
    copied=PrCopy(trusted)
    normalized=PrIntent(trusted,raw.sourceId,raw.itemId,raw.versionId)
    again=PrIntent(normalized,raw.sourceId,raw.itemId,raw.versionId)
    return {source:PrField(copied,"sourceId",invalid),start:PrField(copied,"owedStartMs",invalid),
        force:PrField(copied,"forceCompatible",invalid),audio:PrField(copied,"audioStreamId",invalid),
        normalized:normalized,again:again}
end function
function NativePlexParams(params as Object,plan as Object,detail as Object) as Object
    copied=PrCopy(NativeTrusted(params))
    intent=PrIngress(copied,NativeTrusted(plan),NativeTrusted(detail))
    return {start:PrField(copied,"startPositionMs",invalid),version:PrField(copied,"versionId",invalid),intent:intent}
end function
function UntrustedRecord(scope as Object,pref as Object,intent as Object,alias as String) as Object
    record={}:record.SetModeCaseSensitive()
    for each key in pref.Keys()
        record[key]=pref[key]
    end for
    raw={}:raw.SetModeCaseSensitive()
    for each key in intent.Keys()
        raw[key]=intent[key]
    end for
    if alias<>""
        record[alias]="plex:other"
        raw[alias]="plex:other"
    end if
    return {preference:TpoRecord(record,scope),intent:PrIntent(raw,intent.sourceId,intent.itemId,intent.versionId)}
end function
'''

class NativeTrustedAaTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory(prefix='silo-native-trusted-aa-') as directory:
            temp=Path(directory);fixture=temp/'boundary.brs';fixture.write_text(BOUNDARY)
            files=[REPO/'source/core/TrackPreference.brs',
                   ROOT/'source/core/TrackPreferenceOwnerPolicy.brs',ROOT/'source/core/PlexReplacementPolicy.brs',
                   REPO/'source/core/RequestQueuePolicy.brs',fixture]
            return run_function(files,name,list(args),root=temp)
    def test_native_model_copy_preserves_camel_lookup_pending_dedupe_and_manual_epoch(self):
        out=self.call('NativePreferenceModel',SCOPE)
        self.assertEqual(7,out['epoch']);self.assertEqual(1,out['first']);self.assertEqual(0,out['second'])
        self.assertIsNotNone(out['pending']);self.assertEqual(8,out['manualEpoch']);self.assertIsNone(out['pendingMode'])
    def test_native_client_intent_copy_preserves_fields_and_validates_again(self):
        out=self.call('NativePlexIntent',INTENT)
        self.assertEqual((SCOPE['sourceId'],90000,True,'22'),(out['source'],out['start'],out['force'],out['audio']))
        self.assertIsNotNone(out['again'])
    def test_native_replacement_params_keep_explicit_start_caps_and_audio_through_ingress(self):
        params={'versionId':'file-1','startPositionMs':90000,'forceTranscode':True,'maxVideoBitrate':8000,'videoResolution':'1920x1080','audioStreamId':'22'}
        plan={'sourceId':SCOPE['sourceId'],'itemId':'1','versionId':'file-1','startPositionMs':0}
        detail={'versionsComplete':True,'item':{'sourceId':SCOPE['sourceId'],'itemId':'1'},'versions':[
            {'sourceId':SCOPE['sourceId'],'itemId':'1','versionId':'file-1','mediaId':'10','partId':'100',
             'mediaIndex':0,'partIndex':0,'partCount':1,'durationMs':600000,'audio':[{'id':'22'}]}]}
        out=self.call('NativePlexParams',params,plan,detail)
        self.assertEqual((90000,'file-1'),(out['start'],out['version']));self.assertIsNotNone(out['intent'])
        intent=out['intent'];self.assertEqual((90000,True,8000,'22'),(intent['owedStartMs'],intent['forceCompatible'],intent['maxVideoBitrate'],intent['audioStreamId']))
    def test_case_sensitive_untrusted_records_keep_rejecting_alias_collisions(self):
        valid=self.call('UntrustedRecord',SCOPE,PREF,INTENT,'')
        self.assertIsNotNone(valid['preference']);self.assertIsNotNone(valid['intent'])
        for alias in ('sourceid','SOURCEID'):
            with self.subTest(alias=alias):
                out=self.call('UntrustedRecord',SCOPE,PREF,INTENT,alias)
                self.assertIsNone(out['preference']);self.assertIsNone(out['intent'])

if __name__=='__main__':unittest.main()
