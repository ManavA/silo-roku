"""Retained finished-frame Up Next policies; native popup coordinator retired."""
from pathlib import Path
import tempfile
import unittest
from tests import test_up_next_policy as policy
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]

def low_policy():
    return [policy.native(980),policy.neighbors(),policy.neighbors(previous=True),policy.markers(),
            policy.native(981),policy.event("watching_result",probability=.2)]


POLICY_BATCH='''
function FinishedPolicyBatch(cases as Object) as Object
    result=[]
    for each fixtureCase in cases
        state=UpNextCreate(fixtureCase.config)
        trace=[]
        for each inputEvent in fixtureCase.events
            decision=UpNextReduce(state,inputEvent)
            state=decision.state
            decision["projection"]=UpNextProjection(state)
            trace.Push(decision)
        end for
        result.Push(trace)
    end for
    return result
end function
'''


class StillWatchingFinishedTests(unittest.TestCase):
    def pure(self,cases):
        with tempfile.TemporaryDirectory(prefix="silo-finished-policy-") as directory:
            temporary=Path(directory)
            boundary=temporary/"boundary.brs"
            boundary.write_text(POLICY_BATCH)
            files=[ROOT/"source/core/ServerUrlPolicy.brs",ROOT/"source/core/MarkerPolicy.brs",
                ROOT/"source/core/EpisodeNeighbors.brs",ROOT/"source/core/ContinueOverlay.brs",
                ROOT/"source/core/UpNextPolicy.brs",boundary]
            return run_function(files,"FinishedPolicyBatch",[cases],root=temporary)


    def test_policy_finished_manual_next_previous_keep_original_two_receipts(self):
        cases=[]
        for action in ("next","previous"):
            cases.append({"config":policy.config(autoplayStreak=3),"events":[*low_policy(),
                policy.native(1199,"finished"),policy.intent(action),policy.receipt("native_stopped"),policy.receipt()]})
        for action,trace in zip(("next","previous"),self.pure(cases)):
            with self.subTest(action=action):
                self.assertEqual("watching",trace[6]["state"]["phase"])
                self.assertTrue(trace[6]["projection"]["shown"])
                self.assertEqual([],trace[6]["effects"])
                self.assertTrue(trace[7]["effects"],"manual navigation from the held finished popup was rejected")
                self.assertEqual("manual_"+action,trace[7]["effects"][0]["origin"])
                self.assertEqual([],trace[8]["effects"])
                self.assertEqual("advance",trace[9]["effects"][0]["kind"])
                self.assertEqual("stop-1",trace[7]["effects"][0]["stopId"])
                self.assertEqual(0,trace[7]["state"]["autoplayStreak"])
                for forbidden in ("positionMs","finished","persistProgress","watched"):
                    self.assertNotIn(forbidden,trace[7]["effects"][0])


    def test_policy_finished_exception_requires_prior_visible_low_frame_and_settled_current_frame(self):
        bad=[policy.native(1199,"finished",landed=False),policy.native(1199,"finished",settling=True),
            policy.native(1199,"finished",status={"renderedEpoch":1}),
            policy.native(1199,"finished",status={"renderedClipId":8}),
            policy.native(1199,"finished",status={"renderedPosition":-1}),
            policy.native(1199,"finished",status={"errorCode":-19})]
        cases=[{"config":policy.config(autoplayStreak=3),"events":[*low_policy(),packet,policy.intent()]} for packet in bad]
        cases.append({"config":policy.config(autoplayStreak=3),"events":[*low_policy(),policy.intent("dismiss"),
            policy.native(1199,"finished"),policy.intent()]})
        for trace in self.pure(cases):
            self.assertFalse(any(effect["kind"]=="close" for effect in trace[-1]["effects"]))
        late={"config":policy.config(autoplayStreak=3),"events":[*low_policy()[:-1],
            policy.native(1199,"finished",quiet=True),policy.event("watching_result",probability=.1),policy.intent()]}
        trace=self.pure([late])[0]
        self.assertFalse(trace[-2]["accepted"],"a low answer after finished must not arm the hold")
        self.assertEqual([],trace[-1]["effects"])
