"""EpisodeNeighborTask publication remains scoped and private-safe."""

from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_brightscript, run_function


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "components/EpisodeNeighborTask.brs"
NEIGHBORS = ROOT / "source/core/EpisodeNeighbors.brs"
OVERLAY = ROOT / "source/core/ContinueOverlay.brs"
JOB = {"provider": "plex", "sourceId": "plex:fixture", "profileId": "owner",
       "generation": 12, "lookupId": "neighbor-4", "anchorItemId": "101",
       "playbackSessionId": "play-3", "params": {}}

WORKER_BOUNDARY = '''
function EpisodeNeighborExecute(job as Object) as Object
    if m.failDispatch then throw "synthetic-private-token https://private.example.test"
    return {status:"verified_end"}
end function

function RunWorker(job as Object, failDispatch as Boolean) as Object
    m.failDispatch = failDispatch
    m.top = {job:job,result:invalid}
    escaped = false
    try
        runNeighborJob()
    catch exception
        escaped = true
    end try
    return {escaped:escaped,result:m.top.result}
end function
'''


class EpisodeTaskLivenessTests(unittest.TestCase):
    def run_worker(self, *, failure=False, output=False):
        with tempfile.TemporaryDirectory(prefix="silo-neighbor-liveness-") as directory:
            temporary = Path(directory)
            worker = temporary / "worker.brs"
            worker.write_text(WORKER.read_text().replace("function EpisodeNeighborExecute(",
                                                       "function UnusedEpisodeNeighborExecute(", 1))
            boundary = temporary / "boundary.brs"
            boundary.write_text(WORKER_BOUNDARY)
            files = [worker, boundary]
            if output:
                return run_brightscript(files, 'RunWorker({provider:"plex",lookupId:"neighbor-4"},true)',
                                       root=temporary)
            return run_function(files, "RunWorker", [JOB, failure], root=temporary)


    def test_worker_exception_publishes_scoped_retryable_failure(self):
        result = self.run_worker(failure=True)
        self.assertFalse(result["escaped"], "catchable failures must publish a correlated outcome")
        self.assertEqual({**{key: value for key, value in JOB.items() if key != "params"},
                          "status": "retryable", "errorCode": "task_failed"}, result["result"])
        self.assertNotIn("synthetic-private", str(result))

    def test_exception_diagnostics_never_print_private_text(self):
        output = self.run_worker(failure=True, output=True)
        self.assertNotIn("synthetic-private", output)
        self.assertNotIn("private.example.test", output)

    def test_success_keeps_the_scoped_worker_outcome(self):
        result = self.run_worker()
        self.assertFalse(result["escaped"])
        self.assertEqual({**{key: value for key, value in JOB.items() if key != "params"},
                          "status": "verified_end"}, result["result"])


if __name__ == "__main__":
    unittest.main()
