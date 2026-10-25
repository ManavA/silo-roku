"""Real one-page owned inventory policy; fixture titles and credentials are synthetic."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/OwnedIndexPolicy.brs"
FIXTURE = ROOT / "tests/fixtures/owned_index/plex_page.json"
JOB = {"provider": "plex", "sourceId": "plex:fixture-server", "profileId": "",
       "inventoryRunId": "run-1", "libraryId": "10", "offset": 0,
       "limit": 48, "requestId": 1}
SESSION = {"sourceId": JOB["sourceId"], "profileId": "", "accountId": "fixture-account",
           "baseUrl": "https://server.example.test", "token": "synthetic-private-token",
           "accountToken": "synthetic-private-account", "clientId": "fixture-client"}
NOW = 1791882000


class OwnedIndexPolicyTests(unittest.TestCase):
    def call(self, function, arguments):
        self.assertTrue(POLICY.is_file(), "owned inventory page policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-policy-") as directory:
            return run_function(POLICY, function, arguments, root=Path(directory))

    def decode(self, value=None, job=None):
        if value is None:
            value = json.loads(FIXTURE.read_text())
        return self.call("OwnedIndexDecodePage", [job or JOB, json.dumps(value)])

    def test_one_page_is_compact_and_advances_by_raw_slots_including_filtered_cards(self):
        result = self.decode()
        self.assertTrue(result["ok"])
        page = result["page"]
        self.assertEqual(3, page["rawCount"])
        self.assertEqual(3, page["nextOffset"])
        self.assertTrue(page["hasMore"])
        self.assertFalse(page["pageTerminal"])
        self.assertEqual(["100", "102"], [record["itemId"] for record in page["records"]])
        self.assertEqual({"itemId", "type", "title", "year", "tmdbId", "imdbId", "tvdbId"},
                         set(page["records"][0]))
        self.assertEqual("1000", page["records"][0]["tmdbId"])
        self.assertEqual("tt12345", page["records"][0]["imdbId"])
        self.assertTrue(page["externalIdsComplete"])
        self.assertNotIn("synthetic-private", json.dumps(result))
        self.assertNotIn("/library/", json.dumps(result))
        self.assertNotIn("complete", result)

    def test_unknown_total_full_page_requires_one_more_job(self):
        items = [{"ratingKey": str(index), "type": "movie", "title": "Synthetic"}
                 for index in range(48)]
        page = self.decode({"MediaContainer": {"offset": 48, "size": 48, "Metadata": items}},
                           {**JOB, "offset": 48})["page"]
        self.assertTrue(page["hasMore"])
        self.assertEqual(96, page["nextOffset"])
        self.assertFalse(page["totalKnown"])
        self.assertFalse(page["externalIdsComplete"])

    def test_short_unknown_total_and_authoritative_empty_page_are_terminal_pages(self):
        for container in ({"offset": 0, "size": 0, "totalSize": 0, "Metadata": []},
                          {"offset": 0, "size": 0, "Metadata": []}):
            with self.subTest(container=container):
                page = self.decode({"MediaContainer": container})["page"]
                self.assertTrue(page["pageTerminal"])
                self.assertFalse(page["hasMore"])
                self.assertEqual(-1, page["nextOffset"])
                self.assertNotIn("inventoryComplete", page)

    def test_oversized_raw_page_and_response_bytes_are_rejected_without_truncation(self):
        value = json.loads(FIXTURE.read_text())
        value["MediaContainer"]["Metadata"] = value["MediaContainer"]["Metadata"][:1] * 49
        self.assertEqual("page_budget", self.decode(value)["errorCode"])
        self.assertEqual("response_too_large", self.call("OwnedIndexDecodePage", [JOB, "x" * 262145])["errorCode"])
        self.assertEqual("response_too_large", self.call("OwnedIndexDecodePage", [JOB, "é" * 131073])["errorCode"])

    def test_inconsistent_or_malformed_pagination_never_proves_completion(self):
        values = [{"offset": 1}, {"offset": "0x"}, {"offset": None}, {"size": None}, {"totalSize": None}, {"size": 4}, {"totalSize": 2},
                  {"totalSize": "broken"}, {"Metadata": None}, {"Metadata": {}},
                  {"Metadata": [], "size": 0, "totalSize": 20}, {"offset": -1}]
        for patch in values:
            with self.subTest(patch=patch):
                value = json.loads(FIXTURE.read_text())
                value["MediaContainer"].update(patch)
                result = self.decode(value)
                self.assertFalse(result["ok"])
                self.assertNotIn("page", result)

    def test_malformed_supported_records_conflicts_duplicates_and_missing_identity_fail_closed(self):
        raw = json.loads(FIXTURE.read_text())["MediaContainer"]["Metadata"][0]
        variants = [{"ratingKey": ""}, {"title": ""}, {"title": "x" * 257}, {"title": "Bad\nTitle"},
                    {"year": "unknown"}, {"Guid": "tmdb://1"},
                    {"Guid": [{"id": "tmdb://1"}, {"id": "tmdb://2"}]}]
        for patch in variants:
            with self.subTest(patch=patch):
                value = {"MediaContainer": {"offset": 0, "size": 1, "totalSize": 1,
                                           "Metadata": [{**raw, **patch}]}}
                self.assertFalse(self.decode(value)["ok"])
        duplicate = {"MediaContainer": {"size": 2, "totalSize": 2, "Metadata": [raw, raw]}}
        self.assertEqual("duplicate_identity", self.decode(duplicate)["errorCode"])
        self.assertFalse(self.decode({"MediaContainer": {"Metadata": [None]}})["ok"])

    def test_missing_external_ids_are_tracked_separately_from_terminal_page(self):
        item = {"ratingKey": "1", "type": "movie", "title": "Synthetic"}
        page = self.decode({"MediaContainer": {"Metadata": [item], "size": 1, "totalSize": 1}})["page"]
        self.assertTrue(page["pageTerminal"])
        self.assertFalse(page["externalIdsComplete"])

    def test_job_accepts_explicit_empty_plex_profile_but_rejects_unbounded_or_private_input(self):
        self.assertTrue(self.call("OwnedIndexValidJob", [JOB]))
        for patch in ({"provider": "silo"}, {"sourceId": ""}, {"profileId": None},
                      {"limit": 49}, {"offset": -1}, {"offset": 1.5}, {"offset": 2147483600},
                      {"inventoryRunId": "../unsafe"}, {"libraryId": "../unsafe"},
                      {"requestId": None}, {"writeShard": "yes"}, {"token": "private"}):
            with self.subTest(patch=patch):
                self.assertFalse(self.call("OwnedIndexValidJob", [{**JOB, **patch}]))
        missing = copy.deepcopy(JOB)
        missing.pop("profileId")
        self.assertFalse(self.call("OwnedIndexValidJob", [missing]))

    def test_session_matching_checks_account_revision_and_credentials_inside_task(self):
        self.assertTrue(self.call("OwnedIndexSessionMatches", [JOB, SESSION, SESSION, 3, 3]))
        for patch in ({"accountId": "different"}, {"sourceId": "plex:other"},
                      {"profileId": "other"}, {"baseUrl": "https://other.example.test"},
                      {"token": "changed"}, {"accountToken": "changed"}):
            self.assertFalse(self.call("OwnedIndexSessionMatches", [JOB, SESSION, {**SESSION, **patch}, 3, 3]))
        self.assertFalse(self.call("OwnedIndexSessionMatches", [JOB, SESSION, SESSION, 3, 4]))

    def test_registry_and_native_literal_key_case_do_not_break_scoped_work(self):
        stored = {key.lower(): value for key, value in SESSION.items()}
        native_job = {key.lower(): value for key, value in JOB.items()}
        self.assertTrue(self.call("OwnedIndexValidJob", [native_job]))
        self.assertTrue(self.call("OwnedIndexSessionMatches", [JOB, stored, stored, 3, 3]))
        self.assertTrue(self.call("OwnedIndexDecodePage", [native_job, FIXTURE.read_text()])["ok"])

    def test_shard_schema_has_scope_expiry_raw_offsets_and_no_credentials(self):
        page = self.decode()["page"]
        result = self.call("OwnedIndexShard", [JOB, page, SESSION, 3, NOW])
        self.assertTrue(result["ok"])
        self.assertLessEqual(result["bytes"], 65536)
        self.assertEqual("cachefs:/owned-run-1-10-0.json", result["uri"])
        data = json.loads(result["body"])
        self.assertEqual("fixture-account", data["accountId"])
        self.assertEqual(3, data["sessionRevision"])
        self.assertEqual(NOW + 3600, data["expiresAt"])
        self.assertEqual(3, data["rawCount"])
        self.assertNotIn("synthetic-private", result["body"])
        self.assertTrue(self.call("OwnedIndexValidateShard", [result["body"], JOB, SESSION, 3, NOW])["ok"])
        self.assertFalse(self.call("OwnedIndexValidateShard", [result["body"], JOB, SESSION, 3, NOW + 3601])["ok"])
        self.assertFalse(self.call("OwnedIndexValidateShard", [result["body"], JOB, SESSION, 4, NOW])["ok"])

    def test_shard_readback_rejects_extra_fields_records_scope_and_limits(self):
        page = self.decode()["page"]
        good = json.loads(self.call("OwnedIndexShard", [JOB, page, SESSION, 3, NOW])["body"])
        for change in ("extra", "record", "scope", "count", "record_limit"):
            bad = copy.deepcopy(good)
            if change == "extra": bad["token"] = "private"
            if change == "record": bad["records"][0]["url"] = "https://private.example.test"
            if change == "scope": bad["accountId"] = "other"
            if change == "count": bad["rawCount"] = 0
            if change == "record_limit": bad["records"] = bad["records"][:1] * 49
            with self.subTest(change=change):
                self.assertFalse(self.call("OwnedIndexValidateShard", [json.dumps(bad), JOB, SESSION, 3, NOW])["ok"])
        self.assertFalse(self.call("OwnedIndexValidateShard", ["x" * 65537, JOB, SESSION, 3, NOW])["ok"])

    def test_persisted_numeric_strings_fail_without_throwing(self):
        page = self.decode()["page"]
        good = json.loads(self.call("OwnedIndexShard", [JOB, page, SESSION, 3, NOW])["body"])
        for field in ("offset", "pageSize", "rawCount", "totalSize", "nextOffset",
                      "schema", "sessionRevision", "createdAt", "expiresAt"):
            with self.subTest(field=field):
                bad = copy.deepcopy(good)
                bad[field] = str(bad[field])
                result = self.call("OwnedIndexValidateShard", [json.dumps(bad), JOB, SESSION, 3, NOW])
                self.assertFalse(result["ok"])
        bad = copy.deepcopy(good)
        bad["records"][0]["year"] = str(bad["records"][0]["year"])
        self.assertFalse(self.call("OwnedIndexValidateShard", [json.dumps(bad), JOB, SESSION, 3, NOW])["ok"])


if __name__ == "__main__":
    unittest.main()
