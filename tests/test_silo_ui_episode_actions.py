"""Episode options keep the series page and bind every action to its owner."""
import unittest
from tests.test_silo_ui_detail_experimental import version
import json,re
from tests import test_silo_ui_detail_policy as detail

ROOT = detail.ROOT


class EpisodeActionTests(unittest.TestCase):
    def scene(self, script):
        return detail.SiloUIDetailPolicyTests().scene('''
m.provider="silo":m.sourceId="silo:server":m.profileId="p":m.generation=2
m.view="detail":m.zone="episodes":m.browseViewToken=1:m.detailToken=4:m.detailSeasonRequest=3
m.detailItem={itemId:"series"}:m.focused={itemId:"ep",sourceId:"silo:server",type:"episode",title:"Arrival",resumeMs:42000}
m.top={}:m.labels=[]:m.plays=[]:m.requests=[]:m.toasts=[]
handled=DetailKey("options")
''' + script, replace=[('Api', '''sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.requests.Push({action:action,itemId:params.itemId,purpose:purpose})
 m.lastRequest={extra:extra,params:params}
end sub
'''),
            ('DetailFocusedEpisode', 'function DetailFocusedEpisode() as Dynamic\n return m.focused\nend function'),
            ('DetailEpisodeShow', '''sub DetailEpisodeShow(title as String,labels as Object,mode as String)
 node={id:m.requests.Count()+m.labels.Count(),buttonSelected:0,buttonFocused:0,isSameNode:function(other)
 return other<>invalid and m.id=other.id
 end function}
 m.labels=labels:m.top.dialog=node
 ticket=BrowseEventTicket(node,"episode_actions"):ticket.mode=mode:ticket.labels=labels
 m.detailEpisode.ticket=ticket
end sub'''),
            ('Toast', 'sub Toast(message as String)\n m.toasts.Push(message)\nend sub'),
        ], helpers=(ROOT/'components/SiloUIDialogs.brs').read_text()+'''
sub BrowseSocial(item as Object)
 m.social=item.itemId
end sub
sub PlayItem(item as Object,startMs as Dynamic,version="" as String,audio=invalid as Dynamic,experimental=invalid as Dynamic)
 m.lastExperimental=experimental
 m.plays.Push({itemId:item.itemId,startMs:startMs,version:version,audio:audio})
end sub
function ActionEvent() as Object
 return {node:m.top.dialog,getRoSGNode:function()
 return m.node
 end function}
end function
'''+re.search(r'function PlayerExperimentalChoiceValid[\s\S]*?end function',(ROOT/'components/SiloUIPlayer.brs').read_text()).group(0))

    def test_episode_experimental_requires_fresh_probe_and_plays_exact_file(self):
        rows=json.dumps([version()]).replace('"','""')
        result=self.scene('''DetailEpisodeResult({ok:true},{item:m.focused,versions:ParseJson("'''+rows+'''")},m.detailEpisode.ticket)
 probe=m.lastRequest.extra
 before=m.labels
 DetailResult("detail_experimental_probe",{ok:true},{available:true},probe)
 offered=m.labels
 for i=0 to m.labels.Count()-1
 if m.labels[i]="Experimental Play" then m.top.dialog.buttonSelected=i
 end for
 onDetailEpisodeAction(ActionEvent())
 print FormatJson({before:before,offered:offered,plays:m.plays,ticket:m.lastExperimental})''')
        self.assertNotIn('Experimental Play',result['before'])
        self.assertIn('Experimental Play',result['offered'])
        self.assertEqual('4k',result['plays'][0]['version'])
        self.assertEqual('ep',result['ticket']['itemId'])

    def test_episode_probe_rejects_changed_version_audio_focus_and_context(self):
        rows=json.dumps([version()]).replace('"','""')
        for change in ['m.detailEpisode.selected="missing"','m.detailEpisode.audio={}', 'm.focused={itemId:"other"}', 'm.generation=3', 'm.detailEpisode.active=false']:
            with self.subTest(change=change):
                result=self.scene('''DetailEpisodeResult({ok:true},{item:m.focused,versions:ParseJson("'''+rows+'''")},m.detailEpisode.ticket)
 probe=m.lastRequest.extra
 '''+change+'''
 DetailResult("detail_experimental_probe",{ok:true},{available:true},probe)
 print FormatJson({labels:m.labels,plays:m.plays})''')
                self.assertNotIn('Experimental Play',result['labels'])
                self.assertEqual([],result['plays'])

    def test_episode_ticket_remains_valid_during_play_loading_and_rejects_parent_or_owner_changes(self):
        rows=json.dumps([version()]).replace('"','""')
        result=self.scene('''DetailEpisodeResult({ok:true},{item:m.focused,versions:ParseJson("'''+rows+'''")},m.detailEpisode.ticket)
 probe=m.lastRequest.extra
 DetailResult("detail_experimental_probe",{ok:true},{available:true},probe)
 m.detailEpisode.active=false:m.playLoading=true
 accepted=PlayerExperimentalChoiceValid(probe,m.focused,"4k",invalid,m.detailEpisode.versions)
 m.detailEpisode.selected="other"
 changed=PlayerExperimentalChoiceValid(probe,m.focused,"4k",invalid,m.detailEpisode.versions)
 print FormatJson({accepted:accepted,changed:changed})''')
        self.assertEqual(dict(accepted=True,changed=False),result)

    def test_episode_unavailable_or_superseded_probe_keeps_basic_play(self):
        rows=json.dumps([version()]).replace('"','""')
        for result in ['{ok:false},{available:true}', '{ok:true},{available:false}', '{ok:true},{available:"true"}']:
            with self.subTest(result=result):
                value=self.scene('''DetailEpisodeResult({ok:true},{item:m.focused,versions:ParseJson("'''+rows+'''")},m.detailEpisode.ticket)
 old=m.lastRequest.extra
 DetailExperimentalProbe(true)
 fresh=m.lastRequest.extra
 DetailResult("detail_experimental_probe",{ok:true},{available:true},old)
 stale=m.labels
 DetailResult("detail_experimental_probe",'''+result+''',fresh)
 m.top.dialog.buttonSelected=0:onDetailEpisodeAction(ActionEvent())
 print FormatJson({stale:stale,labels:m.labels,play:m.plays[0],experimental:m.lastExperimental})''')
                self.assertNotIn('Experimental Play',value['stale'])
                self.assertNotIn('Experimental Play',value['labels'])
                self.assertEqual('ep',value['play']['itemId'])
                self.assertIsNone(value['experimental'])

    def test_probe_menu_update_preserves_focused_action_when_cancel_index_moves(self):
        rows=json.dumps([version(),dict(versionId='other',videoTracks=[],audioTracks=[])]).replace('"','""')
        for label in ['Cancel','Version']:
            with self.subTest(label=label):
                value=self.scene('''DetailEpisodeResult({ok:true},{item:m.focused,versions:ParseJson("'''+rows+'''")},m.detailEpisode.ticket)
 for i=0 to m.labels.Count()-1
 if m.labels[i]="'''+label+'''" then m.top.dialog.buttonFocused=i
 end for
 oldFocus=m.top.dialog.buttonFocused
 DetailResult("detail_experimental_probe",{ok:true},{available:true},m.lastRequest.extra)
 print FormatJson({oldFocus:oldFocus,focus:m.top.dialog.focusButton,label:m.labels[m.top.dialog.focusButton]})''')
                self.assertEqual(label,value['label'])
                self.assertEqual(value['oldFocus']+(1 if label=='Cancel' else 0),value['focus'])

    def test_remote_options_opens_focused_episode_and_other_zones_keep_social_menu(self):
        result=self.scene('''episodeRequests=m.requests:episodeLabels=m.labels:episodeSocial=m.social
 m.zone="detailButtons":m.requests=[]
 otherHandled=DetailKey("options")
 print FormatJson({handled:handled,requests:episodeRequests,labels:episodeLabels,episodeSocial:episodeSocial,otherHandled:otherHandled,social:m.social,otherRequests:m.requests})''')
        self.assertEqual(dict(handled=True,requests=[dict(action='detail',itemId='ep',purpose='detail_episode_actions')],labels=['Cancel'],episodeSocial=None,otherHandled=True,social='series',otherRequests=[]),result)

    def test_failed_metadata_keeps_resume_and_restart_without_versions(self):
        result=self.scene('''DetailResult("detail_episode_actions",{ok:false},{},m.detailEpisode.ticket)
 m.top.dialog.buttonSelected=1:onDetailEpisodeAction(ActionEvent())
 print FormatJson({labels:m.labels,plays:m.plays,series:m.detailItem.itemId,requests:m.requests,active:m.detailEpisode.active})''')
        self.assertEqual(['Resume','From beginning','Mark watched','Cancel'], result['labels'])
        self.assertEqual([dict(itemId='ep',startMs=0,version='',audio=None)], result['plays'])
        self.assertEqual('series',result['series'])
        self.assertEqual([dict(action='detail',itemId='ep',purpose='detail_episode_actions')],result['requests'])
        self.assertFalse(result['active'])

    def test_cancel_loading_rejects_late_metadata(self):
        result=self.scene('''ticket=m.detailEpisode.ticket
 onDetailEpisodeAction(ActionEvent())
 DetailEpisodeResult({ok:true},{item:m.focused,versions:[{versionId:"a"},{versionId:"b"}]},ticket)
 print FormatJson({labels:m.labels,active:m.detailEpisode.active,plays:m.plays})''')
        self.assertEqual(dict(labels=['Cancel'],active=False,plays=[]),result)

    def test_profile_season_focus_and_item_mismatch_cannot_offer_or_play_another_episode(self):
        for mutation in ['m.profileId="other"','m.detailSeasonRequest=4','m.focused={itemId:"other"}', 'm.detailToken=5']:
            with self.subTest(mutation=mutation):
                result=self.scene(mutation+'''
 DetailEpisodeResult({ok:true},{item:m.focused,versions:[]},m.detailEpisode.ticket)
 onDetailEpisodeAction(ActionEvent())
 print FormatJson({labels:m.labels,plays:m.plays})''')
                self.assertEqual(dict(labels=['Cancel'],plays=[]),result)
        result=self.scene('''DetailEpisodeResult({ok:true},{item:{itemId:"other",sourceId:"silo:server"}},m.detailEpisode.ticket)
 print FormatJson({active:m.detailEpisode.active,plays:m.plays,labels:m.labels})''')
        self.assertEqual(dict(active=False,plays=[],labels=['Cancel']),result)

    def test_back_and_replaced_dialog_reject_pending_episode_result(self):
        for action in ['onDetailEpisodeClosed(ActionEvent())', 'm.top.dialog={id:-1}']:
            with self.subTest(action=action):
                result=self.scene('ticket=m.detailEpisode.ticket\n'+action+'''
 DetailEpisodeResult({ok:true},{item:m.focused,versions:[]},ticket)
 onDetailEpisodeAction(ActionEvent())
 print FormatJson({active:m.detailEpisode.active,plays:m.plays,labels:m.labels})''')
                self.assertEqual(dict(active=False,plays=[],labels=['Cancel']),result)

    def test_exact_episode_version_and_audio_selection_reaches_playback(self):
        result=self.scene('''versions=[{versionId:"a",audioTracks:[]},{versionId:"b",audioTracks:[{id:"en",sourceOrdinal:0,codec:"aac",language:"en",channels:2},{id:"ja",sourceOrdinal:1,codec:"aac",language:"ja",channels:2}]}]
 DetailEpisodeResult({ok:true},{item:m.focused,versions:versions},m.detailEpisode.ticket)
 m.top.dialog.buttonSelected=3:onDetailEpisodeAction(ActionEvent())
 m.top.dialog.buttonSelected=2:onDetailEpisodeAction(ActionEvent())
 m.top.dialog.buttonSelected=4:onDetailEpisodeAction(ActionEvent())
 m.top.dialog.buttonSelected=2:onDetailEpisodeAction(ActionEvent())
 selectedVersions=DetailPlaybackVersions("ep")
 m.top.dialog.buttonSelected=0:onDetailEpisodeAction(ActionEvent())
 print FormatJson({play:m.plays[0],versions:selectedVersions.Count(),series:m.detailItem.itemId,season:m.detailSeasonRequest})''')
        self.assertEqual('ep',result['play']['itemId'])
        self.assertEqual('b',result['play']['version'])
        self.assertEqual(42000,result['play']['startMs'])
        self.assertEqual('ja',result['play']['audio']['trackId'])
        self.assertEqual(2,result['versions'])
        self.assertEqual('series',result['series'])
        self.assertEqual(3,result['season'])
