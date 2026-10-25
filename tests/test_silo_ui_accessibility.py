"""Manual focus speech uses committed focus, never paint callbacks."""
import json
import re
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class AccessibilityTests(unittest.TestCase):
    def flow(self, action):
        source = (ROOT / 'components/SiloUIScene.brs').read_text()
        zone = re.search(r'sub SetZone\(.*?\nend sub', source, re.S)[0]
        navigation = (ROOT / 'components/SiloUINavigation.brs').read_text()
        drawer = re.search(r'function SiloUINavigationKey\(.*?\nend function', navigation, re.S)[0]
        move = re.search(r'function PillMove\(.*?\nend function', source, re.S)[0]
        with tempfile.TemporaryDirectory() as tmp:
            seam = Path(tmp) / 'focus.brs'
            seam.write_text(move + '\n' + zone + '\n' + drawer + '''
sub PaintZone(name as String, focused as Boolean)
end sub
sub HomeSyncTimer()
end sub
sub SiloUIFocusTrace(action as String, zone as String)
end sub
sub SiloUINavigationSync()
end sub

sub PaintPills(name as String, focused as Boolean)
end sub
''')
            output = run_brightscript([ROOT / 'components/SiloUIAccessibility.brs', ROOT / 'source/core/SiloUINavigationPolicy.brs', seam], '''
    m.calls=[]
    m.audioGuide={calls:m.calls,Say:function(text, flushSpeech, dontRepeat)
        m.calls.Push({text:text,flush:flushSpeech,repeat:dontRepeat})
        return true
    end function}
    m.top={appFocused:true,dialog:invalid,findNode:function(id)
        return m.node
    end function}
    m.manualFocus={focused:true,setFocus:sub(value)
        m.focused=value
    end sub,hasFocus:function()
        return m.focused
    end function}
    m.focused=true:m.view="home":m.zone="heroButtons":m.navigationMode="top"
    parent={visible:true,opacity:1,getParent:function()
        return invalid
    end function}
    m.label={parent:parent,text:"Play",visible:true,opacity:1,getParent:function()
        return m.parent
    end function}
    m.parent=parent:m.top.node=m.label
    second={parent:parent,text:"Details",visible:true,opacity:1,getParent:function()
        return m.parent
    end function}
    m.pillGroups={heroButtons:{index:0,pills:[{label:m.label},{label:second}]}}
''' + action + '''
    print FormatJson(m.calls)
''', root=Path(tmp))
            return json.loads(output)

    def test_committed_move_speaks_once_and_edge_does_not_repeat(self):
        calls = self.flow('''
    SiloUIAccessibilityFocused()
    PillMove("heroButtons",1)
    PillMove("heroButtons",1)
    SiloUIAccessibilityFocused()
''')
        self.assertEqual([c['text'] for c in calls], ['Play, button, 1 of 2', 'Details, button, 2 of 2'])
        self.assertTrue(all(c['flush'] and not c['repeat'] for c in calls))

    def test_native_modal_hidden_background_and_stale_focus_are_silent(self):
        for change in ['m.zone="rows"', 'm.top.dialog={}', 'm.parent.visible=false',
                       'm.parent.opacity=0', 'm.top.appFocused=false',
                       'm.manualFocus.focused=false', 'm.view="detail"',
                       'm.pillGroups.heroButtons.index=9', 'm.audioGuide=invalid']:
            with self.subTest(change=change):
                self.assertEqual(self.flow(change + '\n SiloUIAccessibilityFocused()'), [])

    def test_return_from_native_focus_announces_again(self):
        calls = self.flow('''
    SiloUIAccessibilityFocused()
    m.zone="rows":SiloUIAccessibilityFocused()
    m.zone="heroButtons":SiloUIAccessibilityFocused()
''')
        self.assertEqual(len(calls), 2)

    def test_repaint_and_unowned_move_do_not_speak(self):
        self.assertEqual(self.flow('''
    PaintPills("heroButtons",true)
    m.zone="rows"
    PillMove("heroButtons",1)
'''), [])

    def test_labels_are_bounded_and_link_labels_are_silent(self):
        calls = self.flow('m.label.text=String(200,"x"):SiloUIAccessibilityFocused()')
        self.assertEqual(calls[0]['text'], 'x' * 120 + ', button, 1 of 2')
        for label in ['https://private.example/pin', 'user@example.test']:
            self.assertEqual(self.flow(f'm.label.text="{label}":SiloUIAccessibilityFocused()'), [])

    def test_zone_handoff_and_drawer_commit_use_the_same_speech_boundary(self):
        calls = self.flow('''
    SetZone("heroButtons")
    SetZone("heroButtons")
    m.pillGroups.drawer=m.pillGroups.heroButtons
    m.zone="drawer":m.drawerOpen=true:m.drawerIndex=0
    SiloUIAccessibilityFocused()
    SiloUINavigationKey("down")
    SiloUINavigationKey("down")
''')
        self.assertEqual([c['text'] for c in calls], [
            'Play, button, 1 of 2', 'Play, button, 1 of 2', 'Details, button, 2 of 2'])

    def test_profile_controls_never_speak_account_name(self):
        calls = self.flow('''
    m.zone="avatar":m.label.text="Secret account"
    SiloUIAccessibilityFocused()
    m.navigationMode="left":m.zone="nav":SiloUIAccessibilityFocused()
    m.zone="drawer":m.drawerOpen=true:m.drawerIndex=-1:SiloUIAccessibilityFocused()
''')
        self.assertEqual([c['text'] for c in calls], ['Profile menu, button'] * 3)

    def test_owner_changes_allow_reentry_without_speaking_during_the_change(self):
        calls = self.flow('''
    SiloUIAccessibilityFocused()
    m.top.appFocused=false:onSiloUIAccessibilityOwnerChanged()
    SiloUIAccessibilityFocused()
    m.top.appFocused=true:onSiloUIAccessibilityOwnerChanged()
    SetZone("heroButtons")
    m.top.dialog={}:onSiloUIAccessibilityOwnerChanged()
    SiloUIAccessibilityFocused()
    m.top.dialog=invalid:onSiloUIAccessibilityOwnerChanged()
    SetZone("heroButtons")
''')
        self.assertEqual([c['text'] for c in calls], ['Play, button, 1 of 2'] * 3)

    def test_zero_delta_does_not_create_a_focus_announcement(self):
        self.assertEqual(self.flow('PillMove("heroButtons",0)'), [])
