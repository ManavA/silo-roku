"""Safe playback failure enums survive the Task boundary and lease cleanup."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import test_silo_replan_task as replan

SILO = ROOT / 'source/adapters/SiloAdapter.brs'
TASK = ROOT / 'components/ApiTask.brs'


def terminal(reason='audio_conversion_unsupported'):
    return {'protocol_version': 3, 'outcome': 'terminal', 'terminal': {
        'reason': reason, 'message': 'private-token https://private.example',
        'headers': {'Authorization': 'private-token'}, 'retryable': True}}


class SiloPlaybackFailureTests(unittest.TestCase):
    def details(self, code, decision, stage='start'):
        self.assertIn('function SiloPlaybackFailureDetails(', SILO.read_text())
        return run_function(SILO, 'SiloPlaybackFailureDetails', [
            {'ok': False, 'errorCode': code, 'message': 'private-token'}, decision, stage])

    def test_terminal_reason_is_compact_and_known_audio_failure_is_retained(self):
        self.assertEqual({'ok': False, 'errorCode': 'playback_terminal',
                          'reason': 'audio_conversion_unsupported', 'stage': 'start'},
                         self.details('playback_terminal', terminal()))

    def test_unknown_reason_and_stage_cannot_escape(self):
        value = self.details('playback_terminal', terminal('https://private.example/token'), 'private-token')
        self.assertEqual({'ok': False, 'errorCode': 'playback_terminal'}, value)
        value = self.details('unsupported_stream', terminal())
        self.assertEqual({'ok': False, 'errorCode': 'unsupported_stream', 'stage': 'start'}, value)

    def test_protocol_and_format_errors_keep_legacy_code_and_safe_stage(self):
        for code in ('unsupported_protocol', 'unsupported_playback_protocol', 'unsupported_stream'):
            self.assertEqual({'ok': False, 'errorCode': code, 'stage': 'replan'},
                             self.details(code, {}, 'replan'))

    def test_adapter_exposes_server_audio_terminal_enum(self):
        value = run_function(SILO, 'SiloPlaybackPlan', [terminal(), {}])
        self.assertEqual('audio_conversion_unsupported', value.get('reason'))
        self.assertNotIn('private-token', json.dumps(value))

    def test_cleanup_success_failure_and_exception_preserve_bounded_reason(self):
        text = TASK.read_text()
        function = 'function TaskRejectSiloPlayback(' + text.split('function TaskRejectSiloPlayback(', 1)[1].split('end function', 1)[0] + 'end function\n'
        boundary = '''
function TaskError(code as String) as Object
 return {ok:false,errorCode:code}
end function
function MergeSessionPatch(base as Object, patch as Object) as Object
 return patch
end function
function TaskPlaybackEvent(provider, session, action, params, revision) as Object
 m.stopped = action = "playback_stop" and params.sessionId = "session-1"
 if m.mode = "throw" then throw "synthetic cleanup failure"
 return {ok:m.mode = "success"}
end function
function CheckFailure(decision as Object, mode as String) as Object
 m.mode=mode:m.stopped=false
 cleanup={sessionId:"session-1",installationId:"install-1",stopId:"stop-1",persistProgress:false}
 outcome=TaskRejectSiloPlayback({},cleanup,"playback_terminal",0,decision)
 return {outcome:outcome,stopped:m.stopped}
end function
'''
        self.assertIn('decision = invalid as Dynamic', function)
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / 'worker.brs'
            worker.write_text(function + boundary)
            for mode in ('success', 'failure', 'throw'):
                value = run_function([SILO, worker], 'CheckFailure', [terminal(), mode])
                self.assertTrue(value['stopped'])
                outcome = value['outcome']
                self.assertEqual('playback_terminal', outcome['errorCode'])
                self.assertEqual('audio_conversion_unsupported', outcome.get('reason'))
                self.assertEqual('start', outcome.get('stage'))
                self.assertEqual(mode != 'success', 'plan' in outcome)
                self.assertNotIn('private-token', json.dumps(value))

    def test_replan_public_failure_preserves_reason_and_lease_uncertainty(self):
        value = replan.SiloReplanTaskTests().call(decision=terminal())['outcome']
        self.assertEqual('playback_terminal', value['errorCode'])
        self.assertEqual('audio_conversion_unsupported', value.get('reason'))
        self.assertEqual('replan', value.get('stage'))
        self.assertTrue(value['leaseUncertain'])
        self.assertEqual({'installationId':'install-0001','playbackAttemptId':'playback-attempt-0001','sessionId':'session-0001'}, value.get('report'))
        self.assertNotIn('private-token', json.dumps(value))


if __name__ == '__main__':
    unittest.main()
