"""LAN chooser behavior at the approved onboarding and Task result seams."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from tools.brightscript import run_brightscript
from tests.test_lan_identity import CANDIDATE
ROOT = Path(__file__).resolve().parents[1]

class LanChooserTests(unittest.TestCase):
    def ui(self, script):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            onboarding = (ROOT/'components/SiloUIOnboarding.brs').read_text()
            onboarding = re.sub(r'sub ObScreen\(.*?\nend sub', '''sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)
 if m.lanRendering <> true then SiloUILanRetire()
 m.title=b:m.body=c:m.choices=choices:m.view="onboarding"
end sub''', onboarding, count=1, flags=re.S)
            onboarding = re.sub(r'sub ObServerAddressDialog\(\).*?\nend sub', '', onboarding, count=1, flags=re.S)
            (directory/'onboarding.brs').write_text(onboarding)
            helper = (ROOT/'components/SiloUILan.brs').read_text()
            helper = re.sub(r'sub SiloUILanStartTask\(.*?\nend sub', '''sub SiloUILanStartTask(kind as String,job as Object)
 m.started.Push({kind:kind,job:job})
end sub''', helper, count=1, flags=re.S)
            (directory/'lan.brs').write_text(helper)
            (directory/'stubs.brs').write_text('''
sub SetZone(zone as String)
end sub
sub ObServerAddressDialog()
 m.dialogOpened=true
end sub
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent.Push({action:action,params:params})
end sub
''')
            paths = [ROOT/'source/core/LanDiscoveryPolicy.brs',ROOT/'source/core/LanIdentityPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloUISignInPolicy.brs',ROOT/'components/SiloUISignIn.brs',directory/'onboarding.brs',directory/'lan.brs',directory/'stubs.brs']
            output = run_brightscript(paths, '''
 m.generation=7:m.view="onboarding":m.pollTimer={control:"stop"}:m.savedServers=[]
 m.started=[]:m.sent=[]:m.sourceId="silo:existing":m.profileId="existing"
 m.candidate=ParseJson('''+'"'+json.dumps(CANDIDATE).replace('"','""')+'"'+''')
 '''+script, root=directory)
            return json.loads(output)

    def test_find_servers_is_explicit_and_discovery_does_not_change_session(self):
        result=self.ui('''
 ObShowSiloServers()
 before=m.choices
 ObChoose({action:"silo_find"})
 print FormatJson({before:before,started:m.started,sent:m.sent,source:m.sourceId,profile:m.profileId})
 ''')
        self.assertIn('silo_find',[c['action'] for c in result['before']])
        self.assertEqual('LanDiscoveryTask',result['started'][0]['kind'])
        self.assertEqual([],result['sent'])
        self.assertEqual(('silo:existing','existing'),(result['source'],result['profile']))

    def test_selected_address_requires_confirmation_and_matching_identity_before_signin(self):
        result=self.ui('''
 ObChoose({action:"silo_find"})
 SiloUILanResult({token:m.lanToken,generation:7,status:"complete",candidates:[m.candidate]})
 candidateChoice=m.choices[0]
 ObChoose(candidateChoice)
 confirmation={body:m.body,sent:m.sent.Count(),tasks:m.started.Count()}
 ObChoose(m.choices[0])
 checking={sent:m.sent.Count(),tasks:m.started.Count(),job:m.started[1].job}
 SiloUILanResult({token:m.lanToken,generation:7,ok:true,serverId:m.candidate.serverId,trusted:false})
 print FormatJson({confirmation:confirmation,checking:checking,sent:m.sent})
 ''')
        self.assertIn(CANDIDATE['address'],result['confirmation']['body'])
        self.assertEqual((0,1),(result['confirmation']['sent'],result['confirmation']['tasks']))
        self.assertEqual((0,2),(result['checking']['sent'],result['checking']['tasks']))
        self.assertEqual(0,result['checking']['job']['selected'])
        self.assertEqual([{'action':'set_server','params':{'baseUrl':f"http://{CANDIDATE['address']}:{CANDIDATE['port']}"}}],result['sent'])

    def test_back_and_generation_changes_discard_late_identity_and_discovery(self):
        result=self.ui('''
 ObChoose({action:"silo_find"})
 oldToken=m.lanToken
 OnboardingKey("back")
 SiloUILanResult({token:oldToken,generation:7,status:"complete",candidates:[m.candidate]})
 afterBack=m.title
 ObChoose({action:"silo_find"})
 SiloUILanResult({token:m.lanToken,generation:7,status:"complete",candidates:[m.candidate]})
 ObChoose(m.choices[0])
 confirm=m.choices[0]
 m.generation=8
 ObChoose(confirm)
 SiloUILanResult({token:m.lanToken,generation:7,ok:true,serverId:m.candidate.serverId})
 print FormatJson({afterBack:afterBack,sent:m.sent,tasks:m.started.Count()})
 ''')
        self.assertEqual('Connect your server',result['afterBack'])
        self.assertEqual([],result['sent'])
        self.assertEqual(2,result['tasks'])

    def test_mismatch_and_unsupported_identity_keep_manual_fallback_without_signin(self):
        for reply in ['{ok:false,errorCode:"network_error"}', '{ok:true,serverId:"other"}']:
            result=self.ui('''
 ObChoose({action:"silo_find"})
 SiloUILanResult({token:m.lanToken,generation:7,status:"complete",candidates:[m.candidate]})
 ObChoose(m.choices[0]):ObChoose(m.choices[0])
 reply='''+reply+'''
 reply.token=m.lanToken:reply.generation=7
 SiloUILanResult(reply)
 print FormatJson({title:m.title,choices:m.choices,sent:m.sent,source:m.sourceId})
 ''')
            self.assertEqual("Couldn't confirm this server",result['title'])
            self.assertIn('silo_address',[c['action'] for c in result['choices']])
            self.assertEqual([],result['sent'])
            self.assertEqual('silo:existing',result['source'])

    def test_candidates_are_bounded_and_names_cannot_inject_ui_control_text(self):
        result=self.ui('''
 ObChoose({action:"silo_find"})
 candidates=[]
 m.candidate.instance="Bad"+Chr(10)+"Name._silo._tcp.local."
 for index=0 to 19
  candidates.Push(m.candidate)
 end for
 SiloUILanResult({token:m.lanToken,generation:7,status:"complete",candidates:candidates})
 print FormatJson({choices:m.choices,sent:m.sent})
 ''')
        choices=[c for c in result['choices'] if c['action']=='silo_lan_select']
        self.assertEqual(16,len(choices))
        self.assertIn('Bad Name',choices[0]['label'])
        self.assertNotIn('\n',choices[0]['label'])
        self.assertEqual([],result['sent'])


    def test_manual_entry_from_results_returns_to_server_choices_when_dismissed(self):
        result=self.ui('''
 ObChoose({action:"silo_find"})
 SiloUILanResult({token:m.lanToken,generation:7,status:"complete",candidates:[m.candidate]})
 ObChoose({action:"silo_address"})
 onObServerClosed()
 print FormatJson({title:m.title,choices:m.choices,sent:m.sent,opened:m.dialogOpened})
 ''')
        self.assertEqual('Connect your server',result['title'])
        self.assertIn('silo_find',[c['action'] for c in result['choices']])
        self.assertTrue(result['opened'])
        self.assertEqual([],result['sent'])
