"""Chapter controls use the normalized book queue and existing playback handoff."""
import unittest
import test_silo_ui_audio_paused_seek as fixtures

class AudioChapterTests(unittest.TestCase):
 flow = fixtures.PausedAudioSeekTests.flow
 def test_targets_follow_chapters_and_restart_after_three_seconds(self):
  r=self.flow('''
   q=[{offsetMs:0,durationMs:60000,chapters:[{start_seconds:0},{start_seconds:30}]},{offsetMs:60000,durationMs:60000,chapters:[]}]
   print FormatJson({next:SiloUIAudioChapterTarget(q,0,35000,1),restart:SiloUIAudioChapterTarget(q,0,34000,-1),previous:SiloUIAudioChapterTarget(q,0,33000,-1),part:SiloUIAudioChapterTarget(q,1,2000,-1),end:SiloUIAudioChapterTarget(q,1,5000,1)})
  ''')
  self.assertEqual(r,dict(next=dict(index=1,localMs=0),restart=dict(index=0,localMs=30000),previous=dict(index=0,localMs=0),part=dict(index=0,localMs=30000),end=None))
 def option(self,body,index=7):
  return self.flow('''
   m.audioPositionReady=true:m.audioOptionsToken=7
   m.audioQueue=[{offsetMs:0,durationMs:120000,chapters:[{start_seconds:0},{start_seconds:60}]},{offsetMs:120000,durationMs:60000,chapters:[{start_seconds:0},{start_seconds:30}]}]
   m.audioOptionChapters=m.audioQueue[0].chapters
   node={id:1,buttonSelected:INDEX,isSameNode:function(other)
    return m.id=other.id
   end function}
   m.top.dialog=node:m.browseDialog=node
   m.browsePaged={handler:"onSiloUIAudioOption",previous:-1,nextPage:-1,count:10,start:0}
   BrowseBindDialog(node,"onSiloUIAudioOption")
   event={node:node,getRoSGNode:function()
    return m.node
   end function}
  '''.replace('INDEX',str(index))+body)
 def test_next_chapter_seeks_and_cancels_crossed_sleep_boundary(self):
  self.assertEqual(self.option('''
   m.audioChapterSleep={endMs:60000}
   onSiloUIAudioOption(event)
   print FormatJson({seek:m.audioNode.seek,paused:SiloUIAudioPausedSeekCurrent(),sleep:m.audioChapterSleep<>invalid,ready:m.audioPositionReady})
  '''),dict(seek=60,paused=True,sleep=False,ready=False))
 def test_next_part_preserves_pause_and_fixed_timer_without_rewriting_queue(self):
  self.assertEqual(self.option('''
   m.audioLocalMs=65000:m.audioStarted=false
   m.audioSleepMs=900000:m.audioSleepClock={marker:"deadline"}
   onSiloUIAudioOption(event)
   print FormatJson({index:m.audioIndex,next:m.audioNext,paused:m.audioPartPaused,fixed:m.audioSleepMs,clock:m.audioSleepClock.marker,count:m.audioQueue.Count()})
  '''),dict(index=1,next=dict(index=1,localMs=0),paused=True,fixed=900000,clock='deadline',count=2))
 def test_next_uses_captured_seek_target_instead_of_stale_position(self):
  self.assertEqual(self.option('''
   SiloUIAudioSeek(65000)
   m.audioLocalMs=1000:m.audioStarted=false
   onSiloUIAudioOption(event)
   print FormatJson({next:m.audioNext,paused:m.audioPartPaused})
  '''),dict(next=dict(index=1,localMs=0),paused=True))
 def test_finished_hold_chapter_action_reloads_paused_until_explicit_play(self):
  self.assertEqual(self.option('''
   m.audioNode.state="finished":m.audioChapterFinished=true:m.audioStarted=false
   m.audioLocalMs=120000
   onSiloUIAudioOption(event)
   held=m.audioPartPaused
   SiloUIAudioKey("play")
   print FormatJson({next:m.audioNext,held:held,afterPlay:m.audioPartPaused})
  '''),dict(next=dict(index=1,localMs=0),held=True,afterPlay=False))
 def test_unavailable_or_stale_controls_do_not_seek_or_replace_part(self):
  for setup in ['m.audioIndex=1:m.audioLocalMs=55000', 'm.audioScope="other"', 'm.audioOptionsToken=6', 'm.audioPositionReady=false:m.audioSeekTargetMs=invalid', 'm.view="library"']:
   with self.subTest(setup=setup):
    self.assertEqual(self.option(setup+'''
     onSiloUIAudioOption(event)
     print FormatJson({seek:m.audioNode.seek,next:m.audioNext,control:m.audioNode.control})
    '''),dict(seek=None,next=None,control='pause'))
 def test_previous_chapter_and_missing_metadata_have_bounded_targets(self):
  r=self.flow('''
   q=[{offsetMs:0,durationMs:60000,chapters:[]},{offsetMs:60000,durationMs:60000,chapters:[{start_seconds:10},{start_seconds:30}]}]
   print FormatJson({first:SiloUIAudioChapterTarget(q,0,2000,-1),fallback:SiloUIAudioChapterTarget(q,0,5000,-1),next:SiloUIAudioChapterTarget(q,0,5000,1),previous:SiloUIAudioChapterTarget(q,1,1000,-1),invalidIndex:SiloUIAudioChapterTarget(q,2,0,1),invalidPosition:SiloUIAudioChapterTarget(q,0,65000,1)})
  ''')
  self.assertEqual(r,dict(first=None,fallback=dict(index=0,localMs=0),next=dict(index=1,localMs=0),previous=dict(index=0,localMs=0),invalidIndex=None,invalidPosition=None))
 def test_previous_restarts_finished_part_with_pause_and_progress_scope(self):
  self.assertEqual(self.option('''
   m.audioNode.state="finished":m.audioChapterFinished=true
   m.audioLocalMs=120000:m.audioSequence=0:m.audioOwner={generation:1}
   m.audioBook.itemId="book"
   SiloUIAudioCapturePausedSeek(120000)
   onSiloUIAudioOption(event)
   print FormatJson({next:m.audioNext,paused:m.audioPartPaused,progress:m.lastAudioProgress.positionMs,sync:m.audioSyncFlight.params.positionMs,timeline:SiloUIAudioGlobal(m.audioQueue,m.audioIndex,m.audioLocalMs)})
  ''',6),dict(next=dict(index=0,localMs=60000),paused=True,progress=120000,sync=120000,timeline=60000))
 def test_chapter_order_and_duplicate_starts_do_not_change_nearest_boundary(self):
  r=self.flow('''
   q=[{offsetMs:0,durationMs:120000,chapters:[{start_seconds:60},{start_seconds:30},{start_seconds:30}]}]
   print FormatJson({next:SiloUIAudioChapterTarget(q,0,10000,1),previous:SiloUIAudioChapterTarget(q,0,61000,-1),restart:SiloUIAudioChapterTarget(q,0,65000,-1)})
  ''')
  self.assertEqual(r,dict(next=dict(index=0,localMs=30000),previous=dict(index=0,localMs=30000),restart=dict(index=0,localMs=60000)))
