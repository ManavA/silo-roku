"""Behavior at the host QA durability boundary; no device or server access."""

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from qa_durable import (EventJournal, RunManifest, RunLock, atomic_receipt,
                        read_events, sanitize_event, verify_receipt)


class DurableQATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.manifest = RunManifest.create("qa11980", "a" * 64, 10.0, boot_id="boot-1",
                                           now=100.0)

    def test_manifest_is_immutable_and_deadline_is_fixed(self):
        self.assertEqual(110.0, self.manifest.deadline_mono)
        with self.assertRaises(AttributeError):
            self.manifest.deadline_mono = 200.0
        self.assertTrue(self.manifest.expired(110.0, "boot-1"))
        self.assertTrue(self.manifest.expired(101.0, "other-boot"))
        self.assertFalse(self.manifest.expired(109.0, "boot-1"))
        self.assertEqual(os.getpid(), self.manifest.process.pid)
        self.assertGreater(self.manifest.process.start_ticks, 0)

    def test_manifest_rejects_deadline_overflow(self):
        with self.assertRaisesRegex(ValueError, "invalid deadline"):
            RunManifest.create("qa11980", "a" * 64, 1e308,
                               boot_id="boot-1", now=1e308)

    def test_manifest_detects_artifact_mutation_after_digest_is_frozen(self):
        artifact = self.root / "app.zip"
        self.root.mkdir(mode=0o700)
        artifact.write_bytes(b"frozen package")
        digest = hashlib.sha256(b"frozen package").hexdigest()
        manifest = RunManifest.create("qa11980", digest, 10, boot_id="boot-1", now=100)
        self.assertTrue(manifest.artifact_matches(artifact))
        artifact.write_bytes(b"mutated package")
        self.assertFalse(manifest.artifact_matches(artifact))

    def test_atomic_receipt_is_private_and_identity_checked(self):
        path = self.root / "receipt.json"
        atomic_receipt(path, self.manifest, {"stage": "started"})
        self.assertEqual(0o700, self.root.stat().st_mode & 0o777)
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual({"stage": "started"}, verify_receipt(path, self.manifest))
        for changed in ({"run_id": "other"}, {"artifact_sha256": "b" * 64},
                        {"boot_id": "boot-2"}, {"process": {"pid": 1, "start_ticks": 2}}):
            receipt = json.loads(path.read_text())
            receipt["manifest"].update(changed)
            path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                verify_receipt(path, self.manifest)
            atomic_receipt(path, self.manifest, {"stage": "started"})

    def test_failed_atomic_replacement_retains_previous_valid_receipt(self):
        path = self.root / "receipt.json"
        atomic_receipt(path, self.manifest, {"stage": "old"})
        with patch("qa_durable.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                atomic_receipt(path, self.manifest, {"stage": "new"})
        self.assertEqual({"stage": "old"}, verify_receipt(path, self.manifest))
        self.assertEqual(["receipt.json"], [p.name for p in self.root.iterdir()])
        atomic_receipt(path, self.manifest, {"stage": "new"})
        self.assertEqual({"stage": "new"}, verify_receipt(path, self.manifest))

    def test_first_receipt_syncs_new_private_directory_chain(self):
        path = self.root / "nested" / "receipt.json"
        synced = []
        actual_fsync = os.fsync

        def observed_sync(fd):
            synced.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
            actual_fsync(fd)

        with patch("qa_durable.os.fsync", side_effect=observed_sync):
            atomic_receipt(path, self.manifest, {"stage": "started"})
        self.assertTrue({Path(self.temp.name), self.root, self.root / "nested"}
                        <= set(synced))

    def test_event_allowlist_rejects_unknown_fields_without_echo(self):
        self.assertEqual("qa_video state=buffering position=12.5",
                         sanitize_event("qa_video state=buffering position=12.5"))
        for bad in ("qa_video state=buffering token=secret",
                    "qa_video state=evil position=1",
                    "qa_video state=playing url=https://private/x",
                    "other state=playing", "qa_video position=nan"):
            with self.assertRaisesRegex(ValueError, "invalid event") as failure:
                sanitize_event(bad)
            self.assertNotIn("secret", str(failure.exception))
            self.assertNotIn("private", str(failure.exception))

    def test_allowlist_accepts_current_native_numeric_fields(self):
        examples = (
            "qa_control event=3 from=12.5 target=20",
            "qa_control event=2 paused_ms=102 position=12.5",
            "qa_http_defer episode=1 active=2 cap=3 loops=4 wall_ms=5",
            "qa_http_loop route=1 max_idle_ms=2 stop_poll_ms=3 loops=4",
            "qa_memory stage=1 available_kb=2 min_available_kb=2 usage_pct=3 max_usage_pct=3",
        )
        for example in examples:
            self.assertEqual(example, sanitize_event(example))

    def test_roll_telemetry_accepts_emitted_numeric_shapes_and_only_declared_sentinels(self):
        events = (
            "qa_roll_phase g=2 src=4 local=1 kind=2 phase=6 start=100 end=120 ms=20",
            "qa_roll_work g=2 src=4 local=1 kind=2 outcome=1 at=120",
            "qa_roll_bytes source=1048576 audio=32768 hash_source=1048576 hash_audio=32768",
            "qa_roll_bytes source=1.04858e+06 audio=0 hash_source=0 hash_audio=0",
            "qa_roll_ticks count=2 total_ms=11 max_ms=8",
            "qa_roll_demand g=2 src=4 local=1 outcome=3 queued_ms=-1 work_ms=-1",
            "qa_roll_demand g=2 src=4 local=1 outcome=1 queued_ms=5 work_ms=9",
            "qa_roll_admit g=2 src=4 local=1 visits=3 evicted=1 resident=32768",
            "qa_roll_admit g=2 src=4 local=1 visits=3 evicted=1 resident=32768 kind=2 gate=2 lead_ms=-500 min_lead_ms=12000 window_ms=24000 request_end_ms=6000 victim_first_end_ms=-24500 victim_last_end_ms=-24500",
        )
        path = self.root / "roll-events.jsonl"
        with EventJournal(path) as journal:
            for index, event in enumerate(events):
                journal.append(index, event)
        rows, partial = read_events(path)
        self.assertFalse(partial)
        self.assertEqual(events, tuple(row["event"] for row in rows))
        for bad in ("qa_roll_phase g=1 src=1 local=1 kind=1 phase=1 start=1 end=2 ms=-1",
                    "qa_roll_demand g=1 src=1 local=1 outcome=3 queued_ms=-2 work_ms=-1",
                    "qa_roll_bytes source=-1 audio=0 hash_source=0 hash_audio=0",
                    "qa_roll_bytes source=1e999 audio=0 hash_source=0 hash_audio=0",
                    "qa_roll_bytes source=private audio=0 hash_source=0 hash_audio=0",
                    "qa_roll_ticks count=1 total_ms=2",
                    "qa_roll_work g=1 src=1 local=1 kind=1 outcome=1 at=2 token=secret",
                    "qa_roll_ticks count=1 total_ms=2 max_ms=2 url=private"):
            with self.assertRaisesRegex(ValueError, "invalid event") as failure:
                sanitize_event(bad)
            self.assertNotIn("secret", str(failure.exception))
            self.assertNotIn("private", str(failure.exception))

    def test_journal_flushes_on_lifecycle_and_reads_partial_tail(self):
        path = self.root / "events.jsonl"
        with EventJournal(path, fsync_interval=60, now=lambda: 10.0) as journal:
            journal.append(1.0, "qa_video state=buffering position=12")
            journal.flush()
            journal.append(2.0, "qa_video state=playing position=13")
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        with path.open("ab") as output:
            output.write(b'{"elapsed":3,"event":"qa_video')
        rows, partial = read_events(path)
        self.assertTrue(partial)
        self.assertEqual([1.0, 2.0], [row["elapsed"] for row in rows])
        self.assertEqual("qa_video state=playing position=13", rows[-1]["event"])

    def test_journal_restart_discards_crash_incomplete_tail_before_append(self):
        path = self.root / "events.jsonl"
        with EventJournal(path) as journal:
            journal.append(1, "qa_video state=playing position=1")
        with path.open("ab") as output:
            output.write(b'{"elapsed":2,"event":"qa_video')
        with EventJournal(path) as journal:
            journal.append(3, "qa_video state=finished position=3")
        rows, partial = read_events(path)
        self.assertFalse(partial)
        self.assertEqual([1, 3], [row["elapsed"] for row in rows])

    def test_first_journal_claim_syncs_file_and_new_private_directory_chain(self):
        path = self.root / "nested" / "events.jsonl"
        synced = []
        actual_fsync = os.fsync

        def observed_sync(fd):
            synced.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
            actual_fsync(fd)

        with patch("qa_durable.os.fsync", side_effect=observed_sync):
            with EventJournal(path):
                pass
        self.assertTrue({Path(self.temp.name), self.root, self.root / "nested", path}
                        <= set(synced))

    def test_interior_invalid_record_is_explicit_error(self):
        path = self.root / "events.jsonl"
        self.root.mkdir(mode=0o700)
        path.write_text('{"elapsed":1,"event":"qa_video state=playing position=1"}\n'
                        '{"elapsed":2,"event":"qa_video token=private"}\n'
                        '{"elapsed":3,"event":"qa_video state=playing position=3"}\n')
        with self.assertRaisesRegex(ValueError, "record 2") as failure:
            read_events(path)
        self.assertNotIn("private", str(failure.exception))

    def test_periodic_fsync_is_bounded(self):
        clock = [0.0]
        path = self.root / "events.jsonl"
        with patch("qa_durable.os.fsync", wraps=os.fsync) as sync:
            with EventJournal(path, fsync_interval=2.0, now=lambda: clock[0]) as journal:
                baseline = sync.call_count
                journal.append(0, "qa_video state=playing position=0")
                self.assertEqual(baseline, sync.call_count)
                clock[0] = 2.1
                journal.append(2.1, "qa_video state=playing position=2")
                self.assertGreater(sync.call_count, baseline)
                after_periodic = sync.call_count
            self.assertGreater(sync.call_count, after_periodic)

    def test_idle_journal_syncs_last_record_within_interval(self):
        path = self.root / "events.jsonl"
        synced = threading.Event()
        actual_fsync = os.fsync

        def observed_sync(fd):
            actual_fsync(fd)
            synced.set()

        with patch("qa_durable.os.fsync", side_effect=observed_sync):
            with EventJournal(path, fsync_interval=0.05) as journal:
                synced.clear()
                journal.append(0, "qa_video state=playing position=0")
                self.assertTrue(synced.wait(0.5))

    def test_lock_is_exclusive_and_kernel_releases_killed_holder(self):
        lock_path = self.root / "run.lock"
        with RunLock(lock_path, timeout=1):
            with self.assertRaises(TimeoutError):
                with RunLock(lock_path, timeout=0.05):
                    pass
        code = ("import sys,time; from pathlib import Path; "
                "sys.path.insert(0,sys.argv[1]); from qa_durable import RunLock; "
                "lock=RunLock(Path(sys.argv[2]),timeout=1); lock.__enter__(); "
                "print('locked',flush=True); time.sleep(30)")
        process = subprocess.Popen([sys.executable, "-c", code,
                                    str(Path(__file__).resolve().parents[1] / "tools"),
                                    str(lock_path)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual("locked", process.stdout.readline().strip())
            with self.assertRaises(TimeoutError):
                with RunLock(lock_path, timeout=0.05):
                    pass
            process.kill()
            process.wait(timeout=3)
            with RunLock(lock_path, timeout=1):
                pass
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            process.stdout.close()

    def test_lock_rejects_nonfinite_nonnumeric_and_boolean_timing(self):
        for field, invalid in (("timeout", (float("nan"), float("inf"),
                                            -float("inf"), True, False, "1", -1)),
                               ("poll_interval", (float("nan"), float("inf"),
                                                  -float("inf"), True, False, "1", 0))):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    options = {"timeout": 0, "poll_interval": 0.01}
                    options[field] = value
                    with self.assertRaises(ValueError):
                        RunLock(self.root / "run.lock", **options)
        RunLock(self.root / "run.lock", timeout=0, poll_interval=0.01)


if __name__ == "__main__":
    unittest.main()
