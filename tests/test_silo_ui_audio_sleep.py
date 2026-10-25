"""Sleep controls use the current chapter's media boundary."""
import unittest
import test_silo_ui_audio_paused_seek as fixture

class ChapterSleepTests(unittest.TestCase):
 def flow(self, body):
  return fixture.PausedAudioSeekTests().flow('''
   m.audioPositionReady=true:m.audioSequence=0
   m.audioQueue[0].chapters=[{start_seconds:0,end_seconds:60,title:"Opening"},{start_seconds:60,end_seconds:120,title:"Closing"}]
   m.audioOwner={generation:1}:m.audioBook.itemId="book"
   m.audioOptionsToken=7:m.audioOptionChapters=m.audioQueue[0].chapters
   node={id:1,buttonSelected:5,isSameNode:function(other)
    return m.id=other.id
   end function}
   m.top.dialog=node:m.browseDialog=node
   m.browsePaged={handler:"onSiloUIAudioOption",previous:-1,nextPage:-1,count:8,start:0}
   BrowseBindDialog(node,"onSiloUIAudioOption")
   event={node:node,getRoSGNode:function()
    return m.node
   end function}
  '''+body)
 def test_paused_time_does_not_expire_but_playing_crossing_pauses_without_release(self):
  self.assertEqual(self.flow('''
   onSiloUIAudioOption(event)
   onSiloUIAudioTick():before=m.audioNode.control
   m.audioNode.state="playing":m.audioNode.position=61:m.audioNode.control="play"
   onSiloUIAudioTick()
   print FormatJson({before:before,after:m.audioNode.control,retained:m.audioPlan<>invalid,position:m.audioLocalMs})
  '''),dict(before='pause',after='pause',retained=True,position=61000))
 def test_finished_chapter_waits_for_manual_play_before_next_part(self):
  self.assertEqual(self.flow('''
   m.audioQueue[0].chapters[0].end_seconds=120
   m.audioQueue.Push({offsetMs:120000,durationMs:120000})
   onSiloUIAudioOption(event)
   m.audioNode.state="finished":onSiloUIAudioState():onSiloUIAudioState()
   held=m.audioNext=invalid:retained=m.audioPlan<>invalid
   SiloUIAudioKey("play")
   print FormatJson({held:held,retained:retained,nextPart:m.audioNext.index,paused:m.audioPartPaused})
  '''),dict(held=True,retained=True,nextPart=1,paused=False))
 def test_off_seek_and_release_cancel_chapter_sleep(self):
  self.assertEqual(self.flow('''
   onSiloUIAudioOption(event)
   SiloUIAudioSeek(65000)
   seekCancelled=m.audioChapterSleep=invalid
   m.audioLocalMs=36784:m.audioPositionReady=true
   onSiloUIAudioOption(event)
   m.top.dialog=node:m.browseDialog=node:BrowseBindDialog(node,"onSiloUIAudioOption")
   node.buttonSelected=0:onSiloUIAudioOption(event)
   off=m.audioChapterSleep=invalid
   node.buttonSelected=5:m.top.dialog=node:m.browseDialog=node:BrowseBindDialog(node,"onSiloUIAudioOption")
   onSiloUIAudioOption(event)
   m.audioPlan=invalid:SiloUIAudioRelease()
   print FormatJson({seekCancelled:seekCancelled,off:off,released:m.audioChapterSleep=invalid})
  '''),dict(seekCancelled=True,off=True,released=True))
 def test_missing_current_chapter_cannot_arm_timer(self):
  self.assertEqual(self.flow('''
   m.audioLocalMs=120000
   onSiloUIAudioOption(event)
   print FormatJson({armed:m.audioChapterSleep<>invalid})
  '''),dict(armed=False))
 def test_fixed_timer_can_replace_chapter_timer(self):
  self.assertEqual(self.flow('''
   onSiloUIAudioOption(event)
   node.buttonSelected=1:m.top.dialog=node:m.browseDialog=node:BrowseBindDialog(node,"onSiloUIAudioOption")
   onSiloUIAudioOption(event)
   print FormatJson({chapter:m.audioChapterSleep<>invalid,fixed:m.audioSleepMs})
  '''),dict(chapter=False,fixed=900000))

 def test_chapter_pause_reports_resumable_paused_progress(self):
  self.assertEqual(self.flow('''
   onSiloUIAudioOption(event)
   m.audioNode.state="playing":m.audioNode.position=60
   onSiloUIAudioTick()
   print FormatJson({paused:m.lastAudioProgress.isPaused,position:m.lastAudioProgress.positionMs})
  '''),dict(paused=True,position=60000))

 def test_finished_notification_after_boundary_tick_still_holds_next_part(self):
  self.assertEqual(self.flow('''
   m.audioQueue[0].chapters[0].end_seconds=120
   m.audioQueue.Push({offsetMs:120000,durationMs:120000})
   onSiloUIAudioOption(event)
   m.audioNode.state="playing":m.audioNode.position=120:onSiloUIAudioTick()
   m.audioNode.state="finished":onSiloUIAudioState()
   print FormatJson({held:m.audioNext=invalid,retained:m.audioPlan<>invalid})
  '''),dict(held=True,retained=True))
 def test_part_replacement_preserves_fixed_timer_until_explicit_stop(self):
  self.assertEqual(self.flow('''
   node.buttonSelected=1:onSiloUIAudioOption(event)
   m.audioSleepClock={marker:"original deadline"}
   m.audioPlan=invalid
   SiloUIAudioRequestPart(0,60000)
   duration=m.audioSleepMs:clock=m.audioSleepClock.marker
   SiloUIAudioRelease()
   print FormatJson({duration:duration,clock:clock,stopped:m.audioSleepMs})
  '''),dict(duration=900000,clock='original deadline',stopped=0))
