"""Focus ownership fixtures model the native ancestor-retains-leaf observation.

They verify the requested peer-leaf handoff; native focus/key delivery still
requires TV acceptance.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class SiloUIFocusTests(unittest.TestCase):
    def component(self, name, body, replacements=(), helpers=''):
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT/'components'/name).read_text()
            for function, replacement in replacements:
                source = re.sub(r'(?:sub|function) '+function+r'\(.*?\nend (?:sub|function)', replacement, source, count=1, flags=re.S)
            fixture = Path(root)/'focus.brs'
            fixture.write_text(source+'\n'+helpers)
            return run_brightscript([ROOT/'source/core/SiloUIFormat.brs', ROOT/'components/SiloUIAccessibility.brs', fixture], body, root=Path(root))

    def test_manual_zones_take_peer_leaf_focus_from_native_onboarding_list(self):
        output = self.component('SiloUIScene.brs', '''
            state={owner:"",ancestorCalls:0}
            m.zone="" : m.obButtons=FocusLeaf("obButtons",state)
            m.manualFocus=FocusLeaf("manualFocus",state)
            m.top={state:state,avatar:{},setFocus:sub(on as Boolean)
                m.state.ancestorCalls=m.state.ancestorCalls+1
            end sub,findNode:function(id as String) as Object
                return m.avatar
            end function}
            SetZone("obButtons") : native=state.owner
            SetZone("heroButtons") : hero=state.owner
            SetZone("nav") : nav=state.owner
            SetZone("avatar") : avatar=state.owner
            print FormatJson({native:native,hero:hero,nav:nav,avatar:avatar,ancestorCalls:state.ancestorCalls})
        ''', [
            ('PaintZone','sub PaintZone(name as String,focused as Boolean)\nend sub'),
            ('PaintPills','sub PaintPills(name as String,focused as Boolean)\nend sub'),
        ], '''
function FocusLeaf(name as String,state as Object) as Object
    return {name:name,state:state,setFocus:sub(on as Boolean)
        if on then m.state.owner=m.name
    end sub}
end function
sub HomeSyncTimer()
end sub
''')
        self.assertEqual(json.loads(output), {'native':'obButtons','hero':'manualFocus','nav':'manualFocus','avatar':'manualFocus','ancestorCalls':0})

    def test_manual_focus_owner_is_an_empty_scene_peer(self):
        import xml.etree.ElementTree as ET
        children = ET.parse(ROOT/'components/SiloUIScene.xml').getroot().find('children')
        owner = children.find("Group[@id='manualFocus']")
        self.assertIsNotNone(owner)
        self.assertEqual(len(owner), 0)
        self.assertIn('m.manualFocus = m.top.findNode("manualFocus")', (ROOT/'components/SiloUIScene.brs').read_text())

    def test_hidden_onboarding_selection_cannot_activate_old_choice(self):
        output = self.component('SiloUIOnboarding.brs', '''
            m.calls=[] : m.obButtons={itemSelected:0}
            m.obChoices=[{action:"profile"}] : m.view="home"
            onObSelected()
            hidden=m.calls.Count()
            m.view="onboarding" : onObSelected()
            print FormatJson({hidden:hidden,calls:m.calls})
        ''', [('ObChoose','sub ObChoose(choice as Object)\n m.calls.Push(choice.action)\nend sub')])
        self.assertEqual(json.loads(output), {'hidden':0,'calls':['profile']})

    def test_trace_includes_native_and_manual_owners_without_private_fields(self):
        output = self.component('SiloUIScene.brs', '''
            m.focusTraceRemaining=1 : m.view="home" : m.zone="avatar"
            m.obButtons={hasFocus:function() as Boolean
                return false
            end function,isInFocusChain:function() as Boolean
                return false
            end function,title:"private title"}
            m.manualFocus={hasFocus:function() as Boolean
                return true
            end function,isInFocusChain:function() as Boolean
                return true
            end function,uri:"https://private.example"}
            SiloUIFocusTrace("zoneAfter","avatar")
            SiloUIFocusTrace("zoneAfter","avatar")
        ''')
        self.assertEqual(output.strip(), 'SiloUI focus stage=zoneAfter input=avatar view=home zone=avatar obButtonsFocus=false obButtonsChain=false manualFocusFocus=true manualFocusChain=true')
