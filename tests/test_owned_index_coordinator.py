"""Task-local finite scan scheduling against real owned page/manifest policies."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/OwnedIndexCoordinatorPolicy.brs"
PAGE = ROOT / "source/core/OwnedIndexPolicy.brs"
MANIFEST = ROOT / "source/core/OwnedIndexManifestPolicy.brs"
NOW = 1791882000
SCOPE = {"provider": "plex", "sourceId": "plex:fixture-server", "profileId": "",
         "accountId": "fixture-account", "sessionRevision": 3, "inventoryRunId": "run-1"}
DISCOVERY = {"sections": [{"sectionId": "10", "type": "movie"},
                           {"sectionId": "20", "type": "show"}], "truncated": False}
IDLE = {"playbackActive": False, "apiBusy": False, "memoryPressure": False}


class OwnedIndexCoordinatorTests(unittest.TestCase):
    def call(self, function, *arguments):
        self.assertTrue(POLICY.is_file(), "owned index scan coordinator is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-coordinator-") as directory:
            return run_function([PAGE, MANIFEST, POLICY], function, list(arguments), root=Path(directory))

    def start(self, scope=None, discovery=None):
        return self.call("OwnedIndexCoordinatorStart", SCOPE if scope is None else scope,
                         DISCOVERY if discovery is None else discovery, NOW)

    def take(self, state, scope=SCOPE, activity=IDLE, now=NOW):
        return self.call("OwnedIndexCoordinatorTake", state, scope, activity, now)

    def receipt(self, job, *, raw_count=3, terminal=False, records=True):
        total = job["offset"] + raw_count + (0 if terminal else 20)
        metadata = [{"ratingKey": str(job["offset"] + index + 1),
                     "type": "clip", "title": "Synthetic filtered card"}
                    for index in range(raw_count)]
        if records and metadata:
            metadata[0] = {"ratingKey": str(job["offset"] + 1),
                           "type": "movie" if job["libraryId"] == "10" else "show",
                           "title": "Synthetic owned title", "Guid": [{"id": "tmdb://1000"}]}
        body = json.dumps({"MediaContainer": {"offset": job["offset"], "size": raw_count,
                                             "totalSize": total, "Metadata": metadata}})
        page = self.call("OwnedIndexDecodePage", job, body)["page"]
        shard = self.call("OwnedIndexShard", job, page, SCOPE, 3, NOW)
        self.assertTrue(shard["ok"])
        result = {key: job[key] for key in ("provider", "sourceId", "profileId", "inventoryRunId",
                                          "libraryId", "offset", "requestId")}
        result.update(status="page", persistent=True, page=page,
                      shardUri=shard["uri"], shardBytes=shard["bytes"])
        return result, shard["body"]

    def complete(self, taken, receipt=None, body=None, scope=SCOPE, now=NOW):
        if receipt is None:
            receipt, body = self.receipt(taken["job"])
        return self.call("OwnedIndexCoordinatorComplete", taken["state"], scope, receipt, body, now)

    def test_start_validates_plex_scope_and_retains_only_bounded_section_descriptors(self):
        raw_scope = {**SCOPE, "token": "synthetic-private", "url": "https://fixture.test"}
        discovery = copy.deepcopy(DISCOVERY)
        discovery["sections"][0].update(title="Synthetic private library", token="synthetic-private")
        state = self.start(raw_scope, discovery)
        self.assertEqual(SCOPE, state["scope"])
        self.assertEqual(["10", "20"], [entry["libraryId"] for entry in state["sections"]])
        self.assertFalse(state["partial"])
        self.assertFalse(state["finished"])
        self.assertFalse(state["authoritativeAbsence"])
        self.assertFalse(state["sourceInventoryComplete"])
        for value in ("synthetic-private", "https://", "Synthetic private library"):
            self.assertNotIn(value, json.dumps(state))
        self.assertLess(len(json.dumps(state)), 4000)

    def test_invalid_scope_and_invalid_or_duplicate_sections_cannot_start(self):
        for patch in ({"provider": "silo"}, {"sourceId": "plex:https://fixture.test"},
                      {"profileId": None}, {"accountId": ""}, {"sessionRevision": -1},
                      {"inventoryRunId": "../unsafe"}):
            with self.subTest(patch=patch):
                self.assertIsNone(self.start({**SCOPE, **patch}))
        for sections in (None, [{"sectionId": "10", "type": "artist"}],
                         [{"sectionId": "../unsafe", "type": "movie"}],
                         [{"sectionId": "10", "type": "movie", "sourceId": "plex:other"}],
                         [DISCOVERY["sections"][0]] * 2):
            with self.subTest(sections=sections):
                self.assertIsNone(self.start(discovery={"sections": sections, "truncated": False}))

    def test_one_valid_48_slot_job_at_a_time_has_no_account_or_credentials(self):
        taken = self.take(self.start())
        job = taken["job"]
        self.assertTrue(self.call("OwnedIndexValidJob", job))
        self.assertEqual(48, job["limit"])
        self.assertEqual(0, job["offset"])
        self.assertTrue(job["writeShard"])
        self.assertNotIn("accountId", job)
        self.assertNotIn("sessionRevision", job)
        busy = self.take(taken["state"])
        self.assertIsNone(busy["job"])
        self.assertEqual(taken["state"], busy["state"])

    def test_correlated_validated_shard_advances_raw_slots_and_drops_all_records(self):
        taken = self.take(self.start())
        receipt, body = self.receipt(taken["job"], raw_count=3)
        done = self.complete(taken, receipt, body)
        self.assertTrue(done["accepted"])
        next_job = self.take(done["state"])["job"]
        self.assertEqual(3, next_job["offset"])
        self.assertNotEqual(taken["job"]["requestId"], next_job["requestId"])
        self.assertEqual(1, len(done["state"]["manifest"]["shards"]))
        for value in ("Synthetic owned title", '"records"', "tmdb://"):
            self.assertNotIn(value, json.dumps(done["state"]))

    def test_every_receipt_correlation_field_fences_stale_results(self):
        taken = self.take(self.start())
        receipt, body = self.receipt(taken["job"])
        for field, value in (("provider", "silo"), ("sourceId", "plex:other"),
                             ("profileId", "other"), ("inventoryRunId", "run-other"),
                             ("libraryId", "20"), ("offset", 3), ("requestId", 999)):
            with self.subTest(field=field):
                ignored = self.complete(taken, {**receipt, field: value}, body)
                self.assertFalse(ignored["accepted"])
                self.assertEqual(taken["state"], ignored["state"])

    def test_empty_terminal_section_advances_to_next_then_finishes_without_absence_claim(self):
        taken = self.take(self.start())
        receipt, body = self.receipt(taken["job"], raw_count=0, terminal=True)
        done = self.complete(taken, receipt, body)
        next_taken = self.take(done["state"])
        self.assertEqual("20", next_taken["job"]["libraryId"])
        self.assertEqual(0, next_taken["job"]["offset"])
        receipt, body = self.receipt(next_taken["job"], terminal=True)
        final = self.complete(next_taken, receipt, body)["state"]
        self.assertTrue(final["finished"])
        self.assertEqual("terminal", final["status"])
        self.assertFalse(final["partial"])
        self.assertFalse(final["authoritativeAbsence"])
        self.assertFalse(final["sourceInventoryComplete"])
        self.assertIsNone(self.take(final)["job"])

    def test_section_errors_mark_partial_and_allow_other_sections_to_scan(self):
        taken = self.take(self.start())
        receipt, body = self.receipt(taken["job"])
        failure = {key: value for key, value in receipt.items() if key not in
                   ("page", "shardUri", "shardBytes")}
        failure.update(status="retryable", persistent=False, errorCode="network_timeout")
        done = self.complete(taken, failure, "")
        self.assertTrue(done["accepted"])
        self.assertTrue(done["state"]["partial"])
        self.assertEqual("partial", done["state"]["sections"][0]["status"])
        self.assertEqual("network_timeout", done["state"]["sections"][0]["errorCode"])
        next_taken = self.take(done["state"])
        self.assertEqual("20", next_taken["job"]["libraryId"])

    def test_worker_session_change_cancels_even_before_the_scanner_observes_new_scope(self):
        taken = self.take(self.start())
        result = {key: taken["job"][key] for key in ("provider", "sourceId", "profileId",
                                                   "inventoryRunId", "libraryId", "offset", "requestId")}
        result.update(status="retryable", persistent=False, errorCode="session_changed")
        done = self.complete(taken, result, "")
        self.assertTrue(done["accepted"])
        self.assertTrue(done["state"]["finished"])
        self.assertTrue(done["state"]["partial"])
        self.assertEqual("cancelled", done["state"]["status"])
        self.assertEqual("session_changed", done["state"]["errorCode"])
        self.assertIsNone(self.take(done["state"])["job"])

    def test_correlated_bad_pages_or_unverified_shards_fail_partial_without_raw_advance(self):
        taken = self.take(self.start())
        receipt, body = self.receipt(taken["job"])
        bad = copy.deepcopy(receipt)
        bad["page"]["nextOffset"] = 1
        for result, shard_body in ((bad, body), ({**receipt, "persistent": False}, ""),
                                   (receipt, "{}"), ({**receipt, "shardUri": "cachefs:/other.json"}, body),
                                   ({**receipt, "token": "synthetic-private"}, body)):
            with self.subTest(result=result, body=shard_body):
                done = self.complete(taken, result, shard_body)
                self.assertTrue(done["accepted"])
                self.assertTrue(done["state"]["partial"])
                self.assertEqual(0, done["state"]["sections"][0]["nextOffset"])
                self.assertEqual([], done["state"]["manifest"]["shards"])

    def test_discovery_truncation_bounds_sections_and_cannot_be_cleared_by_terminal_page(self):
        for count, flag in ((2, True), (24, False), (1000, False)):
            discovery = {"sections": [{"sectionId": str(index), "type": "movie"}
                                      for index in range(count)], "truncated": flag}
            state = self.start(discovery=discovery)
            self.assertEqual(min(count, 24), len(state["sections"]))
            self.assertTrue(state["partial"])
            self.assertTrue(state["sectionTruncated"])
            self.assertLess(len(json.dumps(state)), 9000)

    def test_empty_validated_inventory_is_terminal_but_never_authoritative(self):
        state = self.start(discovery={"sections": [], "truncated": False})
        self.assertTrue(state["finished"])
        self.assertFalse(state["partial"])
        self.assertFalse(state["authoritativeAbsence"])
        self.assertFalse(state["sourceInventoryComplete"])
        self.assertIsNone(self.take(state)["job"])

    def test_foreground_work_and_memory_pause_before_dispatch_and_cancel_an_active_page(self):
        for field in IDLE:
            with self.subTest(field=field):
                activity = {**IDLE, field: True}
                paused = self.take(self.start(), activity=activity)
                self.assertIsNone(paused["job"])
                self.assertEqual("paused", paused["state"]["status"])
                self.assertIsNotNone(self.take(paused["state"])["job"])
                taken = self.take(self.start())
                receipt, body = self.receipt(taken["job"])
                interrupted = self.take(taken["state"], activity=activity)
                self.assertEqual(taken["job"]["requestId"], interrupted["cancelRequestId"])
                self.assertIsNone(interrupted["state"]["inFlight"])
                ignored = self.call("OwnedIndexCoordinatorComplete", interrupted["state"], SCOPE,
                                    receipt, body, NOW)
                self.assertFalse(ignored["accepted"])
                resumed = self.take(interrupted["state"])
                self.assertEqual(0, resumed["job"]["offset"])
                self.assertNotEqual(taken["job"]["requestId"], resumed["job"]["requestId"])

    def test_activity_must_explicitly_report_all_three_idle_conditions(self):
        for activity in (None, {}, {"playbackActive": False},
                         {**IDLE, "apiBusy": "false"}):
            self.assertIsNone(self.take(self.start(), activity=activity)["job"])

    def test_scope_change_cancels_on_take_or_complete_and_cannot_restart_old_run(self):
        taken = self.take(self.start())
        receipt, body = self.receipt(taken["job"])
        for field, value in (("provider", "silo"), ("sourceId", "plex:other"),
                             ("profileId", "other"), ("accountId", "other"),
                             ("sessionRevision", 4), ("inventoryRunId", "run-other")):
            changed = {**SCOPE, field: value}
            for outcome in (self.take(taken["state"], scope=changed),
                            self.complete(taken, receipt, body, scope=changed)):
                with self.subTest(field=field, outcome=outcome):
                    self.assertTrue(outcome["state"]["finished"])
                    self.assertEqual("cancelled", outcome["state"]["status"])
                    self.assertTrue(outcome["state"]["partial"])
                    self.assertEqual(taken["job"]["requestId"], outcome["cancelRequestId"])
                    self.assertIsNone(self.take(outcome["state"])["job"])

    def test_cancel_releases_one_flight_and_sanitizes_reason(self):
        taken = self.take(self.start())
        cancelled = self.call("OwnedIndexCoordinatorCancel", taken["state"], "https://fixture.test?token=secret")
        self.assertEqual(taken["job"]["requestId"], cancelled["cancelRequestId"])
        self.assertEqual("cancelled", cancelled["state"]["errorCode"])
        self.assertNotIn("https://", json.dumps(cancelled))
        self.assertIsNone(self.take(cancelled["state"])["job"])

    def test_manifest_expiry_stops_partial_before_another_job(self):
        taken = self.take(self.start())
        done = self.complete(taken)["state"]
        expired = self.take(done, now=NOW + 3600)
        self.assertIsNone(expired["job"])
        self.assertTrue(expired["state"]["finished"])
        self.assertTrue(expired["state"]["partial"])

    def test_real_manifest_quota_stops_before_a_201st_shard_or_4_mib_overflow(self):
        from tests.test_owned_index_manifest import synthetic_manifest

        for count, shard_bytes in ((200, 1000), (63, 65536)):
            with self.subTest(count=count, shard_bytes=shard_bytes):
                state = self.start()
                state["manifest"] = synthetic_manifest(count, shard_bytes)
                state["dispatchedPages"] = count
                state["nextRequestId"] = count + 1
                state["sections"][0].update(pages=count, nextOffset=count * 48, status="scanning")
                self.assertTrue(self.call("OwnedIndexManifestValidate", state["manifest"], SCOPE, NOW)["ok"])
                stopped = self.take(state)
                self.assertIsNone(stopped["job"])
                self.assertTrue(stopped["state"]["partial"])
                self.assertTrue(stopped["state"]["finished"])
                self.assertEqual("manifest_budget", stopped["state"]["errorCode"])
                self.assertEqual(count, stopped["state"]["manifest"]["shardCount"])

    def test_dispatch_attempts_stay_bounded_when_foreground_repeatedly_interrupts(self):
        state = self.start()
        state["dispatchedPages"] = 200
        state["nextRequestId"] = 201
        stopped = self.take(state)
        self.assertIsNone(stopped["job"])
        self.assertTrue(stopped["state"]["partial"])
        self.assertTrue(stopped["state"]["finished"])
        self.assertEqual("page_budget", stopped["state"]["errorCode"])

    def test_policy_has_no_network_storage_nodes_or_scene_credentials_interface(self):
        self.assertTrue(POLICY.is_file(), "owned index scan coordinator is missing")
        source = POLICY.read_text()
        self.assertRegex(source, r"(?i)Task memory")
        self.assertNotRegex(source, r"(?i)\b(HttpRequest|ReadAsciiFile|WriteAsciiFile|DeleteFile|RenameFile|roSGNode|roRegistrySection)\b")
        self.assertRegex(source, r"OwnedIndexManifestQuota\(")
        self.assertRegex(source, r"OwnedIndexManifestAppend\(")


if __name__ == "__main__":
    unittest.main()
