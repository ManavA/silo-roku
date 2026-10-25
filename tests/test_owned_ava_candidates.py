"""Bounded positive AVA facts from the private Plex cache, without native I/O."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.brightscript import run_function
from tests.test_owned_shard_search import (
    INDEX, MANIFEST, NOW, RANKING, ROOT,
    SESSION, inventory, record,
)


POLICY = ROOT / "source/core/OwnedAvaCandidatePolicy.brs"
JOB = {"sourceId": SESSION["sourceId"], "profileId": "", "requestId": 7,
       "manifestUri": "cachefs:/owned-manifest-run-1.json"}
SCRIPTS = [INDEX, MANIFEST, RANKING, ROOT / "source/core/OwnedShardSearchPolicy.brs",
           ROOT / "source/adapters/MetadataAdapter.brs",
           ROOT / "source/core/MetadataUiPolicy.brs", POLICY]


class OwnedAvaCandidateTests(unittest.TestCase):
    def call(self, function, *arguments):
        self.assertTrue(POLICY.is_file(), "owned AVA candidate policy is missing")
        with tempfile.TemporaryDirectory(prefix="silo-owned-ava-policy-") as directory:
            return run_function(SCRIPTS, function, list(arguments), root=Path(directory))


    def test_job_accepts_only_public_scope_and_a_valid_inventory_manifest(self):
        self.assertTrue(self.call("OwnedAvaCandidateValidJob", JOB))
        for patch in ({"profileId": None}, {"profileId": "../owner"}, {"requestId": -1},
                      {"sourceId": "silo:server"}, {"sourceId": "plex:"},
                      {"manifestUri": "tmp:/owned-manifest-run-1.json"},
                      {"manifestUri": "cachefs:/owned-manifest-../run-1.json"},
                      {"prompt": "drama"}, {"token": "secret"}, {"accountId": "private"}):
            with self.subTest(patch=patch):
                self.assertFalse(self.call("OwnedAvaCandidateValidJob", {**JOB, **patch}))
        missing = dict(JOB)
        missing.pop("profileId")
        self.assertFalse(self.call("OwnedAvaCandidateValidJob", missing))

    def test_policy_validates_public_job_with_packaged_dependencies(self):
        self.assertTrue(run_function(SCRIPTS, "OwnedAvaCandidateValidJob", [JOB]))


    def test_small_inventory_preserves_shows_and_title_only_facts_with_bounded_fields(self):
        show = {**record("101", " S" * 100, 5000), "type": "show", "tmdbId": "",
                "imdbId": "", "tvdbId": ""}
        state = self.call("OwnedAvaCandidateState", JOB["sourceId"], 2)
        state = self.call("OwnedAvaCandidateAccumulate", state, [record(), show])
        self.assertFalse(state["invalidRecord"])
        self.assertEqual(2, len(state["items"]))
        self.assertEqual(("show", 120, 0, ""), (state["items"][1]["type"],
                         len(state["items"][1]["title"]), state["items"][1]["year"],
                         state["items"][1]["tmdbId"]))

    def test_accumulator_rejects_forged_private_record_fields_and_oversized_pages(self):
        state = self.call("OwnedAvaCandidateState", JOB["sourceId"], 1)
        for records in ([{**record(), "url": "https://private.example/stream"}], [record()] * 49):
            with self.subTest(count=len(records)):
                result = self.call("OwnedAvaCandidateAccumulate", copy.deepcopy(state), records)
                self.assertTrue(result["invalidRecord"])
                self.assertEqual([], result["items"])


if __name__ == "__main__":
    unittest.main()
