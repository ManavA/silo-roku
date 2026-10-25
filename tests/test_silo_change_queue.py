"""Run actual request admission through same-session quality/exit races."""
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
HARNESS = '''
function SiloQueueTrace(scenario as String) as Object
    scope={provider:"silo",sourceId:"silo:fixture",profileId:"owner",generation:4}
    state=RqCreate(scope)
    actions=[]
    if scenario="ordered" then actions=["playback_progress","playback_replan","playback_stop"]
    if scenario="priority" then actions=["home","playback_replan"]
    for each action in actions
        job={provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,
            action:action,params:{sessionId:"session-1"}}
        purpose="silo_change_plan"
        cleanup=false
        if action="playback_progress" or action="playback_stop" then purpose="delivery":cleanup=true
        state=RqOffer(state,{job:job,purpose:purpose,cleanup:cleanup}).state
    end for
    trace=[]
    first=RqTake(state):state=first.state
    trace.Push(first.next)
    second=RqTake(state):state=second.state
    trace.Push(second.next)
    if scenario="ordered"
        state=RqComplete(state,first.next.job.requestId)
        third=RqTake(state):state=third.state:trace.Push(third.next)
        fourth=RqTake(state):state=fourth.state:trace.Push(fourth.next)
        if third.next<>invalid then state=RqComplete(state,third.next.job.requestId)
        trace.Push(RqTake(state).next)
    end if
    return {trace:trace,state:state}
end function
'''


class SiloChangeQueueTests(unittest.TestCase):
    def trace(self, scenario):
        with tempfile.TemporaryDirectory(prefix="silo_ui-silo-queue-") as directory:
            harness = Path(directory) / "fixture.brs"
            harness.write_text(HARNESS)
            return run_function([ROOT / "source/core/RequestQueuePolicy.brs", harness],
                                "SiloQueueTrace", [scenario], root=Path(directory))["trace"]

    def test_quality_waits_progress_and_exit_waits_quality_for_same_session(self):
        trace = self.trace("ordered")
        self.assertEqual("playback_progress", trace[0]["job"]["action"])
        self.assertIsNone(trace[1], "quality must wait for the active progress receipt")
        self.assertEqual("playback_replan", trace[2]["job"]["action"])
        self.assertIsNone(trace[3], "Back terminal cannot race an active same-session replan")
        self.assertEqual("playback_stop", trace[4]["job"]["action"])

    def test_quality_has_foreground_priority_without_global_exclusivity(self):
        trace = self.trace("priority")
        self.assertEqual("playback_replan", trace[0]["job"]["action"])
        self.assertEqual(1, trace[0]["priority"])
        self.assertFalse(trace[0]["exclusive"])
        self.assertEqual("home", trace[1]["job"]["action"])


if __name__ == "__main__":
    unittest.main()
