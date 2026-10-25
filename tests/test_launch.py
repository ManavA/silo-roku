"""External Roku launch arguments and startup lifecycle behavior."""
from pathlib import Path
import unittest
import tempfile
import re
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUILaunchPolicy.brs'

class LaunchPolicyTests(unittest.TestCase):
    def test_launch_accepts_case_insensitive_keys_and_opaque_content_id(self):
        self.assertTrue(POLICY.exists(), 'launch policy is missing')
        self.assertEqual(run_function(POLICY, 'SiloUILaunchInput', [{'CONTENTID':'tmdb:movie:42','MEDIATYPE':'Movie'}]),
                         {'contentId':'tmdb:movie:42','mediaType':'movie'})

    def test_untrusted_or_unsupported_launches_are_rejected(self):
        for args in (None, {}, {'contentId':'https://example.org/a','mediaType':'movie'},
                     {'contentId':'a?token=x','mediaType':'episode'},
                     {'contentId':'x'*256,'mediaType':'movie'},
                     {'contentId':'a','mediaType':'channel'},
                     {'contentId':7,'mediaType':'movie'}):
            with self.subTest(args=args):
                self.assertIsNone(run_function(POLICY, 'SiloUILaunchInput', [args]))

    def controller(self, body, drain=False):
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'boundary.brs'
            boundary = BOUNDARY
            files = [POLICY, ROOT/'source/core/SiloUIFormat.brs', ROOT/'components/SiloUILaunch.brs']
            if drain:
                boundary = re.sub(r'(?ims)^function SiloUIBeginTransition.*?^end function\n', '', boundary)
                files.extend([ROOT/'components/SiloUIRobustness.brs', ROOT/'source/core/SiloPlaybackPolicy.brs'])
                boundary += DRAIN_BOUNDARY
            harness.write_text(boundary + "\nfunction Fixture() as Object\n" + body + "\nend function\n")
            return run_function([*files, harness], 'Fixture', [])

    def test_link_waits_for_sign_in_then_uses_authenticated_detail(self):
        self.assertTrue((ROOT/'components/SiloUILaunch.brs').exists(), 'launch controller missing')
        result = self.controller('''InitFixture()
    m.provider = "" : m.sourceId = "" : m.profileId = ""
    SiloUILaunchReceive({contentId:"movie-42",mediaType:"movie"})
    before = m.calls.Count()
    m.provider = "silo" : m.sourceId = "server" : m.profileId = "adult"
    SiloUILaunchTry()
    return {before:before,calls:m.calls,pending:m.launchPending}
''')
        self.assertEqual(result['before'], 0)
        self.assertEqual(result['calls'][0]['action'], 'detail')
        self.assertEqual(result['calls'][0]['params'], {'itemId':'movie-42'})

    def test_series_smart_bookmark_resolves_episode_and_plays_it(self):
        result = self.controller('''InitFixture()
    SiloUILaunchReceive({contentId:"show",mediaType:"series"})
    SiloUILaunchResult({ok:true},{item:{itemId:"show",type:"series",playItemId:"episode-3"}},m.calls[0].extra)
    SiloUILaunchResult({ok:true},{item:{itemId:"episode-3",type:"episode",resumeMs:9000}},m.calls[1].extra)
    return {played:m.played}
''')
        self.assertEqual(result['played'][0]['item']['itemId'], 'episode-3')
        self.assertEqual(result['played'][0]['start'], -1)

    def test_profile_prompt_defers_link_and_source_change_rejects_it(self):
        result = self.controller('''InitFixture()
    m.view = "onboarding"
    SiloUILaunchReceive({contentId:"a",mediaType:"movie"})
    before = m.calls.Count()
    m.view = "home" : m.sourceId = "another-server"
    SiloUILaunchTry()
    return {before:before,calls:m.calls,pending:m.launchPending}
''')
        self.assertEqual(result, {'before':0,'calls':[],'pending':None})

    def test_latest_link_wins_and_resumes_without_a_prompt(self):
        result = self.controller('''InitFixture()
    SiloUILaunchReceive({contentId:"old",mediaType:"movie"})
    first = m.calls[0].extra
    SiloUILaunchReceive({contentId:"new",mediaType:"movie"})
    second = m.calls[1].extra
    SiloUILaunchResult({ok:true},{item:{itemId:"old",type:"movie"}},first)
    SiloUILaunchResult({ok:true},{item:{itemId:"new",type:"movie",resumeMs:45000}},second)
    return {played:m.played}
''')
        self.assertEqual(result['played'], [{'item':{'itemId':'new','type':'movie','resumeMs':45000},'start':-1}])

    def test_unavailable_or_wrong_item_returns_home(self):
        result = self.controller('''InitFixture()
    SiloUILaunchReceive({contentId:"missing",mediaType:"movie"})
    SiloUILaunchResult({ok:true},{item:{itemId:"different",type:"movie"}},m.calls[0].extra)
    return {played:m.played,view:m.view,pending:m.launchPending}
''')
        self.assertEqual(result, {'played':[], 'view':'home','pending':None})

    def test_startup_beacon_waits_for_playback_and_closes_dialog_once(self):
        result = self.controller('''InitFixture()
    SiloUILaunchDialog(true)
    SiloUILaunchDialog(true)
    m.launchPending = {contentId:"a"}
    SiloUILaunchReady()
    before = m.beacons.Count()
    m.launchPending = invalid : m.playLoading = true
    SiloUILaunchReady()
    loading = m.beacons.Count()
    m.view = "player" : m.video = {state:"playing"}
    SiloUILaunchReady()
    SiloUILaunchReady()
    return {before:before,loading:loading,beacons:m.beacons}
''')
        self.assertEqual(result, {'before':1,'loading':1,'beacons':['AppDialogInitiate','AppDialogComplete','AppLaunchComplete']})

    def test_invalid_latest_input_fences_and_releases_outstanding_allocation(self):
        result = self.controller('''InitFixture()
    m.playToken = 5 : m.playLoading = true : m.cleanupTickets = {}
    m.pending = {one:{purpose:"play_start"}}
    SiloUILaunchReceive({contentId:"bad/url",mediaType:"movie"})
    owner = {provider:"silo",sourceId:"server",profileId:"adult",generation:1,sessionRevision:4}
    entry = {purpose:"play_start",generation:1,extra:5,owner:owner}
    cancelled = SiloUIAllocationResult(entry,{ok:true,plan:{sessionId:"lease",installationId:"install",stopId:"stop"}})
    return {cancelled:cancelled,token:m.playToken,loading:m.playLoading,tickets:m.cleanupTickets.Count(),calls:m.calls}
''', drain=True)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['token'], 6)
        self.assertFalse(result['loading'])
        self.assertEqual(result['tickets'], 1)
        self.assertEqual(result['calls'][0]['action'], 'playback_stop')
        self.assertFalse(result['calls'][0]['params']['persistProgress'])

    def test_home_loading_is_not_a_rendered_empty_library(self):
        result = self.controller('''InitFixture()
    m.homeRendered = false
    SiloUILaunchReady()
    return {beacons:m.beacons}
''')
        self.assertEqual(result['beacons'], [])

    def test_home_can_complete_after_empty_library_is_rendered(self):
        result = self.controller('''InitFixture()
    SiloUILaunchReady()
    return {beacons:m.beacons}
''')
        self.assertEqual(result['beacons'], ['AppLaunchComplete'])

BOUNDARY = '''
sub InitFixture()
    m.calls = [] : m.played = [] : m.beacons = []
    m.provider = "silo" : m.sourceId = "server" : m.profileId = "adult"
    m.generation = 1 : m.view = "home" : m.homeRows = [] : m.homeRendered = true
    m.top = {observeField:sub(field as String, callback as String)
    end sub,signalBeacon:sub(name as String)
        m.global.beacons.Push(name)
    end sub,global:m}
    SiloUILaunchInit()
end sub
sub Api(action as String, params as Object, purpose as String, extra = invalid as Dynamic)
    m.calls.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
function SiloUIBeginTransition(choice as Object) as Boolean
    SiloUILaunchFetch()
    return true
end function
sub PlayItem(item as Object, start as Integer)
    m.played.Push({item:item,start:start})
    m.playLoading = true
end sub
sub PlayerClose(finished as Boolean)
    m.view = "home"
end sub
sub ShowView(view as String)
    m.view = view
end sub
sub SetZone(zone as String)
    m.zone = zone
end sub
sub Toast(message as String)
    m.toastMessage = message
end sub
'''

DRAIN_BOUNDARY = '''
sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)
    m.view = "onboarding"
end sub
sub PlayerDiscardPrebuffer()
end sub
sub ApiOwned(action as String, params as Object, purpose as String, extra as Dynamic, owner as Object)
    Api(action,params,purpose,extra)
end sub
'''

if __name__ == '__main__':
    unittest.main()
