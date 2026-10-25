"""Retained inventory scan policies and HTTP response byte limits, without Task I/O."""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

from tools.brightscript import run_function
from tests.test_owned_index_policy import ROOT, SESSION

POLICY = ROOT / "source/core/OwnedIndexScanPolicy.brs"
FILES = [ROOT / "source/core/ServerUrlPolicy.brs", ROOT / "source/auth/SessionPolicy.brs",
         ROOT / "source/adapters/PlexAdapter.brs", ROOT / "source/core/OwnedIndexPolicy.brs",
         ROOT / "source/core/OwnedIndexManifestPolicy.brs", ROOT / "source/core/OwnedIndexCoordinatorPolicy.brs",
         ROOT / "source/core/OwnedIndexPointerPolicy.brs", POLICY]
JOB = {"provider": "plex", "sourceId": "plex:fixture-server", "profileId": "",
       "requestId": 700, "inventoryRunId": "scan-fixture-1"}


def response(container):
    return {"ok": True, "statusCode": 200, "body": json.dumps({"MediaContainer": container})}


def sections(count=1):
    return response({"Directory": [{"key": str(10 + index), "type": "movie", "title": "Synthetic private library"}
                                   for index in range(count)]})


def page(offset=0, count=1, total=None, item_id=100):
    container = {"offset": offset, "size": count,
                 "Metadata": [{"ratingKey": str(item_id + index), "type": "movie", "title": "Synthetic private title",
                               "Guid": [{"id": "tmdb://1000"}]} for index in range(count)]}
    if total is not None:
        container["totalSize"] = total
    return response(container)


class OwnedIndexScannerTests(unittest.TestCase):
    def call(self, function, *arguments):
        self.assertTrue(POLICY.is_file(), "owned scan policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-scan-policy-") as directory:
            return run_function(FILES, function, list(arguments), root=Path(directory))


    def test_http_body_limit_is_per_request_and_utf8_bytes_without_changing_default(self):
        http = ROOT / "source/network/Http.brs"
        with tempfile.TemporaryDirectory(prefix="silo-owned-http-") as directory:
            def call(request, body):
                return run_function(http, "HttpResponse", [request, 200, body], root=Path(directory))
            self.assertFalse(call({"responseBodyLimit": 262144}, "é" * 131073)["ok"])
            self.assertEqual("response_too_large", call({"responseBodyLimit": 262144}, "x" * 262145)["errorCode"])
            self.assertTrue(call({}, "x" * 262145)["ok"])
            self.assertTrue(call({"responseBodyLimit": 0}, "x" * 262145)["ok"])


    def test_job_has_exact_public_scope_and_no_private_or_page_parameters(self):
        self.assertTrue(self.call("OwnedIndexScanValidJob", JOB))
        for patch in ({"provider": "silo"}, {"inventoryRunId": "../bad"}, {"profileId": None},
                      {"requestId": None}, {"sourceId": "plex:"}, {"token": "secret"},
                      {"accountId": "account"}, {"libraryId": "10"}, {"offset": 0}):
            with self.subTest(patch=patch):
                self.assertFalse(self.call("OwnedIndexScanValidJob", {**JOB, **patch}))
        bad = dict(JOB)
        bad.pop("profileId")
        self.assertFalse(self.call("OwnedIndexScanValidJob", bad))

    def test_discovery_retains_only_movie_show_ids_and_bounds_and_truncates_at_24(self):
        for count in (0, 23, 24, 25):
            body = sections(count)["body"]
            result = self.call("OwnedIndexScanDecodeSections", body)
            self.assertTrue(result["ok"])
            self.assertEqual(min(count, 24), len(result["discovery"]["sections"]))
            self.assertEqual(count >= 24, result["discovery"]["truncated"])
            self.assertNotIn("Synthetic private", json.dumps(result))
        mixed = response({"Directory": [{"key": "music", "type": "artist"}, {"key": "20", "type": "show"}]})
        self.assertEqual([{"libraryId": "20", "type": "show"}], self.call("OwnedIndexScanDecodeSections", mixed["body"])["discovery"]["sections"])

    def test_invalid_discovery_and_byte_ceiling_fail_without_truncating_wire_text(self):
        for body in ("{", json.dumps({"MediaContainer": {"Directory": None}}),
                     response({"Directory": [{"key": "../unsafe", "type": "movie"}]})["body"],
                     response({"Directory": [{"key": "10", "type": "movie"}] * 2})["body"],
                     "x" * 262145, "é" * 131073):
            with self.subTest(length=len(body)):
                self.assertFalse(self.call("OwnedIndexScanDecodeSections", body)["ok"])


    def test_run_uniqueness_checks_bounded_string_entries_without_mutating_existing_files(self):
        self.assertIn("function OwnedIndexScanRunDirectoryUnused(", POLICY.read_text())
        self.assertTrue(self.call("OwnedIndexScanRunDirectoryUnused", JOB["inventoryRunId"], []))
        self.assertTrue(self.call("OwnedIndexScanRunDirectoryUnused", JOB["inventoryRunId"], ["private.json", "owned-other-10-0.json"]))
        for listing in (["private.json"] * 513, [None], [{}], ["owned-manifest-scan-fixture-1.json"], ["owned-scan-fixture-1-10-0.json.part"]):
            self.assertFalse(self.call("OwnedIndexScanRunDirectoryUnused", JOB["inventoryRunId"], listing))

    def test_native_file_type_policy_rejects_directories_and_malformed_stat(self):
        self.assertIn("function OwnedIndexScanRegularFile(", POLICY.read_text())
        self.assertTrue(self.call("OwnedIndexScanRegularFile", {"type":"file","size":1}))
        for stat in ({"type":"directory","size":1},{"size":1},None,{}):
            self.assertFalse(self.call("OwnedIndexScanRegularFile", stat))

    def test_paths_are_exact_owned_names_and_manifest_and_shard_limits_differ(self):
        for path in ("cachefs:/owned-run-10-0.json", "cachefs:/owned-run-10-0.json.part", "cachefs:/owned-manifest-run.json", "cachefs:/owned-manifest-run.json.part"):
            self.assertTrue(self.call("OwnedIndexScanPathAllowed",path))
        for path in ("cachefs:/private.json", "cachefs:/owned-../10.json", "cachefs:/owned-manifest-run.json/other", "tmp:/owned-run-10-0.json"):
            self.assertFalse(self.call("OwnedIndexScanPathAllowed",path))
        self.assertEqual(131072,self.call("OwnedIndexScanFileLimit","cachefs:/owned-manifest-run.json"))
        self.assertEqual(65536,self.call("OwnedIndexScanFileLimit","cachefs:/owned-run-10-0.json"))


if __name__ == "__main__":
    unittest.main()
