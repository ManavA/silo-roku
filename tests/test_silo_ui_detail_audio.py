"""Explicit detail audio stays scoped to one fresh source file and visit."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_brightscript, run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIDetailPolicy.brs'


def versions():
    return [dict(versionId='file-a', audioTracks=[
        dict(id='stable-dts', index=93, sourceOrdinal=0, codec='dts', language='eng', channels=6),
        dict(id='stable-ac3', index=94, sourceOrdinal=1, codec='ac3', language='eng', channels=6)])]


def choice():
    return dict(itemId='movie', fileId='file-a', trackId='stable-ac3', sourceOrdinal=1,
                codec='ac3', language='eng', channels=6, visit=4,
                sourceId='silo:one', profileId='profile', generation=2)


class SiloUIDetailAudio(unittest.TestCase):
    def choices(self, rows=None, selected='', provider='silo', kind='movie'):
        return run_function(POLICY, 'SiloUIDetailAudioChoices',
                            [provider, dict(itemId='movie', type=kind), versions() if rows is None else rows, selected])

    def test_requires_silo_leaf_and_selected_or_sole_file_with_multiple_tracks(self):
        self.assertEqual(2, len(self.choices()))
        for provider, kind in [('plex','movie'), ('silo','series'), ('silo','show')]:
            self.assertEqual([], self.choices(provider=provider, kind=kind))
        rows = versions() + [dict(versionId='file-b', audioTracks=versions()[0]['audioTracks'])]
        self.assertEqual([], self.choices(rows))
        self.assertEqual(2, len(self.choices(rows, 'file-b')))
        self.assertEqual([], self.choices(rows, 'gone'))
        rows = versions(); rows[0]['audioTracks'] = rows[0]['audioTracks'][1:]
        self.assertEqual([], self.choices(rows))

    def test_choices_use_source_ordinal_stable_id_and_human_labels(self):
        selected = self.choices()[1]
        self.assertEqual(1, selected['sourceOrdinal'])
        self.assertEqual('stable-ac3', selected['trackId'])
        self.assertEqual('file-a', selected['fileId'])
        self.assertEqual('movie', selected['itemId'])
        self.assertIn('English', selected['label'])
        self.assertIn('Dolby Digital', selected['label'])
        self.assertIn('5.1', selected['label'])
        self.assertNotIn('stable-', selected['label'])
        self.assertNotIn('94', selected['label'])

    def test_invalid_or_ambiguous_track_identity_is_not_offered(self):
        for key in ('sourceOrdinal', 'id'):
            rows = versions(); del rows[0]['audioTracks'][1][key]
            self.assertEqual([], self.choices(rows))
        rows = versions(); rows[0]['audioTracks'][1]['sourceOrdinal'] = 0
        self.assertEqual([], self.choices(rows))

    def test_fresh_match_rejects_changed_item_file_id_ordinal_and_track_metadata(self):
        self.assertIsNotNone(run_function(POLICY, 'SiloUIDetailAudioMatch', [choice(), 'movie', 'file-a', versions()]))
        for field, value in [('itemId','other'), ('fileId','file-b'), ('trackId','changed'),
                             ('sourceOrdinal',0), ('codec','eac3'), ('language','fra'), ('channels',2)]:
            selected = choice(); selected[field] = value
            self.assertIsNone(run_function(POLICY, 'SiloUIDetailAudioMatch', [selected, 'movie', 'file-a', versions()]))

    def player(self, code, selection=None, boundary_extra=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT/'components/SiloUIPlayer.brs').read_text()
            for name in ('PlayerResetChrome','PlayerDiscardPrebuffer','PlayerStart','PlayerShowFailure'):
                source = re.sub(r'(?im)^sub '+name+r'\(', 'sub Unused'+name+'(', source, count=1)
            source = re.sub(r'    print "Silo play timing.*\n', '', source)
            player = root/'player.brs'; player.write_text(source)
            boundary = root/'boundary.brs'
            boundary_source='''sub HomeCacheYield()
end sub
sub PlayerResetChrome()
end sub
sub PlayerDiscardPrebuffer()
 m.prebuf=invalid
end sub
sub PlayerStart(plan as Object, bound=false as Boolean)
 m.promoted=true
end sub
sub PlayerShowFailure(stage as String, result as Dynamic)
 m.failure=stage
end sub
function HomeProgressScope() as String
 return "scope"
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.sent.Push({action:action,params:params,purpose:purpose})
end sub
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 Api(action,params,purpose,extra)
end sub
sub Toast(message as String)
 m.message=message
end sub
'''
            if re.search(r'(?im)^\s*sub ApiOwned\(', boundary_extra):
                boundary_source=boundary_source.replace('sub ApiOwned(', 'sub UnusedApiOwned(', 1)
            boundary.write_text(boundary_source+boundary_extra)
            setup = '''m.provider="silo":m.view="detail":m.detailToken=4:m.playToken=1
 m.sourceId="silo:one":m.profileId="profile":m.generation=2:m.sent=[]:m.pending={}:m.cleanupTickets={}
 m.promoted=false:m.detailItem={itemId:"movie",type:"movie"}
'''
            setup += 'm.detailVersions=ParseJson("'+json.dumps(versions()).replace('"','""')+'")\n'
            setup += 'selected=ParseJson("'+json.dumps(choice() if selection is None else selection).replace('"','""')+'")\n'
            out = run_brightscript([POLICY,ROOT/'components/SiloUIDetail.brs',ROOT/'components/SiloUIRobustness.brs',ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloUISettingsPolicy.brs',player,boundary], setup+code, root=root)
            return json.loads(out.strip().splitlines()[-1])

    def test_explicit_choice_pins_file_bypasses_prebuffer_and_forwards_fresh_selector(self):
        result = self.player('''m.prebuf={ready:true,itemId:"movie",startMs:0,item:{itemId:"movie"},plan:{}}
 PlayItem(m.detailItem,0,"",selected)
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({promoted:m.promoted,requests:m.sent})''')
        self.assertFalse(result['promoted'])
        self.assertEqual('detail', result['requests'][0]['action'])
        params = {k.lower():v for k,v in result['requests'][1]['params'].items()}
        self.assertEqual('file-a', params['fileid'])
        self.assertFalse(params['autoversion'])
        self.assertEqual(1, params['audiotrackindex'])
        self.assertEqual('file:file-a:audio:1', params['audiotrackid'])

    def test_wire_index_identity_stays_local_while_request_uses_source_ordinal_id(self):
        selected=choice();selected['trackId']='3'
        result=self.player('''m.detailVersions[0].audioTracks[1].id="3"
 m.detailVersions[0].audioTracks[1].index=3
 m.detailVersions[0].audioTracks[1].wireIndexPresent=true
 PlayItem(m.detailItem,0,"file-a",selected)
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({requests:m.sent,rawId:selected.trackId,retained:m.playAudioChoice.trackId})''',selection=selected)
        params={k.lower():v for k,v in result['requests'][-1]['params'].items()}
        self.assertEqual(1,params['audiotrackindex'])
        self.assertEqual('file:file-a:audio:1',params['audiotrackid'])
        self.assertEqual('3',result['rawId'])
        self.assertEqual('3',result['retained'])

    def test_changed_visit_or_owner_refuses_before_starting(self):
        for field,value in [('visit',3),('sourceId','other'),('profileId','other'),('generation',1)]:
            with self.subTest(field=field):
                selected = choice(); selected[field] = value
                result = self.player('''
 PlayItem(m.detailItem,0,"",selected)
 print FormatJson({requests:m.sent,message:m.message})''',selection=selected)
                self.assertEqual([], result['requests'])
                self.assertIn('audio', result['message'].lower())

    def test_changed_fresh_track_does_not_allocate_or_silently_use_default(self):
        result = self.player('''PlayItem(m.detailItem,0,"",selected)
 m.detailVersions[0].audioTracks[1].id="replacement"
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({requests:m.sent,message:m.message,loading:m.playLoading})''')
        self.assertEqual(1, len(result['requests']))
        self.assertFalse(result['loading'])
        self.assertIn('audio', result['message'].lower())

    def test_pending_explicit_choice_cannot_cross_detail_visit_or_owner(self):
        for change in ('m.detailToken=5', 'm.generation=3', 'm.view="home"', 'm.provider="plex"'):
            with self.subTest(change=change):
                result = self.player('''PlayItem(m.detailItem,0,"",selected)
'''+change+'''
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({requests:m.sent,message:m.message,loading:m.playLoading})''')
                self.assertEqual(1, len(result['requests']))
                self.assertFalse(result['loading'])
                self.assertIn('audio', result['message'].lower())


    def detail(self, code):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT/'components/SiloUIDetail.brs').read_text()
            source = source.replace('CreateObject("roSGNode", "Dialog")', 'FakeDialog()')
            source = re.sub(r'(?im)^sub DetailRender\(', 'sub UnusedDetailRender(', source, count=1)
            detail = root/'detail.brs'; detail.write_text(source)
            boundary = root/'boundary.brs'
            boundary.write_text('''function FakeDialog() as Object
 m.dialogId += 1
 return {identity:m.dialogId,observeField:sub(field,handler)
 end sub,isSameNode:function(other)
 return m.identity=other.identity
 end function}
end function
sub DetailRender(item as Object)
 m.rendered=true
end sub
sub PlayerDiscardPrebuffer()
 m.discarded=true
end sub
sub Toast(message as String)
 m.message=message
end sub
function AudioEvent(node as Object) as Object
 return {node:node,getRoSGNode:function()
 return m.node
 end function}
end function
sub PlayItem(item as Object, startMs as Dynamic, fileId="" as String, audio=invalid as Dynamic)
 m.playedAudio=audio
end sub
''')
            setup='''m.provider="silo":m.view="detail":m.detailToken=4:m.browseViewToken=9
 m.sourceId="silo:one":m.profileId="profile":m.generation=2:m.dialogId=0:m.top={}
 m.detailSelectedVersion="":m.detailItem={itemId:"movie",type:"movie"}
'''
            setup += 'm.detailVersions=ParseJson("'+json.dumps(versions()).replace('"','""')+'")\n'
            output=run_brightscript([POLICY,ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIDialogs.brs',detail,boundary],setup+code,root=root)
            return json.loads(output.strip().splitlines()[-1])

    def test_dialog_cancel_keeps_choice_default_clears_it_and_play_forwards_choice(self):
        result=self.detail('''DetailAudioPicker()
 labels=m.top.dialog.buttons
 m.top.dialog.buttonSelected=2:onDetailAudio(AudioEvent(m.top.dialog))
 chosen=m.detailAudioChoice
 DetailAudioPicker():m.top.dialog.buttonSelected=3:onDetailAudio(AudioEvent(m.top.dialog))
 kept=m.detailAudioChoice.trackId=chosen.trackId
 m.detailActions=["Play"]:DetailAction(0)
 passed=m.playedAudio.trackId=chosen.trackId
 DetailAudioPicker():m.top.dialog.buttonSelected=0:onDetailAudio(AudioEvent(m.top.dialog))
 print FormatJson({labels:labels,chosen:chosen,kept:kept,passed:passed,cleared:m.detailAudioChoice})''')
        self.assertEqual('Server default',result['labels'][0])
        self.assertEqual('Cancel',result['labels'][-1])
        self.assertEqual(1,result['chosen']['sourceOrdinal'])
        self.assertEqual(4,result['chosen']['visit'])
        self.assertTrue(result['kept'])
        self.assertTrue(result['passed'])
        self.assertIsNone(result['cleared'])

    def test_stale_audio_dialog_cannot_change_new_visit_or_replaced_dialog(self):
        for change in ('m.detailToken=5', 'DetailAudioPicker()', 'm.detailSelectedVersion="other"'):
            with self.subTest(change=change):
                result=self.detail('''DetailAudioPicker():old=m.top.dialog:old.buttonSelected=2
'''+change+'''
 onDetailAudio(AudioEvent(old))
 print FormatJson(m.detailAudioChoice)''')
                self.assertIsNone(result)

    def test_version_selection_clears_audio_and_renders_available_actions(self):
        result=self.detail('''DetailAudioPicker():m.top.dialog.buttonSelected=2:onDetailAudio(AudioEvent(m.top.dialog))
 m.detailVersionVisit=4:m.detailVersionDialog={buttonSelected:0}
 onDetailVersion()
 print FormatJson({audio:m.detailAudioChoice,rendered:m.rendered})''')
        self.assertIsNone(result['audio'])
        self.assertTrue(result['rendered'])


if __name__ == '__main__':
    unittest.main()
