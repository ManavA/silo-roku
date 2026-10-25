"""Retained pure cache-purge job and path policies; legacy Task execution is retired."""

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "source/core/OwnedIndexPurgePolicy.brs"
JOB = {"requestId": 70}
SHARD = "owned-run-1-10-0.json"
MANIFEST = "owned-manifest-run-1.json"


def file_stat(kind="file"):
    return {"type": kind, "size": 120, "permissions": "rw"}


def fixture_files(names):
    return {"cachefs:/" + name: file_stat() for name in names if isinstance(name, str)}


class OwnedIndexPurgeTests(unittest.TestCase):
    def call(self, function, *arguments):
        self.assertTrue(POLICY.is_file(), "owned-index purge policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-purge-policy-") as directory:
            return run_function(POLICY, function, list(arguments), root=Path(directory))


    def test_job_accepts_only_one_bounded_numeric_request_id(self):
        for request_id in (0, 70, 2147483647):
            self.assertTrue(self.call("OwnedIndexPurgeValidJob", {"requestId": request_id}))
        for job in ({}, None, [], {"requestId": True}, {"requestId": "70"}, {"requestId": -1},
                    {"requestId": 0.5}, {"requestId": 2147483648}, {"requestId": 70, "path": SHARD},
                    {"requestId": 70, "accountId": "synthetic-account"}, {"requestId": 70, "token": "synthetic-private"}):
            with self.subTest(job=job):
                self.assertFalse(self.call("OwnedIndexPurgeValidJob", job))

    def test_only_canonical_owned_index_root_names_produce_paths(self):
        names = [SHARD, SHARD + ".part", MANIFEST, MANIFEST + ".part",
                 "owned-a_b-c_d-2147483599.json", "owned-manifest-a_b.json",
                 "owned-run-1-10--1.json"]  # A library identifier may end in '-'.
        for name in names:
            self.assertEqual("cachefs:/" + name, self.call("OwnedIndexPurgePath", name))
        for name in (None, 1, {}, "", "private.json", "owned-private.json", "owned-manifest-.json",
                     "owned-run-1-10-0.json.part.part", "owned-run-1-10-.json", "owned-run-1-10-1.0.json",
                     "owned-" + "x" * 65 + "-10-0.json", "owned-manifest-" + "x" * 65 + ".json",
                     "../" + SHARD, "cachefs:/" + SHARD, "tmp:/" + SHARD, SHARD + "/private",
                     SHARD + "\n", SHARD + " ", "owned-manifest-a\\b.json", "owned-manifest-%2e%2e.json"):
            with self.subTest(name=name):
                self.assertEqual("", self.call("OwnedIndexPurgePath", name))

    def test_path_guard_rejects_other_roots_extra_segments_and_trailing_controls(self):
        for name in (SHARD, MANIFEST, SHARD + ".part", MANIFEST + ".part"):
            self.assertTrue(self.call("OwnedIndexPurgePathAllowed", "cachefs:/" + name))
        for path in ("tmp:/" + SHARD, "cachefs://" + SHARD, "cachefs:/../" + SHARD,
                     "cachefs:/nested/" + SHARD, "cachefs:/" + SHARD + "\n", "cachefs:/private.json"):
            self.assertFalse(self.call("OwnedIndexPurgePathAllowed", path))


if __name__ == "__main__":
    unittest.main()
