import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloUISignInPolicy.brs'
class SignInTests(unittest.TestCase):
    def call(self,name,*args):
        with tempfile.TemporaryDirectory() as d:
            return run_function(POLICY,name,list(args),root=Path(d))
    def test_recent_servers_are_deduplicated_bounded_and_contain_only_safe_addresses(self):
        saved=['https://a.example','https://b.example','https://c.example','https://d.example','https://e.example']
        self.assertEqual(self.call('SiloUISavedServers',saved,'https://b.example/'),['https://b.example','https://a.example','https://c.example','https://d.example','https://e.example'])
        for address in ['https://user:pass@host','https://host/?token=x','https://host/#secret','file:///tmp/x','https://host/path','https://host/secret-token','https://host\n']:
            self.assertEqual(self.call('SiloUISavedServerAddress',address),'',address)
        self.assertEqual(len(self.call('SiloUISavedServers',saved,'https://new.example')),5)
    def test_local_qr_decodes_verified_uri_and_rejects_credentials_or_unbounded_payloads(self):
        if not shutil.which('zbarimg'):
            self.skipTest('zbarimg required for independent QR decode')
        from PIL import Image
        uri='https://silo.example/activate'
        matrix=self.call('SiloUISignInQr',uri)
        self.assertEqual(len(matrix),37)
        with tempfile.TemporaryDirectory() as d:
            image=Image.new('L',(45*8,45*8),255)
            for y,row in enumerate(matrix):
                for x,value in enumerate(row):
                    if value: image.paste(0,((x+4)*8,(y+4)*8,(x+5)*8,(y+5)*8))
            p=Path(d)/'qr.png';image.save(p)
            result=subprocess.run(['zbarimg','--quiet','--raw',str(p)],capture_output=True,text=True)
        self.assertEqual(result.stdout.strip(),uri,result.stderr)
        for bad in ['https://user:pass@host/activate','https://host/activate?token=secret','javascript:evil','https://host/'+('x'*110)]:
            self.assertEqual(self.call('SiloUISignInQr',bad),[])
    def test_qr_opens_specific_approval_without_entering_a_code(self):
        if not shutil.which('zbarimg'):
            self.skipTest('zbarimg required for independent QR decode')
        from PIL import Image
        base='https://silo.example/activate'
        expected=base+'?code=ABCD1234'
        for complete in (expected,base+'?token=synthetic-legacy-token'):
            with self.subTest(complete=complete):
                uri=self.call('SiloUISignInApprovalUri',base,'ABCD-1234',complete)
                self.assertEqual(uri,expected)
                matrix=self.call('SiloUISignInQr',uri)
                self.assertEqual(len(matrix),37)
                with tempfile.TemporaryDirectory() as d:
                    image=Image.new('L',(45*8,45*8),255)
                    for y,row in enumerate(matrix):
                        for x,value in enumerate(row):
                            if value:image.paste(0,((x+4)*8,(y+4)*8,(x+5)*8,(y+5)*8))
                    p=Path(d)/'qr.png';image.save(p)
                    result=subprocess.run(['zbarimg','--quiet','--raw',str(p)],capture_output=True,text=True)
                self.assertEqual(result.stdout.strip(),expected,result.stderr)
        self.assertEqual(self.call('SiloUISignInApprovalUri',base,'',''),base)
        self.assertEqual(self.call('SiloUISignInQr',base+'?other=ABCD1234'),[])
        self.assertEqual(self.call('SiloUISignInQr','https://silo.example/other?code=ABCD1234'),[])
    def test_device_start_shows_phone_approval_link_in_qr(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.body=c:m.code=d\nend sub',source,count=1,flags=re.S)
            source=re.sub(r'sub ObSchedulePoll\(\).*?\nend sub','sub ObSchedulePoll()\n m.scheduled=true\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
function TextOr(value as Dynamic) as String
 if type(value)="String" then return value
 return ""
end function
function NumberOr(value as Dynamic, fallback as Double) as Double
 if type(value)="Integer" then return value
 return fallback
end function
sub SiloUISignInShowQr(uri as String)
 m.qr=uri
end sub
''')
            output=run_brightscript([POLICY,p,stub],'''
                m.obQr={}:m.obMode="silo"
                OnboardingResult("ob_device_start",{ok:true},{verificationUri:"https://silo.example/activate",verificationUriComplete:"https://silo.example/activate?code=ABCD1234",userCode:"ABCD-1234",intervalMs:3000},invalid)
                print FormatJson({qr:m.qr,body:m.body,code:m.code,scheduled:m.scheduled})
            ''',root=Path(d))
        result=json.loads(output)
        self.assertEqual(result['qr'],'https://silo.example/activate?code=ABCD1234')
        self.assertEqual(result['code'],'ABCD-1234')
        self.assertTrue(result['scheduled'])
        self.assertIn('app',result['body'].lower())
        self.assertIn('https://silo.example/activate',result['body'])
    def test_shipping_qr_result_rejects_replaced_code_and_closed_screen(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUISignIn.brs').read_text()
            source=re.sub(r'sub SiloUISignInPaintQr\(.*?\nend sub','sub SiloUISignInPaintQr(matrix as Object)\n m.paints=m.paints+1\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'signin.brs';p.write_text(source)
            output=run_brightscript([p],'''
                m.paints=0:m.obQrGeneration=2:m.view="onboarding":m.obMode="silo"
                SiloUISignInQrResult({generation:1,matrix:[[1]]})
                m.view="home"
                SiloUISignInQrResult({generation:2,matrix:[[1]]})
                m.view="onboarding"
                SiloUISignInQrResult({generation:2,matrix:[[1]]})
                print FormatJson(m.paints)
            ''',root=Path(d))
        self.assertEqual(json.loads(output),1)
    def test_shipping_scene_includes_local_task_and_qr_surface(self):
        import xml.etree.ElementTree as ET
        scene=ET.parse(ROOT/'components/SiloUIScene.xml').getroot()
        scripts=[x.attrib['uri'] for x in scene.findall('script')]
        self.assertIn('pkg:/source/core/SiloUISignInPolicy.brs',scripts)
        self.assertIn('pkg:/components/SiloUISignIn.brs',scripts)
        self.assertIsNotNone(scene.find('.//Group[@id="obQr"]'))
        task=ET.parse(ROOT/'components/SiloUIQrTask.xml').getroot()
        self.assertEqual(task.attrib['extends'],'Task')
    def test_qr_keeps_overflow_hint_for_three_approval_actions(self):
        source=(ROOT/'components/SiloUISignIn.brs').read_text()
        paint=source.split('sub SiloUISignInPaintQr(matrix as Object)',1)[1].split('end sub',1)[0]
        self.assertIn('m.obChoices.Count() > m.obButtons.numRows',paint)
    def test_saved_server_choice_requests_only_its_address(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.choices=choices\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent={action:action,params:params,provider:provider}
end sub
''')
            output=run_brightscript([POLICY,ROOT/'components/SiloUISignIn.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
                m.savedServers=["https://one.example","https://two.example"]
                m.pollTimer={control:"stop"}
                m.sourceId="silo:old":m.profileId="old-profile"
                ObStartSilo()
                ObChoose(m.choices[1])
                print FormatJson({sent:m.sent,source:m.sourceId,profile:m.profileId})
            ''',root=Path(d))
        result=json.loads(output)
        self.assertEqual(result,{'sent':{'action':'set_server','params':{'baseUrl':'https://two.example'},'provider':'silo'},'source':'','profile':''})
    def test_saved_server_is_confirmed_before_phone_approval_without_address_entry(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.screen=b:m.choices=choices\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent={action:action,params:params,purpose:purpose,provider:provider}
end sub
''')
            output=run_brightscript([POLICY,ROOT/'components/SiloUISignIn.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
                m.savedServers=["https://one.example"]:m.pollTimer={control:"stop"}
                ObStartSilo()
                requestedBefore=m.sent<>invalid
                if not requestedBefore then ObChoose(m.choices[0])
                print FormatJson({requestedBefore:requestedBefore,sent:m.sent,mode:m.obMode})
            ''',root=Path(d))
        self.assertEqual(json.loads(output),{'requestedBefore':False,'sent':{'action':'set_server','params':{'baseUrl':'https://one.example'},'purpose':'ob_server','provider':'silo'},'mode':'silo'})

    def test_first_silo_signin_requests_own_server_without_network(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.screen=b:m.choices=choices\nend sub',source,count=1,flags=re.S)
            source=re.sub(r'sub ObServerAddressDialog\(.*?\nend sub','sub ObServerAddressDialog()\n m.keyboardOpened=true\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent={action:action,params:params,purpose:purpose,provider:provider}
end sub
''')
            output=run_brightscript([POLICY,ROOT/'components/SiloUISignIn.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
                m.savedServers=[]:m.pollTimer={control:"stop"}:m.keyboardOpened=false
                ObStartSilo()
                actions=[]:for each choice in m.choices:actions.Push(choice.action):end for
                started={sent:m.sent,mode:m.obMode,keyboardOpened:m.keyboardOpened,actions:actions}
                print FormatJson(started)
            ''',root=Path(d))
        self.assertEqual(json.loads(output),{'sent':None,'mode':'','keyboardOpened':True,'actions':['silo_address','sources']})

    def test_retry_keeps_manually_entered_server_before_it_is_saved(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.choices=choices\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent={action:action,params:params}
end sub
''')
            output=run_brightscript([POLICY,ROOT/'components/SiloUISignIn.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
                m.savedServers=[]:m.pollTimer={control:"stop"}
                ObConnectSilo("https://own.example")
                ObError("Couldn't reach the Silo server.")
                ObChoose({action:"retry"})
                print FormatJson(m.sent)
            ''',root=Path(d))
        self.assertEqual(json.loads(output),{'action':'set_server','params':{'baseUrl':'https://own.example'}})

    def test_existing_silo_session_without_address_history_keeps_its_server(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.choices=choices\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent={action:action,params:params}
end sub
''')
            output=run_brightscript([POLICY,ROOT/'components/SiloUISignIn.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
                m.savedServers=[]:m.pollTimer={control:"stop"}
                m.obStatus={silo:{sourceId:"silo:https://own.example",connected:false}}
                ObStartSilo()
                requestedBefore=m.sent<>invalid
                if not requestedBefore then ObChoose(m.choices[0])
                print FormatJson({requestedBefore:requestedBefore,sent:m.sent})
            ''',root=Path(d))
        self.assertEqual(json.loads(output),{'requestedBefore':False,'sent':{'action':'set_server','params':{'baseUrl':'https://own.example'}}})

    def test_failed_saved_server_can_be_changed(self):
        from tools.brightscript import run_brightscript
        import re
        with tempfile.TemporaryDirectory() as d:
            source=(ROOT/'components/SiloUIOnboarding.brs').read_text()
            source=re.sub(r'sub ObScreen\(.*?\nend sub','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.choices=choices\nend sub',source,count=1,flags=re.S)
            p=Path(d)/'onboarding.brs';p.write_text(source)
            stub=Path(d)/'stub.brs';stub.write_text('''
sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
 m.sent={action:action,params:params}
end sub
''')
            output=run_brightscript([POLICY,ROOT/'components/SiloUISignIn.brs',ROOT/'source/core/SiloUIFormat.brs',p,stub],'''
                m.savedServers=["https://old.example"]:m.pollTimer={control:"stop"}
                ObStartSilo()
                ObChoose(m.choices[0])
                ObError("Couldn't reach the Silo server.")
                actions=[]:for each choice in m.choices:actions.Push(choice.action):end for
                print FormatJson(actions)
            ''',root=Path(d))
        self.assertIn('silo_servers',json.loads(output))
