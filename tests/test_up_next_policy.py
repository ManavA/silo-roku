"""Continuation waits for genuine VOD clocks and both outgoing close receipts."""
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import ROOT as REPO, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/UpNextPolicy.brs'
MARKER = ROOT / 'source/core/MarkerPolicy.brs'
SCOPE = {'provider': 'plex', 'sourceId': 'plex:fixture', 'profileId': 'owner', 'generation': 9}
LEASE = {**SCOPE, 'generation': 8, 'sessionId': 'session-a'}


def episode(item='101', number=9, **changes):
    return {'provider': 'plex', 'sourceId': 'plex:fixture', 'itemId': item, 'type': 'episode', 'title': 'Episode ' + item,
            'seriesItemId': '10', 'parentItemId': '110', 'seasonNumber': 1, 'episodeNumber': number,
            'durationMs': 1200000, 'resumeMs': 0, **changes}


def config(**changes):
    return {'scope': SCOPE, 'leaseScope': LEASE, 'attemptId': 'play-1', 'versionId': 'file-a', 'item': episode(),
            'durationMs': 1200000, 'relativeTimeline': False, 'timelineOffsetMs': 0,
            'lookupId': 'next-1', 'previousLookupId': 'previous-1', 'stopId': 'stop-1', 'autoplayAllowed': True,
            'autoplayStreak': 0, **changes}


def event(kind, **changes):
    return {'kind': kind, 'scope': SCOPE, 'attemptId': 'play-1', 'versionId': 'file-a', 'itemId': '101', **changes}


def native(seconds=800, state='playing', **changes):
    status = {'attemptId': 'play-1', 'mode': 'playback', 'state': state, 'clipId': 7, 'errorCode': 0,
              'position': seconds, 'duration': 1200, 'renderedPosition': seconds, 'renderedClipId': 7, 'renderedEpoch': 0}
    status.update(changes.pop('status', {}))
    return event('native', **{'status':status,'landed':True,'settling':False,**changes})


def proof(previous=False, scope=None):
    scope = scope or SCOPE
    return {**scope, 'status': 'known', 'lookupId': 'previous-1' if previous else 'next-1',
            'currentItemId': '100' if previous else '101', 'nextItemId': '101' if previous else '102',
            'seriesId': '10', 'currentSeasonNumber': 1, 'nextSeasonNumber': 1,
            'currentSeasonItemId': '110', 'nextSeasonItemId': '110'}


def neighbors(previous=False, **changes):
    candidate = episode('100' if previous else '102', 8 if previous else 12)
    return event('neighbors', **{'direction':'previous' if previous else 'next','lookupId':'previous-1' if previous else 'next-1',
                 'status':'known','candidate':candidate,'proof':proof(previous),
                 'detail':{'item':candidate,'versions':[{'versionId':candidate['sourceId']+':'+candidate['itemId']+':900:901',
                        'mediaId':'900','partId':'901'}]},**changes})


def credits(start=1000000, end=1100000, final=False):
    return {'type': 'credits', 'startMs': start, 'endMs': end, 'isFinal': final}


def markers(marks=None, **changes):
    return event('markers', markers=marks if marks is not None else [credits()], **changes)


def intent(action='next', **changes):
    return event('intent', action=action, **changes)


def receipt(kind='terminal_result', **changes):
    return event(kind, **{'scope':LEASE,'stopId':'stop-1','ok':True,'terminal':True,**changes})


class UpNextPolicyTests(unittest.TestCase):
    def trace(self, *events, setup=None, alias=None):
        self.assertTrue(POLICY.is_file(), 'continuation policy is missing')
        with tempfile.TemporaryDirectory(prefix='silo-upnext-') as directory:
            temp = Path(directory)
            source = POLICY.read_text()
            if alias:
                source = source.replace('type(', 'UnFixtureType(') + f'''
function UnFixtureType(value as Dynamic) as String
    kind = Type(value)
    if kind="Integer" or kind="roInt" then return "{alias}"
    return kind
end function
'''
            path = temp/'policy.brs'
            path.write_text(source + '''
function UnTrace(config as Object, events as Object) as Object
    state = UpNextCreate(config)
    trace = []
    for each inputEvent in events
        decision = UpNextReduce(state,inputEvent)
        state = decision.state
        decision["projection"] = UpNextProjection(state)
        trace.Push(decision)
    end for
    return trace
end function
''')
            helpers=[MARKER,REPO/'source/core/EpisodeNeighbors.brs',REPO/'source/core/ContinueOverlay.brs']
            if alias:
                boxed=[]
                for helper in helpers:
                    facade=temp/helper.name
                    facade.write_text(helper.read_text().replace('type(', 'UnFixtureType('))
                    boxed.append(facade)
                helpers=boxed
            files = [REPO/'source/core/ServerUrlPolicy.brs',*helpers,path]
            return run_function(files, 'UnTrace', [setup or config(), list(events)], root=temp)

    def test_neighbor_read_is_once_after_playing_and_never_blocks_preplay(self):
        trace = self.trace(native(state='buffering'), native(state='paused'), native(landed=False), native())
        self.assertEqual([], trace[0]['effects'])
        self.assertEqual([], trace[1]['effects'])
        self.assertEqual('request_neighbors', trace[2]['effects'][0]['kind'])
        self.assertEqual('101', trace[2]['effects'][0]['anchor']['itemId'])
        self.assertEqual([], trace[3]['effects'])

    def test_earliest_latter_half_credits_start_is_target_and_countdown_starts_thirty_seconds_before(self):
        marks = [credits(900000, 1200000, True), credits(100000, 200000), credits(800000, 1000000)]
        trace = self.trace(native(700), neighbors(), markers(marks), native(770), native(770.1), native(800))
        self.assertEqual((770000, 800000), (trace[2]['state']['promptMs'], trace[2]['state']['targetMs']))
        self.assertEqual(30, trace[3]['projection']['countdownSeconds'])
        self.assertEqual(30, trace[4]['projection']['countdownSeconds'])
        self.assertEqual('close', trace[5]['effects'][0]['kind'])
        self.assertEqual('automatic_next', trace[5]['effects'][0]['origin'])

    def test_absent_and_invalid_credits_use_duration_minus_min_sixty_seconds_or_ten_percent(self):
        for duration, target, prompt in ((1200000, 1140000, 1110000), (120000, 108000, 78000)):
            trace = self.trace(native(0), markers([credits(1, 1), credits(-1, 1000)]), setup=config(durationMs=duration))
            self.assertEqual((target, prompt), (trace[-1]['state']['targetMs'], trace[-1]['state']['promptMs']))

    def test_paused_buffering_and_settling_do_not_autoplay_or_count_down_from_wall_clock(self):
        trace = self.trace(native(950), neighbors(), markers(), native(980, 'paused'),
                           native(1001, 'buffering'), native(1001, settling=True), native(1001))
        self.assertEqual(20, trace[3]['projection']['countdownSeconds'])
        self.assertFalse(any(e['kind']=='close' for step in trace[3:6] for e in step['effects']))
        self.assertEqual('close', trace[6]['effects'][0]['kind'])
        self.assertFalse(self.trace(native(), event('tick', nowMs=1e9))[-1]['accepted'])

    def test_unlanded_or_wrong_rendered_clip_epoch_and_optimistic_clock_cannot_auto_advance(self):
        for packet in (native(1001, landed=False), native(1001, status={'renderedPosition': 950, 'position': 1100}),
                       native(1001, status={'renderedEpoch': 1}), native(1001, status={'renderedClipId': 8}),
                       native(1001, status={'renderedPosition': -1})):
            trace = self.trace(native(800), neighbors(), markers(), packet)
            self.assertFalse(any(e['kind']=='close' for e in trace[-1]['effects']))

    def test_dismiss_and_manual_intent_persist_for_attempt_and_manual_next_still_works(self):
        trace = self.trace(native(980), neighbors(), markers(), intent('dismiss'), native(1100),
                           markers([credits(1100000,1200000)]), intent('next'))
        self.assertTrue(trace[3]['state']['dismissed'])
        self.assertFalse(trace[4]['projection']['shown'])
        self.assertEqual([], trace[4]['effects'])
        self.assertEqual('manual_next', trace[6]['effects'][0]['origin'])
        self.assertEqual(0, trace[6]['state']['autoplayStreak'])
        self.assertEqual([], self.trace(native(), neighbors(), intent(), intent())[-1]['effects'])

    def test_previous_requires_reverse_native_adjacency_proof_and_fresh_available_detail(self):
        trace = self.trace(native(), neighbors(previous=True), intent('previous'))
        self.assertEqual('100', trace[-1]['effects'][0]['target']['itemId'])
        for bad in (neighbors(previous=True, proof=proof()), neighbors(previous=True, detail={'item': episode('100'), 'versions': []})):
            self.assertFalse(self.trace(native(), bad)[-1]['projection']['previousAvailable'])

    def test_verified_final_episode_has_no_countdown_or_advance_and_unavailable_read_is_optional(self):
        for status in ('verified_end', 'retryable', 'ambiguous'):
            trace = self.trace(native(), event('neighbors', direction='next', lookupId='next-1', status=status), native(1199))
            self.assertFalse(trace[-1]['projection']['shown'])
            self.assertFalse(trace[-1]['projection']['nextAvailable'])
            self.assertEqual([], trace[-1]['effects'])

    def test_exactly_once_advance_waits_for_native_stop_and_successful_terminal_receipt_in_either_order(self):
        for ordered in ((receipt('native_stopped'), receipt()), (receipt(), receipt('native_stopped'))):
            trace = self.trace(native(), neighbors(), intent(), *ordered, receipt(), receipt('native_stopped'))
            self.assertEqual([], trace[3]['effects'])
            self.assertEqual('advance', trace[4]['effects'][0]['kind'])
            self.assertEqual('102', trace[4]['effects'][0]['target']['itemId'])
            self.assertEqual([], trace[5]['effects'])
            self.assertEqual([], trace[6]['effects'])

    def test_failed_or_wrongly_scoped_terminal_receipt_blocks_advance_and_retry_keeps_stop_id(self):
        trace = self.trace(native(), neighbors(), intent(), receipt('native_stopped'), receipt(ok=False),
                           event('retry'), receipt())
        self.assertEqual('blocked', trace[4]['state']['phase'])
        self.assertEqual('retry_terminal', trace[5]['effects'][0]['kind'])
        self.assertEqual('stop-1', trace[5]['effects'][0]['stopId'])
        self.assertEqual('advance', trace[6]['effects'][0]['kind'])
        for changes in ({'scope': {**LEASE,'sessionId':'other'}}, {'scope': {**LEASE,'profileId':'other'}},
                        {'scope': {**LEASE,'generation':9}}, {'stopId':'other'}, {'terminal':False}):
            trace = self.trace(native(), neighbors(), intent(), receipt('native_stopped'), receipt(**changes))
            self.assertEqual([], trace[-1]['effects'])

    def test_cancellation_while_closing_prevents_receipts_from_advancing_but_does_not_cancel_cleanup(self):
        trace = self.trace(native(), neighbors(), intent(), event('cancel'), receipt('native_stopped'), receipt())
        self.assertEqual('cancelled', trace[3]['state']['phase'])
        self.assertEqual([], trace[3]['effects'])
        self.assertEqual([], trace[-1]['effects'])

    def test_finished_waiting_neighbor_can_advance_after_proof_and_both_receipts_without_fake_completion(self):
        trace = self.trace(native(1190), native(1199,'finished'), receipt('native_stopped'), receipt(), neighbors())
        self.assertEqual('close', trace[1]['effects'][0]['kind'])
        self.assertEqual([], trace[3]['effects'])
        self.assertEqual('advance', trace[4]['effects'][0]['kind'])
        close = trace[1]['effects'][0]
        for forbidden in ('positionMs','durationMs','finished','watched','persistProgress'):
            self.assertNotIn(forbidden, close)

    def test_all_async_and_manual_events_are_source_profile_item_attempt_version_file_fenced(self):
        for changes in ({'scope':{**SCOPE,'sourceId':'plex:other'}}, {'scope':{**SCOPE,'profileId':'other'}},
                        {'scope':{**SCOPE,'generation':10}}, {'attemptId':'old'}, {'versionId':'file-b'}, {'itemId':'102'}):
            trace = self.trace(native(), neighbors(), intent(**changes))
            self.assertFalse(trace[-1]['accepted'])
            self.assertEqual([], trace[-1]['effects'])
            self.assertFalse(self.trace(native(), neighbors(**changes))[-1]['accepted'])

    def test_still_watching_is_optional_asked_once_after_three_autoplays_and_manual_play_resets(self):
        trace = self.trace(native(980), neighbors(), markers(), native(981),
                           event('watching_result', probability=.2), native(1001), intent(),setup=config(autoplayStreak=3))
        self.assertEqual(1, sum(e['kind']=='ask_still_watching' for step in trace[:4] for e in step['effects']))
        self.assertTrue(trace[4]['projection']['stillWatching'])
        self.assertEqual([], trace[5]['effects'])
        self.assertEqual('manual_next', trace[6]['effects'][0]['origin'])
        self.assertEqual(0, trace[6]['state']['autoplayStreak'])
        # Missing optional inference cannot block playback or countdown advancement.
        trace = self.trace(native(980), neighbors(), markers(), native(1001), setup=config(autoplayStreak=3))
        self.assertTrue(any(e['kind']=='close' for e in trace[-1]['effects']))

    def test_private_silo_url_scope_numeric_aliases_and_bounded_markers_do_not_leak_into_projection(self):
        scope={**SCOPE,'provider':'silo','sourceId':'silo:https://synthetic.example.test'}
        item=episode(provider='silo',sourceId=scope['sourceId'],seriesId='series-a')
        trace=self.trace(native(scope=scope), setup=config(scope=scope,leaseScope={**scope,'sessionId':'session-a'},item=item))
        self.assertIsNotNone(trace[0]['state'])
        self.assertNotIn('https:',str(trace[0]['projection']))
        for alias in ('roInteger','roLongInteger','roDouble'):
            self.assertTrue(self.trace(native(), neighbors(), intent(),alias=alias)[-1]['accepted'])
        trace=self.trace(native(), markers([credits(600000+i*1000,900000+i*1000) for i in range(100)]))
        self.assertLessEqual(len(trace[-1]['state']['markers']),32)

    def test_verified_proof_is_compact_and_never_retains_arbitrary_payload(self):
        raw=proof();raw['privatePayload']={'body':'X'*50000,'url':'https://synthetic.example.test/private'}
        step=self.trace(native(),neighbors(proof=raw))[-1]
        self.assertTrue(step['projection']['nextAvailable'])
        self.assertNotIn('privatePayload',step['state']['nextProof'])
        self.assertLess(len(str(step['state']['nextProof'])),600)

    def test_quiet_native_refresh_preserves_manual_origin_instead_of_auto_launching(self):
        trace=self.trace(native(800),neighbors(),markers(),native(1001,quiet=True),intent(),setup=config(autoplayStreak=3))
        self.assertFalse(any(e['kind']=='close' for e in trace[3]['effects']))
        self.assertEqual('manual_next',trace[-1]['effects'][0]['origin'])
        self.assertEqual(0,trace[-1]['state']['autoplayStreak'])

    def test_focus_event_is_bounded_and_attempt_fenced(self):
        trace=self.trace(native(980),neighbors(),markers(),event('focus',focus='dismiss'),event('focus',focus='bad'))
        self.assertTrue(trace[3]['accepted'])
        self.assertEqual('dismiss',trace[3]['projection']['focus'])
        self.assertFalse(trace[4]['accepted'])
        self.assertFalse(self.trace(native(),event('focus',focus='play',versionId='old'))[-1]['accepted'])
        closing=self.trace(native(),neighbors(),intent(),event('focus',focus='dismiss'))[-1]
        self.assertTrue(closing['accepted'],'Cancel must remain focusable during ordered cleanup')
        self.assertEqual('dismiss',closing['projection']['focus'])

    def test_unknown_runtime_allows_verified_manual_next_without_inventing_countdown(self):
        setup=config(durationMs=0,item=episode(durationMs=0))
        trace=self.trace(native(30),neighbors(),native(500),intent(),setup=setup)
        self.assertTrue(trace[0]['effects'],'unknown-duration episode lost verified manual navigation')
        self.assertEqual('request_neighbors',trace[0]['effects'][0]['kind'])
        self.assertTrue(trace[1]['projection']['nextAvailable'])
        self.assertFalse(trace[2]['projection']['shown'])
        self.assertEqual([],trace[2]['effects'])
        self.assertEqual('manual_next',trace[3]['effects'][0]['origin'])

    def test_error_native_state_does_not_read_or_advance_even_if_state_says_playing(self):
        trace=self.trace(native(30,status={'errorCode':-1001}))
        self.assertEqual([],trace[0]['effects'])
        self.assertFalse(trace[0]['state']['read'])
        trace=self.trace(native(800),neighbors(),markers(),native(1001,status={'errorCode':-19}))
        self.assertFalse(any(e['kind']=='close' for e in trace[-1]['effects']))

    def test_autoplay_disabled_keeps_manual_next_without_a_false_starting_countdown(self):
        trace=self.trace(native(980),neighbors(),markers(),native(1001),intent(),setup=config(autoplayAllowed=False))
        self.assertTrue(trace[2]['projection']['shown'])
        self.assertFalse(trace[2]['projection']['countdownStarted'])
        self.assertFalse(any(e['kind']=='close' for e in trace[3]['effects']))
        self.assertEqual('manual_next',trace[4]['effects'][0]['origin'])

    def test_final_marker_can_present_early_only_after_real_seek_lands_without_false_countdown(self):
        marker={'type':'recap','startMs':400000,'endMs':600000,'isFinal':True}
        trace=self.trace(native(500),neighbors(),markers([marker]),event('final_marker',marker=marker,clipId=7,renderedEpoch=0,settling=True),
            native(600),native(1111))
        self.assertTrue(trace[3]['accepted'])
        self.assertFalse(trace[3]['projection']['shown'])
        self.assertTrue(trace[4]['projection']['shown'])
        self.assertFalse(trace[4]['projection']['countdownStarted'])
        self.assertEqual([],trace[4]['effects'])
        self.assertEqual(29,trace[5]['projection']['countdownSeconds'])

    def test_final_marker_force_needs_exact_hydrated_marker_current_clip_epoch_and_next(self):
        marker={'type':'recap','startMs':400000,'endMs':600000,'isFinal':True}
        for changes in ({'clipId':8},{'renderedEpoch':1},{'versionId':'other'},
                        {'marker':{**marker,'endMs':600001}}):
            e=event('final_marker',**{'marker':marker,'clipId':7,'renderedEpoch':0,'settling':True,**changes})
            self.assertFalse(self.trace(native(500),neighbors(),markers([marker]),e)[-1]['accepted'])
        e=event('final_marker',marker=marker,clipId=7,renderedEpoch=0,settling=True)
        self.assertFalse(self.trace(native(500),markers([marker]),e)[-1]['accepted'])


if __name__=='__main__':
    unittest.main()
