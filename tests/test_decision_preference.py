"""Exact public preference/clock/gateway projections; no native IO."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

C = Path(__file__).resolve().parents[1]
ROOT = C if (C/'tools/brightscript.py').exists() else Path.cwd()
sys.path.insert(0,str(ROOT))
from tools.brightscript import run_function

SCOPE = {'provider':'plex','sourceId':'plex:fixture','profileId':'owner','generation':7}
PREF = {'schemaVersion':1,'sourceId':SCOPE['sourceId'],'profileId':'owner','personalized':False,
        'cloudDecisions':False,'stillWatchingCheck':False,'gatewayOrigin':''}
VIEWER = {'daypart':'late','weekend':False,'device':'tv','session':{'minutes':140,'episodes_in_row':3}}
NOW = 1792000000123

class DecisionPreferenceTests(unittest.TestCase):
    def call(self,name,*args,bridge=''):
        policy=C/'source/core/DecisionPreference.brs'
        self.assertTrue(policy.exists(),'Decision preference behavior is missing')
        files=[ROOT/'source/core/ServerUrlPolicy.brs',policy]
        adapter=C/'source/adapters/DecisionGatewayAdapter.brs'
        if adapter.exists():files.append(adapter)
        with tempfile.TemporaryDirectory(prefix='silo_ui-decision-pure-') as d:
            p=Path(d)
            if bridge:
                fixture=p/'fixture.brs';fixture.write_text(bridge);files.append(fixture)
            return run_function(files,name,list(args),root=p)

    def test_default_is_exact_seven_fields_off_with_no_gateway(self):
        self.assertEqual(PREF,self.call('DecisionPreferenceDefaults',SCOPE))
        self.assertIsNone(self.call('DecisionPreferenceNormalize',None,SCOPE))
        self.assertEqual(PREF,self.call('DecisionPreferenceNormalize',PREF,SCOPE))

    def test_full_set_rejects_foreign_malformed_secret_and_case_collision_records(self):
        bad=[None,[],{}, {**PREF,'sourceId':'plex:foreign'}, {**PREF,'profileId':'other'},
             {**PREF,'schemaVersion':True},{**PREF,'schemaVersion':2},{**PREF,'personalized':1},
             {**PREF,'cloudDecisions':'true'},{**PREF,'stillWatchingCheck':None},
             {**PREF,'token':'synthetic-private'}, {**PREF,'Personalized':True}]
        bridge='''
function FixturePreferences(values as Object,scope as Object) as Object
 answers=[]
 for each raw in values
  answers.Push(DecisionPreferenceNormalize(raw,scope))
 end for
 return answers
end function
'''
        self.assertEqual([None]*len(bad),self.call('FixturePreferences',bad,SCOPE,bridge=bridge))

    def test_origin_has_no_path_credentials_query_fragment_or_cleartext(self):
        values=['','HTTPS://Gateway.Example.Test:443/','https://gateway.example.test:08443',
                'https://[2001:DB8::1]:443/',None,1,'http://gateway.example.test',
                'https://user@gateway.example.test','https://gateway.example.test/decide',
                'https://gateway.example.test?secret=x','https://gateway.example.test#x',
                ' https://gateway.example.test','https://gateway.example.test\n',
                'https://gateway.example.test:0','https://gateway.example.test:65536',
                'https://bad..test','https://gateway.example.test//']
        expected=['','https://gateway.example.test','https://gateway.example.test:8443','https://[2001:db8::1]']+[None]*13
        bridge='''
function FixtureOrigins(values as Object) as Object
 answers=[]
 for each value in values
  answers.Push(DecisionGatewayOrigin(value))
 end for
 return answers
end function
'''
        self.assertEqual(expected,self.call('FixtureOrigins',values,bridge=bridge))

    def test_validated_alias_record_returns_normal_native_lookup(self):
        bridge='''
function FixtureNormalLookup(raw as Object,scope as Object) as Object
 out=DecisionPreferenceNormalize(raw,scope)
 if out=invalid then return invalid
 return {source:out.SOURCEID,profile:out.PROFILEID,off:out.STILLWATCHINGCHECK}
end function
'''
        aliased={k.lower():v for k,v in PREF.items()}
        self.assertEqual({'source':'plex:fixture','profile':'owner','off':False},self.call('FixtureNormalLookup',aliased,SCOPE,bridge=bridge))

    def test_epoch_whole_validation_never_truncates_large_milliseconds(self):
        bridge='''
function FixtureEpoch(values as Object) as Object
 out=[]
 for each value in values
  out.Push(DecisionEpochMs(value))
 end for
 out.Push(DecisionEpochMs(1792000000123# + 0.5#))
 return out
end function
'''
        # ParseJson in the host rounds a huge JSON fractional number to Float;
        # construct the actual native Double fraction at the accessor boundary.
        values=[NOW,True,str(NOW),-1,9000000000001,9000000000000,2147483649]
        self.assertEqual([True,False,False,False,False,True,True,False],self.call('FixtureEpoch',values,bridge=bridge))

    def test_clock_uses_native_millisecond_snapshot_without_second_rounding(self):
        source=C/'source/adapters/DecisionGatewayAdapter.brs'
        self.assertTrue(source.exists(),'Decision gateway adapter is missing')
        with tempfile.TemporaryDirectory(prefix='silo_ui-decision-clock-') as d:
            p=Path(d);adapter=p/'adapter.brs'
            adapter.write_text(source.read_text().replace('CreateObject("roDateTime")','FixtureDecisionDate()'))
            fixture=p/'fixture.brs';fixture.write_text('''
function FixtureDecisionDate() as Object
 return {AsMillisecondsLong:function() as Double
  return 1792000000999#
 end function}
end function
''')
            value=run_function([adapter,fixture],'DecisionNowMs',[],root=p)
            self.assertEqual(1792000000999,value)

    def test_gateway_requests_only_project_exact_coarse_state_and_install_bearer(self):
        value=self.call('BuildDecisionGatewayRequest','decide','https://gateway.example.test','synthetic-install',VIEWER)
        self.assertTrue(value['ok']);self.assertEqual('POST',value['method'])
        self.assertEqual('https://gateway.example.test/decide',value['url'])
        self.assertEqual({'Accept':'application/json','Content-Type':'application/json','Authorization':'Bearer synthetic-install'},value['headers'])
        self.assertEqual({'kind':'upnext','version':1,'state':{'viewer':VIEWER}},json.loads(value['body']))
        self.assertEqual(8192,value['responseBodyLimit'])
        for changed in ({**VIEWER,'sourceId':'plex:fixture'}, {**VIEWER,'weekend':1},
                        {**VIEWER,'session':{**VIEWER['session'],'minutes':1.5}},
                        {**VIEWER,'session':{**VIEWER['session'],'episodes_in_row':2}}):
            self.assertFalse(self.call('BuildDecisionGatewayRequest','decide','https://gateway.example.test','synthetic-install',changed)['ok'])
        value=self.call('BuildDecisionGatewayRequest','install','https://gateway.example.test','',None)
        self.assertEqual('{}',value['body']);self.assertNotIn('Authorization',value['headers'])

    def test_answer_requires_exact_type_finite_range_and_bounded_utf8_body(self):
        for raw in ({'type':'noul','noul':.2},{'type':'Noul','noul':.2},{'type':'noul','noul':'0.2'},
                    {'type':'noul','noul':True},{'type':'noul','noul':-.1},{'type':'noul','noul':1.1}):
            value=self.call('DecodeDecisionGatewayAnswer',json.dumps({'answers':{'still_watching':raw}}))
            self.assertEqual({'probability':.2} if raw=={'type':'noul','noul':.2} else None,value)
        for body in ('null','[]','{}',' '*8193,'é'*4097):
            self.assertIsNone(self.call('DecodeDecisionGatewayAnswer',body))

if __name__=='__main__':unittest.main()
