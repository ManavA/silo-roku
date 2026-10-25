"""Fresh detail/device → owned start/replan/stop HTTP seam.

Uses real eligibility and receipt policies. Synthetic HTTP and device responses
cannot prove native codec mapping, output or streaming reliability. The private
activation copy exercises transport behind the shipping disabled claim gate.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function
from tests import test_silo_playback_task as legacy

ROOT = Path(__file__).resolve().parents[1]


class SiloOriginalTransportTests(unittest.TestCase):
    def inputs(self):
        candidate = json.loads((ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())
        session = legacy.SiloPlaybackTaskTests().session()
        wire = json.loads((legacy.FIXTURES/'catalog_item_detail_movie.json').read_text())
        wire['content_id'] = 'fixture-item'
        wire['versions'] = [candidate['freshFile']['wire']]
        wire['versions'][0]['subtitle_tracks'] = []
        receipt = json.loads((ROOT/'tests/fixtures/silo/original_p7_receipt.json').read_text())
        receipt['timeline'] = {'player_start_seconds':0,'timeline_offset_seconds':0,'can_seek_anywhere':True}
        decision = {'protocol_version':3,'outcome':'plan','session_id':receipt['session_id'],'playback_plan':receipt}
        return session, wire, decision

    def ordinary_hls(self, decision):
        ordinary = copy.deepcopy(decision)
        raw = ordinary['playback_plan']
        raw.update(delivery='server_remux_hls',decision_reason='server_remux',transformations=[
            {'name':'server_dv7_to_hdr10','executor':'server','recipe_version':'2'},
            {'name':'audio_to_aac','executor':'server','recipe_version':'4'},
            {'name':'hls_mpegts','executor':'server','recipe_version':'1'}])
        raw['stream'].update(protocol='hls',container='hls')
        raw['effective_recipe'].update(dynamic_range='hdr10',audio_codec='aac',
                                      audio_channels=2,audio_layout='stereo')
        return ordinary

    def worker(self, session, wire, decision, *, active=False, change_revision=False, replan=None, start_options=None):
        cap = json.loads((legacy.FIXTURES/'playback_capabilities.json').read_text())
        cap['installation_id'] = 'server-install'
        cap['features'] = [] if replan is None else replan.get('features',[])
        if cap['features']: cap['deliveries'].append('server_remux_hls')
        responses = [{'statusCode':200,'body':json.dumps(x)} for x in [wire, cap, decision]]
        config = {} if replan is None else replan
        if config.get('mutations'):
            responses.extend([{'statusCode':200,'body':'{"outcome":"accepted"}'},{'statusCode':200,'body':'{"outcome":"stopped"}'}])
        elif replan is not None and not config.get('speculative'):
            if 'audioSelectIndex' in config:
                responses.extend([{'statusCode':200,'body':json.dumps(config.get('wire',wire))},{'statusCode':200,'body':json.dumps(cap)}])
            else:
                responses.append({'statusCode':200,'body':json.dumps(cap)})
                if active and not config.get('failure') and not config.get('disabled'):
                    responses.append({'statusCode':config.get('detailStatus',200),'body':json.dumps(config.get('wire',wire))})
            responses.append({'statusCode':config.get('status',200),'body':json.dumps(config['decision'])})
        else:
            responses.append({'statusCode':200,'body':'{"outcome":"stopped"}'})
        boundary = legacy.BOUNDARIES.replace('format.chcnt<=2 and format.codec="aac"','(format.chcnt<=2 and format.codec="aac") or (format.codec="ac3" and format.chcnt=6)')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api = root/'api.brs'
            api.write_text((ROOT/'components/ApiTask.brs').read_text().replace('function TaskUniqueId(', 'function UnusedTaskUniqueId(',1).replace('function TaskRokuSiloContext(', 'function UnusedTaskRokuSiloContext(',1).replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
            http = root/'http.brs'
            http.write_text((ROOT/'source/network/Http.brs').read_text().replace('function HttpRequest(', 'function UnusedHttpRequest(',1))
            policy = root/'original.brs'
            source = (ROOT/'source/core/SiloOriginalPlaybackPolicy.brs').read_text()
            if active:
                source = source.replace('function SiloOriginalActivationEnabled(', 'function ShippingDisabledSiloOriginalActivationEnabled(',1)
                source += '\nfunction SiloOriginalActivationEnabled() as Boolean\n return true\nend function\n'
            policy.write_text(source)
            files = [api,http,policy,ROOT/"source/core/SiloUIPlaybackChoicesPolicy.brs"]
            for path in legacy.FILES:
                if path.name == "SiloOriginalPlaybackPolicy.brs":
                    continue
                target=root/path.name
                target.write_text(path.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
                files.append(target)
            bridge = root/'bridge.brs'
            bridge.write_text(boundary+'''
function OriginalStart(session as Object,wire as Object,responses as Object,changeRevision as Boolean,config as Object,startOptions as Object) as Object
 decoded = DecodeSiloResponse("detail",FormatJson(wire),{sourceId:session.sourceId})
 detail = ScopeCatalogData(decoded.data,session.sourceId)
 params = {itemId:"fixture-item",fileId:"731",detail:detail,qualityPreference:"original",qualityExplicit:false}
 for each key in startOptions
  params[key] = startOptions[key]
 end for
 if config.speculative = true then params["speculativePrebuffer"] = true
 device = FixtureSiloDevice():device.videoMode="2160p60"
 started = RunSiloPlaybackStart(session,params,responses,changeRevision)
 if started.outcome.ok <> true or config.Count() = 0 or config.speculative = true then return started
 plan = started.outcome.plan
 if config.disabled = true then plan.siloPlayback["originalDisabled"] = true
 if config.mutations = true
  progress = TaskPlaybackEvent("silo",session,"playback_progress",{sessionId:plan.sessionId,installationId:plan.installationId,positionMs:12500,sequence:1,isPaused:false},0)
  stopped = TaskPlaybackEvent("silo",session,"playback_stop",{sessionId:plan.sessionId,installationId:plan.installationId,persistProgress:false,stopId:"10000000-0000-4000-8000-000000000002"},0)
  return {outcome:started.outcome,progress:progress,stopped:stopped,requests:m.requests}
 end if
 scope = {provider:"silo",sourceId:session.sourceId,profileId:session.profileId,generation:0}
 params = {sessionId:plan.sessionId,plan:plan,qualityPreference:"original",positionMs:12500,replanRequestId:"request-fixture-0002"}
 if config.failure = true then params["failureClassification"] = "decoder_failure"
 if config.audioSelectIndex <> invalid
  params.Delete("qualityPreference")
  params["audioTrackIndex"] = config.audioSelectIndex
  result = TaskSelectSiloAudio(session,params,scope,0)
 else
  result = TaskReplanSiloPlayback(session,params,scope,0)
 end if
 return {outcome:result,requests:m.requests}
end function
''')
            files.append(bridge)
            return run_function(files,'OriginalStart',[session,wire,responses,change_revision,config,start_options or {}],root=root)

    def test_shipping_gate_keeps_original_claims_and_audio_selectors_absent(self):
        session, wire, decision = self.inputs()
        decision["playback_plan"].pop("decision_reason")
        result = self.worker(session,wire,decision)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        body = json.loads(result['requests'][2]['body'])
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertNotIn('audio_track_index',body)
        self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))
        self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
        self.assertEqual({'installation_id':'server-install',
                         'stop_id':'10000000-0000-4000-8000-000000000001'},
                         json.loads(result['requests'][-1]['body']))

    def test_qualified_start_pins_ordinal_and_exposes_owned_original_descriptor(self):
        session, wire, decision = self.inputs()
        result = self.worker(session,wire,decision,active=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][2]['body'])
        self.assertEqual((1,'file:731:audio:1'),(body['audio_track_index'],body['audio_track_id']))
        expected = ['client_managed_dynamic_range_v1','client_selected_audio_track_v1']
        self.assertEqual(expected,body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertEqual([],body['client_features'])
        for name in ['progressive','hls']:
            self.assertEqual([],body['client_playback_context']['deliveries'][name]['validated_claims'])
        plan = result['outcome']['plan']
        self.assertEqual('mkv',plan['streamFormat'])
        self.assertEqual({'delivery':'original_http','recipeRange':'dolby_vision'},plan['playbackDiagnostics'])
        original = plan['originalPlayback']
        self.assertEqual(('731','session-fixture-01',1,'ac3'),(original['fileId'],original['sessionId'],original['audioIdentity']['index'],original['audioIdentity']['codec']))
        self.assertEqual(session['sourceId'],original['sourceId'])
        self.assertEqual('fixture-item',original['itemId'])
        self.assertEqual(plan['siloPlayback']['playbackAttemptId'],original['playbackAttemptId'])

    def test_changed_server_audio_is_rejected_and_allocated_session_is_closed(self):
        session, wire, decision = self.inputs()
        decision['playback_plan']['selected_tracks']['audio'] = {'id':'file:731:audio:0','index':0}
        result = self.worker(session,wire,decision,active=True)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('invalid_original_receipt',result['outcome']['errorCode'])
        self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
        cleanup = json.loads(result['requests'][-1]['body'])
        self.assertNotIn('position',cleanup)
        self.assertNotIn('originalPlayback',result['outcome'])

    def test_managed_original_receipt_without_fresh_proof_cannot_bind_video(self):
        session, wire, decision = self.inputs()
        wire['versions'][0]['video_tracks'][0]['dv_profile'] = 5
        result = self.worker(session,wire,decision,active=True)
        body = json.loads(result['requests'][2]['body'])
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertFalse(result['outcome']['ok'])
        # No current delivery-specific DV authority: refuse before Original diagnostics.
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        self.assertEqual('DELETE',result['requests'][-1]['method'])

    def test_guarded_progress_and_stop_keep_the_owned_session(self):
        session, wire, decision = self.inputs()
        result = self.worker(session,wire,decision,active=True,replan={'mutations':True})
        self.assertTrue(result['progress']['ok'])
        self.assertTrue(result['stopped']['ok'])
        self.assertEqual(['GET','GET','POST','POST','DELETE'],[r['method'] for r in result['requests']])
        self.assertIn('/session-fixture-01/progress',result['requests'][3]['url'])
        self.assertEqual(12.5,json.loads(result['requests'][3]['body'])['position'])
        self.assertNotIn('position',json.loads(result['requests'][4]['body']))

    def test_quality_replan_requires_fresh_same_file_and_keeps_selected_audio(self):
        session, wire, decision = self.inputs()
        replacement = copy.deepcopy(decision)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        result = self.worker(session,wire,decision,active=True,replan={'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST','GET','GET','POST'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual({'id':'file:731:audio:1','index':1},body['selected_tracks']['audio'])
        self.assertEqual(['opaque-attempt-key-01'],body['attempted_plan_keys'])
        self.assertEqual('session-fixture-01',result['outcome']['plan']['originalPlayback']['sessionId'])
        self.assertEqual('plan-fixture-02',result['outcome']['plan']['originalPlayback']['planId'])
        self.assertEqual(12500,result['outcome']['plan']['originalResumeMs'])

    def test_failed_original_withdraws_claims_and_refuses_new_original_key(self):
        session, wire, decision = self.inputs()
        repeated = copy.deepcopy(decision)
        repeated['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='different-original-key-02')
        result = self.worker(session,wire,decision,active=True,replan={'failure':True,'decision':repeated})
        self.assertFalse(result['outcome']['ok'])
        # The withdrawn Original route has no current DV authority.
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        self.assertTrue(result['outcome']['leaseUncertain'])
        self.assertTrue(result['outcome']['controlReceipt']['originalDisabled'])
        self.assertEqual('plan-fixture-02',result['outcome']['controlReceipt']['planId'])
        self.assertEqual(['GET','GET','POST','GET','POST'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertEqual({'classification':'decoder_failure'},body['failure'])
        self.assertEqual(['opaque-attempt-key-01'],body['attempted_plan_keys'])
        self.assertEqual({'id':'file:731:audio:1','index':1},body['selected_tracks']['audio'])

    def test_fresh_changed_source_refuses_replan_and_retains_new_control_receipt(self):
        session, wire, decision = self.inputs()
        replacement = copy.deepcopy(decision)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        changed = copy.deepcopy(wire)
        changed['versions'][0]['video_tracks'][0]['dv_profile'] = 5
        result = self.worker(session,wire,decision,active=True,replan={'wire':changed,'decision':replacement})
        self.assertFalse(result['outcome']['ok'])
        # No current delivery-specific DV authority: refuse before Original diagnostics.
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        self.assertTrue(result['outcome']['leaseUncertain'])
        self.assertEqual('plan-fixture-02',result['outcome']['controlReceipt']['planId'])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])

    def test_speculative_prebuffer_does_not_claim_or_select_original_audio(self):
        session, wire, decision = self.inputs()
        decision['playback_plan'].pop('decision_reason')
        result = self.worker(session,wire,decision,active=True,replan={'speculative':True})
        # P7 has no negotiated native route here. Speculation cannot allocate
        # a session merely to discover a server fallback or an Original claim.
        self.assertEqual({'ok':False,'errorCode':'unsupported_stream'},result['outcome'])
        self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_profile_revision_change_closes_allocated_original(self):
        session, wire, decision = self.inputs()
        result = self.worker(session,wire,decision,active=True,change_revision=True)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('session_changed',result['outcome']['errorCode'])
        self.assertEqual('DELETE',result['requests'][-1]['method'])

    def test_original_failure_keeps_patched_hdr10_copy_fallback(self):
        session, wire, decision = self.inputs()
        replacement = copy.deepcopy(decision)
        raw = replacement['playback_plan']
        raw.update(plan_id='plan-fixture-02',plan_attempt_key='copied-hdr10-key-02',delivery='server_remux_hls',decision_reason='server_remux',transformations=[{'name':'hls_mpegts','executor':'server','recipe_version':'1'}])
        raw['stream'].update(protocol='hls',container='hls')
        raw['effective_recipe'].update(dynamic_range='hdr10',audio_codec='eac3')
        result = self.worker(session,wire,decision,active=True,replan={'failure':True,'features':['native_hls_mpegts_v1'],'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        plan = result['outcome']['plan']
        self.assertEqual('hls',plan['streamFormat'])
        self.assertEqual('731',plan['versionId'])
        self.assertTrue(plan['siloPlayback']['originalDisabled'])
        self.assertNotIn('originalPlayback',plan)
        self.assertEqual({'delivery':'server_remux_hls','recipeRange':'hdr10'},plan['playbackDiagnostics'])

    def test_official_policy_terminal_does_not_start_another_original(self):
        session, wire, decision = self.inputs()
        terminal={'protocol_version':3,'outcome':'adaptation_unavailable','terminal':{'reason':'adaptation_exhausted','retryable':False}}
        result = self.worker(session,wire,decision,active=True,replan={'failure':True,'decision':terminal})
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('playback_terminal',result['outcome']['errorCode'])
        self.assertEqual(['GET','GET','POST','GET','POST'],[r['method'] for r in result['requests']])
        self.assertTrue(result['outcome']['leaseUncertain'])

    def test_server_fallback_cannot_silently_replace_requested_source_audio(self):
        session, wire, decision = self.inputs()
        decision['playback_plan'].update(delivery='server_remux_progressive',decision_reason='server_remux')
        decision['playback_plan']['selected_tracks']['audio'] = {'id':'file:731:audio:0','index':0}
        result = self.worker(session,wire,decision,active=True)
        self.assertFalse(result['outcome']['ok'])
        # No current delivery-specific DV authority: refuse before Original diagnostics.
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])

        body = json.loads(result['requests'][2]['body'])
        self.assertEqual((1,'file:731:audio:1'),(body['audio_track_index'],body['audio_track_id']))

    def test_uncertain_replan_keeps_lease_without_allocating_or_deleting_again(self):
        session, wire, decision = self.inputs()
        result = self.worker(session,wire,decision,active=True,replan={'failure':True,'status':503,'decision':{'detail':'private'}})
        self.assertFalse(result['outcome']['ok'])
        self.assertTrue(result['outcome']['leaseUncertain'])
        self.assertEqual('server_error',result['outcome']['errorCode'])
        self.assertEqual(['GET','GET','POST','GET','POST'],[r['method'] for r in result['requests']])
        self.assertNotIn('private',json.dumps(result['outcome']))

    def test_malformed_extra_source_facts_leave_ordinary_request_available(self):
        session, wire, decision = self.inputs()
        wire['versions'][0]['video_tracks'][0]['profile'] = {'untrusted':'shape'}
        decision['playback_plan'].pop('decision_reason')
        result = self.worker(session,wire,decision,active=True)
        # Dispatch remains available; unsolicited P7 bytes have no current DV proof.
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
        self.assertTrue(result['outcome']['cleanupLeaseClosed'])
        self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][2]['body'])
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertNotIn('audio_track_index',body)

    def test_public_dto_omitted_empty_subtitle_inventory_qualifies(self):
        session, wire, decision = self.inputs()
        wire['versions'][0].pop('subtitle_tracks')
        result = self.worker(session,wire,decision,active=True)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body = json.loads(result['requests'][2]['body'])
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertNotIn('subtitle_track_index',body)

    def test_local_off_with_source_subtitles_qualifies_with_public_dto_none(self):
        session, wire, decision = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        result = self.worker(session,wire,decision,active=True,start_options={'subtitleMode':'off'})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body = json.loads(result['requests'][2]['body'])
        # Official48ae validateTrackPairV3 rejects negative indices; omitted
        # selectors resolve to SubtitleOffV3 even with a source inventory.
        self.assertNotIn('subtitle_track_index',body)
        self.assertNotIn('subtitleMode',body)
        self.assertNotIn('subtitle_track_id',body)
    def test_guarded_replan_preserves_receipt_none_with_nonempty_subtitle_inventory(self):
        session, wire, decision = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        replacement = copy.deepcopy(decision)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        result = self.worker(session,wire,decision,active=True,start_options={'subtitleMode':'off'},replan={'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body = json.loads(result['requests'][-1]['body'])
        self.assertNotIn('subtitle',body['selected_tracks'])
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
    def test_other_subtitle_intents_and_malformed_inventory_keep_normal_requests(self):
        session, wire, decision = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        decision['playback_plan'].pop('decision_reason')
        cases = [({'subtitleMode':'auto'},True),({'subtitleMode':'forced'},True),
                 ({'subtitleMode':'off','subtitleTrackIndex':0},True),
                 ({'subtitleMode':'off','subtitleTrackId':'file:731:subtitle:0'},True),
                 ({'subtitleMode':'off'},False)]
        for options, active in cases:
            with self.subTest(options=options,active=active):
                result = self.worker(session,wire,decision,active=active,start_options=options)
                # Dispatch remains available; unsolicited P7 bytes have no current DV proof.
                self.assertFalse(result['outcome']['ok'])
                self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
                self.assertTrue(result['outcome']['cleanupLeaseClosed'])
                self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
                body = json.loads(result['requests'][2]['body'])
                self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
                for local, remote in [('subtitleTrackIndex','subtitle_track_index'),('subtitleTrackId','subtitle_track_id')]:
                    if local in options: self.assertEqual(options[local],body[remote])
                    else: self.assertNotIn(remote,body)
        for malformed in [None,{'unknown':'shape'}]:
            wire['versions'][0]['subtitle_tracks'] = malformed
            result = self.worker(session,wire,decision,active=True,start_options={'subtitleMode':'off'})
            body = json.loads(result['requests'][2]['body'])
            self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
            self.assertNotIn('subtitle_track_index',body)
    def test_negative_subtitle_selector_is_refused_before_public_start(self):
        session, wire, decision = self.inputs()
        result = self.worker(session,wire,decision,active=True,start_options={'subtitleTrackIndex':-1})
        self.assertEqual({'ok':False,'errorCode':'invalid_request'},result['outcome'])
        self.assertEqual([],result['requests'])

    def test_user_original_quality_from_ordinary_hls_builds_fresh_owned_candidate(self):
        session, wire, original = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        ordinary = self.ordinary_hls(original)
        replacement = copy.deepcopy(original)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':1},replan={'features':['native_hls_mpegts_v1'],'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST','GET','GET','POST'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertEqual({'id':'file:731:audio:1','index':1},body['selected_tracks']['audio'])
        self.assertEqual('session-fixture-01',result['outcome']['plan']['originalPlayback']['sessionId'])
        self.assertEqual(12500,result['outcome']['plan']['originalResumeMs'])

    def test_explicit_ac3_from_ordinary_hls_reuses_fresh_ingress_and_upgrades(self):
        session, wire, original = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        for audio in wire['versions'][0]['audio_tracks']:
            audio.update(title='Source Title',embedded_title='Embedded Title')
        ordinary = self.ordinary_hls(original)
        ordinary['playback_plan']['selected_tracks']['audio'] = {'id':'file:731:audio:0','index':0}
        ordinary['playback_plan']['source'].update(audio_codec='truehd',audio_channels=8,audio_layout='7.1')
        replacement = copy.deepcopy(original)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':0},replan={'features':['native_hls_mpegts_v1'],'audioSelectIndex':1,'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST','GET','GET','POST'],[r['method'] for r in result['requests']])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual({'id':'file:731:audio:1','index':1},body['selected_tracks']['audio'])
        self.assertEqual('ac3',result['outcome']['plan']['originalPlayback']['audioIdentity']['codec'])
    def test_ordinary_failure_and_withdrawn_lease_do_not_enable_original(self):
        session, wire, original = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        ordinary = self.ordinary_hls(original)
        replacement = self.ordinary_hls(original)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='hls-key-fixture-02')
        for mode in ['failure','disabled']:
            with self.subTest(mode=mode):
                config = {'features':['native_hls_mpegts_v1'],'decision':replacement,mode:True}
                result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':1},replan=config)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual(['GET','GET','POST','GET','POST'],[r['method'] for r in result['requests']])
                body = json.loads(result['requests'][-1]['body'])
                self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
                self.assertNotIn('originalPlayback',result['outcome']['plan'])
                if mode == 'disabled': self.assertTrue(result['outcome']['plan']['siloPlayback']['originalDisabled'])

    def test_original_quality_preserves_explicit_unsupported_truehd(self):
        session, wire, original = self.inputs()
        ordinary = self.ordinary_hls(original)
        ordinary['playback_plan']['selected_tracks']['audio'] = {'id':'file:731:audio:0','index':0}
        ordinary['playback_plan']['source'].update(audio_codec='truehd',audio_channels=8,audio_layout='7.1')
        replacement = copy.deepcopy(ordinary)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='hls-key-fixture-02')
        result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':0},replan={'features':['native_hls_mpegts_v1'],'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body = json.loads(result['requests'][-1]['body'])
        self.assertEqual({'id':'file:731:audio:0','index':0},body['selected_tracks']['audio'])
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertNotIn('originalPlayback',result['outcome']['plan'])

    def test_refused_upgrade_receipt_retains_the_owned_replan_lease(self):
        session, wire, original = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        ordinary = self.ordinary_hls(original)
        replacement = copy.deepcopy(original)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        replacement['playback_plan']['effective_recipe']['width'] = 1920
        result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':1},replan={'features':['native_hls_mpegts_v1'],'decision':replacement})
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('invalid_original_receipt',result['outcome']['errorCode'])
        self.assertTrue(result['outcome']['leaseUncertain'])
        self.assertEqual('session-fixture-01',result['outcome']['controlReceipt']['sessionId'])
        self.assertEqual('plan-fixture-02',result['outcome']['controlReceipt']['planId'])
        self.assertEqual(['GET','GET','POST','GET','GET','POST'],[r['method'] for r in result['requests']])

    def test_deactivated_original_quality_replan_skips_optional_detail_get(self):
        session, wire, original = self.inputs()
        ordinary = self.ordinary_hls(original)
        replacement = copy.deepcopy(ordinary)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='hls-key-fixture-02')
        result = self.worker(session,wire,ordinary,start_options={'audioTrackIndex':1},replan={'features':['native_hls_mpegts_v1'],'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST','GET','POST'],[r['method'] for r in result['requests']])
        self.assertEqual([],json.loads(result['requests'][-1]['body'])['client_playback_context']['deliveries']['original_http']['validated_claims'])

    def test_failed_optional_detail_keeps_ordinary_original_quality_replan_available(self):
        session, wire, original = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        ordinary = self.ordinary_hls(original)
        replacement = copy.deepcopy(ordinary)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='hls-key-fixture-02')
        result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':1},replan={'features':['native_hls_mpegts_v1'],'detailStatus':503,'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST','GET','GET','POST'],[r['method'] for r in result['requests']])
        self.assertEqual('hls',result['outcome']['plan']['streamFormat'])
        self.assertNotIn('originalPlayback',result['outcome']['plan'])
        self.assertEqual([],json.loads(result['requests'][-1]['body'])['client_playback_context']['deliveries']['original_http']['validated_claims'])
    def test_malformed_optional_detail_keeps_ordinary_replan_but_guarded_http_failure_refuses(self):
        session, wire, original = self.inputs()
        wire['versions'][0]['subtitle_tracks'] = [{'codec':'subrip','language':'en'}]
        ordinary = self.ordinary_hls(original)
        replacement = copy.deepcopy(ordinary)
        replacement['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='hls-key-fixture-02')
        result = self.worker(session,wire,ordinary,active=True,start_options={'audioTrackIndex':1},replan={'features':['native_hls_mpegts_v1'],'wire':{'unexpected':'shape'},'decision':replacement})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertNotIn('originalPlayback',result['outcome']['plan'])
        result = self.worker(session,wire,original,active=True,start_options={'subtitleMode':'off'},replan={'detailStatus':503,'decision':replacement})
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('server_error',result['outcome']['errorCode'])
        self.assertEqual(['GET','GET','POST','GET','GET'],[r['method'] for r in result['requests']])
