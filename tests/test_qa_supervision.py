"""Host-only QA supervisor lifecycle tests using fake local commands."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from qa_supervision import prepare, load_plan, run_worker, watch_once, watch, launch


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.artifact = Path(self.temp.name) / "app.zip"
        self.artifact.write_bytes(b"known package")
        self.marker = Path(self.temp.name) / "cleaned"
        self.cleanup = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).open('a').write('x')", str(self.marker)]
        self.runner = [sys.executable, "-c", "import time; time.sleep(10)"]

    def prepared(self, lease=5, grace=2):
        return prepare(self.root, "qa_test", self.artifact, lease, self.runner, self.cleanup, cleanup_grace=grace)

    def mark_started(self, manifest):
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": manifest.process.start_ticks}})

    def test_healthy_monitor_preserves_original_lease_and_private_plan(self):
        monitor = [sys.executable, "-c", "raise SystemExit(0)"]
        manifest = prepare(self.root, "qa_test", self.artifact, 5, self.runner,
                           self.cleanup, monitor=monitor, monitor_timeout=0.5)
        self.mark_started(manifest)
        self.assertEqual("waiting", watch_once(self.root))
        same, plan = load_plan(self.root)
        self.assertEqual(manifest.deadline_mono, same.deadline_mono)
        self.assertEqual(monitor, plan["monitor"])
        self.assertEqual(0.5, plan["monitor_timeout"])
        self.assertFalse((self.root / "stop-request.json").exists())
        self.assertFalse(self.marker.exists())

    def test_monitor_stop_drains_exact_runner_then_uses_existing_cleanup(self):
        from qa_durable import atomic_receipt, verify_receipt
        manifest = prepare(self.root, "qa_test", self.artifact, 5, self.runner,
                           self.cleanup, monitor=[sys.executable, "-c", "raise SystemExit(75)"])
        unit = "roku-qa-qa_test-runner.service"
        atomic_receipt(self.root / "services.json", manifest,
                       {"runner": unit, "watchdog": "roku-qa-qa_test-watchdog.service"})
        commands = []
        def drained(command, **kwargs):
            self.assertFalse(self.marker.exists())
            stop = verify_receipt(self.root / "stop-request.json", manifest)
            self.assertEqual({"reason": "resource-limit"}, stop)
            commands.append(command)
            return subprocess.CompletedProcess(command, 0,
                stdout="LoadState=not-found\nActiveState=inactive\nControlGroup=\n")
        self.mark_started(manifest)
        with patch("qa_supervision.subprocess.run", side_effect=drained), \
             patch("qa_supervision.ProcessIdentity.still_running", side_effect=[True, False]):
            self.assertEqual("cleaned", watch_once(self.root))
        self.assertEqual("x", self.marker.read_text())
        self.assertIn(["systemctl", "--user", "stop", unit], commands)
        self.assertTrue(all(command[-1] == unit for command in commands))
        self.assertEqual("resource-limit", verify_receipt(
            self.root / "cleanup-claim.json", manifest)["reason"])
        self.assertEqual(manifest.deadline_mono, load_plan(self.root)[0].deadline_mono)

    def test_unknown_monitor_exit_and_missing_executable_fail_closed(self):
        from qa_durable import verify_receipt
        for index, monitor in enumerate(([sys.executable, "-c", "raise SystemExit(2)"],
                                          ["/nonexistent/qa-monitor"])):
            with self.subTest(monitor=index):
                self.root = Path(self.temp.name) / f"failure-{index}"
                manifest = prepare(self.root, "qa_test", self.artifact, 5, self.runner,
                                   self.cleanup, monitor=monitor)
                self.mark_started(manifest)
                with patch("qa_supervision.ProcessIdentity.still_running", side_effect=[True, False]):
                    self.assertEqual("cleaned", watch_once(self.root))
                self.assertEqual({"reason": "monitor-failed"}, verify_receipt(
                    self.root / "stop-request.json", manifest))

    def test_monitor_timeout_kills_descendants_and_obeys_remaining_lease(self):
        from qa_durable import verify_receipt
        late = Path(self.temp.name) / "late-monitor"
        child = "import pathlib,sys,time; time.sleep(0.8); pathlib.Path(sys.argv[1]).touch()"
        parent = ("import subprocess,sys,time; "
                  "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(10)")
        manifest = prepare(self.root, "qa_test", self.artifact, 0.3, self.runner,
                           self.cleanup, monitor=[sys.executable, "-c", parent, child, str(late)],
                           monitor_timeout=10)
        self.mark_started(manifest)
        before = time.monotonic()
        with patch("qa_supervision.ProcessIdentity.still_running", side_effect=[True, False]):
            self.assertEqual("cleaned", watch_once(self.root))
        self.assertLess(time.monotonic() - before, 0.7)
        self.assertEqual({"reason": "monitor-timeout"}, verify_receipt(
            self.root / "stop-request.json", manifest))
        self.assertEqual(manifest.deadline_mono, load_plan(self.root)[0].deadline_mono)
        time.sleep(0.9)
        self.assertFalse(late.exists())

    def test_stale_or_malformed_stop_receipt_fails_closed_without_rerunning_monitor(self):
        from dataclasses import replace
        from qa_durable import atomic_receipt, verify_receipt
        for index, kind in enumerate(("stale", "malformed", "reason")):
            with self.subTest(kind=kind):
                self.root = Path(self.temp.name) / f"receipt-{index}"
                observed = Path(self.temp.name) / f"monitor-ran-{index}"
                monitor = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                           str(observed)]
                manifest = prepare(self.root, "qa_test", self.artifact, 5, self.runner,
                                   self.cleanup, monitor=monitor)
                receipt = self.root / "stop-request.json"
                if kind == "stale":
                    atomic_receipt(receipt, replace(manifest, run_id="old_run"), {"reason": "resource-limit"})
                elif kind == "reason":
                    atomic_receipt(receipt, manifest, {"reason": "secret arbitrary output"})
                else:
                    receipt.write_text("{broken")
                self.assertEqual("cleaned", watch_once(self.root))
                self.assertFalse(observed.exists())
                self.assertEqual({"reason": "invalid-stop-request"}, verify_receipt(receipt, manifest))

    def test_persisted_stop_request_retries_same_cleanup_without_monitor(self):
        from qa_durable import atomic_receipt, verify_receipt
        monitor = [sys.executable, "-c", "raise SystemExit(0)"]
        manifest = prepare(self.root, "qa_test", self.artifact, 5, self.runner,
                           self.cleanup, monitor=monitor)
        atomic_receipt(self.root / "stop-request.json", manifest, {"reason": "resource-limit"})
        self.assertEqual("cleaned", watch_once(self.root))
        self.assertEqual("resource-limit", verify_receipt(
            self.root / "cleanup-claim.json", manifest)["reason"])

    def test_watch_sleep_never_passes_fixed_lease(self):
        self.prepared(lease=0.3)
        with patch("qa_supervision.watch_once", side_effect=["waiting", "cleaned"]), \
             patch("qa_supervision.time.sleep") as sleep:
            self.assertEqual("cleaned", watch(self.root, poll_interval=10))
        self.assertLessEqual(sleep.call_args.args[0], 0.3)

    def test_cli_freezes_optional_monitor_command(self):
        monitor = [sys.executable, "-c", "print('private output'); raise SystemExit(75)"]
        plan_file = Path(self.temp.name) / "input-plan.json"
        plan_file.write_text(json.dumps({"run_id": "qa_test", "artifact": str(self.artifact),
            "lease_seconds": 5, "runner": self.runner, "cleanup": self.cleanup,
            "cleanup_grace": 2, "monitor": monitor, "monitor_timeout": 0.5}))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
            "tools" / "qa_supervision.py"), "prepare", str(self.root), str(plan_file)],
            capture_output=True, text=True, timeout=3)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(monitor, load_plan(self.root)[1]["monitor"])
        self.mark_started(load_plan(self.root)[0])
        with patch("qa_supervision.ProcessIdentity.still_running", side_effect=[True, False]):
            self.assertEqual("cleaned", watch_once(self.root))
        self.assertEqual("", result.stdout)

    def test_late_expiry_cleanup_claim_never_exceeds_original_lease_plus_grace(self):
        from qa_durable import verify_receipt
        manifest = self.prepared(lease=0.01, grace=2)
        self.assertEqual("cleaned", watch_once(self.root, now=manifest.deadline_mono + 0.1))
        claim = verify_receipt(self.root / "cleanup-claim.json", manifest)
        self.assertEqual(manifest.deadline_mono + 2, claim["cleanup_deadline_mono"])

    def test_fast_stop_monitor_waits_until_runner_admitted(self):
        observed = Path(self.temp.name) / "monitor-ran"
        monitor = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch(); raise SystemExit(75)", str(observed)]
        prepare(self.root, "qa_test", self.artifact, 5, self.runner, self.cleanup, monitor=monitor)
        self.assertEqual("waiting", watch_once(self.root))
        self.assertFalse(observed.exists())
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "terminal.json").exists())

    def test_dead_runner_skips_monitor_and_cleans_immediately(self):
        from qa_durable import atomic_receipt
        observed = Path(self.temp.name) / "monitor-ran"
        monitor = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch(); import time; time.sleep(10)", str(observed)]
        manifest = prepare(self.root, "qa_test", self.artifact, 5, self.runner, self.cleanup, monitor=monitor)
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": 1}})
        self.assertEqual("cleaned", watch_once(self.root))
        self.assertFalse(observed.exists())

    def test_cleanup_receipts_fence_launch_and_worker_admission(self):
        from qa_durable import atomic_receipt
        for index, filename in enumerate(("stop-request.json", "cleanup-claim.json", "terminal.json")):
            with self.subTest(receipt=filename):
                self.root = Path(self.temp.name) / f"admission-{index}"
                manifest = self.prepared()
                atomic_receipt(self.root / filename, manifest, {"reason": "resource-limit"})
                with patch("qa_supervision.subprocess.run") as systemd, \
                     patch("qa_supervision.os.execv") as execute, \
                     patch("qa_supervision.signal.setitimer"):
                    with self.assertRaises(ValueError):
                        launch(self.root)
                    with self.assertRaises(ValueError):
                        run_worker(self.root)
                systemd.assert_not_called()
                execute.assert_not_called()
                self.assertFalse((self.root / "runner-started.json").exists())

    def test_worker_waiting_for_admission_cannot_cross_cleanup_claim(self):
        import fcntl
        from qa_durable import RunLock, atomic_receipt
        manifest = self.prepared()
        blocked = Event()
        real_flock = fcntl.flock
        def record_contention(fd, operation):
            try:
                return real_flock(fd, operation)
            except BlockingIOError:
                blocked.set()
                raise
        with ThreadPoolExecutor(max_workers=1) as pool:
            with RunLock(self.root / "watch.lock", timeout=1):
                with patch("qa_durable.fcntl.flock", side_effect=record_contention):
                    worker = pool.submit(run_worker, self.root)
                    self.assertTrue(blocked.wait(1), "worker did not wait for admission lock")
                    atomic_receipt(self.root / "cleanup-claim.json", manifest,
                        {"stage": "claimed", "reason": "runner-exit",
                         "cleanup_deadline_mono": manifest.deadline_mono + 2})
            with self.assertRaisesRegex(ValueError, "stopping or terminal"):
                worker.result(timeout=1)
        self.assertFalse((self.root / "runner-started.json").exists())

    def test_prepare_syncs_new_run_directory_parent(self):
        parent_inode = self.root.parent.stat().st_ino
        synced = []
        real_fsync = os.fsync
        def record(fd):
            synced.append(os.fstat(fd).st_ino)
            return real_fsync(fd)
        with patch("qa_supervision.os.fsync", side_effect=record):
            self.prepared()
        self.assertIn(parent_inode, synced)

    def test_cli_error_does_not_echo_private_path(self):
        secret = "secret-token-in-path"
        process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"),
                                  "prepare", str(self.root), str(self.root / secret)],
                                 capture_output=True, text=True, timeout=3)
        self.assertNotEqual(0, process.returncode)
        self.assertNotIn(secret, process.stderr)

    def test_prepare_is_private_and_recovery_preserves_original_deadline(self):
        first = self.prepared()
        second, plan = load_plan(self.root)
        self.assertEqual(first.deadline_mono, second.deadline_mono)
        self.assertEqual(self.cleanup, plan["cleanup"])
        self.assertEqual(0o700, self.root.stat().st_mode & 0o777)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in self.root.iterdir() if p.is_file()))
        with self.assertRaises(FileExistsError):
            self.prepared()

    def test_stop_timeout_keeps_live_runner_protected(self):
        manifest = self.prepared(lease=0.01)
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": manifest.process.start_ticks}})
        atomic_receipt(self.root / "services.json", manifest,
                       {"runner": "roku-qa-qa_test-runner.service",
                        "watchdog": "roku-qa-qa_test-watchdog.service"})
        with patch("qa_supervision.subprocess.run", side_effect=subprocess.TimeoutExpired("systemctl", 1)):
            self.assertEqual("runner-still-live", watch_once(self.root, now=manifest.deadline_mono + 0.1))
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "terminal.json").exists())

    def test_stop_time_consumes_original_cleanup_grace(self):
        self.cleanup = [sys.executable, "-c", "import time; time.sleep(0.4)"]
        manifest = self.prepared(lease=0.01, grace=1)
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": manifest.process.start_ticks}})
        atomic_receipt(self.root / "services.json", manifest,
                       {"runner": "roku-qa-qa_test-runner.service",
                        "watchdog": "roku-qa-qa_test-watchdog.service"})
        now = manifest.deadline_mono + 0.1
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="LoadState=not-found\nActiveState=inactive\nControlGroup=\n")
        with patch("qa_supervision.ProcessIdentity.still_running", return_value=False), \
             patch("qa_supervision.subprocess.run", side_effect=fake_run), \
             patch("qa_supervision.time.monotonic", return_value=now + 0.8):
            self.assertEqual("failed", watch_once(self.root, now=now))
        self.assertEqual("cleanup-failed", json.loads((self.root / "terminal.json").read_text())["payload"]["reason"])

    def test_early_main_exit_waits_for_descendant_teardown(self):
        manifest = self.prepared(lease=10)
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": manifest.process.start_ticks}})
        atomic_receipt(self.root / "services.json", manifest,
                       {"runner": "roku-qa-qa_test-runner.service", "watchdog": "roku-qa-qa_test-watchdog.service"})
        def teardown(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="LoadState=loaded\nActiveState=deactivating\nControlGroup=\n")
        def drained(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="LoadState=not-found\nActiveState=inactive\nControlGroup=\n")
        with patch("qa_supervision.ProcessIdentity.still_running", return_value=False), \
             patch("qa_supervision.subprocess.run", side_effect=teardown):
            self.assertEqual("runner-still-live", watch_once(self.root))
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "terminal.json").exists())
        with patch("qa_supervision.ProcessIdentity.still_running", return_value=False), \
             patch("qa_supervision.subprocess.run", side_effect=drained):
            self.assertEqual("cleaned", watch_once(self.root))
        self.assertEqual("x", self.marker.read_text())

    def test_stop_timeout_after_main_exit_never_invokes_cleanup(self):
        manifest = self.prepared(lease=0.01)
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": manifest.process.start_ticks}})
        atomic_receipt(self.root / "services.json", manifest,
                       {"runner": "roku-qa-qa_test-runner.service", "watchdog": "roku-qa-qa_test-watchdog.service"})
        def timeout(command, **kwargs):
            if "stop" in command:
                raise subprocess.TimeoutExpired("systemctl", 1)
            return subprocess.CompletedProcess(command, 0, stdout="LoadState=loaded\nActiveState=active\nControlGroup=\n")
        with patch("qa_supervision.ProcessIdentity.still_running", return_value=False), \
             patch("qa_supervision.subprocess.run", side_effect=timeout):
            self.assertEqual("runner-still-live", watch_once(self.root, now=manifest.deadline_mono + 0.1))
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "terminal.json").exists())

    def test_timed_out_cleanup_kills_descendant_before_terminal_receipt(self):
        child = ("import pathlib,sys,time; time.sleep(0.4); pathlib.Path(sys.argv[1]).write_text('late')")
        parent = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(10)")
        manifest = prepare(self.root, "qa_test", self.artifact, 0.01, self.runner,
                           [sys.executable, "-c", parent, child, str(self.marker)],
                           cleanup_grace=0.15)
        self.assertEqual("failed", watch_once(self.root, now=manifest.deadline_mono + 0.01))
        time.sleep(0.55)
        self.assertFalse(self.marker.exists())

    def test_watch_retries_bounded_lock_contention(self):
        self.prepared()
        with patch("qa_supervision.watch_once", side_effect=[TimeoutError("busy"), "cleaned"]), \
             patch("qa_supervision.time.sleep"):
            self.assertEqual("cleaned", watch(self.root))

    def test_expired_lease_runs_cleanup_once_and_records_terminal_receipt(self):
        manifest = self.prepared(lease=0.01)
        result = watch_once(self.root, now=manifest.deadline_mono + 1)
        self.assertEqual("cleaned", result)
        self.assertEqual("x", self.marker.read_text())
        self.assertEqual("already-cleaned", watch_once(self.root, now=manifest.deadline_mono + 1))
        self.assertEqual("x", self.marker.read_text())
        receipt = json.loads((self.root / "terminal.json").read_text())
        self.assertEqual(manifest.run_id, receipt["manifest"]["run_id"])
        self.assertEqual(manifest.artifact_sha256, receipt["manifest"]["artifact_sha256"])
        self.assertEqual(manifest.boot_id, receipt["manifest"]["boot_id"])

    def test_killed_watchdog_reuses_original_claim_and_deadline(self):
        code = ("import os,pathlib,signal,sys; p=pathlib.Path(sys.argv[1]); "
                "first=not p.exists(); p.open('a').write('x'); "
                "os.kill(os.getppid(),signal.SIGKILL) if first else None")
        manifest = prepare(self.root, "qa_test", self.artifact, 0.01,
                           self.runner, [sys.executable, "-c", code, str(self.marker)],
                           cleanup_grace=3)
        first = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"),
                                  "watch", str(self.root)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        try:
            self.assertNotEqual(0, first.wait(timeout=3))
            claim = json.loads((self.root / "cleanup-claim.json").read_text())["payload"]
            self.assertFalse((self.root / "terminal.json").exists())
            self.assertEqual("cleaned", watch_once(self.root, now=claim["cleanup_deadline_mono"] - 1))
            self.assertEqual("xx", self.marker.read_text())
            same, _ = load_plan(self.root)
            self.assertEqual(manifest.deadline_mono, same.deadline_mono)
            final_claim = json.loads((self.root / "cleanup-claim.json").read_text())["payload"]
            self.assertEqual(claim["cleanup_deadline_mono"], final_claim["cleanup_deadline_mono"])
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=2)

    def test_competing_watchdogs_converge_on_one_terminal_receipt(self):
        manifest = self.prepared(lease=0.01)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: watch_once(self.root, now=manifest.deadline_mono + 1), range(2)))
        self.assertEqual(["already-cleaned", "cleaned"], sorted(results))
        self.assertEqual("x", self.marker.read_text())

    @unittest.skipUnless(os.environ.get("ROKU_QA_SYSTEMD_TEST") == "1", "opt-in transient user services")
    def test_transient_services_survive_launcher_exit_and_cleanup(self):
        run_id = "test-" + uuid.uuid4().hex[:8]
        manifest = prepare(self.root, run_id, self.artifact, 3,
                           self.runner, self.cleanup, cleanup_grace=4)
        runner_unit = f"roku-qa-{run_id}-runner.service"
        watch_unit = f"roku-qa-{run_id}-watchdog.service"
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"),
                            "launch", str(self.root)], check=True, timeout=10)
            deadline = time.monotonic() + 9
            while not (self.root / "terminal.json").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertEqual("x", self.marker.read_text())
            self.assertEqual("cleaned", json.loads((self.root / "terminal.json").read_text())["payload"]["stage"])
        finally:
            for unit in (runner_unit, watch_unit):
                subprocess.run(["systemctl", "--user", "stop", unit], timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @unittest.skipUnless(os.environ.get("ROKU_QA_SYSTEMD_TEST") == "1", "opt-in transient user services")
    def test_early_main_exit_service_drains_descendant_before_cleanup(self):
        run_id = "test-" + uuid.uuid4().hex[:8]
        alive = Path(self.temp.name) / "descendant-alive"
        child = ("import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                 "p=pathlib.Path(sys.argv[1]); p.touch(); time.sleep(0.8); p.unlink()")
        runner = [sys.executable, "-c",
                  "import pathlib,subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
                  "p=pathlib.Path(sys.argv[2]); exec('while not p.exists(): time.sleep(0.01)')",
                  child, str(alive)]
        cleanup = [sys.executable, "-c",
                   "import pathlib,sys; assert not pathlib.Path(sys.argv[1]).exists(); pathlib.Path(sys.argv[2]).write_text('x')",
                   str(alive), str(self.marker)]
        prepare(self.root, run_id, self.artifact, 3, runner, cleanup, cleanup_grace=4)
        units = [f"roku-qa-{run_id}-{role}.service" for role in ("runner", "watchdog")]
        try:
            launch(self.root)
            deadline = time.monotonic() + 6
            while not (self.root / "terminal.json").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual("x", self.marker.read_text())
            self.assertFalse(alive.exists())
            self.assertEqual("cleaned", json.loads((self.root / "terminal.json").read_text())["payload"]["stage"])
        finally:
            for unit in units:
                subprocess.run(["systemctl", "--user", "stop", unit], timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @unittest.skipUnless(os.environ.get("ROKU_QA_SYSTEMD_TEST") == "1", "opt-in transient user services")
    def test_runner_cgroup_kill_triggers_independent_watchdog(self):
        run_id = "test-" + uuid.uuid4().hex[:8]
        prepare(self.root, run_id, self.artifact, 12,
                self.runner, self.cleanup, cleanup_grace=4)
        runner_unit = f"roku-qa-{run_id}-runner.service"
        watch_unit = f"roku-qa-{run_id}-watchdog.service"
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"),
                            "launch", str(self.root)], check=True, timeout=10)
            deadline = time.monotonic() + 3
            while not (self.root / "runner-started.json").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue((self.root / "runner-started.json").exists())
            subprocess.run(["systemctl", "--user", "kill", "--kill-whom=all", runner_unit],
                           check=True, timeout=5, stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + 4
            while not self.marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual("x", self.marker.read_text())
        finally:
            for unit in (runner_unit, watch_unit):
                subprocess.run(["systemctl", "--user", "stop", unit], timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_runner_launch_rechecks_original_deadline_after_watchdog_start(self):
        manifest = self.prepared(lease=5)
        commands = []
        def fake_start(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0)
        with patch("qa_supervision.subprocess.run", side_effect=fake_start), \
             patch("qa_supervision.RunLock", return_value=nullcontext()), \
             patch("qa_supervision.time.monotonic", side_effect=[manifest.deadline_mono - 2,
                                                                    manifest.deadline_mono - 2,
                                                                    manifest.deadline_mono + 0.1]):
            with self.assertRaisesRegex(ValueError, "lease expired"):
                launch(self.root)
        self.assertEqual(1, len(commands))

    def test_runner_runtime_limit_never_adds_lease_time(self):
        manifest = self.prepared(lease=5)
        commands = []
        def fake_start(command, **kwargs):
            self.assertLessEqual(kwargs["timeout"], 2.2)
            commands.append(command)
            return subprocess.CompletedProcess(command, 0)
        with patch("qa_supervision.subprocess.run", side_effect=fake_start), \
             patch("qa_supervision.RunLock", return_value=nullcontext()), \
             patch("qa_supervision.time.monotonic", side_effect=[manifest.deadline_mono - 2.2,
                                                                    manifest.deadline_mono - 2.2,
                                                                    manifest.deadline_mono - 1.4]):
            launch(self.root)
        runner = commands[-1]
        limit = next(x for x in runner if x.startswith("--property=RuntimeMaxSec="))
        self.assertLessEqual(float(limit.split("=", 2)[-1].rstrip("s")), 1.4)

    def test_second_launch_refuses_to_restart_same_run(self):
        self.prepared()
        manifest, _ = load_plan(self.root)
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "services.json", manifest,
                       {"runner": "roku-qa-test-runner.service",
                        "watchdog": "roku-qa-test-watchdog.service"})
        with self.assertRaisesRegex(ValueError, "already launched"):
            launch(self.root)

    def test_runner_entry_refuses_second_start(self):
        self.prepared()
        manifest, _ = load_plan(self.root)
        from qa_durable import atomic_receipt
        atomic_receipt(self.root / "runner-started.json", manifest,
                       {"process": {"pid": os.getpid(), "start_ticks": manifest.process.start_ticks}})
        with self.assertRaisesRegex(ValueError, "already started"):
            run_worker(self.root)

    def test_runner_enforces_original_deadline_without_watchdog(self):
        prepare(self.root, "qa_test", self.artifact, 0.6, self.runner,
                self.cleanup, cleanup_grace=10)
        time.sleep(0.3)
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"),
                                   "run", str(self.root)], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        try:
            self.assertNotEqual(0, worker.wait(timeout=0.7))
            self.assertFalse(self.marker.exists())
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=2)

    def test_invalid_reloaded_identity_refuses_cleanup(self):
        manifest = self.prepared(lease=0.01)
        path = self.root / "manifest.json"
        for field, bad in (("run_id", "../other"), ("artifact_sha256", "a"),
                           ("deadline_mono", "tomorrow"), ("process", {"pid": -1, "start_ticks": 0})):
            original = path.read_text()
            document = json.loads(original)
            document["manifest"][field] = bad
            path.write_text(json.dumps(document))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "invalid supervision plan"):
                watch_once(self.root, now=manifest.deadline_mono + 1)
            self.assertFalse(self.marker.exists())
            path.write_text(original)

    def test_stale_artifact_refuses_cleanup(self):
        manifest = self.prepared(lease=0.01)
        self.artifact.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "artifact mismatch"):
            watch_once(self.root, now=manifest.deadline_mono + 1)
        self.assertFalse(self.marker.exists())

    def test_runner_sigkill_triggers_cleanup_before_deadline(self):
        manifest = self.prepared(lease=30)
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"), "run", str(self.root)])
        try:
            for _ in range(100):
                if (self.root / "runner-started.json").exists():
                    break
                time.sleep(0.01)
            self.assertTrue((self.root / "runner-started.json").exists())
            worker.kill()
            worker.wait(timeout=2)
            self.assertEqual("cleaned", watch_once(self.root, now=manifest.start_mono + 1))
            self.assertEqual("x", self.marker.read_text())
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=2)

    def test_live_runner_cannot_be_cleaned_before_deadline(self):
        manifest = self.prepared(lease=30)
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "qa_supervision.py"), "run", str(self.root)])
        try:
            for _ in range(100):
                if (self.root / "runner-started.json").exists():
                    break
                time.sleep(0.01)
            self.assertEqual("waiting", watch_once(self.root, now=manifest.start_mono + 1))
            self.assertFalse(self.marker.exists())
        finally:
            worker.kill()
            worker.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
