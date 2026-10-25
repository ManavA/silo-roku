"""Persistent holder Auto evidence through real child Tasks and HTTP/SDK leaves.

Retained choice comes from the actual no-choice Scene/Task producer. Technical
source identities are synthetic; these checks do not establish native playback.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_silo_p7_auto_producer as auto
from tests import test_silo_p7_compat_holder as p7
from tests import test_silo_compat_playback_task as holder
from tests import test_silo_p7_producer_flow as producer

ROOT=Path(__file__).resolve().parents[1]

class P7AutoHolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auto.P7AutoProducer.setUpClass()
        result=auto.P7AutoProducer().run_auto()
        cls.choice=result['outcome']['compatContinuation']['autoAudioSelection']

    def transcript(self, *, choice='valid', mutate=None, commands=False, overrides=None, command_change='', device=None, **kwargs):
        selected=copy.deepcopy(self.choice) if choice=='valid' else choice
        read=Path.read_text
        def source(path,*args,**kw):
            text=read(path,*args,**kw)
            if path==ROOT/'components/ApiTask.brs':
                old='function SiloCompatPreparationEnabled('
                assert old in text
                text=text.replace(old,'function ShippingSiloCompatPreparationEnabled(',1)
                text+='\nfunction SiloCompatPreparationEnabled() as Boolean\n return true\nend function\n'
                for gate in ('SiloP7CompatPreparationEnabled','SiloP7AACPreparationEnabled'):
                    text=text.replace('function '+gate+'(','function Shipping'+gate+'(',1)
                    text+='\nfunction '+gate+'() as Boolean\n return true\nend function\n'
            return text
        execute=holder.CompatPlaybackTask.transcript
        def fixture(instance,*args,**kw):
            kw['options']={**kw.get('options',{}),'autoVersion':True}
            if choice!='absent':kw['options']['autoAudioSelection']=selected
            kw['device_overrides']={**kw.get('device_overrides',{}),**producer.DEVICE,**(device or {})}
            return execute(instance,*args,**kw)
        schedule=p7.P7CompatHolder().commands() if commands else {}
        if commands:
            for key,value in schedule.items():
                injection='''if command.action="bind" or command.action="seek"
   command["autoVersion"]=true:command["autoAudioSelection"]=SpCopy(m.fixtureAutoChoice)
  end if
  '''+command_change+'\n  m.top.command=command'
                schedule[key]=value.replace('m.top.command=command',injection)
            key=' m.top={command:{action:"prepare"'
            schedule[key]=' m.fixtureAutoChoice=SpCopy(params.autoAudioSelection)\n'+key
        schedule.update(overrides or {})
        with patch.object(Path,'read_text',source),patch.object(holder.CompatPlaybackTask,'transcript',fixture):
            return p7.P7CompatHolder().transcript(mutate=mutate,sdk_overrides=schedule,**kwargs)

    def test_present_null_auto_marker_refuses_before_discovery_or_auth(self):
        result=self.transcript(choice=None)
        self.assertNotIn('fixtureError',result,result)
        self.assertEqual(['refused'],[r['phase'] for r in result['results']],result)
        self.assertFalse(result['results'][-1]['ok'])
        self.assertFalse(any('compat.example' in r['url'] or 'jellyfin' in r['url'] for r in result['requests']))
        self.assertEqual(0,result['mediaRequests'])

    def test_auto_mode_with_missing_choice_refuses_before_discovery_or_auth(self):
        result=self.transcript(choice='absent')
        self.assertEqual(['refused'],[r['phase'] for r in result['results']],result)
        self.assertFalse(any('compat.example' in r['url'] or '/compat/connect-info' in r['url'] for r in result['requests']))

    def test_fresh_preference_change_refuses_before_discovery_or_auth(self):
        def changed(values):
            values['detail']['versions'][0]['effective_audio_track_index']=2
        result=self.transcript(mutate=changed)
        self.assertEqual(['refused'],[r['phase'] for r in result['results']],result)
        self.assertEqual(1,len(result['requests']),result['requests'])
        self.assertFalse(any('/compat/connect-info' in r['url'] for r in result['requests']))

    def test_real_producer_choice_prepares_exact_pair_then_revokes_unused_credential(self):
        result=self.transcript()
        self.assertEqual(['prepared','closed'],[r['phase'] for r in result['results']],result)
        request=next(r for r in result['requests'] if '/PlaybackInfo' in r['url'])
        body=json.loads(request['body'])
        self.assertEqual((holder.SOURCE,2,-1),(body['MediaSourceId'],body['AudioStreamIndex'],body['SubtitleStreamIndex']))
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['privateCleared'])
        self.assertEqual(0,result['mediaRequests'])

    def test_reanchor_preference_drift_refuses_before_second_metadata_or_negotiation(self):
        def changed(values):
            values['reanchorDetail']=copy.deepcopy(values['detail'])
            values['reanchorDetail']['versions'][0]['effective_audio_track_index']=2
        result=self.transcript(mutate=changed,commands=True)
        self.assertNotIn('fixtureError',result,result)
        self.assertIn('seek_refused',[r['phase'] for r in result['results']],result)
        self.assertEqual(1,sum('/PlaybackInfo' in r['url'] for r in result['requests']))
        self.assertEqual(1,sum(r['url'].endswith('/Items/'+holder.SOURCE) for r in result['requests']))
        self.assertEqual(1,sum('/Sessions/Playing/Stopped' in r['url'] for r in result['requests']))
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['privateCleared'])

    def test_real_choice_reanchors_twice_and_owned_close_revokes(self):
        result=self.transcript(commands=True)
        self.assertNotIn('fixtureError',result,result)
        prepared=[r for r in result['results'] if r['phase']=='prepared']
        self.assertEqual([1,2,3],[r['planGeneration'] for r in prepared],result)
        self.assertEqual(3,sum('/PlaybackInfo' in r['url'] for r in result['requests']))
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['results'][-1]['mediaClosed'])
        self.assertTrue(result['privateCleared'])

    def test_lost_auto_metadata_on_bind_or_seek_refuses_but_close_still_revokes(self):
        for action,phase in [('bind','binding_refused'),('seek','seek_refused')]:
            with self.subTest(action=action):
                change='if command.action="'+action+'" then command.Delete("autoAudioSelection"):command.Delete("autoVersion")'
                result=self.transcript(commands=True,command_change=change)
                self.assertNotIn('fixtureError',result,result)
                self.assertIn(phase,[r['phase'] for r in result['results']],result)
                self.assertEqual(1,sum('/PlaybackInfo' in r['url'] for r in result['requests']))
                self.assertTrue(result['results'][-1]['credentialRevoked'])
                self.assertTrue(result['privateCleared'])

    def test_fresh_raw_title_or_unselected_inventory_drift_refuses_before_auth(self):
        def title(values):values['detail']['versions'][0]['audio_tracks'][2]['title']=''
        def inventory(values):values['detail']['versions'][0]['audio_tracks'].pop()
        for mutate in (title,inventory):
            with self.subTest(change=mutate.__name__):
                result=self.transcript(mutate=mutate)
                self.assertEqual(['refused'],[r['phase'] for r in result['results']],result)
                self.assertEqual(1,len(result['requests']))
                self.assertFalse(any('/compat/connect-info' in r['url'] for r in result['requests']))

    def test_reanchor_rechecks_unselected_mp4_query_before_new_negotiation(self):
        key=next(k for k in producer.DEVICE if 'format.chcnt' in k)
        device={key:'if m.autoQueryDrift=true and format.codec="truehd" and format.container="mp4" then return {result:true}\n        '+producer.DEVICE[key]}
        boundary='if m.fixtureDetailCount>1 then body=FormatJson(m.values["native/reanchor_detail"])'
        overrides={boundary:boundary+'\n  if m.fixtureDetailCount>1 then FixtureSiloDevice().autoQueryDrift=true'}
        result=self.transcript(commands=True,device=device,overrides=overrides)
        self.assertNotIn('fixtureError',result,result)
        self.assertIn('seek_refused',[r['phase'] for r in result['results']],result)
        self.assertEqual(1,sum('/PlaybackInfo' in r['url'] for r in result['requests']))
        self.assertEqual(1,sum(r['url'].endswith('/Items/'+holder.SOURCE) for r in result['requests']))
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['privateCleared'])

    def test_malformed_query_or_mixed_selected_pair_refuses_before_auth(self):
        malformed=copy.deepcopy(self.choice)
        malformed['queries'][0]['source_ordinal']=True
        mixed=copy.deepcopy(self.choice)
        mixed['audio_track_index']=0
        for choice in (malformed,mixed):
            with self.subTest(choice=choice['audio_track_index']):
                result=self.transcript(choice=choice)
                self.assertEqual(['refused'],[r['phase'] for r in result['results']],result)
                self.assertEqual(1,len(result['requests']))
                self.assertFalse(any('/compat/connect-info' in r['url'] for r in result['requests']))

    def test_malformed_public_bind_mode_or_kind_refuses_and_keeps_owned_close(self):
        for marker,mutation in [('mode','command.autoAudioSelection["mode"]=[]'),
                                ('kind','command["eligibilityKind"]={}'),
                                ('null_kind','command["eligibilityKind"]=invalid'),
                                ('array_kind','command["eligibilityKind"]=[]')]:
            with self.subTest(marker=marker):
                change='if command.action="bind"\n   '+mutation+'\n  end if'
                result=self.transcript(commands=True,command_change=change)
                self.assertNotIn('fixtureError',result,result)
                self.assertIn('binding_refused',[r['phase'] for r in result['results']],result)
                self.assertNotIn('binding',[r['phase'] for r in result['results']])
                self.assertTrue(result['results'][-1]['credentialRevoked'])
                self.assertTrue(result['privateCleared'])
