"""Worker publication keeps its correlated envelope and private-safe failures."""

from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_brightscript, run_function


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "components/ApiTask.brs"
JOB = {"provider": "plex", "action": "pin_start", "sourceId": "", "profileId": "",
       "generation": 4, "requestId": "ui-1", "params": {}}

WORKER_BOUNDARY = '''
function ExecuteApiAction(provider as String, action as String, params as Object, scope as Object) as Object
    if m.failDispatch then throw "synthetic-private-token https://private.example.test"
    return {ok:true,data:{code:"ABCD"}}
end function

function RunWorker(job as Object, failDispatch as Boolean) as Object
    m.failDispatch = failDispatch
    m.top = {job:job,result:invalid}
    m.escaped = false
    try
        runJob()
    catch exception
        m.escaped = true
    end try
    return {escaped:m.escaped,result:m.top.result}
end function
'''


class ApiTaskLivenessTests(unittest.TestCase):
    def run_worker(self, *, failure=False, output=False):
        with tempfile.TemporaryDirectory(prefix="silo-worker-liveness-") as directory:
            temporary = Path(directory)
            worker = temporary / "worker.brs"
            worker.write_text(WORKER.read_text().replace("function ExecuteApiAction(",
                                                       "function UnusedExecuteApiAction(", 1))
            boundary = temporary / "boundary.brs"
            boundary.write_text(WORKER_BOUNDARY)
            files = [worker, boundary]
            if output:
                return run_brightscript(files, 'RunWorker({provider:"plex",action:"pin_start",requestId:"ui-1"},true)',
                                       root=temporary)
            return run_function(files, "RunWorker", [JOB, failure], root=temporary)


    def success(self):
        return {**{key: value for key, value in JOB.items() if key != "params"},
                "ok": True, "data": {"code": "ABCD"}}

    def test_worker_exception_publishes_a_correlated_safe_failure(self):
        result = self.run_worker(failure=True)
        self.assertFalse(result["escaped"], "a caught worker failure must still publish its result")
        self.assertEqual({**{key: value for key, value in JOB.items() if key != "params"},
                          "ok": False, "errorCode": "task_failed", "authPhase": "worker"}, result["result"])
        self.assertNotIn("synthetic-private", str(result))

    def test_exception_diagnostics_never_print_private_exception_text(self):
        output = self.run_worker(failure=True, output=True)
        self.assertNotIn("synthetic-private", output)
        self.assertNotIn("private.example.test", output)

    def test_success_keeps_the_complete_worker_envelope(self):
        result = self.run_worker()
        self.assertFalse(result["escaped"])
        self.assertEqual(self.success(), result["result"])


if __name__ == "__main__":
    unittest.main()
