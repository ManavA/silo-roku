"""The shipping source entry remains Silo-only while Plex is deferred."""
import unittest
from tests import test_silo_ui_plex_policy

class SiloUISiloEntryTests(unittest.TestCase):
    def scene(self, script, replacements=()):
        return test_silo_ui_plex_policy.SiloUIPlexPolicyTests().scene('SiloUIOnboarding.brs', script, replacements)

    def test_boot_only_checks_silo(self):
        actual=self.scene('m.calls=[]:Boot():print FormatJson(m.calls)',[
            ('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.calls.Push({action:action,provider:provider})\nend sub')])
        self.assertEqual(actual,[dict(action='session_status',provider='silo')])

    def test_silo_status_restores_without_waiting_for_plex_and_ignores_old_plex(self):
        actual=self.scene('''
            m.calls=[]:m.obStatus={}
            OnboardingResult("ob_status",{ok:true},{connected:true},"plex")
            OnboardingResult("ob_status",{ok:true},{connected:true},"silo")
            OnboardingResult("ob_source_status",{ok:true},{connected:true},"plex")
            print FormatJson(m.calls)
        ''',[('EnterSource','sub EnterSource(provider as String,status as Object)\n m.calls.Push(provider)\nend sub')])
        self.assertEqual(actual,['silo'])

    def test_source_picker_only_offers_silo_and_ignores_stale_plex_choice(self):
        actual=self.scene('''
            m.pollTimer={}:m.calls=[]
            ObChooseSource()
            ObChoose({action:"plex"})
            print FormatJson({choices:m.choices,eyebrow:m.eyebrow,calls:m.calls})
        ''',[
            ('ObResetScope','sub ObResetScope()\nend sub'),
            ('ObScreen','sub ObScreen(a as String,b as String,c as String,d as String,choices as Object)\n m.choices=choices:m.eyebrow=a\nend sub'),
            ('Api','sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)\n m.calls.Push(action)\nend sub')])
        self.assertEqual(actual,dict(choices=[dict(label='Silo',action='silo')],eyebrow='Welcome',calls=[]))

    def test_enter_source_rejects_plex_before_mutating_app_state(self):
        actual=self.scene('''
            m.provider="silo":m.generation=7
            EnterSource("plex",{connected:true})
            print FormatJson({provider:m.provider,generation:m.generation})
        ''')
        self.assertEqual(actual,dict(provider='silo',generation=7))
