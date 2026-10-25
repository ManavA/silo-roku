"""Native callback completion requires a first playing observation per load."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_brightscript

ROOT = Path(__file__).resolve().parents[1]


class SiloUINativeEarlyFinish(unittest.TestCase):
    def scene(self, code):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT / 'components/SiloUIPlayer.brs').read_text()
            names = ['PlayerClose', 'PlayerRecoverNativeFailure', 'PlayerFailureResult',
                     'PlayerShowFailure', 'PlayerAutoAdvance', 'PlayerLoadMarkers',
                     'PlayerOriginalObserve', 'PlayerPlaybackFocus', 'onPlayerTracks',
                     'PlayerUpdateNativeActions', 'PlayerCurrentCue']
            for name in names:
                source = re.sub(r'(?im)^(sub|function) ' + name + r'\(',
                                r'\1 Unused' + name + '(', source, count=1)
            player = root / 'player.brs'
            player.write_text(source)
            boundary = root / 'boundary.brs'
            boundary.write_text('''function PlayerRecoverNativeFailure(reason as String) as Boolean
 m.reasons.Push(reason)
 if m.canRecover then m.recoveringNative=true
 return m.canRecover
end function
sub PlayerClose(finished as Boolean)
 m.closes.Push(finished)
end sub
function PlayerFailureResult(result as Object, plan as Dynamic) as Object
 return {}
end function
sub PlayerShowFailure(stage as String, result as Object)
 m.failures.Push(stage)
end sub
sub PlayerAutoAdvance()
 m.advances += 1
end sub
sub PlayerLoadMarkers()
end sub
sub PlayerOriginalObserve()
 m.originalObservations += 1
end sub
function SiloUIPlayerNext(item as Object, episodes as Dynamic) as Dynamic
 return invalid
end function
sub PlayerPlaybackFocus()
end sub
sub onPlayerTracks()
end sub
function PlayerCurrentCue() as Dynamic
 return invalid
end function
sub PlayerUpdateNativeActions(cue as Dynamic)
end sub
''')
            setup = '''m.view="player":m.playPlan={durationMs:1000}:m.video={state:"finished",position:1,duration:1}
 m.canRecover=true:m.reasons=[]:m.closes=[]:m.failures=[]:m.advances=0
 m.originalObservations=0
'''
            output = run_brightscript([ROOT/'components/SiloUIRobustness.brs',ROOT/'components/SiloUISubtitleArtifact.brs', ROOT/'source/core/SiloUIFormat.brs',
                                      ROOT/'source/core/SiloUISettingsPolicy.brs', ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'components/SiloUICompatPlayback.brs', player, boundary],
                                     setup + code, root=root)
            return json.loads(output.strip().splitlines()[-1])

    def test_early_finish_recovers_once_without_completion_even_with_up_next(self):
        result = self.scene('''m.playNext={}:m.upNextActive=true:m.upNextDismissed=false
 onVideoState()
 onVideoState()
 print FormatJson({reasons:m.reasons,closes:m.closes,advances:m.advances})''')
        self.assertEqual({'reasons':['decoder_failure'], 'closes':[], 'advances':0}, result)

    def test_exhausted_early_finish_closes_unfinished_and_shows_native_failure(self):
        result = self.scene('''m.canRecover=false
 onVideoState()
 print FormatJson({reasons:m.reasons,closes:m.closes,failures:m.failures})''')
        self.assertEqual({'reasons':['decoder_failure'], 'closes':[False], 'failures':['native']}, result)

    def test_first_playing_allows_short_completion_and_survives_buffering(self):
        result = self.scene('''m.video.state="playing":onVideoState()
 m.video.state="buffering":onVideoState()
 m.video.state="finished":onVideoState()
 m.playNext={}:m.upNextActive=true:m.upNextDismissed=false
 onVideoState()
 print FormatJson({reasons:m.reasons,closes:m.closes,advances:m.advances})''')
        self.assertEqual({'reasons':[], 'closes':[True], 'advances':1}, result)

    def test_stale_cancelled_or_ownerless_finish_does_nothing(self):
        result = self.scene('''m.view="detail":onVideoState()
 m.view="player":m.transitionIntent={}:onVideoState()
 m.transitionIntent=invalid:m.playPlan=invalid:onVideoState()
 print FormatJson({reasons:m.reasons,closes:m.closes,advances:m.advances})''')
        self.assertEqual({'reasons':[], 'closes':[], 'advances':0}, result)

    def test_guarded_original_still_owns_preplaying_finish(self):
        result = self.scene('''m.originalPlayback={phase:"awaiting_tracks"}
 onVideoState()
 print FormatJson({observed:m.originalObservations,reasons:m.reasons,closes:m.closes})''')
        self.assertEqual({'observed':1, 'reasons':[], 'closes':[]}, result)

    def test_verified_original_completion_keeps_its_reducer_verdict(self):
        result = self.scene('''m.originalPlayback={phase:"verified_playing"}:m.nativeSeenPlaying=true
 onVideoState()
 print FormatJson({observed:m.originalObservations,reasons:m.reasons,closes:m.closes})''')
        self.assertEqual({'observed':1, 'reasons':[], 'closes':[True]}, result)

    def test_fresh_player_start_resets_previous_playing_observation(self):
        result = self.scene('''m.video.state="playing":onVideoState()
 m.top={findNode:function(name)
 return {}
 end function}
 m.nav={}:m.playItem={}:m.toast={}:m.progressTimer={}
 PlayerStart({},true)
 m.video.state="finished":onVideoState()
 print FormatJson({reasons:m.reasons,closes:m.closes})''')
        self.assertEqual({'reasons':['decoder_failure'], 'closes':[]}, result)


if __name__ == '__main__':
    unittest.main()
