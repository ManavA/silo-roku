"""Artwork cannot outrank cleanup, explicit playback or previews."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
C=Path(__file__).resolve().parents[1]
BRIDGE='''
function ArtworkQueueOrder() as Object
 scope={provider:"plex",sourceId:"plex:synthetic",profileId:"",generation:7}
 state=RqCreate(scope)
 jobs=[{action:"metadata_artwork",purpose:"public_artwork"},{action:"detail",purpose:"preview_detail"},{action:"playback_start",purpose:"playback"},{action:"playback_stop",purpose:"delivery"}]
 for each entry in jobs
  job={provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:7,action:entry.action,params:{}}
  offered=RqOffer(state,{job:job,purpose:entry.purpose})
  state=offered.state
 end for
 order=[]
 for i=0 to 3
  taken=RqTake(state)
  state=taken.state
  order.Push(taken.next.job.action)
  if i<2
   if i=1
    third=RqTake(state)
    if third.next<>invalid then return {thirdTask:true}
   end if
  else
   state=RqComplete(state,taken.next.job.requestId)
  end if
  if i=1
   for each active in state.active
    state=RqComplete(state,active.job.requestId)
   end for
  end if
 end for
 return {order:order,thirdTask:false}
end function
'''
class ArtworkQueueTests(unittest.TestCase):
 def test_public_optional_read_remains_below_terminal_play_preview_and_two_workers(self):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d)/'fixture.brs';b.write_text(BRIDGE)
   x=run_function(C/'source/core/RequestQueuePolicy.brs','RqCreate',[{}],root=Path(d))
   x=run_function([C/'source/core/RequestQueuePolicy.brs',b],'ArtworkQueueOrder',[],root=Path(d))
  self.assertEqual(['playback_stop','playback_start','detail','metadata_artwork'],x['order']);self.assertFalse(x['thirdTask'])
