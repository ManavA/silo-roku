"""Retained pointer serialization and restore job validation; legacy Task execution is retired."""

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function
from tests.test_owned_index_policy import ROOT, SESSION, NOW
from tests.test_owned_index_manifest import synthetic_manifest, shard

POINTER = ROOT / "source/core/OwnedIndexPointerPolicy.brs"
FILES = [ROOT / "source/core/OwnedIndexPolicy.brs",
         ROOT / "source/core/OwnedIndexManifestPolicy.brs", POINTER]
PATH = "cachefs:/silo-owned-pointer-v1.json"
URI = "cachefs:/owned-manifest-run-1.json"
SHARD_URI = "cachefs:/owned-run-1-10-0.json"
JOB = {"provider": "plex", "sourceId": SESSION["sourceId"], "profileId": "", "requestId": 701}


def fixture_files(count=1):
    manifest = synthetic_manifest(count)
    files = {PATH: json.dumps({"schema": 1, "inventoryRunId": "run-1"})}
    for index, entry in enumerate(manifest["shards"]):
        body, uri, size = shard(offset=index * 48, item_id=str(index + 100))
        entry["itemIds"] = [str(index + 100)]
        entry["bytes"] = size
        files[uri] = body
    manifest["totalBytes"] = sum(entry["bytes"] for entry in manifest["shards"])
    files[URI] = json.dumps(manifest)
    return files


class OwnedIndexRestoreTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POINTER.is_file(), "owned index pointer policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-pointer-") as directory:
            return run_function(FILES, name, list(args), root=Path(directory))


    def test_pointer_retains_only_schema_and_run_id_and_derives_safe_path(self):
        result = self.call("OwnedIndexPointerCreate", "run-1")
        self.assertTrue(result["ok"])
        self.assertEqual(PATH, result["uri"])
        self.assertEqual({"schema": 1, "inventoryRunId": "run-1"}, json.loads(result["body"]))
        self.assertEqual(len(result["body"].encode()), result["bytes"])
        decoded = self.call("OwnedIndexPointerDecode", result["body"])
        self.assertEqual({"ok": True, "inventoryRunId": "run-1", "manifestUri": URI}, decoded)
        for run_id in ("../outside", "", "x" * 65, "secret?token=1", "run-1.json"):
            self.assertFalse(self.call("OwnedIndexPointerCreate", run_id)["ok"])

    def test_pointer_rejects_extra_fields_alias_duplicates_types_and_utf8_budget(self):
        good = {"schema": 1, "inventoryRunId": "run-1"}
        for patch in ({"schema": True}, {"schema": "1"}, {"schema": 2},
                      {"inventoryRunId": "../bad"}, {"inventoryRunId": None},
                      {"token": "synthetic-private-token"}, {"Schema": 1}):
            self.assertFalse(self.call("OwnedIndexPointerDecode", json.dumps({**good, **patch}))["ok"])
        for body in ("{", "{}", "[]", "x" * 513, "é" * 257):
            self.assertFalse(self.call("OwnedIndexPointerDecode", body)["ok"])
        for path in (PATH, PATH + ".part"):
            self.assertTrue(self.call("OwnedIndexPointerPathAllowed", path))
        for path in (PATH + "/file", PATH + ".other", "tmp:/silo-owned-pointer-v1.json"):
            self.assertFalse(self.call("OwnedIndexPointerPathAllowed", path))

    def test_restore_job_accepts_only_public_scope(self):
        self.assertTrue(self.call("OwnedIndexRestoreValidJob", JOB))
        for patch in ({"provider": "silo"}, {"sourceId": "plex:"}, {"profileId": None},
                      {"requestId": True}, {"token": "secret"}, {"accountId": "private"},
                      {"manifestUri": URI}, {"inventoryRunId": "run-1"}):
            self.assertFalse(self.call("OwnedIndexRestoreValidJob", {**JOB, **patch}))


if __name__ == "__main__":
    unittest.main()
