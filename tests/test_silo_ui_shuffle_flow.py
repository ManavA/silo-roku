"""Server picks and mutation results remain owned by one bounded shuffle."""
import json
import re
import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class SiloUIShuffleFlowTests(unittest.TestCase):
 def test_capability_gate_and_stale_result_cannot_replace_server_picks(self):
  with tempfile.TemporaryDirectory() as tmp:
   module=Path(tmp)/'shuffle.brs'
   source=(ROOT/'components/SiloUIShuffle.brs').read_text()
   source=re.sub(r'sub ShuffleDialog\(\).*?\nend sub','sub ShuffleDialog()\nend sub',source,flags=re.S)
   module.write_text(source+'''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action)
    end sub
    sub Toast(message as String)
    end sub
   ''')
   actual=run_brightscript([module,ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs'],'''
    m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="library":m.libraryToken=1:m.browseViewToken=1
    context=BrowseCaptureContext()
    m.calls=[]:m.shuffleEpoch=3:m.shufflePending={kind:"library",scopeId:"l1"}:m.shuffleOwner={generation:1}:m.shuffleBusy=true
    ShuffleResult("shuffle_caps",{ok:true},{allowed:false,kinds:[]},{token:3,ui:context})
    blocked=m.calls.Count()
    ShuffleResult("shuffle_caps",{ok:true},{allowed:true,kinds:["library"]},{token:3,ui:context})
    m.shuffle={shuffleId:"owned",current:{itemId:"a"},next:{itemId:"b"}}
    ShuffleResult("shuffle_skip",{ok:true},{shuffleId:"other",current:{itemId:"c"},next:{itemId:"d"}},{token:2})
    print FormatJson({blocked:blocked,calls:m.calls,pick:m.shuffle.next.itemId})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(blocked=0,calls=['shuffle_start'],pick='b'))

 def test_old_detail_dialog_cannot_mutate_same_view_new_visit(self):
  with tempfile.TemporaryDirectory() as tmp:
   helper=Path(tmp)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action)
    end sub
   ''')
   actual=run_brightscript([ROOT/'components/SiloUIShuffle.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs',helper],'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="detail":m.detailToken=2
    m.shuffleEpoch=3:m.shuffleDialogEpoch=3:m.shuffle={shuffleId:"s1"}
    m.detailToken=1:m.shuffleDialogOwner=BrowseCaptureContext():m.detailToken=2
    m.shuffleDialog={buttonSelected:2,isSameNode:function(node)
      return true
    end function}
    event={getRoSGNode:function()
      return {}
    end function}
    onShuffleChoice(event)
    print FormatJson({calls:m.calls,closed:m.shuffleDialog=invalid})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(calls=[],closed=True))

 def test_late_shuffle_create_after_library_visit_is_stopped_with_captured_owner(self):
  with tempfile.TemporaryDirectory() as tmp:
   helper=Path(tmp)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push({action:action,source:owner.sourceId,id:params.shuffleId})
    end sub
   ''')
   actual=run_brightscript([ROOT/'components/SiloUIShuffle.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs',helper],'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="library":m.libraryToken=2
    m.shuffleEpoch=3:m.shuffleBusy=true
    owner={provider:"silo",sourceId:"silo:synthetic",profileId:"p",generation:1}
    m.libraryToken=1:m.shuffleStartOwner=BrowseCaptureContext():m.libraryToken=2
    retired=ShuffleAllocationResult({purpose:"shuffle_start",generation:1,extra:{token:3},owner:owner},{ok:true,data:{shuffleId:"s1"},sessionRevision:0})
    print FormatJson({retired:retired,calls:m.calls,busy:m.shuffleBusy})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(retired=True,calls=[dict(action='shuffle_stop',source='silo:synthetic',id='s1')],busy=False))

 def test_advance_reply_after_new_detail_visit_keeps_state_without_starting_playback(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=(ROOT/'components/SiloUIShuffle.brs').read_text()
   source=re.sub(r'sub ShufflePlayCurrent\(.*?\nend sub','sub ShufflePlayCurrent(automatic as Boolean)\n m.calls.Push("play")\nend sub',source,count=1,flags=re.S)
   source=re.sub(r'sub ShuffleDialog\(\).*?\nend sub','sub ShuffleDialog()\n m.calls.Push("dialog")\nend sub',source,count=1,flags=re.S)
   fixture=Path(tmp)/'shuffle.brs';fixture.write_text(source+'''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action):m.extra=extra
    end sub
    sub Toast(message as String)
      m.calls.Push("toast")
    end sub
   ''')
   actual=run_brightscript([fixture,ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs'],'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="detail":m.detailToken=1:m.detailItem={itemId:"a"}:m.browseViewToken=2
    m.shuffleEpoch=3:m.shuffleOwner={generation:1}:m.shuffle={shuffleId:"s1",current:{itemId:"a"},next:{itemId:"b"}}
    ShuffleAdvance(false)
    m.detailToken=2:m.detailItem={itemId:"other"}
    ShuffleResult("shuffle_advance",{ok:true},{shuffleId:"s1",current:{itemId:"b"},next:{itemId:"c"}},m.extra)
    print FormatJson({calls:m.calls,current:m.shuffle.current.itemId,busy:m.shuffleBusy})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(calls=['shuffle_advance'],current='b',busy=False))

 def test_skip_reply_after_leaving_view_updates_server_pick_without_opening_dialog(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=(ROOT/'components/SiloUIShuffle.brs').read_text()
   source=re.sub(r'sub ShuffleDialog\(\).*?\nend sub','sub ShuffleDialog()\n m.calls.Push("dialog")\nend sub',source,count=1,flags=re.S)
   fixture=Path(tmp)/'shuffle.brs';fixture.write_text(source+'''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action):m.extra=extra
    end sub
    sub Toast(message as String)
      m.calls.Push("toast")
    end sub
   ''')
   actual=run_brightscript([fixture,ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs'],'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="library":m.libraryToken=1:m.browseViewToken=2
    m.shuffleEpoch=3:m.shuffleDialogEpoch=3:m.shuffleOwner={generation:1}:m.shuffle={shuffleId:"s1",current:{itemId:"a"},next:{itemId:"b"}}
    m.shuffleDialogOwner=BrowseCaptureContext()
    m.shuffleDialog={buttonSelected:2,isSameNode:function(node)
      return true
    end function}
    m.top={dialog:m.shuffleDialog}
    event={getRoSGNode:function()
      return {}
    end function}
    onShuffleChoice(event)
    m.view="search":m.searchToken=5:m.browseViewToken=3
    ShuffleResult("shuffle_skip",{ok:true},{shuffleId:"s1",current:{itemId:"a"},next:{itemId:"c"}},m.extra)
    print FormatJson({calls:m.calls,next:m.shuffle.next.itemId,busy:m.shuffleBusy})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(calls=['shuffle_skip'],next='c',busy=False))

 def test_late_stop_reply_clears_shuffle_without_clearing_new_player_next_item(self):
  with tempfile.TemporaryDirectory() as tmp:
   helper=Path(tmp)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action):m.extra=extra
    end sub
    sub Toast(message as String)
      m.calls.Push("toast")
    end sub
   ''')
   actual=run_brightscript([ROOT/'components/SiloUIShuffle.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'source/core/SiloUIFormat.brs',helper],'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="detail":m.detailToken=1:m.browseViewToken=2
    m.shuffleEpoch=3:m.shuffleOwner={generation:1}:m.shuffle={shuffleId:"s1"}
    ShuffleStop()
    m.view="player":m.playToken=8:m.browseViewToken=3:m.playNext={itemId:"new-sequential"}
    ShuffleResult("shuffle_stop",{ok:true},{stopped:true},m.extra)
    print FormatJson({calls:m.calls,next:m.playNext,cleared:m.shuffle=invalid})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(calls=['shuffle_stop'],next=dict(itemId='new-sequential'),cleared=True))

 def test_manual_title_start_retires_pending_shuffle_before_new_detail_request(self):
  with tempfile.TemporaryDirectory() as tmp:
   helper=Path(tmp)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action)
    end sub
    sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic)
      m.calls.Push(action)
    end sub
    sub Toast(message as String)
    end sub
   ''')
   actual=run_brightscript([ROOT/'components/SiloUIRobustness.brs',ROOT/'components/SiloUIPlayer.brs',ROOT/'components/SiloUIShuffle.brs',ROOT/'components/SiloUIHome.brs',ROOT/'components/SiloUIDiagnostics.brs',ROOT/'source/core/SiloUIFormat.brs',helper],'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="detail":m.playToken=4
    m.shuffleEpoch=3:m.shuffleBusy=true:m.shuffleOwner={generation:1}:m.shuffle={shuffleId:"s1",current:{itemId:"a"}}
    m.pending={}:m.video={}:m.upNextTimer={}:m.playerCue={}
    PlayItem({itemId:"other",title:"Manual title"},0)
    print FormatJson({calls:m.calls,cleared:m.shuffle=invalid,epoch:m.shuffleEpoch})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(calls=['shuffle_stop','detail'],cleared=True,epoch=4))

 def test_manual_start_cancels_pending_shuffle_creation_and_retires_late_allocation(self):
  with tempfile.TemporaryDirectory() as tmp:
   helper=Path(tmp)/'boundary.brs';helper.write_text('''
    sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
      m.calls.Push(action)
    end sub
    sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic)
      m.calls.Push(action)
    end sub
    sub Toast(message as String)
    end sub
   ''')
   files=[ROOT/p for p in ['components/SiloUIRobustness.brs','components/SiloUIPlayer.brs','components/SiloUIShuffle.brs','components/SiloUIHome.brs','components/SiloUIDiagnostics.brs','components/SiloUIDialogs.brs','source/core/SiloUIFormat.brs']]+[helper]
   actual=run_brightscript(files,'''
    m.calls=[]:m.provider="silo":m.sourceId="silo:synthetic":m.profileId="p":m.generation=1:m.view="detail":m.playToken=4:m.detailToken=1:m.detailItem={itemId:"a"}:m.browseViewToken=2
    m.shuffleEpoch=3:m.shuffleBusy=true:m.shuffleOwner={provider:"silo",sourceId:"silo:synthetic",profileId:"p",generation:1}
    m.shuffleStartOwner=BrowseCaptureContext()
    m.pending={}:m.video={}:m.upNextTimer={}:m.playerCue={}
    PlayItem({itemId:"other",title:"Manual title"},0)
    retired=ShuffleAllocationResult({purpose:"shuffle_start",generation:1,extra:{token:3},owner:m.shuffleOwner},{ok:true,data:{shuffleId:"late"},sessionRevision:0})
    print FormatJson({calls:m.calls,retired:retired,busy:m.shuffleBusy,epoch:m.shuffleEpoch,loading:m.playLoading})
   ''',root=Path(tmp))
  self.assertEqual(json.loads(actual),dict(calls=['detail','shuffle_stop'],retired=True,busy=False,epoch=4,loading=True))
